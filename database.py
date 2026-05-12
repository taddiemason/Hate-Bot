"""
SQLite-backed persistence layer.

Replaces the flat-JSON file approach (economy.json, roast_count.json,
roast_log.json) with a single WAL-mode SQLite database.  A threading.Lock
serialises all writes so concurrent Discord events can't corrupt state.

Public API (same signatures as the original bot.py helpers):
    init_db()
    load_economy() -> dict
    save_economy(data: dict)
    load_count() -> int
    save_count(count: int)
    log_roast()
    get_weekly_recap() -> (int | None, list[str])
"""

import os
import json
import shutil
import sqlite3
import threading
import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))


def _writable_dir(path: str) -> bool:
    """True if `path` is an existing directory we can write into.

    SQLite in WAL mode needs to create -wal and -shm sidecar files alongside
    the database, so the directory itself must be writable — not just the
    database file. os.access checks the effective UID, which is what
    sqlite3 will use.
    """
    return os.path.isdir(path) and os.access(path, os.W_OK | os.X_OK)


def _resolve_db_path() -> str:
    env = os.getenv("DB_PATH")
    if env:
        return os.path.abspath(os.path.expanduser(env))

    primary = os.path.join(_HERE, "hatebot.db")
    if _writable_dir(_HERE):
        return primary

    # The install directory isn't writable by the bot's runtime user (common
    # when setup.sh was run with sudo, or the repo is owned by a different
    # account than the systemd User=). Fall back to a per-user data dir.
    xdg = os.getenv("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    fallback_dir = os.path.join(xdg, "hatebot")
    os.makedirs(fallback_dir, exist_ok=True)
    fallback = os.path.join(fallback_dir, "hatebot.db")

    if os.path.exists(primary) and not os.path.exists(fallback):
        try:
            shutil.copy2(primary, fallback)
        except OSError as e:
            print(f"[database] WARN: couldn't migrate {primary} -> {fallback}: {e}")
    return fallback


DB_PATH = _resolve_db_path()
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
if not _writable_dir(os.path.dirname(DB_PATH)):
    raise RuntimeError(
        f"Database directory is not writable: {os.path.dirname(DB_PATH)!r}. "
        "Set DB_PATH to a writable location, or fix permissions on the install directory."
    )
print(f"[database] Using DB at {DB_PATH}")

_lock = threading.Lock()

_DEFAULT_ECONOMY = {
    "balances": {},
    "bounties": [],
    "insurance_expires": None,
    "pending_upgrades": {},
    "inventory": {},
    "market_listings": [],
    "slow_clap_pending": 0,
    "next_bounty_id": 1,
    "next_listing_id": 1,
    "shop_rotation": None,
    "shop_rotation_expires": None,
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS economy (
                id   INTEGER PRIMARY KEY CHECK (id = 1),
                data TEXT    NOT NULL
            );
            CREATE TABLE IF NOT EXISTS roast_count (
                id    INTEGER PRIMARY KEY CHECK (id = 1),
                count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS roast_log (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT    NOT NULL
            );
        """)


# ── Economy ───────────────────────────────────────────────────────────────────

def load_economy() -> dict:
    with _lock, _conn() as c:
        row = c.execute("SELECT data FROM economy WHERE id = 1").fetchone()
    if row:
        return json.loads(row[0])
    return dict(_DEFAULT_ECONOMY)


def save_economy(data: dict) -> None:
    payload = json.dumps(data)
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO economy (id, data) VALUES (1, ?)"
            " ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (payload,),
        )


# ── Roast counter ─────────────────────────────────────────────────────────────

def load_count() -> int:
    with _lock, _conn() as c:
        row = c.execute("SELECT count FROM roast_count WHERE id = 1").fetchone()
    return row[0] if row else 0


def save_count(count: int) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO roast_count (id, count) VALUES (1, ?)"
            " ON CONFLICT(id) DO UPDATE SET count = excluded.count",
            (count,),
        )


# ── Roast log ─────────────────────────────────────────────────────────────────

def log_roast() -> None:
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with _lock, _conn() as c:
        c.execute("INSERT INTO roast_log (timestamp) VALUES (?)", (now,))


def get_weekly_recap():
    with _lock, _conn() as c:
        rows = c.execute("SELECT timestamp FROM roast_log ORDER BY id").fetchall()
        if not rows:
            return None, []
        log = [r[0] for r in rows]
        c.execute("DELETE FROM roast_log")
    return len(log), log
