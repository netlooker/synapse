"""Ollama embedding adapter."""

from __future__ import annotations

import ollama

from .base import BaseEmbeddingAdapter


class OllamaEmbeddingAdapter(BaseEmbeddingAdapter):
    """Embedding adapter for Ollama."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dimensions: int | None,
        api_key: str | None,
        encoding_format: str,
        context_strategy: str = "auto",
    ) -> None:
        super().__init__(
            base_url=base_url,
            model=model,
            dimensions=dimensions,
            api_key=api_key,
            encoding_format=encoding_format,
            context_strategy=context_strategy,
        )
        self.client = ollama.Client(host=self.base_url)

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        response = self.client.embeddings(model=self.model, prompt=text)
        return response["embedding"]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = self.client.embed(model=self.model, input=texts)
        return response.embeddings
