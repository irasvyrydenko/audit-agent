"""kpi_extractor tests on a small synthetic companyfacts fixture (values are made up)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from audit_agent.common.config import KPIDefinition, load_settings
from audit_agent.filing_loader.loader import Filing, FilingRef, Table
from audit_agent.kpi_extractor.extractor import extract_from_xbrl, extract_kpi, extract_years
from audit_agent.kpi_extractor.xbrl import parse_expression, prior_period_end, select_fact
from evals.kpi_extractor.run_eval import (
    agreement_rows,
    coverage_rows,
    score,
    table_match_rows,
    table_numbers,
)

ACC = "0000000001-24-000001"
OTHER = "0000000001-23-000001"
FY_END = date(2024, 9, 28)
PRIOR_END = date(2023, 9, 30)


def _dur(val: float, start: str, end: str, accn: str = ACC, filed: str = "2024-11-01") -> dict:
    return {"start": start, "end": end, "val": val, "accn": accn, "form": "10-K", "filed": filed}


def _inst(val: float, end: str, accn: str = ACC, filed: str = "2024-11-01") -> dict:
    return {"end": end, "val": val, "accn": accn, "form": "10-K", "filed": filed}


def _facts(tags: dict[str, list[dict]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {t: {"units": {"USD": rows}} for t, rows in tags.items()}}}


FACTS = _facts(
    {
        "Revenues": [
            _dur(1000, "2023-10-01", "2024-09-28"),
            _dur(900, "2022-09-25", "2023-09-30"),
            _dur(260, "2024-06-30", "2024-09-28"),  # quarter: must be ignored
            _dur(999, "2023-10-01", "2024-09-28", accn=OTHER),  # other filing
        ],
        "NetIncomeLoss": [_dur(100, "2023-10-01", "2024-09-28")],
        "Assets": [_inst(5000, "2024-09-28"), _inst(4500, "2023-09-30")],
        "LiabilitiesAndStockholdersEquity": [_inst(5000, "2024-09-28")],
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest": [
            _inst(1800, "2024-09-28")
        ],
        "CommercialPaper": [_inst(50, "2024-09-28")],
        "LongTermDebtCurrent": [_inst(70, "2024-09-28")],
        "LongTermDebtNoncurrent": [_inst(800, "2024-09-28"), _inst(850, "2023-09-30")],
    }
)


def kpi(name: str, period_type: str, *tags: str) -> KPIDefinition:
    return KPIDefinition(name=name, period_type=period_type, tags=list(tags))


# --- expressions ---------------------------------------------------------------------------


def test_parse_expression_signs_and_optional() -> None:
    terms = parse_expression("A? + B - c_ref")
    assert [(t.name, t.sign, t.optional) for t in terms] == [
        ("A", 1, True),
        ("B", 1, False),
        ("c_ref", -1, False),
    ]
    assert terms[2].is_kpi_ref and not terms[0].is_kpi_ref


@pytest.mark.parametrize("bad", ["", "A +", "A * B", "A + + B", "1A"])
def test_parse_expression_rejects_malformed(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_expression(bad)


# --- fact selection ------------------------------------------------------------------------


def _select(tag: str, period_end: date, period_type: str) -> float | None:
    rows = FACTS["facts"]["us-gaap"][tag]["units"]["USD"]
    fact = select_fact(
        rows,
        taxonomy="us-gaap",
        tag=tag,
        accession=ACC,
        period_end=period_end,
        period_type=period_type,  # type: ignore[arg-type]
    )
    return fact.value if fact else None


def test_select_full_year_duration_from_chosen_filing_only() -> None:
    assert _select("Revenues", FY_END, "duration") == 1000
    assert _select("Revenues", PRIOR_END, "duration") == 900


def test_select_instant_ignores_durations_and_vice_versa() -> None:
    assert _select("Assets", FY_END, "instant") == 5000
    assert _select("Assets", FY_END, "duration") is None
    assert _select("Revenues", FY_END, "instant") is None


def test_select_duplicate_takes_latest_filed() -> None:
    rows = [_inst(1, "2024-09-28", filed="2024-11-01"), _inst(2, "2024-09-28", filed="2024-12-01")]
    fact = select_fact(
        rows,
        taxonomy="us-gaap",
        tag="X",
        accession=ACC,
        period_end=FY_END,
        period_type="instant",
    )
    assert fact is not None and fact.value == 2
    assert fact.ref == "us-gaap:X@2024-09-28"


def test_prior_period_end_from_fiscal_year_start() -> None:
    assert prior_period_end(FACTS, ACC, FY_END) == PRIOR_END
    assert prior_period_end(FACTS, "missing", FY_END) is None


# --- KPI resolution ------------------------------------------------------------------------


def test_tag_fallback_order() -> None:
    value = extract_kpi(
        kpi("revenue", "duration", "SalesRevenueNet", "Revenues"), FACTS, ACC, FY_END, {}
    )
    assert value.value == 1000
    assert value.expression == "Revenues"
    assert [c.ref for c in value.citations] == ["us-gaap:Revenues@2024-09-28"]
    assert value.citations[0].accession == ACC


def test_difference_expression() -> None:
    expr = (
        "LiabilitiesAndStockholdersEquity - "
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"
    )
    value = extract_kpi(
        kpi("total_liabilities", "instant", "Liabilities", expr), FACTS, ACC, FY_END, {}
    )
    assert value.value == 3200
    assert len(value.citations) == 2


def test_optional_terms_sum_present_ones() -> None:
    expr = "ShortTermBorrowings? + CommercialPaper? + LongTermDebtCurrent?"
    value = extract_kpi(kpi("current_debt", "instant", expr), FACTS, ACC, FY_END, {})
    assert value.value == 120


def test_required_term_missing_falls_through_to_none() -> None:
    value = extract_kpi(kpi("x", "instant", "Assets + Missing"), FACTS, ACC, FY_END, {})
    assert value.value is None
    assert value.citations == []


def test_all_optional_terms_missing_is_none() -> None:
    value = extract_kpi(kpi("x", "instant", "Missing1? + Missing2?"), FACTS, ACC, FY_END, {})
    assert value.value is None


def test_kpi_reference_reuses_earlier_values_and_citations() -> None:
    kpis = [
        kpi("current_debt", "instant", "CommercialPaper? + LongTermDebtCurrent?"),
        kpi("long_term_debt", "instant", "LongTermDebtNoncurrent"),
        kpi("total_debt", "instant", "current_debt + long_term_debt"),
    ]
    result = extract_from_xbrl(
        FACTS, ticker="test", fiscal_year=2024, accession=ACC, period_end=FY_END, kpis=kpis
    )
    total = result.values["total_debt"]
    assert total.value == 920
    assert len(total.citations) == 3
    assert result.ticker == "TEST"


def test_kpi_reference_missing_makes_dependent_none() -> None:
    kpis = [
        kpi("current_debt", "instant", "Missing"),
        kpi("total_debt", "instant", "current_debt + LongTermDebtNoncurrent"),
    ]
    result = extract_from_xbrl(
        FACTS, ticker="T", fiscal_year=2024, accession=ACC, period_end=FY_END, kpis=kpis
    )
    assert result.get("total_debt") is None
    assert result.get("unknown") is None


def test_extract_years_returns_current_and_prior() -> None:
    ref = FilingRef(
        cik="0000000001",
        accession=ACC,
        form="10-K",
        filing_date=date(2024, 11, 1),
        report_date=FY_END,
        primary_document="x.htm",
    )
    kpis = [kpi("revenue", "duration", "Revenues"), kpi("total_assets", "instant", "Assets")]
    current, prior = extract_years(FACTS, ref, "T", 2024, kpis)
    assert current.get("revenue") == 1000
    assert prior is not None
    assert prior.fiscal_year == 2023
    assert prior.period_end == PRIOR_END
    assert prior.get("revenue") == 900
    assert prior.get("total_assets") == 4500


def test_config_expressions_all_parse_and_refs_point_backwards() -> None:
    seen: set[str] = set()
    for definition in load_settings().kpis:
        for expr in definition.tags:
            for term in parse_expression(expr):
                if term.is_kpi_ref:
                    assert term.name in seen, f"{definition.name} uses {term.name} before it"
        seen.add(definition.name)


# --- eval helpers --------------------------------------------------------------------------


def _filing_with_table(rows: list[list[str]]) -> Filing:
    ref = FilingRef(
        cik="1",
        accession=ACC,
        form="10-K",
        filing_date=date(2024, 11, 1),
        report_date=FY_END,
        primary_document="x.htm",
    )
    return Filing(
        ticker="T",
        fiscal_year=2024,
        ref=ref,
        sections={},
        tables=[Table(id="item_8:t0", item="8", rows=rows)],
    )


def test_table_numbers_parses_negatives_dollars_and_spaces() -> None:
    filing = _filing_with_table([["Accumulated deficit", "( 19,154 )", "$ 5,983", "17.7", "n/a"]])
    assert table_numbers(filing) == {19154, 5983, 17}


def test_eval_scoring_rates() -> None:
    kpis = [kpi("revenue", "duration", "Revenues"), kpi("cost_of_revenue", "duration", "Missing")]
    current = extract_from_xbrl(
        FACTS, ticker="T", fiscal_year=2024, accession=ACC, period_end=FY_END, kpis=kpis
    )
    earlier = current.model_copy(deep=True)
    earlier.values["revenue"].value = 1003  # 0.3% off: within 0.5% tolerance
    rows = (
        coverage_rows(current)
        + table_match_rows(current, {5})
        + agreement_rows(current, earlier, rel_tol=0.005)
    )
    metrics = score(rows)
    assert metrics["coverage_rate"] == 0.5
    assert metrics["per_kpi_coverage"] == {"revenue": 1.0, "cost_of_revenue": 0.0}
    assert metrics["table_match_rate"] == 0.0  # 1000 USD = 0 $M, not in {5}
    assert metrics["cross_filing_agreement_rate"] == 1.0
    assert metrics["exact_match_rate"] is None
