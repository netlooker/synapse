"""Tests for Synapse settings and provider configuration."""

import json
import sqlite3
from pathlib import Path

from synapse.embeddings import EmbeddingClient
from synapse.db import Database
from synapse.providers.embeddings import (
    InfinityEmbeddingAdapter,
    OllamaEmbeddingAdapter,
    OpenAICompatibleEmbeddingAdapter,
)
from synapse.settings import load_settings
from synapse.vector_store import SQLiteVecStore, create_vector_store


def test_load_settings_reads_pplx_4b_provider_defaults():
    settings = load_settings("config/synapse.example.toml")

    provider = settings.embedding_provider("default")
    assert provider.type == "infinity"
    assert provider.model == "perplexity-ai/pplx-embed-v1-4b"
    assert provider.base_url == "http://127.0.0.1:8081"
    assert provider.dimensions == 2560

    contextual = settings.contextual_embedding_provider()
    assert contextual.model == "perplexity-ai/pplx-embed-context-v1-4b"
    assert contextual.base_url == "http://127.0.0.1:8081"
    assert contextual.dimensions == 2560
    assert contextual.context_strategy == "infinity_batch"

    assert settings.index.max_chunk_chars == 3200
    assert settings.index.min_chunk_chars == 1200
    assert settings.index.target_chunk_tokens == 480
    assert settings.index.max_chunk_tokens == 900
    assert settings.index.chunk_overlap_chars == 220
    assert settings.index.chunk_strategy == "hybrid"
    assert settings.search.candidate_multiplier == 4
    assert settings.search.note_weight == 0.4
    assert settings.search.chunk_weight == 0.6
    assert settings.cipher.default_timeout_seconds == 45.0
    assert settings.cipher.explain_timeout_seconds == 45.0
    assert settings.cipher.chunking_timeout_seconds == 30.0
    assert settings.cipher.stub_review_timeout_seconds == 45.0
    assert settings.vault.root == "~/notes"
    assert settings.database.path == "~/notes/.synapse.sqlite"


def test_load_settings_uses_generic_defaults_without_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    settings = load_settings()

    assert settings.vault.root == "~/notes"
    assert settings.database.path == "~/notes/.synapse.sqlite"


def test_load_settings_applies_env_overrides(monkeypatch):
    monkeypatch.setenv("SYNAPSE_EMBEDDING_PROVIDER", "fallback")
    monkeypatch.setenv("SYNAPSE_EMBEDDING_BASE_URL", "http://127.0.0.1:11435")
    monkeypatch.setenv("SYNAPSE_EMBEDDING_MODEL", "custom-model")
    monkeypatch.setenv("SYNAPSE_EMBEDDING_DIMENSIONS", "1024")

    settings = load_settings("config/synapse.example.toml")
    provider = settings.embedding_provider()

    assert provider.name == "fallback"
    assert provider.model == "custom-model"
    assert provider.base_url == "http://127.0.0.1:11435"
    assert provider.dimensions == 1024


def test_openai_compatible_embedding_client_uses_provider_dimensions(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            body = {"data": [{"embedding": [0.1, 0.2, 0.3, 0.4]}]}
            return json.dumps(body).encode("utf-8")

    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("synapse.providers.embeddings.base.request.urlopen", fake_urlopen)

    client = EmbeddingClient(
        provider_type="openai_compatible",
        base_url="http://127.0.0.1:7997/v1",
        model="pplx-embed-v1-4b",
        dimensions=4,
    )
    embedding = client.embed("test")

    assert captured["url"] == "http://127.0.0.1:7997/v1/embeddings"
    assert captured["body"]["model"] == "pplx-embed-v1-4b"
    assert embedding == [0.1, 0.2, 0.3, 0.4]


def test_embedding_client_selects_ollama_adapter():
    client = EmbeddingClient(provider_type="ollama")

    assert isinstance(client.adapter, OllamaEmbeddingAdapter)


def test_embedding_client_selects_infinity_adapter():
    client = EmbeddingClient(
        provider_type="infinity",
        base_url="http://127.0.0.1:8081",
        model="perplexity-ai/pplx-embed-v1-4b",
    )

    assert isinstance(client.adapter, InfinityEmbeddingAdapter)
    assert client.adapter.resolved_context_strategy() == "infinity_batch"


def test_embedding_client_selects_openai_compatible_adapter():
    client = EmbeddingClient(
        provider_type="openai_compatible",
        base_url="http://127.0.0.1:7997/v1",
        model="example-embed",
    )

    assert isinstance(client.adapter, OpenAICompatibleEmbeddingAdapter)


def test_embedding_client_allows_explicit_context_strategy_override():
    client = EmbeddingClient(
        provider_type="infinity",
        base_url="http://127.0.0.1:8081",
        model="perplexity-ai/pplx-embed-context-v1-4b",
        context_strategy="enriched_fallback",
    )

    assert client.adapter.resolved_context_strategy() == "enriched_fallback"


def test_create_vector_store_returns_sqlite_wrapper(tmp_path):
    settings = load_settings("config/synapse.example.toml")
    store = create_vector_store(
        settings,
        db_path=tmp_path / "synapse.sqlite",
        embedding_dim=2560,
    )

    assert isinstance(store, SQLiteVecStore)


def test_load_settings_prefers_project_config_location(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "synapse.toml").write_text(
        "[providers.embeddings.default]\n"
        "type = 'infinity'\n"
        "model = 'config-model'\n"
        "base_url = 'http://config.example'\n"
        "dimensions = 42\n",
        encoding="utf-8",
    )
    (tmp_path / "synapse.toml").write_text(
        "[providers.embeddings.default]\n"
        "type = 'infinity'\n"
        "model = 'legacy-model'\n"
        "base_url = 'http://legacy.example'\n"
        "dimensions = 24\n",
        encoding="utf-8",
    )

    settings = load_settings()

    assert settings.config_path == Path("config/synapse.toml")
    assert settings.embedding_provider("default").model == "config-model"


def test_database_prefers_sqlite_vec_python_loader(monkeypatch, tmp_path):
    called = {"loaded": False}

    class FakeSQLiteVec:
        @staticmethod
        def load(conn: sqlite3.Connection) -> None:
            called["loaded"] = True

    def fake_create_schema(self):
        return None

    monkeypatch.setattr("synapse.db.sqlite_vec", FakeSQLiteVec)
    monkeypatch.setattr(Database, "_create_schema", fake_create_schema)

    db = Database(tmp_path / "test.sqlite")
    db.initialize()

    assert called["loaded"] is True
    db.close()


def test_contextual_ollama_fallback_enriches_chunks(monkeypatch):
    captured = {}

    def fake_embed_batch(self, texts):
        captured["texts"] = texts
        return [[0.0, 0.0] for _ in texts]

    monkeypatch.setattr(OllamaEmbeddingAdapter, "embed_batch", fake_embed_batch)

    client = EmbeddingClient(
        provider_type="ollama",
        base_url="http://127.0.0.1:11434",
        model="argus-ai/pplx-embed-context-v1-0.6b:fp32",
        dimensions=2,
    )
    client.embed_document_chunks(
        ["## One\nAlpha", "## Two\nBeta"],
        document_title="Test Doc",
        document_path="vault/test.md",
    )

    assert len(captured["texts"]) == 2
    assert "Document Title: Test Doc" in captured["texts"][0]
    assert "Next Chunk Preview:" in captured["texts"][0]
    assert "Previous Chunk Preview:" in captured["texts"][1]


def test_openai_contextual_embeddings_use_contextual_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            body = {
                "data": [
                    {
                        "data": [
                            {"embedding": [0.1, 0.2]},
                            {"embedding": [0.3, 0.4]},
                        ]
                    }
                ]
            }
            return json.dumps(body).encode("utf-8")

    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("synapse.providers.embeddings.base.request.urlopen", fake_urlopen)

    client = EmbeddingClient(
        provider_type="openai_compatible",
        base_url="http://127.0.0.1:7997/v1",
        model="pplx-embed-context-v1-0.6b",
        dimensions=2,
    )
    embeddings = client.embed_document_chunks(["chunk one", "chunk two"])

    assert captured["url"] == "http://127.0.0.1:7997/v1/contextualizedembeddings"
    assert captured["body"]["input"] == [["chunk one", "chunk two"]]
    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]


def test_infinity_contextual_embeddings_use_batch_embeddings_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            body = {
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            }
            return json.dumps(body).encode("utf-8")

    def fake_urlopen(req):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("synapse.providers.embeddings.base.request.urlopen", fake_urlopen)

    client = EmbeddingClient(
        provider_type="infinity",
        base_url="http://127.0.0.1:8081",
        model="perplexity-ai/pplx-embed-context-v1-4b",
        dimensions=2,
    )
    embeddings = client.embed_document_chunks(["chunk one", "chunk two"])

    assert captured["url"] == "http://127.0.0.1:8081/embeddings"
    assert captured["body"]["input"] == ["chunk one", "chunk two"]
    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]


def test_contextual_query_wraps_query(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            body = {"data": [{"data": [{"embedding": [0.1, 0.2]}]}]}
            return json.dumps(body).encode("utf-8")

    def fake_urlopen(req):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("synapse.providers.embeddings.base.request.urlopen", fake_urlopen)

    client = EmbeddingClient(
        provider_type="openai_compatible",
        base_url="http://127.0.0.1:7997/v1",
        model="pplx-embed-context-v1-0.6b",
        dimensions=2,
    )
    embedding = client.embed_query("hidden links")

    assert captured["body"]["input"] == [["[[hidden links]]"]]
    assert embedding == [0.1, 0.2]
