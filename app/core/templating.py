"""One shared Jinja environment plus the context every page needs.

Every page renders through `render()` so the header (tab badges, weather chip,
display-mode refresh interval) always has its data, whichever router served
the page.
"""
from datetime import date
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from .. import db, weather
from ..dates import CADENCES
from ..settings_store import get_settings

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
STATIC_DIR = Path(__file__).resolve().parents[1] / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["CADENCES"] = CADENCES


def _static_version(name: str) -> int:
    """mtime of a static file, used as a cache-buster so edits show up without a hard refresh."""
    try:
        return int((STATIC_DIR / name).stat().st_mtime)
    except OSError:
        return 0


def static_url(name: str) -> str:
    """URL of a file in app/static with its own cache-buster (?v=mtime), so only
    files that changed are fetched again."""
    return f"/static/{name}?v={_static_version(name)}"


# Every page loads these, in this order (the order is the cascade). style.css
# holds the design tokens; each css/ file is one area of the app.
CSS_FILES = ["css/fonts.css", "style.css"] + [f"css/{n}.css" for n in (
    "controls", "header", "cards", "home", "mail-rows", "calendar", "board",
    "inbox", "settings", "login", "list", "share")]

templates.env.globals["static_url"] = static_url
templates.env.globals["CSS_FILES"] = CSS_FILES


def _active_tab(path: str) -> str:
    if path.startswith("/whiteboard") or path.startswith("/board"):
        return "whiteboard"
    if path.startswith("/list"):
        return "list"
    if path.startswith("/calendar"):
        return "calendar"
    if path.startswith("/inbox"):
        return "inbox"
    if path.startswith("/share"):
        return "share"
    if path.startswith("/settings"):
        return "settings"
    return "home"


def render(request: Request, name: str, ctx: dict | None = None, status_code: int = 200):
    today = date.today()
    me = getattr(request.state, "user", None)  # None = household login
    # Two queries for the whole header: the badges, and every setting (which
    # the weather chip reads too). The weather never waits on the network here.
    counts = db.nav_counts(today.strftime("%Y-%m-%d"), me["id"] if me else None)
    stored = db.all_settings()
    base = {
        "me": me,
        "nav_share": counts["share"],
        "today": today,
        "active_tab": _active_tab(request.url.path),
        "nav_due": counts["due"],
        "nav_unread": counts["unread"],
        "nav_list": counts["list"],
        "weather": weather.current(stored),
        "app_settings": get_settings(stored),
    }
    if ctx:
        base.update(ctx)
    return templates.TemplateResponse(request, name, base, status_code=status_code)
