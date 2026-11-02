"""MongoDB store: paragraph vectors (Atlas Vector Search) + one document per company-year.

Collections (database `rag.database`):
- `paragraphs`: one document per Chunk + `embedding` + `embedding_model`; vector index
  `rag.vector_index` with filter fields ticker / fiscal_year / item.
- `company_years`: `_id` "<TICKER>_<FY>", filing metadata, current + prior KPISet and
  indicators (XBRL-backed figures used as evidence for numeric questions).
The connection string comes from env `rag.mongodb_uri_env` or `rag.mongodb_default_uri`;
it is never logged (it may contain a password).
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from pymongo import MongoClient, ReplaceOne
from pymongo.collection import Collection
from pymongo.database import Database
from pymongo.operations import SearchIndexModel

from audit_agent.common.config import RagSettings
from audit_agent.indicator_engine.indicators import Indicator
from audit_agent.kpi_extractor.extractor import KPISet
from audit_agent.rag_chat.chunks import Chunk, filing_key

PARAGRAPHS = "paragraphs"
COMPANY_YEARS = "company_years"
FILTER_FIELDS = ("ticker", "fiscal_year", "item")
INDEX_TIMEOUT_S = 120.0
POLL_S = 1.0


class Hit(BaseModel):
    chunk: Chunk
    score: float


class Financials(BaseModel):
    ticker: str
    fiscal_year: int
    accession: str
    kpis: KPISet
    prior_kpis: KPISet | None
    indicators: list[Indicator]


def mongo_uri(settings: RagSettings) -> str:
    return os.getenv(settings.mongodb_uri_env, "").strip() or settings.mongodb_default_uri


def item_filter(ticker: str, fiscal_year: int, items: Sequence[str] | None) -> dict[str, Any]:
    flt: dict[str, Any] = {"ticker": ticker.upper(), "fiscal_year": fiscal_year}
    if items:
        flt["item"] = {"$in": list(items)}
    return flt


def vector_index_definition(dim: int) -> dict[str, Any]:
    fields: list[dict[str, Any]] = [
        {"type": "vector", "path": "embedding", "numDimensions": dim, "similarity": "cosine"}
    ]
    fields += [{"type": "filter", "path": f} for f in FILTER_FIELDS]
    return {"fields": fields}


def chunk_document(chunk: Chunk, vector: list[float], model: str) -> dict[str, Any]:
    return {"_id": chunk.id, **chunk.model_dump(), "embedding": vector, "embedding_model": model}


class MongoStore:
    def __init__(self, settings: RagSettings, client: MongoClient | None = None) -> None:
        self.settings = settings
        self._client = client

    @property
    def db(self) -> Database:
        if self._client is None:
            self._client = MongoClient(mongo_uri(self.settings), serverSelectionTimeoutMS=5000)
        return self._client[self.settings.database]

    @property
    def paragraphs(self) -> Collection:
        return self.db[PARAGRAPHS]

    @property
    def company_years(self) -> Collection:
        return self.db[COMPANY_YEARS]

    # --- index -------------------------------------------------------------------------

    def _index_info(self) -> dict[str, Any] | None:
        found = list(self.paragraphs.list_search_indexes(self.settings.vector_index))
        return found[0] if found else None

    def ensure_vector_index(self) -> None:
        """Create the vector index if missing and wait until it is queryable."""
        if PARAGRAPHS not in self.db.list_collection_names():
            self.db.create_collection(PARAGRAPHS)
        if self._index_info() is None:
            model = SearchIndexModel(
                name=self.settings.vector_index,
                type="vectorSearch",
                definition=vector_index_definition(self.settings.embedding_dim),
            )
            self.paragraphs.create_search_index(model)
        self._wait(lambda: bool((self._index_info() or {}).get("queryable")))

    def _wait(self, ready: Any) -> None:
        deadline = time.monotonic() + INDEX_TIMEOUT_S
        while not ready():
            if time.monotonic() > deadline:
                raise TimeoutError("MongoDB vector index not ready in time")
            time.sleep(POLL_S)

    # --- writes ------------------------------------------------------------------------

    def upsert_chunks(self, chunks: Sequence[Chunk], vectors: Sequence[list[float]]) -> int:
        ops = [
            ReplaceOne(
                {"_id": c.id}, chunk_document(c, v, self.settings.embedding_model), upsert=True
            )
            for c, v in zip(chunks, vectors, strict=True)
        ]
        return self.paragraphs.bulk_write(ops).upserted_count if ops else 0

    def delete_chunks(self, ticker: str, fiscal_year: int) -> int:
        return self.paragraphs.delete_many(item_filter(ticker, fiscal_year, None)).deleted_count

    def upsert_financials(self, fin: Financials, n_paragraphs: int) -> None:
        doc = {
            "_id": filing_key(fin.ticker, fin.fiscal_year),
            **fin.model_dump(mode="json"),
            "n_paragraphs": n_paragraphs,
            "embedding_model": self.settings.embedding_model,
            "indexed_at": datetime.now(UTC).isoformat(),
        }
        self.company_years.replace_one({"_id": doc["_id"]}, doc, upsert=True)

    def wait_searchable(self, chunk: Chunk, vector: list[float]) -> None:
        """Block until a just-written chunk is returned by vector search (index is async)."""
        self._wait(lambda: chunk.id in {h.chunk.id for h in self.search(vector, chunk, 3)})

    # --- reads -------------------------------------------------------------------------

    def is_indexed(self, ticker: str, fiscal_year: int) -> bool:
        doc = self.company_years.find_one(
            {"_id": filing_key(ticker, fiscal_year)}, {"embedding_model": 1}
        )
        return bool(doc) and doc.get("embedding_model") == self.settings.embedding_model

    def financials(self, ticker: str, fiscal_year: int) -> Financials | None:
        doc = self.company_years.find_one({"_id": filing_key(ticker, fiscal_year)})
        return Financials.model_validate(doc) if doc else None

    def chunks(self, ticker: str, fiscal_year: int) -> list[Chunk]:
        docs = self.paragraphs.find(item_filter(ticker, fiscal_year, None), {"embedding": 0})
        return [Chunk.model_validate(d) for d in docs]

    def vector_search(
        self,
        vector: list[float],
        ticker: str,
        fiscal_year: int,
        items: Sequence[str] | None,
        k: int,
    ) -> list[Hit]:
        stage = {
            "$vectorSearch": {
                "index": self.settings.vector_index,
                "path": "embedding",
                "queryVector": vector,
                "numCandidates": max(self.settings.num_candidates, k),
                "limit": k,
                "filter": item_filter(ticker, fiscal_year, items),
            }
        }
        project = {"$project": {"embedding": 0, "score": {"$meta": "vectorSearchScore"}}}
        docs = self.paragraphs.aggregate([stage, project])
        return [Hit(chunk=Chunk.model_validate(d), score=d["score"]) for d in docs]

    def search(self, vector: list[float], like: Chunk, k: int) -> list[Hit]:
        return self.vector_search(vector, like.ticker, like.fiscal_year, None, k)
