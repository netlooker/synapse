"""Minimal MCP server wrapper for Synapse."""

from __future__ import annotations

import json
import os
import re
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
from .errors import SynapseError, SynapseNotFoundError
from .service_api import (
    DiscoverRequest,
    HealthRequest,
    IndexRequest,
    IngestBundleRequest,
    KnowledgeBundleDetailRequest,
    KnowledgeCompileBundleRequest,
    KnowledgeOverviewRequest,
    KnowledgeProposalActionRequest,
    KnowledgeProposalListRequest,
    KnowledgeSourceDetailRequest,
    SearchRequest,
    ValidateRequest,
    WorkspaceIndexRequest,
    WorkspaceSearchRequest,
    apply_knowledge_proposal,
    compile_knowledge_bundle,
    discover_index,
    index_vault_for_workspace,
    index_vault,
    ingest_bundle_artifact,
    knowledge_bundle_detail,
    knowledge_overview,
    knowledge_source_detail,
    list_knowledge_proposals,
    reject_knowledge_proposal,
    resolve_runtime,
    runtime_requirements as service_runtime_requirements,
    runtime_requirements_for_workspace as service_runtime_requirements_for_workspace,
    search_index_for_workspace,
    search_index,
    validate_index,
)
from .settings import load_settings


PLAIN_PATH_DESCRIPTION = (
    "Plain string filesystem path. Example: '/abs/path/to/file'. "
    "Do not wrap the value in a nested object or encode other arguments inside it. "
    'Invalid example: \'{"\\/abs/path/to/file"},query:"signal"\''
)
OPTIONAL_PLAIN_PATH_DESCRIPTION = (
    "Optional plain string filesystem path override. "
    "Do not wrap the value in nested objects or encode other arguments inside it."
)
PLAIN_QUERY_DESCRIPTION = (
    "Plain string search query as a top-level field. "
    'Valid example: {"query": "cross-paper insights"}. '
    'Invalid example: {"db_path": "{\\"/abs/synapse.sqlite\\"},query:\\"cross-paper insights\\"}"}.'
)
SEARCH_MODE_DESCRIPTION = (
    "Search mode as a top-level string. Use one of: source, note, evidence, research. "
    'Valid example: {"mode": "research"}. '
    'Invalid example: encoding mode inside db_path or passing nested mode objects.'
)
INDEX_TOOL_DESCRIPTION = (
    "Index a markdown folder into Synapse. "
    "vault_root must be a plain string path. db_path must be a plain string path. "
    "Do not encode multiple parameters inside db_path. "
    'Valid arguments: {"vault_root": "/abs/vault", "db_path": "/abs/synapse.sqlite"}. '
    'Invalid arguments: {"db_path": "{\\"/abs/synapse.sqlite\\"},vault_root:\\"/abs/vault\\"}"}.'
)
INDEX_SIMPLE_TOOL_DESCRIPTION = (
    "Minimal indexing call for local-model agents. "
    "Call with only plain string vault_root and db_path arguments. "
    'Valid arguments: {"vault_root": "/abs/vault", "db_path": "/abs/synapse.sqlite"}.'
)
SEARCH_TOOL_DESCRIPTION = (
    "Search an indexed Synapse database. "
    "query must be a top-level string field. mode must be a top-level string field. "
    "db_path must be a plain string path. Do not encode multiple parameters inside db_path. "
    'Valid arguments: {"query": "cross-paper insights", "mode": "research", "db_path": "/abs/synapse.sqlite"}. '
    'Invalid arguments: {"db_path": "{\\"/abs/synapse.sqlite\\"},mode:\\"research\\",query:\\"cross-paper insights\\"}"}.'
)
SEARCH_SIMPLE_TOOL_DESCRIPTION = (
    "Minimal search call for local-model agents. "
    "Call with top-level query plus plain string db_path. mode defaults to research."
)
WORKSPACE_HANDLE_DESCRIPTION = (
    "Stable Synapse workspace handle. Use 'current' to target the workspace configured for this server. "
    "Do not pass filesystem paths here."
)
WORKSPACE_HEALTH_TOOL_DESCRIPTION = (
    "Pathless health check for local-model agents. "
    "Use workspace='current' or omit the argument to inspect the configured Synapse workspace."
)
WORKSPACE_INDEX_TOOL_DESCRIPTION = (
    "Pathless indexing call for local-model agents. "
    "Use workspace='current' or omit the argument to index the configured Synapse workspace."
)
WORKSPACE_SEARCH_TOOL_DESCRIPTION = (
    "Pathless search call for local-model agents. "
    "Provide query and optional mode. Use workspace='current' or omit it to search the configured Synapse database."
)
_COLLAPSED_ARG_KEYS = ("config_path", "vault_root", "db_path", "query", "mode")
_COLLAPSED_ARG_PATTERN = re.compile(
    r"(?:^|,)\s*"
    r"(?P<key>config_path|vault_root|db_path|query|mode)"
    r"\s*:\s*"
    r"(?P<value>.*?)(?=(?:,\s*(?:config_path|vault_root|db_path|query|mode)\s*:)|\s*$)",
    re.DOTALL,
)
_PATH_TOKEN_PATTERN = re.compile(r"(?P<path>(?:/|~/)[^\",}\s]+)")


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


def _coerce_mode_arg(value: Any) -> Any:
    normalized = _normalize_mode_value(value)
    if isinstance(normalized, str):
        return normalized
    return value


def _coerce_workspace_arg(value: Any, info: ValidationInfo) -> Any:
    if value is None or isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return value

    field_name = info.field_name or "workspace"
    nested_value = value.get(field_name)
    if isinstance(nested_value, str):
        return nested_value
    if len(value) == 1:
        key, nested = next(iter(value.items()))
        if isinstance(key, str) and nested is None:
            return key
    return value


def _normalize_mode_value(value: Any) -> Any:
    while isinstance(value, dict) and set(value) == {"mode"}:
        value = value["mode"]
    if isinstance(value, str):
        stripped = value.strip().strip('"').lower()
        if stripped in {"source", "note", "evidence", "research"}:
            return stripped
        if stripped in {"0", "1", "2", "3"}:
            return {0: "source", 1: "note", 2: "research", 3: "evidence"}[int(stripped)]
    if isinstance(value, int):
        return {0: "source", 1: "note", 2: "research", 3: "evidence"}.get(value, value)
    return value


def _normalize_tool_arguments(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    recovered: dict[str, Any] = {}
    for source_field in ("config_path", "vault_root", "db_path"):
        recovered.update(_extract_collapsed_arguments(source_field, normalized.get(source_field)))

    for key, value in recovered.items():
        current = normalized.get(key)
        if key in {"config_path", "vault_root", "db_path"}:
            if current is None or _looks_like_collapsed_argument_blob(current):
                normalized[key] = value
            continue
        if current is None:
            normalized[key] = value

    if "mode" in normalized:
        normalized["mode"] = _coerce_mode_arg(normalized["mode"])

    return normalized


def _extract_collapsed_arguments(source_field: str, value: Any) -> dict[str, Any]:
    if not _looks_like_collapsed_argument_blob(value):
        return {}

    text = str(value).strip()
    extracted: dict[str, Any] = {}
    path_match = _PATH_TOKEN_PATTERN.search(text)
    if path_match:
        extracted[source_field] = path_match.group("path")

    for match in _COLLAPSED_ARG_PATTERN.finditer(text):
        key = match.group("key")
        parsed = _parse_collapsed_value(match.group("value"))
        if parsed is None:
            continue
        if key == "mode":
            parsed = _coerce_mode_arg(parsed)
        extracted[key] = parsed
    return extracted


def _looks_like_collapsed_argument_blob(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    return any(f"{key}:" in value for key in _COLLAPSED_ARG_KEYS) or (
        value.strip().startswith("{") and "," in value and "/" in value
    )


def _parse_collapsed_value(raw: str) -> Any:
    token = _trim_unbalanced_suffix(raw.strip().rstrip(","))
    if not token:
        return None
    if token.startswith("{") and token.endswith("}"):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            pass
    if token.startswith('"') and token.endswith('"'):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return token[1:-1].replace('\\"', '"')
    lowered = token.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if re.fullmatch(r"-?\d+", token):
        return int(token)
    if re.fullmatch(r"-?\d+\.\d+", token):
        return float(token)
    return token


def _trim_unbalanced_suffix(token: str) -> str:
    trimmed = token
    while trimmed.endswith("}") and trimmed.count("{") < trimmed.count("}"):
        trimmed = trimmed[:-1].rstrip()
    return trimmed


def _install_argument_normalizer(mcp: FastMCP, tool_name: str) -> None:
    tool = mcp._tool_manager._tools[tool_name]
    original_pre_parse_json = tool.fn_metadata.pre_parse_json
    object.__setattr__(
        tool.fn_metadata,
        "pre_parse_json",
        lambda data, _orig=original_pre_parse_json: _normalize_tool_arguments(_orig(data)),
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
    Literal["source", "note", "evidence", "research"],
    BeforeValidator(_coerce_mode_arg),
    Field(description=SEARCH_MODE_DESCRIPTION),
]
WorkspaceArg = Annotated[
    Literal["current"],
    BeforeValidator(_coerce_workspace_arg),
    Field(description=WORKSPACE_HANDLE_DESCRIPTION),
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


def runtime_requirements_for_workspace(
    workspace: Literal["current"] = "current",
) -> dict[str, Any]:
    from .service_api import WorkspaceHealthRequest

    return service_runtime_requirements_for_workspace(
        WorkspaceHealthRequest(workspace=workspace)
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
            "Path overrides must be plain string paths, not nested objects or collapsed multi-field strings."
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
        name="synapse_health_for_workspace",
        description=WORKSPACE_HEALTH_TOOL_DESCRIPTION,
    )
    def synapse_health_for_workspace(
        workspace: WorkspaceArg = "current",
    ) -> dict[str, Any]:
        return runtime_requirements_for_workspace(workspace=workspace)

    @mcp.tool(
        name="synapse_cipher_health",
        description=(
            "Report Cipher runtime requirements and readiness. "
            "Path overrides must be plain string paths, not nested objects or collapsed multi-field strings."
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
        description=INDEX_TOOL_DESCRIPTION,
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
        description=INDEX_SIMPLE_TOOL_DESCRIPTION,
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
        name="synapse_index_for_workspace",
        description=WORKSPACE_INDEX_TOOL_DESCRIPTION,
    )
    def synapse_index_for_workspace_tool(
        workspace: WorkspaceArg = "current",
    ) -> dict[str, Any]:
        return index_vault_for_workspace(
            WorkspaceIndexRequest(workspace=workspace)
        ).model_dump()

    @mcp.tool(
        name="synapse_search",
        description=SEARCH_TOOL_DESCRIPTION,
    )
    def synapse_search(
        query: QueryArg,
        config_path: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
        provider: str | None = None,
        mode: SearchModeArg = "research",
        limit: int | None = None,
    ) -> dict[str, Any]:
        return search_index(
            SearchRequest(
                query=query,
                config_path=config_path,
                db_path=db_path,
                provider=provider,
                mode=mode,
                limit=limit,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_search_simple",
        description=SEARCH_SIMPLE_TOOL_DESCRIPTION,
    )
    def synapse_search_simple(
        query: QueryArg,
        db_path: RequiredPlainPathArg,
        mode: SearchModeArg = "research",
    ) -> dict[str, Any]:
        return search_index(
            SearchRequest(
                query=query,
                db_path=db_path,
                mode=mode,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_search_for_workspace",
        description=WORKSPACE_SEARCH_TOOL_DESCRIPTION,
    )
    def synapse_search_for_workspace_tool(
        query: QueryArg,
        workspace: WorkspaceArg = "current",
        mode: SearchModeArg = "research",
        limit: int | None = None,
    ) -> dict[str, Any]:
        return search_index_for_workspace(
            WorkspaceSearchRequest(
                query=query,
                workspace=workspace,
                mode=mode,
                limit=limit,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_discover",
        description=(
            "Discover hidden links in an indexed Synapse database. "
            "db_path must be a plain string path, not a nested object or collapsed multi-field string."
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
            "db_path must be a plain string path, not a nested object or collapsed multi-field string."
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

    @mcp.tool(name="synapse_cipher_explain", description="Explain why two knowledge entries are related")
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

    # ------------------------------------------------------------------
    # Research bundle ingest
    # ------------------------------------------------------------------

    @mcp.tool(
        name="synapse_ingest_bundle",
        description=(
            "Ingest a prepared research source bundle JSON artifact into Synapse. "
            "bundle_path must be a plain string filesystem path to the prepared bundle. "
            "Sources and their chunks are written to the vector store so they can be compiled "
            "into managed knowledge notes through the synapse_knowledge_* tools."
        ),
    )
    def synapse_ingest_bundle(
        bundle_path: RequiredPlainPathArg,
        config_path: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
        provider: str | None = None,
    ) -> dict[str, Any]:
        return ingest_bundle_artifact(
            IngestBundleRequest(
                bundle_path=bundle_path,
                config_path=config_path,
                db_path=db_path,
                provider=provider,
            )
        ).model_dump()

    # ------------------------------------------------------------------
    # Compiled knowledge layer (opt-in — requires knowledge.enabled = true)
    # ------------------------------------------------------------------

    @mcp.tool(
        name="synapse_knowledge_overview",
        description=(
            "Return the compiled knowledge layer overview: managed_root, vault_root, "
            "status counts, and recent proposals. Matches the /ui/knowledge/ home page. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_overview(
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return knowledge_overview(
            KnowledgeOverviewRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_compile_bundle",
        description=(
            "Compile an ingested research bundle into pending source_summary proposals. "
            "Returns the job id and the list of created proposal ids. Proposals are not "
            "written to disk until they are applied via synapse_knowledge_apply_proposal. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_compile_bundle(
        bundle_id: str,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return compile_knowledge_bundle(
            KnowledgeCompileBundleRequest(
                bundle_id=bundle_id,
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_list_proposals",
        description=(
            "List compiled knowledge proposals. Filter by status (pending/applied/rejected) "
            "and optionally cap the result count. Matches the /ui/knowledge/proposals review queue. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_list_proposals(
        status: str | None = None,
        limit: int | None = None,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return list_knowledge_proposals(
            KnowledgeProposalListRequest(
                status=status,
                limit=limit,
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_get_proposal",
        description=(
            "Return the full compiled knowledge proposal detail for a specific id: "
            "frontmatter, body markdown, supporting refs, and reviewer action history. "
            "Matches the /ui/knowledge/proposals/{id} review-item page. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_get_proposal(
        proposal_id: int,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        listing = list_knowledge_proposals(
            KnowledgeProposalListRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        )
        for item in listing.proposals:
            if item.id == proposal_id:
                return item.model_dump()
        raise SynapseNotFoundError(f"Proposal not found: {proposal_id}")

    @mcp.tool(
        name="synapse_knowledge_apply_proposal",
        description=(
            "Apply a pending compiled knowledge proposal. Writes the managed note to disk, "
            "updates index.md and log.md, then reindexes the affected files. Returns the "
            "written path and the list of reindexed files. Requires knowledge.enabled = true."
        ),
    )
    def synapse_knowledge_apply_proposal(
        proposal_id: int,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return apply_knowledge_proposal(
            proposal_id,
            KnowledgeProposalActionRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            ),
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_reject_proposal",
        description=(
            "Reject a pending compiled knowledge proposal and append the reason to log.md. "
            "An optional reason string is recorded in the reviewer action. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_reject_proposal(
        proposal_id: int,
        reason: str | None = None,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return reject_knowledge_proposal(
            proposal_id,
            KnowledgeProposalActionRequest(
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
                reason=reason,
            ),
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_bundle_detail",
        description=(
            "Return bundle metadata plus every ingested source in the bundle with its "
            "proposal and applied counts. Matches the /ui/knowledge/bundles/{bundle_id} page. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_bundle_detail(
        bundle_id: str,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return knowledge_bundle_detail(
            KnowledgeBundleDetailRequest(
                bundle_id=bundle_id,
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    @mcp.tool(
        name="synapse_knowledge_source_detail",
        description=(
            "Return a single source's normalized metadata, stored segments (summary/abstract/full_text), "
            "and related proposals. Matches the /ui/knowledge/sources/{bundle_id}/{source_id} page. "
            "Requires knowledge.enabled = true in settings."
        ),
    )
    def synapse_knowledge_source_detail(
        bundle_id: str,
        source_id: str,
        config_path: OptionalPlainPathArg = None,
        vault_root: OptionalPlainPathArg = None,
        db_path: OptionalPlainPathArg = None,
    ) -> dict[str, Any]:
        return knowledge_source_detail(
            KnowledgeSourceDetailRequest(
                bundle_id=bundle_id,
                source_id=source_id,
                config_path=config_path,
                vault_root=vault_root,
                db_path=db_path,
            )
        ).model_dump()

    for tool_name in (
        "synapse_health",
        "synapse_health_simple",
        "synapse_cipher_health",
        "synapse_index",
        "synapse_index_simple",
        "synapse_index_for_workspace",
        "synapse_search",
        "synapse_search_simple",
        "synapse_search_for_workspace",
        "synapse_discover",
        "synapse_validate",
        "synapse_health_for_workspace",
        "synapse_ingest_bundle",
        "synapse_knowledge_overview",
        "synapse_knowledge_compile_bundle",
        "synapse_knowledge_list_proposals",
        "synapse_knowledge_get_proposal",
        "synapse_knowledge_apply_proposal",
        "synapse_knowledge_reject_proposal",
        "synapse_knowledge_bundle_detail",
        "synapse_knowledge_source_detail",
    ):
        _install_argument_normalizer(mcp, tool_name)

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
