"""Discovery module — find unlinked similar documents.

Surfaces "hidden connections" in the knowledge base by finding
documents that are semantically similar but not explicitly linked.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .vector_store import VectorStore, create_vector_store


# Regex to match [[wikilinks]], capturing the link text
WIKILINK_PATTERN = re.compile(r'\[\[([^\]]+)\]\]')


def extract_wikilinks(content: str) -> set[str]:
    """
    Extract wikilink targets from markdown content.
    
    Args:
        content: Markdown text potentially containing [[links]]
        
    Returns:
        Set of link targets (deduplicated)
    """
    matches = WIKILINK_PATTERN.findall(content)
    
    # Handle heading anchors: [[Document#Section]] → Document
    links = set()
    for match in matches:
        # Strip heading anchor if present
        base = match.split('#')[0].strip()
        if base:
            links.add(base)
    
    return links


@dataclass
class Discovery:
    """A discovered connection between two documents."""
    
    source_path: str
    source_title: str
    target_path: str
    target_title: str
    similarity: float
    semantic_similarity: float = 0.0
    metadata_score: float = 0.0
    graph_score: float = 0.0
    
    def __repr__(self) -> str:
        return (
            f"Discovery({self.source_title!r} → {self.target_title!r}, "
            f"sim={self.similarity:.1%})"
        )


def discover_for_document(
    db: VectorStore,
    doc_path: str,
    top_k: int = 5,
    threshold: float = 0.6
) -> list[Discovery]:
    """
    Find unlinked similar documents for a single document.
    
    Args:
        db: Synapse database connection
        doc_path: Path to the source document
        top_k: Maximum number of similar docs to check
        threshold: Minimum similarity score (0-1)
        
    Returns:
        List of Discovery objects for unlinked similar docs
    """
    # Get source document
    source_doc = _get_document_record(db, doc_path)
    if not source_doc:
        return []
    source_path = source_doc["path"]
    source_title = source_doc["title"] or Path(source_path).stem
    
    # Get source content to check existing links
    source_content = _get_document_content(db, doc_path)
    existing_links = extract_wikilinks(source_content)
    
    # Get source embedding (average of chunk embeddings)
    source_embedding = _get_document_embedding(db, doc_path)
    if source_embedding is None:
        return []
    
    # Find similar documents
    similar_docs = _find_similar_documents(
        db, source_embedding, top_k=top_k + 10, exclude_path=doc_path
    )
    
    discoveries = []
    for candidate in similar_docs:
        target_path = candidate["path"]
        target_title = candidate["title"] or Path(target_path).stem
        semantic_similarity = candidate["semantic_similarity"]
        
        # Check if already linked (source → target)
        if target_title in existing_links:
            continue
        
        # Check if already linked (target → source)
        target_content = _get_document_content(db, target_path)
        target_links = extract_wikilinks(target_content)
        if source_title in target_links:
            continue

        target_doc = _get_document_record(db, target_path)
        metadata_score = _metadata_score(source_doc, target_doc)
        graph_score = _graph_score(
            source_doc=source_doc,
            target_doc=target_doc,
            source_title=source_title,
            target_title=target_title,
        )
        similarity = _composite_discovery_score(
            semantic_similarity=semantic_similarity,
            metadata_score=metadata_score,
            graph_score=graph_score,
        )
        if similarity < threshold:
            continue
        
        discoveries.append(Discovery(
            source_path=source_path,
            source_title=source_title,
            target_path=target_path,
            target_title=target_title,
            similarity=similarity,
            semantic_similarity=semantic_similarity,
            metadata_score=metadata_score,
            graph_score=graph_score,
        ))

    discoveries.sort(key=lambda item: item.similarity, reverse=True)
    return discoveries[:top_k]


def find_discoveries(
    db: VectorStore,
    threshold: float = 0.6,
    top_k: int = 5,
    max_total: int = 20
) -> list[Discovery]:
    """
    Find all unlinked similar document pairs in the corpus.
    
    Args:
        db: Synapse database connection
        threshold: Minimum similarity score
        top_k: Max similar docs to check per document
        max_total: Maximum total discoveries to return
        
    Returns:
        List of Discovery objects, sorted by similarity descending
    """
    # Get all documents
    docs = db.conn.execute(
        "SELECT path FROM documents"
    ).fetchall()
    
    all_discoveries = []
    seen_pairs: set[tuple[str, str]] = set()
    
    for (doc_path,) in docs:
        discoveries = discover_for_document(db, doc_path, top_k=top_k, threshold=threshold)
        
        for d in discoveries:
            # Deduplicate: only keep one direction of each pair
            pair = tuple(sorted([d.source_path, d.target_path]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            all_discoveries.append(d)
    
    # Sort by similarity descending
    all_discoveries.sort(key=lambda d: d.similarity, reverse=True)
    
    return all_discoveries[:max_total]


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


def _get_document_record(db: VectorStore, doc_path: str) -> dict[str, Any] | None:
    if hasattr(db, "get_document"):
        return db.get_document(doc_path)

    row = db.conn.execute(
        "SELECT path, title FROM documents WHERE path = ?",
        (doc_path,),
    ).fetchone()
    if not row:
        return None
    return {
        "path": row["path"],
        "title": row["title"],
        "tags": [],
        "wikilinks": [],
        "frontmatter": {},
    }


def _get_document_embedding(db: VectorStore, doc_path: str) -> Optional[np.ndarray]:
    """Get average embedding for a document."""
    # First get doc_id from path
    row = db.conn.execute(
        "SELECT id FROM documents WHERE path = ?",
        (doc_path,)
    ).fetchone()
    
    if not row:
        return None
    
    doc_id = row[0]
    
    # Join with vec_chunks to get embedding
    rows = db.conn.execute("""
        SELECT v.embedding 
        FROM vec_chunks v
        JOIN chunks c ON c.id = v.chunk_id
        WHERE c.doc_id = ? AND c.scope = 'chunk'
    """, (doc_id,)).fetchall()
    
    if not rows:
        return None
    
    embeddings = []
    for (emb_bytes,) in rows:
        if emb_bytes:
            emb = np.frombuffer(emb_bytes, dtype=np.float32)
            embeddings.append(emb)
    
    if not embeddings:
        return None
    
    # Average of chunk embeddings
    return np.mean(embeddings, axis=0)


def _find_similar_documents(
    db: VectorStore,
    query_embedding: np.ndarray,
    top_k: int = 10,
    exclude_path: Optional[str] = None
) -> list[dict[str, Any]]:
    """
    Find documents similar to the query embedding.
    
    Returns:
        List of candidate dicts with semantic similarity
    """
    # Get all document embeddings (first chunk only for efficiency)
    # Join with vec_chunks to get embedding
    rows = db.conn.execute("""
        SELECT d.path, d.title, v.embedding
        FROM documents d
        JOIN chunks c ON d.id = c.doc_id
        JOIN vec_chunks v ON c.id = v.chunk_id
        WHERE c.chunk_index = 0 AND c.scope = 'chunk'
    """).fetchall()
    
    results = []
    query_norm = np.linalg.norm(query_embedding)
    
    for path, title, emb_bytes in rows:
        if path == exclude_path:
            continue
        
        if not emb_bytes:
            continue
        
        emb = np.frombuffer(emb_bytes, dtype=np.float32)
        emb_norm = np.linalg.norm(emb)
        
        if query_norm == 0 or emb_norm == 0:
            continue
        
        similarity = np.dot(query_embedding, emb) / (query_norm * emb_norm)
        results.append(
            {
                "path": path,
                "title": title,
                "semantic_similarity": float(similarity),
            }
        )
    
    # Sort by similarity descending
    results.sort(key=lambda x: x["semantic_similarity"], reverse=True)
    
    return results[:top_k]


def _metadata_score(source_doc: dict[str, Any], target_doc: dict[str, Any] | None) -> float:
    if not target_doc:
        return 0.0

    source_tags = {_normalize_term(tag) for tag in source_doc.get("tags", [])}
    target_tags = {_normalize_term(tag) for tag in target_doc.get("tags", [])}
    tag_score = 0.0
    if source_tags and target_tags:
        tag_score = 0.08 * _jaccard(source_tags, target_tags)

    source_values = _frontmatter_terms(source_doc.get("frontmatter", {}))
    target_values = _frontmatter_terms(target_doc.get("frontmatter", {}))
    frontmatter_score = 0.0
    if source_values and target_values:
        frontmatter_score = 0.05 * _jaccard(source_values, target_values)

    title_overlap = 0.03 * _jaccard(
        _tokenize(source_doc.get("title") or source_doc.get("path", "")),
        _tokenize(target_doc.get("title") or target_doc.get("path", "")),
    )
    return min(0.18, tag_score + frontmatter_score + title_overlap)


def _graph_score(
    source_doc: dict[str, Any],
    target_doc: dict[str, Any] | None,
    source_title: str,
    target_title: str,
) -> float:
    if not target_doc:
        return 0.0

    source_links = {_normalize_link(link) for link in source_doc.get("wikilinks", [])}
    target_links = {_normalize_link(link) for link in target_doc.get("wikilinks", [])}

    shared_neighbors = 0.0
    if source_links and target_links:
        shared_neighbors = 0.1 * _jaccard(source_links, target_links)

    title_bridge = 0.0
    source_title_norm = _normalize_link(source_title)
    target_title_norm = _normalize_link(target_title)
    if source_title_norm in target_links or target_title_norm in source_links:
        title_bridge = 0.06

    return min(0.16, shared_neighbors + title_bridge)


def _composite_discovery_score(
    *,
    semantic_similarity: float,
    metadata_score: float,
    graph_score: float,
) -> float:
    return min(1.0, (0.75 * semantic_similarity) + metadata_score + graph_score)


def _frontmatter_terms(frontmatter: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    if not isinstance(frontmatter, dict):
        return terms
    for key, value in frontmatter.items():
        terms.add(_normalize_term(key))
        if isinstance(value, list):
            for item in value:
                terms.add(_normalize_term(str(item)))
        else:
            terms.add(_normalize_term(str(value)))
    return {term for term in terms if term}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _tokenize(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9]+", (value or "").lower())
        if len(token) >= 3
    }


def _normalize_term(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _normalize_link(value: str) -> str:
    base = value.split("#")[0].split("|")[0]
    return _normalize_term(base)


def main():
    """CLI entry point for discovery."""
    import argparse
    from .settings import load_settings
    
    parser = argparse.ArgumentParser(
        description="🔗 Synapse Discovery — Find unlinked similar documents"
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
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.65,
        help="Minimum similarity threshold (default: 0.65)"
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Max similar docs to check per document (default: 5)"
    )
    parser.add_argument(
        "--max",
        type=int,
        default=10,
        help="Maximum discoveries to show (default: 10)"
    )
    
    args = parser.parse_args()
    settings = load_settings(args.config)
    provider = settings.embedding_provider()
    
    db_path = Path(args.db or settings.database.path).expanduser()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print("   Run synapse-index first to build the index.")
        return 1
    
    print(f"🔗 Synapse Discovery")
    print(f"   Database: {db_path}")
    print(f"   Threshold: {args.threshold:.0%}")
    print()
    
    db = create_vector_store(settings, db_path=db_path, embedding_dim=provider.dimensions)
    db.initialize()  # Connect to existing database
    discoveries = find_discoveries(
        db,
        threshold=args.threshold,
        top_k=args.top_k,
        max_total=args.max
    )
    
    if not discoveries:
        print("✨ No new discoveries! Your notes are well-connected.")
        return 0
    
    print(f"💡 Found {len(discoveries)} potential connections:\n")
    
    for i, d in enumerate(discoveries, 1):
        print(f"{i}. [{d.similarity:.1%}] {d.source_title} ↔ {d.target_title}")
        print(f"   {d.source_path}")
        print(f"   {d.target_path}")
        print()
    
    return 0


if __name__ == "__main__":
    exit(main())
