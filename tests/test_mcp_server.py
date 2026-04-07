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
from synapse.errors import SynapseTimeoutError
from synapse.mcp_server import (
    _require_server_config,
    build_server,
    resolve_runtime,
    runtime_requirements,
    runtime_requirements_for_workspace,
)
from synapse.service_api import HealthResponse, IndexResponse, IndexStats, SearchResponse


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
            stats=IndexStats(total_files=5, indexed=5, unchanged=0, errors=0, total_chunks=12),
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
            stats=IndexStats(total_files=5, indexed=5, unchanged=0, errors=0, total_chunks=12),
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
                "db_path": f'{{"{db}"}},mode:"hybrid",query:"cross-paper insights about AI and computer science"',
            }
        )

        assert result["query"] == "cross-paper insights about AI and computer science"
        assert result["mode"] == "hybrid"
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
        assert result["mode"] == "hybrid"
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
        assert result["mode"] == "hybrid"
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
