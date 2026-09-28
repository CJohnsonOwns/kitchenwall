import calendar
from datetime import date, datetime, timedelta

# Recurrence options shown in the calendar dropdowns: stored value -> label.
CADENCES = {
    "none": "One-time",
    "weekly": "Weekly",
    "biweekly": "Every 2 weeks",
    "monthly": "Monthly",
    "quarterly": "Every 3 months",
    "semiannual": "Every 6 months",
    "yearly": "Yearly",
}

_WEEKS = {"weekly": 1, "biweekly": 2}
_MONTHS = {"monthly": 1, "quarterly": 3, "semiannual": 6, "yearly": 12}


def _add_months(d: date, months: int) -> date:
    """Add whole months, clamping the day to the target month's length (Jan 31 -> Feb 28)."""
    total = d.month - 1 + months
    year, month = d.year + total // 12, total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def clean_time(value: str | None) -> str | None:
    """A form's time field as "HH:MM" (24h), or None for all day / anything unparseable."""
    try:
        return datetime.strptime((value or "").strip()[:5], "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def format_time(hhmm: str | None, short: bool = False) -> str:
    """ "15:30" -> "3:30 PM" (or "3:30pm" / "9am" when short, for calendar chips)."""
    if not hhmm:
        return ""
    t = datetime.strptime(hhmm, "%H:%M")
    h = t.hour % 12 or 12
    if short:
        return f"{h}{t.strftime(':%M') if t.minute else ''}{'am' if t.hour < 12 else 'pm'}"
    return f"{h}:{t.strftime('%M')} {'AM' if t.hour < 12 else 'PM'}"


def describe_due(due_str: str, today: date) -> dict:
    """Human wording for a due date relative to today, plus a CSS state class."""
    due = date.fromisoformat(due_str)
    days = (due - today).days
    if days < 0:
        n = -days
        label = f"{n} day{'s' if n != 1 else ''} overdue"
        cls = "overdue"
    elif days == 0:
        label, cls = "Due today", "today"
    elif days == 1:
        label, cls = "Tomorrow", ""
    elif days < 7:
        label, cls = due.strftime("%A"), ""
    else:
        label, cls = f"{due.strftime('%a, %b')} {due.day}", ""
    return {
        "days": days,
        "label": label,
        "cls": cls,
        "weekday": due.strftime("%a"),
        "short": f"{due.strftime('%b')} {due.day}",
    }


def advance_date(d: date, interval: str) -> date:
    """Return the next occurrence of a recurring date given an interval."""
    if interval in _WEEKS:
        return d + timedelta(weeks=_WEEKS[interval])
    if interval in _MONTHS:
        return _add_months(d, _MONTHS[interval])
    return d
