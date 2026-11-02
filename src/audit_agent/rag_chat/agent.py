"""LangGraph agent: plan -> retrieve -> answer -> verify, with one broader retry (D-018).

- plan (LLM, JSON): rewrite the question into a search query, pick 10-K Items to search and
  decide whether reported figures are needed. Falls back to "question, all Items, figures"
  if the LLM fails.
- retrieve (code): vector search in MongoDB + XBRL-backed figures as evidence items.
- answer (LLM, JSON): 1..N sentences, each citing evidence ids; uncited / unknown ids dropped.
- verify (code): every number in a sentence must appear in the evidence it cites.
- If nothing survives and attempts remain: broaden (raw question, all Items, figures) and
  retrieve again. Otherwise stop with "no_answer" — never an uncited sentence.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, Field

from audit_agent.common.citations import Citation, CitedStatement
from audit_agent.common.config import RagSettings, load_settings
from audit_agent.common.llm_client import LLMClient, LLMError, LLMRateLimitError
from audit_agent.common.tracing import JsonTracer
from audit_agent.rag_chat.chunks import ITEM_TITLES
from audit_agent.rag_chat.retrieval import Retriever
from audit_agent.rag_chat.store import Financials, Hit
from audit_agent.report_generator.evidence import (
    Evidence,
    indicator_evidence,
    kpi_evidence,
)
from audit_agent.report_generator.generator import number_supported, numbers_in

COMPONENT = "rag_chat"
QUOTE_WORDS = 25
NO_ANSWER = "no_answer: the retrieved evidence does not answer the question"
SYSTEM = (
    "You help auditors read a company's annual report (SEC 10-K). You use only the evidence "
    "provided, never outside knowledge, and answer with JSON only."
)

FinancialsSource = Callable[[str, int], Financials | None]


class Plan(BaseModel):
    search_query: str
    items: list[str] = []  # [] = all indexed Items
    use_financials: bool = True
    source: Literal["llm", "fallback", "broadened"] = "llm"


class ChatStatement(CitedStatement):
    evidence_ids: list[str] = Field(min_length=1)


class ChatAnswer(BaseModel):
    question: str
    ticker: str
    fiscal_year: int
    statements: list[ChatStatement]
    status: str  # "ok" | "no_answer: ..." | "skipped: ..." | "error: ..."
    plan: Plan | None = None
    evidence: list[Evidence] = []
    attempts: int = 0
    n_generated: int = 0  # sentences the LLM wrote (last attempt)
    n_dropped: int = 0  # dropped as uncited or with numbers not in the cited evidence


class ChatState(TypedDict, total=False):
    question: str
    ticker: str
    fiscal_year: int
    company_name: str
    plan: Plan
    attempt: int
    evidence: list[Evidence]
    statements: list[ChatStatement]
    n_generated: int
    n_dropped: int
    status: str


Update = dict[str, Any]


# --- plan --------------------------------------------------------------------------------


def plan_messages(question: str, company: str, fiscal_year: int, items: list[str]) -> list[dict]:
    item_lines = "\n".join(f"  - {i}: {ITEM_TITLES.get(i, 'Item ' + i)}" for i in items)
    user = (
        f"Company: {company}, fiscal year {fiscal_year}.\nQuestion: {question}\n\n"
        "Tools:\n"
        "- search_filing: semantic search over paragraphs of these 10-K Items:\n"
        f"{item_lines}\n"
        "- financials: reported XBRL figures (revenue, net income, operating cash flow, cash, "
        "debt, assets, equity, year-over-year growth) and ratios (gross / operating / net "
        "margin, cash conversion, current ratio, debt to equity, liabilities to assets, DSO).\n\n"
        "Plan the lookup. Return JSON: "
        '{"search_query": "<short English search query with the key terms>", '
        '"items": ["<Items to search; [] if unsure>"], '
        '"use_financials": <true if the answer needs reported figures or ratios>}'
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_plan(answer: Any, question: str, allowed_items: list[str]) -> Plan:
    if not isinstance(answer, dict):
        raise LLMError("plan answer is not a JSON object")
    query = str(answer.get("search_query") or "").strip() or question
    raw_items = answer.get("items")
    items = [str(i) for i in raw_items] if isinstance(raw_items, list) else []
    items = [i for i in dict.fromkeys(items) if i in allowed_items]
    use_fin = answer.get("use_financials")
    return Plan(search_query=query, items=items, use_financials=use_fin is not False)


def fallback_plan(question: str, source: Literal["fallback", "broadened"]) -> Plan:
    return Plan(search_query=question, items=[], use_financials=True, source=source)


# --- evidence ----------------------------------------------------------------------------


def _quote(text: str) -> str:
    words = text.split()
    return " ".join(words[:QUOTE_WORDS]) + (" ..." if len(words) > QUOTE_WORDS else "")


def _truncate(text: str, max_words: int) -> str:
    words = text.split()
    return text if len(words) <= max_words else " ".join(words[:max_words]) + " ..."


def paragraph_evidence(hits: list[Hit], max_words: int) -> list[Evidence]:
    items = []
    for n, hit in enumerate(hits, 1):
        c = hit.chunk
        head = f"{c.heading}: " if c.heading else ""
        items.append(
            Evidence(
                id=f"P{n}",
                section=f"item_{c.item}",
                text=f"[Item {c.item}] {head}{_truncate(c.text, max_words)}",
                citations=[
                    Citation(
                        source_type="section",
                        ref=c.paragraph_id,
                        accession=c.accession,
                        quote=_quote(c.text),
                    )
                ],
            )
        )
    return items


def _dedupe(citations: list[Citation]) -> list[Citation]:
    seen: dict[tuple[str, str | None], Citation] = {}
    for c in citations:
        seen.setdefault((c.ref, c.accession), c)
    return list(seen.values())


def financial_evidence(fin: Financials) -> list[Evidence]:
    by_name = {i.name: i for i in fin.indicators}
    rows = kpi_evidence(fin.kpis, fin.prior_kpis, by_name)
    rows += indicator_evidence(by_name, fin.fiscal_year)
    return [
        Evidence(id=f"F{n}", section=section, text=text, citations=_dedupe(cites))
        for n, (section, text, cites) in enumerate(rows, 1)
    ]


# --- answer + verify ---------------------------------------------------------------------


def answer_messages(
    question: str, company: str, fiscal_year: int, evidence: list[Evidence], max_sentences: int
) -> list[dict]:
    lines = "\n".join(f"{e.id} {e.text}" for e in evidence)
    user = (
        f"Evidence from the FY{fiscal_year} 10-K of {company} (P = filing paragraph, "
        f"F = reported figure):\n{lines}\n\nQuestion: {question}\n\n"
        f"Answer in 1 to {max_sentences} sentences.\n"
        "Rules:\n"
        "- Every sentence must cite 1 to 3 evidence ids that support all of its content.\n"
        "- Copy numbers exactly as written in the evidence; do not compute new numbers.\n"
        "- Use only the evidence. If it does not answer the question, return no statements.\n"
        "- No investment advice and no predictions.\n\n"
        'Output format: {"statements": [{"text": "...", "evidence": ["P2", "F1"]}]}'
    )
    return [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]


def parse_answer(
    answer: Any, evidence: list[Evidence], max_sentences: int
) -> tuple[list[ChatStatement], int]:
    """Cited statements and the number of raw statements the model wrote."""
    raw = answer.get("statements") if isinstance(answer, dict) else None
    if not isinstance(raw, list):
        raise LLMError("answer has no 'statements' list")
    by_id = {e.id: e for e in evidence}
    statements: list[ChatStatement] = []
    for item in raw[:max_sentences]:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        ids = item.get("evidence", [])
        valid = [
            i for i in dict.fromkeys(map(str, ids if isinstance(ids, list) else [])) if i in by_id
        ]
        if text and valid:
            cites = _dedupe([c for i in valid for c in by_id[i].citations])
            statements.append(ChatStatement(text=text, citations=cites, evidence_ids=valid))
    return statements, len(raw)


def unsupported_numbers(statement: ChatStatement, evidence: list[Evidence]) -> list[float]:
    by_id = {e.id: e for e in evidence}
    allowed = numbers_in(" ".join(by_id[i].text for i in statement.evidence_ids if i in by_id))
    return [n for n in numbers_in(statement.text) if not number_supported(n, allowed)]


def verify_statements(
    statements: list[ChatStatement], evidence: list[Evidence]
) -> list[ChatStatement]:
    return [s for s in statements if not unsupported_numbers(s, evidence)]


# --- graph -------------------------------------------------------------------------------


class ChatAgent:
    def __init__(
        self,
        retriever: Retriever,
        financials: FinancialsSource,
        llm: LLMClient,
        *,
        settings: RagSettings | None = None,
        tracer: JsonTracer | None = None,
    ) -> None:
        self.retriever = retriever
        self.financials = financials
        self.llm = llm
        self.settings = settings or load_settings().rag
        self.tracer = tracer
        self.graph = self._build()

    # tracing helpers
    @contextmanager
    def _span(self, name: str) -> Iterator[None]:
        with self.tracer.span(COMPONENT, name) if self.tracer else nullcontext():
            yield

    def _log(self, event: str, **payload: Any) -> None:
        if self.tracer:
            self.tracer.log(COMPONENT, event, **payload)

    # nodes
    def plan(self, state: ChatState) -> Update:
        question = state["question"]
        msgs = plan_messages(
            question, state["company_name"], state["fiscal_year"], self.settings.items
        )
        try:
            plan = parse_plan(self.llm.complete_json(msgs), question, self.settings.items)
        except LLMRateLimitError:
            return {"status": "skipped: LLM daily quota exhausted", "attempt": 0}
        except LLMError as exc:
            self._log("plan_fallback", error=str(exc)[:200])
            plan = fallback_plan(question, "fallback")
        self._log("plan", **plan.model_dump())
        return {"plan": plan, "attempt": 0}

    def retrieve(self, state: ChatState) -> Update:
        plan = state["plan"]
        hits = self.retriever.search(
            plan.search_query,
            state["ticker"],
            state["fiscal_year"],
            plan.items or None,
            self.settings.top_k,
        )
        evidence = paragraph_evidence(hits, self.settings.max_paragraph_words)
        fin = (
            self.financials(state["ticker"], state["fiscal_year"]) if plan.use_financials else None
        )
        if fin is not None:
            evidence += financial_evidence(fin)
        self._log("retrieve", paragraphs=[h.chunk.paragraph_id for h in hits], n=len(evidence))
        return {"evidence": evidence, "attempt": state["attempt"] + 1}

    def answer(self, state: ChatState) -> Update:
        msgs = answer_messages(
            state["question"],
            state["company_name"],
            state["fiscal_year"],
            state["evidence"],
            self.settings.max_answer_sentences,
        )
        try:
            raw = self.llm.complete_json(msgs)
            statements, n_raw = parse_answer(
                raw, state["evidence"], self.settings.max_answer_sentences
            )
        except LLMRateLimitError:
            return {"statements": [], "status": "skipped: LLM daily quota exhausted"}
        except LLMError as exc:
            return {"statements": [], "status": f"error: {exc}"[:300]}
        return {"statements": statements, "n_generated": n_raw, "status": "answered"}

    def verify(self, state: ChatState) -> Update:
        kept = verify_statements(state["statements"], state["evidence"])
        dropped = state.get("n_generated", 0) - len(kept)
        self._log("verify", kept=len(kept), dropped=dropped)
        return {
            "statements": kept,
            "n_dropped": dropped,
            "status": "ok" if kept else NO_ANSWER,
        }

    def broaden(self, state: ChatState) -> Update:
        return {"plan": fallback_plan(state["question"], "broadened")}

    # edges
    def after_plan(self, state: ChatState) -> str:
        return "retrieve" if "plan" in state else END

    def after_answer(self, state: ChatState) -> str:
        return "verify" if state.get("status") == "answered" else END

    def after_verify(self, state: ChatState) -> str:
        retry = not state["statements"] and state["attempt"] < self.settings.max_attempts
        return "broaden" if retry else END

    def _build(self) -> CompiledStateGraph:
        g = StateGraph(ChatState)
        for name in ("plan", "retrieve", "answer", "verify", "broaden"):
            node = getattr(self, name)
            g.add_node(name, self._traced(name, node))
        g.add_edge(START, "plan")
        g.add_conditional_edges("plan", self.after_plan, ["retrieve", END])
        g.add_edge("retrieve", "answer")
        g.add_conditional_edges("answer", self.after_answer, ["verify", END])
        g.add_conditional_edges("verify", self.after_verify, ["broaden", END])
        g.add_edge("broaden", "retrieve")
        return g.compile()

    def _traced(self, name: str, node: Callable[[ChatState], Update]) -> Callable:
        def wrapped(state: ChatState) -> Update:
            with self._span(name):
                return node(state)

        return wrapped

    def ask(
        self, question: str, ticker: str, fiscal_year: int, company_name: str = ""
    ) -> ChatAnswer:
        state: ChatState = self.graph.invoke(
            {
                "question": question.strip(),
                "ticker": ticker.upper(),
                "fiscal_year": fiscal_year,
                "company_name": company_name or ticker.upper(),
            }
        )
        return ChatAnswer(
            question=question.strip(),
            ticker=ticker.upper(),
            fiscal_year=fiscal_year,
            statements=state.get("statements", []),
            status=state.get("status", "error: no status"),
            plan=state.get("plan"),
            evidence=state.get("evidence", []),
            attempts=state.get("attempt", 0),
            n_generated=state.get("n_generated", 0),
            n_dropped=state.get("n_dropped", 0),
        )
