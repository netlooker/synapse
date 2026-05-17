"""Pure local hashed embedding fallback adapter."""

from __future__ import annotations

import hashlib
import math
import re

import numpy as np

from .base import BaseEmbeddingAdapter


class LocalHashEmbeddingAdapter(BaseEmbeddingAdapter):
    """Deterministic local embedding adapter with no network dependency."""

    def embed(self, text: str) -> list[float]:
        if not text or not text.strip():
            raise ValueError("Cannot embed empty text")
        dims = int(self.dimensions or 768)
        vector = np.zeros(dims, dtype=np.float32)
        tokens = re.findall(r"\w+", text.lower())
        if not tokens:
            return vector.tolist()

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            first = int.from_bytes(digest[:8], "little", signed=False)
            second = int.from_bytes(digest[8:16], "little", signed=False)
            third = int.from_bytes(digest[16:24], "little", signed=False)

            vector[first % dims] += 1.0
            vector[second % dims] -= 1.0
            vector[third % dims] += 0.5

        norm = float(np.linalg.norm(vector))
        if math.isfinite(norm) and norm > 0:
            vector /= norm
        return vector.astype(float).tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]
