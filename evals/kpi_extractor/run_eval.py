"""Eval: kpi_extractor (LLM extraction vs XBRL ground truth).

Gold: XBRL companyfacts values (+ manual fixes in data/gold/kpi_extractor/ if XBRL is wrong).
Metrics: exact_match_rate (|pred - gold| / |gold| <= eval.kpi_relative_tolerance),
scale_error_rate (off by x1e3 / x1e6), sign_error_rate, missing_rate, per_kpi {kpi: rate}.
Scale and sign errors are counted separately from other mismatches.
Run: python -m evals.kpi_extractor.run_eval
"""

from __future__ import annotations

from pathlib import Path

from evals.common import write_results

COMPONENT = "kpi_extractor"


def main(results_root: Path | None = None) -> int:
    # TODO: for each company/year, compare extract_with_llm() to extract_from_xbrl().
    path = write_results(
        COMPONENT,
        metrics={
            "exact_match_rate": None,
            "scale_error_rate": None,
            "sign_error_rate": None,
            "missing_rate": None,
            "per_kpi": {},
        },
        dataset={"name": "xbrl_companyfacts", "n": 0},
        status="stub",
        notes="Component not implemented yet.",
        results_root=results_root,
    )
    print(f"[stub] {COMPONENT}: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
