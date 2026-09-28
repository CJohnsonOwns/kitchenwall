"""Cache of fetched message bodies (the newest BODY_CACHE_KEEP are kept)."""
from .core import get_conn


# messages. Kept separate so the list queries stay light.

BODY_CACHE_KEEP = 400


def get_body(account_id: int, uid: str) -> str | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT data_json FROM email_bodies WHERE account_id = ? AND uid = ?", (account_id, uid)
        ).fetchone()
        return row["data_json"] if row else None
    finally:
        conn.close()


def bodies_present(account_id: int, uids: list[str]) -> set[str]:
    if not uids:
        return set()
    conn = get_conn()
    try:
        marks = ",".join("?" for _ in uids)
        rows = conn.execute(
            f"SELECT uid FROM email_bodies WHERE account_id = ? AND uid IN ({marks})", (account_id, *uids)
        ).fetchall()
        return {r["uid"] for r in rows}
    finally:
        conn.close()


def put_body(account_id: int, uid: str, data_json: str):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO email_bodies (account_id, uid, data_json, fetched_at) VALUES (?, ?, ?, datetime('now')) "
            "ON CONFLICT(account_id, uid) DO UPDATE SET data_json = excluded.data_json, fetched_at = excluded.fetched_at",
            (account_id, uid, data_json),
        )
        conn.commit()
    finally:
        conn.close()


def prune_bodies(keep: int = BODY_CACHE_KEEP):
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM email_bodies WHERE rowid NOT IN "
            "(SELECT rowid FROM email_bodies ORDER BY fetched_at DESC LIMIT ?)",
            (keep,),
        )
        conn.commit()
    finally:
        conn.close()
