"""Whiteboard notes, their categories and photos."""
import sqlite3

from .core import get_conn


def list_board_items(include_checked: bool = True):
    conn = get_conn()
    try:
        if include_checked:
            return conn.execute("SELECT * FROM board_items ORDER BY id ASC").fetchall()
        return conn.execute(
            "SELECT * FROM board_items WHERE checked = 0 ORDER BY id ASC"
        ).fetchall()
    finally:
        conn.close()


def list_done_board_items():
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM board_items WHERE checked = 1 ORDER BY id DESC"
        ).fetchall()
    finally:
        conn.close()


def create_board_item(text: str, color: str, item_type: str, created_by: str):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO board_items (text, color, item_type, created_by, x, y, touched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (text, color, item_type, created_by, 20, 20),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_board_item_position(item_id: int, x: int, y: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE board_items SET x = ?, y = ?, touched_at = datetime('now') WHERE id = ?",
            (x, y, item_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_board_item_text(item_id: int, text: str):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE board_items SET text = ?, touched_at = datetime('now') WHERE id = ?",
            (text, item_id),
        )
        conn.commit()
    finally:
        conn.close()


def toggle_board_item_checked(item_id: int, checked: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE board_items SET checked = ?, touched_at = datetime('now') WHERE id = ?",
            (checked, item_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_board_item_categories(item_id: int, category_ids: list[int]):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM board_item_categories WHERE item_id = ?", (item_id,))
        for cid in set(category_ids):
            # INSERT ... SELECT silently skips ids of categories that no longer exist.
            conn.execute(
                "INSERT INTO board_item_categories (item_id, category_id) "
                "SELECT ?, id FROM board_categories WHERE id = ?",
                (item_id, cid),
            )
        conn.execute(
            "UPDATE board_items SET touched_at = datetime('now') WHERE id = ?", (item_id,)
        )
        conn.commit()
    finally:
        conn.close()


def category_ids_by_item() -> dict[int, list[int]]:
    """Map item id -> its category ids, each list ordered by category name."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT ic.item_id, ic.category_id FROM board_item_categories ic "
            "JOIN board_categories c ON c.id = ic.category_id "
            "ORDER BY c.name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()
    result: dict[int, list[int]] = {}
    for r in rows:
        result.setdefault(r["item_id"], []).append(r["category_id"])
    return result


def list_board_categories():
    conn = get_conn()
    try:
        return conn.execute(
            "SELECT * FROM board_categories ORDER BY name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()


def create_board_category(name: str, color: str) -> bool:
    """Returns False if a category with that name (case-insensitive) exists."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO board_categories (name, color) VALUES (?, ?)", (name, color)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def update_board_category(category_id: int, name: str, color: str) -> bool:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE board_categories SET name = ?, color = ? WHERE id = ?",
            (name, color, category_id),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def delete_board_category(category_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM board_categories WHERE id = ?", (category_id,))
        conn.commit()
    finally:
        conn.close()


def delete_board_item(item_id: int) -> str | None:
    """Deletes the note; returns its photo's file name (if any) so the caller can remove the files."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT photo FROM board_items WHERE id = ?", (item_id,)).fetchone()
        conn.execute("DELETE FROM board_items WHERE id = ?", (item_id,))
        conn.commit()
        return row["photo"] if row else None
    finally:
        conn.close()


def get_board_item_photo(item_id: int) -> tuple[bool, str | None]:
    """(note exists, its photo file name or None)."""
    conn = get_conn()
    try:
        row = conn.execute("SELECT photo FROM board_items WHERE id = ?", (item_id,)).fetchone()
        return (row is not None, row["photo"] if row else None)
    finally:
        conn.close()


def set_board_item_photo(item_id: int, photo: str | None):
    conn = get_conn()
    try:
        conn.execute("UPDATE board_items SET photo = ?, touched_at = datetime('now') WHERE id = ?", (photo, item_id))
        conn.commit()
    finally:
        conn.close()
