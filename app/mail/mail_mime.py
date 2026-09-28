"""Parse raw RFC 822 mail into what the templates need, and build outgoing mail.

Both account types hand us the same raw bytes (Gmail API `format=raw`, IMAP
`BODY[]`), so there is one parser. Attachments are identified by their
position in `msg.walk()`, which is stable for the same raw message.
"""
import html as html_lib
import re
from datetime import datetime
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

from .mail_utils import sanitize_html

_WS_RE = re.compile(r"\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_BLOCK_RE = re.compile(r"(?is)<(style|script|head|title)\b.*?</\1\s*>")
_BREAK_RE = re.compile(r"(?i)<br\s*/?>|</(p|div|tr|li|h[1-6]|blockquote)\s*>")
_BASE_RE = re.compile(r"(?is)<base\b[^>]*>")
_META_REFRESH_RE = re.compile(r"(?is)<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh[^>]*>")
_CID_RE = re.compile(r"cid:([^\"'\s)>]+)", re.IGNORECASE)


def _header(msg, name: str) -> str:
    try:
        value = msg.get(name)
    except Exception:  # malformed header — keep going with what we have
        value = msg.get_all(name, [None])[0] if hasattr(msg, "get_all") else None
    return str(value).strip() if value is not None else ""


def html_to_text(html: str) -> str:
    text = _BLOCK_RE.sub("", html)
    text = _BREAK_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    text = html_lib.unescape(text)
    lines = [ln.strip() for ln in text.splitlines()]
    out, blank = [], 0
    for ln in lines:
        blank = blank + 1 if not ln else 0
        if blank <= 1:
            out.append(ln)
    return "\n".join(out).strip()


def make_snippet(text: str, limit: int = 180) -> str:
    return _WS_RE.sub(" ", text or "").strip()[:limit]


def _decode(part) -> bytes:
    try:
        return part.get_payload(decode=True) or b""
    except Exception:
        return b""


def _text_of(part) -> str:
    try:
        return part.get_content()
    except Exception:
        payload = _decode(part)
        charset = part.get_content_charset() or "utf-8"
        try:
            return payload.decode(charset, errors="replace")
        except LookupError:
            return payload.decode("utf-8", errors="replace")


def parse_raw(raw: bytes) -> dict:
    """Headers, bodies and attachment list for one raw message."""
    msg = message_from_bytes(raw, policy=policy.default)

    html_part = text_part = None
    try:
        html_part = msg.get_body(preferencelist=("html",))
        text_part = msg.get_body(preferencelist=("plain",))
    except Exception:
        pass

    attachments = []
    for index, part in enumerate(msg.walk()):
        if part.is_multipart() or part is html_part or part is text_part:
            continue
        filename = part.get_filename()
        cid = (part.get("Content-ID") or "").strip().strip("<>")
        disposition = (part.get_content_disposition() or "").lower()
        if not filename and not cid and disposition != "attachment":
            continue
        data = _decode(part)
        attachments.append(
            {
                "index": index,
                "filename": filename or (f"image-{index}" if part.get_content_maintype() == "image" else f"attachment-{index}"),
                "mime": part.get_content_type(),
                "size": len(data),
                "cid": cid or None,
                # Inline images referenced from the HTML aren't listed as attachments.
                "inline": bool(cid) and disposition != "attachment",
            }
        )

    html_body = _text_of(html_part) if html_part is not None else None
    text_body = _text_of(text_part) if text_part is not None else None
    if html_body:
        html_body = sanitize_html(html_body)
        html_body = _BASE_RE.sub("", html_body)
        html_body = _META_REFRESH_RE.sub("", html_body)
        cids = {a["cid"] for a in attachments if a["cid"]}
        for a in attachments:
            if a["inline"] and a["cid"] not in cids:
                a["inline"] = False
        # Inline images that the HTML never references are shown as attachments.
        referenced = {m.lower() for m in _CID_RE.findall(html_body)}
        for a in attachments:
            if a["inline"] and a["cid"] and a["cid"].lower() not in referenced:
                a["inline"] = False
    else:
        for a in attachments:
            a["inline"] = False
    if not html_body and not text_body:
        text_body = "(empty message)"

    headers = {
        "from": _header(msg, "From"),
        "to": _header(msg, "To"),
        "cc": _header(msg, "Cc"),
        "reply_to": _header(msg, "Reply-To"),
        "subject": _header(msg, "Subject") or "(no subject)",
        "date": _header(msg, "Date"),
        "message_id": _header(msg, "Message-ID"),
        "references": _header(msg, "References"),
    }
    plain = text_body if text_body else html_to_text(html_body or "")
    return {
        "headers": headers,
        "html": html_body,
        "text": text_body,
        "plain": plain,
        "snippet": make_snippet(plain),
        "attachments": attachments,
    }


def get_part(raw: bytes, index: int):
    """(filename, mime, bytes) of the part at `index` in walk order, or None."""
    msg = message_from_bytes(raw, policy=policy.default)
    for i, part in enumerate(msg.walk()):
        if i == index and not part.is_multipart():
            return (part.get_filename() or f"attachment-{i}", part.get_content_type(), _decode(part))
    return None


def attachment_parts(raw: bytes, indexes=None) -> list[tuple[str, str, bytes]]:
    """Real (non-inline) attachments of a message, for forwarding.

    `indexes` limits it to the attachments the person kept ticked; None means all.
    """
    parsed = parse_raw(raw)
    wanted = None if indexes is None else {int(i) for i in indexes}
    out = []
    for a in parsed["attachments"]:
        if a["inline"] or (wanted is not None and a["index"] not in wanted):
            continue
        part = get_part(raw, a["index"])
        if part:
            out.append(part)
    return out


def snippet_from_partial(header_bytes: bytes, text_bytes: bytes) -> str:
    """Best-effort preview line from the headers plus the first few KB of the body."""
    try:
        msg = message_from_bytes(header_bytes.rstrip(b"\r\n") + b"\r\n\r\n" + (text_bytes or b""), policy=policy.default)
        part = None
        try:
            part = msg.get_body(preferencelist=("plain", "html"))
        except Exception:
            part = None
        if part is None:
            return ""
        body = _text_of(part)
        if part.get_content_subtype() == "html":
            body = html_to_text(body)
        return make_snippet(body)
    except Exception:
        return ""


# ---- Addresses ----

def address_list(value: str) -> list[tuple[str, str]]:
    """'A <a@x>, b@y' -> [('A', 'a@x'), ('', 'b@y')] with empties dropped."""
    return [(n, a) for n, a in getaddresses([value or ""]) if a and "@" in a]


def display_name(value: str) -> str:
    name, addr = parseaddr(value or "")
    return name.strip().strip('"') or addr or (value or "").strip() or "(unknown)"


def join_addresses(pairs) -> str:
    return ", ".join(formataddr((n, a)) if n else a for n, a in pairs)


def reply_targets(headers: dict, own_address: str, reply_all: bool) -> tuple[str, str]:
    """(to, cc) strings for a reply or reply-all."""
    own = own_address.lower()
    from_pairs = address_list(headers.get("from", ""))
    from_self = bool(from_pairs) and from_pairs[0][1].lower() == own
    if from_self:
        # Replying to something we sent: go back to its original recipients.
        to_pairs = address_list(headers.get("to", ""))
    else:
        to_pairs = address_list(headers.get("reply_to", "")) or from_pairs
    cc_pairs = []
    if reply_all:
        taken = {a.lower() for _, a in to_pairs} | {own}
        for n, a in address_list(headers.get("to", "")) + address_list(headers.get("cc", "")):
            if a.lower() not in taken:
                cc_pairs.append((n, a))
                taken.add(a.lower())
    return join_addresses(to_pairs), join_addresses(cc_pairs)


def prefixed_subject(subject: str, prefix: str) -> str:
    subject = (subject or "").strip()
    if subject.lower().startswith(prefix.lower()):
        return subject
    return f"{prefix} {subject}".strip()


def nice_date(date_header: str) -> str:
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return date_header or ""
    if dt.tzinfo:
        dt = dt.astimezone()
    return f"{dt.strftime('%a, %b')} {dt.day}, {dt.year} at {dt.strftime('%I:%M %p').lstrip('0')}"


def quote_block(headers: dict, plain: str) -> str:
    lines = (plain or "").strip().splitlines()
    quoted = "\n".join(("> " + ln) if ln else ">" for ln in lines)
    return f"\n\nOn {nice_date(headers.get('date', ''))}, {headers.get('from', '')} wrote:\n{quoted}\n"


def forward_block(headers: dict, plain: str) -> str:
    parts = [
        "\n\n---------- Forwarded message ---------",
        f"From: {headers.get('from', '')}",
        f"Date: {nice_date(headers.get('date', ''))}",
        f"Subject: {headers.get('subject', '')}",
        f"To: {headers.get('to', '')}",
    ]
    if headers.get("cc"):
        parts.append(f"Cc: {headers['cc']}")
    return "\n".join(parts) + "\n\n" + (plain or "").strip() + "\n"


def build_message(
    from_addr: str,
    to: str,
    cc: str,
    subject: str,
    body: str,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[tuple[str, str, bytes]] = (),
    bcc: str = "",
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        # SMTP's send_message and Gmail both strip this before delivery.
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    domain = from_addr.rsplit("@", 1)[-1].strip(">") if "@" in from_addr else None
    msg["Message-ID"] = make_msgid(domain=domain)
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = f"{references or ''} {in_reply_to}".strip()
    msg.set_content(body)
    for filename, mime, data in attachments:
        maintype, _, subtype = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(data, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)
    return msg


def recipients_of(msg: EmailMessage) -> list[str]:
    return [a for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Cc", []) + msg.get_all("Bcc", [])) if a]


def received_from_date(date_header: str | None) -> str | None:
    if not date_header:
        return None
    try:
        dt = parsedate_to_datetime(date_header)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat()


def received_from_epoch_ms(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000).astimezone().isoformat()
    except (TypeError, ValueError, OSError):
        return None
