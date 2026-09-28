"""Guards on the shape of the code, so it stays easy to work on:

- no source file in app/ grows past MAX_LINES (split it into its own module instead);
- every file a template links under /static/ exists;
- every route needs a login, except the ones listed in PUBLIC. This walks the
  real route table, so a new route can't end up public by accident.
"""
import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["HOUSEHOLD_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "structure.db")
os.environ.setdefault("SESSION_SECRET", "structure-test-secret")

FAILED = []
MAX_LINES = 450
# (method, path) pairs that answer without a login.
PUBLIC = {("GET", "/login"), ("POST", "/login")}


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


# ---- file sizes
big = []
for p in (ROOT / "app").rglob("*"):
    if p.suffix in (".py", ".js", ".css", ".html") and p.is_file():
        n = len(p.read_text(encoding="utf-8").splitlines())
        if n > MAX_LINES:
            big.append(f"{p.relative_to(ROOT)} ({n})")
ok(not big, f"no app file over {MAX_LINES} lines" + (": " + ", ".join(big) if big else ""))

# ---- static references
missing = []
for t in (ROOT / "app/templates").glob("*.html"):
    for ref in re.findall(r"""/static/([\w./-]+)""", t.read_text(encoding="utf-8")):
        if not (ROOT / "app/static" / ref).is_file():
            missing.append(f"{t.name}: {ref}")
ok(not missing, "every /static/ file a template uses exists" + (": " + ", ".join(missing) if missing else ""))

# ---- every route needs a login
from fastapi.routing import APIRoute  # noqa: E402
from starlette.routing import Route  # noqa: E402

from app import db  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()


async def call(method: str, path: str):
    """One request straight into the ASGI app, no session cookie. Returns (status, location)."""
    scope = {"type": "http", "http_version": "1.1", "method": method, "path": path, "raw_path": path.encode(),
             "query_string": b"", "headers": [(b"host", b"test")], "scheme": "http",
             "server": ("test", 80), "client": ("127.0.0.1", 1), "root_path": "", "app": app}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(msg):
        sent.append(msg)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    return start["status"], headers.get("location", "")


def walk(routes, prefix=""):
    """(method, path) for every endpoint, looking inside included routers
    (newer FastAPI keeps them as lazy _IncludedRouter wrappers)."""
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from walk(inner.routes, prefix + r.include_context.prefix)
        elif isinstance(r, (APIRoute, Route)) and r.methods:
            for m in r.methods - {"HEAD", "OPTIONS"}:
                yield m, prefix + r.path


leaks = []
routes = 0
for m, raw in sorted(set(walk(app.routes))):
    routes += 1
    status, loc = asyncio.run(call(m, re.sub(r"\{[^}]+\}", "1", raw)))
    gated = status == 303 and loc == "/login"
    if gated == ((m, raw) in PUBLIC):
        leaks.append(f"{m} {raw} -> {status}")
ok(routes > 50, f"route table walked ({routes} routes)")
ok(not leaks, "only PUBLIC routes answer without a login" + (": " + ", ".join(leaks) if leaks else ""))

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all passed'}")
sys.exit(1 if FAILED else 0)
