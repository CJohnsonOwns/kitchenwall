"""Sharing tab: a wall of posts (text, a photo or video, a link) with comments.

Only personal logins can write; the household login (wall screen) sees
everything but gets 403 on every change. You can edit/delete only your own
posts and comments. No likes or counts, on purpose.
"""
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote, urlparse

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from .. import db, photos, videos
from ..core.auth import current_user
from ..core.templating import render, templates
from ..core.web_utils import safe_next

router = APIRouter()

PAGE = 20
BODY_MAX = 5000
COMMENT_MAX = 2000
LINK_MAX = 2000
SHOWN_COMMENTS = 3
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_NO_WRITE = "Sign in as yourself to post. The household login can only look."
LIKE = "👍"
REACTIONS = ("❤️", "😂", "😮", "😢", "🎉")  # the picker, besides Like


def youtube_id(url: str | None) -> str | None:
    """The video id of a YouTube link (watch, youtu.be, shorts, embed), else None."""
    if not url:
        return None
    u = urlparse(url)
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    vid = None
    if host == "youtu.be":
        vid = u.path.strip("/").split("/")[0]
    elif host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        if u.path == "/watch":
            vid = (parse_qs(u.query).get("v") or [""])[0]
        elif u.path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = u.path.split("/")[2] if len(u.path.split("/")) > 2 else ""
    return vid if vid and _YT_ID.match(vid) else None


def clean_link(url: str) -> str | None:
    url = url.strip()[:LINK_MAX]
    if not url:
        return None
    if re.match(r"^[a-zA-Z][\w+.-]*:(?!//)", url) and not re.match(r"^[\w.-]+:\d", url):
        return None  # javascript:, data:, mailto: ... (but "host:8000/x" is fine)
    if "://" not in url:
        url = "https://" + url
    u = urlparse(url)
    return url if u.scheme in ("http", "https") and u.hostname else None


def when(ts: str | None, now: datetime | None = None) -> str:
    """'just now', '5 minutes ago', 'Yesterday at 3:12 PM', 'Mar 4 at 3:12 PM'."""
    if not ts:
        return ""
    t = datetime.fromisoformat(ts).replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    secs = (now - t).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        m = int(secs // 60)
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if secs < 6 * 3600:
        h = int(secs // 3600)
        return f"{h} hour{'s' if h != 1 else ''} ago"
    local, today = t.astimezone(), now.astimezone().date()
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == today:
        return f"Today at {clock}"
    if (today - local.date()).days == 1:
        return f"Yesterday at {clock}"
    fmt = f"{local.strftime('%b')} {local.day}" + (f", {local.year}" if local.year != today.year else "")
    return f"{fmt} at {clock}"


def _names(names: list[str]) -> str:
    return " and ".join(names) if len(names) < 3 else ", ".join(names[:-1]) + " and " + names[-1]


def reaction_summary(rows: list[dict], me) -> dict:
    """Who liked it ("You and Sam like this") and who reacted with what.
    Names, never counts: with two people a number would just be a tally."""
    mine = {r["emoji"] for r in rows if me and r["user_id"] == me["id"]}
    likers = ["You" if me and r["user_id"] == me["id"] else r["name"] for r in rows if r["emoji"] == LIKE]
    likers.sort(key=lambda n: n != "You")
    like_text = ""
    if likers:
        like_text = f"{_names(likers)} {'like' if likers[0] == 'You' or len(likers) > 1 else 'likes'} this"
    chips = []
    for e in REACTIONS:
        who = [r["name"] for r in rows if r["emoji"] == e]
        if who:
            chips.append({"emoji": e, "names": _names(who), "mine": e in mine})
    return {"liked": LIKE in mine, "like_text": like_text, "chips": chips, "mine": mine}


def _media_url(name: str, thumb: bool = False) -> str:
    return f"/share/media/{name}" + ("?size=thumb" if thumb else "")


@router.get("/share")
def share_page(request: Request, before: int | None = None, error: str | None = None):
    me = current_user(request)
    if me and not before:
        db.mark_share_seen(me["id"])  # before render(), so the tab badge clears now
    posts = db.list_posts(PAGE, before)
    for p in posts:
        p["when"] = when(p["created_at"])
        p["youtube"] = youtube_id(p["link_url"])
        p["mine"] = bool(me) and p["user_id"] == me["id"]
        # "New" = arrived since your previous visit (the values from before this one).
        p["new"] = bool(me) and not p["mine"] and p["id"] > me["seen_post"]
        for c in p["comments"]:
            c["when"] = when(c["created_at"])
            c["mine"] = bool(me) and c["user_id"] == me["id"]
            c["new"] = bool(me) and not c["mine"] and c["id"] > me["seen_comment"]
        p["rx"] = reaction_summary(p["reactions"], me)
        p["earlier"] = p["comments"][:-SHOWN_COMMENTS]
        p["latest"] = p["comments"][-SHOWN_COMMENTS:]
    return render(request, "share.html", {
        "posts": posts,
        "older": posts[-1]["id"] if len(posts) == PAGE else None,
        "before": before,
        "error": error,
        "media_url": _media_url,
        "reactions": REACTIONS,
    })


def _back(next: str | None, error: str | None = None, anchor: str = "") -> RedirectResponse:
    url = safe_next(next, "/share")
    if error:
        url += ("&" if "?" in url else "?") + "error=" + quote(error)
    return RedirectResponse(url=url + anchor, status_code=303)


def _chosen(upload: UploadFile | None) -> bool:
    return upload is not None and bool(upload.filename)


@router.post("/share/posts")
def create_post(
    request: Request,
    body: str = Form(""),
    link: str = Form(""),
    media: UploadFile | None = File(None),
):
    me = current_user(request)
    if me is None:
        return Response(_NO_WRITE, status_code=403)
    body = body.strip()[:BODY_MAX]
    link_url = clean_link(link)
    if link.strip() and not link_url:
        return _back(None, "That link doesn't look like a web address.")
    name = kind = None
    if _chosen(media):
        head = media.file.read(16)
        media.file.seek(0)
        try:
            if photos.sniff(head):
                # No thumbnail: the feed shows the original, full resolution.
                name, kind = photos.save(media.file), "photo"
            else:
                name, kind = videos.save(media.file), "video"
        except photos.PhotoError as e:
            return _back(None, f"{e} The post wasn't shared.")
    if not (body or link_url or name):
        return _back(None)
    post_id = db.create_post(me["id"], body, link_url, name, kind)
    return _back(None, anchor=f"#post-{post_id}")


def _own_post(request: Request, post_id: int):
    me = current_user(request)
    post = db.get_post(post_id)
    if me is None or post is None or post["user_id"] != me["id"]:
        return None
    return post


@router.post("/share/posts/{post_id}/edit")
def edit_post(request: Request, post_id: int, body: str = Form(""), next: str | None = Form(None)):
    post = _own_post(request, post_id)
    if post is None:
        return Response("Only the person who shared this can change it.", status_code=403)
    body = body.strip()[:BODY_MAX]
    if body or post["link_url"] or post["media_name"]:
        db.update_post_body(post_id, body)
    return _back(next, anchor=f"#post-{post_id}")


@router.post("/share/posts/{post_id}/delete")
def delete_post(request: Request, post_id: int, next: str | None = Form(None)):
    post = _own_post(request, post_id)
    if post is None:
        return Response("Only the person who shared this can delete it.", status_code=403)
    db.delete_post(post_id)
    (photos.delete if post["media_kind"] == "photo" else videos.delete)(post["media_name"])
    return _back(next)


@router.post("/share/posts/{post_id}/comments")
def add_comment(request: Request, post_id: int, body: str = Form(""), next: str | None = Form(None)):
    me = current_user(request)
    if me is None:
        return Response(_NO_WRITE, status_code=403)
    body = body.strip()[:COMMENT_MAX]
    if body and db.add_comment(post_id, me["id"], body) is None:
        return _back(next, "That post was deleted.")
    return _back(next, anchor=f"#post-{post_id}")


@router.post("/share/posts/{post_id}/react")
def react(request: Request, post_id: int, emoji: str = Form(...), next: str | None = Form(None)):
    """Toggle Like or an emoji reaction. From share.js (X-Fetch header) the
    answer is the post's refreshed reaction row, so the page doesn't jump."""
    me = current_user(request)
    if me is None:
        return Response(_NO_WRITE, status_code=403)
    if emoji not in (LIKE, *REACTIONS):
        return Response("Unknown reaction.", status_code=400)
    if db.toggle_reaction(post_id, me["id"], emoji) is None:
        return _back(next, "That post was deleted.")
    if request.headers.get("X-Fetch"):
        p = {"id": post_id, "rx": reaction_summary(db.post_reactions(post_id), me)}
        html = templates.get_template("_share_reactions.html").render(
            p=p, me=me, here=safe_next(next, "/share"), reactions=REACTIONS)
        return HTMLResponse(html)
    return _back(next, anchor=f"#post-{post_id}")


@router.post("/share/comments/{comment_id}/delete")
def delete_comment(request: Request, comment_id: int, next: str | None = Form(None)):
    me = current_user(request)
    c = db.get_comment(comment_id)
    if me is None or c is None or c["user_id"] != me["id"]:
        return Response("Only the person who wrote this can delete it.", status_code=403)
    db.delete_comment(comment_id)
    return _back(next, anchor=f"#post-{c['post_id']}")


@router.get("/share/media/{name}")
def get_media(name: str, size: str = ""):
    file = photos.path(name, thumb=size == "thumb") or videos.path(name)
    if file is None:
        return Response(status_code=404)
    kind = photos.media_type(file) if photos.path(name) else videos.media_type(file)
    # Names are random and never reused. FileResponse answers Range requests,
    # which iPhone Safari needs to play video.
    return FileResponse(file, media_type=kind, headers={
        "Cache-Control": "private, max-age=31536000, immutable",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })
