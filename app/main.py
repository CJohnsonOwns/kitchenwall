"""The app: start-up, middleware and routers. Routes live in app/routers/."""
import logging
import os
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # before anything below reads os.environ

from fastapi import FastAPI  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from . import db  # noqa: E402
from .core.auth import HOUSEHOLD_PASSWORD, AuthMiddleware  # noqa: E402
from .core.compression import Compress  # noqa: E402
from .core.security import COOKIE_SECURE, DiskGuard, HttpsOnly, SameOriginWrites, SecurityHeaders  # noqa: E402
from .core.static_files import CachedStatic  # noqa: E402
from .mail import email_client, mail_sync  # noqa: E402
from .routers import bills, board, email, home, lists, server, settings, share  # noqa: E402

BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger("household")

# Values from .env.example / old defaults: using them means anyone can log in
# (password) or forge a login cookie (secret).
_EXAMPLE_SECRETS = {"", "dev-secret-change-me", "change-this-to-a-long-random-string"}
SESSION_SECRET = os.environ.get("SESSION_SECRET", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Refuse to run with a guessable cookie secret: anyone could forge a login.
    if SESSION_SECRET in _EXAMPLE_SECRETS or len(SESSION_SECRET) < 16:
        raise RuntimeError("SESSION_SECRET in .env is missing, an example value or too short. "
                           "Set a long random one (deploy/set_secrets.py does this).")
    if HOUSEHOLD_PASSWORD == "changeme" or len(HOUSEHOLD_PASSWORD) < 10:
        if COOKIE_SECURE:  # served on the internet: a weak shared password is not OK
            raise RuntimeError("HOUSEHOLD_PASSWORD is weak; set a real one before serving over https.")
        log.warning("HOUSEHOLD_PASSWORD is weak ('changeme' or under 10 characters). Set a real password in .env.")
    db.init_db()
    email_client.ensure_email_key()
    mail_sync.start_background_sync()
    yield


# No /docs, /redoc or /openapi.json: nothing outside needs a map of the API.
app = FastAPI(title="Kitchenwall", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

# Starlette's add_middleware() inserts at the front of the stack, so the
# *last* middleware added ends up outermost (runs first). AuthMiddleware
# reads request.session, so SessionMiddleware must be added after it.
# Resulting order for a request: Compress -> HttpsOnly -> SecurityHeaders -> SameOriginWrites -> DiskGuard -> Session -> Auth -> routes.
app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    # Never a known fallback value (lifespan refuses to start without a real one).
    secret_key=SESSION_SECRET or secrets.token_urlsafe(32),
    same_site="lax",           # other sites can't submit our forms with your cookie
    max_age=30 * 24 * 3600,    # stay signed in for 30 days on a device
    https_only=COOKIE_SECURE,  # COOKIE_SECURE=1 once served over https
    session_cookie="__Host-session" if COOKIE_SECURE else "session",
)
app.add_middleware(DiskGuard)
app.add_middleware(SameOriginWrites)
app.add_middleware(SecurityHeaders)
app.add_middleware(HttpsOnly)
app.add_middleware(Compress)

app.mount("/static", CachedStatic(directory=str(BASE_DIR / "static")), name="static")

for _r in (home, bills, board, email, lists, server, settings, share):
    app.include_router(_r.router)
