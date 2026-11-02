"""rag_chat tests: chunking, store helpers, TF-IDF retrieval, agent parsing/verification and
the LangGraph flow with a fake LLM and retriever (no MongoDB, no network)."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from audit_agent.common.citations import Citation
from audit_agent.common.config import load_settings
from audit_agent.common.llm_client import LLMError, LLMRateLimitError
from audit_agent.filing_loader.loader import Filing, FilingRef, Paragraph, Section
from audit_agent.indicator_engine.indicators import Indicator
from audit_agent.kpi_extractor.extractor import KPISet, KPIValue
from audit_agent.rag_chat.agent import (
    NO_ANSWER,
    ChatAgent,
    ChatStatement,
    financial_evidence,
    paragraph_evidence,
    parse_answer,
    parse_plan,
    verify_statements,
)
from audit_agent.rag_chat.chunks import Chunk, build_chunks
from audit_agent.rag_chat.retrieval import TfidfRetriever
from audit_agent.rag_chat.store import (
    Financials,
    Hit,
    chunk_document,
    item_filter,
    vector_index_definition,
)
from audit_agent.report_generator.evidence import Evidence

END, PRIOR_END = date(2024, 12, 31), date(2023, 12, 31)
ACC = "acc-1"
RAG = load_settings().rag


def _p(pid: str, item: str, text: str, kind: str = "text") -> Paragraph:
    return Paragraph(id=pid, item=item, index=int(pid.split("p")[-1]), kind=kind, text=text)


FILING = Filing(
    ticker="t",
    fiscal_year=2024,
    ref=FilingRef(
        cik="1",
        accession=ACC,
        form="10-K",
        filing_date=date(2025, 2, 1),
        report_date=END,
        primary_document="t.htm",
    ),
    sections={
        "1A": Section(
            item="1A",
            title="Risk Factors",
            paragraphs=[
                _p("item_1A:p1", "1A", "Supply Chain Risks", kind="heading"),
                _p(
                    "item_1A:p2", "1A", "We rely on single source suppliers in Asia for components."
                ),
                _p("item_1A:p3", "1A", "Too short."),
                _p("item_1A:p4", "1A", "Cyber attacks on our systems could disrupt operations."),
            ],
        ),
        "7": Section(
            item="7",
            title="MD&A",
            paragraphs=[
                _p("item_7:p1", "7", "Revenue grew 25% due to higher product sales in Europe."),
            ],
        ),
    },
    tables=[],
)


def _kset(values: dict[str, float], end: date, fy: int) -> KPISet:
    return KPISet(
        ticker="T",
        fiscal_year=fy,
        period_end=end,
        accession=ACC,
        values={
            k: KPIValue(
                name=k,
                value=v,
                unit="USD",
                period_end=end,
                citations=[Citation(source_type="xbrl", ref=f"us-gaap:{k}@{end}", accession=ACC)],
            )
            for k, v in values.items()
        },
    )


FIN = Financials(
    ticker="T",
    fiscal_year=2024,
    accession=ACC,
    kpis=_kset({"revenue": 2_000e6}, END, 2024),
    prior_kpis=_kset({"revenue": 1_600e6}, PRIOR_END, 2023),
    indicators=[
        Indicator(
            name="revenue_growth",
            value=0.25,
            unit="ratio",
            formula="f",
            status="ok",
            period_end=END,
            inputs={},
            citations=[],
        )
    ],
)


# --- chunks / store helpers --------------------------------------------------------------


def test_build_chunks_skips_headings_and_short_text_and_keeps_heading() -> None:
    chunks = build_chunks(FILING, ["1A", "7", "8"], min_words=5)
    assert [c.paragraph_id for c in chunks] == ["item_1A:p2", "item_1A:p4", "item_7:p1"]
    first = chunks[0]
    assert first.id == "T_2024:item_1A:p2" and first.ticker == "T" and first.accession == ACC
    assert first.embed_text.startswith("Supply Chain Risks\n")
    assert chunks[2].heading is None and chunks[2].embed_text == chunks[2].text


def test_item_filter_and_index_definition() -> None:
    assert item_filter("aapl", 2024, None) == {"ticker": "AAPL", "fiscal_year": 2024}
    assert item_filter("aapl", 2024, ["7"])["item"] == {"$in": ["7"]}
    fields = vector_index_definition(384)["fields"]
    assert fields[0]["numDimensions"] == 384
    assert {f["path"] for f in fields[1:]} == {"ticker", "fiscal_year", "item"}


def test_chunk_document_has_id_vector_and_model() -> None:
    chunk = build_chunks(FILING, ["7"], 5)[0]
    doc = chunk_document(chunk, [0.1, 0.2], "m")
    assert (
        doc["_id"] == chunk.id and doc["embedding"] == [0.1, 0.2] and doc["embedding_model"] == "m"
    )


# --- TF-IDF baseline ---------------------------------------------------------------------


def test_tfidf_ranks_lexical_match_first_and_applies_filters() -> None:
    chunks = build_chunks(FILING, ["1A", "7"], 5)
    r = TfidfRetriever(chunks)
    hits = r.search("suppliers in Asia", "T", 2024, None, 2)
    assert hits[0].chunk.paragraph_id == "item_1A:p2"
    assert [h.chunk.item for h in r.search("revenue", "T", 2024, ["7"], 5)] == ["7"]
    assert r.search("revenue", "OTHER", 2024, None, 5) == []


# --- evidence / parsing / verification ---------------------------------------------------


def _hits() -> list[Hit]:
    return [Hit(chunk=c, score=1.0) for c in build_chunks(FILING, ["1A", "7"], 5)]


def test_paragraph_evidence_cites_paragraph_with_accession() -> None:
    ev = paragraph_evidence(_hits(), max_words=4)
    assert [e.id for e in ev] == ["P1", "P2", "P3"]
    assert ev[0].text.startswith("[Item 1A] Supply Chain Risks: We rely on single ...")
    assert ev[0].citations[0].ref == "item_1A:p2" and ev[0].citations[0].accession == ACC


def test_financial_evidence_is_cited_xbrl_and_indicator() -> None:
    ev = financial_evidence(FIN)
    assert ev[0].id == "F1" and "$2.00B" in ev[0].text and "+25.0%" in ev[0].text
    refs = {c.ref for c in ev[0].citations}
    assert "us-gaap:revenue@2024-12-31" in refs and "indicator:revenue_growth" in refs


def test_parse_plan_filters_items_and_falls_back_to_question() -> None:
    plan = parse_plan({"search_query": "", "items": ["7", "9", "7"]}, "q?", ["1A", "7"])
    assert plan.search_query == "q?" and plan.items == ["7"] and plan.use_financials
    assert not parse_plan({"search_query": "x", "use_financials": False}, "q", ["7"]).use_financials
    with pytest.raises(LLMError):
        parse_plan(["not", "a", "dict"], "q", ["7"])


def _ev() -> list[Evidence]:
    return paragraph_evidence(_hits(), 100) + financial_evidence(FIN)


def test_parse_answer_drops_uncited_and_unknown_ids() -> None:
    raw = {
        "statements": [
            {"text": "Suppliers are in Asia.", "evidence": ["P1"]},
            {"text": "Uncited.", "evidence": []},
            {"text": "Unknown id.", "evidence": ["P99"]},
            "garbage",
        ]
    }
    statements, n_raw = parse_answer(raw, _ev(), max_sentences=5)
    assert n_raw == 4 and [s.text for s in statements] == ["Suppliers are in Asia."]
    assert statements[0].citations[0].ref == "item_1A:p2"
    with pytest.raises(LLMError):
        parse_answer({"answer": "x"}, _ev(), 5)


def test_verify_drops_numbers_not_in_cited_evidence() -> None:
    ev = _ev()
    ok = ChatStatement(
        text="Revenue was $2.00B, up 25.0%.",
        citations=ev[3].citations,
        evidence_ids=["F1"],
    )
    wrong = ChatStatement(
        text="Revenue was $2.40B.", citations=ev[3].citations, evidence_ids=["F1"]
    )
    wrong_source = ChatStatement(
        text="Revenue was $2.00B.", citations=ev[0].citations, evidence_ids=["P1"]
    )
    assert verify_statements([ok, wrong, wrong_source], ev) == [ok]


# --- agent graph -------------------------------------------------------------------------


class FakeLLM:
    def __init__(self, answers: list[Any]) -> None:
        self.answers = list(answers)
        self.calls = 0

    def complete_json(self, messages: list[dict[str, str]]) -> Any:
        self.calls += 1
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


class FakeRetriever:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []

    def search(
        self, query: str, ticker: str, fiscal_year: int, items: list[str] | None, k: int
    ) -> list[Hit]:
        self.calls.append((query, items))
        return [h for h in _hits() if not items or h.chunk.item in items][:k]


def _agent(llm: FakeLLM, retriever: FakeRetriever | None = None) -> ChatAgent:
    return ChatAgent(retriever or FakeRetriever(), lambda t, fy: FIN, llm, settings=RAG)  # type: ignore[arg-type]


PLAN = {"search_query": "suppliers", "items": ["1A"], "use_financials": False}


def test_agent_happy_path_one_attempt() -> None:
    llm = FakeLLM([PLAN, {"statements": [{"text": "Suppliers are in Asia.", "evidence": ["P1"]}]}])
    retriever = FakeRetriever()
    answer = _agent(llm, retriever).ask("Where are suppliers?", "t", 2024)
    assert answer.status == "ok" and answer.attempts == 1 and llm.calls == 2
    assert retriever.calls == [("suppliers", ["1A"])]
    assert answer.statements[0].citations[0].ref == "item_1A:p2"
    assert all(e.id.startswith("P") for e in answer.evidence)  # use_financials = False


def test_agent_retries_broadened_when_nothing_verifies() -> None:
    bad = {"statements": [{"text": "Revenue was $9.99B.", "evidence": ["P1"]}]}
    good = {"statements": [{"text": "Revenue was $2.00B.", "evidence": ["F1"]}]}
    retriever = FakeRetriever()
    answer = _agent(FakeLLM([PLAN, bad, good]), retriever).ask("Revenue?", "T", 2024)
    assert answer.status == "ok" and answer.attempts == 2
    assert retriever.calls[1] == ("Revenue?", None)  # broadened: raw question, all Items
    assert answer.plan is not None and answer.plan.source == "broadened"
    assert answer.statements[0].evidence_ids == ["F1"]


def test_agent_stops_with_no_answer_after_max_attempts() -> None:
    empty = {"statements": []}
    answer = _agent(FakeLLM([PLAN] + [empty] * RAG.max_attempts)).ask("?", "T", 2024)
    assert answer.status == NO_ANSWER and answer.statements == []
    assert answer.attempts == RAG.max_attempts


def test_agent_plan_fallback_and_quota() -> None:
    llm = FakeLLM([LLMError("bad json"), {"statements": []}, {"statements": []}])
    answer = _agent(llm).ask("Q?", "T", 2024)
    assert answer.plan is not None and answer.plan.search_query == "Q?"
    quota = _agent(FakeLLM([LLMRateLimitError("quota")])).ask("Q?", "T", 2024)
    assert quota.status.startswith("skipped") and quota.statements == []


def test_agent_graph_shape() -> None:
    graph = _agent(FakeLLM([])).graph.get_graph()
    edges = {(e.source, e.target) for e in graph.edges}
    assert ("retrieve", "answer") in edges and ("broaden", "retrieve") in edges
    assert ("verify", "broaden") in edges and ("verify", "__end__") in edges


def test_chunk_roundtrip_from_mongo_document() -> None:
    chunk = build_chunks(FILING, ["7"], 5)[0]
    doc = chunk_document(chunk, [0.0], "m")
    assert Chunk.model_validate(doc) == chunk


# --- eval scoring --------------------------------------------------------------------------


def test_score_retrieval_hit_recall_mrr() -> None:
    from evals.rag_chat.run_eval import score_retrieval

    rows = [(["a", "b", "c"], {"b", "x"}), (["d", "e"], {"z"})]
    s = score_retrieval(rows)
    assert s["hit@1"] == 0.0 and s["hit@3"] == 0.5 and s["hit@10"] == 0.5
    assert s["recall@6"] == 0.25  # (1/2 + 0/1) / 2
    assert s["mrr@10"] == 0.25  # (1/2 + 0) / 2


def test_score_answers_counts_gold_and_citations() -> None:
    from audit_agent.rag_chat.agent import ChatAnswer
    from evals.rag_chat.run_eval import score_answers

    cite = Citation(source_type="section", ref="item_1A:p2")
    good = ChatAnswer(
        question="q",
        ticker="T",
        fiscal_year=2024,
        statements=[ChatStatement(text="x", citations=[cite], evidence_ids=["P1"])],
        status="ok",
        attempts=1,
        n_generated=2,
    )
    empty = ChatAnswer(question="q", ticker="T", fiscal_year=2024, statements=[], status="no")
    s = score_answers([(good, {"item_1A:p2"}, {"item_1A:p2"}), (empty, {"y"}, set())])
    assert s["answered_rate"] == 0.5 and s["faithfulness_rate"] == 0.5
    assert s["citation_correctness"] == 1.0 and s["uncited_statement_count"] == 0
    assert s["gold_evidence_rate"] == 1.0
