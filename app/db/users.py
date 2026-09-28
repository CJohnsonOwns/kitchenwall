"""Personal logins (one per person):password hashes, avatar, what they have seen on Sharing."""
from .badges import SHARE_SQL
from .core import get_conn


def get_user(user_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()


def get_user_by_name(username: str):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    finally:
        conn.close()


def list_users() -> list[dict]:
    """Everyone who can sign in personally (no password hashes)."""
    conn = get_conn()
    try:
        return [dict(r) for r in conn.execute("SELECT id, username, display_name FROM users ORDER BY id")]
    finally:
        conn.close()


def upsert_user(username: str, display_name: str, pw_hash: str, must_change: bool = False) -> bool:
    """Creates the user, or resets the name/password of an existing one. True = created."""
    conn = get_conn()
    try:
        n = conn.execute("UPDATE users SET display_name = ?, pw_hash = ?, must_change = ? WHERE username = ?",
                         (display_name, pw_hash, int(must_change), username)).rowcount
        if not n:
            conn.execute("INSERT INTO users (username, display_name, pw_hash, must_change) VALUES (?, ?, ?, ?)",
                         (username, display_name, pw_hash, int(must_change)))
        conn.commit()
        return not n
    finally:
        conn.close()


def set_user_password(user_id: int, pw_hash: str):
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET pw_hash = ?, must_change = 0 WHERE id = ?", (pw_hash, user_id))
        conn.commit()
    finally:
        conn.close()


def mark_share_seen(user_id: int):
    conn = get_conn()
    try:
        conn.execute("UPDATE users SET seen_post = (SELECT COALESCE(MAX(id), 0) FROM posts), "
                     "seen_comment = (SELECT COALESCE(MAX(id), 0) FROM post_comments) WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def count_share_new(user_id: int) -> int:
    """Posts and comments by other people since this person last opened Sharing."""
    conn = get_conn()
    try:
        return conn.execute(SHARE_SQL, {"uid": user_id}).fetchone()[0] if user_id else 0
    finally:
        conn.close()



def set_user_avatar(user_id: int, name: str | None) -> str | None:
    """Sets (or clears) a profile picture; returns the old file name so the caller can delete it."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT avatar FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (name, user_id))
        conn.commit()
        return row["avatar"] if row else None
    finally:
        conn.close()
