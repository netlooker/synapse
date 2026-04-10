"""Schema helpers for the compiled knowledge layer.

This module contains deterministic helpers only — frontmatter serialization,
slug generation, managed-subtree path computation, and small rendering helpers.
Nothing here performs IO or talks to the model layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any, Iterable


class KnowledgeNoteKind(str, Enum):
    """Controlled taxonomy of compiled knowledge note kinds."""

    SOURCE_SUMMARY = "source_summary"
    CONCEPT = "concept"
    COMPARISON = "comparison"
    SYNTHESIS = "synthesis"
    QUERY_OUTPUT = "query_output"


KIND_DIRECTORIES: dict[KnowledgeNoteKind, str] = {
    KnowledgeNoteKind.SOURCE_SUMMARY: "sources",
    KnowledgeNoteKind.CONCEPT: "concepts",
    KnowledgeNoteKind.COMPARISON: "comparisons",
    KnowledgeNoteKind.SYNTHESIS: "syntheses",
    KnowledgeNoteKind.QUERY_OUTPUT: "queries",
}


REQUIRED_FRONTMATTER_KEYS: tuple[str, ...] = (
    "note_kind",
    "title",
    "status",
    "generated_by",
    "generated_at",
    "bundle_ids",
    "source_ids",
    "origin_urls",
    "related_notes",
)


@dataclass(frozen=True)
class CompiledNoteDraft:
    """A deterministic, not-yet-persisted compiled note."""

    note_kind: KnowledgeNoteKind
    slug: str
    title: str
    target_path: str  # posix path relative to vault root
    frontmatter: dict[str, Any]
    body_markdown: str
    supporting_refs: dict[str, Any]


def slugify(value: str) -> str:
    """Deterministic lowercase kebab-case slug."""
    if not value:
        return "untitled"
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = lowered.strip("-")
    return lowered or "untitled"


def kind_directory(kind: KnowledgeNoteKind) -> str:
    return KIND_DIRECTORIES[kind]


def managed_note_path(
    managed_root: str,
    kind: KnowledgeNoteKind,
    slug: str,
    *parents: str,
) -> str:
    """Return the managed relative posix path for a compiled note."""
    root = (managed_root or "_compiled").strip("/")
    directory = kind_directory(kind)
    path = PurePosixPath(root) / directory
    for parent in parents:
        parent_text = str(parent).strip("/")
        if parent_text:
            path /= parent_text
    return str(path / f"{slug}.md")


def managed_index_path(managed_root: str) -> str:
    root = (managed_root or "_compiled").strip("/")
    return str(PurePosixPath(root) / "index.md")


def managed_log_path(managed_root: str) -> str:
    root = (managed_root or "_compiled").strip("/")
    return str(PurePosixPath(root) / "log.md")


def build_frontmatter(
    *,
    note_kind: KnowledgeNoteKind,
    title: str,
    status: str,
    generated_by: str,
    generated_at: datetime | None = None,
    bundle_ids: Iterable[str] = (),
    source_ids: Iterable[str] = (),
    origin_urls: Iterable[str] = (),
    related_notes: Iterable[str] = (),
) -> dict[str, Any]:
    """Build a strict frontmatter dict with the required Phase 1 fields."""
    ts = (generated_at or datetime.now(timezone.utc))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return {
        "note_kind": note_kind.value,
        "title": title,
        "status": status,
        "generated_by": generated_by,
        "generated_at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bundle_ids": _unique_list(bundle_ids),
        "source_ids": _unique_list(source_ids),
        "origin_urls": _unique_list(origin_urls),
        "related_notes": _unique_list(related_notes),
    }


def validate_frontmatter(frontmatter: dict[str, Any]) -> None:
    """Ensure every Phase 1 required key is present."""
    missing = [key for key in REQUIRED_FRONTMATTER_KEYS if key not in frontmatter]
    if missing:
        raise ValueError(
            f"Compiled note frontmatter missing required keys: {', '.join(missing)}"
        )


def serialize_frontmatter(frontmatter: dict[str, Any]) -> str:
    """Serialize frontmatter to a strict, predictable YAML block.

    This uses a narrow dialect that handles scalar strings, booleans, ints,
    and lists of strings. The compiled layer never emits nested structures,
    so we avoid pulling in PyYAML as a new dependency.
    """
    validate_frontmatter(frontmatter)
    lines: list[str] = ["---"]
    for key in REQUIRED_FRONTMATTER_KEYS:
        value = frontmatter[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    # include any extra keys deterministically at the end
    for key in sorted(k for k in frontmatter if k not in REQUIRED_FRONTMATTER_KEYS):
        value = frontmatter[key]
        if isinstance(value, list):
            if not value:
                lines.append(f"{key}: []")
                continue
            lines.append(f"{key}:")
            for item in value:
                lines.append(f"  - {_yaml_scalar(item)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def render_note_markdown(frontmatter: dict[str, Any], body_markdown: str) -> str:
    """Render the full markdown document for a compiled note."""
    header = serialize_frontmatter(frontmatter)
    body = (body_markdown or "").strip()
    return f"{header}\n\n{body}\n" if body else f"{header}\n"


def render_source_summary_body(
    *,
    title: str,
    bundle_id: str,
    source_id: str,
    origin_url: str | None,
    direct_paper_url: str | None,
    summary_text: str | None,
    abstract_text: str | None,
    full_text_excerpt: str | None,
    authors: list[str] | None = None,
    published: str | None = None,
) -> str:
    """Deterministic source_summary body from already-indexed source fields."""
    parts: list[str] = [f"# {title}"]

    provenance_lines: list[str] = []
    provenance_lines.append(f"- bundle: `{bundle_id}`")
    provenance_lines.append(f"- source: `{source_id}`")
    if origin_url:
        provenance_lines.append(f"- origin: <{origin_url}>")
    if direct_paper_url and direct_paper_url != origin_url:
        provenance_lines.append(f"- paper: <{direct_paper_url}>")
    if authors:
        provenance_lines.append(f"- authors: {', '.join(authors)}")
    if published:
        provenance_lines.append(f"- published: {published}")
    parts.append("## Provenance\n\n" + "\n".join(provenance_lines))

    if summary_text and summary_text.strip():
        parts.append("## Summary\n\n" + summary_text.strip())
    if abstract_text and abstract_text.strip():
        parts.append("## Abstract\n\n" + abstract_text.strip())
    if full_text_excerpt and full_text_excerpt.strip():
        parts.append("## Excerpt\n\n" + full_text_excerpt.strip())

    if not (summary_text or abstract_text or full_text_excerpt):
        parts.append(
            "## Notes\n\nNo extracted text was available for this source at compile time."
        )

    return "\n\n".join(parts)


def _unique_list(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values or []:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


_YAML_SAFE_RE = re.compile(r"^[A-Za-z0-9_\-./:@+]+$")


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = "" if value is None else str(value)
    if text == "":
        return '""'
    if _YAML_SAFE_RE.match(text) and not text.startswith("-"):
        return text
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
