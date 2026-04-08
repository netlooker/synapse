"""
synapse.search - Query interface for source-first research search.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .embeddings import EmbeddingClient, EmbeddingService
from .settings import SearchSettings, load_settings
from .vector_store import VectorStore, create_vector_store


class Searcher:
    """Hybrid lexical/vector search over the source-first Synapse corpus."""

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
        default_embedder = embedding_client or note_embedding_client or chunk_embedding_client or EmbeddingClient(
            base_url=embedding_host or "http://127.0.0.1:11434",
            model=embedding_model or "nomic-embed-text:v1.5",
        )
        self.embedder = default_embedder
        self.search_settings = search_settings or SearchSettings()

    def search(
        self,
        query: str,
        limit: int = 5,
        mode: str = "research",
        filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if mode not in {"source", "note", "evidence", "research"}:
            raise ValueError(f"Unsupported search mode: {mode}")

        search_filters = dict(filters or {})
        if mode == "source":
            search_filters["owner_kind"] = "source"
        elif mode == "note":
            search_filters["owner_kind"] = "note"

        candidate_limit = _candidate_limit(limit, self.search_settings.candidate_multiplier)
        lexical_hits = self.db.search_segments_lexical(
            query,
            limit=candidate_limit,
            filters=search_filters,
        )
        vector_hits = self.db.search_segments_vector(
            self.embedder.embed_query(query),
            limit=candidate_limit,
            filters=search_filters,
        )

        merged = _merge_segment_candidates(
            lexical_hits,
            vector_hits,
            lexical_weight=self.search_settings.note_weight,
            vector_weight=self.search_settings.chunk_weight,
        )

        if mode == "evidence":
            ranked = sorted(merged.values(), key=lambda item: item["combined_score"], reverse=True)
            return [_evidence_result(item) for item in ranked[:limit]]
        if mode == "note":
            return _aggregate_results(merged.values(), limit=limit, mode="note")
        if mode == "source":
            return _aggregate_results(merged.values(), limit=limit, mode="source")
        return _aggregate_results(merged.values(), limit=limit, mode="research")


def _candidate_limit(limit: int, multiplier: int) -> int:
    return max(limit, limit * max(1, multiplier))


def _merge_segment_candidates(
    lexical_hits: list[dict[str, Any]],
    vector_hits: list[dict[str, Any]],
    *,
    lexical_weight: float,
    vector_weight: float,
) -> dict[int, dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    lexical_weight, vector_weight = _normalize_weights(lexical_weight, vector_weight)
    rrf_k = 60.0

    for rank, row in enumerate(lexical_hits, start=1):
        item = merged.setdefault(row["segment_id"], dict(row))
        item["bm25_score"] = row.get("bm25_score")
        item["lexical_rank"] = rank
        item["lexical_contribution"] = lexical_weight / (rrf_k + rank)

    for rank, row in enumerate(vector_hits, start=1):
        item = merged.setdefault(row["segment_id"], dict(row))
        item["vector_score"] = row.get("vector_score")
        item["distance"] = row.get("distance")
        item["vector_rank"] = rank
        item["vector_contribution"] = vector_weight / (rrf_k + rank)

    for item in merged.values():
        role_bonus = _role_bonus(item.get("content_role"))
        cross_bonus = 0.02 if item.get("lexical_rank") and item.get("vector_rank") else 0.0
        item["combined_score"] = (
            item.get("lexical_contribution", 0.0)
            + item.get("vector_contribution", 0.0)
            + role_bonus
            + cross_bonus
        )
        item["title"] = item.get("title") or item.get("source_title") or item.get("note_title")
        item["rank_reason"] = _rank_reason(item, role_bonus, cross_bonus)
    return merged


def _aggregate_results(
    items: list[dict[str, Any]],
    *,
    limit: int,
    mode: str,
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], dict[str, Any]] = {}

    for item in items:
        key, result_kind = _group_key(item, mode)
        if key is None:
            continue
        group = groups.get((result_kind, key))
        if group is None:
            groups[(result_kind, key)] = {
                "result_kind": result_kind,
                "group_key": key,
                "best_item": item,
                "score": item["combined_score"],
                "match_count": 1,
            }
            continue
        group["match_count"] += 1
        if item["combined_score"] > group["best_item"]["combined_score"]:
            group["best_item"] = item
        group["score"] = max(group["score"], item["combined_score"])

    results: list[dict[str, Any]] = []
    for group in groups.values():
        best_item = group["best_item"]
        support_bonus = min(0.03, 0.01 * max(group["match_count"] - 1, 0))
        combined_score = group["score"] + support_bonus
        results.append({
            "result_kind": group["result_kind"],
            "title": best_item.get("title"),
            "bundle_id": best_item.get("bundle_id"),
            "source_id": best_item.get("source_id"),
            "note_path": best_item.get("note_path"),
            "origin_url": best_item.get("origin_url"),
            "direct_paper_url": best_item.get("direct_paper_url"),
            "matched_content_role": best_item.get("content_role"),
            "matched_segment_text": _truncate(best_item.get("segment_text", ""), 260),
            "bm25_score": best_item.get("bm25_score"),
            "vector_score": best_item.get("vector_score"),
            "combined_score": combined_score,
            "rank_reason": _aggregate_rank_reason(best_item, group["match_count"], support_bonus),
        })

    results.sort(key=lambda item: item["combined_score"], reverse=True)
    return results[:limit]


def _group_key(item: dict[str, Any], mode: str) -> tuple[str | None, str]:
    if mode == "source":
        source_id = item.get("source_id")
        return (source_id, "source") if source_id else (None, "source")
    if mode == "note":
        note_path = item.get("note_path") or (str(item.get("note_row_id")) if item.get("note_row_id") else None)
        return (note_path, "note") if note_path else (None, "note")
    if item.get("source_id"):
        return item["source_id"], "source"
    note_path = item.get("note_path") or (str(item.get("note_row_id")) if item.get("note_row_id") else None)
    if note_path:
        return note_path, "note"
    return None, "evidence"


def _evidence_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "result_kind": "evidence",
        "title": item.get("title"),
        "bundle_id": item.get("bundle_id"),
        "source_id": item.get("source_id"),
        "note_path": item.get("note_path"),
        "origin_url": item.get("origin_url"),
        "direct_paper_url": item.get("direct_paper_url"),
        "matched_content_role": item.get("content_role"),
        "matched_segment_text": _truncate(item.get("segment_text", ""), 260),
        "bm25_score": item.get("bm25_score"),
        "vector_score": item.get("vector_score"),
        "combined_score": item.get("combined_score", 0.0),
        "rank_reason": item.get("rank_reason", ""),
    }


def _normalize_weights(lexical_weight: float, vector_weight: float) -> tuple[float, float]:
    total = max(lexical_weight + vector_weight, 0.0001)
    return lexical_weight / total, vector_weight / total


def _role_bonus(content_role: str | None) -> float:
    bonuses = {
        "summary": 0.08,
        "abstract": 0.05,
        "full_text": 0.02,
        "note_body": 0.01,
    }
    return bonuses.get(content_role or "", 0.0)


def _truncate(text: str, max_len: int) -> str:
    text = text.strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _rank_reason(item: dict[str, Any], role_bonus: float, cross_bonus: float) -> str:
    parts = []
    if item.get("lexical_rank"):
        parts.append(f"lexical rank {item['lexical_rank']}")
    if item.get("vector_rank"):
        parts.append(f"vector rank {item['vector_rank']}")
    if item.get("content_role"):
        parts.append(f"matched {item['content_role']}")
    if role_bonus > 0:
        parts.append(f"role bonus {role_bonus:.2f}")
    if cross_bonus > 0:
        parts.append("hybrid agreement")
    return ", ".join(parts)


def _aggregate_rank_reason(best_item: dict[str, Any], match_count: int, support_bonus: float) -> str:
    parts = [best_item.get("rank_reason", "")]
    if match_count > 1:
        parts.append(f"{match_count} supporting segments")
    if support_bonus > 0:
        parts.append(f"support bonus {support_bonus:.2f}")
    return ", ".join(part for part in parts if part)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Hybrid source-first search over Synapse research corpora")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--config", default=None, help="Path to Synapse TOML config")
    parser.add_argument("--db", default=None, help="Path to SQLite database")
    parser.add_argument("--provider", default=None, help="Embedding provider name from the Synapse config")
    parser.add_argument(
        "--mode",
        default="research",
        choices=("source", "note", "evidence", "research"),
        help="Search surface to query",
    )
    parser.add_argument("--limit", type=int, default=None, help="Maximum results to return")
    parser.add_argument("--bundle-id", default=None, help="Optional bundle_id filter")
    parser.add_argument("--source-id", default=None, help="Optional source_id filter")
    parser.add_argument("--source-type", default=None, help="Optional source_type filter")

    args = parser.parse_args()
    settings = load_settings(args.config)
    provider = settings.embedding_provider(args.provider or settings.search.provider)
    db_path = Path(args.db or settings.database.path).expanduser()

    store = create_vector_store(settings, db_path=db_path, embedding_dim=provider.dimensions)
    store.initialize()
    try:
        searcher = Searcher(
            db=store,
            embedding_client=EmbeddingClient.from_provider(provider),
            search_settings=settings.search,
        )
        results = searcher.search(
            query=args.query,
            limit=args.limit or settings.search.limit,
            mode=args.mode,
            filters={
                key: value
                for key, value in {
                    "bundle_id": args.bundle_id,
                    "source_id": args.source_id,
                    "source_type": args.source_type,
                }.items()
                if value is not None
            },
        )
    finally:
        store.close()

    for result in results:
        locator = result["direct_paper_url"] or result["origin_url"] or result["note_path"] or result["source_id"]
        print(f"[{result['result_kind']}] {result['title'] or '(untitled)'}")
        print(f"  Score: {result['combined_score']:.4f}")
        print(f"  Match: {result['matched_content_role']} | {result['matched_segment_text']}")
        if locator:
            print(f"  Locator: {locator}")
        print(f"  Why: {result['rank_reason']}")
        print()


if __name__ == "__main__":
    main()
