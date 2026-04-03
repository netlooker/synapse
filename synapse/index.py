"""
synapse.index - Main indexing logic
"""
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .embeddings import EmbeddingClient, EmbeddingService
from .settings import load_settings
from .vector_store import VectorStore, create_vector_store


def extract_title(content: str) -> str | None:
    """Extract title from markdown content.
    
    Priority:
    1. First H1 heading
    2. 'title' from YAML frontmatter
    3. None
    """
    # Try H1 first
    h1_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if h1_match:
        return h1_match.group(1).strip()
    
    # Try frontmatter
    frontmatter_match = re.search(
        r"^---\s*\n(.*?)\n---", 
        content, 
        re.DOTALL
    )
    if frontmatter_match:
        fm_content = frontmatter_match.group(1)
        title_match = re.search(r"^title:\s*(.+)$", fm_content, re.MULTILINE)
        if title_match:
            return title_match.group(1).strip().strip('"\'')
    
    return None


def extract_wikilinks(content: str) -> list[str]:
    """Extract all [[WikiLinks]] from content.
    
    Returns unique links in order of first appearance.
    """
    matches = re.findall(r"\[\[([^\]]+)\]\]", content)
    
    # Unique, preserving order
    seen = set()
    unique = []
    for link in matches:
        if link not in seen:
            seen.add(link)
            unique.append(link)
    
    return unique


def extract_frontmatter(content: str) -> dict[str, Any]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", content, flags=re.DOTALL)
    if not match:
        return {}

    lines = match.group(1).splitlines()
    parsed: dict[str, Any] = {}
    idx = 0
    while idx < len(lines):
        line = lines[idx].rstrip()
        idx += 1
        if not line.strip() or ":" not in line:
            continue

        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if raw_value:
            parsed[key] = _parse_frontmatter_value(raw_value)
            continue

        list_items: list[Any] = []
        while idx < len(lines):
            candidate = lines[idx].strip()
            if not candidate:
                idx += 1
                continue
            if candidate.startswith("- "):
                list_items.append(_parse_frontmatter_value(candidate[2:].strip()))
                idx += 1
                continue
            break
        parsed[key] = list_items if list_items else ""

    return parsed


def extract_inline_tags(content: str) -> list[str]:
    tags: list[str] = []
    seen: set[str] = set()
    tag_pattern = re.compile(r"(?<!\w)#([A-Za-z][\w/-]+)")
    for line in strip_frontmatter(content).splitlines():
        if line.lstrip().startswith("#"):
            continue
        for tag in tag_pattern.findall(line):
            normalized = tag.lower()
            if normalized not in seen:
                seen.add(normalized)
                tags.append(normalized)
    return tags


def extract_document_metadata(content: str) -> dict[str, Any]:
    frontmatter = extract_frontmatter(content)
    wikilinks = extract_wikilinks(content)
    tags = _normalize_tags(frontmatter.get("tags")) + extract_inline_tags(content)
    deduped_tags: list[str] = []
    seen_tags: set[str] = set()
    for tag in tags:
        normalized = tag.lower()
        if normalized not in seen_tags:
            seen_tags.add(normalized)
            deduped_tags.append(normalized)
    return {
        "frontmatter": frontmatter,
        "tags": deduped_tags,
        "wikilinks": wikilinks,
    }


@dataclass(frozen=True)
class ChunkingConfig:
    min_chunk_chars: int = 400
    max_chunk_chars: int = 1500
    target_chunk_tokens: int = 480
    max_chunk_tokens: int = 900
    chunk_overlap_chars: int = 220
    chunk_strategy: str = "hybrid"


def strip_frontmatter(content: str) -> str:
    return re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL)


def _parse_frontmatter_value(raw_value: str) -> Any:
    value = raw_value.strip().strip('"\'')
    if raw_value.startswith("[") and raw_value.endswith("]"):
        inner = raw_value[1:-1].strip()
        if not inner:
            return []
        return [_parse_frontmatter_value(part.strip()) for part in inner.split(",")]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered.isdigit():
        return int(lowered)
    return value


def _normalize_tags(raw_tags: Any) -> list[str]:
    if raw_tags is None:
        return []
    if isinstance(raw_tags, str):
        return [raw_tags.strip().lstrip("#")] if raw_tags.strip() else []
    if isinstance(raw_tags, list):
        return [str(tag).strip().lstrip("#") for tag in raw_tags if str(tag).strip()]
    return [str(raw_tags).strip().lstrip("#")]


def estimate_tokens(text: str) -> int:
    cleaned = " ".join(text.split())
    if not cleaned:
        return 0
    return max(1, round(len(cleaned) / 4))


def chunk_markdown(content: str, config: ChunkingConfig | None = None) -> list[str]:
    cfg = config or ChunkingConfig()
    body = strip_frontmatter(content)
    sections = _split_markdown_sections(body)
    if cfg.chunk_strategy == "heading":
        return _chunk_sections_by_heading(sections, cfg)
    if cfg.chunk_strategy == "hybrid":
        return _chunk_sections_hybrid(sections, cfg)
    raise ValueError(f"Unsupported chunk strategy: {cfg.chunk_strategy}")


def chunk_by_heading(content: str, min_chunk_size: int = 400, max_chunk_size: int = 1500) -> list[str]:
    """Compatibility wrapper around the heading chunker."""
    return chunk_markdown(
        content,
        ChunkingConfig(
            min_chunk_chars=min_chunk_size,
            max_chunk_chars=max_chunk_size,
            chunk_strategy="heading",
        ),
    )


def _split_markdown_sections(content: str) -> list[str]:
    parts = re.split(r"(?=^#+\s)", content, flags=re.MULTILINE)
    sections = [part.strip() for part in parts if part.strip()]
    if sections:
        return sections
    stripped = content.strip()
    return [stripped] if stripped else []


def _chunk_sections_by_heading(sections: list[str], config: ChunkingConfig) -> list[str]:
    chunks: list[str] = []
    current_chunk = ""

    for section in sections:
        if _requires_split(section, config):
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            chunks.extend(_split_large_section(section, config))
            continue

        if (
            current_chunk
            and not current_chunk.lstrip().startswith("#")
            and len(current_chunk) + len(section) < config.min_chunk_chars
        ):
            current_chunk = f"{current_chunk}\n\n{section}"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            current_chunk = section

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def _chunk_sections_hybrid(sections: list[str], config: ChunkingConfig) -> list[str]:
    chunks: list[str] = []
    pending: list[str] = []
    pending_chars = 0
    pending_tokens = 0

    for section in sections:
        if _requires_split(section, config):
            lead_in = None
            if pending and _is_short_lead_in(pending, config):
                lead_in = "\n\n".join(pending).strip()
                pending = []
                pending_chars = 0
                pending_tokens = 0
            if pending:
                chunks.append("\n\n".join(pending).strip())
                pending = []
                pending_chars = 0
                pending_tokens = 0
            chunks.extend(_split_large_section(section, config, lead_in=lead_in))
            continue

        section_chars = len(section)
        section_tokens = estimate_tokens(section)
        if pending and (
            pending_chars + section_chars > config.max_chunk_chars
            or pending_tokens + section_tokens > config.target_chunk_tokens
        ):
            chunks.append("\n\n".join(pending).strip())
            pending = []
            pending_chars = 0
            pending_tokens = 0

        pending.append(section)
        pending_chars += section_chars
        pending_tokens += section_tokens

        if pending_chars >= config.min_chunk_chars or pending_tokens >= config.target_chunk_tokens:
            chunks.append("\n\n".join(pending).strip())
            pending = []
            pending_chars = 0
            pending_tokens = 0

    if pending:
        chunks.append("\n\n".join(pending).strip())

    return [chunk for chunk in chunks if chunk.strip()]


def _requires_split(section: str, config: ChunkingConfig) -> bool:
    return (
        len(section) > config.max_chunk_chars
        or estimate_tokens(section) > config.max_chunk_tokens
    )


def _split_large_section(
    section: str,
    config: ChunkingConfig,
    lead_in: str | None = None,
) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", section) if part.strip()]
    if not paragraphs:
        paragraphs = [section.strip()]
    paragraphs = _merge_heading_stub(paragraphs)

    chunks: list[str] = []
    current_parts: list[str] = [lead_in] if lead_in else []
    current_chars = len(lead_in) if lead_in else 0
    current_tokens = estimate_tokens(lead_in) if lead_in else 0

    for paragraph in paragraphs:
        paragraph_chars = len(paragraph)
        paragraph_tokens = estimate_tokens(paragraph)
        lead_in_only = bool(lead_in) and len(current_parts) == 1 and current_parts[0] == lead_in
        if current_parts and not lead_in_only and (
            current_chars + paragraph_chars > config.max_chunk_chars
            or current_tokens + paragraph_tokens > config.max_chunk_tokens
        ):
            chunk_text = "\n\n".join(current_parts).strip()
            chunks.append(chunk_text)
            overlap = _build_overlap(chunk_text, config.chunk_overlap_chars)
            current_parts = [overlap, paragraph] if overlap else [paragraph]
            current_chars = len("\n\n".join(current_parts))
            current_tokens = estimate_tokens("\n\n".join(current_parts))
            continue

        current_parts.append(paragraph)
        current_chars = len("\n\n".join(current_parts))
        current_tokens = estimate_tokens("\n\n".join(current_parts))

    if current_parts:
        chunks.append("\n\n".join(current_parts).strip())

    return [chunk for chunk in chunks if chunk.strip()]


def _is_short_lead_in(parts: list[str], config: ChunkingConfig) -> bool:
    if not parts:
        return False
    combined = "\n\n".join(parts).strip()
    return (
        len(parts) == 1
        and combined.startswith("#")
        and len(combined) < max(80, config.min_chunk_chars)
    )


def _merge_heading_stub(paragraphs: list[str]) -> list[str]:
    if len(paragraphs) < 2:
        return paragraphs
    first = paragraphs[0]
    if first.startswith("#") and "\n" not in first and len(first) < 120:
        return [f"{first}\n\n{paragraphs[1]}"] + paragraphs[2:]
    return paragraphs


def _build_overlap(text: str, overlap_chars: int) -> str:
    if overlap_chars <= 0 or len(text) <= overlap_chars:
        return ""
    overlap = text[-overlap_chars:].strip()
    if not overlap:
        return ""
    overlap = overlap.split("\n\n")[-1].strip()
    return overlap


def find_markdown_files(
    vault_root: Path,
    include_patterns: tuple[str, ...] = ("**/*.md",),
    exclude_patterns: tuple[str, ...] = (".obsidian/**", ".git/**", "__pycache__/**"),
) -> list[Path]:
    """Find markdown files under the configured root honoring include/exclude patterns."""
    files: list[Path] = []
    for path in vault_root.rglob("*"):
        if not path.is_file():
            continue
        rel_path = _relative_markdown_path(path, vault_root)
        if not _matches_any(rel_path, include_patterns):
            continue
        if _matches_any(rel_path, exclude_patterns):
            continue
        files.append(path)
    return sorted(files)


def _relative_markdown_path(file_path: Path, root_path: Path) -> str:
    try:
        return file_path.relative_to(root_path).as_posix()
    except ValueError:
        return file_path.as_posix()


def _matches_any(relative_path: str, patterns: tuple[str, ...]) -> bool:
    if not patterns:
        return False
    return any(_matches_pattern(relative_path, pattern) for pattern in patterns)


def _matches_pattern(relative_path: str, pattern: str) -> bool:
    regex = _glob_to_regex(pattern)
    return re.fullmatch(regex, relative_path) is not None


def _glob_to_regex(pattern: str) -> str:
    pieces: list[str] = ["^"]
    idx = 0
    while idx < len(pattern):
        if pattern[idx:idx + 3] == "**/":
            pieces.append("(?:.*/)?")
            idx += 3
            continue
        if pattern[idx:idx + 2] == "**":
            pieces.append(".*")
            idx += 2
            continue
        char = pattern[idx]
        if char == "*":
            pieces.append("[^/]*")
        elif char == "?":
            pieces.append("[^/]")
        else:
            pieces.append(re.escape(char))
        idx += 1
    pieces.append("$")
    return "".join(pieces)


def compute_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content."""
    content = file_path.read_bytes()
    return hashlib.sha256(content).hexdigest()


def build_note_embedding_text(content: str, title: str | None, path: str | None = None) -> str:
    """Build a note-level embedding text from the full document."""
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", content, flags=re.DOTALL).strip()
    parts = []
    if title:
        parts.append(f"Title {title}")
    if path:
        parts.append(f"Path {path}")
    if body:
        parts.append(body)
    return "\n\n".join(parts).strip()


class Indexer:
    """Main indexing orchestrator."""

    def __init__(
        self,
        db: VectorStore,
        vault_root: Path,
        embedding_client: EmbeddingService | None = None,
        note_embedding_client: EmbeddingService | None = None,
        chunk_embedding_client: EmbeddingService | None = None,
        embedding_host: str | None = None,
        embedding_model: str | None = None,
        min_chunk_chars: int = 1200,
        max_chunk_chars: int = 3200,
        target_chunk_tokens: int = 480,
        max_chunk_tokens: int = 900,
        chunk_overlap_chars: int = 220,
        chunk_strategy: str = "hybrid",
        include_patterns: tuple[str, ...] = ("**/*.md",),
        exclude_patterns: tuple[str, ...] = (".obsidian/**", ".git/**", "__pycache__/**"),
    ):
        self.db = db
        self.vault_root = Path(vault_root)
        default_embedder = embedding_client or EmbeddingClient(
            base_url=embedding_host or "http://127.0.0.1:11434",
            model=embedding_model or "nomic-embed-text:v1.5",
        )
        self.note_embedder = note_embedding_client or default_embedder
        self.chunk_embedder = chunk_embedding_client or default_embedder
        self.chunking_config = ChunkingConfig(
            min_chunk_chars=min_chunk_chars,
            max_chunk_chars=max_chunk_chars,
            target_chunk_tokens=target_chunk_tokens,
            max_chunk_tokens=max_chunk_tokens,
            chunk_overlap_chars=chunk_overlap_chars,
            chunk_strategy=chunk_strategy,
        )
        self.include_patterns = include_patterns
        self.exclude_patterns = exclude_patterns

    def index_file(self, file_path: Path) -> dict[str, Any]:
        """Index a single markdown file.
        
        Returns stats about the indexing operation.
        """
        content = file_path.read_text(encoding="utf-8")
        content_hash = compute_hash(file_path)
        title = extract_title(content)
        
        # Relative path for storage
        rel_path = _relative_markdown_path(file_path, self.vault_root)
        
        # Check if already indexed with same hash
        existing = self.db.get_document(rel_path)
        if existing and existing["content_hash"] == content_hash:
            return {
                "status": "unchanged",
                "path": rel_path,
                "chunks_created": 0
            }
        
        # Upsert document
        metadata = extract_document_metadata(content)
        doc_id = self.db.upsert_document(
            path=rel_path,
            content_hash=content_hash,
            title=title,
            metadata=metadata,
        )
        
        # Delete old chunks if updating
        if existing:
            self.db.delete_chunks(doc_id)
        
        # Chunk and embed
        chunks = chunk_markdown(content, self.chunking_config)
        note_text = build_note_embedding_text(content, title, rel_path)

        note_embedding = self.note_embedder.embed(note_text)
        self.db.insert_chunk(
            doc_id=doc_id,
            chunk_index=0,
            chunk_text=note_text,
            embedding=note_embedding,
            scope="note",
        )

        chunks_created = 0

        embeddings = self.chunk_embedder.embed_document_chunks(
            chunks,
            document_title=title,
            document_path=rel_path,
        )

        for idx, (chunk_text, embedding) in enumerate(zip(chunks, embeddings)):
            if len(chunk_text.strip()) < 20:
                continue  # Skip tiny chunks

            self.db.insert_chunk(
                doc_id=doc_id,
                chunk_index=idx,
                chunk_text=chunk_text,
                embedding=embedding,
                scope="chunk",
            )
            chunks_created += 1
        
        return {
            "status": "indexed",
            "path": rel_path,
            "title": title,
            "chunks_created": chunks_created
        }

    def index_all(self) -> dict[str, Any]:
        """Index all markdown files in the configured root.
        
        Returns aggregate stats.
        """
        files = find_markdown_files(
            self.vault_root,
            include_patterns=self.include_patterns,
            exclude_patterns=self.exclude_patterns,
        )
        
        stats = {
            "total_files": len(files),
            "indexed": 0,
            "unchanged": 0,
            "errors": 0,
            "total_chunks": 0
        }
        
        for file_path in files:
            try:
                result = self.index_file(file_path)
                
                if result["status"] == "indexed":
                    stats["indexed"] += 1
                    stats["total_chunks"] += result["chunks_created"]
                else:
                    stats["unchanged"] += 1
                    
            except Exception as e:
                stats["errors"] += 1
                print(f"Error indexing {file_path}: {e}")
        
        return stats


def main():
    """CLI entry point for synapse-index."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Index a markdown folder for semantic search")
    parser.add_argument(
        "--config",
        default=os.environ.get("SYNAPSE_CONFIG", "config/synapse.toml"),
        help="Path to Synapse TOML config (defaults to config/synapse.toml)"
    )
    parser.add_argument(
        "--vault-root",
        default=None,
        help="Path to vault root"
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
        "--model",
        default=None,
        help="Override embedding model"
    )
    parser.add_argument(
        "--base-url",
        "--ollama-host",
        dest="base_url",
        default=None,
        help="Override embedding endpoint base URL"
    )
    
    args = parser.parse_args()
    settings = load_settings(args.config)
    note_provider = settings.embedding_provider(args.provider)
    chunk_provider = settings.embedding_provider(args.chunk_provider or settings.index.contextual_provider)
    if note_provider.dimensions != chunk_provider.dimensions:
        raise ValueError(
            f"Note provider dimension {note_provider.dimensions} must match chunk provider dimension {chunk_provider.dimensions}"
        )
    model = args.model or note_provider.model
    base_url = args.base_url or note_provider.base_url
    
    vault_root = Path(args.vault_root or settings.vault.root).expanduser()
    db_path = Path(args.db or settings.database.path).expanduser()
    
    print(f"🧠 Synapse Indexer")
    print(f"   Vault Root: {vault_root}")
    print(f"   Database: {db_path}")
    print(f"   Note Provider: {note_provider.name} ({note_provider.type})")
    print(f"   Chunk Provider: {chunk_provider.name} ({chunk_provider.type})")
    print(f"   Endpoint: {base_url}")
    print(f"   Model: {model}")
    print(f"   Dimensions: {note_provider.dimensions}")
    print()
    
    # Initialize
    db = create_vector_store(settings, db_path=db_path, embedding_dim=note_provider.dimensions)
    db.initialize()
    
    indexer = Indexer(
        db=db,
        vault_root=vault_root,
        note_embedding_client=EmbeddingClient(
            provider_type=note_provider.type,
            base_url=base_url,
            model=model,
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
        min_chunk_chars=settings.index.min_chunk_chars,
        max_chunk_chars=settings.index.max_chunk_chars,
        target_chunk_tokens=settings.index.target_chunk_tokens,
        max_chunk_tokens=settings.index.max_chunk_tokens,
        chunk_overlap_chars=settings.index.chunk_overlap_chars,
        chunk_strategy=settings.index.chunk_strategy,
        include_patterns=settings.vault.include,
        exclude_patterns=settings.vault.exclude,
    )
    
    # Run indexing
    print("📚 Scanning vault root...")
    stats = indexer.index_all()
    
    print()
    print(f"✅ Complete!")
    print(f"   Files: {stats['total_files']}")
    print(f"   Indexed: {stats['indexed']}")
    print(f"   Unchanged: {stats['unchanged']}")
    print(f"   Chunks: {stats['total_chunks']}")
    if stats['errors'] > 0:
        print(f"   ⚠️  Errors: {stats['errors']}")
    
    db.close()


if __name__ == "__main__":
    main()
