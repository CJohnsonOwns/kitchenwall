"""Connecting Gmail accounts: app password (IMAP) or Google sign-in (OAuth), and removing them."""
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ... import db
from ...core.templating import render
from ...mail import email_client, google_oauth, mail_sync
from ...mail.email_client import EmailAuthError
from .common import decorate_accounts

router = APIRouter()


@router.get("/inbox/accounts")
def accounts_page(request: Request, error: str | None = None):
    accounts = decorate_accounts(db.list_email_accounts())
    return render(
        request,
        "email_accounts.html",
        {"accounts": accounts, "error": error, "google_configured": google_oauth.is_configured()},
    )


# The IMAP backend speaks Gmail's extensions only, so the servers are fixed:
# never taken from the form (that would let a request make this server connect
# anywhere and hand it the password).
IMAP_HOST, SMTP_HOST = "imap.gmail.com", "smtp.gmail.com"


@router.post("/inbox/accounts")
def add_account(
    email_address: str = Form(...),
    app_password: str = Form(...),
    display_name: str = Form(""),
):
    app_password = app_password.replace(" ", "")
    try:
        email_client.test_login(email_address, app_password, IMAP_HOST)
    except EmailAuthError as exc:
        return RedirectResponse(url=f"/inbox/accounts?error={quote(str(exc))}", status_code=303)

    account_id = db.create_email_account(
        email_address=email_address,
        display_name=display_name or email_address,
        app_password_enc=email_client.encrypt_password(app_password),
        imap_host=IMAP_HOST,
        smtp_host=SMTP_HOST,
    )
    mail_sync.sync_soon(account_id)
    return RedirectResponse(url="/inbox/accounts", status_code=303)


@router.post("/inbox/accounts/{account_id}/delete")
def delete_account(account_id: int):
    db.delete_email_account(account_id)
    return RedirectResponse(url="/inbox/accounts", status_code=303)


@router.get("/inbox/oauth/start")
def oauth_start(request: Request):
    if not google_oauth.is_configured():
        return RedirectResponse(
            url="/inbox/accounts?error=Google+sign-in+isn%27t+configured+yet+-+see+README.",
            status_code=303,
        )
    state = secrets.token_urlsafe(24)
    request.session["oauth_state"] = state
    return RedirectResponse(url=google_oauth.build_auth_url(state), status_code=303)


@router.get("/inbox/oauth/callback")
def oauth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return RedirectResponse(url=f"/inbox/accounts?error=Google+sign-in+cancelled:+{quote(error)}", status_code=303)

    expected_state = request.session.pop("oauth_state", None)
    if not state or not expected_state or not secrets.compare_digest(state, expected_state):
        return RedirectResponse(url="/inbox/accounts?error=Sign-in+state+mismatch,+try+again.", status_code=303)

    if not code:
        return RedirectResponse(url="/inbox/accounts?error=No+authorization+code+returned.", status_code=303)

    try:
        tokens = google_oauth.exchange_code(code)
        userinfo = google_oauth.get_userinfo(tokens["access_token"])
    except EmailAuthError as exc:
        return RedirectResponse(url=f"/inbox/accounts?error={quote(str(exc))}", status_code=303)

    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        return RedirectResponse(
            url="/inbox/accounts?error=Google+didn%27t+return+a+refresh+token+-+"
            "remove+this+app%27s+access+at+myaccount.google.com/permissions+and+try+again.",
            status_code=303,
        )

    expires_in = tokens.get("expires_in", 3600)
    expiry = (datetime.now(timezone.utc) + timedelta(seconds=expires_in)).isoformat()

    db.upsert_oauth_account(
        email_address=userinfo["email"],
        display_name=userinfo.get("name") or userinfo["email"],
        refresh_token_enc=email_client.encrypt_password(refresh_token),
        access_token_enc=email_client.encrypt_password(tokens["access_token"]),
        token_expiry=expiry,
        scopes=tokens.get("scope"),
    )
    account = next((a for a in db.list_email_accounts() if a["email_address"] == userinfo["email"]), None)
    if account:
        mail_sync.sync_soon(account["id"])
    return RedirectResponse(url="/inbox/accounts", status_code=303)
