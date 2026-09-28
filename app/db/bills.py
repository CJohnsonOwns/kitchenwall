"""Calendar items (table `bills`; "bills" is internal naming only, never shown)."""
from .badges import DUE_SQL
from .core import get_conn


def list_bills(include_paid: bool = False):
    conn = get_conn()
    try:
        # Within a day: all-day items first, then by time.
        where = "" if include_paid else "WHERE paid = 0 "
        return conn.execute(
            f"SELECT * FROM bills {where}ORDER BY due_date ASC, due_time IS NOT NULL, due_time ASC"
        ).fetchall()
    finally:
        conn.close()


def count_open_bills_through(date_str: str) -> int:
    """Open calendar items due on or before the given day (overdue + due today)."""
    conn = get_conn()
    try:
        return conn.execute(DUE_SQL, {"today": date_str}).fetchone()[0]
    finally:
        conn.close()


def get_bill(bill_id: int):
    conn = get_conn()
    try:
        return conn.execute("SELECT * FROM bills WHERE id = ?", (bill_id,)).fetchone()
    finally:
        conn.close()


def create_bill(name: str, amount: float, due_date: str, recurring: str, due_time: str | None = None):
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO bills (name, amount, due_date, recurring, due_time) VALUES (?, ?, ?, ?, ?)",
            (name, amount, due_date, recurring, due_time),
        )
        conn.commit()
    finally:
        conn.close()


def update_bill(bill_id: int, name: str, amount: float, due_date: str, recurring: str, due_time: str | None = None):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE bills SET name = ?, amount = ?, due_date = ?, recurring = ?, due_time = ? WHERE id = ?",
            (name, amount, due_date, recurring, due_time, bill_id),
        )
        conn.commit()
    finally:
        conn.close()


def set_bill_due_date(bill_id: int, due_date: str, paid: int):
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE bills SET due_date = ?, paid = ? WHERE id = ?",
            (due_date, paid, bill_id),
        )
        conn.commit()
    finally:
        conn.close()


def toggle_bill_paid(bill_id: int, paid: int):
    conn = get_conn()
    try:
        conn.execute("UPDATE bills SET paid = ? WHERE id = ?", (paid, bill_id))
        conn.commit()
    finally:
        conn.close()


def delete_bill(bill_id: int):
    conn = get_conn()
    try:
        conn.execute("DELETE FROM bills WHERE id = ?", (bill_id,))
        conn.commit()
    finally:
        conn.close()
