"""Reading a conversation: message views, the sandboxed HTML body (srcdoc), remote-image blocking."""
import re

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from ... import db
from ...core.templating import render, templates
from ...mail import email_client
from ...mail.email_client import EmailAuthError
from ...mail.mail_mime import address_list, display_name as addr_display_name, nice_date
from .attachments import INLINE_TYPES
from .common import ACCOUNT_COLORS, VIEWS, decorate_accounts
from .formatting import format_message_date, human_size, split_quote

router = APIRouter()


def _message_view(account, m: dict, expanded: bool) -> dict:
    account_id, uid = account["id"], m["uid"]
    h = m["headers"]
    html = m.get("html")
    att_url = lambda a: f"/inbox/att/{account_id}/{uid}/{a['index']}"
    if html:
        for a in m["attachments"]:
            if a.get("cid"):
                html = re.sub(re.escape("cid:" + a["cid"]), att_url(a), html, flags=re.IGNORECASE)
    body_text, quoted = split_quote(m.get("text") or "") if not html else ("", "")
    attachments = [
        {
            **a,
            "url": att_url(a),
            "download_url": att_url(a) + "?download=1",
            "size_h": human_size(a["size"]),
            "is_image": a["mime"] in INLINE_TYPES and a["mime"].startswith("image/"),
        }
        for a in m["attachments"]
        if not a.get("inline")
    ]
    from_pairs = address_list(h.get("from", ""))
    return {
        "uid": uid,
        "key": f"{account_id}:{uid}",
        "from_name": addr_display_name(h.get("from", "")),
        "from_addr": from_pairs[0][1] if from_pairs else "",
        "initial": (addr_display_name(h.get("from", ""))[:1] or "?").upper(),
        "to": h.get("to", ""),
        "cc": h.get("cc", ""),
        "date": nice_date(h.get("date", "")) or format_message_date(m.get("received_at")),
        "short_date": format_message_date(m.get("received_at")),
        "snippet": m.get("snippet", ""),
        "html": html,
        "srcdoc": _srcdoc(html) if html else None,
        "has_remote": bool(html and _REMOTE_RE.search(html)),
        "text": body_text,
        "quoted": quoted,
        "attachments": attachments,
        "expanded": expanded,
        "is_starred": m.get("is_starred"),
        "compose": email_client.compose_defaults(account, m),
        # For the composer: the original shown under a reply, and the
        # attachments a forward can carry along.
        "plain": (m.get("plain") or "")[:20000],
        "headers": h,
        "forwardable": [{"index": a["index"], "filename": a["filename"], "size_h": a["size_h"]} for a in attachments],
    }


# Remote images and stylesheets in email are blocked until you choose to load
# them: senders use them as "tracking pixels" to learn when (and from what IP)
# a message was opened. Inline images (served from this site) still show.
# The page's script removes this tag when you press "Show images".
REMOTE_BLOCK_META = (
    '<meta data-hd-block http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; font-src data:\">"
)
_REMOTE_RE = re.compile(r"""(?:src|background)\s*=\s*["']?\s*https?:|url\(\s*["']?\s*https?:|@import""", re.IGNORECASE)


def _srcdoc(html: str) -> str:
    return (
        '<!doctype html><html><head>' + REMOTE_BLOCK_META + '<meta charset="utf-8"><base target="_blank">'
        "<style>html,body{margin:0}body{padding:16px 18px;font:15px/1.5 -apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;"
        "color:#1c1a14;background:#fff;overflow-wrap:anywhere}img{max-width:100%;height:auto}"
        "table{max-width:100%}pre{white-space:pre-wrap}</style></head><body>" + html + "</body></html>"
    )


def _thread_context(account, uid: str, view: str) -> dict:
    thread = email_client.open_thread(account, uid)
    msgs = thread["messages"]
    last = len(msgs) - 1
    views = [
        _message_view(account, m, expanded=(i == last or m["uid"] in thread["was_unread"] or m["uid"] == uid))
        for i, m in enumerate(msgs)
    ]
    accounts = decorate_accounts(db.list_email_accounts())
    color = next((a["color"] for a in accounts if a["id"] == account["id"]), ACCOUNT_COLORS[0])
    return {
        "account": account,
        "accounts": accounts,
        "account_color": color,
        "subject": msgs[0]["headers"]["subject"] if msgs else "(no subject)",
        "messages": views,
        "keys_csv": ",".join(v["key"] for v in views),  # not "keys": see group_threads
        "starred": any(m.get("is_starred") for m in msgs),
        "in_inbox": any(m.get("in_inbox") for m in msgs),
        "view": view if view in VIEWS else "inbox",
        "focus_uid": uid,
    }


@router.get("/inbox/m/{account_id}/{uid}")
def view_thread(request: Request, account_id: int, uid: str, pane: int = 0, view: str = "inbox",
                error: str | None = None, sent: str | None = None):
    account = db.get_email_account(account_id)
    ctx: dict = {"error": error, "sent": sent, "thread": None, "pane": bool(pane)}
    if account is None:
        ctx["error"] = "That account is no longer connected."
    else:
        try:
            ctx["thread"] = _thread_context(account, uid, view)
        except EmailAuthError as exc:
            ctx["error"] = str(exc)
    if pane:
        return templates.TemplateResponse(request, "_thread.html", {**ctx, "next_url": ""})
    return render(request, "email_message.html", ctx)


@router.get("/inbox/message/{row_id}")
def legacy_message(row_id: int):
    row = db.get_message_by_row(row_id)
    if row is None:
        return RedirectResponse(url="/inbox", status_code=303)
    return RedirectResponse(url=f"/inbox/m/{row['account_id']}/{row['uid']}", status_code=303)
