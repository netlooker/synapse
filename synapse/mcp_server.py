"""Minimal MCP server wrapper for Synapse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .cipher_service import (
    AuditVaultRequest,
    CipherDeps,
    CipherService,
    ExplainConnectionRequest,
    ReviewStubCandidatesRequest,
    StubCandidate,
    SuggestChunkingStrategyRequest,
)
from .errors import SynapseError
from .service_api import (
    DiscoverRequest,
    HealthRequest,
    IndexRequest,
    SearchRequest,
    ValidateRequest,
    discover_index,
    index_vault,
    resolve_runtime,
    runtime_requirements as service_runtime_requirements,
    search_index,
    validate_index,
)
from .settings import load_settings


def runtime_requirements(
    config_path: str | None = None,
    vault_root: str | None = None,
    db_path: str | None = None,
    note_provider: str | None = None,
    chunk_provider: str | None = None,
) -> dict[str, Any]:
    return service_runtime_requirements(
        HealthRequest(
            config_path=config_path,
            vault_root=vault_root,
            db_path=db_path,
            note_provider=note_provider,
            chunk_provider=chunk_provider,
        )
    ).model_dump()


def build_server(cipher_service: CipherService | None = None) -> FastMCP:
    """Build the minimal Synapse MCP server."""
    cipher = cipher_service or CipherService()
    mcp = FastMCP(
        "Synapse",
        instructions=(
            "Use Synapse to index markdown folders, search semantically, discover hidden links, "
            "and inspect runtime readiness. Prefer deterministic retrieval tools before reasoning. "
            "Use Cipher tools when you need audit, explanation, chunking advice, or stub review."
        ),
        json_response=True,
    )

    @mcp.tool(name="synapse_health", description="Report Synapse runtime requirements and readiness")
    def synapse_health(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
    ) -> dict[str, Any]:
        return runtime_requirements(
            config_path=config_path,
            vault_root=vault_root,
            db_path=db_path,
            note_provider=note_provider,
            chunk_provider=chunk_provider,
        )

    @mcp.tool(name="synapse_cipher_health", description="Report Cipher runtime requirements and readiness")
    def synapse_cipher_health(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
    ) -> dict[str, Any]:
        return runtime_requirements(
            config_path=config_path,
            vault_root=vault_root,
            db_path=db_path,
            note_provider=note_provider,
            chunk_provider=chunk_provider,
        )

    @mcp.tool(name="synapse_index", description="Index a markdown folder into Synapse")
    def synapse_index(
        config_path: str | None = None,
        vault_root: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
    ) -> dict[str, Any]:
        return index_vault(
            IndexRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
                note_provider=note_provider,
                chunk_provider=chunk_provider,
            )
        ).model_dump()

    @mcp.tool(name="synapse_search", description="Search an indexed Synapse database")
    def synapse_search(
        query: str,
        config_path: str | None = None,
        db_path: str | None = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
        mode: str = "hybrid",
        limit: int | None = None,
    ) -> dict[str, Any]:
        return search_index(
            SearchRequest(
                query=query,
                config_path=config_path,
                db_path=db_path,
                note_provider=note_provider,
                chunk_provider=chunk_provider,
                mode=mode,
                limit=limit,
            )
        ).model_dump()

    @mcp.tool(name="synapse_discover", description="Discover hidden links in an indexed Synapse database")
    def synapse_discover(
        config_path: str | None = None,
        db_path: str | None = None,
        threshold: float = 0.2,
        top_k: int = 3,
        max_total: int = 10,
    ) -> dict[str, Any]:
        return discover_index(
            DiscoverRequest(
                config_path=config_path,
                db_path=db_path,
                threshold=threshold,
                top_k=top_k,
                max_total=max_total,
            )
        ).model_dump()

    @mcp.tool(name="synapse_validate", description="Report broken markdown wikilinks from an indexed Synapse database")
    def synapse_validate(
        config_path: str | None = None,
        db_path: str | None = None,
    ) -> dict[str, Any]:
        return validate_index(
            ValidateRequest(
                config_path=config_path,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(name="synapse_cipher_audit", description="Audit a markdown folder through Cipher")
    async def synapse_cipher_audit(
        vault_root: str,
        synapse_db: str,
        mode: str = "audit",
        wraith_root: str | None = None,
        config_path: str | None = None,
    ) -> dict[str, Any]:
        return await _run_cipher_tool(
            cipher,
            AuditVaultRequest(mode=mode),
            _cipher_deps(vault_root=vault_root, synapse_db=synapse_db, wraith_root=wraith_root),
            config_path=config_path,
        )

    @mcp.tool(name="synapse_cipher_explain", description="Explain why two markdown documents are related")
    async def synapse_cipher_explain(
        doc_a: str,
        doc_b: str,
        config_path: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await _run_cipher_tool(
            cipher,
            ExplainConnectionRequest(doc_a=doc_a, doc_b=doc_b, timeout_seconds=timeout_seconds),
            CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            config_path=config_path,
        )

    @mcp.tool(
        name="synapse_cipher_chunking_strategy",
        description="Ask Cipher for a chunking strategy recommendation for a given model profile",
    )
    async def synapse_cipher_chunking_strategy(
        model_info: str,
        config_path: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        return await _run_cipher_tool(
            cipher,
            SuggestChunkingStrategyRequest(
                model_info=model_info,
                timeout_seconds=timeout_seconds,
            ),
            CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            config_path=config_path,
        )

    @mcp.tool(
        name="synapse_cipher_review_stubs",
        description="Review broken-link stub candidates through Cipher before writing notes",
    )
    async def synapse_cipher_review_stubs(
        candidates: list[dict[str, Any]] | None = None,
        stub_dir: str = "entities",
        config_path: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, Any]:
        stub_candidates = [StubCandidate.model_validate(item) for item in (candidates or [])]
        return await _run_cipher_tool(
            cipher,
            ReviewStubCandidatesRequest(
                candidates=stub_candidates,
                stub_dir=stub_dir,
                timeout_seconds=timeout_seconds,
            ),
            CipherDeps(vault_root=Path("."), synapse_db=Path(".")),
            config_path=config_path,
        )

    return mcp


def main() -> None:
    _require_server_config()
    transport = os.environ.get("SYNAPSE_MCP_TRANSPORT", "stdio")
    build_server().run(transport=transport)


def _require_server_config() -> None:
    config_path = os.environ.get("SYNAPSE_CONFIG")
    if not config_path:
        raise RuntimeError("SYNAPSE_CONFIG is required when starting synapse-mcp.")
    load_settings(config_path)


def _cipher_deps(
    *,
    vault_root: str,
    synapse_db: str,
    wraith_root: str | None = None,
) -> CipherDeps:
    return CipherDeps(
        vault_root=Path(vault_root).expanduser(),
        synapse_db=Path(synapse_db).expanduser(),
        wraith_root=Path(wraith_root).expanduser() if wraith_root else None,
    )


async def _run_cipher_tool(
    cipher: CipherService,
    request: Any,
    deps: CipherDeps,
    *,
    config_path: str | None = None,
) -> dict[str, Any]:
    settings = load_settings(config_path)
    cipher.settings = settings.cipher
    try:
        response = await cipher.handle(request, deps)
    except SynapseError as exc:
        raise RuntimeError(str(exc.to_dict())) from exc
    return response.model_dump()


if __name__ == "__main__":
    main()
