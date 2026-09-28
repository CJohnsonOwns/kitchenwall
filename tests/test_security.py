"""Security behaviour, against a real server (fake Gmail, throwaway DB):
headers, cross-site write blocking, login brake, public paths, API docs off,
upload disk guard, the sandboxed email frame, and refusing to start with a
weak session secret. Different client IPs are simulated with X-Forwarded-For,
which uvicorn trusts only from 127.0.0.1 (as it would from a local proxy)."""
import http.client
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
env = dict(os.environ, HOUSEHOLD_PASSWORD="changeme", SESSION_SECRET="security-test-secret-0123456789")
server = subprocess.Popen([sys.executable, str(HERE / "fake_gmail.py"), os.path.join(tempfile.mkdtemp(), "sec.db"), str(port)],
                          env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
b = f"http://127.0.0.1:{port}"
try:
    for _ in range(60):
        try:
            requests.get(b + "/login", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.25)

    # ---- headers
    r = requests.get(b + "/login")
    h = r.headers
    ok("script-src 'self'" in h.get("content-security-policy", "") and "frame-ancestors 'none'" in h["content-security-policy"],
       "CSP on pages: scripts from this site only, no framing")
    ok(h.get("x-frame-options") == "DENY" and h.get("x-content-type-options") == "nosniff", "X-Frame-Options + nosniff")
    ok(h.get("referrer-policy") == "same-origin", "Referrer-Policy same-origin")
    ok("strict-transport-security" not in h, "no HSTS on plain http")
    ok("no-transform" in h.get("cache-control", ""), "pages say no-transform (Cloudflare must not rewrite them)")
    ok(requests.get(b + "/static/manifest.json").json()["display"] == "fullscreen", "installable app manifest is public")
    ok("unsafe-inline" not in h["content-security-policy"].split("script-src")[1].split(";")[0], "no inline script allowed")

    # ---- public paths + docs
    for path in ("/loginx", "/login/../settings", "/staticx", "/docs", "/openapi.json", "/redoc"):
        r = requests.get(b + path, allow_redirects=False)
        ok(r.status_code in (303, 404) and (r.status_code == 404 or r.headers["location"] == "/login"), f"{path} is not public")

    s = requests.Session()
    s.post(b + "/login", data={"password": "changeme"})
    ok(s.get(b + "/", allow_redirects=False).status_code == 200, "household login works")
    ok(s.get(b + "/docs").status_code == 404 and s.get(b + "/openapi.json").status_code == 404, "API docs are off")

    # ---- cross-site writes
    evil = {"Origin": "http://evil.example"}
    r = s.post(b + "/logout", headers=evil, allow_redirects=False)
    ok(r.status_code == 403, "POST with a foreign Origin is refused")
    ok(s.get(b + "/", allow_redirects=False).status_code == 200, "...and did nothing (still signed in)")
    ok(s.post(b + "/logout", headers={"Sec-Fetch-Site": "cross-site"}, allow_redirects=False).status_code == 403,
       "Sec-Fetch-Site: cross-site is refused")
    ok(s.post(b + "/logout", headers={"Referer": "http://evil.example/x"}, allow_redirects=False).status_code == 403,
       "foreign Referer (no Origin) is refused")
    ok(s.post(b + "/logout", headers={"Origin": "null"}, allow_redirects=False).status_code == 403, "Origin: null is refused")
    r = s.patch(b + "/board/items/1/position", json={"x": 1, "y": 1}, headers=evil)
    ok(r.status_code == 403, "PATCH from another site is refused too")

    # ---- email body frame never runs script
    t = s.get(b + "/inbox/m/1/m1").text
    ok('sandbox="' in t and "allow-scripts" not in t, "email frame is sandboxed without allow-scripts")

    # ---- upload bigger than the free disk
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    c.putrequest("POST", "/share/posts")
    c.putheader("Content-Type", "multipart/form-data; boundary=x")
    c.putheader("Content-Length", str(10 ** 15))
    c.putheader("Cookie", "; ".join(f"{k}={v}" for k, v in s.cookies.items()))
    c.endheaders()
    ok(c.getresponse().status == 413, "an upload bigger than the free disk is refused before it's stored")
    c.close()

    ok(s.post(b + "/logout", headers={"Origin": b}, allow_redirects=False).status_code == 303, "same-site POST still works")

    # ---- login brake (per IP)
    ip_a, ip_b = {"X-Forwarded-For": "203.0.113.7"}, {"X-Forwarded-For": "203.0.113.8"}
    codes = [requests.post(b + "/login", data={"password": "wrong"}, headers=ip_a, allow_redirects=False).status_code
             for _ in range(10)]
    ok(codes == [401] * 10, "ten wrong passwords are just wrong passwords")
    r = requests.post(b + "/login", data={"password": "changeme"}, headers=ip_a, allow_redirects=False)
    ok(r.status_code == 429 and int(r.headers.get("retry-after", "0")) > 0, "11th try from that IP waits (429 + Retry-After), even with the right password")
    r = requests.post(b + "/login", data={"password": "changeme"}, headers=ip_b, allow_redirects=False)
    ok(r.status_code == 303, "another device still signs in (no account lockout)")
finally:
    server.terminate()

# ---- refuses to start with a weak secret
probe = ("import asyncio, app.main as m\n"
         "async def go():\n"
         "    async with m.lifespan(m.app):\n"
         "        pass\n"
         "asyncio.run(go())\n")
for secret in ("", "dev-secret-change-me", "short"):
    r = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True,
                       env=dict(os.environ, SESSION_SECRET=secret, HOUSEHOLD_DB_PATH=os.path.join(tempfile.mkdtemp(), "x.db")))
    ok(r.returncode != 0 and "SESSION_SECRET" in r.stderr, f"won't start with SESSION_SECRET={secret!r}")
r = subprocess.run([sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True,
                   env=dict(os.environ, SESSION_SECRET="a-long-random-test-secret-123456", HOUSEHOLD_PASSWORD="changeme",
                            COOKIE_SECURE="1", HOUSEHOLD_DB_PATH=os.path.join(tempfile.mkdtemp(), "x.db")))
ok(r.returncode != 0 and "HOUSEHOLD_PASSWORD" in r.stderr, "won't serve over https with the 'changeme' password")

# ---- https mode: plain-http visits from other devices go to the https address
redirect_probe = (
    "import asyncio, app.main as m\n"
    "async def call(client, scheme):\n"
    "    sent = []\n"
    "    scope = {'type': 'http', 'http_version': '1.1', 'method': 'GET', 'path': '/inbox', 'raw_path': b'/inbox',\n"
    "             'query_string': b'view=sent', 'headers': [(b'host', b'kitchenwall.lan:8000')], 'scheme': scheme,\n"
    "             'server': ('kitchenwall.lan', 8000), 'client': (client, 5), 'root_path': '', 'app': m.app}\n"
    "    async def receive(): return {'type': 'http.request', 'body': b'', 'more_body': False}\n"
    "    async def send(msg): sent.append(msg)\n"
    "    await m.app(scope, receive, send)\n"
    "    s = sent[0]; return s['status'], dict(s['headers']).get(b'location', b'').decode()\n"
    "for c, s in (('192.168.1.20', 'http'), ('127.0.0.1', 'http'), ('203.0.113.5', 'https')): print(asyncio.run(call(c, s)))\n"
)
r = subprocess.run([sys.executable, "-c", redirect_probe], cwd=ROOT, capture_output=True, text=True,
                   env=dict(os.environ, SESSION_SECRET="a-long-random-test-secret-123456", HOUSEHOLD_PASSWORD="a-strong-test-password",
                            COOKIE_SECURE="1", PUBLIC_ORIGIN="https://home.example.com",
                            HOUSEHOLD_DB_PATH=os.path.join(tempfile.mkdtemp(), "x.db")))
lines = r.stdout.strip().splitlines() + ["", "", ""]
ok(lines[0] == "(308, 'https://home.example.com/inbox?view=sent')", "https mode: an http visit from another device is sent to the https address")
ok(lines[1] == "(303, '/login')", "...but localhost (tunnel, deploy health check) is not redirected")
ok(lines[2] == "(303, '/login')", "...and https requests go straight through")

# ---- the add-account form can't pick the mail servers
sys.path.insert(0, str(ROOT))
from app.routers.email import accounts  # noqa: E402
import inspect  # noqa: E402

params = inspect.signature(accounts.add_account).parameters
ok("imap_host" not in params and "smtp_host" not in params, "mail servers are fixed to Gmail, not taken from the form")

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all passed'}")
sys.exit(1 if FAILED else 0)
