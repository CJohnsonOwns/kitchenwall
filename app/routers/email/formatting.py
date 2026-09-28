"""Small text helpers for the inbox: dates, sizes, sender names, links, quoted replies."""
import re
from datetime import datetime, timedelta

from markupsafe import Markup, escape

from ...core.templating import templates
from ...mail.mail_mime import display_name as addr_display_name


def format_message_date(received_at: str | None) -> str:
    if not received_at:
        return ""
    try:
        dt = datetime.fromisoformat(received_at)
    except ValueError:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    if dt.date() == now.date():
        return dt.strftime("%I:%M %p").lstrip("0")
    if dt.date() == (now - timedelta(days=1)).date():
        return "Yesterday"
    if dt.year == now.year:
        return f"{dt.strftime('%b')} {dt.day}"
    return f"{dt.strftime('%b')} {dt.day}, {dt.year}"


def humanize_since(iso: str | None) -> str | None:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    mins = int((datetime.now() - then).total_seconds() // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return f"{then.strftime('%b')} {then.day}"


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1024 / 1024:.1f} MB"


def sender_name(sender: str | None) -> str:
    return addr_display_name(sender or "")


_URL_RE = re.compile(r"(https?://[^\s<>\"']+[^\s<>\"'.,;:!?)\]])")


def linkify(text: str) -> Markup:
    escaped = str(escape(text or ""))
    return Markup(_URL_RE.sub(r'<a href="\1" target="_blank" rel="noopener noreferrer">\1</a>', escaped))


templates.env.filters["linkify"] = linkify


def split_quote(text: str) -> tuple[str, str]:
    """Separate a plain-text reply from the quoted history under it."""
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        s = ln.strip()
        if s.startswith("On ") and s.endswith("wrote:") and i > 0:
            return "\n".join(lines[:i]).rstrip(), "\n".join(lines[i:])
        if s.startswith("---------- Forwarded message"):
            return text, ""
    # Trailing block of "> " lines.
    j = len(lines)
    while j > 0 and (lines[j - 1].startswith(">") or not lines[j - 1].strip()):
        j -= 1
    if j < len(lines) and j > 0 and any(l.startswith(">") for l in lines[j:]):
        return "\n".join(lines[:j]).rstrip(), "\n".join(lines[j:])
    return text, ""
