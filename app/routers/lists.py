"""Shopping lists: several fully separate lists (Shopping, Costco...). The page
renders one list; list.js then talks JSON to these routes and polls
/list/items so both phones stay current. Every change answers with that
list's items, every list's name and count (for the switcher), and a version
tag. Which list a device last looked at is remembered in a cookie."""
import hashlib
import json

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse

from .. import db
from ..core.templating import render

router = APIRouter()
TEXT_MAX = 200
NAME_MAX = 40
COOKIE = "list_id"


def _pick(lists: list[dict], wanted) -> dict:
    """The list for an id from a query string or cookie; the first list if it's gone or junk."""
    try:
        wanted = int(wanted)
    except (TypeError, ValueError):
        wanted = None
    return next((l for l in lists if l["id"] == wanted), lists[0])


def _state(list_id: int) -> dict:
    lists = db.lists_summary()
    items = [{"id": r["id"], "text": r["text"], "checked": bool(r["checked"])} for r in db.list_items(list_id)]
    version = hashlib.sha1(json.dumps([items, lists]).encode()).hexdigest()[:12]
    return {"ok": True, "list_id": list_id, "lists": lists, "items": items, "version": version}


def _clean(text, limit=TEXT_MAX) -> str:
    return " ".join(str(text or "").split())[:limit]


async def _payload(request: Request) -> dict:
    try:
        data = await request.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _list_or_404(l) -> dict | None:
    lists = db.lists_summary()
    try:
        return next((x for x in lists if x["id"] == int(l)), None)
    except (TypeError, ValueError):
        return None


def _gone():
    return JSONResponse({"ok": False, "gone": True, "error": "That list was deleted."}, status_code=404)


@router.get("/list")
def list_page(request: Request, l: str | None = None):
    lists = db.lists_summary()
    current = _pick(lists, l if l is not None else request.cookies.get(COOKIE))
    resp = render(request, "list.html", {"state": _state(current["id"]), "current": current})
    resp.set_cookie(COOKIE, str(current["id"]), max_age=365 * 86400, samesite="lax", httponly=True)
    return resp


@router.get("/list/items")
def list_state(l: int, since: str = ""):
    if not _list_or_404(l):
        return _gone()
    state = _state(l)
    if since and since == state["version"]:
        return JSONResponse({"ok": True, "same": True, "version": since})
    return JSONResponse(state)


# The JSON routes read the body asynchronously and then do the database work
# in the threadpool, so a slow write never blocks the event loop.

@router.post("/list/items")
async def add_item(request: Request, l: int):
    return await run_in_threadpool(_add_item, l, await _payload(request))


def _add_item(l: int, data: dict):
    if not _list_or_404(l):
        return _gone()
    text = _clean(data.get("text"))
    if not text:
        return JSONResponse({"ok": False, "error": "Type something to add."}, status_code=400)
    item_id = db.add_list_item(l, text)
    return JSONResponse(dict(_state(l), id=item_id))


@router.post("/list/items/{item_id}")
async def update_item(item_id: int, request: Request, l: int):
    return await run_in_threadpool(_update_item, item_id, l, await _payload(request))


def _update_item(item_id: int, l: int, data: dict):
    text = _clean(data["text"]) if "text" in data else None
    if text == "":
        return JSONResponse({"ok": False, "error": "An item needs some text. Use × to delete it."}, status_code=400)
    checked = bool(data["checked"]) if "checked" in data else None
    if not db.update_list_item(item_id, text=text, checked=checked):
        return JSONResponse(dict(_state(l), ok=False, error="That item is gone. Someone may have deleted it."), status_code=404)
    return JSONResponse(_state(l))


@router.post("/list/items/{item_id}/delete")
def delete_item(item_id: int, l: int):
    ids = db.delete_list_items([item_id])
    return JSONResponse(dict(_state(l), undo=ids))


@router.post("/list/clear")
def clear_checked(l: int):
    ids = db.delete_list_items(checked_on_list=l)
    return JSONResponse(dict(_state(l), undo=ids))


@router.post("/list/restore")
async def restore(request: Request, l: int):
    ids = (await _payload(request)).get("ids") or []
    return await run_in_threadpool(_restore, l, [i for i in ids if isinstance(i, int)])


def _restore(l: int, ids: list[int]):
    db.restore_list_items(ids)
    return JSONResponse(_state(l))


# ---- The lists themselves ----

@router.post("/lists")
async def create_list(request: Request):
    return await run_in_threadpool(_create_list, _clean((await _payload(request)).get("name"), NAME_MAX))


def _create_list(name: str):
    if not name:
        return JSONResponse({"ok": False, "error": "Give the list a name."}, status_code=400)
    if db.list_name_taken(name):
        return JSONResponse({"ok": False, "error": f"There's already a list called “{name}”."}, status_code=409)
    return JSONResponse({"ok": True, "id": db.create_list(name)})


@router.post("/lists/{list_id}")
async def rename_list(list_id: int, request: Request):
    return await run_in_threadpool(_rename_list, list_id, _clean((await _payload(request)).get("name"), NAME_MAX))


def _rename_list(list_id: int, name: str):
    if not name:
        return JSONResponse({"ok": False, "error": "Give the list a name."}, status_code=400)
    if db.list_name_taken(name, except_id=list_id):
        return JSONResponse({"ok": False, "error": f"There's already a list called “{name}”."}, status_code=409)
    if not db.rename_list(list_id, name):
        return _gone()
    return JSONResponse(_state(list_id))


@router.post("/lists/{list_id}/delete")
def delete_list(list_id: int):
    if not db.delete_list(list_id):
        return JSONResponse({"ok": False, "error": "You need at least one list, so the last one can't be deleted."},
                            status_code=409)
    return JSONResponse({"ok": True, "next": db.lists_summary()[0]["id"]})


@router.get("/lists/{list_id}")
def open_list(list_id: int):
    return RedirectResponse(url=f"/list?l={list_id}", status_code=303)
