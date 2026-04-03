import json
import sys
from pathlib import Path

import anyio
import pytest
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.fastmcp import FastMCP
from pydantic_ai.models.test import TestModel

from synapse.cipher_service import CipherService
from synapse.errors import SynapseTimeoutError
from synapse.mcp_server import build_server, resolve_runtime, runtime_requirements, _require_server_config


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
    assert "synapse_cipher_audit" in tool_names
    assert "synapse_cipher_explain" in tool_names
    assert "synapse_cipher_chunking_strategy" in tool_names
    assert "synapse_cipher_review_stubs" in tool_names


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

                audit = await session.call_tool(
                    "synapse_cipher_audit",
                    {
                        "cortex_path": str(vault),
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
