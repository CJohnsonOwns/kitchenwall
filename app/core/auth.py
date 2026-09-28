import base64
import hashlib
import hmac
import os
import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse

from .. import db

HOUSEHOLD_PASSWORD = os.environ.get("HOUSEHOLD_PASSWORD", "changeme")

# Paths that don't require an authenticated session: exactly /login, and
# files under /static/ (a bare prefix would also have let "/loginx" through).
PUBLIC_EXACT = ("/login",)
PUBLIC_PREFIXES = ("/static/",)
# All someone with a temporary password can reach.
MUST_CHANGE_OK = ("/password", "/logout")

MIN_PASSWORD = 10
_SCRYPT = (2**15, 8, 1)  # n, r, p: ~50 ms and 32 MB per check


def password_matches(candidate: str) -> bool:
    """Household password check. Constant-time, so response timing can't hint at it."""
    return hmac.compare_digest(candidate.encode("utf-8"), HOUSEHOLD_PASSWORD.encode("utf-8"))


def hash_password(password: str) -> str:
    n, r, p = _SCRYPT
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=64 * 1024 * 1024)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${n}${r}${p}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt),
                             n=int(n), r=int(r), p=int(p), maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(got, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def _fingerprint(value: str) -> str:
    secret = os.environ.get("SESSION_SECRET", "")
    return hmac.new(secret.encode(), value.encode(), hashlib.sha256).hexdigest()[:16]


def password_fingerprint() -> str:
    """Short digest of the current household password, stored in each household session.

    When the household password changes, every existing session stops
    matching and has to log in again, so an old password (or a device you
    no longer trust) doesn't stay signed in.
    """
    return _fingerprint(HOUSEHOLD_PASSWORD)


def user_fingerprint(user) -> str:
    """The same idea for a personal login: changes when that person's password does."""
    return _fingerprint(f"user:{user['id']}:{user['pw_hash']}")


def sign_in_household(request: Request) -> None:
    request.session.clear()
    request.session["authenticated"] = True
    request.session["pw"] = password_fingerprint()


def sign_in_user(request: Request, user) -> None:
    request.session.clear()
    request.session["authenticated"] = True
    request.session["uid"] = user["id"]
    request.session["pw"] = user_fingerprint(user)


def session_user(request: Request):
    """(signed in?, user row or None). None with True = the household login."""
    session = request.session
    if not session.get("authenticated"):
        return False, None
    pw = str(session.get("pw", ""))
    uid = session.get("uid")
    if uid is None:
        return hmac.compare_digest(pw, password_fingerprint()), None
    user = db.get_user(int(uid))
    if user is None or not hmac.compare_digest(pw, user_fingerprint(user)):
        return False, None
    return True, user


def is_authenticated(request: Request) -> bool:
    return session_user(request)[0]


def current_user(request: Request):
    """The signed-in person's user row, or None for the household login."""
    return getattr(request.state, "user", None)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        ok, user = session_user(request)
        if not ok:
            request.session.clear()
            return RedirectResponse(url="/login", status_code=303)
        request.state.user = user
        # Temporary password (add_user.py --temp): nothing else until they pick their own.
        if user is not None and user["must_change"] and not path.startswith(MUST_CHANGE_OK):
            return RedirectResponse(url="/password", status_code=303)
        return await call_next(request)
