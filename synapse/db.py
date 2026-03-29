"""
synapse.db - Database operations with vector search

Uses sqlite-vec extension when available.
"""
import json
import sqlite3
import struct
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

        self._load_vec_extension()

        self._create_schema()

    def _create_schema(self) -> None:
        """Create all required tables."""
        cur = self.conn.cursor()
        
        # Documents table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                content_hash TEXT NOT NULL,
                title TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                wikilinks_json TEXT NOT NULL DEFAULT '[]',
                frontmatter_json TEXT NOT NULL DEFAULT '{}',
                indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        document_columns = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(documents)").fetchall()
        }
        if "tags_json" not in document_columns:
            cur.execute("ALTER TABLE documents ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'")
        if "wikilinks_json" not in document_columns:
            cur.execute("ALTER TABLE documents ADD COLUMN wikilinks_json TEXT NOT NULL DEFAULT '[]'")
        if "frontmatter_json" not in document_columns:
            cur.execute("ALTER TABLE documents ADD COLUMN frontmatter_json TEXT NOT NULL DEFAULT '{}'")
        
        # Chunks table (metadata)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                doc_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'chunk'
            )
        """)

        chunk_columns = {
            row["name"]
            for row in cur.execute("PRAGMA table_info(chunks)").fetchall()
        }
        if "scope" not in chunk_columns:
            cur.execute("ALTER TABLE chunks ADD COLUMN scope TEXT NOT NULL DEFAULT 'chunk'")

        # Vector table (sqlite-vec)
        # We use a separate virtual table linked by rowid (chunk_id)
        cur.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0(
                chunk_id INTEGER PRIMARY KEY,
                embedding float[{self.embedding_dim}]
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
        
        # Create index for faster lookups
        cur.execute("""
            CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id)
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
            WHERE type='table' AND name NOT LIKE 'sqlite_%'
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

    def upsert_document(
        self, 
        path: str, 
        content_hash: str, 
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Insert or update a document, returning its ID."""
        cur = self.conn.cursor()
        metadata = metadata or {}
        tags_json = json.dumps(metadata.get("tags", []), sort_keys=True)
        wikilinks_json = json.dumps(metadata.get("wikilinks", []), sort_keys=True)
        frontmatter_json = json.dumps(metadata.get("frontmatter", {}), sort_keys=True)
        
        # Try to get existing
        cur.execute("SELECT id FROM documents WHERE path = ?", (path,))
        existing = cur.fetchone()
        
        if existing:
            # Update
            cur.execute("""
                UPDATE documents 
                SET content_hash = ?, title = ?, tags_json = ?, wikilinks_json = ?, frontmatter_json = ?, indexed_at = CURRENT_TIMESTAMP
                WHERE path = ?
            """, (content_hash, title, tags_json, wikilinks_json, frontmatter_json, path))
            doc_id = existing[0]
        else:
            # Insert
            cur.execute("""
                INSERT INTO documents (path, content_hash, title, tags_json, wikilinks_json, frontmatter_json)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (path, content_hash, title, tags_json, wikilinks_json, frontmatter_json))
            doc_id = cur.lastrowid
        
        self.conn.commit()
        return doc_id

    def get_document(self, path: str) -> dict[str, Any] | None:
        """Get document by path."""
        cur = self.conn.cursor()
        cur.execute("""
            SELECT id, path, content_hash, title, tags_json, wikilinks_json, frontmatter_json, indexed_at
            FROM documents WHERE path = ?
        """, (path,))
        row = cur.fetchone()
        
        if row:
            doc = dict(row)
            doc["tags"] = _json_load(doc.pop("tags_json"), [])
            doc["wikilinks"] = _json_load(doc.pop("wikilinks_json"), [])
            doc["frontmatter"] = _json_load(doc.pop("frontmatter_json"), {})
            return doc
        return None

    def insert_chunk(
        self,
        doc_id: int,
        chunk_index: int,
        chunk_text: str,
        embedding: list[float],
        scope: str = "chunk",
    ) -> int:
        """Insert a chunk with its embedding."""
        cur = self.conn.cursor()
        
        # 1. Insert metadata into chunks table
        cur.execute("""
            INSERT INTO chunks (doc_id, chunk_index, chunk_text, scope)
            VALUES (?, ?, ?, ?)
        """, (doc_id, chunk_index, chunk_text, scope))
        chunk_id = cur.lastrowid
        
        # 2. Insert embedding into vector table
        # sqlite-vec expects raw bytes for float array if passed as param, 
        # or use vec_f32() function? No, with bindings we usually pass bytes or list.
        # Let's try passing the serialized bytes which works for most sqlite bindings.
        embedding_blob = _serialize_f32(embedding)
        
        cur.execute("""
            INSERT INTO vec_chunks (chunk_id, embedding)
            VALUES (?, ?)
        """, (chunk_id, embedding_blob))
        
        self.conn.commit()
        return chunk_id

    def search_similar(
        self, 
        query_embedding: list[float], 
        limit: int = 10,
        scope: str = "chunk",
        include_paths: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Find similar chunks by vector similarity using sqlite-vec."""
        cur = self.conn.cursor()
        
        embedding_blob = _serialize_f32(query_embedding)
        filters = ["c.scope = ?", "embedding MATCH ?", "k = ?"]
        params: list[Any] = [scope, embedding_blob, limit]
        if include_paths:
            placeholders = ", ".join("?" for _ in include_paths)
            filters.append(f"d.path IN ({placeholders})")
            params.extend(include_paths)
        
        # KNN Search using vec0 virtual table
        cur.execute(f"""
            SELECT 
                c.id as chunk_id,
                c.chunk_text,
                c.doc_id,
                d.path,
                d.title,
                d.tags_json,
                d.wikilinks_json,
                d.frontmatter_json,
                distance
            FROM vec_chunks v
            JOIN chunks c ON c.id = v.chunk_id
            JOIN documents d ON d.id = c.doc_id
            WHERE {" AND ".join(filters)}
            ORDER BY distance
        """, params)
        
        results = []
        for row in cur.fetchall():
            distance = row["distance"]
            # sqlite-vec returns a distance value. Convert that into a bounded
            # relevance score for display purposes instead of assuming cosine.
            similarity = 1.0 / (1.0 + max(distance, 0.0))
            
            results.append({
                "chunk_id": row["chunk_id"],
                "distance": distance,
                "similarity": similarity,
                "chunk_text": row["chunk_text"],
                "doc_id": row["doc_id"],
                "path": row["path"],
                "title": row["title"],
                "tags": _json_load(row["tags_json"], []),
                "wikilinks": _json_load(row["wikilinks_json"], []),
                "frontmatter": _json_load(row["frontmatter_json"], {}),
                "scope": scope,
            })
        
        return results

    def delete_chunks(self, doc_id: int) -> int:
        """Delete all chunks for a document."""
        cur = self.conn.cursor()
        
        # Get chunk IDs to delete from vector table
        cur.execute("SELECT id FROM chunks WHERE doc_id = ?", (doc_id,))
        chunk_ids = [row[0] for row in cur.fetchall()]
        
        if not chunk_ids:
            return 0
            
        # Delete metadata
        cur.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        deleted = cur.rowcount
        
        # Delete vectors (manually, since no cascade on virtual tables usually)
        # Using IN clause for vector table might be slow or unsupported?
        # vec0 supports DELETE WHERE rowid = ?
        for cid in chunk_ids:
             cur.execute("DELETE FROM vec_chunks WHERE chunk_id = ?", (cid,))

        self.conn.commit()
        return deleted

    def get_chunks(self, doc_id: int, scope: str | None = None) -> list[dict[str, Any]]:
        """Get all chunks for a document."""
        cur = self.conn.cursor()
        if scope is None:
            cur.execute("""
                SELECT id, chunk_index, chunk_text, scope
                FROM chunks WHERE doc_id = ?
                ORDER BY scope, chunk_index
            """, (doc_id,))
        else:
            cur.execute("""
                SELECT id, chunk_index, chunk_text, scope
                FROM chunks WHERE doc_id = ? AND scope = ?
                ORDER BY chunk_index
            """, (doc_id, scope))
        
        return [dict(row) for row in cur.fetchall()]

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
