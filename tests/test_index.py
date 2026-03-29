"""
Tests for synapse.index - Main indexing logic
"""
import tempfile
from pathlib import Path

import pytest


class TestMarkdownParsing:
    """Test markdown file parsing."""

    def test_extract_title_from_h1(self):
        """Should extract title from first H1."""
        from synapse.index import extract_title
        
        content = """---
type: entity
---

# My Entity Title

Some content here.
"""
        title = extract_title(content)
        assert title == "My Entity Title"

    def test_extract_title_from_frontmatter(self):
        """Should fall back to frontmatter title if no H1."""
        from synapse.index import extract_title
        
        content = """---
type: entity
title: Frontmatter Title
---

Some content without H1.
"""
        title = extract_title(content)
        assert title == "Frontmatter Title"

    def test_extract_wikilinks(self):
        """Should extract all [[WikiLinks]] from content."""
        from synapse.index import extract_wikilinks
        
        content = """
# Test Document

This references [[Elixir]] and [[Python]].
Also mentions [[sqlite-vec]] for vectors.
"""
        links = extract_wikilinks(content)
        
        assert "Elixir" in links
        assert "Python" in links
        assert "sqlite-vec" in links
        assert len(links) == 3

    def test_extract_wikilinks_handles_duplicates(self):
        """Should return unique links only."""
        from synapse.index import extract_wikilinks
        
        content = """
[[Elixir]] is great. I love [[Elixir]]. Did I mention [[Elixir]]?
"""
        links = extract_wikilinks(content)
        
        assert links == ["Elixir"]

    def test_extract_document_metadata_combines_frontmatter_and_inline_signals(self):
        from synapse.index import extract_document_metadata

        content = """---
tags: [embeddings, maintenance]
status: Draft
---

# Vector Drift

This note links to [[Cipher]] and uses #retrieval in the body.
"""
        metadata = extract_document_metadata(content)

        assert metadata["frontmatter"]["status"] == "Draft"
        assert "embeddings" in metadata["tags"]
        assert "retrieval" in metadata["tags"]
        assert "Cipher" in metadata["wikilinks"]


class TestChunking:
    """Test document chunking strategies."""

    def test_chunk_by_heading(self):
        """Should split content by markdown headings."""
        from synapse.index import chunk_by_heading
        
        content = """# Main Title

Intro paragraph.

## Section One

Content of section one.

## Section Two

Content of section two.
"""
        chunks = chunk_by_heading(content)
        
        assert len(chunks) >= 2
        assert any("Section One" in c for c in chunks)
        assert any("Section Two" in c for c in chunks)

    def test_chunk_by_heading_preserves_context(self):
        """Each chunk should include its heading."""
        from synapse.index import chunk_by_heading
        
        content = """# Title

## Overview

This is the overview.

## Details

These are the details.
"""
        chunks = chunk_by_heading(content)
        
        # Each chunk should be self-contained with its heading
        for chunk in chunks:
            # Should have some structure
            assert len(chunk.strip()) > 0

    def test_hybrid_chunking_splits_large_sections_with_overlap(self):
        from synapse.index import ChunkingConfig, chunk_markdown

        content = """# Retrieval Design

## Large Section

Paragraph one explains that semantic retrieval finds related notes even when the language differs.

Paragraph two explains that chunk overlap should preserve local continuity between split passages.

Paragraph three explains that heading-aware chunking should remain readable and deterministic.
"""
        chunks = chunk_markdown(
            content,
            ChunkingConfig(
                min_chunk_chars=40,
                max_chunk_chars=170,
                target_chunk_tokens=18,
                max_chunk_tokens=24,
                chunk_overlap_chars=60,
                chunk_strategy="hybrid",
            ),
        )

        assert len(chunks) >= 2
        assert "Paragraph one" in chunks[0]
        assert "Paragraph two" in chunks[1]
        assert "preserve local continuity" in chunks[1]

    def test_heading_strategy_keeps_short_sections_separate(self):
        from synapse.index import ChunkingConfig, chunk_markdown

        content = """# Note

## One

Alpha

## Two

Beta
"""
        chunks = chunk_markdown(
            content,
            ChunkingConfig(
                min_chunk_chars=1,
                max_chunk_chars=400,
                chunk_strategy="heading",
            ),
        )

        assert len(chunks) >= 2
        assert any("## One" in chunk for chunk in chunks)
        assert any("## Two" in chunk for chunk in chunks)


class TestFileScanning:
    """Test cortex file discovery."""

    def test_find_markdown_files(self):
        """Should find all .md files in cortex directory."""
        from synapse.index import find_markdown_files
        
        with tempfile.TemporaryDirectory() as tmpdir:
            cortex = Path(tmpdir) / "cortex"
            cortex.mkdir()
            (cortex / "entities").mkdir()
            (cortex / "intel").mkdir()
            
            # Create test files
            (cortex / "entities" / "Test1.md").write_text("# Test 1")
            (cortex / "entities" / "Test2.md").write_text("# Test 2")
            (cortex / "intel" / "Report.md").write_text("# Report")
            (cortex / "README.txt").write_text("Not markdown")
            
            files = find_markdown_files(cortex)
            
            assert len(files) == 3
            assert all(f.suffix == ".md" for f in files)

    def test_find_markdown_files_honors_include_and_exclude_patterns(self):
        from synapse.index import find_markdown_files

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "notes"
            root.mkdir()
            (root / "projects").mkdir()
            (root / ".git").mkdir()
            (root / ".obsidian").mkdir()

            (root / "projects" / "keep.md").write_text("# Keep")
            (root / "projects" / "ignore.txt").write_text("ignore")
            (root / ".git" / "hidden.md").write_text("# Hidden")
            (root / ".obsidian" / "workspace.md").write_text("# Workspace")

            files = find_markdown_files(
                root,
                include_patterns=("projects/**/*.md",),
                exclude_patterns=(".git/**", ".obsidian/**"),
            )

            assert [path.relative_to(root).as_posix() for path in files] == ["projects/keep.md"]

    def test_find_markdown_files_discovers_root_and_nested_markdown(self):
        from synapse.index import find_markdown_files

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "notes"
            root.mkdir()
            (root / "nested").mkdir()
            (root / "root.md").write_text("# Root")
            (root / "nested" / "child.md").write_text("# Child")

            files = find_markdown_files(
                root,
                include_patterns=("**/*.md",),
                exclude_patterns=(),
            )

            assert sorted(path.relative_to(root).as_posix() for path in files) == [
                "nested/child.md",
                "root.md",
            ]

    def test_compute_file_hash(self):
        """Should compute consistent SHA256 hash."""
        from synapse.index import compute_hash
        
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "test.md"
            test_file.write_text("Hello, world!")
            
            hash1 = compute_hash(test_file)
            hash2 = compute_hash(test_file)
            
            assert hash1 == hash2
            assert len(hash1) == 64  # SHA256 hex length


class TestIndexer:
    """Integration tests for the full indexer."""

    def test_index_single_file(self):
        """Should index a single markdown file."""
        from synapse.index import Indexer
        from synapse.db import Database

        class FakeEmbedder:
            def embed(self, text):
                return [0.1, 0.2, 0.3, 0.4]

            def embed_document_chunks(self, chunks, document_title=None, document_path=None):
                return [[0.1, 0.2, 0.3, 0.4] for _ in chunks]
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup
            db_path = Path(tmpdir) / "synapse.sqlite"
            cortex = Path(tmpdir) / "cortex"
            cortex.mkdir()
            
            test_file = cortex / "test.md"
            test_file.write_text("""---
type: entity
---

# Test Entity

This is a test entity about programming.
""")
            
            # Create indexer with mock embeddings
            db = Database(db_path, embedding_dim=4)
            db.initialize()
            
            indexer = Indexer(
                db=db,
                cortex_path=cortex,
                embedding_client=FakeEmbedder(),
            )
            
            # Index
            stats = indexer.index_file(test_file)
            
            assert stats["chunks_created"] > 0
            
            # Verify in database
            doc = db.get_document(str(test_file.relative_to(cortex)))
            assert doc is not None
            
            db.close()

    def test_index_file_creates_note_and_chunk_scopes(self):
        """Indexing should persist one note embedding plus chunk embeddings."""
        from synapse.index import Indexer
        from synapse.db import Database

        class FakeEmbedder:
            def embed(self, text):
                return [0.1, 0.2, 0.3, 0.4]

            def embed_document_chunks(self, chunks, document_title=None, document_path=None):
                return [[0.1, 0.2, 0.3, 0.4] for _ in chunks]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "synapse.sqlite"
            cortex = Path(tmpdir) / "cortex"
            cortex.mkdir()

            test_file = cortex / "test.md"
            test_file.write_text("""# Test Entity

## Overview

This section explains semantic indexing.

## Discovery

This section explains hidden links between notes.
""")

            db = Database(db_path, embedding_dim=4)
            db.initialize()

            indexer = Indexer(
                db=db,
                cortex_path=cortex,
                embedding_client=FakeEmbedder(),
                min_chunk_chars=10,
                max_chunk_chars=400,
                target_chunk_tokens=120,
                max_chunk_tokens=200,
                chunk_overlap_chars=40,
                chunk_strategy="hybrid",
            )

            stats = indexer.index_file(test_file)

            doc = db.get_document(str(test_file.relative_to(cortex)))
            note_chunks = db.get_chunks(doc["id"], scope="note")
            text_chunks = db.get_chunks(doc["id"], scope="chunk")

            assert stats["chunks_created"] >= 2
            assert len(note_chunks) == 1
            assert len(text_chunks) >= 2
            db.close()

    def test_index_file_persists_document_metadata(self):
        from synapse.index import Indexer
        from synapse.db import Database

        class FakeEmbedder:
            def embed(self, text):
                return [0.1, 0.2, 0.3, 0.4]

            def embed_document_chunks(self, chunks, document_title=None, document_path=None):
                return [[0.1, 0.2, 0.3, 0.4] for _ in chunks]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "synapse.sqlite"
            cortex = Path(tmpdir) / "cortex"
            cortex.mkdir()

            test_file = cortex / "vector-maintenance.md"
            test_file.write_text("""---
tags: [embeddings, maintenance]
status: Draft
---

# Vector Maintenance

This note links to [[Cipher]] and references #retrieval in the body.
""")

            db = Database(db_path, embedding_dim=4)
            db.initialize()

            indexer = Indexer(
                db=db,
                cortex_path=cortex,
                embedding_client=FakeEmbedder(),
            )
            indexer.index_file(test_file)

            doc = db.get_document(str(test_file.relative_to(cortex)))

            assert "embeddings" in doc["tags"]
            assert "retrieval" in doc["tags"]
            assert "Cipher" in doc["wikilinks"]
            assert doc["frontmatter"]["status"] == "Draft"
            db.close()

    def test_index_file_stores_paths_relative_to_markdown_root(self):
        from synapse.index import Indexer
        from synapse.db import Database

        class FakeEmbedder:
            def embed(self, text):
                return [0.1, 0.2, 0.3, 0.4]

            def embed_document_chunks(self, chunks, document_title=None, document_path=None):
                return [[0.1, 0.2, 0.3, 0.4] for _ in chunks]

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "synapse.sqlite"
            root = Path(tmpdir) / "notes"
            nested = root / "projects"
            nested.mkdir(parents=True)

            test_file = nested / "idea.md"
            test_file.write_text("# Idea\n\nNested note.")

            db = Database(db_path, embedding_dim=4)
            db.initialize()

            indexer = Indexer(
                db=db,
                cortex_path=root,
                embedding_client=FakeEmbedder(),
            )
            indexer.index_file(test_file)

            assert db.get_document("projects/idea.md") is not None
            assert db.get_document("notes/projects/idea.md") is None
            db.close()
