from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from synapse.cipher_service import CipherService
from synapse.errors import SynapseDependencyError, SynapseTimeoutError
from synapse.service_api import SearchResponse, SearchResult
from synapse.web_api import create_app


def test_openapi_exposes_synapse_and_cipher_routes():
    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert "/search" in payload["paths"]
    assert "/cipher/explain" in payload["paths"]
    assert "/cipher/health" in payload["paths"]
    assert "Synapse API" == payload["info"]["title"]


def test_health_endpoint_reports_runtime(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    response = client.get(
        "/health",
        params={
            "config_path": "config/synapse.example.toml",
            "vault_root": str(vault),
            "db_path": str(db),
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["vault_root"] == str(vault)
    assert payload["database_path"] == str(db)
    assert payload["requirements"]["sqlite_vec"] is True


def test_search_endpoint_uses_shared_service(monkeypatch):
    expected = SearchResponse(
        query="signal",
        mode="research",
        database_path="/tmp/synapse.sqlite",
        results=[
            SearchResult(
                result_kind="source",
                title="Weak Signals",
                bundle_id="bundle-1",
                source_id="source-weak-signals",
                origin_url="https://example.com/weak-signals",
                direct_paper_url=None,
                matched_content_role="summary",
                matched_segment_text="Hidden relationships",
                bm25_score=0.18,
                vector_score=0.72,
                combined_score=0.77,
                rank_reason="lexical rank 1, vector rank 2, matched summary",
            )
        ],
    )

    def fake_search_index(request):
        assert request.query == "signal"
        return expected

    monkeypatch.setattr("synapse.web_api.search_index", fake_search_index)

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    response = client.post(
        "/search",
        json={
            "query": "signal",
            "config_path": "config/synapse.example.toml",
            "db_path": "/tmp/synapse.sqlite",
            "mode": "research",
            "limit": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["results"][0]["title"] == "Weak Signals"
    assert payload["results"][0]["combined_score"] == 0.77


def test_cipher_explain_endpoint_returns_structured_response():
    service = CipherService(
        model=TestModel(custom_output_text="These notes both describe semantic maintenance.")
    )
    app = create_app(cipher_service=service)
    client = TestClient(app)

    response = client.post(
        "/cipher/explain",
        json={"doc_a": "a.md", "doc_b": "b.md"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert "semantic maintenance" in payload["explanation"]


def test_cipher_audit_endpoint_uses_real_request_model(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n\nLinks to [[Missing Note]]", encoding="utf-8")

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="keep it clean")))
    client = TestClient(app)

    response = client.post(
        "/cipher/audit",
        json={
            "mode": "audit",
            "deps": {
                "vault_root": str(vault),
                "synapse_db": str(tmp_path / "synapse.sqlite"),
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["broken_links"][0]["target_link"] == "Missing Note"


def test_cipher_audit_endpoint_honors_config_path(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()

    service = CipherService(model=TestModel(custom_output_text="keep it clean"))
    app = create_app(cipher_service=service)
    client = TestClient(app)

    loaded = {}

    def fake_load_settings(config_path):
        loaded["config_path"] = config_path

        class Settings:
            cipher = object()

        return Settings()

    monkeypatch.setattr("synapse.web_api.load_settings", fake_load_settings)

    response = client.post(
        "/cipher/audit",
        json={
            "mode": "audit",
            "config_path": "config/synapse.example.toml",
            "deps": {
                "vault_root": str(vault),
                "synapse_db": str(tmp_path / "synapse.sqlite"),
            },
        },
    )

    assert response.status_code == 200
    assert loaded["config_path"] == "config/synapse.example.toml"
    assert service.settings is not None


def test_cipher_explain_timeout_maps_to_504():
    class TimeoutCipher:
        settings = None

        async def handle(self, request, deps):
            raise SynapseTimeoutError("Cipher reasoning timed out after 2.0 seconds.", timeout_seconds=2.0)

    app = create_app(cipher_service=TimeoutCipher())
    client = TestClient(app)

    response = client.post(
        "/cipher/explain",
        json={"doc_a": "a.md", "doc_b": "b.md"},
    )

    assert response.status_code == 504
    payload = response.json()
    assert payload["detail"]["error_type"] == "timeout"
    assert payload["detail"]["timeout_seconds"] == 2.0


def test_cipher_explain_dependency_failure_maps_to_424():
    class DependencyCipher:
        settings = None

        async def handle(self, request, deps):
            raise SynapseDependencyError(
                "Cipher reasoning backend is not configured.",
                dependency="reasoning_model",
                retryable=False,
            )

    app = create_app(cipher_service=DependencyCipher())
    client = TestClient(app)

    response = client.post(
        "/cipher/explain",
        json={"doc_a": "a.md", "doc_b": "b.md"},
    )

    assert response.status_code == 424
    payload = response.json()
    assert payload["detail"]["error_type"] == "dependency_unavailable"
    assert payload["detail"]["dependency"] == "reasoning_model"
