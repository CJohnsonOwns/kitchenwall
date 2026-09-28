from urllib.parse import quote

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse

from ..core import auth
from .. import db, photos, weather
from ..settings_store import set_setting
from ..core.templating import render, templates
from ..core.web_utils import safe_next

router = APIRouter()


@router.get("/settings")
def settings_page(request: Request, error: str | None = None, saved: str | None = None,
                  pw_error: str | None = None):
    return render(
        request,
        "settings.html",
        {
            "error": error,
            "saved": saved,
            "pw_error": pw_error,
            "current_location": weather.get_location_label(),
            "accounts": db.list_email_accounts(),
            "categories": db.list_board_categories(),
        },
    )


@router.post("/settings/location")
def set_location(location: str = Form(...)):
    try:
        result = weather.geocode(location)
    except Exception:
        return RedirectResponse(url="/settings?error=Could+not+reach+the+weather+service.", status_code=303)

    if not result:
        return RedirectResponse(url=f"/settings?error=No+place+found+for+{quote(location)}.", status_code=303)

    weather.set_location(result["lat"], result["lon"], result["label"])
    return RedirectResponse(url="/settings?saved=1", status_code=303)


@router.post("/settings/password")
def change_password(request: Request, current: str = Form(...), new: str = Form(...), again: str = Form(...)):
    """Your own password. The new fingerprint signs out your other devices;
    this one is signed in again with it."""
    user = auth.current_user(request)
    if user is None:
        return RedirectResponse(url="/settings", status_code=303)

    def fail(msg: str):
        return RedirectResponse(url=f"/settings?pw_error={quote(msg)}#this-device", status_code=303)

    if not auth.verify_password(current, user["pw_hash"]):
        return fail("Your current password wasn't right.")
    if len(new) < auth.MIN_PASSWORD:
        return fail(f"The new password needs at least {auth.MIN_PASSWORD} characters.")
    if new != again:
        return fail("The two new passwords didn't match.")
    db.set_user_password(user["id"], auth.hash_password(new))
    auth.sign_in_user(request, db.get_user(user["id"]))
    return RedirectResponse(url="/settings?saved=pw", status_code=303)


@router.post("/settings/avatar")
def set_avatar(request: Request, avatar: UploadFile | None = File(None), avatar_thumb: UploadFile | None = File(None)):
    """Your profile picture (Sharing). The browser sends a square thumbnail too."""
    user = auth.current_user(request)
    if user is None or avatar is None or not avatar.filename:
        return RedirectResponse(url="/settings#this-device", status_code=303)
    thumb = avatar_thumb.file.read(photos.THUMB_MAX_BYTES + 1) if avatar_thumb and avatar_thumb.filename else None
    try:
        name = photos.save(avatar.file, thumb)
    except photos.PhotoError as e:
        return RedirectResponse(url=f"/settings?error={quote(str(e))}#this-device", status_code=303)
    photos.delete(db.set_user_avatar(user["id"], name))
    return RedirectResponse(url="/settings?saved=1#this-device", status_code=303)


@router.post("/settings/avatar/delete")
def remove_avatar(request: Request):
    user = auth.current_user(request)
    if user is not None:
        photos.delete(db.set_user_avatar(user["id"], None))
    return RedirectResponse(url="/settings#this-device", status_code=303)


@router.get("/password")
def first_password_page(request: Request, error: str | None = None):
    """Where someone with a temporary password lands after signing in."""
    user = auth.current_user(request)
    if user is None or not user["must_change"]:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "password.html", {"me": user, "error": error})


@router.post("/password")
def first_password(request: Request, new: str = Form(...), again: str = Form(...)):
    user = auth.current_user(request)
    if user is None or not user["must_change"]:
        return RedirectResponse(url="/", status_code=303)

    def fail(msg: str):
        return RedirectResponse(url=f"/password?error={quote(msg)}", status_code=303)

    if len(new) < auth.MIN_PASSWORD:
        return fail(f"It needs at least {auth.MIN_PASSWORD} characters.")
    if new != again:
        return fail("The two passwords didn't match.")
    if auth.verify_password(new, user["pw_hash"]):
        return fail("Pick something other than the temporary password.")
    db.set_user_password(user["id"], auth.hash_password(new))
    auth.sign_in_user(request, db.get_user(user["id"]))
    return RedirectResponse(url="/", status_code=303)


@router.post("/settings/pref")
def set_pref(key: str = Form(...), value: str = Form(...), next: str | None = Form(None)):
    """One endpoint for every segmented/select preference on the settings page."""
    try:
        ok = set_setting(key, value)
    except KeyError:
        ok = False
    if not ok:
        return RedirectResponse(url="/settings?error=That+setting+didn%27t+save.", status_code=303)
    if key == "units":
        weather.clear_cache()
    return RedirectResponse(url=safe_next(next, "/settings?saved=1"), status_code=303)
