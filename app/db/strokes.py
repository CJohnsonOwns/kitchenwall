"""Whiteboard doodle strokes."""
from .core import get_conn


def list_strokes():
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM whiteboard_strokes ORDER BY id ASC").fetchall()
    finally:
        conn.close()


def create_stroke(path: str, color: str, width: int):
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO whiteboard_strokes (path, color, width) VALUES (?, ?, ?)",
            (path, color, width),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def delete_last_stroke():
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM whiteboard_strokes WHERE id = (SELECT MAX(id) FROM whiteboard_strokes)"
        )
        conn.commit()
    finally:
        conn.close()


def clear_strokes():
    conn = get_conn()
    try:
        conn.execute("DELETE FROM whiteboard_strokes")
        conn.commit()
    finally:
        conn.close()
