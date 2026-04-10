"""Shared runtime service layer for MCP and HTTP adapters."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import sqlite_vec
from pydantic import BaseModel, Field

from .discovery import Discovery, find_discoveries
from .embeddings import EmbeddingClient
from .errors import SynapseBadRequestError, SynapseNotFoundError
from .knowledge_service import (
    ApplyProposalResult,
    CompileBundleResult,
    KnowledgeService,
    build_indexer_factory,
)
from .research_ingest import ResearchBundleIngestor
from .index import Indexer
from .search import Searcher
from .settings import AppSettings, ProviderSettings, load_settings
from .validate import BrokenLink, find_broken_links
from .vector_store import create_vector_store


class ProviderSummary(BaseModel):
    name: str
    type: str
    model: str
    base_url: str
    dimensions: int
    context_strategy: str


class RequirementSummary(BaseModel):
    python_environment: bool = True
    sqlite_vec: bool
    markdown_folder: bool
    writable_database_parent: bool
    embedding_models_configured: bool


class HealthRequest(BaseModel):
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None
    note_provider: str | None = None
    chunk_provider: str | None = None


class HealthResponse(BaseModel):
    config_path: str | None = None
    vault_root: str
    vault_exists: bool
    database_path: str
    database_exists: bool
    vector_store: str
    sqlite_vec_python_package: bool
    note_provider: ProviderSummary
    chunk_provider: ProviderSummary
    dimensions_match: bool
    reasoning_model: str | None = None
    requirements: RequirementSummary
    ready_for_indexing: bool


class IndexRequest(BaseModel):
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None
    note_provider: str | None = None
    chunk_provider: str | None = None


class IndexStats(BaseModel):
    total_files: int
    indexed: int
    unchanged: int
    errors: int
    total_segments: int


class IndexResponse(BaseModel):
    vault_root: str
    database_path: str
    note_provider: str
    chunk_provider: str
    stats: IndexStats


class IngestBundleRequest(BaseModel):
    bundle_path: str
    config_path: str | None = None
    db_path: str | None = None
    provider: str | None = None


class IngestBundleResponse(BaseModel):
    bundle_id: str
    bundle_path: str
    database_path: str
    provider: str
    replaced_existing: bool
    source_count: int
    segment_count: int


class SearchRequest(BaseModel):
    query: str
    config_path: str | None = None
    db_path: str | None = None
    provider: str | None = None
    mode: Literal["source", "note", "evidence", "research"] = "research"
    limit: int | None = None
    bundle_id: str | None = None
    source_id: str | None = None
    source_type: str | None = None


class SearchResult(BaseModel):
    result_kind: Literal["source", "note", "evidence"]
    title: str | None = None
    bundle_id: str | None = None
    source_id: str | None = None
    note_path: str | None = None
    origin_url: str | None = None
    direct_paper_url: str | None = None
    matched_content_role: str
    matched_segment_text: str
    bm25_score: float | None = None
    vector_score: float | None = None
    combined_score: float
    rank_reason: str


class SearchResponse(BaseModel):
    query: str
    mode: str
    database_path: str
    results: list[SearchResult] = Field(default_factory=list)


WorkspaceHandle = Literal["current"]


class WorkspaceHealthRequest(BaseModel):
    workspace: WorkspaceHandle = "current"


class WorkspaceIndexRequest(BaseModel):
    workspace: WorkspaceHandle = "current"


class WorkspaceSearchRequest(BaseModel):
    query: str
    workspace: WorkspaceHandle = "current"
    mode: Literal["source", "note", "evidence", "research"] = "research"
    limit: int | None = None
    bundle_id: str | None = None
    source_id: str | None = None
    source_type: str | None = None


class DiscoverRequest(BaseModel):
    config_path: str | None = None
    db_path: str | None = None
    threshold: float = 0.2
    top_k: int = 3
    max_total: int = 10


class DiscoveryResult(BaseModel):
    source_path: str
    source_title: str
    target_path: str
    target_title: str
    similarity: float
    semantic_similarity: float
    metadata_score: float
    graph_score: float


class DiscoverResponse(BaseModel):
    database_path: str
    threshold: float
    discoveries: list[DiscoveryResult] = Field(default_factory=list)


class ValidateRequest(BaseModel):
    config_path: str | None = None
    db_path: str | None = None


class BrokenLinkResult(BaseModel):
    source_path: str
    target_link: str


class ValidateResponse(BaseModel):
    database_path: str
    broken_links: list[BrokenLinkResult] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Compiled knowledge layer
# ---------------------------------------------------------------------------


class KnowledgeCompileBundleRequest(BaseModel):
    bundle_id: str
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None


class KnowledgeCompileBundleResponse(BaseModel):
    job_id: int
    bundle_id: str
    proposal_ids: list[int] = Field(default_factory=list)
    created_count: int


class KnowledgeOverviewRequest(BaseModel):
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None


class KnowledgeProposalSummary(BaseModel):
    id: int
    job_id: int | None = None
    note_kind: str
    slug: str
    title: str | None = None
    target_path: str
    status: str
    created_at: str | None = None
    updated_at: str | None = None


class KnowledgeOverviewResponse(BaseModel):
    managed_root: str
    vault_root: str
    counts: dict[str, int] = Field(default_factory=dict)
    recent_proposals: list[KnowledgeProposalSummary] = Field(default_factory=list)


class KnowledgeProposalListRequest(BaseModel):
    status: str | None = None
    limit: int | None = None
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None


class KnowledgeProposalDetail(BaseModel):
    id: int
    job_id: int | None = None
    note_kind: str
    slug: str
    target_path: str
    title: str | None = None
    status: str
    body_markdown: str
    frontmatter: dict = Field(default_factory=dict)
    supporting_refs: dict = Field(default_factory=dict)
    base_content_hash: str | None = None
    reviewer_action: dict = Field(default_factory=dict)
    created_at: str | None = None
    updated_at: str | None = None


class KnowledgeProposalListResponse(BaseModel):
    proposals: list[KnowledgeProposalDetail] = Field(default_factory=list)


class KnowledgeProposalActionRequest(BaseModel):
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None
    reason: str | None = None


class KnowledgeApplyResponse(BaseModel):
    proposal_id: int
    target_path: str
    written_path: str
    reindexed_files: list[str] = Field(default_factory=list)


class KnowledgeRejectResponse(BaseModel):
    proposal: KnowledgeProposalDetail


class KnowledgeSourceDetailRequest(BaseModel):
    bundle_id: str
    source_id: str
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None


class KnowledgeSourceSegment(BaseModel):
    id: int
    content_role: str
    segment_index: int
    text: str
    token_count: int = 0
    metadata: dict = Field(default_factory=dict)


class KnowledgeBundleSourceSummary(BaseModel):
    bundle_id: str
    source_id: str
    title: str | None = None
    source_type: str | None = None
    published: str | None = None
    proposal_count: int = 0
    applied_count: int = 0
    latest_status: str | None = None


class KnowledgeBundleDetailRequest(BaseModel):
    bundle_id: str
    config_path: str | None = None
    vault_root: str | None = None
    db_path: str | None = None


class KnowledgeBundleDetailResponse(BaseModel):
    bundle_id: str
    bundle: dict = Field(default_factory=dict)
    sources: list[KnowledgeBundleSourceSummary] = Field(default_factory=list)


class KnowledgeSourceDetailResponse(BaseModel):
    bundle_id: str
    source_id: str
    source: dict = Field(default_factory=dict)
    related_proposals: list[KnowledgeProposalDetail] = Field(default_factory=list)
    segments: list[KnowledgeSourceSegment] = Field(default_factory=list)


def resolve_runtime(
    config_path: str | None = None,
    vault_root: str | None = None,
    db_path: str | None = None,
) -> tuple[AppSettings, Path, Path]:
    """Resolve settings plus effective vault and DB paths."""
    settings = load_settings(config_path)
    root = Path(vault_root or settings.vault.root).expanduser()
    db = Path(db_path or settings.database.path).expanduser()
    return settings, root, db


def runtime_requirements(request: HealthRequest) -> HealthResponse:
    """Return the minimum runtime contract and current local readiness."""
    settings, root, db = resolve_runtime(
        request.config_path,
        request.vault_root,
        request.db_path,
    )
    note = settings.embedding_provider(request.note_provider)
    chunk = settings.embedding_provider(request.chunk_provider or settings.index.contextual_provider)
    dimensions_match = note.dimensions == chunk.dimensions
    sqlite_vec_available = _sqlite_vec_available()
    writable_database_parent = db.parent.exists() and os.access(db.parent, os.W_OK)

    return HealthResponse(
        config_path=str(settings.config_path) if settings.config_path else None,
        vault_root=str(root),
        vault_exists=root.exists() and root.is_dir(),
        database_path=str(db),
        database_exists=db.exists(),
        vector_store=settings.vector_store.type,
        sqlite_vec_python_package=sqlite_vec_available,
        note_provider=_provider_summary(note),
        chunk_provider=_provider_summary(chunk),
        dimensions_match=dimensions_match,
        reasoning_model=os.environ.get("SYNAPSE_MODEL"),
        requirements=RequirementSummary(
            sqlite_vec=sqlite_vec_available,
            markdown_folder=root.exists() and root.is_dir(),
            writable_database_parent=writable_database_parent,
            embedding_models_configured=bool(note.model and chunk.model),
        ),
        ready_for_indexing=(
            sqlite_vec_available
            and root.exists()
            and root.is_dir()
            and dimensions_match
            and writable_database_parent
        ),
    )


def index_vault(request: IndexRequest) -> IndexResponse:
    settings, root, db = resolve_runtime(
        request.config_path,
        request.vault_root,
        request.db_path,
    )
    note_cfg = settings.embedding_provider(request.note_provider)
    chunk_cfg = settings.embedding_provider(request.chunk_provider or settings.index.contextual_provider)
    _assert_matching_dimensions(note_cfg, chunk_cfg)

    store = create_vector_store(settings, db_path=db, embedding_dim=note_cfg.dimensions)
    store.initialize()
    try:
        indexer = Indexer(
            db=store,
            vault_root=root,
            note_embedding_client=EmbeddingClient.from_provider(note_cfg),
            chunk_embedding_client=EmbeddingClient.from_provider(chunk_cfg),
            min_chunk_chars=settings.index.min_chunk_chars,
            max_chunk_chars=settings.index.max_chunk_chars,
            target_chunk_tokens=settings.index.target_chunk_tokens,
            max_chunk_tokens=settings.index.max_chunk_tokens,
            chunk_overlap_chars=settings.index.chunk_overlap_chars,
            chunk_strategy=settings.index.chunk_strategy,
            include_patterns=settings.vault.include,
            exclude_patterns=settings.vault.exclude,
        )
        stats = indexer.index_all()
    finally:
        store.close()

    return IndexResponse(
        vault_root=str(root),
        database_path=str(db),
        note_provider=note_cfg.name,
        chunk_provider=chunk_cfg.name,
        stats=IndexStats(**stats),
    )


def ingest_bundle_artifact(request: IngestBundleRequest) -> IngestBundleResponse:
    settings, _, db = resolve_runtime(request.config_path, None, request.db_path)
    provider = settings.embedding_provider(request.provider or settings.index.provider)

    bundle_path = Path(request.bundle_path).expanduser()
    if not bundle_path.exists():
        raise SynapseNotFoundError(f"Prepared bundle not found: {bundle_path}")

    store = create_vector_store(settings, db_path=db, embedding_dim=provider.dimensions)
    store.initialize()
    try:
        ingestor = ResearchBundleIngestor(
            db=store,
            embedding_client=EmbeddingClient.from_provider(provider),
        )
        result = ingestor.ingest_bundle_file(bundle_path)
    finally:
        store.close()

    return IngestBundleResponse(
        bundle_id=result.bundle_id,
        bundle_path=result.bundle_path,
        database_path=str(db),
        provider=provider.name,
        replaced_existing=result.replaced_existing,
        source_count=result.source_count,
        segment_count=result.segment_count,
    )


def search_index(request: SearchRequest) -> SearchResponse:
    settings, _, db = resolve_runtime(request.config_path, None, request.db_path)
    if not db.exists():
        raise SynapseNotFoundError(f"Synapse database not found: {db}")

    provider = settings.embedding_provider(request.provider or settings.search.provider)

    store = create_vector_store(settings, db_path=db, embedding_dim=provider.dimensions)
    store.initialize()
    try:
        searcher = Searcher(
            db=store,
            embedding_client=EmbeddingClient.from_provider(provider),
            search_settings=settings.search,
        )
        results = searcher.search(
            query=request.query,
            limit=request.limit or settings.search.limit,
            mode=request.mode,
            filters={
                key: value
                for key, value in {
                    "bundle_id": request.bundle_id,
                    "source_id": request.source_id,
                    "source_type": request.source_type,
                }.items()
                if value is not None
            },
        )
    finally:
        store.close()

    return SearchResponse(
        query=request.query,
        mode=request.mode,
        database_path=str(db),
        results=[SearchResult(**item) for item in results],
    )


def discover_index(request: DiscoverRequest) -> DiscoverResponse:
    settings, _, db = resolve_runtime(request.config_path, None, request.db_path)
    if not db.exists():
        raise SynapseNotFoundError(f"Synapse database not found: {db}")

    store = create_vector_store(
        settings,
        db_path=db,
        embedding_dim=settings.embedding_provider().dimensions,
    )
    store.initialize()
    try:
        discoveries = find_discoveries(
            store,
            threshold=request.threshold,
            top_k=request.top_k,
            max_total=request.max_total,
        )
    finally:
        store.close()

    return DiscoverResponse(
        database_path=str(db),
        threshold=request.threshold,
        discoveries=[_discovery_result(item) for item in discoveries],
    )


def validate_index(request: ValidateRequest) -> ValidateResponse:
    settings, _, db = resolve_runtime(request.config_path, None, request.db_path)
    if not db.exists():
        raise SynapseNotFoundError(f"Synapse database not found: {db}")

    store = create_vector_store(
        settings,
        db_path=db,
        embedding_dim=settings.embedding_provider().dimensions,
    )
    store.initialize()
    try:
        broken_links = find_broken_links(store)
    finally:
        store.close()

    return ValidateResponse(
        database_path=str(db),
        broken_links=[_broken_link_result(item) for item in broken_links],
    )


def runtime_requirements_for_workspace(request: WorkspaceHealthRequest) -> HealthResponse:
    _assert_workspace_handle(request.workspace)
    return runtime_requirements(HealthRequest())


def index_vault_for_workspace(request: WorkspaceIndexRequest) -> IndexResponse:
    _assert_workspace_handle(request.workspace)
    return index_vault(IndexRequest())


def search_index_for_workspace(request: WorkspaceSearchRequest) -> SearchResponse:
    _assert_workspace_handle(request.workspace)
    return search_index(
        SearchRequest(
            query=request.query,
            mode=request.mode,
            limit=request.limit,
            bundle_id=request.bundle_id,
            source_id=request.source_id,
            source_type=request.source_type,
        )
    )


def _knowledge_service_context(
    config_path: str | None,
    vault_root: str | None,
    db_path: str | None,
) -> tuple[AppSettings, Path, Path]:
    settings, root, db = resolve_runtime(config_path, vault_root, db_path)
    if not settings.knowledge.enabled:
        raise SynapseNotFoundError(
            "Compiled knowledge layer is disabled. Enable [knowledge] in your config."
        )
    return settings, root, db


def _open_knowledge_store(settings: AppSettings, db: Path):
    provider = settings.embedding_provider()
    store = create_vector_store(settings, db_path=db, embedding_dim=provider.dimensions)
    store.initialize()
    return store


def compile_knowledge_bundle(
    request: KnowledgeCompileBundleRequest,
) -> KnowledgeCompileBundleResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        service = KnowledgeService(
            store=store,
            settings=settings,
            vault_root=root,
            indexer_factory=build_indexer_factory(
                store=store, settings=settings, vault_root=root
            ),
        )
        result = service.compile_bundle(request.bundle_id)
    finally:
        store.close()
    return KnowledgeCompileBundleResponse(
        job_id=result.job_id,
        bundle_id=result.bundle_id,
        proposal_ids=result.proposal_ids,
        created_count=result.created_count,
    )


def knowledge_overview(request: KnowledgeOverviewRequest) -> KnowledgeOverviewResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        service = KnowledgeService(store=store, settings=settings, vault_root=root)
        overview = service.overview()
    finally:
        store.close()
    return KnowledgeOverviewResponse(
        managed_root=overview["managed_root"],
        vault_root=overview["vault_root"],
        counts=overview["counts"],
        recent_proposals=[
            KnowledgeProposalSummary(
                id=row["id"],
                job_id=row.get("job_id"),
                note_kind=row["note_kind"],
                slug=row["slug"],
                title=row.get("title"),
                target_path=row["target_path"],
                status=row["status"],
                created_at=str(row.get("created_at")) if row.get("created_at") else None,
                updated_at=str(row.get("updated_at")) if row.get("updated_at") else None,
            )
            for row in overview["recent_proposals"]
        ],
    )


def list_knowledge_proposals(
    request: KnowledgeProposalListRequest,
) -> KnowledgeProposalListResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        service = KnowledgeService(store=store, settings=settings, vault_root=root)
        proposals = service.list_proposals(status=request.status, limit=request.limit)
    finally:
        store.close()
    return KnowledgeProposalListResponse(
        proposals=[_proposal_detail(row) for row in proposals]
    )


def apply_knowledge_proposal(
    proposal_id: int,
    request: KnowledgeProposalActionRequest,
) -> KnowledgeApplyResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        service = KnowledgeService(
            store=store,
            settings=settings,
            vault_root=root,
            indexer_factory=build_indexer_factory(
                store=store, settings=settings, vault_root=root
            ),
        )
        result = service.apply_proposal(proposal_id)
    finally:
        store.close()
    return KnowledgeApplyResponse(
        proposal_id=result.proposal_id,
        target_path=result.target_path,
        written_path=result.written_path,
        reindexed_files=result.reindexed_files,
    )


def reject_knowledge_proposal(
    proposal_id: int,
    request: KnowledgeProposalActionRequest,
) -> KnowledgeRejectResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        service = KnowledgeService(store=store, settings=settings, vault_root=root)
        proposal = service.reject_proposal(proposal_id, reason=request.reason)
    finally:
        store.close()
    return KnowledgeRejectResponse(proposal=_proposal_detail(proposal))


def knowledge_source_detail(
    request: KnowledgeSourceDetailRequest,
) -> KnowledgeSourceDetailResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        source = store.get_source(request.bundle_id, request.source_id)
        if not source:
            raise SynapseNotFoundError(
                f"Source {request.source_id} not found in bundle {request.bundle_id}"
            )
        segments = store.get_source_segments(source["id"])
        service = KnowledgeService(store=store, settings=settings, vault_root=root)
        all_proposals = service.list_proposals()
    finally:
        store.close()
    related = [
        _proposal_detail(row)
        for row in all_proposals
        if (row.get("supporting_refs") or {}).get("source_id") == request.source_id
        and (row.get("supporting_refs") or {}).get("bundle_id") == request.bundle_id
    ]
    return KnowledgeSourceDetailResponse(
        bundle_id=request.bundle_id,
        source_id=request.source_id,
        source={
            key: source.get(key)
            for key in (
                "title",
                "origin_url",
                "direct_paper_url",
                "authors",
                "published",
                "summary_text",
                "abstract_text",
                "source_type",
            )
        },
        related_proposals=related,
        segments=[
            KnowledgeSourceSegment(
                id=segment["id"],
                content_role=segment["content_role"],
                segment_index=segment["segment_index"],
                text=segment["text"],
                token_count=segment.get("token_count") or 0,
                metadata=segment.get("metadata") or {},
            )
            for segment in segments
        ],
    )


def knowledge_bundle_detail(
    request: KnowledgeBundleDetailRequest,
) -> KnowledgeBundleDetailResponse:
    settings, root, db = _knowledge_service_context(
        request.config_path, request.vault_root, request.db_path
    )
    store = _open_knowledge_store(settings, db)
    try:
        bundle = store.get_bundle(request.bundle_id)
        if not bundle:
            raise SynapseNotFoundError(f"Bundle not found: {request.bundle_id}")
        sources = store.list_sources_for_bundle(request.bundle_id)
        service = KnowledgeService(store=store, settings=settings, vault_root=root)
        all_proposals = service.list_proposals()
    finally:
        store.close()

    proposal_map: dict[tuple[str, str], list[dict]] = {}
    for row in all_proposals:
        refs = row.get("supporting_refs") or {}
        key = (str(refs.get("bundle_id") or ""), str(refs.get("source_id") or ""))
        if key[0] and key[1]:
            proposal_map.setdefault(key, []).append(row)

    summaries: list[KnowledgeBundleSourceSummary] = []
    for source in sources:
        key = (request.bundle_id, str(source.get("source_id") or ""))
        related = proposal_map.get(key, [])
        latest = max(
            related,
            key=lambda row: str(row.get("updated_at") or row.get("created_at") or ""),
            default=None,
        )
        summaries.append(
            KnowledgeBundleSourceSummary(
                bundle_id=request.bundle_id,
                source_id=str(source.get("source_id") or ""),
                title=source.get("title"),
                source_type=source.get("source_type"),
                published=source.get("published"),
                proposal_count=len(related),
                applied_count=sum(1 for row in related if row.get("status") == "applied"),
                latest_status=(latest or {}).get("status"),
            )
        )

    return KnowledgeBundleDetailResponse(
        bundle_id=request.bundle_id,
        bundle={
            key: bundle.get(key)
            for key in ("bundle_id", "artifact_path", "imported_at", "metadata", "artifact")
        },
        sources=summaries,
    )


def _proposal_detail(row: dict) -> KnowledgeProposalDetail:
    return KnowledgeProposalDetail(
        id=row["id"],
        job_id=row.get("job_id"),
        note_kind=row["note_kind"],
        slug=row["slug"],
        target_path=row["target_path"],
        title=row.get("title"),
        status=row["status"],
        body_markdown=row.get("body_markdown", ""),
        frontmatter=row.get("frontmatter") or {},
        supporting_refs=row.get("supporting_refs") or {},
        base_content_hash=row.get("base_content_hash"),
        reviewer_action=row.get("reviewer_action") or {},
        created_at=str(row.get("created_at")) if row.get("created_at") else None,
        updated_at=str(row.get("updated_at")) if row.get("updated_at") else None,
    )


def _provider_summary(provider: ProviderSettings) -> ProviderSummary:
    return ProviderSummary(
        name=provider.name,
        type=provider.type,
        model=provider.model,
        base_url=provider.base_url,
        dimensions=provider.dimensions,
        context_strategy=provider.context_strategy,
    )


def _sqlite_vec_available() -> bool:
    return sqlite_vec is not None


def _assert_matching_dimensions(note_cfg: ProviderSettings, chunk_cfg: ProviderSettings) -> None:
    if note_cfg.dimensions != chunk_cfg.dimensions:
        raise SynapseBadRequestError(
            f"Note provider dimension {note_cfg.dimensions} must match chunk provider dimension {chunk_cfg.dimensions}"
        )


def _assert_workspace_handle(workspace: WorkspaceHandle) -> None:
    if workspace != "current":
        raise SynapseBadRequestError(
            f"Unsupported workspace handle: {workspace}. Use workspace='current'."
        )


def _discovery_result(item: Discovery) -> DiscoveryResult:
    return DiscoveryResult(
        source_path=item.source_path,
        source_title=item.source_title,
        target_path=item.target_path,
        target_title=item.target_title,
        similarity=item.similarity,
        semantic_similarity=item.semantic_similarity,
        metadata_score=item.metadata_score,
        graph_score=item.graph_score,
    )


def _broken_link_result(item: BrokenLink) -> BrokenLinkResult:
    return BrokenLinkResult(
        source_path=item.source_path,
        target_link=item.target_link,
    )
