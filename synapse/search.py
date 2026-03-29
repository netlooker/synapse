"""
synapse.search - Query interface for semantic search
"""
import re
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingClient, EmbeddingService
from .settings import SearchSettings, load_settings
from .vector_store import VectorStore, create_vector_store


class Searcher:
    """Semantic search over the indexed markdown corpus."""

    def __init__(
        self,
        db: VectorStore,
        embedding_client: EmbeddingService | None = None,
        note_embedding_client: EmbeddingService | None = None,
        chunk_embedding_client: EmbeddingService | None = None,
        embedding_host: str | None = None,
        embedding_model: str | None = None,
        search_settings: SearchSettings | None = None,
    ):
        self.db = db
        default_embedder = embedding_client or EmbeddingClient(
            base_url=embedding_host or "http://127.0.0.1:11434",
            model=embedding_model or "nomic-embed-text:v1.5",
        )
        self.note_embedder = note_embedding_client or default_embedder
        self.chunk_embedder = chunk_embedding_client or default_embedder
        self.search_settings = search_settings or SearchSettings()

    def search(
        self, 
        query: str, 
        limit: int = 5,
        mode: str = "hybrid",
    ) -> list[dict[str, Any]]:
        """Search for documents similar to the query.
        
        Returns list of results with path, title, similarity, and snippet.
        """
        if mode not in {"note", "chunk", "hybrid"}:
            raise ValueError(f"Unsupported search mode: {mode}")

        note_query_embedding = None
        chunk_query_embedding = None

        if mode == "note":
            note_query_embedding = self.note_embedder.embed_query(query)
            note_results = self.db.search_similar(
                note_query_embedding,
                limit=limit * 2,
                scope="note",
            )
            return _dedupe_results(note_results, limit, query)

        if mode == "chunk":
            chunk_query_embedding = self.chunk_embedder.embed_query(query)
            chunk_results = self.db.search_similar(
                chunk_query_embedding,
                limit=limit * 2,
                scope="chunk",
            )
            return _dedupe_results(chunk_results, limit, query)

        note_query_embedding = self.note_embedder.embed_query(query)
        chunk_query_embedding = self.chunk_embedder.embed_query(query)
        note_results = self.db.search_similar(
            note_query_embedding,
            limit=_candidate_limit(limit, self.search_settings.candidate_multiplier),
            scope="note",
        )
        candidate_paths = [row["path"] for row in note_results]
        chunk_limit = _candidate_limit(limit, self.search_settings.candidate_multiplier)
        chunk_results = self.db.search_similar(
            chunk_query_embedding,
            limit=chunk_limit,
            scope="chunk",
            include_paths=candidate_paths or None,
        )
        if len(chunk_results) < limit:
            fallback_chunk_results = self.db.search_similar(
                chunk_query_embedding,
                limit=chunk_limit,
                scope="chunk",
            )
            chunk_results = _merge_chunk_candidates(chunk_results, fallback_chunk_results)

        return _merge_hybrid_results(
            note_results,
            chunk_results,
            limit,
            note_weight=self.search_settings.note_weight,
            chunk_weight=self.search_settings.chunk_weight,
            candidate_paths=set(candidate_paths),
            query=query,
        )


def _candidate_limit(limit: int, multiplier: int) -> int:
    return max(limit, limit * max(1, multiplier))


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max length, adding ellipsis if needed."""
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."


def _dedupe_results(results: list[dict[str, Any]], limit: int, query: str) -> list[dict[str, Any]]:
    seen_paths = set()
    unique_results = []
    query_terms = _query_terms(query)

    for r in results:
        if r["path"] in seen_paths:
            continue
        seen_paths.add(r["path"])
        metadata_boost = _metadata_boost(r, query_terms)
        unique_results.append({
            "path": r["path"],
            "title": r["title"],
            "similarity": min(1.0, r["similarity"] + metadata_boost),
            "snippet": _truncate(r["chunk_text"], 200),
            "metadata_boost": metadata_boost,
        })

    unique_results.sort(key=lambda row: row["similarity"], reverse=True)
    return unique_results[:limit]


def _merge_hybrid_results(
    note_results: list[dict[str, Any]],
    chunk_results: list[dict[str, Any]],
    limit: int,
    *,
    note_weight: float = 0.4,
    chunk_weight: float = 0.6,
    candidate_paths: set[str] | None = None,
    query: str = "",
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    normalized_note_weight, normalized_chunk_weight = _normalize_weights(note_weight, chunk_weight)
    candidate_paths = candidate_paths or set()
    query_terms = _query_terms(query)

    for result in note_results:
        merged[result["path"]] = {
            "path": result["path"],
            "title": result["title"],
            "note_similarity": result["similarity"],
            "chunk_similarity": 0.0,
            "snippet": _truncate(result["chunk_text"], 200),
            "source": "note",
            "candidate_boost": 0.0,
            "metadata": result,
        }

    for result in chunk_results:
        row = merged.get(result["path"])
        snippet = _truncate(result["chunk_text"], 200)
        if row is None:
            row = {
                "path": result["path"],
                "title": result["title"],
                "note_similarity": 0.0,
                "chunk_similarity": 0.0,
                "snippet": snippet,
                "source": "chunk",
                "candidate_boost": 0.0,
                "metadata": result,
            }
            merged[result["path"]] = row
        row["chunk_similarity"] = max(row["chunk_similarity"], result["similarity"])
        if row["source"] != "chunk" or row["chunk_similarity"] == result["similarity"]:
            row["snippet"] = snippet
            row["source"] = "chunk"
            row["metadata"] = result
        if result["path"] in candidate_paths:
            row["candidate_boost"] = max(row["candidate_boost"], 0.05)
        row["metadata_boost"] = max(
            row.get("metadata_boost", 0.0),
            _metadata_boost(result, query_terms),
        )

    ranked = sorted(
        (
            _finalize_hybrid_row(row, normalized_note_weight, normalized_chunk_weight)
            for row in merged.values()
        ),
        key=lambda row: row["similarity"],
        reverse=True,
    )
    return ranked[:limit]


def _merge_chunk_candidates(
    primary_results: list[dict[str, Any]],
    fallback_results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {row["path"]: row for row in primary_results}
    for row in fallback_results:
        existing = merged.get(row["path"])
        if existing is None or row["similarity"] > existing["similarity"]:
            merged[row["path"]] = row
    return list(merged.values())


def _normalize_weights(note_weight: float, chunk_weight: float) -> tuple[float, float]:
    total = max(note_weight + chunk_weight, 0.0001)
    return note_weight / total, chunk_weight / total


def _finalize_hybrid_row(
    row: dict[str, Any],
    note_weight: float,
    chunk_weight: float,
) -> dict[str, Any]:
    note_similarity = row["note_similarity"]
    chunk_similarity = row["chunk_similarity"]
    agreement_bonus = 0.1 * min(note_similarity, chunk_similarity)
    similarity = min(
        1.0,
        (note_weight * note_similarity)
        + (chunk_weight * chunk_similarity)
        + row.get("candidate_boost", 0.0)
        + row.get("metadata_boost", 0.0)
        + agreement_bonus,
    )
    return {
        "path": row["path"],
        "title": row["title"],
        "similarity": similarity,
        "snippet": row["snippet"],
        "note_similarity": note_similarity,
        "chunk_similarity": chunk_similarity,
        "metadata_boost": row.get("metadata_boost", 0.0),
    }


def _query_terms(query: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9]+", query.lower())
        if len(token) >= 3
    }


def _metadata_boost(row: dict[str, Any], query_terms: set[str]) -> float:
    if not query_terms:
        return 0.0
    metadata_terms = _collect_metadata_terms(row)
    overlap = len(query_terms & metadata_terms)
    return min(0.12, overlap * 0.04)


def _collect_metadata_terms(row: dict[str, Any]) -> set[str]:
    terms: set[str] = set()
    for value in [row.get("title"), row.get("path"), row.get("chunk_text")]:
        terms.update(_tokenize(value))
    for tag in row.get("tags", []) or []:
        terms.update(_tokenize(str(tag)))
    for link in row.get("wikilinks", []) or []:
        terms.update(_tokenize(str(link)))
    frontmatter = row.get("frontmatter", {}) or {}
    if isinstance(frontmatter, dict):
        for key, value in frontmatter.items():
            terms.update(_tokenize(key))
            if isinstance(value, list):
                for item in value:
                    terms.update(_tokenize(str(item)))
            else:
                terms.update(_tokenize(str(value)))
    return terms


def _tokenize(value: str | None) -> set[str]:
    if not value:
        return set()
    return {
        token
        for token in re.split(r"[^a-zA-Z0-9]+", value.lower())
        if len(token) >= 3
    }


def main():
    """CLI entry point for synapse-search."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Semantic search over markdown notes")
    parser.add_argument("query", help="Search query")
    parser.add_argument(
        "--config",
        default=None,
        help="Path to Synapse TOML config"
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Path to SQLite database"
    )
    parser.add_argument(
        "--provider",
        default=None,
        help="Note embedding provider name from the Synapse config"
    )
    parser.add_argument(
        "--chunk-provider",
        default=None,
        help="Chunk embedding provider name from the Synapse config"
    )
    parser.add_argument(
        "--base-url",
        "--ollama-host",
        dest="base_url",
        default=None,
        help="Override embedding endpoint base URL"
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Embedding model to use"
    )
    parser.add_argument(
        "-n", "--limit",
        type=int,
        default=None,
        help="Number of results to return"
    )
    parser.add_argument(
        "--mode",
        choices=["note", "chunk", "hybrid"],
        default=None,
        help="Search scope to use"
    )
    
    args = parser.parse_args()
    settings = load_settings(args.config)
    note_provider = settings.embedding_provider(args.provider or settings.search.provider)
    chunk_provider = settings.embedding_provider(args.chunk_provider or settings.index.contextual_provider)
    if note_provider.dimensions != chunk_provider.dimensions:
        raise ValueError(
            f"Note provider dimension {note_provider.dimensions} must match chunk provider dimension {chunk_provider.dimensions}"
        )
    db_path = Path(args.db or settings.database.path).expanduser()
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        print("   Run synapse-index first.")
        return
    
    # Initialize
    db = create_vector_store(settings, db_path=db_path, embedding_dim=note_provider.dimensions)
    db.initialize()
    
    searcher = Searcher(
        db=db, 
        note_embedding_client=EmbeddingClient(
            provider_type=note_provider.type,
            base_url=args.base_url or note_provider.base_url,
            model=args.model or note_provider.model,
            dimensions=note_provider.dimensions,
            api_key=note_provider.api_key(),
            encoding_format=note_provider.encoding_format,
            context_strategy=note_provider.context_strategy,
        ),
        chunk_embedding_client=EmbeddingClient(
            provider_type=chunk_provider.type,
            base_url=chunk_provider.base_url,
            model=chunk_provider.model,
            dimensions=chunk_provider.dimensions,
            api_key=chunk_provider.api_key(),
            encoding_format=chunk_provider.encoding_format,
            context_strategy=chunk_provider.context_strategy,
        ),
        search_settings=settings.search,
    )
    
    # Search
    print(f"🔍 Searching for: {args.query}")
    print()
    
    results = searcher.search(
        args.query,
        limit=args.limit or settings.search.limit,
        mode=args.mode or settings.search.mode,
    )
    
    if not results:
        print("No results found.")
        return
    
    for i, r in enumerate(results, 1):
        sim_pct = r["similarity"] * 100
        print(f"{i}. [{sim_pct:.1f}%] {r['title'] or r['path']}")
        print(f"   📄 {r['path']}")
        print(f"   {r['snippet']}")
        print()
    
    db.close()


if __name__ == "__main__":
    main()
