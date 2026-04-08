"""Database operations for Synapse's source-first research corpus."""
import json
import sqlite3
import struct
from contextlib import suppress
from pathlib import Path
from typing import Any

try:
    import sqlite_vec
except ImportError:  # pragma: no cover - optional at import time
    sqlite_vec = None


class Database:
    """SQLite database with vector search capabilities."""

    def __init__(
        self,
        db_path: Path | str,
        embedding_dim: int = 768,
        extension_path: Path | str | None = None,
    ):
        self.db_path = Path(db_path)
        self.embedding_dim = embedding_dim
        self.extension_path = Path(extension_path).expanduser() if extension_path else None
        self.conn: sqlite3.Connection | None = None

    def initialize(self) -> None:
        """Create database and initialize schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

        self._load_vec_extension()

        self._create_schema()

    def _create_schema(self) -> None:
        """Create all required tables."""
        cur = self.conn.cursor()

        # Source-first research corpus tables.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS bundles (
                id INTEGER PRIMARY KEY,
                bundle_id TEXT UNIQUE NOT NULL,
                artifact_path TEXT,
                content_hash TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                artifact_json TEXT NOT NULL DEFAULT '{}',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS sources (
                id INTEGER PRIMARY KEY,
                bundle_row_id INTEGER NOT NULL REFERENCES bundles(id) ON DELETE CASCADE,
                source_id TEXT NOT NULL,
                origin_url TEXT,
                direct_paper_url TEXT,
                title TEXT,
                authors_json TEXT NOT NULL DEFAULT '[]',
                published TEXT,
                source_type TEXT,
                retrieved_at TEXT,
                extraction_status TEXT,
                extraction_method TEXT,
                summary_text TEXT,
                abstract_text TEXT,
                full_text TEXT,
                full_text_path TEXT,
                note_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                artifact_json TEXT NOT NULL DEFAULT '{}',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(bundle_row_id, source_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY,
                note_path TEXT UNIQUE,
                note_kind TEXT,
                title TEXT,
                body_text TEXT NOT NULL DEFAULT '',
                content_hash TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS note_sources (
                note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
                source_row_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (note_id, source_row_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS segments (
                id INTEGER PRIMARY KEY,
                owner_kind TEXT NOT NULL,
                owner_source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
                owner_note_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
                source_row_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
                note_row_id INTEGER REFERENCES notes(id) ON DELETE CASCADE,
                content_role TEXT NOT NULL,
                segment_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                token_count INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                imported_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CHECK (
                    (owner_kind = 'source' AND owner_source_id IS NOT NULL AND owner_note_id IS NULL)
                    OR
                    (owner_kind = 'note' AND owner_note_id IS NOT NULL)
                )
            )
        """)
        cur.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_segments USING vec0(
                segment_id INTEGER PRIMARY KEY,
                embedding float[{self.embedding_dim}]
            )
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
                segment_id UNINDEXED,
                text,
                owner_kind UNINDEXED,
                content_role UNINDEXED,
                tokenize = 'unicode61'
            )
        """)
        
        # Discoveries table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS discoveries (
                id INTEGER PRIMARY KEY,
                source_path TEXT NOT NULL,
                target_path TEXT NOT NULL,
                similarity REAL,
                discovered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'pending',
                UNIQUE(source_path, target_path)
            )
        """)
        
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_sources_bundle_row_id ON sources(bundle_row_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_owner_source_id ON segments(owner_source_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_owner_note_id ON segments(owner_note_id)
        """)
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_segments_source_row_id ON segments(source_row_id)
        """)
        
        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def list_tables(self) -> list[str]:
        """List all tables in the database."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT name FROM sqlite_master 
            WHERE type IN ('table', 'virtual table') AND name NOT LIKE 'sqlite_%'
            ORDER BY name
        """)
        return [row[0] for row in cur.fetchall()]

    def vec_version(self) -> str | None:
        """Get vector implementation version."""
        cur = self.conn.cursor()
        try:
            cur.execute("SELECT vec_version()")
            return cur.fetchone()[0]
        except Exception:
            return "unknown"

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
        """Insert or update a bundle row, replacing previous imports with the same bundle_id."""
        cur = self.conn.cursor()
        cur.execute("SELECT id FROM bundles WHERE bundle_id = ?", (bundle_id,))
        existing = cur.fetchone()
        metadata_json = json.dumps(metadata or {}, sort_keys=True)
        artifact_json = json.dumps(artifact or {}, sort_keys=True)

        if existing:
            cur.execute("""
                UPDATE bundles
                SET artifact_path = ?, content_hash = ?, metadata_json = ?, artifact_json = ?, imported_at = CURRENT_TIMESTAMP
                WHERE bundle_id = ?
            """, (artifact_path, content_hash, metadata_json, artifact_json, bundle_id))
            bundle_row_id = existing["id"]
        else:
            cur.execute("""
                INSERT INTO bundles (bundle_id, artifact_path, content_hash, metadata_json, artifact_json)
                VALUES (?, ?, ?, ?, ?)
            """, (bundle_id, artifact_path, content_hash, metadata_json, artifact_json))
            bundle_row_id = cur.lastrowid

        if commit:
            self.conn.commit()
        return bundle_row_id

    def get_bundle(self, bundle_id: str) -> dict[str, Any] | None:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, bundle_id, artifact_path, content_hash, metadata_json, artifact_json, imported_at
            FROM bundles WHERE bundle_id = ?
        """, (bundle_id,))
        row = cur.fetchone()
        if not row:
            return None
        bundle = dict(row)
        bundle["metadata"] = _json_load(bundle.pop("metadata_json"), {})
        bundle["artifact"] = _json_load(bundle.pop("artifact_json"), {})
        return bundle

    def delete_bundle(self, bundle_id: str, *, commit: bool = True) -> int:
        """Delete a previously imported bundle and all dependent source-first rows."""
        cur = self.conn.cursor()
        source_rows = cur.execute(
            "SELECT id FROM sources WHERE bundle_row_id IN (SELECT id FROM bundles WHERE bundle_id = ?)",
            (bundle_id,),
        ).fetchall()
        source_ids = [row["id"] for row in source_rows]
        segment_rows = []
        if source_ids:
            placeholders = ", ".join("?" for _ in source_ids)
            segment_rows = cur.execute(
                f"SELECT id FROM segments WHERE owner_source_id IN ({placeholders}) OR source_row_id IN ({placeholders})",
                [*source_ids, *source_ids],
            ).fetchall()
        deleted_segments = [row["id"] for row in segment_rows]
        for segment_id in deleted_segments:
            self._delete_segment_indexes(segment_id, commit=False)

        cur.execute("DELETE FROM bundles WHERE bundle_id = ?", (bundle_id,))
        deleted = cur.rowcount
        if commit:
            self.conn.commit()
        return deleted

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
    ) -> int:
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO sources (
                bundle_row_id, source_id, origin_url, direct_paper_url, title, authors_json, published,
                source_type, retrieved_at, extraction_status, extraction_method, summary_text,
                abstract_text, full_text, full_text_path, note_path, metadata_json, artifact_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bundle_row_id,
            source_id,
            origin_url,
            direct_paper_url,
            title,
            json.dumps(authors or [], sort_keys=True),
            published,
            source_type,
            retrieved_at,
            extraction_status,
            extraction_method,
            summary_text,
            abstract_text,
            full_text,
            full_text_path,
            note_path,
            json.dumps(metadata or {}, sort_keys=True),
            json.dumps(artifact or {}, sort_keys=True),
        ))
        source_row_id = cur.lastrowid
        if commit:
            self.conn.commit()
        return source_row_id

    def get_source(self, bundle_id: str, source_id: str) -> dict[str, Any] | None:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT
                s.id,
                b.bundle_id,
                s.source_id,
                s.origin_url,
                s.direct_paper_url,
                s.title,
                s.authors_json,
                s.published,
                s.source_type,
                s.retrieved_at,
                s.extraction_status,
                s.extraction_method,
                s.summary_text,
                s.abstract_text,
                s.full_text,
                s.full_text_path,
                s.note_path,
                s.metadata_json,
                s.artifact_json,
                s.imported_at
            FROM sources s
            JOIN bundles b ON b.id = s.bundle_row_id
            WHERE b.bundle_id = ? AND s.source_id = ?
        """, (bundle_id, source_id))
        row = cur.fetchone()
        if not row:
            return None
        source = dict(row)
        source["authors"] = _json_load(source.pop("authors_json"), [])
        source["metadata"] = _json_load(source.pop("metadata_json"), {})
        source["artifact"] = _json_load(source.pop("artifact_json"), {})
        return source

    def insert_note(
        self,
        *,
        note_path: str | None,
        title: str | None,
        body_text: str,
        note_kind: str | None = None,
        content_hash: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> int:
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO notes (note_path, note_kind, title, body_text, content_hash, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            note_path,
            note_kind,
            title,
            body_text,
            content_hash,
            json.dumps(metadata or {}, sort_keys=True),
        ))
        note_id = cur.lastrowid
        if commit:
            self.conn.commit()
        return note_id

    def get_note(self, note_path: str) -> dict[str, Any] | None:
        cur = self.conn.cursor()
        row = cur.execute("""
            SELECT id, note_path, note_kind, title, body_text, content_hash, metadata_json, imported_at
            FROM notes
            WHERE note_path = ?
        """, (note_path,)).fetchone()
        if not row:
            return None
        note = dict(row)
        note["metadata"] = _json_load(note.pop("metadata_json"), {})
        return note

    def delete_note(self, note_id: int, *, commit: bool = True) -> int:
        cur = self.conn.cursor()
        segment_rows = cur.execute(
            "SELECT id FROM segments WHERE owner_note_id = ? OR note_row_id = ?",
            (note_id, note_id),
        ).fetchall()
        for row in segment_rows:
            self._delete_segment_indexes(row["id"], commit=False)
        cur.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        deleted = cur.rowcount
        if commit:
            self.conn.commit()
        return deleted

    def link_note_source(
        self,
        note_id: int,
        source_row_id: int,
        metadata: dict[str, Any] | None = None,
        *,
        commit: bool = True,
    ) -> None:
        cur = self.conn.cursor()
        cur.execute("""
            INSERT OR REPLACE INTO note_sources (note_id, source_row_id, metadata_json)
            VALUES (?, ?, ?)
        """, (note_id, source_row_id, json.dumps(metadata or {}, sort_keys=True)))
        if commit:
            self.conn.commit()

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
    ) -> int:
        """Insert a source-first segment with optional vector and lexical indexes."""
        if owner_kind not in {"source", "note"}:
            raise ValueError(f"Unsupported owner kind: {owner_kind}")

        owner_source_id = owner_id if owner_kind == "source" else None
        owner_note_id = owner_id if owner_kind == "note" else None
        source_ref = source_row_id if source_row_id is not None else owner_source_id
        note_ref = note_row_id if note_row_id is not None else owner_note_id

        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO segments (
                owner_kind, owner_source_id, owner_note_id, source_row_id, note_row_id,
                content_role, segment_index, text, token_count, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            owner_kind,
            owner_source_id,
            owner_note_id,
            source_ref,
            note_ref,
            content_role,
            segment_index,
            text,
            _estimate_tokens(text),
            json.dumps(metadata or {}, sort_keys=True),
        ))
        segment_id = cur.lastrowid
        cur.execute("""
            INSERT INTO segments_fts (segment_id, text, owner_kind, content_role)
            VALUES (?, ?, ?, ?)
        """, (segment_id, text, owner_kind, content_role))
        if embedding is not None:
            cur.execute("""
                INSERT INTO vec_segments (segment_id, embedding)
                VALUES (?, ?)
            """, (segment_id, _serialize_f32(embedding)))
        if commit:
            self.conn.commit()
        return segment_id

    def get_source_segments(self, source_row_id: int) -> list[dict[str, Any]]:
        cur = self.conn.cursor()
        rows = cur.execute("""
            SELECT id, owner_kind, content_role, segment_index, text, token_count, metadata_json
            FROM segments
            WHERE source_row_id = ?
            ORDER BY segment_index
        """, (source_row_id,)).fetchall()
        results = []
        for row in rows:
            segment = dict(row)
            segment["metadata"] = _json_load(segment.pop("metadata_json"), {})
            results.append(segment)
        return results

    def search_segments_lexical(
        self,
        query: str,
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search indexed source-first segments with FTS5/BM25."""
        cur = self.conn.cursor()
        where_clauses = ["segments_fts MATCH ?"]
        params: list[Any] = [query]
        filter_sql, filter_params = _segment_filter_sql(filters)
        where_clauses.extend(filter_sql)
        params.extend(filter_params)
        params.append(limit)

        rows = cur.execute(f"""
            SELECT
                s.id AS segment_id,
                s.owner_kind,
                s.content_role,
                s.segment_index,
                s.text AS segment_text,
                s.token_count,
                src.id AS source_row_id,
                b.bundle_id,
                src.source_id,
                src.title AS source_title,
                src.origin_url,
                src.direct_paper_url,
                src.source_type,
                n.id AS note_row_id,
                n.note_path,
                n.title AS note_title,
                n.note_kind,
                bm25(segments_fts) AS bm25_score
            FROM segments_fts
            JOIN segments s ON s.id = segments_fts.segment_id
            LEFT JOIN sources src ON src.id = COALESCE(s.source_row_id, s.owner_source_id)
            LEFT JOIN bundles b ON b.id = src.bundle_row_id
            LEFT JOIN notes n ON n.id = COALESCE(s.note_row_id, s.owner_note_id)
            WHERE {" AND ".join(where_clauses)}
            ORDER BY bm25_score, s.id
            LIMIT ?
        """, params).fetchall()
        return [_segment_search_row(dict(row), lexical=True) for row in rows]

    def search_segments_vector(
        self,
        query_embedding: list[float],
        *,
        limit: int = 10,
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search indexed source-first segments with sqlite-vec."""
        cur = self.conn.cursor()
        where_clauses = ["embedding MATCH ?", "k = ?"]
        params: list[Any] = [_serialize_f32(query_embedding), limit]
        filter_sql, filter_params = _segment_filter_sql(filters)
        where_clauses.extend(filter_sql)
        params.extend(filter_params)

        rows = cur.execute(f"""
            SELECT
                s.id AS segment_id,
                s.owner_kind,
                s.content_role,
                s.segment_index,
                s.text AS segment_text,
                s.token_count,
                src.id AS source_row_id,
                b.bundle_id,
                src.source_id,
                src.title AS source_title,
                src.origin_url,
                src.direct_paper_url,
                src.source_type,
                n.id AS note_row_id,
                n.note_path,
                n.title AS note_title,
                n.note_kind,
                distance
            FROM vec_segments v
            JOIN segments s ON s.id = v.segment_id
            LEFT JOIN sources src ON src.id = COALESCE(s.source_row_id, s.owner_source_id)
            LEFT JOIN bundles b ON b.id = src.bundle_row_id
            LEFT JOIN notes n ON n.id = COALESCE(s.note_row_id, s.owner_note_id)
            WHERE {" AND ".join(where_clauses)}
            ORDER BY distance
        """, params).fetchall()
        return [_segment_search_row(dict(row), lexical=False) for row in rows]

    def _extension_candidates(self) -> list[Path | str]:
        candidates: list[Path | str] = []
        if self.extension_path:
            candidates.append(self.extension_path)
        return candidates

    def _load_vec_extension(self) -> None:
        self.conn.enable_load_extension(True)
        if sqlite_vec is not None:
            try:
                sqlite_vec.load(self.conn)
                return
            except sqlite3.OperationalError as exc:
                last_error: sqlite3.OperationalError | None = exc
            except Exception as exc:  # pragma: no cover - defensive
                last_error = sqlite3.OperationalError(str(exc))
        else:
            last_error = None

        for candidate in self._extension_candidates():
            try:
                self.conn.load_extension(str(candidate))
                return
            except sqlite3.OperationalError as exc:
                last_error = exc

        if last_error is not None:
            print(f"❌ Failed to load sqlite-vec extension: {last_error}")
            raise last_error

    def _delete_segment_indexes(self, segment_id: int, *, commit: bool = True) -> None:
        cur = self.conn.cursor()
        cur.execute("DELETE FROM segments_fts WHERE segment_id = ?", (segment_id,))
        with suppress(sqlite3.OperationalError):
            cur.execute("DELETE FROM vec_segments WHERE segment_id = ?", (segment_id,))
        if commit:
            self.conn.commit()


def _serialize_f32(vec: list[float]) -> bytes:
    """Serialize a list of floats to bytes (little-endian float32)."""
    return struct.pack(f"{len(vec)}f", *vec)


def _json_load(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default


def _estimate_tokens(text: str) -> int:
    cleaned = " ".join(text.split())
    if not cleaned:
        return 0
    return max(1, round(len(cleaned) / 4))


def _segment_filter_sql(filters: dict[str, Any] | None) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if not filters:
        return clauses, params

    if owner_kind := filters.get("owner_kind"):
        clauses.append("s.owner_kind = ?")
        params.append(owner_kind)
    if bundle_id := filters.get("bundle_id"):
        clauses.append("b.bundle_id = ?")
        params.append(bundle_id)
    if source_id := filters.get("source_id"):
        clauses.append("src.source_id = ?")
        params.append(source_id)
    if source_type := filters.get("source_type"):
        clauses.append("src.source_type = ?")
        params.append(source_type)
    if content_role := filters.get("content_role"):
        clauses.append("s.content_role = ?")
        params.append(content_role)
    if note_path := filters.get("note_path"):
        clauses.append("n.note_path = ?")
        params.append(note_path)
    return clauses, params


def _segment_search_row(row: dict[str, Any], *, lexical: bool) -> dict[str, Any]:
    bm25_score = row.pop("bm25_score", None)
    distance = row.pop("distance", None)
    vector_score = None if distance is None else 1.0 / (1.0 + max(distance, 0.0))
    title = row.get("source_title") or row.get("note_title")
    result = {
        **row,
        "title": title,
        "bm25_score": bm25_score if lexical else None,
        "vector_score": vector_score,
        "distance": distance,
    }
    return result
