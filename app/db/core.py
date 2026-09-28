"""Where the database lives, how connections are opened, and start-up (schema + migrations)."""
import os
import sqlite3
from pathlib import Path

from .schema import INDEXES, MIGRATIONS, SCHEMA

# HOUSEHOLD_DB_PATH lets a local test run point at a throwaway copy of the database.
DB_PATH = Path(
    os.environ.get("HOUSEHOLD_DB_PATH")
    or Path(__file__).resolve().parents[2] / "data" / "household.db"
)


def get_conn() -> sqlite3.Connection:
    # timeout: wait up to 5 s for another writer instead of failing ("database is locked").
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # With WAL (set once in init_db), NORMAL is crash-safe and skips an fsync per write.
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, coltype in MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}")
    conn.commit()


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_conn()
    try:
        # Write-ahead log: readers (pages, the nightly backup, the deploy bridge)
        # never wait for a writer. Stored in the file, so this sticks.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        conn.commit()
        _run_migrations(conn)
        conn.executescript(INDEXES)
        _ensure_a_list(conn)
    finally:
        conn.close()


def _ensure_a_list(conn: sqlite3.Connection) -> None:
    """There's always at least one list, and every item belongs to one
    (items from before multiple lists go on the first)."""
    if conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] == 0:
        conn.execute("INSERT INTO lists (name, position) VALUES ('Shopping', 0)")
    first = conn.execute("SELECT id FROM lists ORDER BY position, id LIMIT 1").fetchone()[0]
    conn.execute("UPDATE list_items SET list_id = ? WHERE list_id IS NULL "
                 "OR list_id NOT IN (SELECT id FROM lists)", (first,))
    conn.commit()
