"""Retrievers with one interface: vector search in MongoDB, and a TF-IDF baseline."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import linear_kernel

from audit_agent.rag_chat.chunks import Chunk
from audit_agent.rag_chat.embeddings import Embedder
from audit_agent.rag_chat.store import Hit, MongoStore


class Retriever(Protocol):
    def search(
        self, query: str, ticker: str, fiscal_year: int, items: Sequence[str] | None, k: int
    ) -> list[Hit]: ...


class VectorRetriever:
    def __init__(self, store: MongoStore, embedder: Embedder) -> None:
        self.store = store
        self.embedder = embedder

    def search(
        self, query: str, ticker: str, fiscal_year: int, items: Sequence[str] | None, k: int
    ) -> list[Hit]:
        vector = self.embedder.embed_query(query)
        return self.store.vector_search(vector, ticker, fiscal_year, items, k)


class TfidfRetriever:
    """Lexical baseline over the same chunks (fit per company-year, same filters)."""

    def __init__(self, chunks: Sequence[Chunk]) -> None:
        self.chunks = list(chunks)
        self.vectorizer = TfidfVectorizer(
            stop_words="english", sublinear_tf=True, ngram_range=(1, 2)
        )
        self.matrix = self.vectorizer.fit_transform([c.embed_text for c in self.chunks])

    def search(
        self, query: str, ticker: str, fiscal_year: int, items: Sequence[str] | None, k: int
    ) -> list[Hit]:
        scores = linear_kernel(self.vectorizer.transform([query]), self.matrix).ravel()
        allowed = [
            i
            for i, c in enumerate(self.chunks)
            if c.ticker == ticker.upper()
            and c.fiscal_year == fiscal_year
            and (not items or c.item in items)
        ]
        ranked = sorted(allowed, key=lambda i: (-scores[i], i))[:k]
        return [Hit(chunk=self.chunks[i], score=float(scores[i])) for i in ranked]
