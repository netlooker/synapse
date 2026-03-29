"""Shared primitives for embedding provider adapters."""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from urllib import request


class BaseEmbeddingAdapter(ABC):
    """Common interface for embedding backends."""

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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.api_key = api_key
        self.encoding_format = encoding_format
        self.context_strategy = context_strategy

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Generate one embedding."""

    @abstractmethod
    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate a batch of embeddings."""

    def embed_query(self, query: str) -> list[float]:
        """Embed a search query."""
        if self.is_contextual_model():
            return self._embed_contextual_query(query)
        return self.embed(query)

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        """Embed ordered chunks from a single document."""
        if not chunks:
            return []
        if self.is_contextual_model():
            return self._embed_contextual_document_chunks(
                chunks,
                document_title=document_title,
                document_path=document_path,
            )
        return self.embed_batch(chunks)

    def is_contextual_model(self) -> bool:
        return "context" in self.model.lower()

    def _embed_contextual_query(self, query: str) -> list[float]:
        if self.resolved_context_strategy() == "native_api":
            return self._embed_native_contextual_query(query)
        return self.embed(f"[[{query}]]")

    def _embed_contextual_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        strategy = self.resolved_context_strategy()
        if strategy == "native_api":
            return self._embed_native_contextual_document_chunks(chunks)
        if strategy == "infinity_batch":
            return self.embed_batch(chunks)
        return self.embed_batch(
            prepare_contextual_chunks(
                chunks,
                document_title=document_title,
                document_path=document_path,
            )
        )

    def resolved_context_strategy(self) -> str:
        if self.context_strategy != "auto":
            return self.context_strategy
        return self.default_context_strategy()

    def default_context_strategy(self) -> str:
        return "enriched_fallback"

    def _embed_native_contextual_query(self, query: str) -> list[float]:
        return self.embed(f"[[{query}]]")

    def _embed_native_contextual_document_chunks(self, chunks: list[str]) -> list[list[float]]:
        return self.embed_batch(chunks)


class HTTPEndpointEmbeddingAdapter(BaseEmbeddingAdapter):
    """HTTP-based embedding adapter shared by OpenAI-like backends."""

    def _post_json(self, path: str, payload: dict) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = request.Request(
            url=f"{self.base_url}/{path.lstrip('/')}",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with request.urlopen(req) as response:
            return json.loads(response.read().decode("utf-8"))

    def _embedding_payload(self, input_value: str | list[str] | list[list[str]]) -> dict:
        payload = {
            "model": self.model,
            "input": input_value,
        }
        if self.dimensions:
            payload["dimensions"] = self.dimensions
        if self.encoding_format and self.encoding_format != "float":
            payload["encoding_format"] = self.encoding_format
        return payload

    def _validate_embedding_dimension(self, embedding: list[float]) -> list[float]:
        if self.dimensions and len(embedding) != self.dimensions:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self.dimensions}, got {len(embedding)}"
            )
        return embedding

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        payload = self._embedding_payload(text)
        data = self._post_json("embeddings", payload)
        return self._validate_embedding_dimension(data["data"][0]["embedding"])

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload = self._embedding_payload(texts)
        data = self._post_json("embeddings", payload)
        return [
            self._validate_embedding_dimension(item["embedding"])
            for item in data["data"]
        ]


def prepare_contextual_chunks(
    chunks: list[str],
    document_title: str | None = None,
    document_path: str | None = None,
) -> list[str]:
    """Approximate contextual chunk embeddings when joint encoding is unavailable."""
    prepared: list[str] = []
    title_line = f"Document Title: {document_title}" if document_title else None
    path_line = f"Document Path: {document_path}" if document_path else None

    for index, chunk in enumerate(chunks):
        headings = re.findall(r"^#+\s+(.+)$", chunk, flags=re.MULTILINE)
        heading_line = f"Current Section: {' / '.join(headings[:2])}" if headings else None
        prev_line = None
        next_line = None
        if index > 0:
            prev_line = f"Previous Chunk Preview: {compact_preview(chunks[index - 1])}"
        if index + 1 < len(chunks):
            next_line = f"Next Chunk Preview: {compact_preview(chunks[index + 1])}"

        parts = [
            "Contextual Retrieval Record",
            title_line,
            path_line,
            heading_line,
            prev_line,
            next_line,
            "Chunk Body:",
            chunk.strip(),
        ]
        prepared.append("\n".join(part for part in parts if part))
    return prepared


def compact_preview(text: str, limit: int = 180) -> str:
    cleaned = " ".join(text.strip().split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."
