"""Eval: rag_chat. Gold: data/gold/rag_chat/questions.jsonl (30 questions, 10 dev / 20 test).

Retrieval (no LLM; the raw question is the query, no Item filter), vector search in MongoDB
vs TF-IDF baseline on the same chunks:
- hit@k: share of questions with >= 1 gold paragraph in the top k (k = 1, 3, 6, 10);
- recall@k: mean share of gold paragraphs in the top k (k = 6, 10);
- mrr@10: mean reciprocal rank of the first gold paragraph.
Only questions with gold paragraphs count; metrics on test, `dev` block for reference.

Answers (LLM agent, test split; skipped with --retrieval-only):
- answered_rate: questions with >= 1 verified sentence;
- faithfulness_rate: verified sentences / sentences the LLM wrote (before the code check);
- citation_correctness: final citations that resolve to an indexed paragraph, XBRL fact or
  indicator of that company-year;
- uncited_statement_count: must be 0;
- gold_evidence_rate: answered questions that cite >= 1 gold paragraph or gold KPI fact.
Run: python -m evals.rag_chat.run_eval [--retrieval-only]
Needs MongoDB (docker compose up -d) and the index (py scripts/build_rag_index.py).
"""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from audit_agent.common.config import PROJECT_ROOT, find_company, load_settings, resolve_path
from audit_agent.common.llm_client import LLMClient
from audit_agent.common.tracing import JsonTracer
from audit_agent.rag_chat.agent import ChatAgent, ChatAnswer
from audit_agent.rag_chat.embeddings import FastEmbedder
from audit_agent.rag_chat.retrieval import Retriever, TfidfRetriever, VectorRetriever
from audit_agent.rag_chat.store import Financials, MongoStore
from evals.common import EVALS_DIR, write_results

COMPONENT = "rag_chat"
GOLD = PROJECT_ROOT / "data" / "gold" / COMPONENT / "questions.jsonl"
HIT_KS = (1, 3, 6, 10)
RECALL_KS = (6, 10)
MAX_K = 10


def load_gold(path: Path = GOLD) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# --- retrieval scoring (pure) --------------------------------------------------------------


def first_hit_rank(ranked: Sequence[str], gold: set[str]) -> int | None:
    return next((i for i, pid in enumerate(ranked, 1) if pid in gold), None)


def score_retrieval(rows: list[tuple[list[str], set[str]]]) -> dict[str, float | None]:
    """rows = (ranked paragraph ids, gold ids) for questions that have gold paragraphs."""
    if not rows:
        return {f"hit@{k}": None for k in HIT_KS}
    n = len(rows)
    out: dict[str, float | None] = {}
    for k in HIT_KS:
        out[f"hit@{k}"] = round(sum(bool(set(r[:k]) & g) for r, g in rows) / n, 4)
    for k in RECALL_KS:
        out[f"recall@{k}"] = round(sum(len(set(r[:k]) & g) / len(g) for r, g in rows) / n, 4)
    ranks = [first_hit_rank(r[:MAX_K], g) for r, g in rows]
    out["mrr@10"] = round(sum(1 / x for x in ranks if x) / n, 4)
    return out


# --- answer scoring (pure) ----------------------------------------------------------------


def gold_refs(question: dict[str, Any], fin: Financials | None) -> set[str]:
    refs = set(question["gold_paragraphs"])
    if fin is not None:
        for name in question["gold_metrics"]:
            kpi = fin.kpis.values.get(name)
            refs |= {c.ref for c in kpi.citations} if kpi else set()
    return refs


def score_answers(rows: list[tuple[ChatAnswer, set[str], set[str]]]) -> dict[str, Any]:
    """rows = (answer, gold refs, known refs of the company-year)."""
    if not rows:
        return {"n": 0}
    answered = [a for a, _, _ in rows if a.statements]
    generated = sum(a.n_generated for a, _, _ in rows)
    kept = sum(len(a.statements) for a, _, _ in rows)
    cites = [(c.ref, known) for a, _, known in rows for s in a.statements for c in s.citations]
    with_gold = sum(
        1
        for a, gold, _ in rows
        if a.statements and {c.ref for s in a.statements for c in s.citations} & gold
    )
    skipped = sum(a.status.startswith("skipped") for a, _, _ in rows)
    return {
        "n": len(rows),
        "skipped_quota": skipped,
        "answered_rate": round(len(answered) / len(rows), 4),
        "faithfulness_rate": round(kept / generated, 4) if generated else None,
        "citation_correctness": (
            round(sum(ref in known for ref, known in cites) / len(cites), 4) if cites else None
        ),
        "uncited_statement_count": sum(
            1 for a, _, _ in rows for s in a.statements if not s.citations
        ),
        "gold_evidence_rate": round(with_gold / len(answered), 4) if answered else None,
        "mean_attempts": round(sum(a.attempts for a, _, _ in rows) / len(rows), 4),
    }


# --- runs ---------------------------------------------------------------------------------


def known_refs(store: MongoStore, ticker: str, fiscal_year: int) -> set[str]:
    refs = {c.paragraph_id for c in store.chunks(ticker, fiscal_year)}
    fin = store.financials(ticker, fiscal_year)
    if fin is not None:
        for kset in [fin.kpis] + ([fin.prior_kpis] if fin.prior_kpis else []):
            refs |= {c.ref for v in kset.values.values() for c in v.citations}
        refs |= {i.citation.ref for i in fin.indicators}
        refs |= {c.ref for i in fin.indicators for c in i.citations}
    return refs


def ranked_ids(retriever: Retriever, q: dict[str, Any]) -> list[str]:
    hits = retriever.search(q["question"], q["ticker"], q["fiscal_year"], None, MAX_K)
    return [h.chunk.paragraph_id for h in hits]


def retrieval_block(
    questions: list[dict[str, Any]], ranked: dict[str, dict[str, list[str]]], method: str
) -> dict[str, float | None]:
    rows = [(ranked[q["id"]][method], set(q["gold_paragraphs"])) for q in questions]
    return score_retrieval([r for r in rows if r[1]])


def main(retrieval_only: bool = False, results_root: Path | None = None) -> int:
    settings = load_settings()
    gold = load_gold()
    store = MongoStore(settings.rag)
    vector = VectorRetriever(store, FastEmbedder(settings.rag))
    tfidf = {t: TfidfRetriever(store.chunks(t, 2024)) for t in {q["ticker"] for q in gold}}
    ranked = {
        q["id"]: {"vector": ranked_ids(vector, q), "tfidf": ranked_ids(tfidf[q["ticker"]], q)}
        for q in gold
    }
    test = [q for q in gold if q["split"] == "test"]
    dev = [q for q in gold if q["split"] == "dev"]
    metrics: dict[str, Any] = retrieval_block(test, ranked, "vector")
    baseline: dict[str, Any] = retrieval_block(test, ranked, "tfidf")
    metrics["dev"] = retrieval_block(dev, ranked, "vector")
    baseline["dev"] = retrieval_block(dev, ranked, "tfidf")

    answers: dict[str, ChatAnswer] = {}
    if not retrieval_only:
        tracer = JsonTracer(resolve_path(settings.tracing.log_dir))
        agent = ChatAgent(vector, store.financials, LLMClient(), tracer=tracer)
        rows = []
        for q in test:
            a = agent.ask(
                q["question"], q["ticker"], q["fiscal_year"], find_company(q["ticker"]).name
            )
            answers[q["id"]] = a
            fin = store.financials(q["ticker"], q["fiscal_year"])
            rows.append((a, gold_refs(q, fin), known_refs(store, q["ticker"], q["fiscal_year"])))
        metrics["answer"] = score_answers(rows)
        baseline["answer"] = None  # no LLM baseline for answers (see D-018)

    write_predictions(gold, ranked, answers, results_root)
    split_n = {"test": len(test), "dev": len(dev)}
    path = write_results(
        COMPONENT,
        metrics,
        dataset={"name": f"gold/{COMPONENT}", "n": len(gold), "split": split_n},
        baseline=baseline,
        notes=(
            "retrieval: raw question as query, no Item filter; baseline = TF-IDF over the "
            "same chunks. answer metrics on test only."
            + (" Retrieval only (--retrieval-only)." if retrieval_only else "")
        ),
        results_root=results_root,
    )
    print(path)
    print(json.dumps({"metrics": metrics, "baseline": baseline}, indent=1))
    return 0


def write_predictions(
    gold: list[dict[str, Any]],
    ranked: dict[str, dict[str, list[str]]],
    answers: dict[str, ChatAnswer],
    results_root: Path | None,
) -> None:
    out = (results_root or EVALS_DIR) / COMPONENT / "results" / "predictions_latest.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for q in gold:
            a = answers.get(q["id"])
            row = {
                "id": q["id"],
                "split": q["split"],
                "question": q["question"],
                "gold_paragraphs": q["gold_paragraphs"],
                "gold_metrics": q["gold_metrics"],
                "vector_top10": ranked[q["id"]]["vector"],
                "tfidf_top10": ranked[q["id"]]["tfidf"],
                "answer": a.model_dump(exclude={"evidence"}) if a else None,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main(retrieval_only="--retrieval-only" in sys.argv))
