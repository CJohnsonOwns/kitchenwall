"""The dashboard with an in-memory fake Gmail, for UI and flow testing.

    python tests/fake_gmail.py <throwaway.db> [port]     # then open http://127.0.0.1:<port>, password "changeme"

Nothing talks to Google: the backend is swapped for `Fake`, and sending is
recorded instead of sent (see /__test/sent). Never point this at the real DB.
"""
import os
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if len(sys.argv) > 1 and __name__ == "__main__":
    os.environ["HOUSEHOLD_DB_PATH"] = sys.argv[1]
os.environ.setdefault("HOUSEHOLD_PASSWORD", "changeme")
os.environ.setdefault("SESSION_SECRET", "test-only-secret")

from app import db, main  # noqa: E402
from app.mail import email_client
from app.mail.mail_mime import parse_raw  # noqa: E402

SENT_LOG = []
ME = {1: "house@example.com", 2: "sam@example.com"}


def mk(frm, to, subject, text=None, html=None, when=0, cc=None, reply_to=None, in_reply_to=None, attach=None, inline_img=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    if cc:
        m["Cc"] = cc
    if reply_to:
        m["Reply-To"] = reply_to
    m["Date"] = format_datetime((datetime.now() - timedelta(hours=when)).astimezone())
    mid = make_msgid(domain="example.com")
    m["Message-ID"] = mid
    if in_reply_to:
        m["In-Reply-To"] = in_reply_to
    m.set_content(text or "See the HTML version.")
    if html:
        m.add_alternative(html, subtype="html")
        if inline_img:
            png = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201ff2be45a0000000049454e44ae426082")
            m.get_payload()[1].add_related(png, maintype="image", subtype="png", cid="<logo@x>")
    for fn, mime, data in attach or []:
        mt, st = mime.split("/")
        m.add_attachment(data, maintype=mt, subtype=st, filename=fn)
    return m, mid


class Fake:
    def __init__(self):
        self.msgs = {1: {}, 2: {}}
        n = 0

        def add(acct, thread, msg, labels, hours):
            nonlocal n
            n += 1
            uid = f"m{n}"
            self.msgs[acct][uid] = {"raw": msg.as_bytes(), "thread": thread, "labels": set(labels), "hours": hours}
            return uid

        pdf = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"
        m, _ = mk("City Power & Light <billing@power.example.com>", "house@example.com", "Your September statement is ready",
                  html="<div style='font-family:Arial'><h2>Statement ready</h2><p>Your statement is ready. <a href='https://example.com/pay'>View it online</a>.</p><img src='cid:logo@x' alt='logo'><p>" + "Details line. " * 40 + "</p></div>",
                  when=2, inline_img=True, attach=[("statement-sept.pdf", "application/pdf", pdf)])
        add(1, "t1", m, {"INBOX", "UNREAD"}, 2)
        m1, id1 = mk("Dr. Patel's Office <front@patel.com>", "sam@example.com", "Appointment reminder: Tue 9:30 AM",
                     text="Hello Sam,\n\nThis is a reminder of your appointment on Tuesday at 9:30 AM.\nReply C to confirm.\n\nhttps://patel.example.com/confirm", when=30)
        add(2, "t2", m1, {"INBOX"}, 30)
        m2, id2 = mk("Sam <sam@example.com>", "front@patel.com", "Re: Appointment reminder: Tue 9:30 AM",
                     text="C\n\nOn Tue, Dr. Patel's Office wrote:\n> Hello Sam,\n> Reply C to confirm.", when=28, in_reply_to=id1)
        add(2, "t2", m2, {"SENT"}, 28)
        m3, _ = mk("Dr. Patel's Office <front@patel.com>", "sam@example.com", "Re: Appointment reminder: Tue 9:30 AM",
                   text="Thanks, you're confirmed! See you Tuesday.", when=4, in_reply_to=id2, reply_to="appointments@patel.com")
        add(2, "t2", m3, {"INBOX", "UNREAD"}, 4)
        m, _ = mk("Mom <mom@example.com>", "house@example.com", "Sunday dinner?", cc="sam@example.com, dad@example.com",
                  text="Thinking roast and the good potatoes. Bring Biscuit!\n\nLove, Mom", when=26,
                  attach=[("biscuit.png", "image/png", bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000" "1f15c4890000000d49444154789c6360f8cfc0f01f0005000201ff2be45a0000000049454e44ae426082"))])
        add(1, "t3", m, {"INBOX", "STARRED"}, 26)
        m, _ = mk("Chewy <no-reply@chewy.com>", "house@example.com", "Biscuit's autoship ships tomorrow", text="Your order ships tomorrow.", when=6)
        add(1, "t4", m, {"INBOX", "UNREAD"}, 6)
        m, _ = mk("house@example.com", "dan@fence.example.com", "Fence quote", text="Hi Dan, could you send the revised quote?", when=50)
        add(1, "t5", m, {"SENT"}, 50)
        m, _ = mk("Shop Newsletter <deals@shop.example.com>", "house@example.com", "Fall sale",
                  html="<h2>Fall sale</h2><p>20% off.</p><img src='https://picsum.photos/seed/hd/400/120' alt='banner' width='400' height='120'><img src='https://track.example.com/open.gif' width='1' height='1'>",
                  when=1)
        add(1, "t9", m, {"INBOX", "UNREAD"}, 1)
        for i in range(8):
            m, _ = mk(f"Newsletter {i} <news{i}@example.com>", "house@example.com", f"Weekly update #{i}", text=f"Update number {i}.", when=60 + i * 10)
            add(1, f"n{i}", m, {"INBOX"} if i < 6 else {"INBOX", "UNREAD"}, 60 + i * 10)

    # --- backend API ---
    def row(self, acct, uid):
        rec = self.msgs[acct][uid]
        p = parse_raw(rec["raw"])
        L = rec["labels"]
        return {
            "uid": uid, "thread_id": rec["thread"], "message_id": p["headers"]["message_id"], "sender": p["headers"]["from"],
            "to_addrs": p["headers"]["to"], "subject": p["headers"]["subject"], "date_header": p["headers"]["date"],
            "received_at": (datetime.now() - timedelta(hours=rec["hours"])).astimezone().isoformat(), "snippet": p["snippet"],
            "is_read": 0 if "UNREAD" in L else 1, "in_inbox": int("INBOX" in L), "in_sent": int("SENT" in L),
            "is_starred": int("STARRED" in L), "is_trashed": int("TRASH" in L), "imap_uid": None,
        }

    def sync(self, account):
        a = account["id"]
        keep = [u for u, r in self.msgs[a].items() if r["labels"] & {"INBOX", "SENT", "STARRED"} and "TRASH" not in r["labels"]]
        cached = db.cached_messages(a)
        db.delete_messages(a, [u for u in cached if u not in keep])
        db.upsert_messages(a, [self.row(a, u) for u in keep])
        db.set_account_fields(a, sync_version=2)

    def fetch_older(self, account, view, count=50):
        return 0

    def search(self, account, q, limit=40):
        a = account["id"]
        q = q.lower()
        return [self.row(a, u) for u, r in self.msgs[a].items() if q in r["raw"].decode(errors="ignore").lower()][:limit]

    def get_raw(self, account, uid):
        return self.msgs[account["id"]][uid]["raw"]

    def thread_messages(self, account, uid, have):
        a = account["id"]
        t = self.msgs[a][uid]["thread"]
        items = []
        for u, r in sorted(self.msgs[a].items(), key=lambda kv: -kv[1]["hours"]):
            if r["thread"] == t:
                row = self.row(a, u)
                row["raw"] = None if u in have else r["raw"]
                items.append(row)
        return items

    def modify(self, account, uids, action, to_inbox=True):
        a = account["id"]
        for u in uids:
            L = self.msgs[a][u]["labels"]
            {"read": lambda: L.discard("UNREAD"), "unread": lambda: L.add("UNREAD"), "star": lambda: L.add("STARRED"),
             "unstar": lambda: L.discard("STARRED"), "archive": lambda: L.discard("INBOX"), "inbox": lambda: L.add("INBOX"),
             "trash": lambda: L.add("TRASH"), "untrash": lambda: (L.discard("TRASH"), to_inbox and L.add("INBOX"))}[action]()


FAKE = Fake()
email_client._backend = lambda account: FAKE


def fake_send(account, mode, to, cc, subject, body, ref_uid=None, include_quote=True, include_attachments=True, **kw):
    SENT_LOG.append(dict(account=account["id"], mode=mode, to=to, cc=cc, subject=subject, body=body, ref=ref_uid,
                         quote=include_quote, bcc=kw.get("bcc"), ref_account=kw.get("ref_account") and kw["ref_account"]["id"],
                         uploads=[(n, len(d)) for n, _, d in kw.get("uploads", [])], fwd=kw.get("forward_indexes")))
    print("SENT", SENT_LOG[-1], flush=True)


email_client.send_mail = fake_send

def seed_household():
    """Calendar items, categories, notes and a doodle, dated relative to today."""
    import datetime as dt

    c = db.get_conn()
    today = dt.date.today()
    d = lambda n: (today + dt.timedelta(days=n)).isoformat()
    for t in ("bills", "board_categories", "board_items", "board_item_categories", "whiteboard_strokes"):
        c.execute(f"DELETE FROM {t}")
    for name, due, rec, paid in [
        ("Water", d(-3), "monthly", 0), ("Furnace tune-up", d(0), "yearly", 0), ("Electric", d(3), "monthly", 0),
        ("Trash pickup", d(5), "quarterly", 0), ("Mortgage", d(6), "monthly", 0), ("Internet", d(8), "monthly", 0),
        ("Dentist - Sam", d(11), "none", 0), ("Gas", d(-7), "monthly", 1),
    ]:
        c.execute("INSERT INTO bills (name, amount, due_date, recurring, paid) VALUES (?, 0, ?, ?, ?)", (name, due, rec, paid))
    for n, col in [("Home repair", "#e0913f"), ("Groceries", "#6fae7b"), ("Outdoors", "#4fa3a0"), ("Errands", "#5b8fd9")]:
        c.execute("INSERT INTO board_categories (name, color) VALUES (?, ?)", (n, col))
    cats = {r["name"]: r["id"] for r in c.execute("SELECT id, name FROM board_categories")}
    notes = [("Fix upstairs sink plumbing", "#fff7b2", 60, 90, 20, ["Home repair"], ""),
             ("Potting soil + 2 bags of mulch", "#c7f0c2", 560, 110, 0, ["Groceries", "Outdoors"], ""),
             ("Eggs, oat milk, basil, coffee filters", "#fff7b2", 440, 340, 0, ["Groceries"], "Sam"),
             ("Screw in dining room table", "#fff7b2", 20, 20, 30, ["Home repair"], "")]
    for i, (text, color, x, y, age, cs, by) in enumerate(notes):
        ts = (dt.datetime.utcnow() - dt.timedelta(days=age)).strftime("%Y-%m-%d %H:%M:%S")
        cur = c.execute("INSERT INTO board_items (text, color, x, y, item_type, checked, created_by, created_at, touched_at) "
                        "VALUES (?,?,?,?,'note',?,?,?,?)", (text, color, x, y, 1 if i == 3 else 0, by, ts, ts))
        for cn in cs:
            c.execute("INSERT INTO board_item_categories VALUES (?, ?)", (cur.lastrowid, cats[cn]))
    c.execute("INSERT INTO whiteboard_strokes (path, color, width) VALUES ('M 360 170 L 410 140 L 500 180', '#d9a441', 4)")
    c.commit()


def seed_everything():
    db.init_db()
    seed_household()
    seed_users()
    c = db.get_conn()
    c.execute("DELETE FROM email_messages"); c.execute("DELETE FROM email_bodies"); c.execute("DELETE FROM email_accounts")
    c.execute("INSERT INTO email_accounts (id, email_address, display_name, app_password_enc, auth_method, sync_version) "
              "VALUES (1, 'house@example.com', 'House', X'', 'app_password', 2)")
    c.execute("INSERT INTO email_accounts (id, email_address, display_name, app_password_enc, auth_method, scopes, sync_version) "
              "VALUES (2, 'sam@example.com', 'Sam', X'', 'oauth', 'https://www.googleapis.com/auth/gmail.readonly', 2)")
    c.commit()
    for a in db.list_email_accounts():
        FAKE.sync(a)
    db.set_account_synced_now(1, datetime.now().isoformat())
    if os.environ.get("SEED_LIST"):  # screenshots want filled lists; the smoke test wants them empty
        seed_weather()
        first = db.lists_summary()[0]["id"]
        for text in ("Eggs", "Oat milk ×2", "Basil", "Coffee filters (the #4 cone ones)", "Dish soap", "Bananas", "Cheddar"):
            db.add_list_item(first, text)
        for item in db.list_items(first)[-2:]:
            db.update_list_item(item["id"], checked=True)
        costco = db.create_list("Costco")
        for text in ("Paper towels", "Olive oil", "Dog food"):
            db.add_list_item(costco, text)
        db.create_list("Hardware store")
        from app import photos
        db.set_board_item_photo(db.list_board_items(include_checked=False)[0]["id"], photos.save(_sample_png()))
        seed_sharing(photos.save(_sample_png(900, 600)))


def seed_users():
    """alex / sam, password 'changeme' (same as the fake household password)."""
    from app.core import auth
    for username, name in (("alex", "Alex"), ("sam", "Sam")):
        db.upsert_user(username, name, auth.hash_password("changeme"))


def seed_sharing(photo_name: str):
    c = db.get_conn()
    ago = lambda **kw: (datetime.utcnow() - timedelta(**kw)).strftime("%Y-%m-%d %H:%M:%S")
    posts = [
        (1, "Found the recipe from that place downtown. Making it Sunday?", "https://example.com/tomato-soup", None, ago(days=3)),
        (2, "Sunset from the back step tonight", None, photo_name, ago(hours=20)),
        (1, "Idea: we paint the hallway the same green as the kitchen chairs. Thoughts?", None, None, ago(minutes=42)),
    ]
    ids = []
    for uid, body, link, photo, ts in posts:
        cur = c.execute("INSERT INTO posts (user_id, body, link_url, media_name, media_kind, created_at) VALUES (?,?,?,?,?,?)",
                        (uid, body, link, photo, "photo" if photo else None, ts))
        ids.append(cur.lastrowid)
    comments = [
        (ids[0], 2, "Yes! I'll grab the tomatoes.", ago(days=2, hours=20)),
        (ids[1], 1, "Wow. Frame-worthy.", ago(hours=19)),
        (ids[1], 2, "The neighbours' cat photobombed the first ten tries", ago(hours=18)),
        (ids[1], 1, "Ha, of course", ago(hours=18)),
        (ids[1], 2, "Printing it for the fridge", ago(hours=2)),
        (ids[2], 2, "Love it. Swatches this weekend?", ago(minutes=10)),
    ]
    c.executemany("INSERT INTO post_comments (post_id, user_id, body, created_at) VALUES (?,?,?,?)", comments)
    c.executemany("INSERT INTO post_reactions (post_id, user_id, emoji) VALUES (?,?,?)",
                  [(ids[1], 1, "👍"), (ids[1], 1, "❤️"), (ids[0], 2, "👍"), (ids[2], 2, "🎉")])
    c.commit()
    c.close()
    from app import photos
    db.set_user_avatar(2, photos.save(_sample_png(240, 240)))


def _sample_png(w=640, h=420) -> bytes:
    """A plain gradient PNG, so screenshots have a photo on a note without an image library."""
    import struct
    import zlib
    rows = b"".join(b"\x00" + bytes(v for x in range(w) for v in (70 + x * 120 // w, 110 + y * 90 // h, 150 - x * 60 // w))
                    for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def seed_weather():
    """A made-up, fresh forecast for screenshots (no network)."""
    import json
    from datetime import timezone

    from app.settings_store import get_settings
    now = datetime.now()
    hourly = [{"label": "Now" if i == 0 else f"{(now.hour + i) % 12 or 12}{'am' if (now.hour + i) % 24 < 12 else 'pm'}",
               "temp": 64 + (i % 4), "icon": "clear" if i < 3 else "cloudy", "rain": 5 * (i % 3)} for i in range(8)]
    days = [("clear", "Clear", 70, 52, 0), ("cloudy", "Partly cloudy", 66, 50, 10), ("rain", "Rain showers", 59, 47, 70),
            ("cloudy", "Overcast", 61, 45, 20), ("clear", "Clear", 68, 49, 0)]
    forecast = [{"label": (now + timedelta(days=i + 1)).strftime("%a"), "icon": ic, "condition": c, "hi": hi, "lo": lo, "rain": r}
                for i, (ic, c, hi, lo, r) in enumerate(days)]
    db.set_setting("weather_lat", "40")
    db.set_setting("weather_lon", "-90")
    db.set_setting("weather_label", "Springfield")
    db.set_setting("weather_cache_json", json.dumps({
        "temp": 65, "feels_like": 63, "condition": "Mostly clear", "icon": "clear", "wind": 6,
        "wind_unit": "km/h" if get_settings()["units"] == "c" else "mph", "hi": 71, "lo": 50,
        "hourly": hourly, "forecast": forecast, "units": get_settings()["units"]}))
    db.set_setting("weather_cache_at", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    import uvicorn

    if Path(sys.argv[1]).resolve() == (ROOT / "data" / "household.db").resolve():
        raise SystemExit("Refusing to run the fake server against the real database.")
    seed_everything()
    main.app.add_api_route("/__test/sent", lambda: SENT_LOG)
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8010
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")
