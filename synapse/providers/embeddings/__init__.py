"""Embedding provider adapters."""

from .factory import create_embedding_adapter
from .infinity import InfinityEmbeddingAdapter
from .ollama import OllamaEmbeddingAdapter
from .openai_compatible import OpenAICompatibleEmbeddingAdapter

__all__ = [
    "InfinityEmbeddingAdapter",
    "OllamaEmbeddingAdapter",
    "OpenAICompatibleEmbeddingAdapter",
    "create_embedding_adapter",
]
