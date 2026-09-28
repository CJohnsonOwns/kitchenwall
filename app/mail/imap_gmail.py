"""Gmail over IMAP, for accounts connected with an App Password.

Everything happens in Gmail's "All Mail" folder using Gmail's IMAP
extensions: X-GM-RAW (Gmail search syntax), X-GM-MSGID (a stable message
id), X-GM-THRID (conversation id) and X-GM-LABELS (archive = drop \\Inbox).
Each sync compares the full membership of Inbox / Sent / Starred with the
cache, so archived or deleted mail disappears and read/star state follows
Gmail in both directions.
"""
import imaplib
import re
import smtplib
import time
from contextlib import contextmanager
from datetime import datetime

from .. import db
from .mail_mime import received_from_date, recipients_of, snippet_from_partial
from .mail_utils import EmailAuthError, decode_mime_words, decrypt_password

imaplib.Commands.setdefault("MOVE", ("SELECTED",))
imaplib._MAXLINE = 10_000_000  # large search results / literals

VIEW_QUERIES = {"inbox": ("in:inbox", 100), "sent": ("in:sent", 50), "starred": ("is:starred", 50)}
HEADER_FIELDS = "FROM TO CC SUBJECT DATE MESSAGE-ID CONTENT-TYPE CONTENT-TRANSFER-ENCODING"
CHUNK = 250

_LIST_RE = re.compile(rb'\((?P<flags>[^)]*)\) (?:"[^"]*"|NIL) (?P<name>.+)$')
_UID_RE = re.compile(rb"(?<![\w-])UID (\d+)")
_MSGID_RE = re.compile(rb"X-GM-MSGID (\d+)")
_THRID_RE = re.compile(rb"X-GM-THRID (\d+)")
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_RECORD_START = re.compile(rb"^\d+ \(")


# ---- Connection ----

def _quote(name: str) -> str:
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _folders(imap) -> dict[str, str]:
    """Special-use roles (\\All, \\Trash, \\Sent) -> folder name as the server spells it."""
    typ, data = imap.list()
    roles: dict[str, str] = {}
    for line in data or []:
        if not isinstance(line, bytes):
            continue
        m = _LIST_RE.search(line)
        if not m:
            continue
        name = m.group("name").decode(errors="replace").strip()
        if name.startswith('"') and name.endswith('"'):
            name = name[1:-1].replace('\\"', '"').replace("\\\\", "\\")
        for flag in m.group("flags").decode(errors="replace").split():
            if flag in ("\\All", "\\Trash", "\\Sent"):
                roles[flag] = name
    roles.setdefault("\\All", "[Gmail]/All Mail")
    roles.setdefault("\\Trash", "[Gmail]/Trash")
    return roles


class _Session:
    def __init__(self, account):
        self.account = account
        password = decrypt_password(account["app_password_enc"])
        try:
            self.imap = imaplib.IMAP4_SSL(account["imap_host"])
            self.imap.login(account["email_address"], password)
        except imaplib.IMAP4.error as exc:
            raise EmailAuthError(f"Login failed for {account['email_address']}: {exc}") from exc
        except OSError as exc:
            raise EmailAuthError(f"Could not reach {account['imap_host']}: {exc}") from exc
        self.folders = _folders(self.imap)
        self.uidvalidity = None

    def select(self, role: str = "\\All", readonly: bool = False):
        name = self.folders.get(role, role)
        typ, _ = self.imap.select(_quote(name), readonly=readonly)
        if typ != "OK":
            raise EmailAuthError(f"Could not open {name} for {self.account['email_address']}")
        uv = self.imap.response("UIDVALIDITY")[1]
        self.uidvalidity = uv[0].decode() if uv and uv[0] else None

    def search(self, query: str) -> list[int]:
        """UIDs (ascending) matching a Gmail search query in the selected folder."""
        self.imap.literal = query.encode("utf-8")
        typ, data = self.imap.uid("SEARCH", "CHARSET", "UTF-8", "X-GM-RAW")
        if typ != "OK":
            raise EmailAuthError(f"Search failed for {self.account['email_address']}")
        return sorted(int(x) for x in (data[0] or b"").split())

    def uid_for_msgid(self, msgid: str) -> int | None:
        typ, data = self.imap.uid("SEARCH", "X-GM-MSGID", str(msgid))
        found = (data[0] or b"").split() if typ == "OK" and data else []
        return int(found[-1]) if found else None

    def fetch(self, uids, items: str) -> list[dict]:
        """FETCH in chunks; returns records with 'meta' bytes and 'literals' [(label, data)]."""
        out = []
        uids = sorted(set(uids))
        for i in range(0, len(uids), CHUNK):
            chunk = ",".join(str(u) for u in uids[i : i + CHUNK])
            typ, data = self.imap.uid("FETCH", chunk, items)
            if typ != "OK":
                raise EmailAuthError(f"Fetch failed for {self.account['email_address']}")
            out += _parse_fetch(data)
        return out

    def close(self):
        try:
            self.imap.logout()
        except Exception:
            pass


@contextmanager
def session(account):
    s = _Session(account)
    try:
        yield s
    finally:
        s.close()


def _parse_fetch(data) -> list[dict]:
    records: list[dict] = []
    for el in data or []:
        if isinstance(el, tuple):
            head = el[0]
            if _RECORD_START.match(head) or not records:
                records.append({"meta": head, "literals": [(head, el[1])]})
            else:
                records[-1]["meta"] += head
                records[-1]["literals"].append((head, el[1]))
        elif isinstance(el, bytes):
            if _RECORD_START.match(el):
                records.append({"meta": el, "literals": []})
            elif records:
                records[-1]["meta"] += el
    for r in records:
        meta = r["meta"]
        m = _UID_RE.search(meta)
        r["uid"] = int(m.group(1)) if m else None
        m = _MSGID_RE.search(meta)
        r["msgid"] = m.group(1).decode() if m else None
        m = _THRID_RE.search(meta)
        r["thrid"] = m.group(1).decode() if m else None
        m = _FLAGS_RE.search(meta)
        r["flags"] = m.group(1).decode(errors="replace").split() if m else []
        tt = imaplib.Internaldate2tuple(meta) if b"INTERNALDATE" in meta else None
        r["internal"] = datetime.fromtimestamp(time.mktime(tt)).astimezone().isoformat() if tt else None
    return [r for r in records if r["uid"] is not None]


def _literal(record: dict, marker: bytes) -> bytes:
    for label, data in record["literals"]:
        if marker in label.upper():
            return data or b""
    return b""


# ---- Rows ----

def _row_from_record(r: dict, views: dict[str, set]) -> dict:
    from email import message_from_bytes

    header_bytes = _literal(r, b"HEADER")
    msg = message_from_bytes(header_bytes)
    date_header = msg.get("Date")
    return {
        "uid": r["msgid"],
        "imap_uid": r["uid"],
        "thread_id": r["thrid"],
        "message_id": msg.get("Message-ID"),
        "sender": decode_mime_words(msg.get("From")),
        "to_addrs": decode_mime_words(msg.get("To")),
        "subject": decode_mime_words(msg.get("Subject")) or "(no subject)",
        "date_header": date_header,
        "received_at": r["internal"] or received_from_date(date_header),
        "snippet": snippet_from_partial(header_bytes, _literal(r, b"TEXT")) or None,
        "is_read": 1 if "\\Seen" in r["flags"] else 0,
        "in_inbox": 1 if r["uid"] in views.get("inbox", ()) else 0,
        "in_sent": 1 if r["uid"] in views.get("sent", ()) else 0,
        "is_starred": 1 if ("\\Flagged" in r["flags"] or r["uid"] in views.get("starred", ())) else 0,
        "is_trashed": 0,
    }


_FULL_ITEMS = f"(UID X-GM-MSGID X-GM-THRID FLAGS INTERNALDATE BODY.PEEK[HEADER.FIELDS ({HEADER_FIELDS})] BODY.PEEK[TEXT]<0.3000>)"


# ---- Sync ----

def sync(account) -> None:
    account_id = account["id"]
    with session(account) as s:
        s.select("\\All", readonly=True)
        fresh = (account["sync_version"] or 1) < 2 or s.uidvalidity != account["imap_uidvalidity"]
        if fresh:
            db.delete_account_messages(account_id)
        cached = {} if fresh else db.cached_messages(account_id)
        by_imap = {r["imap_uid"]: uid for uid, r in cached.items() if r["imap_uid"]}

        views = {name: set(s.search(q)) for name, (q, _) in VIEW_QUERIES.items()}
        members = set().union(*views.values())

        # Anything cached that's no longer in Inbox/Sent/Starred (archived,
        # deleted, or an old row without an All Mail UID) goes.
        gone = [uid for uid, r in cached.items() if not r["imap_uid"] or r["imap_uid"] not in members]
        db.delete_messages(account_id, gone)
        for uid in gone:
            cached.pop(uid, None)
        by_imap = {r["imap_uid"]: uid for uid, r in cached.items()}

        window = set()
        for name, (_, cap) in VIEW_QUERIES.items():
            window |= set(sorted(views[name])[-cap:])

        # Current read/star/inbox state for everything we keep.
        known = set(by_imap)
        updates = {}
        for r in s.fetch(known, "(UID FLAGS)") if known else []:
            uid = by_imap.get(r["uid"])
            if uid:
                updates[uid] = {
                    "is_read": 1 if "\\Seen" in r["flags"] else 0,
                    "is_starred": 1 if ("\\Flagged" in r["flags"] or r["uid"] in views["starred"]) else 0,
                    "in_inbox": 1 if r["uid"] in views["inbox"] else 0,
                    "in_sent": 1 if r["uid"] in views["sent"] else 0,
                    "is_trashed": 0,
                }
        db.set_flags_per_message(account_id, updates)

        new = window - known
        rows = [_row_from_record(r, views) for r in s.fetch(new, _FULL_ITEMS)] if new else []
        db.upsert_messages(account_id, [r for r in rows if r["uid"]])
        db.set_account_fields(account_id, imap_uidvalidity=s.uidvalidity, sync_version=2)


def fetch_older(account, view: str, count: int = 50) -> int:
    query, _ = VIEW_QUERIES[view]
    _, oldest_uid = db.oldest_in_view(account["id"], view)
    with session(account) as s:
        s.select("\\All", readonly=True)
        views = {name: set(s.search(q)) for name, (q, _) in VIEW_QUERIES.items()}
        pool = sorted(views[view])
        if oldest_uid:
            pool = [u for u in pool if u < oldest_uid]
        pick = pool[-count:]
        rows = [_row_from_record(r, views) for r in s.fetch(pick, _FULL_ITEMS)] if pick else []
    db.upsert_messages(account["id"], [r for r in rows if r["uid"]])
    return len(rows)


def search(account, query: str, limit: int = 40) -> list[dict]:
    with session(account) as s:
        s.select("\\All", readonly=True)
        uids = s.search(query)[-limit:]
        views = {"inbox": set(s.search("in:inbox"))} if uids else {}
        return [_row_from_record(r, views) for r in s.fetch(uids, _FULL_ITEMS)] if uids else []


# ---- Reading ----

def _imap_uid(s: _Session, account_id: int, msgid: str) -> int | None:
    row = db.get_message(account_id, msgid)
    if row and row["imap_uid"]:
        return row["imap_uid"]
    return s.uid_for_msgid(msgid)


def get_raw(account, msgid: str) -> bytes:
    with session(account) as s:
        s.select("\\All", readonly=True)
        uid = _imap_uid(s, account["id"], msgid)
        if uid is None:
            raise EmailAuthError("That message is no longer in the mailbox.")
        recs = s.fetch([uid], "(UID BODY.PEEK[])")
        if not recs:
            raise EmailAuthError("Could not load that message.")
        return _literal(recs[0], b"BODY[")


def thread_messages(account, msgid: str, have_bodies: set[str]) -> list[dict]:
    with session(account) as s:
        s.select("\\All", readonly=True)
        uid = _imap_uid(s, account["id"], msgid)
        if uid is None:
            raise EmailAuthError("That message is no longer in the mailbox.")
        head = s.fetch([uid], "(UID X-GM-THRID)")
        thrid = head[0]["thrid"] if head else None
        typ, data = s.imap.uid("SEARCH", "X-GM-THRID", thrid) if thrid else ("NO", [b""])
        uids = sorted(int(x) for x in (data[0] or b"").split()) if typ == "OK" else [uid]
        inbox = set(s.search("in:inbox"))
        items = []
        for r in s.fetch(uids, "(UID X-GM-MSGID X-GM-THRID FLAGS INTERNALDATE)"):
            items.append(
                {
                    "uid": r["msgid"],
                    "imap_uid": r["uid"],
                    "thread_id": r["thrid"],
                    "received_at": r["internal"],
                    "is_read": 1 if "\\Seen" in r["flags"] else 0,
                    "is_starred": 1 if "\\Flagged" in r["flags"] else 0,
                    "in_inbox": 1 if r["uid"] in inbox else 0,
                    "raw": None,
                }
            )
        need = [i["imap_uid"] for i in items if i["uid"] not in have_bodies]
        if need:
            raws = {r["uid"]: _literal(r, b"BODY[") for r in s.fetch(need, "(UID BODY.PEEK[])")}
            for i in items:
                if i["imap_uid"] in raws:
                    i["raw"] = raws[i["imap_uid"]]
    items.sort(key=lambda i: i["imap_uid"])
    return items


# ---- Changing ----

def modify(account, msgids: list[str], action: str, to_inbox: bool = True) -> None:
    if not msgids:
        return
    with session(account) as s:
        if action == "untrash":
            s.select("\\Trash")
            uids = [u for u in (s.uid_for_msgid(m) for m in msgids) if u]
            if uids:
                target = "INBOX" if to_inbox else s.folders["\\All"]
                _move(s, uids, target)
            return

        s.select("\\All")
        uids = [u for u in (_imap_uid(s, account["id"], m) for m in msgids) if u]
        if not uids:
            return
        uidset = ",".join(str(u) for u in uids)
        if action == "read":
            s.imap.uid("STORE", uidset, "+FLAGS.SILENT", r"(\Seen)")
        elif action == "unread":
            s.imap.uid("STORE", uidset, "-FLAGS.SILENT", r"(\Seen)")
        elif action == "star":
            s.imap.uid("STORE", uidset, "+FLAGS.SILENT", r"(\Flagged)")
        elif action == "unstar":
            s.imap.uid("STORE", uidset, "-FLAGS.SILENT", r"(\Flagged)")
        elif action == "archive":
            s.imap.uid("STORE", uidset, "-X-GM-LABELS", r"(\Inbox)")
        elif action == "inbox":
            s.imap.uid("STORE", uidset, "+X-GM-LABELS", r"(\Inbox)")
        elif action == "trash":
            _move(s, uids, s.folders["\\Trash"])
        else:
            raise ValueError(action)


def _move(s: _Session, uids: list[int], target: str):
    uidset = ",".join(str(u) for u in uids)
    typ, data = s.imap.uid("MOVE", uidset, _quote(target))
    if typ != "OK":
        # Servers without MOVE: copy, then flag and expunge the originals.
        s.imap.uid("COPY", uidset, _quote(target))
        s.imap.uid("STORE", uidset, "+FLAGS.SILENT", r"(\Deleted)")
        s.imap.expunge()


# ---- Sending ----

def send(account, mime_msg) -> None:
    password = decrypt_password(account["app_password_enc"])
    try:
        with smtplib.SMTP_SSL(account["smtp_host"], 465) as smtp:
            smtp.login(account["email_address"], password)
            smtp.send_message(mime_msg, from_addr=account["email_address"], to_addrs=recipients_of(mime_msg))
    except smtplib.SMTPException as exc:
        raise EmailAuthError(f"Could not send: {exc}") from exc
    except OSError as exc:
        raise EmailAuthError(f"Could not reach {account['smtp_host']}: {exc}") from exc


def test_login(email_address: str, app_password: str, imap_host: str) -> None:
    try:
        with imaplib.IMAP4_SSL(imap_host) as imap:
            imap.login(email_address, app_password)
    except imaplib.IMAP4.error as exc:
        raise EmailAuthError(
            f"Login failed for {email_address}: {exc}. "
            "Double-check the address and app password, and that 2-Step Verification is on."
        ) from exc
    except OSError as exc:
        raise EmailAuthError(f"Could not reach {imap_host}: {exc}") from exc
