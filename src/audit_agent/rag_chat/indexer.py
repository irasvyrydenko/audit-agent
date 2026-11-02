"""Build the rag_chat index for one company-year from the cached component outputs."""

from __future__ import annotations

from pydantic import BaseModel

from audit_agent.common.config import RagSettings, find_company, load_settings
from audit_agent.common.edgar_client import EdgarClient
from audit_agent.filing_loader.loader import load_filing
from audit_agent.indicator_engine.indicators import compute_all
from audit_agent.kpi_extractor.extractor import load_kpis
from audit_agent.rag_chat.chunks import build_chunks
from audit_agent.rag_chat.embeddings import Embedder
from audit_agent.rag_chat.store import Financials, MongoStore


class IndexStats(BaseModel):
    ticker: str
    fiscal_year: int
    n_paragraphs: int
    skipped: bool = False  # already indexed with the same embedding model


def index_company(
    ticker: str,
    fiscal_year: int,
    store: MongoStore,
    embedder: Embedder,
    *,
    edgar: EdgarClient | None = None,
    refresh: bool = False,
    rag: RagSettings | None = None,
) -> IndexStats:
    """Embed filing paragraphs and store them with the company-year's XBRL figures."""
    settings = load_settings()
    rag = rag or settings.rag
    if not refresh and store.is_indexed(ticker, fiscal_year):
        return IndexStats(
            ticker=ticker.upper(), fiscal_year=fiscal_year, n_paragraphs=0, skipped=True
        )
    edgar = edgar or EdgarClient()
    company = find_company(ticker)
    filing = load_filing(company.ticker, fiscal_year, client=edgar)
    current, prior = load_kpis(company.ticker, fiscal_year, filing.ref, client=edgar)
    indicators = compute_all(current, prior, settings.indicators, is_bank=company.bank)

    chunks = build_chunks(filing, rag.items, rag.min_words)
    vectors = embedder.embed_documents([c.embed_text for c in chunks])
    store.ensure_vector_index()
    store.delete_chunks(company.ticker, fiscal_year)
    store.upsert_chunks(chunks, vectors)
    fin = Financials(
        ticker=company.ticker,
        fiscal_year=fiscal_year,
        accession=filing.ref.accession,
        kpis=current,
        prior_kpis=prior,
        indicators=indicators,
    )
    if chunks:
        store.wait_searchable(chunks[-1], vectors[-1])
    store.upsert_financials(fin, len(chunks))
    return IndexStats(ticker=company.ticker, fiscal_year=fiscal_year, n_paragraphs=len(chunks))
