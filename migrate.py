"""
One-time migration: JSON files → SQLite (hatebot.db).

Run ONCE before starting the bot with the new database.py backend:

    python migrate.py

Safe to run multiple times — existing DB data is overwritten with the JSON
file contents, so run it before you switch over, not after.
"""

import os
import json
import sys

ECONOMY_FILE = "economy.json"
COUNTER_FILE = "roast_count.json"
ROAST_LOG_FILE = "roast_log.json"


def main():
    from database import init_db, save_economy, save_count, _lock, _conn

    init_db()
    print("Database initialised.")

    # ── Economy ───────────────────────────────────────────────────────────────
    if os.path.exists(ECONOMY_FILE):
        with open(ECONOMY_FILE) as f:
            eco = json.load(f)
        save_economy(eco)
        print(f"Migrated {ECONOMY_FILE}  ({len(json.dumps(eco))} bytes)")
    else:
        print(f"  {ECONOMY_FILE} not found — skipping")

    # ── Roast counter ─────────────────────────────────────────────────────────
    if os.path.exists(COUNTER_FILE):
        with open(COUNTER_FILE) as f:
            count = json.load(f).get("count", 0)
        save_count(count)
        print(f"Migrated {COUNTER_FILE}  (count={count})")
    else:
        print(f"  {COUNTER_FILE} not found — skipping")

    # ── Roast log ─────────────────────────────────────────────────────────────
    if os.path.exists(ROAST_LOG_FILE):
        with open(ROAST_LOG_FILE) as f:
            log = json.load(f)
        if log:
            with _lock, _conn() as c:
                c.execute("DELETE FROM roast_log")
                c.executemany(
                    "INSERT INTO roast_log (timestamp) VALUES (?)",
                    [(ts,) for ts in log],
                )
            print(f"Migrated {ROAST_LOG_FILE}  ({len(log)} entries)")
        else:
            print(f"  {ROAST_LOG_FILE} is empty — skipping")
    else:
        print(f"  {ROAST_LOG_FILE} not found — skipping")

    print("\nMigration complete. You can now start the bot.")
    print("Keep the JSON files as backups until you've verified everything works.")


if __name__ == "__main__":
    main()
