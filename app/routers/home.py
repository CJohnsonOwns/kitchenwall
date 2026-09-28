"""Sign in / sign out and the Home page."""
import logging
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..core.auth import hash_password, password_matches, sign_in_household, sign_in_user, verify_password
from ..core.security import login_brake
from ..core.templating import render, templates
from ..settings_store import get_int, get_setting
from . import bills, board
from .email import recent_threads

router = APIRouter()
log = logging.getLogger("household.login")

_DUMMY_HASH = hash_password("not-a-real-password")


def _login_page(request: Request, error: str | None = None, username: str = "", status_code: int = 200):
    return templates.TemplateResponse(
        request, "login.html",
        {"error": error, "users": db.list_users(), "username": username},
        status_code=status_code,
    )


@router.get("/login")
def login_page(request: Request):
    return _login_page(request)


@router.post("/login")
def login_submit(request: Request, password: str = Form(...), username: str = Form("")):
    # No username (or "household") = the shared household password, used by the wall screen.
    username = username.strip()[:100]
    ip = request.client.host if request.client else "?"
    wait = login_brake.wait_seconds(ip)
    if wait:
        resp = _login_page(request, f"Too many wrong passwords from this device. Try again in {-(-wait // 60)} min.",
                           username, status_code=429)
        resp.headers["Retry-After"] = str(wait)
        return resp
    with login_brake.checks:
        if not username or username.lower() == "household":
            if password_matches(password):
                login_brake.succeeded(ip)
                sign_in_household(request)
                return RedirectResponse(url="/", status_code=303)
        else:
            user = db.get_user_by_name(username)
            # Check a throwaway hash for unknown names too, so timing doesn't reveal them.
            if verify_password(password, user["pw_hash"] if user else _DUMMY_HASH) and user:
                login_brake.succeeded(ip)
                sign_in_user(request, user)
                return RedirectResponse(url="/", status_code=303)
    login_brake.failed(ip)
    log.warning("wrong password for %r from %s", username or "household", ip)
    return _login_page(request, "Wrong password, try again.", username, status_code=401)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/login", status_code=303)


def _greeting(hour: int) -> str:
    if hour < 5:
        return "Up late?"
    if hour < 12:
        return "Good morning"
    if hour < 17:
        return "Good afternoon"
    return "Good evening"


def _week_days(today: date, week_start: str) -> list[date]:
    """The 7 days of the week containing today, per the week-start setting."""
    offset = (today.weekday() + (1 if week_start == "sun" else 0)) % 7
    first = today - timedelta(days=offset)
    return [first + timedelta(days=i) for i in range(7)]


@router.get("/")
def dashboard_home(request: Request):
    today = date.today()
    today_str = today.strftime("%Y-%m-%d")
    lookahead = get_int("lookahead_days")
    week_start = get_setting("week_start")

    open_items = [bills.decorate(b, today) for b in db.list_bills(include_paid=False)]
    now_items = [i for i in open_items if i["days"] <= 1]          # overdue, today, tomorrow
    later_items = [i for i in open_items if 1 < i["days"] <= lookahead]

    week = _week_days(today, week_start)
    week_start_str, week_end_str = week[0].strftime("%Y-%m-%d"), week[-1].strftime("%Y-%m-%d")
    all_this_week = [
        bills.decorate(b, today)
        for b in db.list_bills(include_paid=True)
        if week_start_str <= b["due_date"] <= week_end_str
    ]
    week_days = [
        {
            "date": d,
            "is_today": d == today,
            "entries": [i for i in all_this_week if i["due_date"] == d.strftime("%Y-%m-%d")],
        }
        for d in week
    ]

    accounts = db.list_email_accounts()

    ctx = board.board_context()
    ctx.update(
        {
            "greeting": _greeting(datetime.now().hour),
            "today_str": today_str,
            "now_items": now_items,
            "later_items": later_items,
            "lookahead": lookahead,
            "week_days": week_days,
            "week_label": f"{week[0].strftime('%b')} {week[0].day} – {week[-1].strftime('%b')} {week[-1].day}",
            "recent_messages": recent_threads(4),
            "has_email_accounts": len(accounts) > 0,
        }
    )
    return render(request, "dashboard.html", ctx)
