#!/usr/bin/env python3
import asyncio
import json
import logging
from pathlib import Path
from synapse.cipher_service import AuditVaultRequest, CipherDeps, CipherService
from synapse.settings import load_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("synapse.maintain")

STATE_FILE = Path("~/.openclaw/workspace/memory/maintenance-state.json").expanduser()

def get_pulse_count():
    if not STATE_FILE.exists():
        return 0
    try:
        with open(STATE_FILE, 'r') as f:
            data = json.load(f)
            return data.get("pulse_count", 0)
    except:
        return 0

def save_pulse_count(count):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, 'w') as f:
        json.dump({"pulse_count": count}, f)

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--repair", action="store_true", help="Fix broken links and create stubs")
    parser.add_argument("--config", default=None, help="Path to Synapse TOML config")
    args = parser.parse_args()

    count = get_pulse_count()
    count += 1
    save_pulse_count(count)

    # Trigger maintenance every 2nd heartbeat OR if manual repair requested
    if args.repair or count % 2 == 0:
        logger.info(f"🌑 [Pulse {count}] Running Cipher Maintenance (repair={args.repair})...")
        
        settings = load_settings(args.config)
        cortex_path = settings.vault.root_path()
        synapse_db = settings.database.db_path()
        deps = CipherDeps(cortex_path=cortex_path, synapse_db=synapse_db)

        service = CipherService()
        report = await service.handle(
            AuditVaultRequest(mode="repair" if args.repair else "audit"),
            deps,
        )

        print(f"\n🕵️ **Cipher Maintenance Report**")
        print(report.summary)
        for broken_link in report.broken_links[:20]:
            print(f"- {Path(broken_link['source_path']).name} -> [[{broken_link['target_link']}]]")
    else:
        logger.info(f"🌑 [Pulse {count}] Maintenance skipped (Next pulse).")
        # Ensure we at least output something for the heartbeat log
        print("HEARTBEAT_OK")

if __name__ == "__main__":
    asyncio.run(main())
