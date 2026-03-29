"""Factory for embedding provider adapters."""

from __future__ import annotations

from .base import BaseEmbeddingAdapter
from .infinity import InfinityEmbeddingAdapter
from .ollama import OllamaEmbeddingAdapter
from .openai_compatible import OpenAICompatibleEmbeddingAdapter


def create_embedding_adapter(
    *,
    provider_type: str,
    base_url: str,
    model: str,
    dimensions: int | None,
    api_key: str | None,
    encoding_format: str,
    context_strategy: str = "auto",
) -> BaseEmbeddingAdapter:
    adapter_map = {
        "ollama": OllamaEmbeddingAdapter,
        "infinity": InfinityEmbeddingAdapter,
        "openai_compatible": OpenAICompatibleEmbeddingAdapter,
    }
    adapter_cls = adapter_map.get(provider_type, OpenAICompatibleEmbeddingAdapter)
    return adapter_cls(
        base_url=base_url,
        model=model,
        dimensions=dimensions,
        api_key=api_key,
        encoding_format=encoding_format,
        context_strategy=context_strategy,
    )
