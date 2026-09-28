"""The inbox list (views, search, paging) and the Refresh / Older buttons."""
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ... import db
from ...core.templating import render
from ...mail import email_client, mail_sync
from ...mail.email_client import EmailAuthError
from .common import PAGE, VIEWS, _safe_next, _with_params, decorate_accounts, decorate_message, group_threads
from .formatting import humanize_since

router = APIRouter()


@router.get("/inbox")
def inbox_page(
    request: Request,
    view: str = "inbox",
    q: str = "",
    acct: str = "",
    limit: int = PAGE,
    open: str = "",
    error: str | None = None,
    sent: str | None = None,
    notice: str | None = None,
):
    view = view if view in VIEWS else "inbox"
    q = q.strip()
    if view == "search" and not q:
        view = "inbox"
    limit = max(PAGE, min(limit, 1000))
    raw_accounts = db.list_email_accounts()
    accounts = decorate_accounts(raw_accounts)
    colors = {a["id"]: a["color"] for a in accounts}
    own = {a["id"]: a["email_address"] for a in accounts}
    account_id = int(acct) if acct.isdigit() and int(acct) in colors else None

    errors = []
    if view == "search":
        rows = []
        for a in raw_accounts:
            if account_id and a["id"] != account_id:
                continue
            try:
                for r in email_client.search(a, q, limit=40):
                    rows.append({**r, "account_id": a["id"], "display_name": a["display_name"], "email_address": a["email_address"]})
            except EmailAuthError as exc:
                errors.append(str(exc))
        rows.sort(key=lambda r: r.get("received_at") or "", reverse=True)
        rows = [decorate_message(r, colors) for r in rows]
        threads = group_threads(rows, own, "inbox")
        has_more = False
    else:
        rows = [decorate_message(m, colors) for m in db.list_view_messages(view, account_id, limit=limit * 4)]
        threads = group_threads(rows, own, view)
        has_more = True
        threads = threads[:limit]

    return render(
        request,
        "inbox.html",
        {
            "accounts": accounts,
            "threads": threads,
            "view": view,
            "q": q,
            "acct": account_id or "",
            "limit": limit,
            "has_more": has_more and bool(threads),
            "open_key": open,
            "error": error or ("; ".join(errors) if errors else None),
            "sent": sent,
            "notice": notice,
            "last_sync": humanize_since(db.latest_sync_at()),
            "view_counts": {
                "inbox": db.count_unread_messages(),
            },
        },
    )


@router.post("/inbox/refresh")
def inbox_refresh(next: str | None = Form(None)):
    errors = mail_sync.sync_all_accounts()
    target = _safe_next(next)
    if errors:
        return RedirectResponse(url=_with_params(target, error="; ".join(errors)), status_code=303)
    return RedirectResponse(url=target, status_code=303)


@router.post("/inbox/older")
def inbox_older(view: str = Form("inbox"), acct: str = Form(""), limit: int = Form(PAGE)):
    view = view if view in ("inbox", "starred", "sent") else "inbox"
    errors, got = [], 0
    for a in db.list_email_accounts():
        if acct.isdigit() and a["id"] != int(acct):
            continue
        try:
            got += email_client.fetch_older(a, view, PAGE)
        except EmailAuthError as exc:
            errors.append(str(exc))
    params = {"view": view, "acct": acct, "limit": limit + PAGE}
    if errors:
        params["error"] = "; ".join(errors)
    elif not got:
        params["notice"] = "That's everything. There's no older mail in this view."
    return RedirectResponse(url="/inbox?" + urlencode({k: v for k, v in params.items() if v != ""}) + "#more", status_code=303)
