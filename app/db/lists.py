"""Shopping lists and their items (soft delete + undo)."""
from .badges import LIST_SQL
from .core import get_conn


def lists_summary() -> list[dict]:
    """Every list in order, with how many things are left to get on each."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT l.id, l.name, COUNT(i.id) AS to_get FROM lists l "
            "LEFT JOIN list_items i ON i.list_id = l.id AND i.deleted = 0 AND i.checked = 0 "
            "GROUP BY l.id ORDER BY l.position, l.id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_name_taken(name: str, except_id: int | None = None) -> bool:
    conn = get_conn()
    try:
        return conn.execute("SELECT 1 FROM lists WHERE name = ? COLLATE NOCASE AND id IS NOT ?",
                            (name, except_id)).fetchone() is not None
    finally:
        conn.close()


def create_list(name: str) -> int:
    conn = get_conn()
    try:
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM lists").fetchone()[0]
        cur = conn.execute("INSERT INTO lists (name, position) VALUES (?, ?)", (name, pos))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def rename_list(list_id: int, name: str) -> bool:
    conn = get_conn()
    try:
        n = conn.execute("UPDATE lists SET name = ? WHERE id = ?", (name, list_id)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def delete_list(list_id: int) -> bool:
    """Deletes a list and everything on it. The last remaining list can't be deleted."""
    conn = get_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM lists").fetchone()[0] <= 1:
            return False
        conn.execute("DELETE FROM list_items WHERE list_id = ?", (list_id,))
        n = conn.execute("DELETE FROM lists WHERE id = ?", (list_id,)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def list_items(list_id: int):
    """Live rows on one list: still to get in the order added, then checked ones newest first."""
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT id, text, checked FROM list_items WHERE deleted = 0 AND list_id = ? "
            "ORDER BY checked, CASE WHEN checked THEN checked_at END DESC, id", (list_id,)
        ).fetchall()
    finally:
        conn.close()


def count_list_to_get() -> int:
    """Across every list (drives the tab badge)."""
    conn = get_conn()
    try:
        return conn.execute(LIST_SQL).fetchone()[0]
    finally:
        conn.close()


def add_list_item(list_id: int, text: str) -> int:
    """Adding something already on that list doesn't duplicate it: an unchecked
    match is left alone, a checked one goes back on the list."""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, checked FROM list_items WHERE deleted = 0 AND list_id = ? AND text = ? COLLATE NOCASE "
            "ORDER BY checked LIMIT 1",
            (list_id, text),
        ).fetchone()
        if row:
            if row["checked"]:
                conn.execute("UPDATE list_items SET checked = 0, checked_at = NULL, updated_at = datetime('now') "
                             "WHERE id = ?", (row["id"],))
                conn.commit()
            return row["id"]
        cur = conn.execute("INSERT INTO list_items (list_id, text) VALUES (?, ?)", (list_id, text))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_list_item(item_id: int, text: str | None = None, checked: bool | None = None) -> bool:
    conn = get_conn()
    try:
        n = 0
        if text is not None:
            n += conn.execute("UPDATE list_items SET text = ?, updated_at = datetime('now') WHERE id = ? AND deleted = 0",
                              (text, item_id)).rowcount
        if checked is not None:
            n += conn.execute(
                "UPDATE list_items SET checked = ?, checked_at = CASE WHEN ? THEN datetime('now') END, "
                "updated_at = datetime('now') WHERE id = ? AND deleted = 0",
                (int(checked), int(checked), item_id)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def delete_list_items(ids=None, checked_on_list: int | None = None) -> list[int]:
    """Soft-delete the given ids (or every checked row on one list). Returns the ids deleted, for Undo."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM list_items WHERE deleted = 1 AND updated_at < datetime('now', '-1 day')")
        if checked_on_list is not None:
            ids = [r[0] for r in conn.execute("SELECT id FROM list_items WHERE deleted = 0 AND checked = 1 AND list_id = ?",
                                              (checked_on_list,))]
        ids = [int(i) for i in ids or []]
        conn.executemany("UPDATE list_items SET deleted = 1, updated_at = datetime('now') WHERE id = ? AND deleted = 0",
                         [(i,) for i in ids])
        conn.commit()
        return ids
    finally:
        conn.close()


def restore_list_items(ids) -> int:
    conn = get_conn()
    try:
        n = sum(conn.execute("UPDATE list_items SET deleted = 0, updated_at = datetime('now') WHERE id = ? AND deleted = 1",
                             (int(i),)).rowcount for i in ids)
        conn.commit()
        return n
    finally:
        conn.close()
