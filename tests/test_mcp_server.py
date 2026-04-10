import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.fastmcp import FastMCP
from pydantic_ai.models.test import TestModel

from synapse.cipher_service import CipherService
from synapse.errors import SynapseBadRequestError, SynapseNotFoundError, SynapseTimeoutError
from synapse.mcp_server import (
    _require_server_config,
    build_server,
    resolve_runtime,
    runtime_requirements,
    runtime_requirements_for_workspace,
)
from synapse.service_api import (
    HealthResponse,
    IndexResponse,
    IndexStats,
    IngestBundleResponse,
    KnowledgeApplyResponse,
    KnowledgeBundleDetailResponse,
    KnowledgeBundleSourceSummary,
    KnowledgeCompileBundleResponse,
    KnowledgeOverviewResponse,
    KnowledgeProposalDetail,
    KnowledgeProposalListResponse,
    KnowledgeProposalSummary,
    KnowledgeRejectResponse,
    KnowledgeSourceDetailResponse,
    KnowledgeSourceSegment,
    SearchResponse,
)


def test_resolve_runtime_honors_overrides(tmp_path):
    config = tmp_path / "synapse.toml"
    config.write_text(
        "[vault]\nroot = '~/notes'\n\n[database]\npath = '~/notes/.synapse.sqlite'\n",
        encoding="utf-8",
    )

    settings, root, db = resolve_runtime(
        config_path=str(config),
        vault_root=str(tmp_path / "vault"),
        db_path=str(tmp_path / "db.sqlite"),
    )

    assert settings.config_path == config
    assert root == tmp_path / "vault"
    assert db == tmp_path / "db.sqlite"


def test_runtime_requirements_reports_readiness_fields(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"

    requirements = runtime_requirements(
        config_path="config/synapse.example.toml",
        vault_root=str(vault),
        db_path=str(db),
    )

    assert requirements["vault_root"] == str(vault)
    assert requirements["database_path"] == str(db)
    assert requirements["vault_exists"] is True
    assert requirements["sqlite_vec_python_package"] is True
    assert "note_provider" in requirements
    assert "chunk_provider" in requirements


def test_build_server_returns_fastmcp_instance():
    server = build_server()
    assert isinstance(server, FastMCP)
    tool_names = set(server._tool_manager._tools.keys())
    assert "synapse_health" in tool_names
    assert "synapse_health_simple" in tool_names
    assert "synapse_health_for_workspace" in tool_names
    assert "synapse_cipher_health" in tool_names
    assert "synapse_index_simple" in tool_names
    assert "synapse_index_for_workspace" in tool_names
    assert "synapse_search_simple" in tool_names
    assert "synapse_search_for_workspace" in tool_names
    assert "synapse_cipher_audit" in tool_names
    assert "synapse_cipher_explain" in tool_names
    assert "synapse_cipher_chunking_strategy" in tool_names
    assert "synapse_cipher_review_stubs" in tool_names
    # Knowledge layer parity with the admin UI and HTTP API.
    assert "synapse_ingest_bundle" in tool_names
    assert "synapse_knowledge_overview" in tool_names
    assert "synapse_knowledge_compile_bundle" in tool_names
    assert "synapse_knowledge_list_proposals" in tool_names
    assert "synapse_knowledge_get_proposal" in tool_names
    assert "synapse_knowledge_apply_proposal" in tool_names
    assert "synapse_knowledge_reject_proposal" in tool_names
    assert "synapse_knowledge_bundle_detail" in tool_names
    assert "synapse_knowledge_source_detail" in tool_names


def test_health_tool_schema_describes_plain_string_paths():
    server = build_server()
    params = server._tool_manager._tools["synapse_health"].parameters["properties"]

    assert "plain string filesystem path" in params["vault_root"]["description"].lower()
    assert "nested objects" in params["vault_root"]["description"].lower()
    assert "plain string filesystem path" in params["db_path"]["description"].lower()


def test_index_tool_schema_includes_valid_and_invalid_examples():
    server = build_server()
    description = server._tool_manager._tools["synapse_index"].description

    assert "valid arguments" in description.lower()
    assert "invalid arguments" in description.lower()
    assert "do not encode multiple parameters inside db_path" in description.lower()


def test_search_tool_schema_includes_valid_and_invalid_examples():
    server = build_server()
    description = server._tool_manager._tools["synapse_search"].description
    params = server._tool_manager._tools["synapse_search"].parameters["properties"]

    assert "valid arguments" in description.lower()
    assert "invalid arguments" in description.lower()
    assert "top-level string field" in description.lower()
    assert "top-level field" in params["query"]["description"].lower()


def test_workspace_health_tool_schema_describes_current_handle():
    server = build_server()
    params = server._tool_manager._tools["synapse_health_for_workspace"].parameters["properties"]

    assert "configured synapse workspace" in (
        server._tool_manager._tools["synapse_health_for_workspace"].description.lower()
    )
    assert "workspace" in params
    assert "do not pass filesystem paths" in params["workspace"]["description"].lower()


def test_health_tool_normalizes_common_nested_path_shapes(tmp_path):
    server = build_server()
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_health"].run(
            {
                "config_path": "config/synapse.example.toml",
                "vault_root": {"vault_root": str(vault)},
                "db_path": {str(db): None},
            }
        )

        assert result["vault_root"] == str(vault)
        assert result["database_path"] == str(db)

    anyio.run(exercise)


def test_health_simple_tool_normalizes_collapsed_db_path_blob(monkeypatch, tmp_path):
    server = build_server()
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"

    captured: dict[str, str | None] = {}

    def fake_runtime_requirements(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
    ) -> dict[str, object]:
        captured["config_path"] = config_path
        captured["vault_root"] = vault_root
        captured["db_path"] = db_path
        return {
            "config_path": config_path,
            "vault_root": vault_root,
            "database_path": db_path,
            "ready_for_indexing": True,
        }

    monkeypatch.setattr("synapse.mcp_server.runtime_requirements", fake_runtime_requirements)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_health_simple"].run(
            {
                "db_path": f'{{"{db}"}},vault_root:"{vault}"',
            }
        )

        assert result["vault_root"] == str(vault)
        assert result["database_path"] == str(db)
        assert captured["vault_root"] == str(vault)
        assert captured["db_path"] == str(db)

    anyio.run(exercise)


def test_workspace_health_tool_uses_configured_runtime(monkeypatch):
    captured = {}

    def fake_runtime_requirements_for_workspace(request):
        captured["workspace"] = request.workspace
        return HealthResponse(
            vault_root="/tmp/vault",
            vault_exists=True,
            database_path="/tmp/synapse.sqlite",
            database_exists=True,
            vector_store="sqlite-vec",
            sqlite_vec_python_package=True,
            note_provider={
                "name": "default",
                "type": "ollama",
                "model": "nomic-embed-text:v1.5",
                "base_url": "http://127.0.0.1:11434",
                "dimensions": 768,
                "context_strategy": "full",
            },
            chunk_provider={
                "name": "contextual",
                "type": "ollama",
                "model": "nomic-embed-text:v1.5",
                "base_url": "http://127.0.0.1:11434",
                "dimensions": 768,
                "context_strategy": "full",
            },
            dimensions_match=True,
            requirements={
                "sqlite_vec": True,
                "markdown_folder": True,
                "writable_database_parent": True,
                "embedding_models_configured": True,
            },
            ready_for_indexing=True,
        )

    monkeypatch.setattr(
        "synapse.mcp_server.service_runtime_requirements_for_workspace",
        fake_runtime_requirements_for_workspace,
    )

    result = runtime_requirements_for_workspace()

    assert captured["workspace"] == "current"
    assert result["database_path"] == "/tmp/synapse.sqlite"


def test_index_simple_tool_normalizes_collapsed_db_path_blob(monkeypatch, tmp_path):
    server = build_server()
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"

    def fake_index_vault(request):
        return IndexResponse(
            vault_root=request.vault_root or "",
            database_path=request.db_path or "",
            note_provider="default",
            chunk_provider="contextual",
            stats=IndexStats(total_files=5, indexed=5, unchanged=0, errors=0, total_segments=12),
        )

    monkeypatch.setattr("synapse.mcp_server.index_vault", fake_index_vault)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_index_simple"].run(
            {
                "db_path": f'{{"{db}"}},vault_root:"{vault}"',
            }
        )

        assert result["vault_root"] == str(vault)
        assert result["database_path"] == str(db)

    anyio.run(exercise)


def test_index_for_workspace_tool_uses_current_handle(monkeypatch):
    server = build_server()
    captured = {}

    def fake_index_vault_for_workspace(request):
        captured["workspace"] = request.workspace
        return IndexResponse(
            vault_root="/tmp/vault",
            database_path="/tmp/synapse.sqlite",
            note_provider="default",
            chunk_provider="contextual",
            stats=IndexStats(total_files=5, indexed=5, unchanged=0, errors=0, total_segments=12),
        )

    monkeypatch.setattr("synapse.mcp_server.index_vault_for_workspace", fake_index_vault_for_workspace)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_index_for_workspace"].run({})

        assert captured["workspace"] == "current"
        assert result["database_path"] == "/tmp/synapse.sqlite"

    anyio.run(exercise)


def test_search_tool_normalizes_collapsed_db_path_blob(monkeypatch, tmp_path):
    server = build_server()
    db = tmp_path / "synapse.sqlite"

    def fake_search_index(request):
        return SearchResponse(
            query=request.query,
            mode=request.mode,
            database_path=request.db_path or "",
            results=[],
        )

    monkeypatch.setattr("synapse.mcp_server.search_index", fake_search_index)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_search"].run(
            {
                "db_path": f'{{"{db}"}},mode:"research",query:"cross-paper insights about AI and computer science"',
            }
        )

        assert result["query"] == "cross-paper insights about AI and computer science"
        assert result["mode"] == "research"
        assert result["database_path"] == str(db)

    anyio.run(exercise)


def test_search_simple_tool_normalizes_nested_mode_objects(monkeypatch, tmp_path):
    server = build_server()
    db = tmp_path / "synapse.sqlite"

    def fake_search_index(request):
        return SearchResponse(
            query=request.query,
            mode=request.mode,
            database_path=request.db_path or "",
            results=[],
        )

    monkeypatch.setattr("synapse.mcp_server.search_index", fake_search_index)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_search_simple"].run(
            {
                "query": "signal",
                "db_path": str(db),
                "mode": {"mode": {"mode": 2}},
            }
        )

        assert result["query"] == "signal"
        assert result["mode"] == "research"
        assert result["database_path"] == str(db)

    anyio.run(exercise)


def test_search_for_workspace_tool_uses_current_handle(monkeypatch):
    server = build_server()
    captured = {}

    def fake_search_index_for_workspace(request):
        captured["workspace"] = request.workspace
        return SearchResponse(
            query=request.query,
            mode=request.mode,
            database_path="/tmp/synapse.sqlite",
            results=[],
        )

    monkeypatch.setattr("synapse.mcp_server.search_index_for_workspace", fake_search_index_for_workspace)

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_search_for_workspace"].run(
            {
                "query": "signal",
                "workspace": {"workspace": "current"},
                "mode": {"mode": {"mode": 2}},
            }
        )

        assert captured["workspace"] == "current"
        assert result["query"] == "signal"
        assert result["mode"] == "research"
        assert result["database_path"] == "/tmp/synapse.sqlite"

    anyio.run(exercise)


def test_health_tool_rejects_unrepairable_nested_path_shapes():
    server = build_server()

    async def exercise() -> None:
        with pytest.raises(ToolError, match="db_path must be a plain string path"):
            await server._tool_manager._tools["synapse_health"].run(
                {
                    "config_path": "config/synapse.example.toml",
                    "vault_root": "/tmp/vault",
                    "db_path": {"db_path": True},
                }
            )

    anyio.run(exercise)


def test_example_mcp_config_is_valid_json():
    example_path = Path("config/synapse.mcp.example.json")
    payload = json.loads(example_path.read_text(encoding="utf-8"))
    assert "mcpServers" in payload
    assert "synapse" in payload["mcpServers"]
    assert payload["mcpServers"]["synapse"]["env"]["SYNAPSE_MCP_TRANSPORT"] == "stdio"


def test_mcp_entrypoint_requires_synapse_config(monkeypatch):
    monkeypatch.delenv("SYNAPSE_CONFIG", raising=False)

    with pytest.raises(RuntimeError, match="SYNAPSE_CONFIG is required"):
        _require_server_config()


def test_module_entrypoint_supports_mcp_handshake(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    db = tmp_path / "synapse.sqlite"
    config = tmp_path / "synapse.toml"
    config.write_text(
        f"[vault]\nroot = '{vault}'\n\n[database]\npath = '{db}'\n",
        encoding="utf-8",
    )
    (vault / "alpha.md").write_text("# Alpha\n\nLinks to [[Missing Note]]", encoding="utf-8")

    async def exercise() -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "synapse.mcp_server"],
            cwd=str(Path.cwd()),
            env={"SYNAPSE_CONFIG": str(config)},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.serverInfo.name == "Synapse"

                tools = await session.list_tools()
                tool_names = {tool.name for tool in tools.tools}
                assert "synapse_health" in tool_names
                assert "synapse_health_simple" in tool_names
                assert "synapse_health_for_workspace" in tool_names
                assert "synapse_cipher_health" in tool_names
                assert "synapse_index_simple" in tool_names
                assert "synapse_index_for_workspace" in tool_names
                assert "synapse_search_simple" in tool_names
                assert "synapse_search_for_workspace" in tool_names

                health = await session.call_tool(
                    "synapse_health",
                    {
                        "config_path": "config/synapse.example.toml",
                        "vault_root": str(vault),
                        "db_path": str(db),
                    },
                )
                text_parts = [item.text for item in health.content if hasattr(item, "text")]
                assert any("ready_for_indexing" in text for text in text_parts)

                cipher_health = await session.call_tool(
                    "synapse_cipher_health",
                    {
                        "config_path": "config/synapse.example.toml",
                        "vault_root": str(vault),
                        "db_path": str(db),
                    },
                )
                cipher_health_text = "\n".join(
                    item.text for item in cipher_health.content if hasattr(item, "text")
                )
                assert "ready_for_indexing" in cipher_health_text

                simple_health = await session.call_tool(
                    "synapse_health_simple",
                    {
                        "vault_root": {"vault_root": str(vault)},
                        "db_path": {str(db): None},
                    },
                )
                simple_health_text = "\n".join(
                    item.text for item in simple_health.content if hasattr(item, "text")
                )
                assert "ready_for_indexing" in simple_health_text

                audit = await session.call_tool(
                    "synapse_cipher_audit",
                    {
                        "vault_root": str(vault),
                        "synapse_db": str(db),
                    },
                )
                audit_text = "\n".join(item.text for item in audit.content if hasattr(item, "text"))
                assert "Missing Note" in audit_text

    anyio.run(exercise)


def test_cipher_explain_tool_supports_model_backed_output():
    server = build_server(
        cipher_service=CipherService(
            model=TestModel(custom_output_text="These notes share a semantic memory pattern.")
        ),
    )

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_cipher_explain"].fn(
            doc_a="a.md",
            doc_b="b.md",
        )
        assert "semantic memory" in result["explanation"]

    anyio.run(exercise)


def test_cipher_health_tool_matches_runtime_requirements():
    server = build_server()
    result = server._tool_manager._tools["synapse_cipher_health"].fn(
        config_path="config/synapse.example.toml",
        vault_root="/tmp/vault",
        db_path="/tmp/synapse.sqlite",
    )
    assert result["vault_root"] == "/tmp/vault"
    assert result["database_path"] == "/tmp/synapse.sqlite"


def test_cipher_chunking_tool_reports_structured_timeout_error():
    class TimeoutCipher:
        settings = None

        async def handle(self, request, deps):
            raise SynapseTimeoutError("Cipher reasoning timed out after 1.0 seconds.", timeout_seconds=1.0)

    server = build_server(cipher_service=TimeoutCipher())

    async def exercise() -> None:
        with pytest.raises(RuntimeError) as exc_info:
            await server._tool_manager._tools["synapse_cipher_chunking_strategy"].fn(
                model_info="1024-dim embeddings",
            )
        assert "timeout" in str(exc_info.value)
        assert "1.0" in str(exc_info.value)

    anyio.run(exercise)


# ---------------------------------------------------------------------------
# Research bundle ingest + compiled knowledge layer
# ---------------------------------------------------------------------------


_PROPOSAL_DETAIL_FIXTURE = KnowledgeProposalDetail(
    id=11,
    job_id=7,
    note_kind="source_summary",
    slug="source-attention",
    target_path="_knowledge/sources/bundle-001/source-attention.md",
    title="Attention Is All You Need",
    status="pending",
    body_markdown="# Attention\n\n## Provenance\n\n- bundle: `bundle-001`",
    frontmatter={"note_kind": "source_summary", "title": "Attention Is All You Need"},
    supporting_refs={"bundle_id": "bundle-001", "source_id": "source-attention"},
)


def test_ingest_bundle_tool_delegates_to_service_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_ingest_bundle_artifact(request):
        captured["bundle_path"] = request.bundle_path
        captured["config_path"] = request.config_path
        captured["db_path"] = request.db_path
        captured["provider"] = request.provider
        return IngestBundleResponse(
            bundle_id="bundle-001",
            bundle_path=request.bundle_path,
            database_path=request.db_path or "/tmp/synapse.sqlite",
            provider=request.provider or "default",
            replaced_existing=False,
            source_count=3,
            segment_count=12,
        )

    monkeypatch.setattr("synapse.mcp_server.ingest_bundle_artifact", fake_ingest_bundle_artifact)

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_ingest_bundle"].run(
            {
                "bundle_path": "/tmp/prepared_bundle.json",
                "db_path": "/tmp/synapse.sqlite",
                "provider": "default",
            }
        )
        assert result["bundle_id"] == "bundle-001"
        assert result["source_count"] == 3
        assert result["segment_count"] == 12

    anyio.run(exercise)

    assert captured["bundle_path"] == "/tmp/prepared_bundle.json"
    assert captured["db_path"] == "/tmp/synapse.sqlite"
    assert captured["provider"] == "default"


def test_knowledge_overview_tool_delegates_to_service_api(monkeypatch):
    overview_response = KnowledgeOverviewResponse(
        managed_root="_knowledge",
        vault_root="/tmp/vault",
        counts={"pending": 2, "applied": 1},
        recent_proposals=[
            KnowledgeProposalSummary(
                id=11,
                job_id=7,
                note_kind="source_summary",
                slug="source-attention",
                title="Attention Is All You Need",
                target_path="_knowledge/sources/bundle-001/source-attention.md",
                status="pending",
            )
        ],
    )
    monkeypatch.setattr(
        "synapse.mcp_server.knowledge_overview",
        lambda request: overview_response,
    )

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_overview"].run({})
        assert result["managed_root"] == "_knowledge"
        assert result["counts"]["pending"] == 2
        assert result["recent_proposals"][0]["id"] == 11

    anyio.run(exercise)


def test_knowledge_compile_bundle_tool_delegates_to_service_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_compile(request):
        captured["bundle_id"] = request.bundle_id
        return KnowledgeCompileBundleResponse(
            job_id=7,
            bundle_id=request.bundle_id,
            proposal_ids=[11, 12],
            created_count=2,
        )

    monkeypatch.setattr("synapse.mcp_server.compile_knowledge_bundle", fake_compile)

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_compile_bundle"].run(
            {"bundle_id": "bundle-001"}
        )
        assert result["job_id"] == 7
        assert result["proposal_ids"] == [11, 12]
        assert result["created_count"] == 2

    anyio.run(exercise)

    assert captured["bundle_id"] == "bundle-001"


def test_knowledge_list_proposals_tool_delegates_to_service_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_list(request):
        captured["status"] = request.status
        captured["limit"] = request.limit
        return KnowledgeProposalListResponse(proposals=[_PROPOSAL_DETAIL_FIXTURE])

    monkeypatch.setattr("synapse.mcp_server.list_knowledge_proposals", fake_list)

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_list_proposals"].run(
            {"status": "pending", "limit": 5}
        )
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["id"] == 11
        assert result["proposals"][0]["title"] == "Attention Is All You Need"

    anyio.run(exercise)

    assert captured["status"] == "pending"
    assert captured["limit"] == 5


def test_knowledge_get_proposal_tool_returns_matching_detail(monkeypatch):
    other = _PROPOSAL_DETAIL_FIXTURE.model_copy(update={"id": 99, "title": "Other"})
    monkeypatch.setattr(
        "synapse.mcp_server.list_knowledge_proposals",
        lambda request: KnowledgeProposalListResponse(
            proposals=[other, _PROPOSAL_DETAIL_FIXTURE]
        ),
    )

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_get_proposal"].run(
            {"proposal_id": 11}
        )
        assert result["id"] == 11
        assert result["title"] == "Attention Is All You Need"
        assert result["body_markdown"].startswith("# Attention")

    anyio.run(exercise)


def test_knowledge_get_proposal_tool_raises_not_found(monkeypatch):
    monkeypatch.setattr(
        "synapse.mcp_server.list_knowledge_proposals",
        lambda request: KnowledgeProposalListResponse(proposals=[_PROPOSAL_DETAIL_FIXTURE]),
    )

    server = build_server()

    async def exercise() -> None:
        with pytest.raises(ToolError) as exc_info:
            await server._tool_manager._tools["synapse_knowledge_get_proposal"].run(
                {"proposal_id": 9999}
            )
        assert "Proposal not found" in str(exc_info.value)

    anyio.run(exercise)


def test_knowledge_apply_proposal_tool_delegates_to_service_api(monkeypatch):
    captured: dict[str, object] = {}

    def fake_apply(proposal_id, request):
        captured["proposal_id"] = proposal_id
        captured["vault_root"] = request.vault_root
        return KnowledgeApplyResponse(
            proposal_id=proposal_id,
            target_path="_knowledge/sources/bundle-001/source-attention.md",
            written_path="/tmp/vault/_knowledge/sources/bundle-001/source-attention.md",
            reindexed_files=[
                "_knowledge/sources/bundle-001/source-attention.md",
                "_knowledge/index.md",
                "_knowledge/log.md",
            ],
        )

    monkeypatch.setattr("synapse.mcp_server.apply_knowledge_proposal", fake_apply)

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_apply_proposal"].run(
            {"proposal_id": 11, "vault_root": "/tmp/vault"}
        )
        assert result["proposal_id"] == 11
        assert result["written_path"].endswith("source-attention.md")
        assert any("index.md" in rel for rel in result["reindexed_files"])

    anyio.run(exercise)

    assert captured["proposal_id"] == 11
    assert captured["vault_root"] == "/tmp/vault"


def test_knowledge_reject_proposal_tool_passes_reason_through(monkeypatch):
    captured: dict[str, object] = {}

    def fake_reject(proposal_id, request):
        captured["proposal_id"] = proposal_id
        captured["reason"] = request.reason
        return KnowledgeRejectResponse(
            proposal=_PROPOSAL_DETAIL_FIXTURE.model_copy(
                update={
                    "status": "rejected",
                    "reviewer_action": {"action": "reject", "reason": request.reason or ""},
                }
            )
        )

    monkeypatch.setattr("synapse.mcp_server.reject_knowledge_proposal", fake_reject)

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_reject_proposal"].run(
            {"proposal_id": 11, "reason": "duplicate"}
        )
        assert result["proposal"]["status"] == "rejected"
        assert result["proposal"]["reviewer_action"]["reason"] == "duplicate"

    anyio.run(exercise)

    assert captured["proposal_id"] == 11
    assert captured["reason"] == "duplicate"


def test_knowledge_bundle_detail_tool_delegates_to_service_api(monkeypatch):
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
    monkeypatch.setattr(
        "synapse.mcp_server.knowledge_bundle_detail",
        lambda request: bundle_response,
    )

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_bundle_detail"].run(
            {"bundle_id": "bundle-001"}
        )
        assert result["bundle_id"] == "bundle-001"
        assert result["bundle"]["artifact_path"] == "/tmp/bundle-001.json"
        assert result["sources"][0]["proposal_count"] == 1
        assert result["sources"][0]["title"] == "Attention Is All You Need"

    anyio.run(exercise)


def test_knowledge_source_detail_tool_delegates_to_service_api(monkeypatch):
    source_response = KnowledgeSourceDetailResponse(
        bundle_id="bundle-001",
        source_id="source-attention",
        source={
            "title": "Attention Is All You Need",
            "origin_url": "https://arxiv.org/abs/1706.03762",
            "authors": ["Vaswani", "Shazeer"],
            "summary_text": "Transformer summary.",
        },
        related_proposals=[_PROPOSAL_DETAIL_FIXTURE],
        segments=[
            KnowledgeSourceSegment(
                id=101,
                content_role="summary",
                segment_index=0,
                text="Transformer summary.",
                token_count=3,
                metadata={"bundle_id": "bundle-001", "source_id": "source-attention"},
            )
        ],
    )
    monkeypatch.setattr(
        "synapse.mcp_server.knowledge_source_detail",
        lambda request: source_response,
    )

    server = build_server()

    async def exercise() -> None:
        result = await server._tool_manager._tools["synapse_knowledge_source_detail"].run(
            {"bundle_id": "bundle-001", "source_id": "source-attention"}
        )
        assert result["source"]["title"] == "Attention Is All You Need"
        assert result["segments"][0]["content_role"] == "summary"
        assert result["related_proposals"][0]["id"] == 11

    anyio.run(exercise)


def test_knowledge_tools_respect_feature_gate(monkeypatch):
    """When knowledge.enabled = false the service layer raises a bad-request error."""

    def fake_compile(request):
        raise SynapseBadRequestError(
            "Compiled knowledge layer is disabled. Set knowledge.enabled = true to use this feature."
        )

    monkeypatch.setattr("synapse.mcp_server.compile_knowledge_bundle", fake_compile)

    server = build_server()

    async def exercise() -> None:
        with pytest.raises(ToolError) as exc_info:
            await server._tool_manager._tools["synapse_knowledge_compile_bundle"].run(
                {"bundle_id": "bundle-001"}
            )
        assert "disabled" in str(exc_info.value)
        assert "knowledge.enabled" in str(exc_info.value)

    anyio.run(exercise)


class _MCPFakeEmbedder:
    """Dependency-free embedder that matches the shapes used by the web-api live test."""

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


def _write_live_knowledge_config(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    """Build a config + prepared bundle that the MCP tools can run end to end."""
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
                'managed_root = "_knowledge"',
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
    return vault, db_path, bundle_path, config_path


def test_knowledge_tools_run_end_to_end_against_live_sqlite(tmp_path, monkeypatch):
    """Ingest → compile → apply → list roundtrip through the MCP tool layer."""
    vault, db_path, bundle_path, config_path = _write_live_knowledge_config(tmp_path)

    fake_embedder = _MCPFakeEmbedder()
    monkeypatch.setattr(
        "synapse.service_api.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )
    monkeypatch.setattr(
        "synapse.knowledge_service.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )

    server = build_server()

    async def exercise() -> None:
        ingest_result = await server._tool_manager._tools["synapse_ingest_bundle"].run(
            {
                "bundle_path": str(bundle_path),
                "config_path": str(config_path),
                "db_path": str(db_path),
            }
        )
        assert ingest_result["bundle_id"] == "bundle-001"
        assert ingest_result["source_count"] == 1

        overview = await server._tool_manager._tools["synapse_knowledge_overview"].run(
            {"config_path": str(config_path)}
        )
        assert overview["managed_root"] == "_knowledge"

        compile_result = await server._tool_manager._tools["synapse_knowledge_compile_bundle"].run(
            {"bundle_id": "bundle-001", "config_path": str(config_path)}
        )
        assert compile_result["created_count"] == 1
        proposal_id = compile_result["proposal_ids"][0]

        detail = await server._tool_manager._tools["synapse_knowledge_get_proposal"].run(
            {"proposal_id": proposal_id, "config_path": str(config_path)}
        )
        assert detail["title"] == "Attention Is All You Need"
        assert detail["status"] == "pending"
        assert detail["target_path"] == "_knowledge/sources/bundle-001/source-attention.md"

        bundle_detail = await server._tool_manager._tools["synapse_knowledge_bundle_detail"].run(
            {"bundle_id": "bundle-001", "config_path": str(config_path)}
        )
        assert bundle_detail["sources"][0]["source_id"] == "source-attention"
        assert bundle_detail["sources"][0]["proposal_count"] == 1

        source_detail = await server._tool_manager._tools["synapse_knowledge_source_detail"].run(
            {
                "bundle_id": "bundle-001",
                "source_id": "source-attention",
                "config_path": str(config_path),
            }
        )
        assert source_detail["source"]["title"] == "Attention Is All You Need"
        assert any(seg["content_role"] == "summary" for seg in source_detail["segments"])

        apply_result = await server._tool_manager._tools["synapse_knowledge_apply_proposal"].run(
            {"proposal_id": proposal_id, "config_path": str(config_path)}
        )
        assert apply_result["proposal_id"] == proposal_id
        assert Path(apply_result["written_path"]).exists()

        applied_listing = await server._tool_manager._tools["synapse_knowledge_list_proposals"].run(
            {"status": "applied", "config_path": str(config_path)}
        )
        applied_ids = [row["id"] for row in applied_listing["proposals"]]
        assert proposal_id in applied_ids

    anyio.run(exercise)

    compiled_note = vault / "_knowledge" / "sources" / "bundle-001" / "source-attention.md"
    assert compiled_note.exists()
    assert "Attention Is All You Need" in compiled_note.read_text(encoding="utf-8")
    index_path = vault / "_knowledge" / "index.md"
    log_path = vault / "_knowledge" / "log.md"
    assert "source-attention.md" in index_path.read_text(encoding="utf-8")
    assert "apply :: proposal #" in log_path.read_text(encoding="utf-8")


def test_knowledge_reject_proposal_runs_end_to_end_against_live_sqlite(tmp_path, monkeypatch):
    vault, db_path, bundle_path, config_path = _write_live_knowledge_config(tmp_path)

    fake_embedder = _MCPFakeEmbedder()
    monkeypatch.setattr(
        "synapse.service_api.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )
    monkeypatch.setattr(
        "synapse.knowledge_service.EmbeddingClient.from_provider",
        lambda provider: fake_embedder,
    )

    server = build_server()

    async def exercise() -> None:
        await server._tool_manager._tools["synapse_ingest_bundle"].run(
            {
                "bundle_path": str(bundle_path),
                "config_path": str(config_path),
                "db_path": str(db_path),
            }
        )
        compile_result = await server._tool_manager._tools["synapse_knowledge_compile_bundle"].run(
            {"bundle_id": "bundle-001", "config_path": str(config_path)}
        )
        proposal_id = compile_result["proposal_ids"][0]

        reject_result = await server._tool_manager._tools["synapse_knowledge_reject_proposal"].run(
            {
                "proposal_id": proposal_id,
                "reason": "duplicate",
                "config_path": str(config_path),
            }
        )
        assert reject_result["proposal"]["status"] == "rejected"
        assert reject_result["proposal"]["reviewer_action"]["reason"] == "duplicate"

    anyio.run(exercise)

    log_path = vault / "_knowledge" / "log.md"
    assert "reject :: proposal #" in log_path.read_text(encoding="utf-8")
    assert "duplicate" in log_path.read_text(encoding="utf-8")
