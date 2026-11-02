"""Ask the rag_chat agent one question from the command line.

Needs the index (`py scripts/build_rag_index.py`) and MongoDB (`docker compose up -d`).
Run: py scripts/ask.py AAPL 2024 "What does Apple say about supply chain risks?"
"""

from __future__ import annotations

import sys

from audit_agent.common.config import find_company, load_settings, resolve_path
from audit_agent.common.llm_client import LLMClient
from audit_agent.common.tracing import JsonTracer
from audit_agent.rag_chat.agent import ChatAgent
from audit_agent.rag_chat.embeddings import FastEmbedder
from audit_agent.rag_chat.retrieval import VectorRetriever
from audit_agent.rag_chat.store import MongoStore


def main(ticker: str, fiscal_year: int, question: str) -> int:
    settings = load_settings()
    store = MongoStore(settings.rag)
    tracer = JsonTracer(resolve_path(settings.tracing.log_dir))
    agent = ChatAgent(
        VectorRetriever(store, FastEmbedder(settings.rag)),
        store.financials,
        LLMClient(),
        tracer=tracer,
    )
    answer = agent.ask(question, ticker, fiscal_year, find_company(ticker).name)
    print(f"status: {answer.status} (attempts {answer.attempts}, dropped {answer.n_dropped})")
    if answer.plan:
        print(f"plan: {answer.plan.model_dump()}")
    for s in answer.statements:
        refs = ", ".join(c.ref for c in s.citations)
        print(f"- {s.text}\n    [{', '.join(s.evidence_ids)}] {refs}")
    print(f"trace: {tracer.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], int(sys.argv[2]), " ".join(sys.argv[3:])))
