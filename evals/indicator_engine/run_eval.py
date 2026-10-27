"""Eval: indicator_engine.

Formula correctness is covered by unit tests vs hand calculations
(tests/test_indicator_engine.py). This script runs the full chain (XBRL KPIs -> indicators)
on the company set and reports:
- hand_calc_match_rate: indicators within gold tolerance of data/gold/indicator_engine/
  hand_calcs.json (inputs typed from Item 8 statements, computed outside src/);
- coverage {indicator: share of applicable companies with a value};
- not_applicable_count (bank rules) and flags_triggered {flag: count}.
Run: python -m evals.indicator_engine.run_eval
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from audit_agent.common.config import load_companies, load_settings, resolve_path
from audit_agent.filing_loader.loader import load_filing
from audit_agent.indicator_engine.indicators import Indicator, anomaly_flags, compute_all
from audit_agent.kpi_extractor.extractor import load_kpis
from evals.common import write_results

COMPONENT = "indicator_engine"


def load_gold() -> dict[str, Any]:
    path = resolve_path(load_settings().paths.gold) / COMPONENT / "hand_calcs.json"
    return json.loads(path.read_text(encoding="utf-8"))


def compare_hand_calcs(
    ticker: str, indicators: list[Indicator], case: dict[str, Any], tol: float
) -> list[dict[str, Any]]:
    by_name = {i.name: i.value for i in indicators}
    rows = []
    for name, expected in case["expected"].items():
        got = by_name.get(name)
        match = got is not None and abs(got - expected) <= tol * max(abs(expected), 1e-9)
        rows.append(
            {"ticker": ticker, "indicator": name, "expected": expected, "got": got, "match": match}
        )
    return rows


def coverage(per_company: dict[str, list[Indicator]]) -> dict[str, float | None]:
    names = [i.name for i in next(iter(per_company.values()))]
    result: dict[str, float | None] = {}
    for name in names:
        applicable = [
            i
            for inds in per_company.values()
            for i in inds
            if i.name == name and i.status != "not_applicable"
        ]
        ok = sum(i.status == "ok" for i in applicable)
        result[name] = round(ok / len(applicable), 4) if applicable else None
    return result


def main(results_root: Path | None = None) -> int:
    settings = load_settings()
    companies = load_companies()
    fy = companies.default_fiscal_year
    gold = load_gold()
    gold_cases = {(c["ticker"], c["fiscal_year"]): c for c in gold["cases"]}
    per_company: dict[str, list[Indicator]] = {}
    hand_rows: list[dict[str, Any]] = []
    flags_triggered: dict[str, int] = {}
    for company in companies.companies:
        filing = load_filing(company.ticker, fy)
        current, prior = load_kpis(company.ticker, fy, filing.ref)
        inds = compute_all(current, prior, settings.indicators, is_bank=company.bank)
        per_company[company.ticker] = inds
        for flag in anomaly_flags(current, inds, settings.indicators, is_bank=company.bank):
            flags_triggered[flag.name] = flags_triggered.get(flag.name, 0) + int(flag.triggered)
        if case := gold_cases.get((company.ticker, fy)):
            hand_rows += compare_hand_calcs(company.ticker, inds, case, gold["tolerance"])
    metrics = {
        "hand_calc_match_rate": round(sum(r["match"] for r in hand_rows) / len(hand_rows), 4)
        if hand_rows
        else None,
        "hand_calc_n": len(hand_rows),
        "coverage": coverage(per_company),
        "not_applicable_count": sum(
            i.status == "not_applicable" for inds in per_company.values() for i in inds
        ),
        "flags_triggered": flags_triggered,
    }
    path = write_results(
        COMPONENT,
        metrics=metrics,
        dataset={"name": f"gold/{COMPONENT}", "n": len(per_company), "fiscal_year": fy},
        notes="Full chain XBRL -> indicators. Hand calcs drafted by the coding agent from Item 8 "
        "figures (AAPL, WMT); spot-check pending.",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    predictions.write_text("\n".join(json.dumps(r) for r in hand_rows) + "\n", encoding="utf-8")
    print(f"{COMPONENT}: {json.dumps(metrics, indent=1)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
