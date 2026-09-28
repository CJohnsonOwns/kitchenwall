"""Sending mail (new, reply, reply all, forward) and the address-book autocomplete."""
from fastapi import APIRouter, File, Form, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from ... import db
from ...mail import email_client, mail_sync
from ...mail.email_client import EmailAuthError
from .common import _safe_next, _with_params

router = APIRouter()


@router.get("/inbox/contacts")
def contacts():
    return JSONResponse({"contacts": email_client.contacts()})


@router.post("/inbox/send")
async def send(
    account_id: int = Form(...),
    mode: str = Form("new"),
    ref_uid: str = Form(""),
    ref_account_id: str = Form(""),
    to_address: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    subject: str = Form(""),
    body: str = Form(""),
    include_quote: str = Form(""),
    fwd_choice: str = Form(""),
    fwd_att: list[int] = Form([]),
    files: list[UploadFile] = File([]),
    next: str = Form("/inbox"),
    draft_key: str = Form(""),
):
    target = _safe_next(next)
    account = db.get_email_account(account_id)
    if account is None:
        return RedirectResponse(url=_with_params(target, error="That account is no longer connected."), status_code=303)
    if not (to_address.strip() or cc.strip() or bcc.strip()):
        return RedirectResponse(url=_with_params(target, error="Add at least one recipient."), status_code=303)
    ref_account = db.get_email_account(int(ref_account_id)) if ref_account_id.isdigit() else account
    mode = mode if mode in ("new", "reply", "replyall", "forward") else "new"
    uploads = []
    for f in files or []:
        if f is None or not f.filename:
            continue
        data = await f.read()
        if data:
            uploads.append((f.filename, f.content_type or "application/octet-stream", data))
    try:
        # Sending is slow network work (SMTP / Gmail API): keep it off the event loop.
        await run_in_threadpool(
            email_client.send_mail,
            account,
            mode,
            to_address.strip(),
            cc.strip(),
            subject.strip() or "(no subject)",
            body,
            ref_uid=ref_uid or None,
            include_quote=bool(include_quote),
            include_attachments=True,
            bcc=bcc.strip(),
            ref_account=ref_account,
            uploads=uploads,
            # The forward form lists the original's attachments as checkboxes;
            # fwd_choice marks that the list was shown, so none ticked means none.
            forward_indexes=list(fwd_att) if fwd_choice else None,
        )
    except EmailAuthError as exc:
        return RedirectResponse(url=_with_params(target, error=str(exc)), status_code=303)
    mail_sync.sync_soon(account_id)
    return RedirectResponse(url=_with_params(target, sent="1", dk=draft_key), status_code=303)
