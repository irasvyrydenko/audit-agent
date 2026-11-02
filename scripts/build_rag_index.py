"""Build the rag_chat MongoDB index (paragraph vectors + XBRL figures) for every company.

Needs MongoDB with Atlas Vector Search: `docker compose up -d` (see docker-compose.yml).
Uses cached filings / companyfacts; downloads from EDGAR only what is missing.

Run: py scripts/build_rag_index.py [fiscal_year] [--refresh]
"""

from __future__ import annotations

import sys
import time

from audit_agent.common.config import load_companies, load_settings
from audit_agent.rag_chat.embeddings import FastEmbedder
from audit_agent.rag_chat.indexer import index_company
from audit_agent.rag_chat.store import MongoStore


def main(fiscal_year: int | None = None, refresh: bool = False) -> int:
    rag = load_settings().rag
    companies = load_companies()
    fy = fiscal_year or companies.default_fiscal_year
    store, embedder = MongoStore(rag), FastEmbedder(rag)
    for company in companies.companies:
        start = time.perf_counter()
        stats = index_company(company.ticker, fy, store, embedder, refresh=refresh, rag=rag)
        state = "already indexed" if stats.skipped else f"{stats.n_paragraphs} paragraphs"
        print(f"{stats.ticker} FY{fy}: {state} ({time.perf_counter() - start:.1f} s)")
    return 0


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raise SystemExit(main(int(args[0]) if args else None, refresh="--refresh" in sys.argv))
