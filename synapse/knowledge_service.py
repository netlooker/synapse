"""Deterministic orchestration for the compiled knowledge layer.

Phase 1 scope:
- compile_bundle: produce source_summary proposals for every source in a bundle.
- list/get proposals and overview counts.
- apply/reject proposals: apply writes markdown into the managed subtree,
  updates index.md and log.md, then re-indexes affected files through the
  normal Indexer path.

No model/Cipher plumbing lives here. All markdown bodies are rendered
deterministically from already-indexed source fields.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .embeddings import EmbeddingClient
from .errors import (
    SynapseBadRequestError,
    SynapseConflictError,
    SynapseNotFoundError,
)
from .index import Indexer
from .knowledge_schema import (
    CompiledNoteDraft,
    KnowledgeNoteKind,
    build_frontmatter,
    managed_index_path,
    managed_log_path,
    managed_note_path,
    render_note_markdown,
    render_source_summary_body,
    slugify,
)
from .settings import AppSettings, KnowledgeSettings
from .vector_store import VectorStore


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def ensure_enabled(settings: KnowledgeSettings) -> None:
    if not settings.enabled:
        raise SynapseBadRequestError(
            "Compiled knowledge layer is disabled. Set knowledge.enabled = true to use this feature."
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_if_exists(path: Path) -> str | None:
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8")
    return None


def _truncate_text(text: str | None, max_chars: int = 1200) -> str | None:
    if not text:
        return None
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    head = stripped[: max_chars - 1].rstrip()
    return head + "…"


def build_source_summary_draft(
    *,
    source: dict[str, Any],
    knowledge: KnowledgeSettings,
    generated_at: datetime | None = None,
) -> CompiledNoteDraft:
    """Build the deterministic source_summary draft for a single source."""
    title = (source.get("title") or source.get("source_id") or "Untitled source").strip()
    bundle_id = str(source.get("bundle_id") or "")
    source_id = str(source.get("source_id") or "")
    slug = slugify(source_id or title)
    bundle_slug = slugify(bundle_id or "bundle")
    target_path = managed_note_path(
        knowledge.managed_root,
        KnowledgeNoteKind.SOURCE_SUMMARY,
        slug,
        bundle_slug,
    )
    origin_url = source.get("origin_url") or None
    direct_paper_url = source.get("direct_paper_url") or None

    body = render_source_summary_body(
        title=title,
        bundle_id=bundle_id,
        source_id=source_id,
        origin_url=origin_url,
        direct_paper_url=direct_paper_url,
        summary_text=source.get("summary_text"),
        abstract_text=source.get("abstract_text"),
        full_text_excerpt=_truncate_text(source.get("full_text")),
        authors=list(source.get("authors") or []),
        published=source.get("published"),
    )

    frontmatter = build_frontmatter(
        note_kind=KnowledgeNoteKind.SOURCE_SUMMARY,
        title=title,
        status=knowledge.default_status,
        generated_by=knowledge.generated_by,
        generated_at=generated_at,
        bundle_ids=[bundle_id] if bundle_id else [],
        source_ids=[source_id] if source_id else [],
        origin_urls=[u for u in (origin_url, direct_paper_url) if u],
        related_notes=[],
    )

    supporting_refs = {
        "bundle_id": bundle_id,
        "source_id": source_id,
        "origin_url": origin_url,
        "direct_paper_url": direct_paper_url,
        "authors": list(source.get("authors") or []),
        "published": source.get("published"),
        "source_type": source.get("source_type"),
    }

    return CompiledNoteDraft(
        note_kind=KnowledgeNoteKind.SOURCE_SUMMARY,
        slug=slug,
        title=title,
        target_path=target_path,
        frontmatter=frontmatter,
        body_markdown=body,
        supporting_refs=supporting_refs,
    )


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompileBundleResult:
    job_id: int
    bundle_id: str
    proposal_ids: list[int]
    created_count: int


@dataclass(frozen=True)
class ApplyProposalResult:
    proposal_id: int
    target_path: str
    written_path: str
    reindexed_files: list[str]


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class KnowledgeService:
    """Deterministic orchestration for the compiled knowledge layer."""

    def __init__(
        self,
        *,
        store: VectorStore,
        settings: AppSettings,
        vault_root: Path,
        indexer_factory=None,
    ):
        self.store = store
        self.settings = settings
        self.vault_root = Path(vault_root)
        self._indexer_factory = indexer_factory

    # ---- compile ------------------------------------------------------

    def compile_bundle(self, bundle_id: str) -> CompileBundleResult:
        ensure_enabled(self.settings.knowledge)
        bundle = self.store.get_bundle(bundle_id)
        if not bundle:
            raise SynapseNotFoundError(f"Bundle not found: {bundle_id}")
        sources = self.store.list_sources_for_bundle(bundle_id)
        if not sources:
            raise SynapseBadRequestError(
                f"Bundle {bundle_id} has no sources to compile."
            )

        job_id = self.store.create_knowledge_job(
            job_kind="compile_bundle",
            scope={"bundle_id": bundle_id},
            status="running",
            summary=f"Compile source summaries for {bundle_id}",
        )

        proposal_ids: list[int] = []
        generated_at = datetime.now(timezone.utc)
        for source in sources:
            draft = build_source_summary_draft(
                source=source,
                knowledge=self.settings.knowledge,
                generated_at=generated_at,
            )
            existing_path = self.vault_root / draft.target_path
            base_hash: str | None = None
            if existing_path.exists():
                base_hash = _content_hash(existing_path.read_text(encoding="utf-8"))

            proposal_id = self.store.insert_knowledge_proposal(
                job_id=job_id,
                note_kind=draft.note_kind.value,
                slug=draft.slug,
                target_path=draft.target_path,
                title=draft.title,
                body_markdown=draft.body_markdown,
                frontmatter=draft.frontmatter,
                supporting_refs=draft.supporting_refs,
                base_content_hash=base_hash,
                status="pending",
            )
            proposal_ids.append(proposal_id)

        self.store.update_knowledge_job(
            job_id,
            status="ready",
            summary=f"Created {len(proposal_ids)} source_summary proposal(s) for {bundle_id}",
        )

        return CompileBundleResult(
            job_id=job_id,
            bundle_id=bundle_id,
            proposal_ids=proposal_ids,
            created_count=len(proposal_ids),
        )

    # ---- queries ------------------------------------------------------

    def list_proposals(self, *, status: str | None = None, limit: int | None = None) -> list[dict[str, Any]]:
        ensure_enabled(self.settings.knowledge)
        return self.store.list_knowledge_proposals(status=status, limit=limit)

    def get_proposal(self, proposal_id: int) -> dict[str, Any]:
        ensure_enabled(self.settings.knowledge)
        proposal = self.store.get_knowledge_proposal(proposal_id)
        if not proposal:
            raise SynapseNotFoundError(f"Proposal not found: {proposal_id}")
        return proposal

    def overview(self) -> dict[str, Any]:
        ensure_enabled(self.settings.knowledge)
        counts_by_status = self.store.count_knowledge_proposals_by_status()
        recent_proposals = self.store.list_knowledge_proposals(limit=10)
        return {
            "managed_root": self.settings.knowledge.managed_root,
            "counts": counts_by_status,
            "recent_proposals": recent_proposals,
            "vault_root": str(self.vault_root),
        }

    # ---- apply / reject -----------------------------------------------

    def apply_proposal(self, proposal_id: int) -> ApplyProposalResult:
        ensure_enabled(self.settings.knowledge)
        proposal = self.store.get_knowledge_proposal(proposal_id)
        if not proposal:
            raise SynapseNotFoundError(f"Proposal not found: {proposal_id}")
        if proposal["status"] not in {"pending"}:
            raise SynapseBadRequestError(
                f"Proposal {proposal_id} is not pending (status={proposal['status']})."
            )

        target_path = proposal["target_path"]
        on_disk = self.vault_root / target_path
        current_hash: str | None = None
        if on_disk.exists():
            current_hash = _content_hash(on_disk.read_text(encoding="utf-8"))
        expected_hash = proposal.get("base_content_hash")
        if current_hash != expected_hash:
            raise SynapseConflictError(
                f"Target file changed since proposal {proposal_id} was generated."
            )

        markdown = render_note_markdown(
            proposal["frontmatter"],
            proposal["body_markdown"],
        )

        index_path = self.vault_root / managed_index_path(self.settings.knowledge.managed_root)
        log_path = self.vault_root / managed_log_path(self.settings.knowledge.managed_root)
        snapshots = self._snapshot_files([on_disk, index_path, log_path])

        try:
            on_disk.parent.mkdir(parents=True, exist_ok=True)
            on_disk.write_text(markdown, encoding="utf-8")

            self._update_index_md(include_proposals=[proposal])
            self._append_log_entry(
                action="apply",
                proposal=proposal,
            )

            reindexed = self._reindex_managed(target_path)
        except Exception:
            self._restore_files(snapshots)
            raise

        self.store.update_knowledge_proposal_status(
            proposal_id,
            status="applied",
            reviewer_action={
                "action": "apply",
                "at": _now_iso(),
                "target_path": target_path,
            },
        )

        return ApplyProposalResult(
            proposal_id=proposal_id,
            target_path=target_path,
            written_path=str(on_disk),
            reindexed_files=reindexed,
        )

    def reject_proposal(
        self,
        proposal_id: int,
        *,
        reason: str | None = None,
    ) -> dict[str, Any]:
        ensure_enabled(self.settings.knowledge)
        proposal = self.store.get_knowledge_proposal(proposal_id)
        if not proposal:
            raise SynapseNotFoundError(f"Proposal not found: {proposal_id}")
        if proposal["status"] not in {"pending"}:
            raise SynapseBadRequestError(
                f"Proposal {proposal_id} is not pending (status={proposal['status']})."
            )
        self.store.update_knowledge_proposal_status(
            proposal_id,
            status="rejected",
            reviewer_action={
                "action": "reject",
                "at": _now_iso(),
                "reason": reason or "",
            },
        )
        self._append_log_entry(
            action="reject",
            proposal=proposal,
            reason=reason,
        )
        refreshed = self.store.get_knowledge_proposal(proposal_id)
        assert refreshed is not None
        return refreshed

    # ---- internal helpers ---------------------------------------------

    def _append_log_entry(
        self,
        *,
        action: str,
        proposal: dict[str, Any],
        reason: str | None = None,
    ) -> None:
        log_rel = managed_log_path(self.settings.knowledge.managed_root)
        log_path = self.vault_root / log_rel
        log_path.parent.mkdir(parents=True, exist_ok=True)

        if not log_path.exists():
            header = (
                "# Compiled knowledge log\n\n"
                "Append-only operational history of compile, apply, and reject actions.\n"
            )
            log_path.write_text(header, encoding="utf-8")

        line = (
            f"- {_now_iso()} :: {action} :: proposal #{proposal['id']} "
            f"({proposal['note_kind']}) -> `{proposal['target_path']}`"
        )
        if reason:
            line += f" -- reason: {reason}"
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _update_index_md(self, *, include_proposals: Iterable[dict[str, Any]] = ()) -> None:
        index_rel = managed_index_path(self.settings.knowledge.managed_root)
        index_path = self.vault_root / index_rel
        index_path.parent.mkdir(parents=True, exist_ok=True)

        applied = list(self.store.list_knowledge_proposals(status="applied"))
        by_id = {row["id"]: row for row in applied}
        for proposal in include_proposals:
            by_id[proposal["id"]] = proposal
        applied = list(by_id.values())
        lines = [
            "# Compiled knowledge index",
            "",
            "This index is maintained by Synapse. It lists compiled notes grouped by kind.",
            "",
        ]
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for proposal in applied:
            by_kind.setdefault(proposal["note_kind"], []).append(proposal)
        for kind in sorted(by_kind):
            lines.append(f"## {kind}")
            lines.append("")
            for row in sorted(by_kind[kind], key=lambda r: r["target_path"]):
                title = row.get("title") or row["target_path"]
                link = posixpath.relpath(
                    row["target_path"],
                    start=posixpath.dirname(index_rel),
                )
                lines.append(f"- [{title}]({link})")
            lines.append("")
        index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _reindex_managed(self, changed_path: str) -> list[str]:
        """Re-index only the files under the managed root.

        We deliberately narrow the indexer scan to the managed subtree by
        calling ``index_file`` on the targeted file plus ``index.md`` and
        ``log.md``. This keeps apply fast and avoids re-scanning the entire
        vault.
        """
        if self._indexer_factory is None:
            return []
        indexer = self._indexer_factory()
        touched: list[str] = []
        managed_root = self.settings.knowledge.managed_root
        candidates = [
            self.vault_root / changed_path,
            self.vault_root / managed_index_path(managed_root),
            self.vault_root / managed_log_path(managed_root),
        ]
        for path in candidates:
            if path.exists() and path.is_file():
                result = indexer.index_file(path)
                touched.append(result.get("path", str(path)))
        return touched

    def _snapshot_files(self, paths: Iterable[Path]) -> dict[Path, tuple[bool, str | None]]:
        snapshots: dict[Path, tuple[bool, str | None]] = {}
        for path in paths:
            if path.exists() and path.is_file():
                snapshots[path] = (True, path.read_text(encoding="utf-8"))
            else:
                snapshots[path] = (False, None)
        return snapshots

    def _restore_files(self, snapshots: dict[Path, tuple[bool, str | None]]) -> None:
        for path, (existed, content) in snapshots.items():
            if existed:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content or "", encoding="utf-8")
                continue
            if path.exists():
                path.unlink()


# ---------------------------------------------------------------------------
# Service constructor helpers
# ---------------------------------------------------------------------------


def build_indexer_factory(
    *,
    store: VectorStore,
    settings: AppSettings,
    vault_root: Path,
):
    """Build an Indexer factory that matches the default runtime wiring."""

    def factory() -> Indexer:
        note_cfg = settings.embedding_provider()
        chunk_cfg = settings.embedding_provider(settings.index.contextual_provider)
        return Indexer(
            db=store,
            vault_root=vault_root,
            note_embedding_client=EmbeddingClient.from_provider(note_cfg),
            chunk_embedding_client=EmbeddingClient.from_provider(chunk_cfg),
            min_chunk_chars=settings.index.min_chunk_chars,
            max_chunk_chars=settings.index.max_chunk_chars,
            target_chunk_tokens=settings.index.target_chunk_tokens,
            max_chunk_tokens=settings.index.max_chunk_tokens,
            chunk_overlap_chars=settings.index.chunk_overlap_chars,
            chunk_strategy=settings.index.chunk_strategy,
            include_patterns=settings.vault.include,
            exclude_patterns=settings.vault.exclude,
        )

    return factory
