"""Protections for when the app is reachable from outside the house.

- SecurityHeaders: CSP, no framing, nosniff, referrer policy, (HSTS on https).
- SameOriginWrites: rejects state-changing requests that come from another
  site (CSRF), using the Origin / Referer / Sec-Fetch-Site headers every
  current browser sends. No tokens in forms needed.
- HttpsOnly: plain-http visits from other devices go to PUBLIC_ORIGIN.
- DiskGuard: refuses an upload that wouldn't fit on the disk.
- LoginBrake: after LIMIT wrong passwords from one IP within WINDOW seconds,
  that IP waits (429). Accounts are never locked, other devices unaffected.
  Also caps how many password checks run at once (scrypt uses 32 MB each).

Settings (.env): COOKIE_SECURE=1 once the app is served over https (secure
cookie + HSTS); PUBLIC_ORIGIN=https://name.example for the public address, if
a proxy rewrites the Host header. See deploy/EXPOSING.md.
"""
import os
import shutil
import tempfile
import threading
import time
from collections import deque
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "") == "1"
PUBLIC_ORIGIN = os.environ.get("PUBLIC_ORIGIN", "").rstrip("/")

# 'unsafe-inline' is for style="" attributes only (note positions, colours);
# scripts are files from this site, never inline. https: images are for email
# "Show images" (the email frame inherits this policy; until you press it,
# the frame's own stricter policy blocks remote content).
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "media-src 'self' blob:",
    "font-src 'self' data:",
    "connect-src 'self'",
    "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com",
    "frame-ancestors 'none'",
    "base-uri 'none'",
    "object-src 'none'",
    "form-action 'self'",
])

_HEADERS = [
    (b"x-frame-options", b"DENY"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), payment=(), usb=()"),
] + ([(b"strict-transport-security", b"max-age=31536000")] if COOKIE_SECURE else [])


class SecurityHeaders:
    """Adds the headers above to every response. A route that sets its own
    Content-Security-Policy (media, attachments: sandboxed) keeps it."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                headers += [(k, v) for k, v in _HEADERS if k not in present]
                if b"content-security-policy" not in present:
                    headers.append((b"content-security-policy", CSP.encode()))
                # Pages are personal and must reach the browser unmodified: no-transform
                # stops Cloudflare rewriting them (e.g. its email-address obfuscation,
                # whose injected script the CSP would block, leaving "[email protected]").
                if b"cache-control" not in present:
                    headers.append((b"cache-control", b"private, no-transform"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_headers)


class HttpsOnly:
    """With COOKIE_SECURE=1 and PUBLIC_ORIGIN set, a plain-http visit from another
    device (e.g. an old http://server:8000 bookmark) is sent to the https
    address, where the secure login cookie works. Requests from this machine
    itself (the tunnel, the deploy bridge's health checks) are left alone."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        client = (scope.get("client") or ("", 0))[0]
        if (scope["type"] == "http" and COOKIE_SECURE and PUBLIC_ORIGIN and scope.get("scheme") == "http"
                and client not in ("127.0.0.1", "::1")):
            target = PUBLIC_ORIGIN + scope["path"] + (("?" + scope["query_string"].decode("latin-1")) if scope["query_string"] else "")
            await send({"type": "http.response.start", "status": 308,
                        "headers": [(b"location", target.encode("latin-1")), (b"content-length", b"0")]})
            await send({"type": "http.response.body", "body": b""})
            return
        await self.app(scope, receive, send)


_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


def cross_site(headers: dict[str, str]) -> bool:
    """True if a state-changing request was started by another site."""
    allowed = {headers.get("host", "")}
    if PUBLIC_ORIGIN:
        allowed.add(urlsplit(PUBLIC_ORIGIN).netloc)
    origin = headers.get("origin")
    if origin:
        return origin == "null" or urlsplit(origin).netloc not in allowed
    if headers.get("sec-fetch-site") == "cross-site":
        return True
    referer = headers.get("referer")
    return bool(referer) and urlsplit(referer).netloc not in allowed


class SameOriginWrites:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in _UNSAFE:
            headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
            if cross_site(headers):
                body = b"Blocked: that request came from another website."
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                        (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)


class DiskGuard:
    """Refuses a request body that wouldn't fit on the disk with 5% to spare.
    Uploads are spooled to a temp file before any route sees them, so this
    has to happen here. Not a size cap: anything that fits is accepted."""

    RESERVE = 0.05

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            length = next((v for k, v in scope["headers"] if k == b"content-length"), b"")
            if length.isdigit() and int(length) > (1 << 20):
                u = shutil.disk_usage(tempfile.gettempdir())
                if int(length) > u.free - u.total * self.RESERVE:
                    body = b"That upload is bigger than the free space on the server."
                    await send({"type": "http.response.start", "status": 413,
                                "headers": [(b"content-type", b"text/plain; charset=utf-8"),
                                            (b"content-length", str(len(body)).encode())]})
                    await send({"type": "http.response.body", "body": body})
                    return
        await self.app(scope, receive, send)


class LoginBrake:
    """Per-IP wrong-password counter (in memory; a restart forgets it)."""

    LIMIT = 10
    WINDOW = 15 * 60
    MAX_IPS = 10_000  # bound memory if many addresses try

    def __init__(self):
        self._fails: dict[str, deque] = {}
        self._lock = threading.Lock()
        # At most this many scrypt checks at once (each takes ~50 ms and 32 MB).
        self.checks = threading.BoundedSemaphore(4)

    def _recent(self, ip: str, now: float) -> deque:
        q = self._fails.get(ip, deque())
        while q and now - q[0] > self.WINDOW:
            q.popleft()
        return q

    def wait_seconds(self, ip: str) -> int:
        """0 if this IP may try a password now, else seconds until it may."""
        now = time.time()
        with self._lock:
            q = self._recent(ip, now)
            if not q:
                self._fails.pop(ip, None)
            if len(q) < self.LIMIT:
                return 0
            return int(self.WINDOW - (now - q[0])) + 1

    def failed(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            if len(self._fails) >= self.MAX_IPS:
                for k in [k for k, q in self._fails.items() if not self._recent(k, now)]:
                    del self._fails[k]
                if len(self._fails) >= self.MAX_IPS:
                    self._fails.pop(next(iter(self._fails)))
            q = self._recent(ip, now)
            q.append(now)
            self._fails[ip] = q

    def succeeded(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)


login_brake = LoginBrake()
