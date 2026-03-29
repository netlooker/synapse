"""OpenAI-compatible embedding adapter."""

from __future__ import annotations

from .base import HTTPEndpointEmbeddingAdapter


class OpenAICompatibleEmbeddingAdapter(HTTPEndpointEmbeddingAdapter):
    """Embedding adapter for OpenAI-compatible endpoints."""

    def default_context_strategy(self) -> str:
        return "native_api"

    def _embed_native_contextual_query(self, query: str) -> list[float]:
        return self._embed_contextual_documents([[f"[[{query}]]"]])[0][0]

    def _embed_native_contextual_document_chunks(self, chunks: list[str]) -> list[list[float]]:
        return self._embed_contextual_documents([chunks])[0]

    def _embed_contextual_documents(
        self,
        documents: list[list[str]],
    ) -> list[list[list[float]]]:
        payload = self._embedding_payload(documents)
        data = self._post_json("contextualizedembeddings", payload)
        documents_out: list[list[list[float]]] = []
        for doc in data["data"]:
            documents_out.append(
                [
                    self._validate_embedding_dimension(item["embedding"])
                    for item in doc["data"]
                ]
            )
        return documents_out
