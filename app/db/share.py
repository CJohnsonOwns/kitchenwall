"""Sharing wall: posts, comments, reactions."""
from .core import get_conn


def create_post(user_id: int, body: str, link_url: str | None, media_name: str | None, media_kind: str | None) -> int:
    conn = get_conn()
    try:
        cur = conn.execute("INSERT INTO posts (user_id, body, link_url, media_name, media_kind) VALUES (?, ?, ?, ?, ?)",
                           (user_id, body, link_url, media_name, media_kind))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_post(post_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    finally:
        conn.close()


def update_post_body(post_id: int, body: str):
    conn = get_conn()
    try:
        conn.execute("UPDATE posts SET body = ?, edited_at = datetime('now') WHERE id = ?", (body, post_id))
        conn.commit()
    finally:
        conn.close()


def delete_post(post_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()
    finally:
        conn.close()


def list_posts(limit: int, before_id: int | None = None) -> list[dict]:
    """Newest first, each with its author's name/picture, its comments (oldest
    first) and its reactions."""
    conn = get_conn()
    try:
        posts = [dict(r) for r in conn.execute(
            "SELECT p.*, u.display_name AS author, u.avatar AS author_avatar FROM posts p JOIN users u ON u.id = p.user_id "
            "WHERE p.id < ? ORDER BY p.id DESC LIMIT ?", (before_id or 2**62, limit))]
        by_id = {p["id"]: p for p in posts}
        for p in posts:
            p["comments"], p["reactions"] = [], []
        if by_id:
            marks = ",".join("?" * len(by_id))
            for c in conn.execute(
                    f"SELECT c.*, u.display_name AS author, u.avatar AS author_avatar FROM post_comments c "
                    f"JOIN users u ON u.id = c.user_id WHERE c.post_id IN ({marks}) ORDER BY c.id", list(by_id)):
                by_id[c["post_id"]]["comments"].append(dict(c))
            for r in _reaction_rows(conn, list(by_id)):
                by_id[r["post_id"]]["reactions"].append(r)
        return posts
    finally:
        conn.close()


def _reaction_rows(conn, post_ids: list[int]) -> list[dict]:
    marks = ",".join("?" * len(post_ids))
    return [dict(r) for r in conn.execute(
        f"SELECT r.post_id, r.user_id, r.emoji, u.display_name AS name FROM post_reactions r "
        f"JOIN users u ON u.id = r.user_id WHERE r.post_id IN ({marks}) ORDER BY r.created_at, u.id", post_ids)]


def post_reactions(post_id: int) -> list[dict]:
    conn = get_conn()
    try:
        return _reaction_rows(conn, [post_id])
    finally:
        conn.close()


def toggle_reaction(post_id: int, user_id: int, emoji: str) -> bool | None:
    """Adds this person's reaction, or takes it back if it's there. True = now on;
    None if the post is gone."""
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone():
            return None
        n = conn.execute("DELETE FROM post_reactions WHERE post_id = ? AND user_id = ? AND emoji = ?",
                         (post_id, user_id, emoji)).rowcount
        if not n:
            conn.execute("INSERT INTO post_reactions (post_id, user_id, emoji) VALUES (?, ?, ?)", (post_id, user_id, emoji))
        conn.commit()
        return not n
    finally:
        conn.close()


def add_comment(post_id: int, user_id: int, body: str) -> int | None:
    """None if the post is gone."""
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM posts WHERE id = ?", (post_id,)).fetchone():
            return None
        cur = conn.execute("INSERT INTO post_comments (post_id, user_id, body) VALUES (?, ?, ?)",
                           (post_id, user_id, body))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_comment(comment_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM post_comments WHERE id = ?", (comment_id,)).fetchone()
    finally:
        conn.close()


def delete_comment(comment_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM post_comments WHERE id = ?", (comment_id,))
        conn.commit()
    finally:
        conn.close()
