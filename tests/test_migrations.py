"""Upgrading a database from before several lists and note photos: the old
list items land on a first list called Shopping, nothing is lost, and running
the upgrade again changes nothing."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
path = os.path.join(tempfile.mkdtemp(), "old.db")
os.environ["HOUSEHOLD_DB_PATH"] = path

FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


# The shape of the live database before this change.
c = sqlite3.connect(path)
c.executescript("""
CREATE TABLE list_items (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, checked INTEGER NOT NULL DEFAULT 0,
  checked_at TEXT, deleted INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE board_items (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, color TEXT NOT NULL DEFAULT '#fff7b2',
  x INTEGER NOT NULL DEFAULT 20, y INTEGER NOT NULL DEFAULT 20, item_type TEXT NOT NULL DEFAULT 'note',
  checked INTEGER NOT NULL DEFAULT 0, created_by TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
INSERT INTO list_items (text) VALUES ('Eggs'), ('Basil');
INSERT INTO list_items (text, checked) VALUES ('Cheddar', 1);
INSERT INTO board_items (text) VALUES ('Old note');
""")
c.commit()
c.close()

from app import db  # noqa: E402

db.init_db()
lists = db.lists_summary()
ok([l["name"] for l in lists] == ["Shopping"], "a first list called Shopping is created")
ok([r["text"] for r in db.list_items(lists[0]["id"])] == ["Eggs", "Basil", "Cheddar"], "old items are all on it")
ok(lists[0]["to_get"] == 2, "its count is right")
ok(db.get_board_item_photo(1) == (True, None), "old notes have no photo")
db.init_db()
ok(len(db.lists_summary()) == 1, "running the upgrade again adds nothing")

sys.exit(1 if FAILED else 0)
