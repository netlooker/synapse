"""Tests for deterministic knowledge schema helpers."""

from datetime import datetime, timezone

import pytest

from synapse.knowledge_schema import (
    KnowledgeNoteKind,
    REQUIRED_FRONTMATTER_KEYS,
    build_frontmatter,
    managed_index_path,
    managed_log_path,
    managed_note_path,
    render_note_markdown,
    render_source_summary_body,
    serialize_frontmatter,
    slugify,
    validate_frontmatter,
)


def test_slugify_handles_punctuation_and_unicode():
    assert slugify("Attention Is All You Need!") == "attention-is-all-you-need"
    assert slugify("  ---hello---  ") == "hello"
    assert slugify("") == "untitled"
    assert slugify("///") == "untitled"


def test_managed_paths_use_kind_directory_layout():
    note = managed_note_path("_compiled", KnowledgeNoteKind.SOURCE_SUMMARY, "foo")
    assert note == "_compiled/sources/foo.md"
    scoped = managed_note_path("_compiled", KnowledgeNoteKind.SOURCE_SUMMARY, "foo", "bundle-1")
    assert scoped == "_compiled/sources/bundle-1/foo.md"
    assert managed_index_path("_compiled") == "_compiled/index.md"
    assert managed_log_path("_compiled") == "_compiled/log.md"
    # managed_root override
    assert managed_note_path("knowledge", KnowledgeNoteKind.CONCEPT, "x") == "knowledge/concepts/x.md"


def test_build_frontmatter_populates_required_keys_and_normalizes_lists():
    fm = build_frontmatter(
        note_kind=KnowledgeNoteKind.SOURCE_SUMMARY,
        title="Signals",
        status="draft",
        generated_by="synapse",
        generated_at=datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc),
        bundle_ids=["b1", "b1", None, ""],
        source_ids=["s1"],
        origin_urls=["https://example.com/a"],
        related_notes=[],
    )
    for key in REQUIRED_FRONTMATTER_KEYS:
        assert key in fm
    assert fm["note_kind"] == "source_summary"
    assert fm["generated_at"] == "2026-04-10T12:00:00Z"
    assert fm["bundle_ids"] == ["b1"]  # deduped, empties stripped
    assert fm["related_notes"] == []


def test_validate_frontmatter_rejects_missing_keys():
    with pytest.raises(ValueError):
        validate_frontmatter({"note_kind": "source_summary"})


def test_serialize_frontmatter_emits_stable_yaml():
    fm = build_frontmatter(
        note_kind=KnowledgeNoteKind.SOURCE_SUMMARY,
        title="A Paper: Deep Dive",
        status="draft",
        generated_by="synapse",
        generated_at=datetime(2026, 4, 10, 12, 0, 0, tzinfo=timezone.utc),
        bundle_ids=["bundle-1"],
        source_ids=["src-1"],
        origin_urls=["https://example.com/x"],
    )
    text = serialize_frontmatter(fm)
    # First and last lines must be document markers.
    assert text.startswith("---\n")
    assert text.endswith("\n---")
    # Required keys appear in deterministic order.
    lines = text.splitlines()
    body = "\n".join(lines)
    assert "note_kind: source_summary" in body
    assert 'title: "A Paper: Deep Dive"' in body  # colon forces quoting
    assert "origin_urls:" in body
    assert "  - https://example.com/x" in body
    # Empty list renders inline, not as nested bullet block.
    assert "related_notes: []" in body


def test_render_note_markdown_combines_frontmatter_and_body():
    fm = build_frontmatter(
        note_kind=KnowledgeNoteKind.SOURCE_SUMMARY,
        title="T",
        status="draft",
        generated_by="synapse",
    )
    md = render_note_markdown(fm, "hello world")
    assert md.startswith("---\n")
    assert "hello world" in md
    assert md.endswith("\n")


def test_render_source_summary_body_is_deterministic_and_covers_fields():
    body = render_source_summary_body(
        title="Attention Is All You Need",
        bundle_id="bundle-1",
        source_id="src-1",
        origin_url="https://arxiv.org/abs/1706.03762",
        direct_paper_url="https://arxiv.org/pdf/1706.03762",
        summary_text="Transformer architecture summary.",
        abstract_text="We propose the Transformer...",
        full_text_excerpt="The dominant sequence transduction models...",
        authors=["Vaswani", "Shazeer"],
        published="2017-06-12",
    )
    assert body.startswith("# Attention Is All You Need")
    assert "## Provenance" in body
    assert "- bundle: `bundle-1`" in body
    assert "- source: `src-1`" in body
    assert "- origin: <https://arxiv.org/abs/1706.03762>" in body
    assert "- paper: <https://arxiv.org/pdf/1706.03762>" in body
    assert "## Summary" in body
    assert "## Abstract" in body
    assert "## Excerpt" in body
    assert "Vaswani, Shazeer" in body
    # Determinism — calling twice returns the same string.
    body2 = render_source_summary_body(
        title="Attention Is All You Need",
        bundle_id="bundle-1",
        source_id="src-1",
        origin_url="https://arxiv.org/abs/1706.03762",
        direct_paper_url="https://arxiv.org/pdf/1706.03762",
        summary_text="Transformer architecture summary.",
        abstract_text="We propose the Transformer...",
        full_text_excerpt="The dominant sequence transduction models...",
        authors=["Vaswani", "Shazeer"],
        published="2017-06-12",
    )
    assert body == body2


def test_render_source_summary_body_handles_missing_text():
    body = render_source_summary_body(
        title="Bare Source",
        bundle_id="b",
        source_id="s",
        origin_url=None,
        direct_paper_url=None,
        summary_text=None,
        abstract_text=None,
        full_text_excerpt=None,
    )
    assert "## Notes" in body
    assert "No extracted text was available" in body
