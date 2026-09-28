"""Guards for the speed work, so it can't quietly regress:
WAL mode + indexes (and that the hot queries use them), the one-query header
badges, weather never making a page wait on the network, and gzip on text but
not on media."""
import asyncio
import gzip
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["HOUSEHOLD_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "eff.db")
os.environ.setdefault("SESSION_SECRET", "efficiency-test-secret-0123456789")
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


from app import db, weather  # noqa: E402

db.init_db()
conn = db.get_conn()
ok(conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal", "database is in WAL mode")
names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
ok({"ix_msg_view", "ix_msg_newest", "ix_list_items_list", "ix_comments_post"} <= names, "indexes exist")


def plan(sql, *args):
    return " ".join(r[-1] for r in conn.execute("EXPLAIN QUERY PLAN " + sql, args))


ok("ix_msg_view" in plan(db.badges.UNREAD_SQL), "unread badge uses an index")
ok("ix_list_items_list" in plan("SELECT * FROM list_items WHERE list_id = ? AND deleted = 0", 1), "list items use an index")
conn.close()

# ---- header badges: one call, same numbers as the single counters
db.create_bill("Test", 0, "2000-01-01", "none")
db.add_list_item(db.lists_summary()[0]["id"], "milk")
c = db.nav_counts("2030-01-01", None)
ok(c == {"due": db.count_open_bills_through("2030-01-01"), "unread": db.count_unread_messages(),
         "list": db.count_list_to_get(), "share": 0} and c["due"] == 1 and c["list"] == 1,
   "nav_counts matches the single counters")

# ---- weather: a stale cache is shown at once, refreshed in the background
db.set_setting("weather_lat", "40")
db.set_setting("weather_lon", "-90")
stale = {"temp": 50, "units": "f", "hourly": [], "forecast": []}
db.set_setting("weather_cache_json", __import__("json").dumps(stale))
db.set_setting("weather_cache_at", "2000-01-01T00:00:00+00:00")
calls = []


def slow_fetch(lat, lon, units):
    calls.append(1)
    time.sleep(1.5)
    return dict(stale, temp=60)


weather._fetch_forecast = slow_fetch
t0 = time.time()
w = weather.current()
ok(time.time() - t0 < 0.3 and w["temp"] == 50, "stale weather returns immediately (no network wait)")
time.sleep(2)
ok(calls and weather.current()["temp"] == 60, "...and was refreshed in the background")

# ---- gzip on text, not on media
from app.main import app  # noqa: E402


async def get(path: str, extra=()):
    scope = {"type": "http", "http_version": "1.1", "method": "GET", "path": path, "raw_path": path.encode(),
             "query_string": b"v=1", "headers": [(b"host", b"t"), (b"accept-encoding", b"gzip"), *extra],
             "scheme": "http", "server": ("t", 80), "client": ("127.0.0.1", 1), "root_path": "", "app": app}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return {k.decode(): v.decode() for k, v in start["headers"]}, body


h, body = asyncio.run(get("/static/css/inbox.css"))
ok(h.get("content-encoding") == "gzip" and b"Inbox" in gzip.decompress(body), "CSS is sent gzipped")
ok("immutable" in h.get("cache-control", ""), "versioned static files are cached for good")
h, _ = asyncio.run(get("/static/fonts/inter-latin.woff2"))
ok("content-encoding" not in h, "fonts (already compressed) are not gzipped")
h, _ = asyncio.run(get("/static/css/inbox.css", [(b"range", b"bytes=0-99")]))
ok("content-encoding" not in h, "range requests are not gzipped")

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all passed'}")
sys.exit(1 if FAILED else 0)
