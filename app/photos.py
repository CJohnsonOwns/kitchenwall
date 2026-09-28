"""Photos on whiteboard notes and Sharing posts, stored as files next to the database:

    data/photos/<name>             the original, full resolution, as uploaded
    data/photos/thumb/<stem>.jpg   a smaller copy the browser makes before upload (notes,
                                   profile pictures; Sharing posts show the original)

Names are random (unguessable, never reused), so files can be cached forever
and a name can't point anywhere else. The type is taken from the file's first
bytes, not from what the browser claims. Only JPEG, PNG, WebP and GIF are
kept: they're what every browser can show.

There's no size cap unless MAX_PHOTO_MB is set in .env. Uploads are copied to
disk in chunks, never read whole into memory.
"""
import io
import os
import re
import secrets
import shutil
from pathlib import Path
from typing import BinaryIO

from . import db

THUMB_MAX_BYTES = 8 * 1024 * 1024
_CHUNK = 1024 * 1024
_NAME = re.compile(r"^[A-Za-z0-9_-]{16}\.(jpg|png|webp|gif)$")
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp", "gif": "image/gif"}


class PhotoError(ValueError):
    pass


def cap_bytes(env_name: str) -> int | None:
    """Upload cap from .env in MB (e.g. MAX_PHOTO_MB=50); unset or 0 = no cap."""
    try:
        mb = int(os.environ.get(env_name, "0") or 0)
    except ValueError:
        return None
    return mb * 1024 * 1024 if mb > 0 else None


def _dir() -> Path:
    return db.DB_PATH.parent / "photos"


def sniff(data: bytes) -> str | None:
    """File extension for the image type in `data`, or None if it isn't one we keep."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    return None


def as_stream(src: bytes | BinaryIO) -> BinaryIO:
    return io.BytesIO(src) if isinstance(src, (bytes, bytearray)) else src


MIN_FREE = 0.05  # uploads stop when the disk is 95% full, so the database always has room


def _disk_nearly_full(folder: Path) -> bool:
    u = shutil.disk_usage(folder)
    return u.free < u.total * MIN_FREE


def write_limited(src: BinaryIO, head: bytes, dest: Path, limit: int | None, too_big: str) -> None:
    """Writes `head` and then the rest of `src` to `dest` in chunks. Raises
    PhotoError (and leaves no file) if the total goes over `limit` or the
    disk gets nearly full while writing."""
    if _disk_nearly_full(dest.parent):
        raise PhotoError("The server's disk is nearly full, so uploads are paused.")
    written = len(head)
    try:
        with open(dest, "wb") as out:
            out.write(head)
            while chunk := src.read(_CHUNK):
                written += len(chunk)
                if limit is not None and written > limit:
                    raise PhotoError(too_big)
                if written % (256 * _CHUNK) < _CHUNK and _disk_nearly_full(dest.parent):  # every ~256 MB
                    raise PhotoError("The server's disk is nearly full, so the upload was stopped.")
                out.write(chunk)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def save(original: bytes | BinaryIO, thumb: bytes | None = None) -> str:
    """Stores a photo (and its thumbnail, if the browser made a usable one); returns its name."""
    src = as_stream(original)
    head = src.read(16)
    if not head:
        raise PhotoError("That file was empty.")
    ext = sniff(head)
    if not ext:
        raise PhotoError("That isn't a photo this app can show (use JPEG, PNG, WebP or GIF).")
    limit = cap_bytes("MAX_PHOTO_MB")
    name = f"{secrets.token_urlsafe(12)}.{ext}"
    folder = _dir()
    (folder / "thumb").mkdir(parents=True, exist_ok=True)
    write_limited(src, head, folder / name, limit, f"That photo is over {(limit or 0) >> 20} MB.")
    if thumb and len(thumb) <= THUMB_MAX_BYTES and sniff(thumb) in ("jpg", "webp", "png"):
        (folder / "thumb" / f"{name.rsplit('.', 1)[0]}.jpg").write_bytes(thumb)
    return name


def path(name: str, thumb: bool = False) -> Path | None:
    """The file to serve for a photo name, or None if the name is bad or missing.
    A missing thumbnail falls back to the original."""
    if not _NAME.match(name or ""):
        return None
    full = _dir() / name
    if thumb:
        small = _dir() / "thumb" / f"{name.rsplit('.', 1)[0]}.jpg"
        if small.is_file():
            return small
    return full if full.is_file() else None


def media_type(file: Path) -> str:
    return MEDIA_TYPES.get(file.suffix.lstrip("."), "application/octet-stream")


def delete(name: str | None) -> None:
    if not name or not _NAME.match(name):
        return
    (_dir() / name).unlink(missing_ok=True)
    (_dir() / "thumb" / f"{name.rsplit('.', 1)[0]}.jpg").unlink(missing_ok=True)
