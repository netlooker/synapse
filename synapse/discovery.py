"""Discovery module — find unlinked similar notes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np

from .vector_store import VectorStore, create_vector_store


WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


def extract_wikilinks(content: str) -> set[str]:
    matches = WIKILINK_PATTERN.findall(content)
    links = set()
    for match in matches:
        base = match.split("#")[0].strip()
        if base:
            links.add(base)
    return links


@dataclass
class Discovery:
    source_path: str
    source_title: str
    target_path: str
    target_title: str
    similarity: float
    semantic_similarity: float = 0.0
    metadata_score: float = 0.0
    graph_score: float = 0.0

    def __repr__(self) -> str:
        return f"Discovery({self.source_title!r} → {self.target_title!r}, sim={self.similarity:.1%})"


def discover_for_document(
    db: VectorStore,
    doc_path: str,
    top_k: int = 5,
    threshold: float = 0.6,
) -> list[Discovery]:
    source_doc = _get_note_record(db, doc_path)
    if not source_doc:
        return []

    source_path = source_doc["path"]
    source_title = source_doc["title"] or Path(source_path).stem
    existing_links = extract_wikilinks(source_doc.get("body_text", ""))
    source_embedding = _get_note_embedding(db, doc_path)
    if source_embedding is None:
        return []

    similar_docs = _find_similar_notes(
        db,
        source_embedding,
        top_k=top_k + 10,
        exclude_path=doc_path,
    )

    discoveries = []
    for candidate in similar_docs:
        target_path = candidate["path"]
        target_title = candidate["title"] or Path(target_path).stem
        semantic_similarity = candidate["semantic_similarity"]

        if target_title in existing_links:
            continue

        target_doc = _get_note_record(db, target_path)
        if not target_doc:
            continue

        target_links = extract_wikilinks(target_doc.get("body_text", ""))
        if source_title in target_links:
            continue

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

        discoveries.append(
            Discovery(
                source_path=source_path,
                source_title=source_title,
                target_path=target_path,
                target_title=target_title,
                similarity=similarity,
                semantic_similarity=semantic_similarity,
                metadata_score=metadata_score,
                graph_score=graph_score,
            )
        )

    discoveries.sort(key=lambda item: item.similarity, reverse=True)
    return discoveries[:top_k]


def find_discoveries(
    db: VectorStore,
    threshold: float = 0.6,
    top_k: int = 5,
    max_total: int = 20,
) -> list[Discovery]:
    rows = db.conn.execute("SELECT note_path FROM notes").fetchall()
    all_discoveries = []
    seen_pairs: set[tuple[str, str]] = set()

    for (doc_path,) in rows:
        discoveries = discover_for_document(db, doc_path, top_k=top_k, threshold=threshold)
        for discovery in discoveries:
            pair = tuple(sorted([discovery.source_path, discovery.target_path]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            all_discoveries.append(discovery)

    all_discoveries.sort(key=lambda item: item.similarity, reverse=True)
    return all_discoveries[:max_total]


def _get_note_record(db: VectorStore, note_path: str) -> dict[str, Any] | None:
    if hasattr(db, "get_note"):
        note = db.get_note(note_path)
        if note:
            metadata = note.get("metadata", {}) or {}
            return {
                "id": note["id"],
                "path": note["note_path"],
                "title": note.get("title"),
                "body_text": note.get("body_text", ""),
                "tags": metadata.get("tags", []),
                "wikilinks": metadata.get("wikilinks", []),
                "frontmatter": metadata.get("frontmatter", {}),
            }

    row = db.conn.execute(
        "SELECT id, note_path, title, body_text, metadata_json FROM notes WHERE note_path = ?",
        (note_path,),
    ).fetchone()
    if not row:
        return None
    metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}
    return {
        "id": row["id"],
        "path": row["note_path"],
        "title": row["title"],
        "body_text": row["body_text"],
        "tags": metadata.get("tags", []),
        "wikilinks": metadata.get("wikilinks", []),
        "frontmatter": metadata.get("frontmatter", {}),
    }


def _get_note_embedding(db: VectorStore, note_path: str) -> Optional[np.ndarray]:
    row = db.conn.execute(
        "SELECT id FROM notes WHERE note_path = ?",
        (note_path,),
    ).fetchone()
    if not row:
        return None
    note_id = row[0]
    rows = db.conn.execute("""
        SELECT v.embedding
        FROM vec_segments v
        JOIN segments s ON s.id = v.segment_id
        WHERE s.owner_kind = 'note' AND s.owner_note_id = ?
    """, (note_id,)).fetchall()
    embeddings = []
    for (emb_bytes,) in rows:
        if emb_bytes:
            embeddings.append(np.frombuffer(emb_bytes, dtype=np.float32))
    if not embeddings:
        return None
    return np.mean(embeddings, axis=0)


def _find_similar_notes(
    db: VectorStore,
    query_embedding: np.ndarray,
    *,
    top_k: int = 10,
    exclude_path: str | None = None,
) -> list[dict[str, Any]]:
    rows = db.conn.execute("SELECT note_path, title FROM notes").fetchall()
    results = []
    query_norm = np.linalg.norm(query_embedding)

    for note_path, title in rows:
        if note_path == exclude_path:
            continue
        embedding = _get_note_embedding(db, note_path)
        if embedding is None:
            continue
        emb_norm = np.linalg.norm(embedding)
        if query_norm == 0 or emb_norm == 0:
            continue
        similarity = float(np.dot(query_embedding, embedding) / (query_norm * emb_norm))
        results.append(
            {
                "path": note_path,
                "title": title,
                "semantic_similarity": similarity,
            }
        )

    results.sort(key=lambda item: item["semantic_similarity"], reverse=True)
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
    import argparse
    from .settings import load_settings

    parser = argparse.ArgumentParser(description="🔗 Synapse Discovery — Find unlinked similar notes")
    parser.add_argument("--config", default=None, help="Path to Synapse TOML config")
    parser.add_argument("--db", default=None, help="Path to synapse database")
    parser.add_argument("--threshold", type=float, default=0.65, help="Minimum similarity threshold (default: 0.65)")
    parser.add_argument("--top-k", type=int, default=5, help="Max similar notes to check per note (default: 5)")
    parser.add_argument("--max", type=int, default=10, help="Maximum discoveries to show (default: 10)")

    args = parser.parse_args()
    settings = load_settings(args.config)
    provider = settings.embedding_provider()
    db_path = Path(args.db or settings.database.path).expanduser()
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print("   Run synapse-index first to build the index.")
        return 1

    print("🔗 Synapse Discovery")
    print(f"   Database: {db_path}")
    print(f"   Threshold: {args.threshold:.0%}")
    print()

    db = create_vector_store(settings, db_path=db_path, embedding_dim=provider.dimensions)
    db.initialize()
    discoveries = find_discoveries(db, threshold=args.threshold, top_k=args.top_k, max_total=args.max)

    if not discoveries:
        print("✨ No new discoveries! Your notes are well-connected.")
        return 0

    print(f"💡 Found {len(discoveries)} potential connections:\n")
    for index, discovery in enumerate(discoveries, 1):
        print(f"{index}. [{discovery.similarity:.1%}] {discovery.source_title} ↔ {discovery.target_title}")
        print(f"   {discovery.source_path}")
        print(f"   {discovery.target_path}")
        print()
    return 0


if __name__ == "__main__":
    exit(main())
