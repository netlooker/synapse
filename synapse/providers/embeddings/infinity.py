"""Infinity embedding adapter."""

from __future__ import annotations

from .base import HTTPEndpointEmbeddingAdapter


class InfinityEmbeddingAdapter(HTTPEndpointEmbeddingAdapter):
    """Embedding adapter for Infinity servers."""

    def default_context_strategy(self) -> str:
        return "infinity_batch"
