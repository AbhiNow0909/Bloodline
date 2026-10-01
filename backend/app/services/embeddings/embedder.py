"""Text embeddings, computed locally with fastembed (ONNX Runtime, no PyTorch).

The model is loaded on first use and kept for the life of the process: loading costs about
0.3 s and ~170 MB, so the API does not pay for it until a report is indexed or searched.
Report text never leaves the server to be embedded.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol

from app.config import get_settings
from app.models.report_chunk import EMBEDDING_DIMENSIONS

if TYPE_CHECKING:
    from fastembed import TextEmbedding


class EmbeddingError(Exception):
    """The embedding model could not be loaded or run. The message is safe to log and show."""


class Embedder(Protocol):
    """What indexing and search need from an embedding model (the mocking boundary)."""

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """`BAAI/bge-small-en-v1.5` (or the configured model) through fastembed."""

    def __init__(self, model_name: str, cache_dir: str, *, offline: bool, threads: int) -> None:
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._offline = offline
        self._threads = threads
        self._model: TextEmbedding | None = None
        self._lock = threading.Lock()  # background tasks run in a thread pool

    def _load(self) -> TextEmbedding:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding  # heavy: imported on first use only

                try:
                    model = TextEmbedding(
                        self.model_name,
                        cache_dir=self._cache_dir,
                        threads=self._threads,
                        local_files_only=self._offline,
                    )
                except Exception as exc:
                    raise EmbeddingError(
                        f"The embedding model {self.model_name} could not be loaded."
                    ) from exc
                size = model.embedding_size
                if size != EMBEDDING_DIMENSIONS:
                    raise EmbeddingError(
                        f"{self.model_name} makes {size}-dimensional vectors; the database "
                        f"stores {EMBEDDING_DIMENSIONS}."
                    )
                self._model = model
            return self._model

    def embed_passages(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        return [vector.tolist() for vector in model.passage_embed(list(texts), batch_size=8)]

    def embed_query(self, text: str) -> list[float]:
        model = self._load()
        return [float(x) for x in next(iter(model.query_embed(text)))]


@lru_cache
def get_embedder() -> Embedder:
    """The process-wide embedder (one loaded model, shared by indexing and search)."""
    settings = get_settings()
    return FastEmbedder(
        settings.embedding_model,
        str(settings.embedding_cache_dir),
        offline=settings.embedding_offline,
        threads=settings.embedding_threads,
    )
