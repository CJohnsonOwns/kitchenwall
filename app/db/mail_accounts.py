"""Connected Gmail accounts (tokens and passwords are stored encrypted by the caller)."""
from .core import get_conn


_ACCOUNT_FIELDS = {"scopes", "history_id", "imap_uidvalidity", "sync_version", "last_synced_at", "display_name"}


def list_email_accounts():
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM email_accounts ORDER BY created_at ASC, id ASC"
        ).fetchall()
    finally:
        conn.close()


def get_email_account(account_id: int):
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM email_accounts WHERE id = ?", (account_id,)
        ).fetchone()
    finally:
        conn.close()


def create_email_account(
    email_address: str,
    display_name: str,
    app_password_enc: bytes,
    imap_host: str = "imap.gmail.com",
    smtp_host: str = "smtp.gmail.com",
):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO email_accounts (email_address, display_name, app_password_enc, imap_host, smtp_host, sync_version) "
            "VALUES (?, ?, ?, ?, ?, 1)",
            (email_address, display_name, app_password_enc, imap_host, smtp_host),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def upsert_oauth_account(
    email_address: str,
    display_name: str,
    refresh_token_enc: bytes,
    access_token_enc: bytes,
    token_expiry: str,
    scopes: str | None = None,
):
    conn = get_conn()
    try:
        cur = conn.execute(
            """
            INSERT INTO email_accounts
                (email_address, display_name, auth_method, app_password_enc, refresh_token_enc,
                 access_token_enc, token_expiry, scopes)
            VALUES (?, ?, 'oauth', X'', ?, ?, ?, ?)
            ON CONFLICT(email_address) DO UPDATE SET
                display_name = excluded.display_name,
                auth_method = 'oauth',
                refresh_token_enc = excluded.refresh_token_enc,
                access_token_enc = excluded.access_token_enc,
                token_expiry = excluded.token_expiry,
                scopes = excluded.scopes
            """,
            (email_address, display_name, refresh_token_enc, access_token_enc, token_expiry, scopes),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_oauth_tokens(account_id: int, access_token_enc: bytes, token_expiry: str):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE email_accounts SET access_token_enc = ?, token_expiry = ? WHERE id = ?",
            (access_token_enc, token_expiry, account_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_account_fields(account_id: int, **fields):
    bad = set(fields) - _ACCOUNT_FIELDS
    if bad:
        raise ValueError(f"not an account field: {bad}")
    if not fields:
        return
    conn = get_conn()
    try:
        cols = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE email_accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))
        conn.commit()
    finally:
        conn.close()


def delete_email_account(account_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM email_accounts WHERE id = ?", (account_id,))
        conn.commit()
    finally:
        conn.close()


def set_account_synced_now(account_id: int, timestamp: str):
    set_account_fields(account_id, last_synced_at=timestamp)


def latest_sync_at() -> str | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT MAX(last_synced_at) AS t FROM email_accounts").fetchone()
        return row["t"] if row else None
    finally:
        conn.close()
