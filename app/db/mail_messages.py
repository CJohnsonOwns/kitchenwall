"""The local cache of message headers/flags that the inbox is drawn from."""
from .badges import UNREAD_SQL
from .core import get_conn


# One row per message we know about in the Inbox, Sent or Starred views.
# `uid` is the Gmail message id (API accounts) or X-GM-MSGID (app-password /
# IMAP accounts); both are stable for the life of the message. `imap_uid` is
# the message's UID in the IMAP "All Mail" folder, used to act on it.

MESSAGE_FIELDS = (
    "message_id", "thread_id", "sender", "to_addrs", "subject", "date_header", "received_at",
    "is_read", "snippet", "in_inbox", "in_sent", "is_starred", "is_trashed", "imap_uid",
)
FLAG_FIELDS = ("is_read", "in_inbox", "in_sent", "is_starred", "is_trashed")

VIEW_WHERE = {
    "inbox": "m.in_inbox = 1 AND m.is_trashed = 0",
    "starred": "m.is_starred = 1 AND m.is_trashed = 0",
    "sent": "m.in_sent = 1 AND m.is_trashed = 0",
}


def upsert_messages(account_id: int, rows: list[dict]):
    """Insert or fully update message rows (each dict has 'uid' plus MESSAGE_FIELDS)."""
    if not rows:
        return
    conn = get_conn()
    try:
        cols = ", ".join(MESSAGE_FIELDS)
        marks = ", ".join("?" for _ in MESSAGE_FIELDS)
        updates = ", ".join(
            f"{c} = COALESCE(excluded.{c}, email_messages.{c})" if c in ("snippet", "imap_uid", "to_addrs")
            else f"{c} = excluded.{c}"
            for c in MESSAGE_FIELDS
        )
        conn.executemany(
            f"INSERT INTO email_messages (account_id, uid, {cols}) VALUES (?, ?, {marks}) "
            f"ON CONFLICT(account_id, uid) DO UPDATE SET {updates}",
            [(account_id, r["uid"], *[r.get(c) for c in MESSAGE_FIELDS]) for r in rows],
        )
        conn.commit()
    finally:
        conn.close()


def update_message_flags(account_id: int, uids: list[str], **flags):
    """Set flag columns (is_read, in_inbox, ...) on the given cached messages."""
    bad = set(flags) - set(FLAG_FIELDS) - {"imap_uid"}
    if bad:
        raise ValueError(f"not a flag: {bad}")
    if not uids or not flags:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k} = ?" for k in flags)
        conn.executemany(
            f"UPDATE email_messages SET {cols} WHERE account_id = ? AND uid = ?",
            [(*flags.values(), account_id, u) for u in uids],
        )
        conn.commit()
    finally:
        conn.close()


def set_flags_per_message(account_id: int, updates: dict[str, dict]):
    """{uid: {flag: value}} — different values per message, one transaction."""
    if not updates:
        return
    bad = {k for flags in updates.values() for k in flags} - set(FLAG_FIELDS) - {"imap_uid"}
    if bad:  # column names go into the SQL text, so only known ones
        raise ValueError(f"unknown message fields: {bad}")
    conn = get_conn()
    try:
        for uid, flags in updates.items():
            cols = ", ".join(f"{k} = ?" for k in flags)
            conn.execute(
                f"UPDATE email_messages SET {cols} WHERE account_id = ? AND uid = ?",
                (*flags.values(), account_id, uid),
            )
        conn.commit()
    finally:
        conn.close()


def delete_messages(account_id: int, uids):
    uids = list(uids)
    if not uids:
        return
    conn = get_conn()
    try:
        conn.executemany(
            "DELETE FROM email_messages WHERE account_id = ? AND uid = ?", [(account_id, u) for u in uids]
        )
        conn.commit()
    finally:
        conn.close()


def delete_account_messages(account_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM email_messages WHERE account_id = ?", (account_id,))
        conn.execute("DELETE FROM email_bodies WHERE account_id = ?", (account_id,))
        conn.commit()
    finally:
        conn.close()


def cached_messages(account_id: int) -> dict[str, dict]:
    """uid -> row dict for every cached message of one account."""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM email_messages WHERE account_id = ?", (account_id,)).fetchall()
        return {r["uid"]: dict(r) for r in rows}
    finally:
        conn.close()


def get_message(account_id: int, uid: str):
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT m.*, a.email_address, a.display_name FROM email_messages m "
            "JOIN email_accounts a ON a.id = m.account_id WHERE m.account_id = ? AND m.uid = ?",
            (account_id, uid),
        ).fetchone()
    finally:
        conn.close()


def any_in_inbox(account_id: int, uids: list[str]) -> bool:
    """Is any of these messages in the inbox? (One query, for Delete's Undo.)"""
    if not uids:
        return False
    conn = get_conn()
    try:
        marks = ",".join("?" for _ in uids)
        return conn.execute(
            f"SELECT 1 FROM email_messages WHERE account_id = ? AND uid IN ({marks}) AND in_inbox = 1 LIMIT 1",
            (account_id, *uids),
        ).fetchone() is not None
    finally:
        conn.close()


def get_message_by_row(row_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM email_messages WHERE id = ?", (row_id,)).fetchone()
    finally:
        conn.close()


def list_view_messages(view: str, account_id: int | None = None, limit: int = 200):
    where = VIEW_WHERE.get(view, VIEW_WHERE["inbox"])
    params: list = []
    if account_id:
        where += " AND m.account_id = ?"
        params.append(account_id)
    conn = get_conn()
    try:
        return conn.execute(
            f"""
            SELECT m.*, a.email_address, a.display_name
            FROM email_messages m
            JOIN email_accounts a ON a.id = m.account_id
            WHERE {where}
            ORDER BY COALESCE(m.received_at, m.date_header) DESC
            LIMIT ?
            """,
            (*params, limit),
        ).fetchall()
    finally:
        conn.close()


def oldest_in_view(account_id: int, view: str):
    """(received_at, imap_uid) of the oldest cached message in a view, or (None, None)."""
    conn = get_conn()
    try:
        row = conn.execute(
            f"SELECT MIN(m.received_at) AS t, MIN(m.imap_uid) AS u FROM email_messages m "
            f"WHERE m.account_id = ? AND {VIEW_WHERE[view]}",
            (account_id,),
        ).fetchone()
        return (row["t"], row["u"]) if row else (None, None)
    finally:
        conn.close()


def count_unread_messages() -> int:
    """Unread messages in the inbox (drives the tab badge)."""
    conn = get_conn()
    try:
        return conn.execute(UNREAD_SQL).fetchone()[0]
    finally:
        conn.close()
