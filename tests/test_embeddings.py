"""
Tests for synapse.embeddings - Ollama embedding client
"""
import pytest


# Hermetic fake Ollama endpoint
OLLAMA_HOST = "http://127.0.0.1:11434"


def _vector_for(text: str) -> list[float]:
    programming_terms = ("programming", "language", "python", "elixir", "database", "ai")
    score = sum(1 for term in programming_terms if term in text.lower())
    return [
        float(score),
        float(len(text.split())),
        float(sum(ord(ch) for ch in text) % 17),
        1.0,
    ]


class FakeBatchResponse:
    def __init__(self, embeddings):
        self.embeddings = embeddings


class FakeOllamaClient:
    def __init__(self, host):
        self.host = host

    def embeddings(self, model, prompt):
        del model
        return {"embedding": _vector_for(prompt)}

    def embed(self, model, input):
        del model
        return FakeBatchResponse([_vector_for(text) for text in input])


class TestEmbeddingClient:
    """Test embedding generation via Ollama."""

    @pytest.fixture(autouse=True)
    def fake_ollama_client(self, monkeypatch):
        monkeypatch.setattr(
            "synapse.providers.embeddings.ollama.ollama.Client",
            FakeOllamaClient,
        )

    def test_embed_single_text(self):
        """Should generate embedding for a single text."""
        from synapse.embeddings import EmbeddingClient
        
        client = EmbeddingClient(host=OLLAMA_HOST)
        embedding = client.embed("Hello, world!")
        
        assert embedding is not None
        assert len(embedding) == 4
        assert all(isinstance(x, float) for x in embedding)

    def test_embed_returns_different_vectors(self):
        """Different texts should produce different embeddings."""
        from synapse.embeddings import EmbeddingClient
        
        client = EmbeddingClient(host=OLLAMA_HOST)
        
        emb1 = client.embed("Elixir is a functional programming language")
        emb2 = client.embed("Python is an interpreted language")
        emb3 = client.embed("The weather is nice today")
        
        # Embeddings should be different
        assert emb1 != emb2
        assert emb1 != emb3
        
        # But Elixir and Python (both programming) should be more similar
        # than Elixir and weather
        from synapse.embeddings import cosine_similarity
        
        sim_programming = cosine_similarity(emb1, emb2)
        sim_unrelated = cosine_similarity(emb1, emb3)
        
        assert sim_programming > sim_unrelated

    def test_embed_empty_string_raises(self):
        """Empty string should raise an error."""
        from synapse.embeddings import EmbeddingClient
        
        client = EmbeddingClient(host=OLLAMA_HOST)
        
        with pytest.raises(ValueError):
            client.embed("")

    def test_embed_batch(self):
        """Should embed multiple texts efficiently."""
        from synapse.embeddings import EmbeddingClient
        
        client = EmbeddingClient(host=OLLAMA_HOST)
        
        texts = [
            "First document about AI",
            "Second document about databases",
            "Third document about Python",
        ]
        
        embeddings = client.embed_batch(texts)
        
        assert len(embeddings) == 3
        assert all(len(emb) == 4 for emb in embeddings)


class TestCosineSimilarity:
    """Test cosine similarity calculation."""

    def test_identical_vectors(self):
        """Identical vectors should have similarity of 1.0."""
        from synapse.embeddings import cosine_similarity
        
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        sim = cosine_similarity(vec, vec)
        
        assert abs(sim - 1.0) < 0.0001

    def test_orthogonal_vectors(self):
        """Orthogonal vectors should have similarity of 0.0."""
        from synapse.embeddings import cosine_similarity
        
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [0.0, 1.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        
        assert abs(sim - 0.0) < 0.0001

    def test_opposite_vectors(self):
        """Opposite vectors should have similarity of -1.0."""
        from synapse.embeddings import cosine_similarity
        
        vec1 = [1.0, 0.0, 0.0]
        vec2 = [-1.0, 0.0, 0.0]
        sim = cosine_similarity(vec1, vec2)
        
        assert abs(sim - (-1.0)) < 0.0001
