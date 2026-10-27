"""MD&A claim extraction with the LLM (D-016).

Candidate paragraphs are picked by code (metric keyword + number or direction word), at most
`max_candidates` per filing, `batch_size` per call. The LLM returns the number and unit as
written; scaling to base units is done in code (no LLM scale errors). A claim whose quote is
not found in its paragraph is dropped.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from audit_agent.common.config import ConsistencySettings
from audit_agent.common.llm_client import LLMClient, LLMError, LLMRateLimitError
from audit_agent.consistency_checker.checker import SUPPORTED_METRICS, Claim
from audit_agent.filing_loader.loader import Paragraph

METRIC_DESCRIPTIONS = {
    "revenue": "total company revenue / net sales / total net revenue",
    "cost_of_revenue": "total cost of sales / cost of revenue",
    "operating_income": "total operating income",
    "pretax_income": "income / earnings before income taxes",
    "net_income": "net income attributable to the company's shareholders",
    "net_income_incl_nci": "consolidated net income including noncontrolling interests",
    "operating_cash_flow": "cash provided by operating activities",
    "cash": "cash and cash equivalents",
    "total_debt": "total debt / borrowings",
    "total_assets": "total assets",
    "stockholders_equity": "total shareholders' equity",
    "gross_margin": "gross margin / gross profit as a percentage of revenue or net sales",
    "operating_margin": "operating income as a percentage of revenue or net sales",
    "net_margin": "net income as a percentage of revenue",
    "pretax_margin": "income before taxes as a percentage of revenue or sales",
}
UNIT_SCALE = {
    "usd_billion": 1e9,
    "usd_million": 1e6,
    "usd_thousand": 1e3,
    "usd": 1.0,
    "percent": 0.01,
    "percentage_points": 0.01,
    "basis_points": 1e-4,
}
KINDS = ("level", "change_pct", "change_abs", "change_pp", "direction")
SYSTEM_PROMPT = (
    "You extract verifiable quantitative claims from the MD&A section of SEC 10-K filings. "
    "Answer with JSON only."
)
_KEYWORDS = re.compile(
    r"\b(net sales|revenues?|net revenue|sales|net income|net earnings|earnings|operating income|"
    r"gross (?:margin|profit)|cash (?:and cash equivalents|provided by|generated|flows?)|debt|"
    r"borrowings|total assets|equity)\b",
    re.I,
)
_SIGNAL = re.compile(r"\d|\b(increas|decreas|grew|rose|declin|flat|higher|lower|up|down)", re.I)


def select_candidates(
    paragraphs: Iterable[Paragraph], settings: ConsistencySettings
) -> list[Paragraph]:
    out = [
        p
        for p in paragraphs
        if p.kind == "text"
        and p.item in settings.items
        and _KEYWORDS.search(p.text)
        and _SIGNAL.search(p.text)
        and re.search(r"\d", p.text)
    ]
    return out[: settings.max_candidates]


def build_messages(paragraphs: list[Paragraph], fiscal_year: int) -> list[dict[str, str]]:
    metrics = "\n".join(f"- {k}: {v}" for k, v in METRIC_DESCRIPTIONS.items())
    numbered = "\n\n".join(f"[{i}] {p.text}" for i, p in enumerate(paragraphs, start=1))
    user = (
        f"The filing covers fiscal year {fiscal_year}. "
        f"Extract claims about these metrics:\n{metrics}\n\n"
        "For each claim return: paragraph (number), quote (exact words copied from the paragraph), "
        'metric (one name from the list, or null), scope ("company" for company-wide totals, '
        '"segment" for a segment, product, region or business line), fiscal_year (the year the '
        "claim is about), kind (level = value of the metric; change_pct = percent change; "
        "change_abs = change in money; change_pp = change of a percentage in percentage or basis "
        "points; direction = only up/down/flat), direction (up/down/flat or null), number (as "
        "written, without sign, or null), unit (usd_billion, usd_million, usd_thousand, usd, "
        "percent, percentage_points, basis_points, or null).\n"
        "One claim per number; skip per-share amounts and non-GAAP measures.\n\n"
        'Output format: {"claims": [{"paragraph": 1, "quote": "...", "metric": "net_income", '
        '"scope": "company", "fiscal_year": 2024, "kind": "level", "direction": null, '
        '"number": 58.5, "unit": "usd_billion"}]}\n\n'
        f"Paragraphs:\n\n{numbered}"
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def _normalize(text: str) -> str:
    return (
        re.sub(r"\s+", " ", text.replace("’", "'").replace("“", '"').replace("”", '"'))
        .strip()
        .lower()
    )


def _to_claim(item: dict[str, Any], paragraphs: list[Paragraph], claim_id: str) -> Claim | None:
    try:
        paragraph = paragraphs[int(item["paragraph"]) - 1]
    except (KeyError, ValueError, TypeError, IndexError):
        return None
    quote = str(item.get("quote") or "").strip()
    if not quote or _normalize(quote) not in _normalize(paragraph.text):
        return None  # hallucinated or paraphrased quote
    kind = item.get("kind") if item.get("kind") in KINDS else "direction"
    unit, number = item.get("unit"), item.get("number")
    value = None
    if isinstance(number, int | float) and unit in UNIT_SCALE:
        value = abs(float(number)) * UNIT_SCALE[unit]
    metric = item.get("metric") if item.get("metric") in SUPPORTED_METRICS else None
    direction = item.get("direction") if item.get("direction") in ("up", "down", "flat") else None
    year = item.get("fiscal_year")
    as_written = None
    if value is not None:
        as_written = f"{number} {unit.replace('usd_', '').replace('_', ' ')}"
    return Claim(
        id=claim_id,
        paragraph_id=paragraph.id,
        text=quote,
        metric=metric,
        scope="segment" if item.get("scope") == "segment" else "company",
        fiscal_year=year if isinstance(year, int) else None,
        kind=kind,  # type: ignore[arg-type]
        direction=direction,  # type: ignore[arg-type]
        value=value,
        as_written=as_written,
    )


def parse_claims(answer: Any, paragraphs: list[Paragraph], prefix: str) -> list[Claim]:
    raw = answer.get("claims") if isinstance(answer, dict) else None
    if not isinstance(raw, list):
        raise LLMError("answer has no 'claims' list")
    claims = []
    for item in raw:
        if isinstance(item, dict) and (
            claim := _to_claim(item, paragraphs, f"{prefix}{len(claims) + 1}")
        ):
            claims.append(claim)
    return claims


def extract_claims(
    paragraphs: Iterable[Paragraph],
    fiscal_year: int,
    client: LLMClient,
    settings: ConsistencySettings,
) -> tuple[list[Claim], int]:
    """Claims from MD&A candidates and the number of failed batches (rate limits re-raised)."""
    candidates = select_candidates(paragraphs, settings)
    claims: list[Claim] = []
    failed = 0
    for start in range(0, len(candidates), settings.batch_size):
        batch = candidates[start : start + settings.batch_size]
        try:
            answer = client.complete_json(build_messages(batch, fiscal_year))
            claims += parse_claims(answer, batch, prefix=f"c{start // settings.batch_size + 1}-")
        except LLMRateLimitError:
            raise
        except LLMError:
            failed += 1
    return claims, failed
