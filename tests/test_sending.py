"""How outgoing mail is built: threading headers, quoting, Cc/Bcc, forwarding
attachments, sending from another account, and the size limit. Nothing is sent:
the SMTP sender is replaced with a list."""
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["HOUSEHOLD_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "send.db")

import fake_gmail as fg  # noqa: E402
from app import db  # noqa: E402
from app.mail import email_client, imap_gmail

FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


db.init_db()
c = db.get_conn()
c.execute("DELETE FROM email_accounts")
for i, addr in ((1, "house@example.com"), (2, "sam@example.com")):
    c.execute("INSERT INTO email_accounts (id,email_address,display_name,app_password_enc,auth_method,sync_version) "
              "VALUES (?,?,?,X'','app_password',2)", (i, addr, addr.split("@")[0].title()))
c.commit()
fg.FAKE.sync(db.get_email_account(1))
out = []
imap_gmail.send = lambda acct, msg: out.append(msg)
import importlib  # noqa: E402

importlib.reload(email_client)  # undo fake_gmail's send stub so the real builder runs
email_client._backend = lambda a: fg.FAKE
a, b = db.get_email_account(1), db.get_email_account(2)

email_client.send_mail(a, "forward", "friend@example.com", "", "Fwd: statement", "FYI", ref_uid="m1")
f = out[-1]
ok([p.get_filename() for p in f.iter_attachments()] == ["statement-sept.pdf"], "forward carries the original's attachment")
ok("---------- Forwarded message" in f.get_body(("plain",)).get_content() and f["In-Reply-To"] is None, "forward has the forwarded header and isn't threaded")

email_client.send_mail(a, "replyall", "Mom <mom@example.com>", "sam@example.com, dad@example.com", "Re: Sunday dinner?",
                       "We will be there!", ref_uid="m5", include_quote=True)
r = out[-1]
ok(bool(r["In-Reply-To"]) and bool(r["References"]), "reply is threaded")
ok("> Thinking roast" in r.get_body(("plain",)).get_content(), "reply quotes the original")
ok(imap_gmail.recipients_of(r) == ["mom@example.com", "sam@example.com", "dad@example.com"], "reply-all recipients")

email_client.send_mail(a, "reply", "Mom <mom@example.com>", "", "Re: Sunday dinner?", "Short", ref_uid="m5", include_quote=False)
ok("wrote:" not in out[-1].get_body(("plain",)).get_content(), "quote can be left out")

email_client.send_mail(b, "forward", "friend@example.com", "", "Fwd", "FYI", ref_uid="m1", ref_account=a, bcc="hidden@example.com",
                       uploads=[("notes.txt", "text/plain", b"hello")], forward_indexes=[6])
f = out[-1]
ok(f["From"] == "sam@example.com", "can send from a different account than the one that received it")
ok([p.get_filename() for p in f.iter_attachments()] == ["statement-sept.pdf", "notes.txt"], "chosen attachment plus uploaded file")
ok("hidden@example.com" in imap_gmail.recipients_of(f), "Bcc recipients get the message")

email_client.send_mail(b, "forward", "friend@example.com", "", "Fwd", "FYI", ref_uid="m1", ref_account=a, forward_indexes=[])
ok(list(out[-1].iter_attachments()) == [], "unticking every attachment forwards none")

try:
    email_client.send_mail(a, "new", "x@example.com", "", "Big", "x", uploads=[("big.bin", "application/octet-stream", b"0" * (25 * 1024 * 1024))])
    ok(False, "oversize attachments refused")
except email_client.EmailAuthError:
    ok(True, "oversize attachments refused")

sys.exit(1 if FAILED else 0)
