---
name: add-component-eval
description: Use when creating or extending an evaluation script for a component (evals/<component>/run_eval.py) — gives the template, the shared metrics JSON format, where results go, and how to compare against a baseline.
---

# Adding / extending a component eval

## Where things live
- Script: `evals/<component>/run_eval.py`, runnable as `python -m evals.<component>.run_eval`
  (`make eval C=<component>`).
- Gold data: `data/gold/<component>/` (committed). See `data/gold/README.md`.
- Results: `evals/<component>/results/latest.json` + timestamped copy per real run, written
  only via `evals.common.write_results` (never hand-rolled JSON).

## Template

```python
"""Eval: <component>. Gold: data/gold/<component>/... Metrics: ... Run: python -m evals.<component>.run_eval"""

from __future__ import annotations
from pathlib import Path
from audit_agent.common.config import PROJECT_ROOT, load_settings
from evals.common import write_results

COMPONENT = "<component>"
GOLD_DIR = PROJECT_ROOT / "data" / "gold" / COMPONENT


def load_gold() -> list[dict]: ...
def predict(example: dict) -> dict: ...  # calls the component (LLM cached)
def score(gold: list[dict], preds: list[dict]) -> dict[str, float | dict]: ...


def main(results_root: Path | None = None) -> int:
    gold = load_gold()
    preds = [predict(ex) for ex in gold]
    metrics = score(gold, preds)
    baseline = None  # or score(gold, baseline_preds)
    path = write_results(
        COMPONENT,
        metrics,
        dataset={"name": f"gold/{COMPONENT}", "n": len(gold)},
        baseline=baseline,
        results_root=results_root,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Keep `load_gold` / `score` pure and unit-test `score` on a tiny hand-made example.
Also save per-example predictions to `evals/<component>/results/predictions_latest.jsonl`
(id, gold, pred, correct) — the `error-analysis` skill samples failures from it.

## Metric format rules
- Rates as floats in [0, 1], rounded to 4 decimals. Counts as ints. Undefined → `null`.
- Per-class metrics: `{"per_class": {label: {"precision", "recall", "f1", "support"}}}`.
- Always include `n` in `dataset`, and a `split` if there is one.
- Metric names per component are fixed in AGENTS.md → Evaluation rules. Don't rename
  without logging it in `docs/decisions.md` (breaks comparisons across runs).

## Baselines
- Put baseline scores in the `baseline` field with **the same keys** as `metrics`, computed
  on the **same examples/split**.
- risk_detector: baseline = TF-IDF + LogReg trained on the train split only.
- kpi_extractor: XBRL is ground truth, not a baseline; optionally report a regex/table
  heuristic as baseline.
- consistency_checker: trivial baseline = always "unverifiable" (shows majority-class accuracy).

## Reproducibility
- Model from config only; seed from `eval.random_seed`; LLM calls cached → reruns are free.
- Never tune prompts/thresholds on the test split.

## Checklist
- [ ] `main()` returns 0 and writes `status: "ok"`
- [ ] Score function unit-tested; `tests/test_evals.py` still passes
- [ ] Metrics + takeaway recorded in `docs/crisp_dm.md` → Evaluation (use `crisp-dm-log`)
- [ ] `make lint test` passes
