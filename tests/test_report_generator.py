"""report_generator tests: evidence formatting, summary parsing (uncited sentences dropped),
LLM failure fallback, and the faithfulness check catching planted false statements."""

from __future__ import annotations

from datetime import date
from typing import Any

from audit_agent.common.citations import Citation
from audit_agent.common.llm_client import LLMError
from audit_agent.filing_loader.loader import Filing, FilingRef, Paragraph, Section
from audit_agent.indicator_engine.indicators import AnomalyFlag, Indicator
from audit_agent.kpi_extractor.extractor import KPISet, KPIValue
from audit_agent.report_generator.evidence import build_evidence, money, pct, signed_pct
from audit_agent.report_generator.generator import (
    DISCLAIMER,
    Report,
    ReportStatement,
    check_faithfulness,
    generate_report,
    numbers_in,
    parse_summary,
)
from audit_agent.risk_detector.labels import RiskPrediction

END, PRIOR_END = date(2024, 12, 31), date(2023, 12, 31)
ACC = "acc-1"


def _kset(values: dict[str, float], end: date, fy: int) -> KPISet:
    return KPISet(
        ticker="T",
        fiscal_year=fy,
        period_end=end,
        accession=ACC,
        values={
            k: KPIValue(
                name=k,
                value=v,
                unit="USD",
                period_end=end,
                citations=[Citation(source_type="xbrl", ref=f"us-gaap:{k}@{end}", accession=ACC)],
            )
            for k, v in values.items()
        },
    )


CURRENT = _kset({"revenue": 2_000e6, "net_income": 300e6}, END, 2024)
PRIOR = _kset({"revenue": 1_600e6, "net_income": 320e6}, PRIOR_END, 2023)


def _ind(name: str, value: float | None, inputs: list[str], unit: str = "ratio") -> Indicator:
    return Indicator(
        name=name,
        value=value,
        unit=unit,  # type: ignore[arg-type]
        formula="f",
        status="ok" if value is not None else "missing",
        period_end=END,
        inputs={},
        citations=[c for k in inputs for c in CURRENT.values[k].citations],
    )


INDICATORS = [
    _ind("revenue_growth", 0.25, ["revenue"]),
    _ind("net_margin", 0.15, ["net_income", "revenue"]),
    _ind("current_ratio", None, []),
]
FLAGS = [
    AnomalyFlag(
        name="revenue_decline",
        triggered=False,
        reason="revenue_growth = 0.250 (not below 0.0)",
        citations=[Citation(source_type="computed", ref="indicator:revenue_growth")],
    )
]
FILING = Filing(
    ticker="T",
    fiscal_year=2024,
    ref=FilingRef(
        cik="1",
        accession=ACC,
        form="10-K",
        filing_date=date(2025, 2, 1),
        report_date=END,
        primary_document="t.htm",
    ),
    sections={
        "1A": Section(
            item="1A",
            title="Risk Factors",
            paragraphs=[
                Paragraph(id="item_1A:p1", item="1A", index=1, text="We face cyber attacks " * 20),
                Paragraph(id="item_1A:p2", item="1A", index=2, text="Lawsuits may hurt us."),
            ],
        )
    },
    tables=[],
)
RISKS = [
    RiskPrediction(
        paragraph_id="item_1A:p1",
        labels=["cybersecurity"],
        scores={"cybersecurity": 1.0},
        method="llm",
        citation=Citation(source_type="section", ref="item_1A:p1"),
    ),
    RiskPrediction(
        paragraph_id="item_1A:p2",
        labels=["none"],
        scores={"none": 1.0},
        method="llm",
        citation=Citation(source_type="section", ref="item_1A:p2"),
    ),
]


def evidence() -> list:
    return build_evidence(
        FILING,
        CURRENT,
        PRIOR,
        INDICATORS,
        FLAGS,
        RISKS,
        risk_labels=["cybersecurity", "litigation", "none"],
        distress_below=1.1,
        safe_above=2.6,
    )


# --- evidence --------------------------------------------------------------------------------


def test_formatting() -> None:
    assert money(391_035e6) == "$391.04B"
    assert money(-42_012e6) == "-$42.01B"
    assert money(812.5e6) == "$812.50M"
    assert pct(0.2397) == "24.0%"
    assert signed_pct(-0.034) == "-3.4%"


def test_evidence_texts_and_citations() -> None:
    ev = evidence()
    texts = [e.text for e in ev]
    assert texts[0] == "Revenue: $2.00B in FY2024 vs $1.60B in FY2023 (+25.0%)."
    assert "Net margin: 15.0% in FY2024." in texts
    assert not any("Current ratio" in t for t in texts)  # missing indicator -> no statement
    assert any(t.startswith("None of the 1 evaluated red-flag rules") for t in texts)
    risk = next(e for e in ev if e.section == "risk_themes")
    assert risk.text.startswith("Risk theme cybersecurity: main topic of 1 of 2")
    assert risk.citations[0].ref == "item_1A:p1"
    assert risk.citations[0].quote and risk.citations[0].quote.endswith("...")
    assert [e.id for e in ev] == [f"E{i}" for i in range(1, len(ev) + 1)]
    assert all(e.citations for e in ev)
    revenue_refs = {c.ref for c in ev[0].citations}
    assert revenue_refs == {
        f"us-gaap:revenue@{END}",
        f"us-gaap:revenue@{PRIOR_END}",
        "indicator:revenue_growth",
    }


# --- summary ---------------------------------------------------------------------------------


class FakeClient:
    def __init__(self, answer: Any = None, error: Exception | None = None) -> None:
        self.answer, self.error, self.calls = answer, error, 0

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        if self.error:
            raise self.error
        return self.answer


def test_parse_summary_drops_uncited_and_unknown_ids() -> None:
    ev = evidence()
    answer = {
        "statements": [
            {"text": "Revenue rose 25.0% to $2.00B.", "evidence": ["E1"]},
            {"text": "Uncited claim.", "evidence": []},
            {"text": "Invented source.", "evidence": ["E999"]},
            "not a dict",
        ]
    }
    statements, dropped = parse_summary(answer, ev)
    assert [s.text for s in statements] == ["Revenue rose 25.0% to $2.00B."]
    assert dropped == 3
    assert statements[0].origin == "llm" and statements[0].citations


def test_generate_report_with_summary_then_details() -> None:
    ev = evidence()
    client = FakeClient({"statements": [{"text": "Net margin was 15.0%.", "evidence": ["E3"]}]})
    report = generate_report("T", 2024, ev, client)  # type: ignore[arg-type]
    assert report.statements[0].section == "summary"
    assert len(report.statements) == 1 + len(ev)
    assert report.summary_status.startswith("ok (1 sentences")
    assert all(s.citations for s in report.statements)
    assert report.disclaimer == DISCLAIMER
    assert "not investment advice" in DISCLAIMER.lower()


def test_llm_failure_gives_report_without_summary() -> None:
    ev = evidence()
    report = generate_report("T", 2024, ev, FakeClient(error=LLMError("quota")))  # type: ignore[arg-type]
    assert report.section("summary") == []
    assert report.summary_status.startswith("skipped")
    assert len(report.statements) == len(ev)


# --- faithfulness ----------------------------------------------------------------------------


def _check(report: Report) -> Any:
    return check_faithfulness(report, evidence(), FILING, [CURRENT, PRIOR], INDICATORS)


def test_template_report_is_fully_faithful() -> None:
    report = generate_report("T", 2024, evidence())
    result = _check(report)
    assert result.n_supported == result.n_statements > 0
    assert result.n_citation_errors == 0


def test_numbers_in() -> None:
    assert numbers_in("Revenue $4,002.81B, up 2.0% in FY2024") == [4002.81, 2.0, 2024.0]


def test_planted_false_number_is_caught() -> None:
    ev = evidence()
    good = ReportStatement(
        text="Revenue grew 25% to $2.00B.",  # rounded 25.0 -> still supported
        citations=ev[0].citations,
        section="summary",
        origin="llm",
        evidence_ids=["E1"],
    )
    false = good.model_copy(update={"text": "Revenue grew 35.0% to $2.00B."})
    result = _check(Report(ticker="T", fiscal_year=2024, statements=[good, false]))
    assert result.unsupported_ids == [1]
    assert "35.0" in result.reasons[1]


def test_planted_unresolved_citation_is_caught() -> None:
    bad = ReportStatement(
        text="Lawsuits are a risk.",
        citations=[Citation(source_type="section", ref="item_1A:p999")],
        section="summary",
        origin="llm",
        evidence_ids=[],
    )
    result = _check(Report(ticker="T", fiscal_year=2024, statements=[bad]))
    assert result.n_citation_errors == 1
    assert result.unsupported_ids == [0]


# --- eval helpers ----------------------------------------------------------------------------


def test_eval_perturb_and_score() -> None:
    from evals.report_generator.run_eval import perturb, score

    st = ReportStatement(
        text="Net margin: 15.0% in FY2024.",
        citations=evidence()[0].citations,
        section="s",
        origin="template",
    )
    assert perturb(st).text == "Net margin: 16.50% in FY2024."  # type: ignore[union-attr]
    assert perturb(st.model_copy(update={"text": "No numbers here."})) is None
    rows = [
        {
            "statements": 4,
            "supported": 4,
            "summary_statements": 0,
            "summary_supported": 0,
            "citations": 10,
            "citation_errors": 1,
            "uncited": 0,
            "perturbed_detected": 3,
            "perturbed_planted": 3,
        }
    ]
    metrics = score(rows)
    assert metrics["faithfulness_rate"] == 1.0
    assert metrics["summary_faithfulness_rate"] is None
    assert metrics["citation_correctness"] == 0.9
    assert metrics["perturbed_detection_rate"] == 1.0
    assert metrics["summaries_generated"] == 0


def test_consistency_evidence_lists_checked_claims() -> None:
    from audit_agent.consistency_checker.checker import Claim, verify_claim
    from audit_agent.report_generator.evidence import consistency_evidence

    claims = [
        Claim(
            id="a",
            paragraph_id="item_7:p1",
            text="Revenue was $2.0 billion",
            metric="revenue",
            kind="level",
            value=2.0e9,
            as_written="$2.0 billion",
        ),
        Claim(
            id="b",
            paragraph_id="item_7:p2",
            text="revenue up 40%",
            metric="revenue",
            kind="change_pct",
            value=0.40,
            direction="up",
            as_written="40%",
        ),
        Claim(
            id="c",
            paragraph_id="item_7:p3",
            text="Segment A sales rose",
            metric="revenue",
            scope="segment",
            kind="direction",
            direction="up",
        ),
    ]
    checks = [verify_claim(c, CURRENT, PRIOR, 0.005) for c in claims]
    assert [r.verdict for r in checks] == ["supported", "contradicted", "unverifiable"]
    items = consistency_evidence(checks)
    texts = [t for _, t, _ in items]
    assert texts[0].startswith(
        "MD&A claims checked against XBRL data: 3 extracted, 1 supported, 1 contradicted"
    )
    assert texts[1] == (
        'MD&A claim "Revenue was $2.0 billion" (item_7:p1) is supported: computed revenue = $2.00B.'
    )
    assert texts[2].endswith("is contradicted: computed revenue = +25.0%.")
    assert len(items) == 3  # unverifiable claim only counted in the summary
    assert all(cites for _, _, cites in items)
