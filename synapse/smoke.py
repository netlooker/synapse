"""Agent-facing dry-run smoke test for Synapse."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .cipher_service import CipherDeps, CipherService, ExplainConnectionRequest
from .gardener import cultivate
from .service_api import (
    DiscoverRequest,
    HealthRequest,
    IndexRequest,
    SearchRequest,
    ValidateRequest,
    discover_index,
    index_vault,
    runtime_requirements,
    search_index,
    validate_index,
)
from .settings import load_settings


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = PROJECT_ROOT / "benchmarks" / "fixtures"
FIXTURE_VAULT = FIXTURE_ROOT / "vault"
FIXTURE_QUERIES = FIXTURE_ROOT / "retrieval_queries.json"
DEFAULT_CIPHER_DOC_A = "agency-memory.md"
DEFAULT_CIPHER_DOC_B = "weak-signals.md"


@dataclass
class SmokeResult:
    config_path: str | None
    vault_root: str
    db_path: str
    used_temporary_db: bool
    health_ready: bool
    indexed_files: int
    indexed_segments: int
    search_query: str
    top_search_paths: list[str]
    discovery_count: int
    broken_link_count: int
    garden_status: str
    cipher_status: str
    cipher_summary: str | None = None


def load_default_query() -> str:
    items = json.loads(FIXTURE_QUERIES.read_text(encoding="utf-8"))
    if not items:
        raise ValueError(f"No fixture queries found in {FIXTURE_QUERIES}")
    return str(items[0]["query"])


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def reasoning_env_configured() -> bool:
    required = ("OPENAI_BASE_URL", "OPENAI_API_KEY", "SYNAPSE_MODEL")
    return all(os.environ.get(name) for name in required)


def _prepare_db_path(
    db_path: Path | None,
    *,
    keep_db: bool,
    reuse_db: bool,
) -> tuple[Path, Path | None, bool]:
    if db_path is not None:
        resolved = db_path.expanduser()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        if resolved.exists() and not reuse_db:
            raise ValueError(
                f"Refusing to reuse existing database path without --reuse-db: {resolved}"
            )
        return resolved, None, False

    if keep_db:
        temp_root = Path(tempfile.mkdtemp(prefix="synapse-smoke-"))
        return temp_root / "synapse-smoke.sqlite", temp_root, True

    temp_root = Path(tempfile.mkdtemp(prefix="synapse-smoke-"))
    return temp_root / "synapse-smoke.sqlite", temp_root, True


def run_smoke(
    *,
    config_path: str | None = None,
    vault_root: str | None = None,
    db_path: str | None = None,
    query: str | None = None,
    limit: int = 3,
    discover_threshold: float = 0.2,
    with_cipher: str = "auto",
    cipher_doc_a: str = DEFAULT_CIPHER_DOC_A,
    cipher_doc_b: str = DEFAULT_CIPHER_DOC_B,
    keep_db: bool = False,
    reuse_db: bool = False,
) -> SmokeResult:
    settings = load_settings(config_path)
    resolved_vault = Path(vault_root).expanduser() if vault_root else FIXTURE_VAULT
    query_text = query or load_default_query()

    resolved_db, temp_root, used_temporary_db = _prepare_db_path(
        Path(db_path) if db_path else None,
        keep_db=keep_db,
        reuse_db=reuse_db,
    )

    try:
        health = runtime_requirements(
            HealthRequest(
                config_path=config_path,
                vault_root=str(resolved_vault),
                db_path=str(resolved_db),
            )
        )
        index = index_vault(
            IndexRequest(
                config_path=config_path,
                vault_root=str(resolved_vault),
                db_path=str(resolved_db),
            )
        )
        if index.stats.errors:
            raise RuntimeError(f"Smoke indexing reported errors: {index.stats.errors}")

        search = search_index(
            SearchRequest(
                query=query_text,
                config_path=config_path,
                db_path=str(resolved_db),
                mode="research",
                limit=limit,
            )
        )
        discover = discover_index(
            DiscoverRequest(
                config_path=config_path,
                db_path=str(resolved_db),
                threshold=discover_threshold,
                top_k=3,
                max_total=10,
            )
        )
        validate = validate_index(
            ValidateRequest(
                config_path=config_path,
                db_path=str(resolved_db),
            )
        )

        asyncio.run(
            cultivate(
                resolved_db,
                resolved_vault,
                apply=False,
                settings=settings,
                embedding_dim=settings.embedding_provider().dimensions,
            )
        )

        cipher_status = "skipped"
        cipher_summary: str | None = None
        if with_cipher == "always" and not reasoning_env_configured():
            raise RuntimeError(
                "Cipher smoke requested with --with-cipher=always, but reasoning env is not configured."
            )
        run_cipher = with_cipher == "always" or (
            with_cipher == "auto" and reasoning_env_configured()
        )
        if run_cipher:
            response = asyncio.run(
                CipherService().handle(
                    ExplainConnectionRequest(
                        doc_a=cipher_doc_a,
                        doc_b=cipher_doc_b,
                        timeout_seconds=settings.cipher.explain_timeout_seconds,
                    ),
                    CipherDeps(vault_root=resolved_vault, synapse_db=resolved_db),
                )
            )
            cipher_status = "passed"
            cipher_summary = response.explanation

        return SmokeResult(
            config_path=str(settings.config_path) if settings.config_path else None,
            vault_root=str(resolved_vault),
            db_path=str(resolved_db),
            used_temporary_db=used_temporary_db,
            health_ready=health.ready_for_indexing,
            indexed_files=index.stats.total_files,
            indexed_segments=index.stats.total_segments,
            search_query=query_text,
            top_search_paths=[
                item.source_id or item.note_path or item.origin_url or item.direct_paper_url or (item.title or "")
                for item in search.results[:limit]
            ],
            discovery_count=len(discover.discoveries),
            broken_link_count=len(validate.broken_links),
            garden_status="passed",
            cipher_status=cipher_status,
            cipher_summary=cipher_summary,
        )
    finally:
        if temp_root is not None and not keep_db:
            shutil.rmtree(temp_root, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run an agent-facing Synapse dry run against the fixture vault."
    )
    parser.add_argument("--config", default=None, help="Path to Synapse TOML config")
    parser.add_argument(
        "--vault-root",
        default=None,
        help="Markdown root to dry-run. Defaults to the bundled fixture vault.",
    )
    parser.add_argument(
        "--db",
        default=None,
        help="SQLite database path to use. Defaults to a fresh temporary DB.",
    )
    parser.add_argument(
        "--reuse-db",
        action="store_true",
        help="Allow reuse of an existing --db path. Disabled by default to avoid stale state.",
    )
    parser.add_argument(
        "--keep-db",
        action="store_true",
        help="Keep the temporary DB on disk instead of cleaning it up after the run.",
    )
    parser.add_argument(
        "--query",
        default=None,
        help="Search query for the smoke run. Defaults to the first fixture benchmark query.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="Top-k results to show for the smoke search.",
    )
    parser.add_argument(
        "--discover-threshold",
        type=float,
        default=0.2,
        help="Discovery threshold to use during the smoke run.",
    )
    parser.add_argument(
        "--with-cipher",
        choices=["auto", "always", "never"],
        default="auto",
        help="Whether to run the model-backed Cipher explanation step.",
    )
    parser.add_argument(
        "--cipher-doc-a",
        default=DEFAULT_CIPHER_DOC_A,
        help="First fixture note for the optional Cipher explanation step.",
    )
    parser.add_argument(
        "--cipher-doc-b",
        default=DEFAULT_CIPHER_DOC_B,
        help="Second fixture note for the optional Cipher explanation step.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the smoke summary as JSON.",
    )

    args = parser.parse_args()
    result = run_smoke(
        config_path=args.config,
        vault_root=args.vault_root,
        db_path=args.db,
        query=args.query,
        limit=args.limit,
        discover_threshold=args.discover_threshold,
        with_cipher=args.with_cipher,
        cipher_doc_a=args.cipher_doc_a,
        cipher_doc_b=args.cipher_doc_b,
        keep_db=args.keep_db,
        reuse_db=args.reuse_db,
    )

    if args.json:
        print(json.dumps(asdict(result), indent=2))
        return

    print("🧪 Synapse Smoke")
    print(f"   Config: {result.config_path or '(defaults)'}")
    print(f"   Vault: {result.vault_root}")
    print(f"   Database: {result.db_path}")
    print(f"   Temp DB: {'yes' if result.used_temporary_db else 'no'}")
    print(f"   Ready For Indexing: {'yes' if result.health_ready else 'no'}")
    print()
    print("✅ Index")
    print(f"   Files: {result.indexed_files}")
    print(f"   Segments: {result.indexed_segments}")
    print()
    print("✅ Search")
    print(f"   Query: {result.search_query}")
    for idx, path in enumerate(result.top_search_paths, start=1):
        print(f"   {idx}. {path}")
    print()
    print("✅ Discovery")
    print(f"   Connections: {result.discovery_count}")
    print()
    print("✅ Validation")
    print(f"   Broken Links: {result.broken_link_count}")
    print()
    print("✅ Gardener")
    print(f"   Status: {result.garden_status}")
    print()
    print("✅ Cipher" if result.cipher_status == "passed" else "ℹ️  Cipher")
    print(f"   Status: {result.cipher_status}")
    if result.cipher_summary:
        print(f"   Summary: {first_nonempty_line(result.cipher_summary)}")


if __name__ == "__main__":
    main()
