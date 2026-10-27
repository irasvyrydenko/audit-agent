"""Eval: risk_detector — LLM classifier (TF-IDF + LogReg baseline pending).

Gold: data/gold/risk_detector/paragraphs.jsonl ({paragraph_id, ticker, fy, text, labels,
split, labeled_by}); sample drawn by evals/risk_detector/sample_gold.py. The LLM is scored on
the `test` split. Metrics: per_class {label: {precision, recall, f1, support}}, macro_f1
(over labels with support > 0, excluding "none"), micro_f1, exact_match (subset accuracy).
The baseline will go in the "baseline" field once it has its own training split.
Run: python -m evals.risk_detector.run_eval
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sklearn.metrics import precision_recall_fscore_support
from sklearn.preprocessing import MultiLabelBinarizer

from audit_agent.common.config import load_settings
from audit_agent.common.llm_client import LLMClient
from audit_agent.filing_loader.loader import Paragraph
from audit_agent.risk_detector.llm_classifier import NONE_LABEL, classify_paragraphs
from evals.common import write_results
from evals.risk_detector.sample_gold import gold_path, read_gold

COMPONENT = "risk_detector"


def to_paragraph(row: dict[str, Any]) -> Paragraph:
    item = row["paragraph_id"].split(":")[0].removeprefix("item_")
    index = int(row["paragraph_id"].rsplit(":p", 1)[1])
    return Paragraph(id=row["paragraph_id"], item=item, index=index, text=row["text"])


def score(gold: list[list[str]], pred: list[list[str]], labels: list[str]) -> dict[str, Any]:
    """Multi-label P/R/F1 per class + macro (risk labels with support) + micro + exact match."""
    mlb = MultiLabelBinarizer(classes=labels)
    y_true, y_pred = mlb.fit_transform(gold), mlb.transform(pred)
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, zero_division=0)
    per_class = {
        label: {
            "precision": round(float(p[i]), 4),
            "recall": round(float(r[i]), 4),
            "f1": round(float(f[i]), 4),
            "support": int(s[i]),
        }
        for i, label in enumerate(labels)
    }
    scored = [lab for lab in labels if lab != NONE_LABEL and per_class[lab]["support"] > 0]
    macro = sum(per_class[lab]["f1"] for lab in scored) / len(scored) if scored else None
    _, _, micro, _ = precision_recall_fscore_support(
        y_true, y_pred, average="micro", zero_division=0
    )
    exact = (
        sum(set(g) == set(q) for g, q in zip(gold, pred, strict=True)) / len(gold) if gold else None
    )
    return {
        "per_class": per_class,
        "macro_f1": None if macro is None else round(macro, 4),
        "macro_f1_labels": scored,
        "micro_f1": round(float(micro), 4),
        "exact_match": None if exact is None else round(exact, 4),
    }


def main(results_root: Path | None = None) -> int:
    settings = load_settings()
    rows = [r for r in read_gold(gold_path()) if r["split"] == "test" and r["labels"]]
    errors: list[str] = []
    preds = classify_paragraphs(
        [to_paragraph(r) for r in rows],
        settings.risk_labels,
        LLMClient(),
        settings.risk_label_definitions,
        settings.risk_detector,
        on_error=lambda p, e: errors.append(p.id),
    )
    by_id = {p.paragraph_id: p.labels for p in preds}
    gold = [r["labels"] for r in rows]
    # Failed paragraphs count as predicting "none" so errors are penalised, not dropped.
    predicted = [by_id.get(r["paragraph_id"], [NONE_LABEL]) for r in rows]
    metrics = score(gold, predicted, settings.risk_labels)
    metrics["llm_failures"] = len(errors)
    path = write_results(
        COMPONENT,
        metrics=metrics,
        baseline=None,
        dataset={
            "name": f"gold/{COMPONENT}",
            "n": len(rows),
            "split": "test",
            "labeled_by": sorted({str(r.get("labeled_by")) for r in rows}),
        },
        notes="Gold labels are an agent draft pending human review. TF-IDF baseline pending "
        "(needs a separate training split).",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    lines = [
        json.dumps({"paragraph_id": r["paragraph_id"], "ticker": r["ticker"], "gold": g, "pred": q})
        for r, g, q in zip(rows, gold, predicted, strict=True)
    ]
    predictions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{COMPONENT}: {json.dumps(metrics, indent=1)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
