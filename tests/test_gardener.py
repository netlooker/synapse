from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel

from synapse.cipher_service import CipherService
from synapse.db import Database
from synapse.gardener import cultivate
from synapse.settings import load_settings


def _seed_broken_link_db(db_path: Path) -> None:
    db = Database(db_path, embedding_dim=4)
    db.initialize()
    doc_id = db.upsert_document("vault/source.md", "hash:source", "Source")
    db.insert_chunk(
        doc_id,
        0,
        "# Source\n\nLinks to [[Semantic Memory]] and [[x]]",
        [1.0, 0.0, 0.0, 0.0],
    )
    db.conn.commit()
    db.close()


@pytest.mark.asyncio
async def test_gardener_dry_run_only_writes_approved_when_apply(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "source.md").write_text(
        "# Source\n\nLinks to [[Semantic Memory]] and [[x]]",
        encoding="utf-8",
    )
    db_path = tmp_path / "synapse.sqlite"
    _seed_broken_link_db(db_path)

    model = TestModel(
        custom_output_text=(
            '{"reviews": ['
            '{"target_link": "Semantic Memory", "action": "create_stub", '
            '"rationale": "Useful concept.", "confidence": 0.91, '
            '"suggested_path": "entities/Semantic Memory.md"}, '
            '{"target_link": "x", "action": "skip", '
            '"rationale": "Too vague.", "confidence": 0.20, '
            '"suggested_path": "entities/x.md"}'
            "]}"
        )
    )

    await cultivate(
        db_path=db_path,
        cortex_path=vault,
        apply=False,
        settings=load_settings("config/synapse.example.toml"),
        embedding_dim=4,
        cipher_service=CipherService(model=model),
    )
    assert not (vault / "entities" / "Semantic Memory.md").exists()

    await cultivate(
        db_path=db_path,
        cortex_path=vault,
        apply=True,
        settings=load_settings("config/synapse.example.toml"),
        embedding_dim=4,
        cipher_service=CipherService(model=model),
    )
    assert (vault / "entities" / "Semantic Memory.md").exists()
    assert not (vault / "entities" / "x.md").exists()
