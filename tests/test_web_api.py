import json
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from synapse.cipher_service import CipherService
from synapse.errors import SynapseDependencyError, SynapseTimeoutError
from synapse.service_api import (
    IngestBundleResponse,
    KnowledgeApplyResponse,
    KnowledgeBundleDetailResponse,
    KnowledgeBundleSourceSummary,
    KnowledgeCompileBundleResponse,
    KnowledgeOverviewResponse,
    KnowledgeProposalDetail,
    KnowledgeProposalListResponse,
    KnowledgeProposalSummary,
    KnowledgeSourceSegment,
    KnowledgeRejectResponse,
    KnowledgeSourceDetailResponse,
    SearchResponse,
    SearchResult,
)
from synapse.web_api import create_app


class RuntimeFakeEmbedder:
    def embed(self, _text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_query(self, _query: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_document_chunks(
        self,
        chunks: list[str],
        document_title: str | None = None,
        document_path: str | None = None,
    ) -> list[list[float]]:
        return [[float(index + 1), 0.0, 0.0, 0.0] for index, _ in enumerate(chunks)]


def test_openapi_exposes_synapse_and_cipher_routes():
    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    payload = response.json()
    assert "/search" in payload["paths"]
    assert "/ingest-bundle" in payload["paths"]
    assert "/knowledge/compile/bundle" in payload["paths"]
    assert "/knowledge/overview" in payload["paths"]
    assert "/knowledge/proposals" in payload["paths"]
    assert "/knowledge/proposals/{proposal_id}/apply" in payload["paths"]
    assert "/knowledge/proposals/{proposal_id}/reject" in payload["paths"]
    assert "/ui/knowledge/sources" in payload["paths"]
    assert "/ui/knowledge/bundles/{bundle_id}" in payload["paths"]
    assert "/ui/knowledge/library" in payload["paths"]
    assert "/ui/knowledge/operations" in payload["paths"]
    assert "/ui/knowledge/logs" in payload["paths"]
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


def test_ingest_bundle_endpoint_uses_shared_service(monkeypatch):
    expected = IngestBundleResponse(
        bundle_id="bundle-123",
        bundle_path="/tmp/prepared_bundle.json",
        database_path="/tmp/synapse.sqlite",
        provider="default",
        replaced_existing=False,
        source_count=2,
        segment_count=5,
    )

    def fake_ingest_bundle_artifact(request):
        assert request.bundle_path == "/tmp/prepared_bundle.json"
        return expected

    monkeypatch.setattr("synapse.web_api.ingest_bundle_artifact", fake_ingest_bundle_artifact)

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)
    response = client.post(
        "/ingest-bundle",
        json={"bundle_path": "/tmp/prepared_bundle.json"},
    )

    assert response.status_code == 200
    assert response.json()["bundle_id"] == "bundle-123"


def test_knowledge_json_routes_use_shared_services(monkeypatch):
    compile_response = KnowledgeCompileBundleResponse(
        job_id=7,
        bundle_id="bundle-001",
        proposal_ids=[11, 12],
        created_count=2,
    )
    overview_response = KnowledgeOverviewResponse(
        managed_root="_compiled",
        vault_root="/tmp/vault",
        counts={"pending": 2},
        recent_proposals=[
            KnowledgeProposalSummary(
                id=11,
                job_id=7,
                note_kind="source_summary",
                slug="source-attention",
                title="Attention Is All You Need",
                target_path="_compiled/sources/bundle-001/source-attention.md",
                status="pending",
            )
        ],
    )
    proposal_detail = KnowledgeProposalDetail(
        id=11,
        job_id=7,
        note_kind="source_summary",
        slug="source-attention",
        target_path="_compiled/sources/bundle-001/source-attention.md",
        title="Attention Is All You Need",
        status="pending",
        body_markdown="# Attention",
        frontmatter={"note_kind": "source_summary"},
        supporting_refs={"bundle_id": "bundle-001", "source_id": "source-attention"},
    )
    proposal_list_response = KnowledgeProposalListResponse(proposals=[proposal_detail])
    apply_response = KnowledgeApplyResponse(
        proposal_id=11,
        target_path="_compiled/sources/bundle-001/source-attention.md",
        written_path="/tmp/vault/_compiled/sources/bundle-001/source-attention.md",
        reindexed_files=[
            "_compiled/sources/bundle-001/source-attention.md",
            "_compiled/index.md",
            "_compiled/log.md",
        ],
    )
    reject_response = KnowledgeRejectResponse(proposal=proposal_detail.model_copy(update={"status": "rejected"}))

    monkeypatch.setattr("synapse.web_api.compile_knowledge_bundle", lambda request: compile_response)
    monkeypatch.setattr("synapse.web_api.knowledge_overview", lambda request: overview_response)
    monkeypatch.setattr("synapse.web_api.list_knowledge_proposals", lambda request: proposal_list_response)
    monkeypatch.setattr("synapse.web_api.apply_knowledge_proposal", lambda proposal_id, request: apply_response)
    monkeypatch.setattr("synapse.web_api.reject_knowledge_proposal", lambda proposal_id, request: reject_response)

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    compile_api = client.post("/knowledge/compile/bundle", json={"bundle_id": "bundle-001"})
    assert compile_api.status_code == 200
    assert compile_api.json()["job_id"] == 7

    overview_api = client.get("/knowledge/overview")
    assert overview_api.status_code == 200
    assert overview_api.json()["counts"]["pending"] == 2

    proposals_api = client.get("/knowledge/proposals")
    assert proposals_api.status_code == 200
    assert proposals_api.json()["proposals"][0]["id"] == 11

    apply_api = client.post("/knowledge/proposals/11/apply", json={})
    assert apply_api.status_code == 200
    assert apply_api.json()["proposal_id"] == 11

    reject_api = client.post("/knowledge/proposals/11/reject", json={"reason": "skip"})
    assert reject_api.status_code == 200
    assert reject_api.json()["proposal"]["status"] == "rejected"


def test_knowledge_ui_routes_render_and_redirect(monkeypatch, tmp_path):
    managed_root = "_compiled"
    log_dir = tmp_path / managed_root
    log_dir.mkdir(parents=True)
    (log_dir / "log.md").write_text(
        "# Compiled knowledge log\n\n"
        "- 2026-04-10T10:00:00Z :: apply :: proposal #11 (source_summary) -> `_compiled/sources/bundle-001/source-attention.md`\n",
        encoding="utf-8",
    )
    overview_response = KnowledgeOverviewResponse(
        managed_root=managed_root,
        vault_root=str(tmp_path),
        counts={"pending": 1, "applied": 1},
        recent_proposals=[
            KnowledgeProposalSummary(
                id=11,
                job_id=7,
                note_kind="source_summary",
                slug="source-attention",
                title="Attention Is All You Need",
                target_path="_compiled/sources/bundle-001/source-attention.md",
                status="pending",
            )
        ],
    )
    proposal_detail = KnowledgeProposalDetail(
        id=11,
        job_id=7,
        note_kind="source_summary",
        slug="source-attention",
        target_path="_compiled/sources/bundle-001/source-attention.md",
        title="Attention Is All You Need",
        status="pending",
        body_markdown="# Attention",
        frontmatter={"note_kind": "source_summary", "title": "Attention Is All You Need"},
        supporting_refs={"bundle_id": "bundle-001", "source_id": "source-attention"},
    )
    proposals_response = KnowledgeProposalListResponse(proposals=[proposal_detail])
    source_response = KnowledgeSourceDetailResponse(
        bundle_id="bundle-001",
        source_id="source-attention",
        source={
            "title": "Attention Is All You Need",
            "origin_url": "https://arxiv.org/abs/1706.03762",
            "authors": ["Vaswani", "Shazeer"],
            "summary_text": "Transformer summary.",
        },
        related_proposals=[proposal_detail],
        segments=[
            KnowledgeSourceSegment(
                id=101,
                content_role="summary",
                segment_index=0,
                text="Transformer summary.",
                token_count=3,
                metadata={"bundle_id": "bundle-001", "source_id": "source-attention"},
            ),
            KnowledgeSourceSegment(
                id=102,
                content_role="full_text",
                segment_index=1,
                text="Multi-head attention and positional encodings.",
                token_count=6,
                metadata={"bundle_id": "bundle-001", "source_id": "source-attention"},
            ),
        ],
    )
    bundle_response = KnowledgeBundleDetailResponse(
        bundle_id="bundle-001",
        bundle={
            "bundle_id": "bundle-001",
            "artifact_path": "/tmp/bundle-001.json",
            "imported_at": "2026-04-10T09:00:00Z",
        },
        sources=[
            KnowledgeBundleSourceSummary(
                bundle_id="bundle-001",
                source_id="source-attention",
                title="Attention Is All You Need",
                source_type="paper",
                published="2017-06-12",
                proposal_count=1,
                applied_count=0,
                latest_status="pending",
            )
        ],
    )

    calls = {"apply": 0, "reject": 0}

    monkeypatch.setattr("synapse.web_api.knowledge_overview", lambda request: overview_response)
    monkeypatch.setattr("synapse.web_api.list_knowledge_proposals", lambda request: proposals_response)
    monkeypatch.setattr("synapse.web_api.knowledge_source_detail", lambda request: source_response)
    monkeypatch.setattr("synapse.web_api.knowledge_bundle_detail", lambda request: bundle_response)
    monkeypatch.setattr(
        "synapse.web_api.apply_knowledge_proposal",
        lambda proposal_id, request: calls.__setitem__("apply", proposal_id) or KnowledgeApplyResponse(
            proposal_id=proposal_id,
            target_path=proposal_detail.target_path,
            written_path=f"/tmp/{proposal_id}.md",
            reindexed_files=[],
        ),
    )
    monkeypatch.setattr(
        "synapse.web_api.reject_knowledge_proposal",
        lambda proposal_id, request: calls.__setitem__("reject", proposal_id) or KnowledgeRejectResponse(
            proposal=proposal_detail.model_copy(update={"status": "rejected"})
        ),
    )

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    overview = client.get("/ui/knowledge/")
    assert overview.status_code == 200
    assert "Knowledge Home" in overview.text
    assert "Pending review" in overview.text

    sources = client.get("/ui/knowledge/sources")
    assert sources.status_code == 200
    assert "Tracked sources" in sources.text

    bundle = client.get("/ui/knowledge/bundles/bundle-001")
    assert bundle.status_code == 200
    assert "Bundle bundle-001" in bundle.text
    assert "Bundle sources" in bundle.text

    source = client.get("/ui/knowledge/sources/bundle-001/source-attention")
    assert source.status_code == 200
    assert "Attention Is All You Need" in source.text
    assert "Contribution summary" in source.text
    assert "Source chunks" in source.text
    assert "Multi-head attention and positional encodings." in source.text

    library = client.get("/ui/knowledge/library")
    assert library.status_code == 200
    assert "Managed library" in library.text

    queue = client.get("/ui/knowledge/proposals")
    assert queue.status_code == 200
    assert "Review Queue" in queue.text

    detail = client.get("/ui/knowledge/proposals/11")
    assert detail.status_code == 200
    assert "Review Item #11" in detail.text
    assert "Supporting references" in detail.text

    operations = client.get("/ui/knowledge/operations")
    assert operations.status_code == 200
    assert "Operational activity" in operations.text
    assert "proposal #11" in operations.text

    logs = client.get("/ui/knowledge/logs")
    assert logs.status_code == 200
    assert "Append-only operational log" in logs.text
    assert "apply :: proposal #11" in logs.text

    apply_ui = client.post("/ui/knowledge/proposals/11/apply", follow_redirects=False)
    assert apply_ui.status_code == 303
    assert apply_ui.headers["location"] == "/ui/knowledge/proposals"
    assert calls["apply"] == 11

    reject_ui = client.post("/ui/knowledge/proposals/11/reject", follow_redirects=False)
    assert reject_ui.status_code == 303
    assert reject_ui.headers["location"] == "/ui/knowledge/proposals"
    assert calls["reject"] == 11


def test_knowledge_routes_return_404_when_disabled():
    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    json_response = client.get(
        "/knowledge/overview",
        params={"config_path": "config/synapse.example.toml"},
    )
    assert json_response.status_code == 404
    assert json_response.json()["detail"]["error_type"] == "not_found"

    html_response = client.get(
        "/ui/knowledge/",
        params={"config_path": "config/synapse.example.toml"},
    )
    assert html_response.status_code == 404
    assert html_response.json()["detail"]["error_type"] == "not_found"


def test_live_ui_apply_route_works_with_runtime_sqlite_wrapper(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    db_path = tmp_path / "synapse.sqlite"
    sidecar = tmp_path / "source.txt"
    sidecar.write_text(
        "The Transformer uses attention-only sequence modeling.\n\n"
        "The second paragraph explains multi-head attention.",
        encoding="utf-8",
    )
    bundle_path = tmp_path / "bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_id": "bundle-001",
                "sources": [
                    {
                        "source_id": "source-attention",
                        "origin_url": "https://example.com/attention",
                        "title": "Attention Is All You Need",
                        "authors": ["Vaswani", "Shazeer"],
                        "published": "2017-06-12",
                        "source_type": "paper",
                        "summary": "Attention-only sequence transduction.",
                        "abstract": "A model built entirely on attention mechanisms.",
                        "full_text_path": sidecar.name,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    config_path = tmp_path / "synapse.toml"
    config_path.write_text(
        "\n".join(
            [
                "[vault]",
                f'root = "{vault}"',
                "",
                "[database]",
                f'path = "{db_path}"',
                "",
                "[index]",
                'provider = "default"',
                'contextual_provider = "default"',
                "",
                "[search]",
                'provider = "default"',
                "",
                "[knowledge]",
                "enabled = true",
                'managed_root = "_compiled"',
                "",
                "[providers.embeddings.default]",
                'type = "ollama"',
                'model = "fake-embed"',
                'base_url = "http://127.0.0.1:11434"',
                "dimensions = 4",
                'encoding_format = "float"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    fake_embedder = RuntimeFakeEmbedder()
    monkeypatch.setattr(
        "synapse.service_api.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )
    monkeypatch.setattr(
        "synapse.knowledge_service.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )

    app = create_app(cipher_service=CipherService(model=TestModel(custom_output_text="linked memory")))
    client = TestClient(app)

    ingest = client.post(
        "/ingest-bundle",
        json={"bundle_path": str(bundle_path), "config_path": str(config_path)},
    )
    assert ingest.status_code == 200
    assert ingest.json()["bundle_id"] == "bundle-001"

    compile_response = client.post(
        "/knowledge/compile/bundle",
        json={"bundle_id": "bundle-001", "config_path": str(config_path)},
    )
    assert compile_response.status_code == 200
    proposal_id = compile_response.json()["proposal_ids"][0]

    apply_response = client.post(
        f"/ui/knowledge/proposals/{proposal_id}/apply",
        params={"config_path": str(config_path)},
        follow_redirects=False,
    )
    assert apply_response.status_code == 303
    assert apply_response.headers["location"] == "/ui/knowledge/proposals"

    proposals = client.get(
        "/knowledge/proposals",
        params={"config_path": str(config_path), "status": "applied"},
    )
    assert proposals.status_code == 200
    assert proposals.json()["proposals"][0]["id"] == proposal_id

    compiled_note = vault / "_compiled" / "sources" / "bundle-001" / "source-attention.md"
    assert compiled_note.exists()
    assert "Attention Is All You Need" in compiled_note.read_text(encoding="utf-8")

    index_path = vault / "_compiled" / "index.md"
    log_path = vault / "_compiled" / "log.md"
    assert index_path.exists()
    assert log_path.exists()
    assert "source-attention.md" in index_path.read_text(encoding="utf-8")
    assert f"apply :: proposal #{proposal_id}" in log_path.read_text(encoding="utf-8")


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
