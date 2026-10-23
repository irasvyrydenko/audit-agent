"""Eval: indicator_engine.

Correctness is covered by unit tests vs hand calculations (tests/test_indicator_engine.py).
This script reports coverage on the company set and agreement with
data/gold/indicator_engine/hand_calcs.json.
Metrics: hand_calc_match_rate, coverage {indicator: share of companies with a value},
not_applicable_count.
Run: python -m evals.indicator_engine.run_eval
"""

from __future__ import annotations

from pathlib import Path

from evals.common import write_results

COMPONENT = "indicator_engine"


def main(results_root: Path | None = None) -> int:
    # TODO: compute indicators for each company, compare with hand calculations.
    path = write_results(
        COMPONENT,
        metrics={"hand_calc_match_rate": None, "coverage": {}, "not_applicable_count": None},
        dataset={"name": f"gold/{COMPONENT}", "n": 0},
        status="stub",
        notes="Component not implemented yet.",
        results_root=results_root,
    )
    print(f"[stub] {COMPONENT}: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
