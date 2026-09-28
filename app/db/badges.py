"""The tab badges in the header, which every page shows: one connection and
one query for all of them. The single-count functions elsewhere (bills,
lists, users, mail_messages) use the same SQL from here."""
from .core import get_conn

DUE_SQL = "SELECT COUNT(*) FROM bills WHERE paid = 0 AND due_date <= :today"
UNREAD_SQL = "SELECT COUNT(*) FROM email_messages m WHERE m.is_read = 0 AND m.in_inbox = 1 AND m.is_trashed = 0"
LIST_SQL = "SELECT COUNT(*) FROM list_items WHERE deleted = 0 AND checked = 0"
SHARE_SQL = ("SELECT COALESCE((SELECT (SELECT COUNT(*) FROM posts WHERE user_id != u.id AND id > u.seen_post)"
             " + (SELECT COUNT(*) FROM post_comments WHERE user_id != u.id AND id > u.seen_comment)"
             " FROM users u WHERE u.id = :uid), 0)")


def nav_counts(today: str, user_id: int | None) -> dict[str, int]:
    """{'due', 'unread', 'list', 'share'} for the header. `share` is 0 for the household login."""
    conn = get_conn()
    try:
        row = conn.execute(
            f"SELECT ({DUE_SQL}) AS due, ({UNREAD_SQL}) AS unread, ({LIST_SQL}) AS list, ({SHARE_SQL}) AS share",
            {"today": today, "uid": user_id or 0},
        ).fetchone()
        return dict(row)
    finally:
        conn.close()
