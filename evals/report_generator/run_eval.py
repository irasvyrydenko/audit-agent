"""Eval: report_generator.

Data: generated reports for the company set + a manually checked sample in
data/gold/report_generator/ (statement-level supported yes/no).
Metrics: faithfulness_rate (supported statements / all), citation_correctness (cited ref
exists and supports the statement), uncited_statement_count (must be 0),
judge_agreement (automatic check vs manual labels).
Run: python -m evals.report_generator.run_eval
"""

from __future__ import annotations

from pathlib import Path

from evals.common import write_results

COMPONENT = "report_generator"


def main(results_root: Path | None = None) -> int:
    # TODO: generate reports, run check_faithfulness, compare to manual sample.
    path = write_results(
        COMPONENT,
        metrics={
            "faithfulness_rate": None,
            "citation_correctness": None,
            "uncited_statement_count": None,
            "judge_agreement": None,
        },
        dataset={"name": f"gold/{COMPONENT}", "n": 0},
        status="stub",
        notes="Component not implemented yet.",
        results_root=results_root,
    )
    print(f"[stub] {COMPONENT}: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
