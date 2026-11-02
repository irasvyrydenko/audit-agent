"""Local sentence embeddings (fastembed, ONNX). Model name only from settings.rag."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from audit_agent.common.config import RagSettings, resolve_path

BATCH_SIZE = 64


class Embedder(Protocol):
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Lazy wrapper: the model is downloaded/loaded on first use and cached on disk."""

    def __init__(self, settings: RagSettings) -> None:
        self.settings = settings
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is None:
            from fastembed import TextEmbedding  # heavy import, only when needed

            self._model = TextEmbedding(
                self.settings.embedding_model,
                cache_dir=str(resolve_path(self.settings.embedding_cache_dir)),
            )
        return self._model

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._load().embed(list(texts), batch_size=BATCH_SIZE)
        return [v.tolist() for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        # query_embed adds the model's retrieval instruction (bge: "Represent this sentence...")
        return next(iter(self._load().query_embed(text))).tolist()
