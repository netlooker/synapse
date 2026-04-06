"""Minimal MCP server wrapper for Synapse."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import BeforeValidator, Field, ValidationInfo

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


PLAIN_PATH_DESCRIPTION = (
    "Plain string filesystem path. Example: '/abs/path/to/file'. "
    "Do not wrap the value in a nested object."
)
OPTIONAL_PLAIN_PATH_DESCRIPTION = (
    "Optional plain string filesystem path override. "
    "Do not wrap the value in nested objects."
)
PLAIN_QUERY_DESCRIPTION = "Plain string search query."
SEARCH_MODE_DESCRIPTION = "Search mode. Use one of: note, chunk, hybrid."


def _coerce_path_arg(value: Any, info: ValidationInfo) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, Path):
        return str(value)
    if not isinstance(value, dict):
        return value

    field_name = info.field_name or "path"
    nested_value = value.get(field_name)
    if isinstance(nested_value, str):
        return nested_value
    if len(value) == 1:
        key, nested = next(iter(value.items()))
        if isinstance(key, str) and nested is None:
            return key

    raise ValueError(
        f"{field_name} must be a plain string path, not a nested object. "
        f"Use {field_name}='/abs/path' directly."
    )


OptionalPlainPathArg = Annotated[
    str | None,
    BeforeValidator(_coerce_path_arg),
    Field(description=OPTIONAL_PLAIN_PATH_DESCRIPTION),
]
RequiredPlainPathArg = Annotated[
    str,
    BeforeValidator(_coerce_path_arg),
    Field(description=PLAIN_PATH_DESCRIPTION),
]
QueryArg = Annotated[str, Field(description=PLAIN_QUERY_DESCRIPTION)]
SearchModeArg = Annotated[
    Literal["note", "chunk", "hybrid"],
    Field(description=SEARCH_MODE_DESCRIPTION),
]


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

    @mcp.tool(
        name="synapse_health",
        description=(
            "Report Synapse runtime requirements and readiness. "
            "Path overrides must be plain string paths, not nested objects."
        ),
    )
    def synapse_health(
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
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

    @mcp.tool(
        name="synapse_health_simple",
        description=(
            "Minimal health check for local-model agents. "
            "Call with only plain string vault_root and db_path arguments."
        ),
    )
    def synapse_health_simple(
        vault_root: RequiredPlainPathArg,
        db_path: RequiredPlainPathArg,
    ) -> dict[str, Any]:
        return runtime_requirements(
            vault_root=vault_root,
            db_path=db_path,
        )

    @mcp.tool(
        name="synapse_cipher_health",
        description=(
            "Report Cipher runtime requirements and readiness. "
            "Path overrides must be plain string paths, not nested objects."
        ),
    )
    def synapse_cipher_health(
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
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

    @mcp.tool(
        name="synapse_index",
        description=(
            "Index a markdown folder into Synapse. "
            "Path overrides must be plain string paths, not nested objects."
        ),
    )
    def synapse_index(
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
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

    @mcp.tool(
        name="synapse_index_simple",
        description=(
            "Minimal indexing call for local-model agents. "
            "Call with only plain string vault_root and db_path arguments."
        ),
    )
    def synapse_index_simple(
        vault_root: RequiredPlainPathArg,
        db_path: RequiredPlainPathArg,
    ) -> dict[str, Any]:
        return index_vault(
            IndexRequest(
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_search",
        description=(
            "Search an indexed Synapse database. "
            "db_path must be a plain string path, not a nested object."
        ),
    )
    def synapse_search(
        query: QueryArg,
        config_path: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
        note_provider: str | None = None,
        chunk_provider: str | None = None,
        mode: SearchModeArg = "hybrid",
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

    @mcp.tool(
        name="synapse_search_simple",
        description=(
            "Minimal search call for local-model agents. "
            "Call with query plus plain string db_path. mode defaults to hybrid."
        ),
    )
    def synapse_search_simple(
        query: QueryArg,
        db_path: RequiredPlainPathArg,
        mode: SearchModeArg = "hybrid",
    ) -> dict[str, Any]:
        return search_index(
            SearchRequest(
                query=query,
                db_path=db_path,
                mode=mode,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_discover",
        description=(
            "Discover hidden links in an indexed Synapse database. "
            "db_path must be a plain string path, not a nested object."
        ),
    )
    def synapse_discover(
        config_path: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
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

    @mcp.tool(
        name="synapse_validate",
        description=(
            "Report broken markdown wikilinks from an indexed Synapse database. "
            "db_path must be a plain string path, not a nested object."
        ),
    )
    def synapse_validate(
        config_path: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return validate_index(
            ValidateRequest(
                config_path=config_path,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(name="synapse_cipher_audit", description="Audit a markdown folder through Cipher")
    async def synapse_cipher_audit(
        vault_root: RequiredPlainPathArg,
        synapse_db: RequiredPlainPathArg,
        mode: Literal["audit", "repair"] = "audit",
        wraith_root: OptionalPlainPathArg = None,
        config_path: OptionalPlainPathArg = None,
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
