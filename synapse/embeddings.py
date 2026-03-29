"""
synapse.embeddings - Embedding client facade
"""

from __future__ import annotations

import math
from typing import Protocol

from .providers.embeddings import create_embedding_adapter
from .providers.embeddings.base import BaseEmbeddingAdapter, prepare_contextual_chunks
from .settings import ProviderSettings


class EmbeddingService(Protocol):
    """Behavior required by indexing and search services."""

    def embed(self, text: str) -> list[float]:
        """Generate one embedding."""

    def embed_query(self, query: str) -> list[float]:
        """Generate a query embedding."""

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        """Generate embeddings for ordered chunks from one document."""


class EmbeddingClient:
    """Stable facade over provider-specific embedding adapters."""

    def __init__(
        self,
        provider_type: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        model: str = "nomic-embed-text:v1.5",
        dimensions: int | None = 768,
        api_key: str | None = None,
        encoding_format: str = "float",
        context_strategy: str = "auto",
        host: str | None = None,
    ):
        self.provider_type = provider_type
        self.base_url = (host or base_url).rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key
        self.encoding_format = encoding_format
        self.context_strategy = context_strategy
        self.adapter = create_embedding_adapter(
            provider_type=provider_type,
            base_url=self.base_url,
            model=model,
            dimensions=dimensions,
            api_key=api_key,
            encoding_format=encoding_format,
            context_strategy=context_strategy,
        )

    @classmethod
    def from_provider(cls, provider: ProviderSettings) -> "EmbeddingClient":
        return cls(
            provider_type=provider.type,
            base_url=provider.base_url,
            model=provider.model,
            dimensions=provider.dimensions,
            api_key=provider.api_key(),
            encoding_format=provider.encoding_format,
            context_strategy=provider.context_strategy,
        )

    def embed(self, text: str) -> list[float]:
        return self.adapter.embed(text)

    def embed_query(self, query: str) -> list[float]:
        return self.adapter.embed_query(query)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self.adapter.embed_batch(texts)

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        return self.adapter.embed_document_chunks(
            chunks,
            document_title=document_title,
            document_path=document_path,
        )

    def is_contextual_model(self) -> bool:
        return self.adapter.is_contextual_model()


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)


__all__ = [
    "BaseEmbeddingAdapter",
    "EmbeddingClient",
    "EmbeddingService",
    "cosine_similarity",
    "prepare_contextual_chunks",
]
