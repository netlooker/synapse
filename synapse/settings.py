"""Application settings for Synapse."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import SynapseNotFoundError


DEFAULT_CONFIG_PATHS = (
    Path("config/synapse.toml"),
    Path("synapse.toml"),
)
DEFAULT_EXAMPLE_CONFIG_PATH = Path("config/synapse.example.toml")
DEFAULT_DB_PATH = "~/notes/.synapse.sqlite"
DEFAULT_VAULT_PATH = "~/notes"


@dataclass(frozen=True)
class VaultSettings:
    root: str = DEFAULT_VAULT_PATH
    include: tuple[str, ...] = ("**/*.md",)
    exclude: tuple[str, ...] = (".obsidian/**", ".git/**", "__pycache__/**")

    def root_path(self) -> Path:
        return Path(self.root).expanduser()


@dataclass(frozen=True)
class IndexSettings:
    min_chunk_chars: int = 1200
    max_chunk_chars: int = 3200
    target_chunk_tokens: int = 480
    max_chunk_tokens: int = 900
    chunk_overlap_chars: int = 220
    chunk_strategy: str = "hybrid"
    provider: str = "default"
    contextual_provider: str = "contextual"


@dataclass(frozen=True)
class DatabaseSettings:
    path: str = DEFAULT_DB_PATH
    extension_path: str | None = None

    def db_path(self) -> Path:
        return Path(self.path).expanduser()

    def extension_file(self) -> Path | None:
        if not self.extension_path:
            return None
        return Path(self.extension_path).expanduser()


@dataclass(frozen=True)
class ProviderSettings:
    name: str
    type: str = "ollama"
    model: str = "nomic-embed-text:v1.5"
    base_url: str = "http://127.0.0.1:11434"
    dimensions: int = 768
    encoding_format: str = "float"
    context_strategy: str = "auto"
    api_key_env: str | None = None

    def api_key(self) -> str | None:
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)


@dataclass(frozen=True)
class SearchSettings:
    provider: str = "default"
    limit: int = 5
    mode: str = "research"
    candidate_multiplier: int = 4
    note_weight: float = 0.4
    chunk_weight: float = 0.6


@dataclass(frozen=True)
class VectorStoreSettings:
    type: str = "sqlite_vec"


@dataclass(frozen=True)
class CipherSettings:
    default_timeout_seconds: float = 45.0
    explain_timeout_seconds: float = 45.0
    chunking_timeout_seconds: float = 30.0
    stub_review_timeout_seconds: float = 45.0


@dataclass(frozen=True)
class AppSettings:
    config_path: Path | None = None
    vault: VaultSettings = field(default_factory=VaultSettings)
    index: IndexSettings = field(default_factory=IndexSettings)
    database: DatabaseSettings = field(default_factory=DatabaseSettings)
    search: SearchSettings = field(default_factory=SearchSettings)
    vector_store: VectorStoreSettings = field(default_factory=VectorStoreSettings)
    cipher: CipherSettings = field(default_factory=CipherSettings)
    embedding_providers: dict[str, ProviderSettings] = field(default_factory=dict)

    def embedding_provider(self, name: str | None = None) -> ProviderSettings:
        provider_name = name or self.index.provider
        provider = self.embedding_providers.get(provider_name)
        if provider:
            return provider
        if self.embedding_providers:
            return next(iter(self.embedding_providers.values()))
        return ProviderSettings(name="default")

    def contextual_embedding_provider(self) -> ProviderSettings:
        return self.embedding_provider(self.index.contextual_provider)


def load_settings(config_path: str | Path | None = None) -> AppSettings:
    """Load settings from TOML with environment-based overrides."""
    resolved_config_path, require_exists = _resolve_config_path(config_path)
    raw = _load_toml(resolved_config_path, require_exists=require_exists)

    vault = raw.get("vault", {})
    index = raw.get("index", {})
    database = raw.get("database", {})
    search = raw.get("search", {})
    vector_store = raw.get("vector_store", {})
    cipher = raw.get("cipher", {})
    providers = raw.get("providers", {}).get("embeddings", {})

    embedding_providers = {
        name: ProviderSettings(
            name=name,
            type=provider.get("type", "ollama"),
            model=provider.get("model", "nomic-embed-text:v1.5"),
            base_url=provider.get("base_url", "http://127.0.0.1:11434"),
            dimensions=int(provider.get("dimensions", 768)),
            encoding_format=provider.get("encoding_format", "float"),
            context_strategy=provider.get("context_strategy", "auto"),
            api_key_env=provider.get("api_key_env"),
        )
        for name, provider in providers.items()
    }

    settings = AppSettings(
        config_path=resolved_config_path if resolved_config_path.exists() else None,
        vault=VaultSettings(
            root=os.environ.get(
                "SYNAPSE_VAULT_PATH",
                vault.get("root", DEFAULT_VAULT_PATH),
            ),
            include=tuple(vault.get("include", ("**/*.md",))),
            exclude=tuple(vault.get("exclude", (".obsidian/**", ".git/**", "__pycache__/**"))),
        ),
        index=IndexSettings(
            min_chunk_chars=int(index.get("min_chunk_chars", 1200)),
            max_chunk_chars=int(index.get("max_chunk_chars", 3200)),
            target_chunk_tokens=int(index.get("target_chunk_tokens", 480)),
            max_chunk_tokens=int(index.get("max_chunk_tokens", 900)),
            chunk_overlap_chars=max(0, int(index.get("chunk_overlap_chars", 220))),
            chunk_strategy=index.get("chunk_strategy", "hybrid"),
            provider=os.environ.get("SYNAPSE_EMBEDDING_PROVIDER", index.get("provider", "default")),
            contextual_provider=index.get("contextual_provider", "contextual"),
        ),
        database=DatabaseSettings(
            path=os.environ.get("SYNAPSE_DB", database.get("path", DEFAULT_DB_PATH)),
            extension_path=database.get("extension_path"),
        ),
        search=SearchSettings(
            provider=os.environ.get(
                "SYNAPSE_EMBEDDING_PROVIDER",
                search.get("provider", index.get("provider", "default")),
            ),
            limit=int(search.get("limit", 5)),
            mode=search.get("mode", "research"),
            candidate_multiplier=max(1, int(search.get("candidate_multiplier", 4))),
            note_weight=float(search.get("note_weight", 0.4)),
            chunk_weight=float(search.get("chunk_weight", 0.6)),
        ),
        vector_store=VectorStoreSettings(
            type=vector_store.get("type", "sqlite_vec"),
        ),
        cipher=CipherSettings(
            default_timeout_seconds=float(cipher.get("default_timeout_seconds", 45.0)),
            explain_timeout_seconds=float(
                cipher.get("explain_timeout_seconds", cipher.get("default_timeout_seconds", 45.0))
            ),
            chunking_timeout_seconds=float(
                cipher.get("chunking_timeout_seconds", cipher.get("default_timeout_seconds", 45.0))
            ),
            stub_review_timeout_seconds=float(
                cipher.get("stub_review_timeout_seconds", cipher.get("default_timeout_seconds", 45.0))
            ),
        ),
        embedding_providers=embedding_providers,
    )

    return _apply_provider_env_overrides(settings)


def _apply_provider_env_overrides(settings: AppSettings) -> AppSettings:
    if not settings.embedding_providers:
        return settings

    override_model = os.environ.get("SYNAPSE_EMBEDDING_MODEL")
    override_base_url = os.environ.get("SYNAPSE_EMBEDDING_BASE_URL")
    override_dimensions = os.environ.get("SYNAPSE_EMBEDDING_DIMENSIONS")
    if not any((override_model, override_base_url, override_dimensions)):
        return settings

    provider_name = settings.index.provider
    updated = dict(settings.embedding_providers)
    original = updated.get(provider_name, ProviderSettings(name=provider_name))
    updated[provider_name] = ProviderSettings(
        name=original.name,
        type=original.type,
        model=override_model or original.model,
        base_url=override_base_url or original.base_url,
        dimensions=int(override_dimensions or original.dimensions),
        encoding_format=original.encoding_format,
        context_strategy=original.context_strategy,
        api_key_env=original.api_key_env,
    )
    return AppSettings(
        config_path=settings.config_path,
        vault=settings.vault,
        index=settings.index,
        database=settings.database,
        search=settings.search,
        vector_store=settings.vector_store,
        cipher=settings.cipher,
        embedding_providers=updated,
    )


def _load_toml(config_path: Path, *, require_exists: bool = False) -> dict[str, Any]:
    if not config_path.exists():
        if require_exists:
            raise SynapseNotFoundError(f"Synapse config not found: {config_path}")
        return {}
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def _resolve_config_path(config_path: str | Path | None) -> tuple[Path, bool]:
    if config_path:
        return Path(config_path), True

    env_path = os.environ.get("SYNAPSE_CONFIG")
    if env_path:
        return Path(env_path), True

    for candidate in DEFAULT_CONFIG_PATHS:
        if candidate.exists():
            return candidate, False

    return DEFAULT_CONFIG_PATHS[0], False
