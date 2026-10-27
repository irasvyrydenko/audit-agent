"""LLM risk classifier: batched multi-label JSON classification (D-013).

One call labels up to `batch_size` paragraphs. Paragraphs are numbered 1..n in the prompt and
mapped back to their ids. A batch whose answer is truncated, unparsable or incomplete is split
in half and retried; a single paragraph that still fails gets no prediction (logged by caller).
Rate-limit errors are re-raised immediately.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from audit_agent.common.citations import Citation
from audit_agent.common.config import RiskDetectorSettings, Settings
from audit_agent.common.llm_client import LLMClient, LLMError, LLMRateLimitError
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.labels import RiskPrediction

NONE_LABEL = "none"

SYSTEM_PROMPT = (
    "You classify paragraphs from the Risk Factors section of SEC 10-K filings into risk "
    "categories. Answer with JSON only."
)


def select_paragraphs(
    paragraphs: Iterable[Paragraph], settings: RiskDetectorSettings
) -> list[Paragraph]:
    """Text paragraphs of the configured Items with at least `min_words` words."""
    return [
        p
        for p in paragraphs
        if p.kind == "text"
        and p.item in settings.items
        and len(p.text.split()) >= settings.min_words
    ]


def truncate_words(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]) + " ..."


def build_messages(
    paragraphs: list[Paragraph], definitions: dict[str, str], max_words: int
) -> list[dict[str, str]]:
    label_lines = "\n".join(f"- {name}: {desc}" for name, desc in definitions.items())
    numbered = "\n\n".join(
        f"[{i}] {truncate_words(p.text, max_words)}" for i, p in enumerate(paragraphs, start=1)
    )
    user = (
        f"Categories:\n{label_lines}\n\n"
        "Rules:\n"
        "- A paragraph can have several categories; pick every category that is a main topic "
        "of the paragraph, not one that is only mentioned in passing.\n"
        f'- Use ["{NONE_LABEL}"] alone when no category applies.\n'
        "- Use only the category names listed above.\n"
        f"- Return one result for every paragraph id from 1 to {len(paragraphs)}.\n\n"
        'Output format: {"results": [{"id": 1, "labels": ["litigation"]}, ...]}\n\n'
        f"Paragraphs:\n\n{numbered}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def clean_labels(raw: Any, allowed: list[str]) -> list[str]:
    """Keep allowed labels in config order; 'none' only when nothing else is left."""
    given = {str(label).strip().lower() for label in raw} if isinstance(raw, list) else set()
    risks = [label for label in allowed if label in given and label != NONE_LABEL]
    return risks or [NONE_LABEL]


def parse_results(answer: Any, n: int) -> dict[int, Any]:
    """{1-based id: raw labels}; raises LLMError if any id is missing."""
    results = answer.get("results") if isinstance(answer, dict) else None
    if not isinstance(results, list):
        raise LLMError("answer has no 'results' list")
    by_id: dict[int, Any] = {}
    for item in results:
        if isinstance(item, dict) and isinstance(item.get("id"), int | str):
            try:
                by_id[int(item["id"])] = item.get("labels")
            except ValueError:
                continue
    missing = set(range(1, n + 1)) - set(by_id)
    if missing:
        raise LLMError(f"answer misses ids {sorted(missing)[:5]}")
    return by_id


def to_prediction(paragraph: Paragraph, labels: list[str]) -> RiskPrediction:
    return RiskPrediction(
        paragraph_id=paragraph.id,
        labels=labels,
        scores={label: 1.0 for label in labels},  # LLM gives no calibrated probabilities
        method="llm",
        citation=Citation(source_type="section", ref=paragraph.id),
    )


def classify_batch(
    batch: list[Paragraph],
    labels: list[str],
    definitions: dict[str, str],
    client: LLMClient,
    max_words: int,
    on_error: Callable[[Paragraph, str], None] | None = None,
) -> list[RiskPrediction]:
    """Classify one batch; split in half on failure."""
    try:
        answer = client.complete_json(build_messages(batch, definitions, max_words))
        by_id = parse_results(answer, len(batch))
    except LLMRateLimitError:
        raise  # quota exhausted: splitting would only burn more failed calls
    except LLMError as exc:
        if len(batch) == 1:
            if on_error:
                on_error(batch[0], str(exc))
            return []
        mid = len(batch) // 2
        return [
            *classify_batch(batch[:mid], labels, definitions, client, max_words, on_error),
            *classify_batch(batch[mid:], labels, definitions, client, max_words, on_error),
        ]
    return [to_prediction(p, clean_labels(by_id[i], labels)) for i, p in enumerate(batch, start=1)]


def classify_paragraphs(
    paragraphs: list[Paragraph],
    labels: list[str],
    client: LLMClient,
    definitions: dict[str, str],
    settings: RiskDetectorSettings,
    on_error: Callable[[Paragraph, str], None] | None = None,
) -> list[RiskPrediction]:
    """Classify the given paragraphs (callers usually pass `select_paragraphs(...)`)."""
    predictions: list[RiskPrediction] = []
    size = settings.batch_size
    for start in range(0, len(paragraphs), size):
        batch = paragraphs[start : start + size]
        predictions += classify_batch(
            batch, labels, definitions, client, settings.max_words, on_error
        )
    return predictions


def detect_risks(
    paragraphs: Iterable[Paragraph],
    client: LLMClient,
    settings: Settings,
    on_error: Callable[[Paragraph, str], None] | None = None,
) -> list[RiskPrediction]:
    """Pipeline entry: select paragraphs per config, classify, return predictions."""
    selected = select_paragraphs(paragraphs, settings.risk_detector)
    return classify_paragraphs(
        selected,
        settings.risk_labels,
        client,
        settings.risk_label_definitions,
        settings.risk_detector,
        on_error,
    )
