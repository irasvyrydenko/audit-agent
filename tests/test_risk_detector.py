"""risk_detector tests: paragraph selection, prompt, label cleaning, batching and split-retry
with a fake LLM client (no network)."""

from __future__ import annotations

import json
import re
from typing import Any

from audit_agent.common.config import RiskDetectorSettings, load_settings
from audit_agent.common.llm_client import LLMError, LLMRateLimitError
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.llm_classifier import (
    build_messages,
    classify_paragraphs,
    clean_labels,
    detect_risks,
    parse_results,
    select_paragraphs,
    truncate_words,
)

LABELS = ["litigation", "cybersecurity", "none"]
DEFS = {"litigation": "lawsuits", "cybersecurity": "breaches", "none": "nothing"}
SETTINGS = RiskDetectorSettings(items=["1A"], min_words=3, max_words=50, batch_size=4)


def para(i: int, text: str = "", item: str = "1A", kind: str = "text") -> Paragraph:
    body = text or f"paragraph number {i} about a cyber breach"
    return Paragraph(id=f"item_{item}:p{i}", item=item, index=i, kind=kind, text=body)


class FakeClient:
    """Answers by keyword; can fail for batches larger than `fail_above`."""

    def __init__(self, fail_above: int | None = None, drop_id: int | None = None) -> None:
        self.calls: list[int] = []
        self.fail_above = fail_above
        self.drop_id = drop_id

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        user = messages[-1]["content"]
        items = re.findall(r"^\[(\d+)\] (.*)$", user, flags=re.MULTILINE)
        self.calls.append(len(items))
        if self.fail_above is not None and len(items) > self.fail_above:
            raise LLMError("truncated")
        results = []
        for num, text in items:
            if self.drop_id is not None and int(num) == self.drop_id and len(items) > 1:
                continue
            labels = ["cybersecurity"] if "cyber" in text else ["none"]
            if "lawsuit" in text:
                labels.append("litigation")
            results.append({"id": int(num), "labels": labels})
        return json.loads(json.dumps({"results": results}))


def test_select_paragraphs_filters_item_kind_and_length() -> None:
    paras = [
        para(1),
        para(2, item="7"),
        para(3, kind="heading"),
        para(4, text="too short"),
    ]
    assert [p.id for p in select_paragraphs(paras, SETTINGS)] == ["item_1A:p1"]


def test_truncate_words() -> None:
    assert truncate_words("a b c", 5) == "a b c"
    assert truncate_words("a b c d", 2) == "a b ..."


def test_build_messages_lists_labels_and_numbers_paragraphs() -> None:
    msgs = build_messages([para(7), para(9)], DEFS, max_words=50)
    user = msgs[-1]["content"]
    assert "- litigation: lawsuits" in user
    assert "[1] paragraph number 7" in user and "[2] paragraph number 9" in user
    assert "from 1 to 2" in user


def test_clean_labels() -> None:
    assert clean_labels(["Cybersecurity", "litigation"], LABELS) == ["litigation", "cybersecurity"]
    assert clean_labels(["none", "litigation"], LABELS) == ["litigation"]
    assert clean_labels(["made_up"], LABELS) == ["none"]
    assert clean_labels("litigation", LABELS) == ["none"]  # not a list
    assert clean_labels([], LABELS) == ["none"]


def test_parse_results_requires_every_id() -> None:
    assert parse_results({"results": [{"id": "1", "labels": []}, {"id": 2}]}, 2) == {1: [], 2: None}
    for bad in [{"results": [{"id": 1}]}, {"foo": []}, []]:
        try:
            parse_results(bad, 2)
        except LLMError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_classify_batches_and_maps_ids() -> None:
    paras = [para(i) for i in range(1, 7)]
    paras[2] = para(3, text="a lawsuit about a cyber breach")
    client = FakeClient()
    preds = classify_paragraphs(paras, LABELS, client, DEFS, SETTINGS)  # type: ignore[arg-type]
    assert client.calls == [4, 2]
    assert [p.paragraph_id for p in preds] == [p.id for p in paras]
    assert preds[2].labels == ["litigation", "cybersecurity"]
    assert preds[0].citation.source_type == "section"
    assert preds[0].citation.ref == "item_1A:p1"
    assert preds[0].method == "llm"


def test_failed_batch_is_split_and_retried() -> None:
    paras = [para(i) for i in range(1, 5)]
    client = FakeClient(fail_above=1)
    errors: list[str] = []
    preds = classify_paragraphs(  # type: ignore[arg-type]
        paras, LABELS, client, DEFS, SETTINGS, on_error=lambda p, e: errors.append(p.id)
    )
    assert len(preds) == 4
    assert errors == []
    assert client.calls[0] == 4 and client.calls.count(1) == 4


def test_incomplete_answer_is_split_and_single_failures_reported() -> None:
    paras = [para(i) for i in range(1, 3)]
    client = FakeClient(drop_id=2)  # batches of 2 miss id 2; single calls succeed
    preds = classify_paragraphs(paras, LABELS, client, DEFS, SETTINGS)  # type: ignore[arg-type]
    assert [p.paragraph_id for p in preds] == ["item_1A:p1", "item_1A:p2"]

    always_fail = FakeClient(fail_above=0)
    errors: list[str] = []
    out = classify_paragraphs(  # type: ignore[arg-type]
        paras[:1], LABELS, always_fail, DEFS, SETTINGS, on_error=lambda p, e: errors.append(p.id)
    )
    assert out == [] and errors == ["item_1A:p1"]


def test_detect_risks_uses_config_labels() -> None:
    settings = load_settings()
    long_text = "the company could suffer a cyber attack that disrupts systems " * 4
    preds = detect_risks([para(1, text=long_text)], FakeClient(), settings)  # type: ignore[arg-type]
    assert preds[0].labels == ["cybersecurity"]
    assert set(preds[0].labels) <= set(settings.risk_labels)


def test_rate_limit_is_not_split() -> None:
    class QuotaClient:
        calls = 0

        def complete_json(self, messages: list[dict[str, str]]) -> Any:
            QuotaClient.calls += 1
            raise LLMRateLimitError("free-models-per-day")

    paras = [para(i) for i in range(1, 5)]
    try:
        classify_paragraphs(paras, LABELS, QuotaClient(), DEFS, SETTINGS)  # type: ignore[arg-type]
    except LLMRateLimitError:
        pass
    else:
        raise AssertionError("rate limit swallowed")
    assert QuotaClient.calls == 1
