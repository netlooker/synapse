"""Benchmark Synapse retrieval profiles against a fixture vault."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import tempfile
import time
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from synapse.embeddings import EmbeddingClient
from synapse.index import Indexer
from synapse.search import Searcher
from synapse.settings import SearchSettings, load_settings
from synapse.vector_store import create_vector_store


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures"
FIXTURE_VAULT = FIXTURE_ROOT / "vault"
FIXTURE_QUERIES = FIXTURE_ROOT / "retrieval_queries.json"


INDEX_PROFILES = [
    {"name": "infinity_batch", "context_strategy": "infinity_batch"},
    {"name": "enriched_fallback", "context_strategy": "enriched_fallback"},
]

SEARCH_PROFILES = [
    {"name": "note_only", "mode": "note", "candidate_multiplier": 4, "note_weight": 1.0, "chunk_weight": 0.0},
    {"name": "chunk_only", "mode": "chunk", "candidate_multiplier": 4, "note_weight": 0.0, "chunk_weight": 1.0},
    {"name": "hybrid_default", "mode": "hybrid", "candidate_multiplier": 4, "note_weight": 0.4, "chunk_weight": 0.6},
    {"name": "hybrid_balanced", "mode": "hybrid", "candidate_multiplier": 4, "note_weight": 0.5, "chunk_weight": 0.5},
    {"name": "hybrid_chunk_heavy", "mode": "hybrid", "candidate_multiplier": 6, "note_weight": 0.25, "chunk_weight": 0.75},
]


def load_queries(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def reciprocal_rank(result_paths: list[str], relevant: set[str]) -> float:
    for rank, path in enumerate(result_paths, start=1):
        if Path(path).name in relevant:
            return 1.0 / rank
    return 0.0


def recall_at_k(result_paths: list[str], relevant: set[str], k: int) -> float:
    hits = sum(1 for path in result_paths[:k] if Path(path).name in relevant)
    return hits / max(1, len(relevant))


def ndcg_at_k(result_paths: list[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for idx, path in enumerate(result_paths[:k], start=1):
        if Path(path).name in relevant:
            dcg += 1.0 / _log2(idx + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / _log2(idx + 1) for idx in range(1, ideal_hits + 1))
    if idcg == 0:
        return 0.0
    return dcg / idcg


def _log2(value: int) -> float:
    import math

    return math.log(value, 2)


def build_index(config_path: Path, db_path: Path, context_strategy: str) -> tuple[float, object]:
    settings = load_settings(config_path)
    note_provider = settings.embedding_provider("default")
    chunk_provider = replace(settings.contextual_embedding_provider(), context_strategy=context_strategy)
    db = create_vector_store(settings, db_path=db_path, embedding_dim=note_provider.dimensions)
    db.initialize()
    indexer = Indexer(
        db=db,
        cortex_path=FIXTURE_VAULT,
        note_embedding_client=EmbeddingClient.from_provider(note_provider),
        chunk_embedding_client=EmbeddingClient.from_provider(chunk_provider),
        min_chunk_chars=settings.index.min_chunk_chars,
        max_chunk_chars=settings.index.max_chunk_chars,
    )
    started = time.perf_counter()
    stats = indexer.index_all()
    elapsed = time.perf_counter() - started
    return elapsed, (db, settings, stats, note_provider, chunk_provider)


def benchmark_search_profiles(
    db,
    settings,
    note_provider,
    chunk_provider,
    queries: list[dict],
    limit: int,
) -> list[dict]:
    results: list[dict] = []
    for profile in SEARCH_PROFILES:
        search_settings = SearchSettings(
            provider=settings.search.provider,
            limit=limit,
            mode=profile["mode"],
            candidate_multiplier=profile["candidate_multiplier"],
            note_weight=profile["note_weight"],
            chunk_weight=profile["chunk_weight"],
        )
        searcher = Searcher(
            db=db,
            note_embedding_client=EmbeddingClient.from_provider(note_provider),
            chunk_embedding_client=EmbeddingClient.from_provider(chunk_provider),
            search_settings=search_settings,
        )

        latencies = []
        recalls = []
        mrrs = []
        ndcgs = []
        failures: list[dict] = []
        for item in queries:
            started = time.perf_counter()
            rows = searcher.search(item["query"], limit=limit, mode=profile["mode"])
            latencies.append(time.perf_counter() - started)
            paths = [row["path"] for row in rows]
            relevant = set(item["relevant"])
            recalls.append(recall_at_k(paths, relevant, limit))
            mrrs.append(reciprocal_rank(paths, relevant))
            ndcgs.append(ndcg_at_k(paths, relevant, limit))
            if not any(Path(path).name in relevant for path in paths[:limit]):
                failures.append({"id": item["id"], "results": paths[:limit], "relevant": sorted(relevant)})

        results.append(
            {
                "name": profile["name"],
                "mode": profile["mode"],
                "candidate_multiplier": profile["candidate_multiplier"],
                "note_weight": profile["note_weight"],
                "chunk_weight": profile["chunk_weight"],
                "avg_latency_ms": statistics.mean(latencies) * 1000.0,
                "recall_at_k": statistics.mean(recalls),
                "mrr": statistics.mean(mrrs),
                "ndcg_at_k": statistics.mean(ndcgs),
                "failures": failures,
            }
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark Synapse retrieval profiles")
    parser.add_argument("--config", default="config/synapse.toml", help="Runtime config path")
    parser.add_argument("--limit", type=int, default=3, help="Top-k cutoff")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a text table")
    args = parser.parse_args()

    config_path = Path(args.config)
    queries = load_queries(FIXTURE_QUERIES)
    benchmark_results = []

    for index_profile in INDEX_PROFILES:
        with tempfile.TemporaryDirectory(prefix="synapse-bench-") as tmpdir:
            db_path = Path(tmpdir) / f"{index_profile['name']}.sqlite"
            index_time, payload = build_index(
                config_path=config_path,
                db_path=db_path,
                context_strategy=index_profile["context_strategy"],
            )
            db, settings, stats, note_provider, chunk_provider = payload
            try:
                search_results = benchmark_search_profiles(
                    db=db,
                    settings=settings,
                    note_provider=note_provider,
                    chunk_provider=chunk_provider,
                    queries=queries,
                    limit=args.limit,
                )
            finally:
                db.close()

        benchmark_results.append(
            {
                "index_profile": index_profile["name"],
                "index_time_s": index_time,
                "files_indexed": stats["total_files"],
                "chunks_indexed": stats["total_chunks"],
                "search_profiles": search_results,
            }
        )

    if args.json:
        print(json.dumps(benchmark_results, indent=2))
        return

    for section in benchmark_results:
        print(f"## Index Profile: {section['index_profile']}")
        print(
            f"index_time={section['index_time_s']:.2f}s "
            f"files={section['files_indexed']} chunks={section['chunks_indexed']}"
        )
        for row in section["search_profiles"]:
            print(
                f"- {row['name']}: "
                f"recall@{args.limit}={row['recall_at_k']:.3f} "
                f"mrr={row['mrr']:.3f} "
                f"ndcg@{args.limit}={row['ndcg_at_k']:.3f} "
                f"avg_latency_ms={row['avg_latency_ms']:.1f}"
            )
            if row["failures"]:
                first = row["failures"][0]
                print(
                    f"  first_miss={first['id']} "
                    f"results={','.join(first['results'])} "
                    f"relevant={','.join(first['relevant'])}"
                )
        print()


if __name__ == "__main__":
    main()
