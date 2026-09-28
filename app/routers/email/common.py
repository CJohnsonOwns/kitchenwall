"""Shared by the inbox routes: account colours, list rows, conversation grouping, redirects."""
from urllib.parse import urlencode

from ... import db
from ...core.web_utils import safe_next
from ...mail import google_oauth
from ...mail.mail_mime import address_list
from .formatting import format_message_date, sender_name

# Colour dot that tells accounts apart in the inbox (by position, so it's stable).
ACCOUNT_COLORS = ["#d9a441", "#5b8fd9", "#d67aa8", "#6fae7b", "#9a7ad6", "#4fa3a0"]
VIEWS = ("inbox", "starred", "sent", "search")
PAGE = 50


def decorate_accounts(accounts) -> list[dict]:
    out = []
    for i, a in enumerate(accounts):
        row = dict(a)
        row["color"] = ACCOUNT_COLORS[i % len(ACCOUNT_COLORS)]
        row["needs_reconnect"] = a["auth_method"] == "oauth" and google_oauth.can_modify(a) is False
        out.append(row)
    return out


def decorate_message(m, colors: dict[int, str]) -> dict:
    """List-row fields for one message (DB row or search-result dict)."""
    row = dict(m)
    row["display_date"] = format_message_date(row.get("received_at"))
    row["from_name"] = sender_name(row.get("sender"))
    row["initial"] = (row["from_name"][:1] or "?").upper()
    row["account_color"] = colors.get(row["account_id"], ACCOUNT_COLORS[0])
    row["key"] = f"{row['account_id']}:{row['uid']}"
    row["url"] = f"/inbox/m/{row['account_id']}/{row['uid']}"
    return row


def group_threads(rows: list[dict], own_addresses: dict[int, str], view: str) -> list[dict]:
    """Collapse message rows (newest first) into conversations, newest first."""
    groups: dict[tuple, dict] = {}
    order = []
    for r in rows:
        k = (r["account_id"], r.get("thread_id") or r["uid"])
        g = groups.get(k)
        if g is None:
            g = {"latest": r, "rows": [], "names": []}
            groups[k] = g
            order.append(k)
        g["rows"].append(r)
    threads = []
    for k in order:
        g = groups[k]
        latest = g["latest"]
        own = (own_addresses.get(latest["account_id"]) or "").lower()
        names = []
        for r in reversed(g["rows"]):  # oldest first
            if view == "sent":
                who = ", ".join(n or a.split("@")[0] for n, a in address_list(r.get("to_addrs") or "")) or "(no recipient)"
            else:
                addr = address_list(r.get("sender") or "")
                who = "me" if addr and addr[0][1].lower() == own else r["from_name"]
            if who not in names:
                names.append(who)
        t = dict(latest)
        t["participants"] = ", ".join(names[-3:])
        if view == "sent":
            t["participants"] = "To: " + t["participants"]
        t["count"] = len(g["rows"])
        t["unread"] = any(not r["is_read"] for r in g["rows"])
        t["starred"] = any(r.get("is_starred") for r in g["rows"])
        t["in_inbox"] = any(r.get("in_inbox") for r in g["rows"])
        # Not "keys": Jinja resolves t.keys to the dict method, not this value.
        t["keys_csv"] = ",".join(r["key"] for r in g["rows"])
        t["search_text"] = " ".join(
            [t["participants"], latest.get("sender") or "", latest.get("subject") or "", latest.get("snippet") or ""]
        ).lower()
        threads.append(t)
    return threads


def recent_threads(limit: int = 4) -> list[dict]:
    """Newest inbox conversations for the Home page card."""
    accounts = decorate_accounts(db.list_email_accounts())
    colors = {a["id"]: a["color"] for a in accounts}
    own = {a["id"]: a["email_address"] for a in accounts}
    rows = [decorate_message(m, colors) for m in db.list_view_messages("inbox", limit=limit * 4)]
    return group_threads(rows, own, "inbox")[:limit]


def _safe_next(next_url: str | None, default: str = "/inbox") -> str:
    return safe_next(next_url, default)


def _with_params(url: str, **params) -> str:
    extra = urlencode({k: v for k, v in params.items() if v not in (None, "")})
    if not extra:
        return url
    return url + ("&" if "?" in url else "?") + extra
