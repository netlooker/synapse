"""Validation module — check integrity of the knowledge graph."""

from dataclasses import dataclass
from pathlib import Path
from typing import Set

from .discovery import extract_wikilinks
from .vector_store import VectorStore, create_vector_store

@dataclass
class BrokenLink:
    """A link that points to a non-existent document."""
    source_path: str
    target_link: str

def find_broken_links(db: VectorStore) -> list[BrokenLink]:
    """
    Scan all documents for broken wikilinks.
    """
    # 1. Get all valid titles and paths
    valid_targets: Set[str] = set()
    
    rows = db.conn.execute("SELECT path, title FROM documents").fetchall()
    
    docs = []
    for path, title in rows:
        valid_targets.add(path)
        if title:
            valid_targets.add(title)
        
        # Also allow linking by filename stem
        stem = path.split("/")[-1].replace(".md", "")
        valid_targets.add(stem)
        
        docs.append((path, title))

    # 2. Scan content for links
    broken_links = []
    
    for path, title in docs:
        content = _get_document_content(db, path)
        links = extract_wikilinks(content)
        
        for link in links:
            if link not in valid_targets:
                broken_links.append(BrokenLink(path, link))
                
    return broken_links

def _get_document_content(db: VectorStore, doc_path: str) -> str:
    """Get concatenated chunk content for a document."""
    # First get doc_id from path
    row = db.conn.execute(
        "SELECT id FROM documents WHERE path = ?",
        (doc_path,)
    ).fetchone()
    
    if not row:
        return ""
    
    doc_id = row[0]
    
    chunks = db.conn.execute(
        "SELECT chunk_text FROM chunks WHERE doc_id = ? AND scope = 'chunk' ORDER BY chunk_index",
        (doc_id,)
    ).fetchall()
    
    return "\n".join(content for (content,) in chunks)

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
    
    if not broken_links:
        print("\n✅ No broken links found! Graph is healthy.")
        return 0
        
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
