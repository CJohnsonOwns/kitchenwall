"""Videos on Sharing posts, stored as data/videos/<name>. Same rules as
photos.py: random names, type taken from the file's first bytes, copied to
disk in chunks. MP4/MOV (what phones record) and WebM only. No size cap
unless MAX_VIDEO_MB is set in .env.
"""
import re
import secrets
from pathlib import Path
from typing import BinaryIO

from . import db
from .photos import PhotoError, as_stream, cap_bytes, write_limited

_NAME = re.compile(r"^[A-Za-z0-9_-]{16}\.(mp4|mov|webm)$")
# .mov is served as video/mp4: same container family, and Chrome/Android won't
# try a video/quicktime source at all.
MEDIA_TYPES = {"mp4": "video/mp4", "mov": "video/mp4", "webm": "video/webm"}


def _dir() -> Path:
    return db.DB_PATH.parent / "videos"


def sniff(data: bytes) -> str | None:
    if data[4:8] == b"ftyp":
        # iPhones record QuickTime ("qt  "); everything else here is MP4-family.
        return "mov" if data[8:12] == b"qt  " else "mp4"
    if data[:4] == b"\x1a\x45\xdf\xa3":
        return "webm"
    return None


def save(original: bytes | BinaryIO) -> str:
    src = as_stream(original)
    head = src.read(16)
    if not head:
        raise PhotoError("That file was empty.")
    ext = sniff(head)
    if not ext:
        raise PhotoError("That isn't a video this app can play (use MP4, MOV or WebM).")
    limit = cap_bytes("MAX_VIDEO_MB")
    name = f"{secrets.token_urlsafe(12)}.{ext}"
    _dir().mkdir(parents=True, exist_ok=True)
    write_limited(src, head, _dir() / name, limit, f"That video is over {(limit or 0) >> 20} MB.")
    return name


def path(name: str) -> Path | None:
    if not _NAME.match(name or ""):
        return None
    full = _dir() / name
    return full if full.is_file() else None


def media_type(file: Path) -> str:
    return MEDIA_TYPES.get(file.suffix.lstrip("."), "application/octet-stream")


def delete(name: str | None) -> None:
    if name and _NAME.match(name):
        (_dir() / name).unlink(missing_ok=True)
