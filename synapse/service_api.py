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
    total_chunks: int


class IndexResponse(BaseModel):
    vault_root: str
    database_path: str
    note_provider: str
    chunk_provider: str
    stats: IndexStats


class SearchRequest(BaseModel):
    query: str
    config_path: str | None = None
    db_path: str | None = None
    note_provider: str | None = None
    chunk_provider: str | None = None
    mode: Literal["note", "chunk", "hybrid"] = "hybrid"
    limit: int | None = None


class SearchResult(BaseModel):
    path: str
    title: str
    similarity: float
    snippet: str
    note_similarity: float | None = None
    chunk_similarity: float | None = None
    metadata_boost: float | None = None


class SearchResponse(BaseModel):
    query: str
    mode: str
    database_path: str
    results: list[SearchResult] = Field(default_factory=list)


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
            cortex_path=root,
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


def search_index(request: SearchRequest) -> SearchResponse:
    settings, _, db = resolve_runtime(request.config_path, None, request.db_path)
    if not db.exists():
        raise SynapseNotFoundError(f"Synapse database not found: {db}")

    note_cfg = settings.embedding_provider(request.note_provider or settings.search.provider)
    chunk_cfg = settings.embedding_provider(request.chunk_provider or settings.index.contextual_provider)
    _assert_matching_dimensions(note_cfg, chunk_cfg)

    store = create_vector_store(settings, db_path=db, embedding_dim=note_cfg.dimensions)
    store.initialize()
    try:
        searcher = Searcher(
            db=store,
            note_embedding_client=EmbeddingClient.from_provider(note_cfg),
            chunk_embedding_client=EmbeddingClient.from_provider(chunk_cfg),
            search_settings=settings.search,
        )
        results = searcher.search(
            query=request.query,
            limit=request.limit or settings.search.limit,
            mode=request.mode,
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
