"""Eval: filing_loader segmentation.

Gold: data/gold/filing_loader/<ticker>_<fy>.json — for each Item, the expected first and last
paragraph text (or char offsets).
Metrics: segmentation_accuracy (share of Items whose boundaries match gold),
per_item_accuracy {item: acc}, items_missing.
Run: python -m evals.filing_loader.run_eval
"""

from __future__ import annotations

from pathlib import Path

from evals.common import write_results

COMPONENT = "filing_loader"


def main(results_root: Path | None = None) -> int:
    # TODO: load gold, run filing_loader on each gold filing, compare boundaries.
    path = write_results(
        COMPONENT,
        metrics={"segmentation_accuracy": None, "per_item_accuracy": {}, "items_missing": None},
        dataset={"name": f"gold/{COMPONENT}", "n": 0},
        status="stub",
        notes="Component not implemented yet.",
        results_root=results_root,
    )
    print(f"[stub] {COMPONENT}: wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
