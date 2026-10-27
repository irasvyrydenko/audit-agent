"""Eval: risk_detector — LLM classifier vs TF-IDF + LogReg baseline (D-013, D-015).

Gold: data/gold/risk_detector/paragraphs.jsonl ({paragraph_id, ticker, fy, text, labels,
split, labeled_by}); sample drawn by evals/risk_detector/sample_gold.py.
All methods are scored on the same `test` split:
- LLM: predictions of the production pipeline (`detect_risks` over each filing's Item 1A,
  contiguous batches, served from the LLM cache);
- baseline.gold_dev: TF-IDF + LogReg trained on the gold `dev` split;
- baseline.silver_llm: same model trained on LLM labels of all other Item 1A paragraphs of
  the company set (gold paragraphs excluded) — a distillation reference, not independent.
Metrics per method: per_class {label: {precision, recall, f1, support}}, macro_f1 (risk
labels with support > 0, excluding "none"), micro_f1, exact_match (subset accuracy).
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
from audit_agent.filing_loader.loader import Paragraph, load_filing
from audit_agent.risk_detector.baseline import TfidfLogRegBaseline
from audit_agent.risk_detector.labels import RiskPrediction
from audit_agent.risk_detector.llm_classifier import NONE_LABEL, detect_risks
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


def pipeline_predictions(
    tickers: list[str], fiscal_year: int, client: LLMClient
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """LLM labels and texts for every classified Item 1A paragraph, keyed 'TICKER|id'."""
    settings = load_settings()
    labels: dict[str, list[str]] = {}
    texts: dict[str, str] = {}
    for ticker in tickers:
        filing = load_filing(ticker, fiscal_year)
        paragraphs = filing.sections["1A"].paragraphs
        preds: list[RiskPrediction] = detect_risks(paragraphs, client, settings)
        text_by_id = {p.id: p.text for p in paragraphs}
        for pred in preds:
            key = f"{ticker}|{pred.paragraph_id}"
            labels[key] = pred.labels
            texts[key] = text_by_id[pred.paragraph_id]
    return labels, texts


def _key(row: dict[str, Any]) -> str:
    return f"{row['ticker']}|{row['paragraph_id']}"


def main(results_root: Path | None = None) -> int:
    settings = load_settings()
    labels = settings.risk_labels
    seed = settings.eval.random_seed
    gold_rows = [r for r in read_gold(gold_path()) if r["labels"]]
    dev = [r for r in gold_rows if r["split"] == "dev"]
    test = [r for r in gold_rows if r["split"] == "test"]
    fiscal_year = test[0]["fy"]
    tickers = list(dict.fromkeys(r["ticker"] for r in gold_rows))

    llm_labels, llm_texts = pipeline_predictions(tickers, fiscal_year, LLMClient())
    gold_test = [r["labels"] for r in test]
    test_texts = [r["text"] for r in test]
    # Paragraphs the pipeline did not classify count as "none" (penalised, not dropped).
    llm_pred = [llm_labels.get(_key(r), [NONE_LABEL]) for r in test]

    dev_model = TfidfLogRegBaseline(labels, seed=seed).fit(
        [r["text"] for r in dev], [r["labels"] for r in dev]
    )
    gold_keys = {_key(r) for r in gold_rows}
    silver_keys = [k for k in llm_labels if k not in gold_keys]
    silver_model = TfidfLogRegBaseline(labels, seed=seed).fit(
        [llm_texts[k] for k in silver_keys], [llm_labels[k] for k in silver_keys]
    )
    dev_pred = dev_model.predict_labels(test_texts)
    silver_pred = silver_model.predict_labels(test_texts)

    metrics = score(gold_test, llm_pred, labels)
    metrics["llm_unclassified"] = sum(_key(r) not in llm_labels for r in test)
    baseline = {
        "gold_dev": {**score(gold_test, dev_pred, labels), "train_n": len(dev)},
        "silver_llm": {**score(gold_test, silver_pred, labels), "train_n": len(silver_keys)},
    }
    path = write_results(
        COMPONENT,
        metrics=metrics,
        baseline=baseline,
        dataset={
            "name": f"gold/{COMPONENT}",
            "n": len(test),
            "split": "test",
            "train_n_dev": len(dev),
            "labeled_by": sorted({str(r.get("labeled_by")) for r in gold_rows}),
        },
        notes="Gold labels are an agent draft pending human review; n=40 test paragraphs, "
        "so per-class numbers are noisy. LLM = cached pipeline predictions.",
        results_root=results_root,
    )
    predictions = path.parent / "predictions_latest.jsonl"
    lines = [
        json.dumps(
            {
                "paragraph_id": r["paragraph_id"],
                "ticker": r["ticker"],
                "gold": g,
                "llm": a,
                "baseline_dev": b,
                "baseline_silver": c,
            }
        )
        for r, g, a, b, c in zip(test, gold_test, llm_pred, dev_pred, silver_pred, strict=True)
    ]
    predictions.write_text("\n".join(lines) + "\n", encoding="utf-8")
    summary = {
        name: {k: m[k] for k in ("macro_f1", "micro_f1", "exact_match")}
        for name, m in {"llm": metrics, **baseline}.items()
    }
    print(f"{COMPONENT}: {json.dumps(summary, indent=1)}\n-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
