"""Validation module — check integrity of the knowledge graph."""

from dataclasses import dataclass
from pathlib import Path
from typing import Set

from .discovery import extract_wikilinks
from .vector_store import VectorStore, create_vector_store

@dataclass
class BrokenLink:
    """A link that points to a non-existent note."""
    source_path: str
    target_link: str


@dataclass
class VectorIntegrity:
    """Vector-to-segment linkage diagnostics for sqlite-vec storage."""

    segment_count: int
    vector_count: int
    orphan_vector_count: int
    missing_vector_count: int
    shadow_rowids_id_null_count: int
    linkage_key: str
    status: str


def find_broken_links(db: VectorStore) -> list[BrokenLink]:
    """Scan indexed notes for broken wikilinks."""
    valid_targets: Set[str] = set()
    rows = [
        (row["note_path"], row["title"])
        for row in db.conn.execute("SELECT note_path, title FROM notes").fetchall()
    ]

    docs = []
    for path, title in rows:
        valid_targets.add(path)
        if title:
            valid_targets.add(title)

        stem = path.split("/")[-1].replace(".md", "")
        valid_targets.add(stem)
        docs.append((path, title))

    broken_links = []

    for path, title in docs:
        content = _get_note_content(db, path)
        links = extract_wikilinks(content)

        for link in links:
            if link not in valid_targets:
                broken_links.append(BrokenLink(path, link))

    return broken_links


def inspect_vector_integrity(db: VectorStore) -> VectorIntegrity:
    """Report whether sqlite-vec rows still line up with Synapse segments."""
    segment_count = _count(db, "SELECT COUNT(*) FROM segments")
    rowids_available = _table_exists(db, "vec_segments_rowids")
    id_column_available = _column_exists(db, "vec_segments_rowids", "id")

    if rowids_available:
        vector_count = _count(db, "SELECT COUNT(*) FROM vec_segments_rowids")
        orphan_vector_count = _count(
            db,
            """
            SELECT COUNT(*)
            FROM vec_segments_rowids vr
            LEFT JOIN segments s ON s.id = vr.rowid
            WHERE s.id IS NULL
            """,
        )
        missing_vector_count = _count(
            db,
            """
            SELECT COUNT(*)
            FROM segments s
            LEFT JOIN vec_segments_rowids vr ON vr.rowid = s.id
            WHERE vr.rowid IS NULL
            """,
        )
        shadow_rowids_id_null_count = (
            _count(db, "SELECT COUNT(*) FROM vec_segments_rowids WHERE id IS NULL")
            if id_column_available
            else 0
        )
    else:
        vector_count = _count(db, "SELECT COUNT(*) FROM vec_segments")
        orphan_vector_count = _count(
            db,
            """
            SELECT COUNT(*)
            FROM vec_segments v
            LEFT JOIN segments s ON s.id = v.segment_id
            WHERE s.id IS NULL
            """,
        )
        missing_vector_count = _count(
            db,
            """
            SELECT COUNT(*)
            FROM segments s
            LEFT JOIN vec_segments v ON v.segment_id = s.id
            WHERE v.segment_id IS NULL
            """,
        )
        shadow_rowids_id_null_count = 0

    status = "ok"
    if orphan_vector_count > 0:
        status = "error"
    elif missing_vector_count > 0:
        status = "warning"

    return VectorIntegrity(
        segment_count=segment_count,
        vector_count=vector_count,
        orphan_vector_count=orphan_vector_count,
        missing_vector_count=missing_vector_count,
        shadow_rowids_id_null_count=shadow_rowids_id_null_count,
        linkage_key="segments.id -> vec_segments.segment_id / vec_segments_rowids.rowid",
        status=status,
    )


def _count(db: VectorStore, query: str) -> int:
    row = db.conn.execute(query).fetchone()
    return int(row[0] if row else 0)


def _table_exists(db: VectorStore, table_name: str) -> bool:
    row = db.conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = ?
        LIMIT 1
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _column_exists(db: VectorStore, table_name: str, column_name: str) -> bool:
    return any(
        row["name"] == column_name
        for row in db.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    )


def _get_note_content(db: VectorStore, note_path: str) -> str:
    """Get note body content from the source-first notes table."""
    row = db.conn.execute(
        "SELECT body_text FROM notes WHERE note_path = ?",
        (note_path,),
    ).fetchone()

    if not row:
        return ""
    return str(row[0] or "")
def main():
    """CLI entry point for validation."""
    import argparse
    from .settings import load_settings
    
    parser = argparse.ArgumentParser(
        description="🛡️ Synapse Validator — Check knowledge graph integrity"
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Synapse TOML config"
    )
    parser.add_argument(
        "--db", 
        default=None,
        help="Path to synapse database"
    )
    
    args = parser.parse_args()
    settings = load_settings(args.config)
    provider = settings.embedding_provider()
    
    db_path = Path(args.db or settings.database.path).expanduser()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1
        
    print(f"🛡️ Validating Knowledge Graph...")
    print(f"   Database: {db_path}")
    
    db = create_vector_store(settings, db_path=db_path, embedding_dim=provider.dimensions)
    db.initialize()
    
    broken_links = find_broken_links(db)
    vector_integrity = inspect_vector_integrity(db)

    print("\nVector integrity:")
    print(f"   Status: {vector_integrity.status}")
    print(f"   Segments: {vector_integrity.segment_count}")
    print(f"   Vectors: {vector_integrity.vector_count}")
    print(f"   Orphan vectors: {vector_integrity.orphan_vector_count}")
    print(f"   Missing vectors: {vector_integrity.missing_vector_count}")
    print(
        "   sqlite-vec shadow rowids.id NULLs: "
        f"{vector_integrity.shadow_rowids_id_null_count} (informational)"
    )
    print(f"   Linkage key: {vector_integrity.linkage_key}")
    
    if not broken_links:
        print("\n✅ No broken links found! Graph is healthy.")
        return 0 if vector_integrity.status != "error" else 1
        
    print(f"\n❌ Found {len(broken_links)} broken links:\n")
    
    for link in broken_links[:5]: # Limit output to avoid spam
        print(f"   {link.source_path}")
        print(f"   └── [[{link.target_link}]] (Target not found)")
        print()
    if len(broken_links) > 5:
        print(f"... and {len(broken_links) - 5} more.")
        
    return 1

if __name__ == "__main__":
    exit(main())
