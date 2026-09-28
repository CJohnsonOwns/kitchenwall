"""Gmail over the Gmail API, for accounts connected with "Sign in with Google".

Sync is two-way: the first sync lists the Inbox, Sent and Starred views;
after that Gmail's history feed tells us exactly what changed (new mail,
label changes, deletions), so each check is a single cheap call.
"""
import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urlencode

import requests

from .. import db
from .mail_mime import received_from_epoch_ms
from .mail_utils import EmailAuthError, ScopeError, decrypt_password, encrypt_password

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_BASE = "https://gmail.googleapis.com/gmail/v1/users/me"

MODIFY_SCOPE = "https://www.googleapis.com/auth/gmail.modify"
SCOPES = " ".join(
    [
        MODIFY_SCOPE,  # read, archive, trash, star, read/unread (includes readonly)
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/userinfo.email",
    ]
)

# Google only allows plain-http redirect URIs on localhost/127.0.0.1, so the
# one-time sign-in is done through an SSH tunnel to the server (see README).
# Once the app has a public https address, set GOOGLE_REDIRECT_URI in .env to
# https://<that address>/inbox/oauth/callback (and add it in Google Cloud).
REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI") or "http://127.0.0.1:8000/inbox/oauth/callback"

REQUEST_TIMEOUT = 20
WORKERS = 8

# How many recent messages of each view the first sync pulls in.
VIEW_QUERIES = {"inbox": ("in:inbox", 100), "sent": ("in:sent", 50), "starred": ("is:starred", 50)}

METADATA_HEADERS = ["From", "To", "Subject", "Date", "Message-ID"]


class HistoryExpired(Exception):
    pass


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_CLIENT_ID")) and bool(os.environ.get("GOOGLE_CLIENT_SECRET"))


def _client_id() -> str:
    return os.environ["GOOGLE_CLIENT_ID"]


def _client_secret() -> str:
    return os.environ["GOOGLE_CLIENT_SECRET"]


def build_auth_url(state: str) -> str:
    params = {
        "client_id": _client_id(),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise EmailAuthError(f"Google sign-in failed: {resp.status_code} {resp.text}")
    return resp.json()


def get_userinfo(access_token: str) -> dict:
    resp = requests.get(USERINFO_URL, headers=_auth_header(access_token), timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _auth_header(access_token: str) -> dict:
    return {"Authorization": f"Bearer {access_token}"}


def can_modify(account) -> bool | None:
    """True/False if we know whether the grant includes modify, None if unknown yet."""
    scopes = account["scopes"] if "scopes" in account.keys() else None
    if not scopes:
        return None
    return MODIFY_SCOPE in scopes.split()


def _refresh_access_token(refresh_token: str) -> dict:
    resp = requests.post(
        TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": _client_id(),
            "client_secret": _client_secret(),
            "grant_type": "refresh_token",
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code >= 400:
        raise EmailAuthError(
            f"Google token refresh failed ({resp.status_code}). The account may need to be "
            "reconnected via Sign in with Google."
        )
    return resp.json()


def _token(account, force: bool = False) -> str:
    """A valid access token for an account row, refreshing (and recording scopes) if needed."""
    now = datetime.now(timezone.utc)
    needs_refresh = True
    if not force and account["token_expiry"]:
        try:
            needs_refresh = now >= datetime.fromisoformat(account["token_expiry"]) - timedelta(minutes=2)
        except ValueError:
            needs_refresh = True
    if not needs_refresh and account["access_token_enc"]:
        return decrypt_password(account["access_token_enc"])

    tokens = _refresh_access_token(decrypt_password(account["refresh_token_enc"]))
    access_token = tokens["access_token"]
    expiry = (now + timedelta(seconds=tokens.get("expires_in", 3600))).isoformat()
    db.update_oauth_tokens(account["id"], encrypt_password(access_token), expiry)
    if tokens.get("scope"):
        db.set_account_fields(account["id"], scopes=tokens["scope"])
    return access_token


class _Api:
    """Tiny Gmail REST helper bound to one account."""

    def __init__(self, account):
        self.account = account
        self.token = _token(account)

    def call(self, method: str, path: str, **kw):
        resp = requests.request(
            method, GMAIL_BASE + path, headers=_auth_header(self.token), timeout=REQUEST_TIMEOUT, **kw
        )
        if resp.status_code == 401:
            self.token = _token(self.account, force=True)
            resp = requests.request(
                method, GMAIL_BASE + path, headers=_auth_header(self.token), timeout=REQUEST_TIMEOUT, **kw
            )
        if resp.status_code == 403 and "insufficient" in resp.text.lower():
            db.set_account_fields(self.account["id"], scopes="no-modify")
            raise ScopeError(
                f"{self.account['display_name']} needs to be reconnected before changes can reach Gmail. "
                "See Email accounts."
            )
        return resp

    def json(self, method: str, path: str, **kw) -> dict:
        resp = self.call(method, path, **kw)
        if resp.status_code >= 400:
            raise EmailAuthError(f"Gmail error for {self.account['email_address']}: {resp.status_code} {resp.text[:200]}")
        return resp.json() if resp.content else {}

    def list_ids(self, query: str, cap: int) -> list[str]:
        ids, page = [], None
        while len(ids) < cap:
            params = {"q": query, "maxResults": min(500, cap - len(ids))}
            if page:
                params["pageToken"] = page
            data = self.json("GET", "/messages", params=params)
            ids += [m["id"] for m in data.get("messages", [])]
            page = data.get("nextPageToken")
            if not page:
                break
        return ids

    def metadata(self, ids: list[str]) -> list[dict]:
        def one(mid):
            resp = self.call(
                "GET",
                f"/messages/{mid}",
                params=[("format", "metadata")] + [("metadataHeaders", h) for h in METADATA_HEADERS],
            )
            return resp.json() if resp.status_code < 400 else None

        if not ids:
            return []
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            return [m for m in pool.map(one, ids) if m]


def _flags(labels: set[str]) -> dict:
    return {
        "is_read": 0 if "UNREAD" in labels else 1,
        "in_inbox": 1 if "INBOX" in labels else 0,
        "in_sent": 1 if "SENT" in labels else 0,
        "is_starred": 1 if "STARRED" in labels else 0,
        "is_trashed": 1 if ("TRASH" in labels or "SPAM" in labels) else 0,
    }


def _keep(labels: set[str]) -> bool:
    if "DRAFT" in labels or "TRASH" in labels or "SPAM" in labels:
        return False
    return bool(labels & {"INBOX", "SENT", "STARRED"})


def _row(meta: dict) -> dict:
    headers = {h["name"].lower(): h["value"] for h in meta.get("payload", {}).get("headers", [])}
    labels = set(meta.get("labelIds", []))
    row = {
        "uid": meta["id"],
        "thread_id": meta.get("threadId"),
        "message_id": headers.get("message-id"),
        "sender": headers.get("from", ""),
        "to_addrs": headers.get("to", ""),
        "subject": headers.get("subject") or "(no subject)",
        "date_header": headers.get("date"),
        "received_at": received_from_epoch_ms(meta.get("internalDate")),
        "snippet": unescape(meta.get("snippet") or "").strip() or None,
        "imap_uid": None,
    }
    row.update(_flags(labels))
    return row


# ---- Sync ----

def sync(account) -> None:
    api = _Api(account)
    if not account["history_id"] or (account["sync_version"] or 1) < 2:
        _full_sync(api)
        return
    try:
        _incremental_sync(api)
    except HistoryExpired:
        _full_sync(api)


def _full_sync(api: _Api) -> None:
    account_id = api.account["id"]
    history_id = api.json("GET", "/profile").get("historyId")
    ids: list[str] = []
    for query, cap in VIEW_QUERIES.values():
        for mid in api.list_ids(query, cap):
            if mid not in ids:
                ids.append(mid)
    rows = [_row(m) for m in api.metadata(ids)]
    rows = [r for r in rows if not r["is_trashed"]]
    if (api.account["sync_version"] or 1) < 2:
        db.delete_account_messages(account_id)
    keep = {r["uid"] for r in rows}
    cached = db.cached_messages(account_id)
    db.delete_messages(account_id, [u for u in cached if u not in keep])
    db.upsert_messages(account_id, rows)
    db.set_account_fields(account_id, history_id=str(history_id), sync_version=2)


def _incremental_sync(api: _Api) -> None:
    account_id = api.account["id"]
    state: dict[str, set | None] = {}
    page, latest = None, None
    while True:
        params = {"startHistoryId": api.account["history_id"], "maxResults": 500}
        if page:
            params["pageToken"] = page
        resp = api.call("GET", "/history", params=params)
        if resp.status_code == 404:
            raise HistoryExpired()
        if resp.status_code >= 400:
            raise EmailAuthError(f"Gmail history failed for {api.account['email_address']}: {resp.text[:200]}")
        data = resp.json()
        latest = data.get("historyId", latest)
        for entry in data.get("history", []):
            for key in ("messagesAdded", "labelsAdded", "labelsRemoved"):
                for rec in entry.get(key, []):
                    m = rec.get("message", {})
                    if "id" in m:
                        state[m["id"]] = set(m.get("labelIds", []))
            for rec in entry.get("messagesDeleted", []):
                m = rec.get("message", {})
                if "id" in m:
                    state[m["id"]] = None
        page = data.get("nextPageToken")
        if not page:
            break

    cached = db.cached_messages(account_id)
    drop, updates, fetch = [], {}, []
    for mid, labels in state.items():
        if labels is None or not _keep(labels):
            if mid in cached:
                drop.append(mid)
        elif mid in cached:
            updates[mid] = _flags(labels)
        else:
            fetch.append(mid)
    db.delete_messages(account_id, drop)
    db.set_flags_per_message(account_id, updates)
    new_rows = [_row(m) for m in api.metadata(fetch)]
    db.upsert_messages(account_id, [r for r in new_rows if not r["is_trashed"]])
    if latest:
        db.set_account_fields(account_id, history_id=str(latest))


def fetch_older(account, view: str, count: int = 50) -> int:
    """Pull `count` messages older than the oldest cached one in a view. Returns how many."""
    api = _Api(account)
    query, _ = VIEW_QUERIES[view]
    oldest, _ = db.oldest_in_view(account["id"], view)
    if oldest:
        try:
            epoch = int(datetime.fromisoformat(oldest).timestamp())
            query += f" before:{epoch}"
        except ValueError:
            pass
    rows = [_row(m) for m in api.metadata(api.list_ids(query, count))]
    rows = [r for r in rows if not r["is_trashed"]]
    db.upsert_messages(account["id"], rows)
    return len(rows)


def search(account, query: str, limit: int = 40) -> list[dict]:
    api = _Api(account)
    return [_row(m) for m in api.metadata(api.list_ids(query, limit))]


# ---- Reading ----

def get_raw(account, uid: str) -> bytes:
    data = _Api(account).json("GET", f"/messages/{uid}", params={"format": "raw"})
    return base64.urlsafe_b64decode(data["raw"] + "=" * (-len(data["raw"]) % 4))


def thread_messages(account, uid: str, have_bodies: set[str]) -> list[dict]:
    """Messages of the conversation containing `uid`, oldest first.

    Each item: uid, thread_id, flags, and `raw` bytes unless its body is already cached.
    """
    api = _Api(account)
    thread_id = api.json("GET", f"/messages/{uid}", params={"format": "minimal"}).get("threadId")
    data = api.json("GET", f"/threads/{thread_id}", params={"format": "minimal"})
    items = []
    for m in data.get("messages", []):
        labels = set(m.get("labelIds", []))
        if "DRAFT" in labels:
            continue
        item = {"uid": m["id"], "thread_id": thread_id, "received_at": received_from_epoch_ms(m.get("internalDate")), "raw": None}
        item.update(_flags(labels))
        items.append(item)

    need = [i for i in items if i["uid"] not in have_bodies]

    def fetch(item):
        item["raw"] = get_raw_with(api, item["uid"])

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(fetch, need))
    return items


def get_raw_with(api: _Api, uid: str) -> bytes:
    data = api.json("GET", f"/messages/{uid}", params={"format": "raw"})
    return base64.urlsafe_b64decode(data["raw"] + "=" * (-len(data["raw"]) % 4))


# ---- Changing ----

_LABEL_ACTIONS = {
    "read": ([], ["UNREAD"]),
    "unread": (["UNREAD"], []),
    "star": (["STARRED"], []),
    "unstar": ([], ["STARRED"]),
    "archive": ([], ["INBOX"]),
    "inbox": (["INBOX"], []),
}


def modify(account, uids: list[str], action: str, to_inbox: bool = True) -> None:
    if not uids:
        return
    if can_modify(account) is False:
        raise ScopeError(
            f"{account['display_name']} needs to be reconnected before changes can reach Gmail. See Email accounts."
        )
    api = _Api(account)
    if action in _LABEL_ACTIONS:
        add, remove = _LABEL_ACTIONS[action]
        api.json("POST", "/messages/batchModify", json={"ids": uids, "addLabelIds": add, "removeLabelIds": remove})
    elif action == "trash":
        for uid in uids:
            api.json("POST", f"/messages/{uid}/trash")
    elif action == "untrash":
        for uid in uids:
            api.json("POST", f"/messages/{uid}/untrash")
        if to_inbox:
            api.json("POST", "/messages/batchModify", json={"ids": uids, "addLabelIds": ["INBOX"], "removeLabelIds": []})
    else:
        raise ValueError(action)


def send(account, mime_msg, thread_id: str | None = None) -> None:
    payload = {"raw": base64.urlsafe_b64encode(mime_msg.as_bytes()).decode()}
    if thread_id:
        payload["threadId"] = thread_id
    _Api(account).json("POST", "/messages/send", json=payload)
