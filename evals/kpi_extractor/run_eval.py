"""Eval: kpi_extractor.

Current scope (XBRL part only; LLM extraction is deferred):
- coverage_rate / missing_rate / per_kpi_coverage: share of (company, KPI) pairs with a value
  for the fiscal year.
- table_match_rate: single-fact KPIs whose XBRL value (in $ millions, rounded) appears in a
  numeric cell of the filing's own Item 8 tables — checks tag/period selection against what
  a human reads in the statements. Multi-fact (derived) KPIs are skipped.
- cross_filing_agreement_rate: prior-year values from the FY 10-K vs current-year values from
  the FY-1 10-K, within eval.kpi_relative_tolerance (disagreement = restatement or bad pick).
LLM-vs-XBRL metrics (exact_match_rate, scale_error_rate, sign_error_rate) stay null until
extract_with_llm exists.
Run: python -m evals.kpi_extractor.run_eval
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from audit_agent.common.config import load_companies, load_settings
from audit_agent.common.edgar_client import EdgarClient
from audit_agent.filing_loader.loader import Filing, find_10k, load_filing
from audit_agent.kpi_extractor.extractor import KPISet, extract_from_xbrl, extract_years
from evals.common import write_results

COMPONENT = "kpi_extractor"
_NUMBER = re.compile(r"^\(?([0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]+)?\)?$")


def table_numbers(filing: Filing, item: str = "8") -> set[int]:
    """Absolute integer values of all numeric cells in the Item's tables."""
    numbers: set[int] = set()
    for table in filing.tables:
        if table.item != item:
            continue
        for row in table.rows:
            for cell in row:
                match = _NUMBER.match(re.sub(r"[\s$]", "", cell))
                if match:
                    numbers.add(int(match[1].replace(",", "")))
    return numbers


def table_match_rows(kpis: KPISet, numbers: set[int]) -> list[dict[str, Any]]:
    """One row per single-fact KPI: does round(|value| / 1e6) appear in the tables?"""
    rows = []
    for name, kpi in kpis.values.items():
        if kpi.value is None or len(kpi.facts) != 1:
            continue
        millions = round(abs(kpi.value) / 1e6)
        rows.append(
            {"check": "table", "ticker": kpis.ticker, "kpi": name, "found": millions in numbers}
        )
    return rows


def agreement_rows(prior: KPISet, earlier: KPISet, rel_tol: float) -> list[dict[str, Any]]:
    """Compare prior-year comparatives with the earlier filing's own current-year values."""
    rows = []
    for name, kpi in prior.values.items():
        other = earlier.get(name)
        if kpi.value is None or other is None:
            continue
        denom = max(abs(other), 1.0)
        rows.append(
            {
                "check": "cross_filing",
                "ticker": prior.ticker,
                "kpi": name,
                "this_filing": kpi.value,
                "earlier_filing": other,
                "agree": abs(kpi.value - other) / denom <= rel_tol,
            }
        )
    return rows


def coverage_rows(kpis: KPISet) -> list[dict[str, Any]]:
    return [
        {"check": "coverage", "ticker": kpis.ticker, "kpi": name, "present": v.value is not None}
        for name, v in kpis.values.items()
    ]


def _rate(rows: list[dict[str, Any]], key: str) -> float | None:
    return round(sum(r[key] for r in rows) / len(rows), 4) if rows else None


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    cov = [r for r in rows if r["check"] == "coverage"]
    table = [r for r in rows if r["check"] == "table"]
    cross = [r for r in rows if r["check"] == "cross_filing"]
    per_kpi = {
        k: _rate([r for r in cov if r["kpi"] == k], "present")
        for k in dict.fromkeys(r["kpi"] for r in cov)
    }
    coverage = _rate(cov, "present")
    return {
        "coverage_rate": coverage,
        "missing_rate": None if coverage is None else round(1 - coverage, 4),
        "per_kpi_coverage": per_kpi,
        "table_match_rate": _rate(table, "found"),
        "table_match_n": len(table),
        "cross_filing_agreement_rate": _rate(cross, "agree"),
        "cross_filing_n": len(cross),
        "exact_match_rate": None,
        "scale_error_rate": None,
        "sign_error_rate": None,
    }


def evaluate_company(ticker: str, fiscal_year: int, client: EdgarClient) -> list[dict[str, Any]]:
    settings = load_settings()
    filing = load_filing(ticker, fiscal_year, client=client)
    facts = client.get_companyfacts(filing.ref.cik)
    current, prior = extract_years(facts, filing.ref, ticker, fiscal_year, settings.kpis)
    rows = coverage_rows(current) + table_match_rows(current, table_numbers(filing))
    if prior is not None:
        earlier_ref = find_10k(client.iter_filings(filing.ref.cik), filing.ref.cik, fiscal_year - 1)
        earlier = extract_from_xbrl(
            facts,
            ticker=ticker,
            fiscal_year=fiscal_year - 1,
            accession=earlier_ref.accession,
            period_end=earlier_ref.report_date,
            kpis=settings.kpis,
        )
        rows += agreement_rows(prior, earlier, settings.eval.kpi_relative_tolerance)
    return rows


def main(results_root: Path | None = None) -> int:
    companies = load_companies()
    fiscal_year = companies.default_fiscal_year
    client = EdgarClient()
    rows = [r for c in companies.companies for r in evaluate_company(c.ticker, fiscal_year, client)]
    metrics = score(rows)
    path = write_results(
        COMPONENT,
        metrics=metrics,
        dataset={
            "name": "xbrl_companyfacts",
            "n": len(companies.companies),
            "fiscal_year": fiscal_year,
            "kpis": len(load_settings().kpis),
        },
        notes="XBRL part only: coverage, Item 8 table match, cross-filing agreement. "
        "LLM-vs-XBRL metrics pending (extract_with_llm not implemented).",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    predictions.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"{COMPONENT}: {json.dumps(metrics, indent=1)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
