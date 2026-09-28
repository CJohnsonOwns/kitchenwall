from datetime import date, datetime, timedelta

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from .. import db
from ..calendar_utils import build_month_grid, parse_month
from ..dates import CADENCES, advance_date, clean_time, describe_due, format_time
from ..settings_store import get_setting
from ..core.templating import render
from ..core.web_utils import safe_next as _safe_next

router = APIRouter()


def safe_next(next_url: str | None, default: str = "/calendar") -> str:
    return _safe_next(next_url, default)


def decorate(bill, today: date) -> dict:
    item = dict(bill)
    item.update(describe_due(item["due_date"], today))
    item["cadence"] = CADENCES.get(item["recurring"], item["recurring"])
    item["time"] = format_time(item.get("due_time"))
    item["time_short"] = format_time(item.get("due_time"), short=True)
    return item


@router.get("/bills")
def bills_redirect(month: str | None = None):
    url = "/calendar" + (f"?month={month}" if month else "")
    return RedirectResponse(url=url, status_code=303)


@router.get("/calendar")
def calendar_page(request: Request, month: str | None = None, day: str | None = None):
    today = date.today()
    month_date = parse_month(month)
    all_bills = db.list_bills(include_paid=True)

    bills_by_day: dict[int, list] = {}
    items_by_date: dict[str, list] = {}
    for b in all_bills:
        due = datetime.strptime(b["due_date"], "%Y-%m-%d").date()
        if due.year == month_date.year and due.month == month_date.month:
            item = decorate(b, today)
            bills_by_day.setdefault(due.day, []).append(item)
            items_by_date.setdefault(b["due_date"], []).append(
                {"id": item["id"], "name": item["name"], "cadence": item["cadence"], "time": item["time"],
                 "paid": bool(item["paid"]), "cls": item["cls"]}
            )

    grid = build_month_grid(month_date, bills_by_day, get_setting("week_start"))
    weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    if get_setting("week_start") == "sun":
        weekdays = ["Sun"] + weekdays[:-1]

    upcoming = [decorate(b, today) for b in all_bills if not b["paid"]]

    prev_month = (month_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month_num = month_date.month + 1
    next_year = month_date.year
    if next_month_num > 12:
        next_month_num = 1
        next_year += 1
    next_month = month_date.replace(year=next_year, month=next_month_num)

    # Which day the side panel opens on: ?day= if it's in this month, else today
    # (if today is in this month), else the 1st.
    selected = None
    if day:
        try:
            d = date.fromisoformat(day)
            if (d.year, d.month) == (month_date.year, month_date.month):
                selected = d
        except ValueError:
            selected = None
    if selected is None:
        selected = today if (today.year, today.month) == (month_date.year, month_date.month) else month_date

    return render(
        request,
        "calendar.html",
        {
            "month_date": month_date,
            "month_label": month_date.strftime("%B %Y"),
            "month_param": month_date.strftime("%Y-%m"),
            "is_current_month": (today.year, today.month) == (month_date.year, month_date.month),
            "grid": grid,
            "weekdays": weekdays,
            "items_by_date": items_by_date,
            "selected_day": selected.strftime("%Y-%m-%d"),
            "upcoming": upcoming,
            "prev_month": prev_month.strftime("%Y-%m"),
            "next_month": next_month.strftime("%Y-%m"),
        },
    )


@router.post("/calendar")
def create_bill(
    name: str = Form(...),
    due_date: str = Form(...),
    due_time: str = Form(""),
    recurring: str = Form("none"),
    next: str | None = Form(None),
):
    name = " ".join(name.split())
    if name:
        if recurring not in CADENCES:
            recurring = "none"
        # The amount column predates the no-money design; it's kept at 0 and never shown.
        db.create_bill(name, 0.0, due_date, recurring, clean_time(due_time))
    return RedirectResponse(url=safe_next(next, f"/calendar?month={due_date[:7]}&day={due_date}"), status_code=303)


@router.get("/calendar/{bill_id}/edit")
def edit_bill_page(request: Request, bill_id: int):
    bill = db.get_bill(bill_id)
    if bill is None:
        return RedirectResponse(url="/calendar", status_code=303)
    return render(request, "bill_edit.html", {"bill": bill})


@router.post("/calendar/{bill_id}/edit")
def edit_bill(
    bill_id: int,
    name: str = Form(...),
    due_date: str = Form(...),
    due_time: str = Form(""),
    recurring: str = Form("none"),
):
    bill = db.get_bill(bill_id)
    if bill is None:
        return RedirectResponse(url="/calendar", status_code=303)
    if recurring not in CADENCES:
        recurring = "none"
    db.update_bill(bill_id, " ".join(name.split()) or bill["name"], bill["amount"], due_date, recurring,
                   clean_time(due_time))
    return RedirectResponse(url=f"/calendar?month={due_date[:7]}&day={due_date}", status_code=303)


@router.post("/calendar/{bill_id}/toggle-paid")
def toggle_paid(bill_id: int, next: str | None = Form(None)):
    bill = db.get_bill(bill_id)
    if bill is None:
        return RedirectResponse(url=safe_next(next), status_code=303)

    if bill["recurring"] != "none" and not bill["paid"]:
        # Recurring item being marked done: roll the date forward instead of
        # leaving it done forever.
        due = datetime.strptime(bill["due_date"], "%Y-%m-%d").date()
        next_due = advance_date(due, bill["recurring"])
        db.set_bill_due_date(bill_id, next_due.strftime("%Y-%m-%d"), 0)
    else:
        db.toggle_bill_paid(bill_id, 0 if bill["paid"] else 1)

    return RedirectResponse(url=safe_next(next), status_code=303)


@router.post("/calendar/{bill_id}/delete")
def delete_bill(bill_id: int, next: str | None = Form(None)):
    db.delete_bill(bill_id)
    return RedirectResponse(url=safe_next(next), status_code=303)
