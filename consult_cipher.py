#!/usr/bin/env python3
import asyncio
from pathlib import Path
from synapse.cipher_service import CipherDeps, CipherService, SuggestChunkingStrategyRequest
from synapse.settings import load_settings

async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Ask Cipher for chunking guidance")
    parser.add_argument("--config", default=None, help="Path to Synapse TOML config")
    parser.add_argument(
        "--model-info",
        default="perplexity-ai/pplx-embed-context-v1-4b, 2560 dimensions, 32k context",
        help="Model capabilities to hand to Cipher",
    )
    args = parser.parse_args()

    settings = load_settings(args.config)
    vault_root = settings.vault.root_path()
    synapse_db = settings.database.db_path()
    deps = CipherDeps(vault_root=vault_root, synapse_db=synapse_db)

    service = CipherService()
    strategy = await service.handle(
        SuggestChunkingStrategyRequest(model_info=args.model_info),
        deps,
    )
    
    print("\n🕵️ **Cipher's Indexing Strategy**")
    print(f"Max Chunk Size: {strategy.max_chunk_size} chars")
    print(f"Min Chunk Size: {strategy.min_chunk_size} chars")
    print(f"Rationale: {strategy.rationale}")

if __name__ == "__main__":
    asyncio.run(main())
