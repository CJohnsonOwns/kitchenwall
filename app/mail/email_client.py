"""One interface over both kinds of Gmail connection.

Routers and the sync thread only talk to this module. It picks the Gmail
API backend (`google_oauth`) or the IMAP/SMTP backend (`imap_gmail`) per
account, keeps the local cache in step after every change, and turns raw
messages into conversation data for the templates.
"""
import json
import threading

from .. import db
from . import google_oauth, imap_gmail
from .mail_mime import (
    address_list,
    attachment_parts,
    build_message,
    forward_block,
    get_part,
    parse_raw,
    prefixed_subject,
    quote_block,
    reply_targets,
)
from .mail_utils import (
    EmailAuthError,
    ScopeError,
    decrypt_password,
    encrypt_password,
    ensure_email_key,
)

__all__ = [
    "EmailAuthError", "ScopeError", "encrypt_password", "decrypt_password", "ensure_email_key",
    "test_login", "sync", "fetch_older", "search", "open_thread", "modify", "get_attachment", "send_mail",
]

ACTIONS = ("read", "unread", "star", "unstar", "archive", "inbox", "trash", "untrash")

# Local flag changes that mirror each action once it has reached Gmail.
_LOCAL = {
    "read": {"is_read": 1},
    "unread": {"is_read": 0},
    "star": {"is_starred": 1},
    "unstar": {"is_starred": 0},
    "archive": {"in_inbox": 0},
    "inbox": {"in_inbox": 1},
    "trash": {"is_trashed": 1},
}

# The opposite of each action, for Undo.
INVERSE = {
    "read": "unread", "unread": "read", "star": "unstar", "unstar": "star",
    "archive": "inbox", "inbox": "archive", "trash": "untrash", "untrash": "trash",
}


def _backend(account):
    return google_oauth if account["auth_method"] == "oauth" else imap_gmail


def test_login(email_address: str, app_password: str, imap_host: str) -> None:
    imap_gmail.test_login(email_address, app_password, imap_host)


def sync(account) -> None:
    _backend(account).sync(account)


def sync_in_background(account_id: int) -> None:
    """Re-sync one account without making the request wait (used after Undo of a delete)."""
    def run():
        account = db.get_email_account(account_id)
        if account:
            try:
                sync(account)
            except Exception:
                pass

    threading.Thread(target=run, daemon=True).start()


def fetch_older(account, view: str, count: int = 50) -> int:
    return _backend(account).fetch_older(account, view, count)


def search(account, query: str, limit: int = 40) -> list[dict]:
    return _backend(account).search(account, query, limit)


def modify(account, uids: list[str], action: str, to_inbox: bool = True) -> None:
    """Apply an action in Gmail, then mirror it in the local cache."""
    if action not in ACTIONS:
        raise ValueError(action)
    _backend(account).modify(account, uids, action, to_inbox=to_inbox)
    if action == "untrash":
        db.update_message_flags(account["id"], uids, is_trashed=0, **({"in_inbox": 1} if to_inbox else {}))
        if account["auth_method"] != "oauth":
            sync_in_background(account["id"])  # the message has a new All Mail UID now
    else:
        db.update_message_flags(account["id"], uids, **_LOCAL[action])


# ---- Conversations ----

def _parsed(account_id: int, uid: str, raw: bytes | None) -> dict | None:
    if raw:
        data = parse_raw(raw)
        db.put_body(account_id, uid, json.dumps(data))
        return data
    cached = db.get_body(account_id, uid)
    return json.loads(cached) if cached else None


def open_thread(account, uid: str, mark_read: bool = True) -> dict:
    """The conversation containing `uid`: messages oldest first, each with parsed body.

    Marks unread messages as read in Gmail (quietly skipped if the account
    can't be changed yet) and in the cache.
    """
    account_id = account["id"]
    backend = _backend(account)
    cached_rows = db.cached_messages(account_id)
    # Bodies we already have; the backend then only downloads the rest.
    probe = [uid] + [u for u, r in cached_rows.items() if r.get("thread_id") and r["thread_id"] == (cached_rows.get(uid) or {}).get("thread_id")]
    have = db.bodies_present(account_id, probe)
    items = backend.thread_messages(account, uid, have)
    if not items:
        raise EmailAuthError("That conversation is no longer in the mailbox.")

    messages = []
    for it in items:
        data = _parsed(account_id, it["uid"], it.get("raw"))
        if data is None:
            # Body cache was pruned between the probe and now: fetch it directly.
            data = _parsed(account_id, it["uid"], backend.get_raw(account, it["uid"]))
        messages.append({**it, "raw": None, **data})

    unread = [m["uid"] for m in messages if not m["is_read"]]
    if mark_read and unread:
        try:
            backend.modify(account, unread, "read")
        except EmailAuthError:
            pass  # the account can't change Gmail yet; still show it read here
        db.update_message_flags(account_id, unread, is_read=1)
    return {"thread_id": items[-1].get("thread_id"), "messages": messages, "was_unread": set(unread)}


def get_attachment(account, uid: str, index: int):
    raw = _backend(account).get_raw(account, uid)
    part = get_part(raw, index)
    if part is None:
        raise EmailAuthError("That attachment couldn't be found.")
    return part


# ---- Sending ----

def contacts(limit: int = 400) -> list[dict]:
    """People you've exchanged mail with, most frequent first, for address autocomplete."""
    counts: dict[str, dict] = {}
    conn = db.get_conn()
    try:
        rows = conn.execute("SELECT sender, to_addrs, in_sent FROM email_messages").fetchall()
    finally:
        conn.close()
    for r in rows:
        # People you've written to count double: they're who you're likely to write to again.
        for field, weight in (("sender", 1), ("to_addrs", 2 if r["in_sent"] else 1)):
            for name, addr in address_list(r[field] or ""):
                key = addr.lower()
                c = counts.setdefault(key, {"name": "", "email": addr, "n": 0})
                c["n"] += weight
                if name and not c["name"]:
                    c["name"] = name.strip('"')
    ranked = sorted(counts.values(), key=lambda c: -c["n"])[:limit]
    return [{"name": c["name"], "email": c["email"]} for c in ranked]


def compose_defaults(account, message: dict) -> dict:
    """Prefilled To/Cc/Subject for reply, reply-all and forward of one message."""
    headers = message["headers"]
    to, _ = reply_targets(headers, account["email_address"], reply_all=False)
    to_all, cc_all = reply_targets(headers, account["email_address"], reply_all=True)
    return {
        "reply": {"to": to, "cc": "", "subject": prefixed_subject(headers["subject"], "Re:")},
        "replyall": {"to": to_all, "cc": cc_all, "subject": prefixed_subject(headers["subject"], "Re:")},
        "forward": {"to": "", "cc": "", "subject": prefixed_subject(headers["subject"], "Fwd:")},
    }


MAX_SEND_BYTES = 24 * 1024 * 1024  # Gmail rejects messages over 25 MB


def send_mail(
    account,
    mode: str,
    to: str,
    cc: str,
    subject: str,
    body: str,
    ref_uid: str | None = None,
    include_quote: bool = True,
    include_attachments: bool = True,
    bcc: str = "",
    ref_account=None,
    uploads: list[tuple[str, str, bytes]] = (),
    forward_indexes=None,
) -> None:
    """Send a new message, reply, reply-all or forward.

    `account` sends it; `ref_account` (default: the same) holds the message
    being replied to or forwarded. `forward_indexes` picks which of its
    attachments go along (None = all); `uploads` are files attached here.
    """
    ref_account = ref_account or account
    in_reply_to = references = thread_id = None
    attachments: list = []
    if mode in ("reply", "replyall", "forward") and ref_uid:
        ref_backend = _backend(ref_account)
        cached = db.get_body(ref_account["id"], ref_uid)
        want_files = mode == "forward" and include_attachments and forward_indexes != []
        raw = None
        if cached is None or want_files:
            raw = ref_backend.get_raw(ref_account, ref_uid)
            ref = parse_raw(raw)
        else:
            ref = json.loads(cached)
        headers = ref["headers"]
        row = db.get_message(ref_account["id"], ref_uid)
        if row and ref_account["id"] == account["id"]:
            thread_id = row["thread_id"]
        if mode == "forward":
            body = body.rstrip() + forward_block(headers, ref["plain"])
            if want_files and raw is not None:
                attachments = attachment_parts(raw, forward_indexes)
            thread_id = None
        else:
            in_reply_to = headers.get("message_id") or None
            references = headers.get("references") or None
            if include_quote:
                body = body.rstrip() + quote_block(headers, ref["plain"])
    attachments = list(attachments) + [u for u in uploads if u[2]]
    if sum(len(a[2]) for a in attachments) > MAX_SEND_BYTES:
        raise EmailAuthError("Attachments add up to more than Gmail's 25 MB limit. Remove some and try again.")

    # Bare address: the display name here is a household label ("House"), not
    # the person's name, and Gmail adds the account's own name when sending.
    from_addr = account["email_address"]
    msg = build_message(from_addr, to, cc, subject, body, in_reply_to, references, attachments, bcc=bcc)
    if account["auth_method"] == "oauth":
        google_oauth.send(account, msg, thread_id)
    else:
        imap_gmail.send(account, msg)
