"""Keep the mail cache in step with Gmail.

Used by the Refresh button and by a background thread that runs on the
server every `mail_sync_minutes` (a household setting), so the inbox is
current even when nobody has pressed Refresh.
"""
import logging
import threading
import time
from datetime import datetime

from .. import db
from . import email_client
from .email_client import EmailAuthError
from ..settings_store import get_int

log = logging.getLogger("household.mail_sync")

_sync_lock = threading.Lock()
_last_auto_sync: float = 0.0


def sync_all_accounts(account_id: int | None = None) -> list[str]:
    """Sync every account (or one). Returns a list of human-readable errors."""
    errors: list[str] = []
    with _sync_lock:
        for account in db.list_email_accounts():
            if account_id and account["id"] != account_id:
                continue
            try:
                email_client.sync(account)
            except EmailAuthError as exc:
                errors.append(str(exc))
                continue
            except Exception as exc:  # network hiccups shouldn't kill the loop
                log.exception("mail sync failed for %s", account["email_address"])
                errors.append(f"{account['email_address']}: {exc}")
                continue
            db.set_account_synced_now(account["id"], datetime.now().isoformat())
        try:
            db.prune_bodies()
        except Exception:
            log.exception("body cache prune failed")
    return errors


def _loop() -> None:
    global _last_auto_sync
    time.sleep(45)  # let the app finish starting
    while True:
        try:
            minutes = get_int("mail_sync_minutes")
            if minutes > 0 and time.time() - _last_auto_sync >= minutes * 60:
                _last_auto_sync = time.time()
                for err in sync_all_accounts():
                    log.warning("mail sync: %s", err)
        except Exception:
            log.exception("mail sync loop error")
        time.sleep(60)


def start_background_sync() -> None:
    threading.Thread(target=_loop, name="mail-sync", daemon=True).start()


def sync_soon(account_id: int) -> None:
    """Sync one account in the background (e.g. right after it's connected)."""
    threading.Thread(target=lambda: sync_all_accounts(account_id), daemon=True).start()
