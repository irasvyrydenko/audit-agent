"""Eval: filing_loader segmentation.

Gold: data/gold/filing_loader/<TICKER>_<FY>.json — per Item, the first 80 chars of the
expected first and last paragraph.
An Item is correct when both boundaries match (prefix match on normalized text).
Metrics: segmentation_accuracy, start_accuracy, end_accuracy, per_item_accuracy,
items_missing. Per-example rows go to results/predictions_latest.jsonl.
Run: python -m evals.filing_loader.run_eval
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from audit_agent.common.config import PROJECT_ROOT
from audit_agent.filing_loader.html_blocks import normalize
from audit_agent.filing_loader.loader import Filing, load_filing
from evals.common import write_results

COMPONENT = "filing_loader"
GOLD_DIR = PROJECT_ROOT / "data" / "gold" / COMPONENT
PREFIX_CHARS = 60


def load_gold(gold_dir: Path = GOLD_DIR) -> list[dict[str, Any]]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(gold_dir.glob("*.json"))]


def _same(a: str, b: str) -> bool:
    return normalize(a)[:PREFIX_CHARS] == normalize(b)[:PREFIX_CHARS]


def compare(gold: dict[str, Any], filing: Filing) -> list[dict[str, Any]]:
    rows = []
    for item, expected in gold["items"].items():
        section = filing.sections.get(item)
        row: dict[str, Any] = {"id": f"{gold['ticker']}_{gold['fiscal_year']}:{item}"}
        row["item"], row["gold"] = item, expected
        if section is None or not section.paragraphs:
            row.update(pred=None, start_ok=False, end_ok=False, correct=False)
        else:
            first, last = section.paragraphs[0].text, section.paragraphs[-1].text
            row["pred"] = {"first": first[:80], "last": last[:80]}
            row["start_ok"] = _same(first, expected["first"])
            row["end_ok"] = _same(last, expected["last"])
            row["correct"] = row["start_ok"] and row["end_ok"]
        rows.append(row)
    return rows


def score(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    per_item: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        per_item[r["item"]].append(r["correct"])

    def rate(key: str) -> float | None:
        return round(sum(r[key] for r in rows) / n, 4) if n else None

    return {
        "segmentation_accuracy": rate("correct"),
        "start_accuracy": rate("start_ok"),
        "end_accuracy": rate("end_ok"),
        "per_item_accuracy": {k: round(sum(v) / len(v), 4) for k, v in sorted(per_item.items())},
        "items_missing": sum(r["pred"] is None for r in rows),
    }


def main(results_root: Path | None = None) -> int:
    gold = load_gold()
    rows = [r for g in gold for r in compare(g, load_filing(g["ticker"], g["fiscal_year"]))]
    path = write_results(
        COMPONENT,
        metrics=score(rows),
        dataset={
            "name": f"gold/{COMPONENT}",
            "n": len(rows),
            "filings": len(gold),
            "split": "dev",
        },
        notes="Dev gold drafted from inspected parser output (not independent); see crisp_dm.md.",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    predictions.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")
    print(f"{COMPONENT}: {score(rows)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
