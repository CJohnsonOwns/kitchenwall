import os
import re
from email.header import decode_header, make_header
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"

_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script>", re.IGNORECASE | re.DOTALL)
_ON_ATTR_RE = re.compile(r"""\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""", re.IGNORECASE)


class EmailAuthError(Exception):
    """Raised when an email login/API call fails (bad credentials, expired token, etc.)."""


class ScopeError(EmailAuthError):
    """A Google account was connected before the dashboard asked for permission
    to change mail (archive, delete, read state). It needs one reconnect."""


def ensure_email_key() -> bytes:
    """Make sure a persistent Fernet key exists for encrypting credentials at rest."""
    key = os.environ.get("EMAIL_ENC_KEY")
    if key:
        return key.encode()

    new_key = Fernet.generate_key()
    with open(ENV_PATH, "a", encoding="utf-8") as f:
        f.write(f"\nEMAIL_ENC_KEY={new_key.decode()}\n")
    os.environ["EMAIL_ENC_KEY"] = new_key.decode()
    return new_key


def _fernet() -> Fernet:
    key = os.environ.get("EMAIL_ENC_KEY")
    if not key:
        key = ensure_email_key().decode()
    return Fernet(key.encode())


def encrypt_password(plain: str) -> bytes:
    return _fernet().encrypt(plain.encode())


def decrypt_password(token: bytes) -> str:
    try:
        return _fernet().decrypt(bytes(token)).decode()
    except InvalidToken as exc:
        raise EmailAuthError("Stored credential could not be decrypted.") from exc


def decode_mime_words(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def sanitize_html(html: str) -> str:
    """Defense-in-depth on top of the sandboxed iframe the HTML renders in:
    strip <script> tags and inline event-handler attributes."""
    html = _SCRIPT_RE.sub("", html)
    html = _ON_ATTR_RE.sub("", html)
    return html
