"""Gardener module — maintain and prune the markdown knowledge graph."""

import asyncio
from pathlib import Path
from typing import Iterable, Set
import argparse

from .cipher_service import (
    CipherDeps,
    CipherService,
    ReviewStubCandidatesRequest,
    StubCandidate,
)
from .validate import find_broken_links, BrokenLink
from .settings import AppSettings, load_settings
from .vector_store import create_vector_store

STUB_TEMPLATE = """---
type: entity
tags: [stub, auto-generated]
status: Stub
---

# {title}

## Definition

(Auto-generated stub for [[{title}]])

## Context
Linked from:
{backlinks}
"""

def _group_missing_targets(broken_links: Iterable[BrokenLink]) -> dict[str, Set[str]]:
    missing_targets: dict[str, Set[str]] = {}
    for link in broken_links:
        missing_targets.setdefault(link.target_link, set()).add(link.source_path)
    return missing_targets


def _safe_stub_name(target: str) -> str:
    return target.replace("/", "-").replace(":", " -")


def _default_stub_path(stub_dir: str, target: str) -> str:
    return f"{stub_dir}/{_safe_stub_name(target)}.md"


async def cultivate(
    db_path: Path,
    vault_root: Path,
    apply: bool = False,
    settings: AppSettings | None = None,
    embedding_dim: int = 768,
    stub_dir: str = "entities",
    cipher_service: CipherService | None = None,
):
    """
    Review broken links and optionally create approved stubs.
    """
    print(f"🌻 The Gardener is tending to {vault_root}...")
    
    resolved_settings = settings or load_settings()
    db = create_vector_store(resolved_settings, db_path=db_path, embedding_dim=embedding_dim)
    db.initialize()
    try:
        broken_links = find_broken_links(db)
        
        if not broken_links:
            print("✅ Garden is healthy. No broken links.")
            return

        print(f"🍂 Found {len(broken_links)} broken links.")
        
        missing_targets = _group_missing_targets(broken_links)
        print(f"🧪 Reviewing {len(missing_targets)} stub candidates with Cipher...")

        service = cipher_service or CipherService()
        review = await service.handle(
            ReviewStubCandidatesRequest(
                candidates=[
                    StubCandidate(
                        target_link=target,
                        source_paths=sorted(sources),
                        suggested_path=_default_stub_path(stub_dir, target),
                    )
                    for target, sources in sorted(missing_targets.items())
                ],
                stub_dir=stub_dir,
            ),
            CipherDeps(vault_root=vault_root, synapse_db=db_path),
        )

        approved = [item for item in review.reviews if item.action == "create_stub"]
        skipped = [item for item in review.reviews if item.action == "skip"]

        for item in approved:
            print(
                f"✅ Approve stub: {item.target_link} "
                f"({item.confidence:.0%}) -> {item.suggested_path or _default_stub_path(stub_dir, item.target_link)}"
            )
            print(f"   {item.rationale}")

        for item in skipped:
            print(f"⏭️  Skip stub: {item.target_link} ({item.confidence:.0%})")
            print(f"   {item.rationale}")

        if not approved:
            print("\n✅ No stub candidates approved.")
            return

        if not apply:
            print("\n🔍 Dry run complete. Re-run with --apply to write approved stubs.")
            return

        stub_root = vault_root / stub_dir
        stub_root.mkdir(parents=True, exist_ok=True)
        created_count = 0

        for item in approved:
            target = item.target_link
            file_path = vault_root / (item.suggested_path or _default_stub_path(stub_dir, target))
            if file_path.exists():
                print(f"⚠️  Skipping {target}: File exists but not indexed? (Run index)")
                continue

            sources = missing_targets.get(target, set())
            backlinks_text = "\n".join([f"- [[{Path(s).stem}]]" for s in sources])
            content = STUB_TEMPLATE.format(
                title=target,
                backlinks=backlinks_text
            )

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            print(f"✨ Created: {file_path.relative_to(vault_root)}")
            created_count += 1

        if created_count > 0:
            print(f"\n✅ Created {created_count} approved stubs. Run 'synapse-index' to register them.")
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description="🌻 Synapse Gardener")
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
        "--vault-root",
        default=None,
        help="Path to vault root"
    )
    parser.add_argument(
        "--stub-dir",
        default="entities",
        help="Relative directory for approved stubs",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write approved stubs to disk after Cipher review",
    )
    
    args = parser.parse_args()
    settings = load_settings(args.config)
    db_path = Path(args.db or settings.database.path).expanduser()
    vault_root = Path(args.vault_root or settings.vault.root).expanduser()
    provider = settings.embedding_provider()

    asyncio.run(
        cultivate(
            db_path,
            vault_root,
            apply=args.apply,
            settings=settings,
            embedding_dim=provider.dimensions,
            stub_dir=args.stub_dir,
        )
    )


if __name__ == "__main__":
    main()
