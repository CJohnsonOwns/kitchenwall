"""Unit tests for the mail backends: IMAP response parsing, Gmail history sync,
scope handling, and login/session checks. No network, throwaway database."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
tmp = os.path.join(tempfile.mkdtemp(), "u.db")
os.environ["HOUSEHOLD_DB_PATH"] = tmp
os.environ["HOUSEHOLD_PASSWORD"] = "correct-horse-battery"
os.environ["SESSION_SECRET"] = "unit-test-secret"

from app.core import auth  # noqa: E402
from app import db
from app.mail import google_oauth, imap_gmail
from app.mail.mail_utils import ScopeError  # noqa: E402
from app.core.web_utils import safe_next  # noqa: E402

db.init_db()
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


# ---- Login / sessions / redirects ----
class _Req:
    def __init__(self, session):
        self.session = session


ok(auth.password_matches("correct-horse-battery") and not auth.password_matches("wrong"), "password check")
good = {"authenticated": True, "pw": auth.password_fingerprint()}
ok(auth.is_authenticated(_Req(good)), "fresh session accepted")
ok(not auth.is_authenticated(_Req({"authenticated": True})), "session without password fingerprint rejected")
auth.HOUSEHOLD_PASSWORD = "a-new-password-2026"
ok(not auth.is_authenticated(_Req(good)), "changing the password signs out existing sessions")
auth.HOUSEHOLD_PASSWORD = "correct-horse-battery"

# Personal logins
h = auth.hash_password("pan-galactic-9")
ok(h.startswith("scrypt$") and auth.verify_password("pan-galactic-9", h), "scrypt hash round-trips")
ok(not auth.verify_password("pan-galactic-8", h) and not auth.verify_password("x", "garbage"), "wrong password / bad hash refused")
ok(auth.hash_password("pan-galactic-9") != h, "each hash gets its own salt")
db.upsert_user("alex", "Alex", h)
u = db.get_user_by_name("ALEX")
ok(u is not None and u["display_name"] == "Alex", "usernames are case-insensitive")
mine = {"authenticated": True, "uid": u["id"], "pw": auth.user_fingerprint(u)}
signed, who = auth.session_user(_Req(mine))
ok(signed and who["id"] == u["id"], "personal session accepted and knows who")
ok(auth.session_user(_Req(good)) == (True, None), "household session is still accepted (no person)")
ok(not auth.is_authenticated(_Req({"authenticated": True, "uid": u["id"], "pw": auth.password_fingerprint()})),
   "household fingerprint can't be reused for a person")
ok(not auth.is_authenticated(_Req({"authenticated": True, "uid": 999, "pw": "x"})), "unknown user id rejected")
db.set_user_password(u["id"], auth.hash_password("new-password-2026"))
ok(not auth.is_authenticated(_Req(mine)), "changing your password signs out your old sessions")
ok(auth.is_authenticated(_Req(good)), "... but not the household login")

ok(safe_next("/inbox?x=1", "/d") == "/inbox?x=1", "same-site redirect allowed")
ok(all(safe_next(u, "/d") == "/d" for u in ("//evil.com", "/\\evil.com", "https://evil.com", "", None)), "off-site redirects refused")

# ---- IMAP response parsing (shapes as imaplib returns them from Gmail) ----
data = [
    (b'1 (UID 501 X-GM-MSGID 1790000000000000001 X-GM-THRID 1790000000000000009 FLAGS (\\Seen \\Flagged) '
     b'INTERNALDATE "25-Sep-2026 10:00:00 +0000" BODY[HEADER.FIELDS (FROM TO CC SUBJECT DATE MESSAGE-ID CONTENT-TYPE CONTENT-TRANSFER-ENCODING)] {120}',
     b"From: A <a@x.com>\r\nTo: me@x.com\r\nSubject: =?utf-8?q?Caf=C3=A9?=\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n"),
    (b" BODY[TEXT]<0> {20}", b"Hello there, friend"),
    b")",
    (b'2 (UID 502 X-GM-MSGID 1790000000000000002 X-GM-THRID 1790000000000000002 FLAGS () INTERNALDATE "25-Sep-2026 11:00:00 +0000" BODY[HEADER.FIELDS (FROM)] {20}',
     b"From: b@y.com\r\n\r\n"),
    (b" BODY[TEXT]<0> {5}", b"Hi yo"),
    b")",
]
recs = imap_gmail._parse_fetch(data)
ok(len(recs) == 2, "two FETCH records parsed")
ok(recs[0]["uid"] == 501 and recs[0]["msgid"] == "1790000000000000001" and recs[0]["thrid"] == "1790000000000000009", "UID / X-GM-MSGID / X-GM-THRID")
ok("\\Seen" in recs[0]["flags"] and "\\Flagged" in recs[0]["flags"] and recs[1]["flags"] == [], "FLAGS")
row = imap_gmail._row_from_record(recs[0], {"inbox": {501}, "sent": set(), "starred": set()})
ok(row["subject"] == "Café" and row["snippet"] == "Hello there, friend" and row["is_read"] == 1 and row["is_starred"] == 1 and row["in_inbox"] == 1, f"row from record: {row['subject']!r} {row['snippet']!r}")
flags_only = imap_gmail._parse_fetch([b"3 (UID 7 FLAGS (\\Seen))", b"4 (UID 9 FLAGS ())"])
ok([r["uid"] for r in flags_only] == [7, 9], "flags-only FETCH lines")


class FakeImap:
    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\All \\HasNoChildren) "/" "[Google Mail]/All Mail"',
                      b'(\\HasNoChildren \\Trash) "/" "[Google Mail]/Bin"', b'(\\HasNoChildren \\Sent) "/" "[Google Mail]/Sent Mail"']


f = imap_gmail._folders(FakeImap())
ok(f["\\All"] == "[Google Mail]/All Mail" and f["\\Trash"] == "[Google Mail]/Bin", f"localized folders found: {f}")

# ---- Gmail API: incremental sync from history, with a fake REST layer ----
aid = db.create_email_account("g@x.com", "G", b"")
db.set_account_fields(aid, history_id="100", sync_version=2)
db.upsert_messages(aid, [
    {"uid": "a", "thread_id": "t", "sender": "x", "subject": "s", "is_read": 0, "in_inbox": 1, "in_sent": 0, "is_starred": 0, "is_trashed": 0},
    {"uid": "b", "thread_id": "t", "sender": "x", "subject": "s", "is_read": 1, "in_inbox": 1, "in_sent": 0, "is_starred": 0, "is_trashed": 0},
    {"uid": "c", "thread_id": "t", "sender": "x", "subject": "s", "is_read": 1, "in_inbox": 1, "in_sent": 0, "is_starred": 0, "is_trashed": 0},
])


class Resp:
    def __init__(self, code, js):
        self.status_code, self._js, self.text, self.content = code, js, str(js), b"x"

    def json(self):
        return self._js


class FakeApi:
    def __init__(self, account):
        self.account = account

    def call(self, method, path, **kw):
        if path == "/history":
            return Resp(200, {"historyId": "150", "history": [
                {"labelsRemoved": [{"message": {"id": "a", "labelIds": ["INBOX"]}}]},           # a read
                {"labelsRemoved": [{"message": {"id": "b", "labelIds": ["CATEGORY_UPDATES"]}}]},  # b archived
                {"labelsAdded": [{"message": {"id": "c", "labelIds": ["TRASH"]}}]},              # c trashed
                {"messagesAdded": [{"message": {"id": "d", "labelIds": ["INBOX", "UNREAD"]}}]},  # d new
                {"messagesAdded": [{"message": {"id": "e", "labelIds": ["DRAFT"]}}]},            # draft ignored
            ]})
        raise AssertionError(path)

    def metadata(self, ids):
        return [{"id": i, "threadId": "t2", "labelIds": ["INBOX", "UNREAD"], "snippet": "It&#39;s new", "internalDate": "1790000000000",
                 "payload": {"headers": [{"name": "From", "value": "N <n@x.com>"}, {"name": "Subject", "value": "New"}]}} for i in ids]


google_oauth._incremental_sync(FakeApi(db.get_email_account(aid)))
c = db.cached_messages(aid)
ok(c["a"]["is_read"] == 1 and c["a"]["in_inbox"] == 1, "history: read state pulled from Gmail")
ok("b" not in c, "history: archived message dropped")
ok("c" not in c, "history: trashed message dropped")
ok("d" in c and c["d"]["snippet"] == "It's new" and c["d"]["is_read"] == 0, "history: new message added with unescaped snippet")
ok("e" not in c, "history: drafts ignored")
ok(db.get_email_account(aid)["history_id"] == "150", "history cursor advanced")


class Expired(FakeApi):
    def call(self, method, path, **kw):
        return Resp(404, {})


try:
    google_oauth._incremental_sync(Expired(db.get_email_account(aid)))
    ok(False, "expired history raises")
except google_oauth.HistoryExpired:
    ok(True, "expired history triggers a full resync")

# ---- Scope handling ----
db.set_account_fields(aid, scopes="https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send")
db.get_conn().execute("UPDATE email_accounts SET auth_method='oauth' WHERE id=?", (aid,)).connection.commit()
acct = db.get_email_account(aid)
ok(google_oauth.can_modify(acct) is False, "old grant detected as read-only")
try:
    google_oauth.modify(acct, ["a"], "archive")
    ok(False, "modify refused")
except ScopeError as e:
    ok("reconnected" in str(e), "archive on a read-only grant explains it needs a reconnect")
db.set_account_fields(aid, scopes=google_oauth.SCOPES)
ok(google_oauth.can_modify(db.get_email_account(aid)) is True, "new grant allows changes")
shutil.rmtree(os.path.dirname(tmp), ignore_errors=True)
sys.exit(1 if FAILED else 0)
