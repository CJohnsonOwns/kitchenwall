"""Downloading / viewing an email attachment, served so it can never run script on this site."""
from urllib.parse import quote

from fastapi import APIRouter
from fastapi.responses import Response

from ... import db
from ...mail import email_client
from ...mail.email_client import EmailAuthError

router = APIRouter()

# Attachments shown in the browser rather than downloaded. Everything else is
# forced to download, so an HTML/SVG attachment can never run on this site.
INLINE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "application/pdf"}


@router.get("/inbox/att/{account_id}/{uid}/{index}")
def attachment(account_id: int, uid: str, index: int, download: int = 0):
    account = db.get_email_account(account_id)
    if account is None:
        return Response("Not found", status_code=404)
    try:
        filename, mime, data = email_client.get_attachment(account, uid, index)
    except EmailAuthError as exc:
        return Response(str(exc), status_code=404, media_type="text/plain")
    inline = not download and mime in INLINE_TYPES
    disposition = "inline" if inline else "attachment"
    headers = {
        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(filename)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, max-age=86400",
    }
    # Chrome won't render a PDF under a `sandbox` policy, and PDFs open in the
    # browser's own viewer (they can't run script on this site), so only
    # everything else gets the sandbox.
    if not (inline and mime == "application/pdf"):
        headers["Content-Security-Policy"] = "sandbox; default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'"
    return Response(content=data, media_type=mime if inline else "application/octet-stream", headers=headers)
