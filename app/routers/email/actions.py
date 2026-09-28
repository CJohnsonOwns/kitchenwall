"""Archive, delete, star and read-state changes (single, bulk and undo)."""
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from ... import db
from ...mail import email_client
from ...mail.email_client import INVERSE, EmailAuthError
from .common import _safe_next, _with_params

router = APIRouter()


def _parse_keys(keys) -> dict[int, list[str]]:
    by_account: dict[int, list[str]] = {}
    if isinstance(keys, str):
        keys = [k for k in keys.split(",") if k]
    for k in keys or []:
        a, _, uid = str(k).partition(":")
        if a.isdigit() and uid:
            by_account.setdefault(int(a), []).append(uid)
    return by_account


def _run_action(action: str, keys, to_inbox: bool | None) -> dict:
    if action not in email_client.ACTIONS:
        return {"ok": False, "errors": ["Unknown action."]}
    by_account = _parse_keys(keys)
    done, errors, undo_keys, was_inbox = 0, [], [], False
    for account_id, uids in by_account.items():
        account = db.get_email_account(account_id)
        if account is None:
            continue
        if action == "trash":
            was_inbox = was_inbox or db.any_in_inbox(account_id, uids)
        try:
            email_client.modify(account, uids, action, to_inbox=True if to_inbox is None else to_inbox)
        except EmailAuthError as exc:
            errors.append(str(exc))
            continue
        done += len(uids)
        undo_keys += [f"{account_id}:{u}" for u in uids]
    if not errors and done == 0:
        # Never report success for a change that didn't happen.
        errors.append("Nothing was changed: those messages couldn't be found. Try refreshing the page.")
    undo = None
    if undo_keys:
        undo = {"action": INVERSE[action], "keys": undo_keys, "to_inbox": was_inbox if action == "trash" else True}
    return {"ok": not errors, "done": done, "errors": errors, "undo": undo, "unread": db.count_unread_messages()}


@router.post("/inbox/action")
async def inbox_action(request: Request):
    # _run_action talks to Gmail over the network; run it in a worker thread so
    # a slow call doesn't freeze the app for everyone else.
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
        result = await run_in_threadpool(_run_action, payload.get("action", ""), payload.get("keys", []), payload.get("to_inbox"))
        return JSONResponse(result, status_code=200 if result["ok"] else 409)
    form = await request.form()
    result = await run_in_threadpool(_run_action, form.get("action", ""), form.get("keys", ""), None)
    target = _safe_next(form.get("next"))
    if result["errors"]:
        target = _with_params(target, error="; ".join(result["errors"]))
    return RedirectResponse(url=target, status_code=303)


@router.get("/inbox/unread-count")
def unread_count():
    return JSONResponse({"unread": db.count_unread_messages()})
