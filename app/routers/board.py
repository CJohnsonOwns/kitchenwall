import re
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from .. import db, photos
from ..core.templating import render
from ..core.web_utils import safe_next

router = APIRouter()

# Preset palette for note categories (Outlook-style: pick a colour, not a hex).
CATEGORY_COLORS = [
    ("#d96c5f", "Red"),
    ("#e0913f", "Orange"),
    ("#e3cc5a", "Yellow"),
    ("#6fae7b", "Green"),
    ("#4fa3a0", "Teal"),
    ("#5b8fd9", "Blue"),
    ("#9a7ad6", "Purple"),
    ("#d67aa8", "Pink"),
    ("#a3876a", "Brown"),
    ("#8a94a3", "Grey"),
]
_CATEGORY_HEXES = {hex_ for hex_, _ in CATEGORY_COLORS}
CATEGORY_NAME_MAX = 30

# Note paper colours offered in the composer.
NOTE_COLORS = [
    ("#fff7b2", "Yellow"),
    ("#c7f0c2", "Green"),
    ("#c2e0f0", "Blue"),
    ("#f0c2e0", "Pink"),
    ("#f0d9b5", "Orange"),
]
_NOTE_HEXES = {hex_ for hex_, _ in NOTE_COLORS}
NOTE_TEXT_MAX = 500
# Doodles arrive as "M x y L x y ..." (doodle.js pathFromPoints) with a pen colour.
STROKE_MAX = 200_000
_STROKE_PATH = re.compile(r"M[ \d.LM-]*")
_HEX = re.compile(r"#[0-9a-fA-F]{6}")

# A note's paper ages in stages the longer nobody touches it:
# fresh -> first crease -> yellowed & curling -> well-worn & dog-eared.
AGE_STAGE_DAYS = (3, 7, 14)


def age_stage(timestamp: str | None, now: datetime | None = None) -> int:
    """0-3 aging stage for a UTC 'YYYY-MM-DD HH:MM:SS' timestamp (SQLite datetime('now'))."""
    if not timestamp:
        return 0
    try:
        then = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 0
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    days = (now - then).total_seconds() / 86400
    return sum(days >= threshold for threshold in AGE_STAGE_DAYS)


def wear_style(item_id: int) -> str:
    """CSS variables giving each note its own crease angles and tilt.

    Derived from the id rather than random, so a note wrinkles the same way
    on every page load.
    """
    tilt = ((item_id * 7919) % 9 - 4) * 0.4          # -1.6 .. 1.6 deg
    crease_a = 18 + (item_id * 53) % 50               # 18 .. 67 deg
    crease_b = 108 + (item_id * 97) % 50              # 108 .. 157 deg
    shift = (item_id * 31) % 21 - 10                  # -10 .. 10 px
    return (
        f"--tilt: {tilt:.1f}deg; --crease-a: {crease_a}deg; "
        f"--crease-b: {crease_b}deg; --crease-shift: {shift}px;"
    )


def decorate(row, cats_by_item: dict[int, list[int]]) -> dict:
    item = dict(row)
    item["category_ids"] = cats_by_item.get(item["id"], [])
    item["age_stage"] = age_stage(item.get("touched_at") or item["created_at"])
    item["wear"] = wear_style(item["id"])
    return item


def board_context() -> dict:
    """Everything the board widget needs (also used by the home page peek)."""
    categories = [dict(c) for c in db.list_board_categories()]
    cats_by_item = db.category_ids_by_item()
    items = [decorate(r, cats_by_item) for r in db.list_board_items(include_checked=False)]
    return {
        "items": items,
        "aging_count": sum(1 for i in items if i["age_stage"] >= 2),
        "categories": categories,
        "categories_by_id": {c["id"]: c for c in categories},
        "cats_by_item": cats_by_item,
        "note_colors": NOTE_COLORS,
    }


def _clean_category(name: str, color: str) -> tuple[str, str]:
    name = " ".join(name.split())[:CATEGORY_NAME_MAX]
    if color not in _CATEGORY_HEXES:
        color = CATEGORY_COLORS[0][0]
    return name, color


def _safe_next(next_url: str | None) -> str:
    return safe_next(next_url, "/whiteboard")


@router.get("/board")
def board_page():
    return RedirectResponse(url="/whiteboard", status_code=303)


@router.get("/whiteboard")
def whiteboard_page(request: Request):
    ctx = board_context()
    ctx.update(
        {
            "strokes": db.list_strokes(),
            "done_items": [decorate(r, ctx["cats_by_item"]) for r in db.list_done_board_items()],
            "category_colors": CATEGORY_COLORS,
            "cat_error": request.query_params.get("cat_error"),
            "photo_error": request.query_params.get("photo_error"),
        }
    )
    return render(request, "whiteboard.html", ctx)


@router.post("/board/items")
def create_item(
    text: str = Form(...),
    color: str = Form("#fff7b2"),
    created_by: str = Form(""),
    category_ids: list[int] = Form([]),
    next: str | None = Form(None),
    photo: UploadFile | None = File(None),
    photo_thumb: UploadFile | None = File(None),
):
    text = text.strip()[:NOTE_TEXT_MAX]
    target = _safe_next(next)
    if text:
        if color not in _NOTE_HEXES:
            color = NOTE_COLORS[0][0]
        item_id = db.create_board_item(text, color, "note", created_by.strip()[:40])
        if category_ids:
            db.set_board_item_categories(item_id, category_ids)
        if _chosen(photo):
            try:
                db.set_board_item_photo(item_id, photos.save(photo.file, _read(photo_thumb, photos.THUMB_MAX_BYTES)))
            except photos.PhotoError as e:
                # The note is kept; say why the photo wasn't.
                sep = "&" if "?" in target else "?"
                target = f"{target}{sep}photo_error={quote(str(e))}"
    return RedirectResponse(url=target, status_code=303)


# The JSON routes below read the body asynchronously, then do the database
# work in the threadpool (run_in_threadpool), so a slow write never blocks the
# event loop for everyone else.

@router.patch("/board/items/{item_id}/text")
async def update_item_text(item_id: int, request: Request):
    return await run_in_threadpool(_update_item_text, item_id, await request.json())


def _update_item_text(item_id: int, payload: dict):
    text = str(payload.get("text", "")).strip()[:NOTE_TEXT_MAX]
    if not text:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
    db.update_board_item_text(item_id, text)
    return JSONResponse({"ok": True, "text": text})


@router.put("/board/items/{item_id}/categories")
async def update_item_categories(item_id: int, request: Request):
    ids = [int(i) for i in (await request.json()).get("category_ids", [])]
    await run_in_threadpool(db.set_board_item_categories, item_id, ids)
    return JSONResponse({"ok": True})


# ---- Categories (managed from the whiteboard's "Categories" dialog) ----

def _back_to_categories(ok: bool = True) -> RedirectResponse:
    url = "/whiteboard" + ("" if ok else "?cat_error=duplicate") + "#categories"
    return RedirectResponse(url=url, status_code=303)


@router.post("/board/categories")
def create_category(name: str = Form(...), color: str = Form("")):
    name, color = _clean_category(name, color)
    return _back_to_categories(not name or db.create_board_category(name, color))


@router.post("/board/categories/{category_id}")
def update_category(category_id: int, name: str = Form(...), color: str = Form("")):
    name, color = _clean_category(name, color)
    return _back_to_categories(not name or db.update_board_category(category_id, name, color))


@router.post("/board/categories/{category_id}/delete")
def delete_category(category_id: int):
    db.delete_board_category(category_id)
    return _back_to_categories()


@router.patch("/board/items/{item_id}/position")
async def update_position(item_id: int, request: Request):
    payload = await request.json()
    x = int(payload.get("x", 0))
    y = int(payload.get("y", 0))
    await run_in_threadpool(db.update_board_item_position, item_id, x, y)
    return JSONResponse({"ok": True})


@router.patch("/board/items/{item_id}/toggle")
async def toggle_item(item_id: int, request: Request):
    checked = 1 if (await request.json()).get("checked") else 0
    await run_in_threadpool(db.toggle_board_item_checked, item_id, checked)
    return JSONResponse({"ok": True})


@router.post("/board/items/{item_id}/delete")
def delete_item(item_id: int, next: str | None = Form(None)):
    photos.delete(db.delete_board_item(item_id))
    return RedirectResponse(url=_safe_next(next), status_code=303)


# ---- Photos on notes ----

def _chosen(upload: UploadFile | None) -> bool:
    return upload is not None and bool(upload.filename)


def _read(upload: UploadFile | None, limit: int) -> bytes | None:
    """A small upload's bytes (None if no file was chosen); reads one byte past
    the limit so an oversize file is caught without reading all of it."""
    if not _chosen(upload):
        return None
    return upload.file.read(limit + 1)


def _photo_urls(name: str) -> dict:
    return {"full": f"/board/photos/{name}", "thumb": f"/board/photos/{name}?size=thumb"}


@router.post("/board/items/{item_id}/photo")
def set_photo(item_id: int, photo: UploadFile | None = File(None), photo_thumb: UploadFile | None = File(None)):
    exists, old = db.get_board_item_photo(item_id)
    if not exists:
        return JSONResponse({"ok": False, "error": "That note is gone. Someone may have deleted it."}, status_code=404)
    try:
        name = photos.save(photo.file if _chosen(photo) else b"", _read(photo_thumb, photos.THUMB_MAX_BYTES))
    except photos.PhotoError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
    db.set_board_item_photo(item_id, name)
    photos.delete(old)
    return JSONResponse({"ok": True, **_photo_urls(name)})


@router.post("/board/items/{item_id}/photo/delete")
def remove_photo(item_id: int):
    exists, old = db.get_board_item_photo(item_id)
    if exists:
        db.set_board_item_photo(item_id, None)
        photos.delete(old)
    return JSONResponse({"ok": exists})


@router.get("/board/photos/{name}")
def get_photo(name: str, size: str = ""):
    file = photos.path(name, thumb=size == "thumb")
    if file is None:
        return Response(status_code=404)
    # Names are random and never reused, so the browser can keep them for good.
    return FileResponse(file, media_type=photos.media_type(file), headers={
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


@router.post("/board/items/{item_id}/restore")
def restore_item(item_id: int):
    db.toggle_board_item_checked(item_id, 0)
    return RedirectResponse(url="/whiteboard", status_code=303)


# ---- Doodle strokes ----

@router.post("/board/strokes")
async def create_stroke(request: Request):
    payload = await request.json()
    path = str(payload.get("path", ""))
    color = str(payload.get("color", "#d9a441"))
    width = max(1, min(12, int(payload.get("width", 3))))
    if not path or len(path) > STROKE_MAX or not _STROKE_PATH.fullmatch(path):
        return JSONResponse({"ok": False, "error": "bad path"}, status_code=400)
    if not _HEX.fullmatch(color):
        color = "#d9a441"
    stroke_id = await run_in_threadpool(db.create_stroke, path, color, width)
    return JSONResponse({"ok": True, "id": stroke_id})


@router.post("/board/strokes/undo")
def undo_stroke():
    db.delete_last_stroke()
    return RedirectResponse(url="/whiteboard", status_code=303)


@router.post("/board/strokes/clear")
def clear_all_strokes():
    db.clear_strokes()
    return RedirectResponse(url="/whiteboard", status_code=303)
