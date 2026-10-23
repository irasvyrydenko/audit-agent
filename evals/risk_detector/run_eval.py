"""Eval: risk_detector — LLM classifier vs TF-IDF + LogReg baseline.

Gold: data/gold/risk_detector/paragraphs.jsonl ({paragraph_id, text, labels}), fixed
train/test split (seed from config). Baseline trains on train only; both score on test.
Metrics (for each method): per_class {label: {precision, recall, f1, support}},
macro_f1, micro_f1. The baseline goes in the "baseline" field.
Run: python -m evals.risk_detector.run_eval
"""

from __future__ import annotations

from pathlib import Path

from evals.common import write_results

COMPONENT = "risk_detector"


def main(results_root: Path | None = None) -> int:
    # TODO: load gold split, fit baseline, run LLM classifier, compute per-class P/R/F1.
    empty = {"per_class": {}, "macro_f1": None, "micro_f1": None}
    path = write_results(
        COMPONENT,
        metrics=dict(empty),
        baseline=dict(empty),
        dataset={"name": f"gold/{COMPONENT}", "n": 0, "split": "test"},
        status="stub",
        notes="Component not implemented yet.",
        results_root=results_root,
    )
    print(f"[stub] {COMPONENT}: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
