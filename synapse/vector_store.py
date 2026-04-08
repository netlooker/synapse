"""Vector store abstractions for Synapse."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Protocol

from .db import Database
from .settings import AppSettings


class VectorStore(Protocol):
    """Minimal vector store interface used by the current application layer."""

    conn: sqlite3.Connection | None

    def initialize(self) -> None: ...
    def close(self) -> None: ...
    def list_tables(self) -> list[str]: ...
    def vec_version(self) -> str | None: ...
    def upsert_bundle(
        self,
        bundle_id: str,
        content_hash: str,
        artifact_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        *,
        commit: bool = True,
    ) -> int: ...
    def get_bundle(self, bundle_id: str) -> dict[str, Any] | None: ...
    def delete_bundle(self, bundle_id: str, *, commit: bool = True) -> int: ...
    def insert_source(
        self,
        bundle_row_id: int,
        source_id: str,
        *,
        origin_url: str | None = None,
        direct_paper_url: str | None = None,
        title: str | None = None,
        authors: list[str] | None = None,
        published: str | None = None,
        source_type: str | None = None,
        retrieved_at: str | None = None,
        extraction_status: str | None = None,
        extraction_method: str | None = None,
        summary_text: str | None = None,
        abstract_text: str | None = None,
        full_text: str | None = None,
        full_text_path: str | None = None,
        note_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> int: ...
    def get_source(self, bundle_id: str, source_id: str) -> dict[str, Any] | None: ...
    def get_note(self, note_path: str) -> dict[str, Any] | None: ...
    def delete_note(self, note_id: int, *, commit: bool = True) -> int: ...
    def insert_segment(
        self,
        *,
        owner_kind: str,
        owner_id: int,
        content_role: str,
        segment_index: int,
        text: str,
        embedding: list[float] | None,
        source_row_id: int | None = None,
        note_row_id: int | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> int: ...
    def get_source_segments(self, source_row_id: int) -> list[dict[str, Any]]: ...
    def search_segments_lexical(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...
    def search_segments_vector(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]: ...


class SQLiteVecStore:
    """Thin wrapper around the existing sqlite-vec-backed database implementation."""

    def __init__(
        self,
        db_path: Path | str,
        embedding_dim: int,
        extension_path: Path | str | None = None,
    ):
        self.backend = Database(
            db_path=db_path,
            embedding_dim=embedding_dim,
            extension_path=extension_path,
        )

    @property
    def conn(self) -> sqlite3.Connection | None:
        return self.backend.conn

    def initialize(self) -> None:
        self.backend.initialize()

    def close(self) -> None:
        self.backend.close()

    def list_tables(self) -> list[str]:
        return self.backend.list_tables()

    def vec_version(self) -> str | None:
        return self.backend.vec_version()

    def upsert_bundle(
        self,
        bundle_id: str,
        content_hash: str,
        artifact_path: str | None = None,
        metadata: dict[str, Any] | None = None,
        artifact: dict[str, Any] | None = None,
        *,
        commit: bool = True,
    ) -> int:
        return self.backend.upsert_bundle(
            bundle_id,
            content_hash,
            artifact_path=artifact_path,
            metadata=metadata,
            artifact=artifact,
            commit=commit,
        )

    def get_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        return self.backend.get_bundle(bundle_id)

    def delete_bundle(self, bundle_id: str, *, commit: bool = True) -> int:
        return self.backend.delete_bundle(bundle_id, commit=commit)

    def insert_source(self, bundle_row_id: int, source_id: str, **kwargs: Any) -> int:
        return self.backend.insert_source(bundle_row_id, source_id, **kwargs)

    def get_source(self, bundle_id: str, source_id: str) -> dict[str, Any] | None:
        return self.backend.get_source(bundle_id, source_id)

    def get_note(self, note_path: str) -> dict[str, Any] | None:
        return self.backend.get_note(note_path)

    def delete_note(self, note_id: int, *, commit: bool = True) -> int:
        return self.backend.delete_note(note_id, commit=commit)

    def insert_segment(self, **kwargs: Any) -> int:
        return self.backend.insert_segment(**kwargs)

    def get_source_segments(self, source_row_id: int) -> list[dict[str, Any]]:
        return self.backend.get_source_segments(source_row_id)

    def search_segments_lexical(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.backend.search_segments_lexical(query, limit=limit, filters=filters)

    def search_segments_vector(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return self.backend.search_segments_vector(query_embedding, limit=limit, filters=filters)


def create_vector_store(
    settings: AppSettings,
    db_path: Path | str | None = None,
    embedding_dim: int | None = None,
) -> VectorStore:
    """Create the configured vector store backend."""
    store_type = settings.vector_store.type
    resolved_db_path = Path(db_path or settings.database.path).expanduser()

    if store_type == "sqlite_vec":
        return SQLiteVecStore(
            db_path=resolved_db_path,
            embedding_dim=embedding_dim or settings.embedding_provider().dimensions,
            extension_path=settings.database.extension_file(),
        )

    raise ValueError(f"Unsupported vector store type: {store_type}")
