from __future__ import annotations

from pathlib import Path

import pytest

from synapse.service_api import (
    BrokenLinkResult,
    DiscoverResponse,
    DiscoveryResult,
    HealthResponse,
    IndexResponse,
    IndexStats,
    ProviderSummary,
    RequirementSummary,
    SearchResponse,
    SearchResult,
    ValidateResponse,
)
from synapse.smoke import run_smoke


def _health_response(db_path: str) -> HealthResponse:
    provider = ProviderSummary(
        name="default",
        type="infinity",
        model="example",
        base_url="http://127.0.0.1:8081",
        dimensions=2560,
        context_strategy="infinity_batch",
    )
    return HealthResponse(
        config_path="config/synapse.example.toml",
        vault_root="vault",
        vault_exists=True,
        database_path=db_path,
        database_exists=False,
        vector_store="sqlite_vec",
        sqlite_vec_python_package=True,
        note_provider=provider,
        chunk_provider=provider,
        dimensions_match=True,
        reasoning_model=None,
        requirements=RequirementSummary(
            sqlite_vec=True,
            markdown_folder=True,
            writable_database_parent=True,
            embedding_models_configured=True,
        ),
        ready_for_indexing=True,
    )


def _patch_smoke_dependencies(monkeypatch):
    from synapse.settings import load_settings as real_load_settings

    monkeypatch.setattr("synapse.smoke.load_settings", lambda config: real_load_settings("config/synapse.example.toml"))
    monkeypatch.setattr(
        "synapse.smoke.runtime_requirements",
        lambda request: _health_response(request.db_path or "db.sqlite"),
    )
    monkeypatch.setattr(
        "synapse.smoke.index_vault",
        lambda request: IndexResponse(
            vault_root=request.vault_root or "vault",
            database_path=request.db_path or "db.sqlite",
            note_provider="default",
            chunk_provider="contextual",
            stats=IndexStats(total_files=8, indexed=8, unchanged=0, errors=0, total_chunks=8),
        ),
    )
    monkeypatch.setattr(
        "synapse.smoke.search_index",
        lambda request: SearchResponse(
            query=request.query,
            mode=request.mode,
            database_path=request.db_path or "db.sqlite",
            results=[
                SearchResult(
                    path="weak-signals.md",
                    title="Weak Signals",
                    similarity=0.73,
                    snippet="snippet",
                ),
                SearchResult(
                    path="agency-memory.md",
                    title="Agency Memory",
                    similarity=0.70,
                    snippet="snippet",
                ),
            ],
        ),
    )
    monkeypatch.setattr(
        "synapse.smoke.discover_index",
        lambda request: DiscoverResponse(
            database_path=request.db_path or "db.sqlite",
            threshold=request.threshold,
            discoveries=[
                DiscoveryResult(
                    source_path="agency-memory.md",
                    source_title="Agency Memory",
                    target_path="weak-signals.md",
                    target_title="Weak Signals",
                    similarity=0.42,
                    semantic_similarity=0.38,
                    metadata_score=0.02,
                    graph_score=0.02,
                )
            ],
        ),
    )
    monkeypatch.setattr(
        "synapse.smoke.validate_index",
        lambda request: ValidateResponse(
            database_path=request.db_path or "db.sqlite",
            broken_links=[],
        ),
    )

    async def fake_cultivate(*args, **kwargs):
        return None

    monkeypatch.setattr("synapse.smoke.cultivate", fake_cultivate)


def test_run_smoke_refuses_existing_db_without_reuse(tmp_path):
    db_path = tmp_path / "existing.sqlite"
    db_path.write_text("occupied", encoding="utf-8")

    with pytest.raises(ValueError, match="Refusing to reuse existing database path"):
        run_smoke(
            config_path="config/synapse.example.toml",
            db_path=str(db_path),
        )


def test_run_smoke_uses_temp_db_and_skips_cipher_by_default(monkeypatch):
    _patch_smoke_dependencies(monkeypatch)
    monkeypatch.setattr("synapse.smoke.reasoning_env_configured", lambda: False)

    result = run_smoke(with_cipher="auto")

    assert result.used_temporary_db is True
    assert result.indexed_files == 8
    assert result.discovery_count == 1
    assert result.broken_link_count == 0
    assert result.cipher_status == "skipped"
    assert not Path(result.db_path).exists()


def test_run_smoke_runs_cipher_when_reasoning_env_is_available(monkeypatch):
    _patch_smoke_dependencies(monkeypatch)
    monkeypatch.setattr("synapse.smoke.reasoning_env_configured", lambda: True)

    class FakeCipherResponse:
        explanation = "These notes both describe retrieval maintenance."

    class FakeCipherService:
        async def handle(self, request, deps):
            return FakeCipherResponse()

    monkeypatch.setattr("synapse.smoke.CipherService", FakeCipherService)

    result = run_smoke(with_cipher="auto")

    assert result.cipher_status == "passed"
    assert "retrieval maintenance" in (result.cipher_summary or "")
