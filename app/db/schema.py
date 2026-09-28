"""Table definitions (SCHEMA) and columns added since (MIGRATIONS). Applied on every start by core.init_db()."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    amount REAL NOT NULL,
    due_date TEXT NOT NULL,
    recurring TEXT NOT NULL DEFAULT 'none',
    paid INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS board_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#fff7b2',
    x INTEGER NOT NULL DEFAULT 20,
    y INTEGER NOT NULL DEFAULT 20,
    item_type TEXT NOT NULL DEFAULT 'note',
    checked INTEGER NOT NULL DEFAULT 0,
    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS board_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    color TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS board_item_categories (
    item_id INTEGER NOT NULL REFERENCES board_items(id) ON DELETE CASCADE,
    category_id INTEGER NOT NULL REFERENCES board_categories(id) ON DELETE CASCADE,
    PRIMARY KEY (item_id, category_id)
);

CREATE TABLE IF NOT EXISTS email_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL UNIQUE,
    display_name TEXT,
    auth_method TEXT NOT NULL DEFAULT 'app_password',
    app_password_enc BLOB NOT NULL DEFAULT (X''),
    refresh_token_enc BLOB,
    access_token_enc BLOB,
    token_expiry TEXT,
    imap_host TEXT NOT NULL DEFAULT 'imap.gmail.com',
    smtp_host TEXT NOT NULL DEFAULT 'smtp.gmail.com',
    last_synced_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS email_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    message_id TEXT,
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    date_header TEXT,
    received_at TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    UNIQUE(account_id, uid)
);

CREATE TABLE IF NOT EXISTS email_bodies (
    account_id INTEGER NOT NULL REFERENCES email_accounts(id) ON DELETE CASCADE,
    uid TEXT NOT NULL,
    data_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, uid)
);

CREATE TABLE IF NOT EXISTS whiteboard_strokes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#d9a441',
    width INTEGER NOT NULL DEFAULT 3,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Separate shopping lists (Shopping, Costco, Hardware...). There's always at least one.
CREATE TABLE IF NOT EXISTS lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Items on those lists. Deleting only sets `deleted` so Undo can bring
-- a row back; rows deleted more than a day ago are purged.
CREATE TABLE IF NOT EXISTS list_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    checked INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT,
    deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Personal logins (made with deploy/add_user.py). The household password in
-- .env still works too, as a view-only "Household" login for the wall screen.
-- seen_post/seen_comment: newest post/comment id when this person last opened
-- Sharing (drives only their own badge and "new" marks).
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    pw_hash TEXT NOT NULL,
    seen_post INTEGER NOT NULL DEFAULT 0,
    seen_comment INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Sharing tab: posts (text and/or one photo/video and/or a link) and comments.
-- media_name is a file in data/photos or data/videos, per media_kind.
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL DEFAULT '',
    link_url TEXT,
    media_name TEXT,
    media_kind TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    edited_at TEXT
);

-- Likes (👍) and emoji reactions on posts: one row per person per emoji.
CREATE TABLE IF NOT EXISTS post_reactions (
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    emoji TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (post_id, user_id, emoji)
);

CREATE TABLE IF NOT EXISTS post_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Indexes for the queries every page runs (tab badges, inbox list, lists,
# Sharing). Applied after MIGRATIONS, since some columns come from there.
INDEXES = """
CREATE INDEX IF NOT EXISTS ix_msg_view ON email_messages (in_inbox, is_trashed, is_read);
CREATE INDEX IF NOT EXISTS ix_msg_newest ON email_messages (COALESCE(received_at, date_header));
CREATE INDEX IF NOT EXISTS ix_msg_thread ON email_messages (account_id, thread_id);
CREATE INDEX IF NOT EXISTS ix_bodies_fetched ON email_bodies (fetched_at);
CREATE INDEX IF NOT EXISTS ix_bills_open ON bills (paid, due_date);
CREATE INDEX IF NOT EXISTS ix_list_items_list ON list_items (list_id, deleted, checked);
CREATE INDEX IF NOT EXISTS ix_comments_post ON post_comments (post_id);
"""

# Columns added after the initial release. CREATE TABLE IF NOT EXISTS won't
# retrofit these onto a database file created by an older version of the
# app, so add them by hand if missing.
MIGRATIONS = [
    ("email_accounts", "auth_method", "TEXT NOT NULL DEFAULT 'app_password'"),
    ("email_accounts", "refresh_token_enc", "BLOB"),
    ("email_accounts", "access_token_enc", "BLOB"),
    ("email_accounts", "token_expiry", "TEXT"),
    ("email_messages", "thread_id", "TEXT"),
    # Last time anyone created/moved/re-categorized/restored a note; drives
    # the paper-aging look. NULL on pre-existing notes = fall back to created_at.
    ("board_items", "touched_at", "TEXT"),
    # First line or so of the message, shown under the subject in the inbox.
    ("email_messages", "snippet", "TEXT"),
    # Two-way mail sync (Phase 1/2 inbox work). Which views a message is in,
    # its star/trash state, recipients (for the Sent view) and, for IMAP
    # accounts, its UID in "All Mail".
    ("email_messages", "in_inbox", "INTEGER NOT NULL DEFAULT 1"),
    ("email_messages", "in_sent", "INTEGER NOT NULL DEFAULT 0"),
    ("email_messages", "is_starred", "INTEGER NOT NULL DEFAULT 0"),
    ("email_messages", "is_trashed", "INTEGER NOT NULL DEFAULT 0"),
    ("email_messages", "imap_uid", "INTEGER"),
    ("email_messages", "to_addrs", "TEXT"),
    # Granted OAuth scopes, Gmail history cursor, IMAP UIDVALIDITY, and a
    # version number: accounts below 2 get their old cache wiped and resynced.
    ("email_accounts", "scopes", "TEXT"),
    ("email_accounts", "history_id", "TEXT"),
    ("email_accounts", "imap_uidvalidity", "TEXT"),
    ("email_accounts", "sync_version", "INTEGER NOT NULL DEFAULT 1"),
    # Optional time of day for a calendar item, "HH:MM" (24h). NULL = all day.
    ("bills", "due_time", "TEXT"),
    # Which list an item is on (lists table). Pre-lists items get the first list.
    ("list_items", "list_id", "INTEGER"),
    # Photo on a whiteboard note: a file name in data/photos (see photos.py). NULL = none.
    ("board_items", "photo", "TEXT"),
    # 1 = signed up with a temporary password (add_user.py --temp): must pick
    # their own right after signing in.
    ("users", "must_change", "INTEGER NOT NULL DEFAULT 0"),
    # Profile picture: a file name in data/photos (see photos.py). NULL = initial letter.
    ("users", "avatar", "TEXT"),
]
