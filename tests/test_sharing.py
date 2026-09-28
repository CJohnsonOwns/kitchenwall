"""Personal logins and the Sharing tab, end to end over HTTP against the fake
server (users alex/sam, password 'changeme'), plus a few unit checks."""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
os.environ["HOUSEHOLD_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "unit.db")
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


# ---- Unit checks ----
from app import db, photos, videos  # noqa: E402
from app.routers.share import clean_link, when, youtube_id  # noqa: E402

db.init_db()
ok(all(youtube_id(u) == "dQw4w9WgXcQ" for u in (
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "https://youtu.be/dQw4w9WgXcQ?si=x",
    "https://m.youtube.com/shorts/dQw4w9WgXcQ", "https://youtube.com/embed/dQw4w9WgXcQ")), "YouTube links recognised")
ok(youtube_id("https://example.com/watch?v=dQw4w9WgXcQ") is None and youtube_id("https://youtu.be/<script>") is None,
   "other sites / bad ids aren't embedded")
ok(clean_link("example.com/a") == "https://example.com/a" and clean_link("javascript:alert(1)") is None
   and clean_link("ftp://x.y") is None, "links must be http(s)")
ok(when("2000-01-01 00:00:00").endswith("PM") or when("2000-01-01 00:00:00").endswith("AM"), "old dates show a date and time")

MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 200_000
ok(videos.sniff(MP4) == "mp4" and videos.sniff(b"\x00\x00\x00\x14ftypqt  ") == "mov"
   and videos.sniff(b"\x1a\x45\xdf\xa3....") == "webm" and videos.sniff(b"hello world!!!!!") is None, "video types sniffed from bytes")
ok(photos.cap_bytes("MAX_PHOTO_MB") is None, "no photo size cap by default")
os.environ["MAX_VIDEO_MB"] = "0"
big = videos.save(MP4)
ok(videos.path(big) is not None and videos.path(big).stat().st_size == len(MP4), "video streamed to disk whole")
os.environ["MAX_PHOTO_MB"] = "1"
png = b"\x89PNG\r\n\x1a\n" + b"\x00" * (1024 * 1024 + 10)
try:
    photos.save(png)
    ok(False, "a cap set in .env is enforced")
except photos.PhotoError:
    left = list((db.DB_PATH.parent / "photos").glob("*.png"))
    ok(not left, "a cap set in .env is enforced, leaving no partial file")
del os.environ["MAX_PHOTO_MB"]


# ---- Over HTTP ----
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
dbfile = os.path.join(tempfile.mkdtemp(), "share.db")
env = dict(os.environ, HOUSEHOLD_PASSWORD="changeme", SESSION_SECRET="share-test-secret")
env.pop("HOUSEHOLD_DB_PATH")
server = subprocess.Popen([sys.executable, str(HERE / "fake_gmail.py"), dbfile, str(port)], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
b = f"http://127.0.0.1:{port}"


def login(username=None, password="changeme"):
    s = requests.Session()
    data = {"password": password} | ({"username": username} if username else {})
    return s, s.post(b + "/login", data=data, allow_redirects=False)


def badge(s):
    m = re.search(r'title="(\d+) new"', s.get(b + "/list").text)
    return int(m.group(1)) if m else 0


try:
    for _ in range(60):
        try:
            requests.get(b + "/login", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.25)

    t = requests.get(b + "/login").text
    ok('value="alex"' in t and 'value="sam"' in t and 'value="household"' in t, "login page offers each person + Household")
    ok(login("alex", "wrong")[1].status_code == 401, "wrong personal password refused")
    ok(login("nobody")[1].status_code == 401, "unknown name refused")
    ok(login("sam", "")[1].status_code in (401, 422), "empty password refused")
    alex, r = login("alex")
    ok(r.status_code == 303, "Alex signs in")
    sam, _ = login("Sam")
    house, r = login()
    ok(r.status_code == 303, "password-only login is the household login (used by deploy health checks)")
    house2, r = login("household")
    ok(r.status_code == 303, "picking Household works too")

    ok(alex.get(b + "/share").status_code == 200 and "What's on your mind, Alex?" in alex.get(b + "/share").text,
       "Alex sees the composer")
    ht = house.get(b + "/share").text
    ok("wall-composer" not in ht and "household login" in ht, "household sees the wall without a composer")
    ok("Signed in as Alex" in alex.get(b + "/settings").text and "Signed in as Household" in house.get(b + "/settings").text,
       "Settings says who's signed in")

    # Posting
    r = alex.post(b + "/share/posts", data={"body": "Paint the hallway green?"}, allow_redirects=False)
    ok(r.status_code == 303 and "#post-" in r.headers["location"], "text post")
    ok(house.post(b + "/share/posts", data={"body": "x"}).status_code == 403, "household can't post")
    ok(badge(sam) == 1 and badge(alex) == 0, "badge counts only the other person's posts")
    ok("Paint the hallway green?" in sam.get(b + "/share").text and badge(sam) == 0, "opening Sharing clears your badge")
    post_id = int(re.search(r'id="post-(\d+)"', alex.get(b + "/share").text).group(1))

    # Comments
    r = sam.post(b + f"/share/posts/{post_id}/comments", data={"body": "Yes! Swatches Saturday", "next": "/share"},
                   allow_redirects=False)
    ok(r.status_code == 303, "Sam comments")
    ok(house.post(b + f"/share/posts/{post_id}/comments", data={"body": "x"}).status_code == 403, "household can't comment")
    ok(badge(alex) == 1, "a comment by the other person shows on your badge")
    page = alex.get(b + "/share").text
    ok("Swatches Saturday" in page and "is-new" in page, "comment shown, marked new")
    cid = int(re.search(r'id="comment-(\d+)"', page).group(1))
    ok(alex.post(b + f"/share/comments/{cid}/delete").status_code == 403, "can't delete someone else's comment")
    ok(sam.post(b + f"/share/posts/{post_id}/delete").status_code == 403, "can't delete someone else's post")
    ok(sam.post(b + f"/share/posts/{post_id}/edit", data={"body": "hacked"}).status_code == 403, "can't edit someone else's post")
    alex.post(b + f"/share/posts/{post_id}/edit", data={"body": "Paint the hallway sage green?"})
    page = alex.get(b + "/share").text
    ok("sage green" in page and "edited" in page, "author can edit")
    sam.post(b + f"/share/comments/{cid}/delete")
    ok("Swatches Saturday" not in alex.get(b + "/share").text, "author can delete their comment")

    # Photo, video, link
    small_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 500  # only the first bytes are checked
    r = sam.post(b + "/share/posts", data={"body": "Sunset"}, files={"media": ("s.png", small_png, "image/png")},
                   allow_redirects=False)
    ok(r.status_code == 303 and "error" not in r.headers["location"], "photo post")
    src = re.search(r'<img src="(/share/media/[^"?]+\.png)"', alex.get(b + "/share").text)
    ok(src and alex.get(b + src.group(1)).content == small_png, "feed shows the full-resolution original")
    ok(src and requests.get(b + src.group(1), allow_redirects=False).status_code == 303, "media needs a login")
    r = alex.post(b + "/share/posts", data={"body": "Dog video"}, files={"media": ("clip.mp4", MP4, "video/mp4")},
                   allow_redirects=False)
    ok(r.status_code == 303 and "error" not in r.headers["location"], "video post")
    vid = re.search(r'<video class="post-media" src="(/share/media/[^"#]+\.mp4)', alex.get(b + "/share").text)
    ok(vid is not None, "video shown in a player")
    rr = alex.get(b + vid.group(1), headers={"Range": "bytes=0-99"}) if vid else None
    ok(rr is not None and rr.status_code == 206 and len(rr.content) == 100, "video answers Range requests (iPhone playback)")
    r = alex.post(b + "/share/posts", data={"body": "nope"}, files={"media": ("x.mp4", b"not really a video at all", "video/mp4")},
                   allow_redirects=False)
    ok("error=" in r.headers["location"] and "nope" not in alex.get(b + "/share").text, "a non-video upload is refused, no post made")
    alex.post(b + "/share/posts", data={"body": "", "link": "https://youtu.be/dQw4w9WgXcQ"})
    alex.post(b + "/share/posts", data={"body": "Recipe", "link": "example.com/soup"})
    page = sam.get(b + "/share").text
    ok("youtube-nocookie.com/embed/dQw4w9WgXcQ" in page and 'href="https://example.com/soup"' in page, "YouTube embeds, other links link")
    r = alex.post(b + "/share/posts", data={"link": "javascript:alert(1)"}, allow_redirects=False)
    ok("error=" in r.headers["location"], "non-web links refused")
    ok(alex.post(b + "/share/posts", data={"body": "  "}, allow_redirects=False).status_code == 303
       and alex.get(b + "/share").text.count('class="card post') == 5, "an empty post is ignored")

    # Deleting a post removes its file
    vpid = int(re.findall(r'id="post-(\d+)"', alex.get(b + "/share").text)[2])  # newest first: video is 3rd
    alex.post(b + f"/share/posts/{vpid}/delete")
    ok(vid and alex.get(b + vid.group(1)).status_code == 404, "deleting a post deletes its video")

    # Password change: this device stays in, the other one is signed out
    alex2, _ = login("alex")
    r = alex.post(b + "/settings/password", data={"current": "wrong", "new": "a-long-new-pass", "again": "a-long-new-pass"},
                   allow_redirects=False)
    ok("pw_error=" in r.headers["location"], "password change needs the current password")
    r = alex.post(b + "/settings/password", data={"current": "changeme", "new": "short", "again": "short"}, allow_redirects=False)
    ok("pw_error=" in r.headers["location"], "new password must be long enough")
    r = alex.post(b + "/settings/password", data={"current": "changeme", "new": "a-long-new-pass", "again": "a-long-new-pass"},
                   allow_redirects=False)
    ok("saved=pw" in r.headers["location"], "password changed")
    ok(alex.get(b + "/share", allow_redirects=False).status_code == 200, "the device that changed it stays signed in")
    ok(alex2.get(b + "/share", allow_redirects=False).status_code == 303, "Alex's other devices are signed out")
    ok(sam.get(b + "/share", allow_redirects=False).status_code == 200 and house.get(b + "/", allow_redirects=False).status_code == 200,
       "other people and the household login are unaffected")
    ok(login("alex", "a-long-new-pass")[1].status_code == 303, "new password works")
    ok(house.post(b + "/settings/password", data={"current": "changeme", "new": "a-long-new-pass", "again": "a-long-new-pass"},
                  allow_redirects=False).headers["location"] == "/settings", "household login has no password to change here")

    # Likes and emoji reactions
    pid = int(re.findall(r'id="post-(\d+)"', sam.get(b + "/share").text)[0])
    r = sam.post(b + f"/share/posts/{pid}/react", data={"emoji": "👍", "next": "/share"}, allow_redirects=False)
    ok(r.status_code == 303 and f"#post-{pid}" in r.headers["location"], "like (plain form)")
    page = alex.get(b + "/share").text
    ok("Sam likes this" in page, "others see who liked it")
    ok("You like this" in sam.get(b + "/share").text, "you see 'You like this'")
    r = alex.post(b + f"/share/posts/{pid}/react", data={"emoji": "👍", "next": "/share"}, headers={"X-Fetch": "1"})
    ok(r.status_code == 200 and "You and Sam like this" in r.text and 'id="rx-' in r.text and "<html" not in r.text,
       "like from share.js answers with just the reaction row")
    alex.post(b + f"/share/posts/{pid}/react", data={"emoji": "❤️"})
    page = sam.get(b + "/share").text
    ok("Alex and You like this" not in page and "You and Alex like this" in page and "❤️</span> Alex" in page,
       "emoji reaction shows who")
    alex.post(b + f"/share/posts/{pid}/react", data={"emoji": "❤️"})
    ok("❤️</span> Alex" not in sam.get(b + "/share").text, "tapping again takes it back")
    ok(alex.post(b + f"/share/posts/{pid}/react", data={"emoji": "💩"}).status_code == 400, "only the offered emoji")
    ok(house.post(b + f"/share/posts/{pid}/react", data={"emoji": "👍"}).status_code == 403, "household can't react")
    ok("rx-bar" not in house.get(b + "/share").text, "household sees no Like/React buttons")

    # Profile pictures
    r = sam.post(b + "/settings/avatar", files={"avatar": ("me.png", small_png, "image/png"),
                                                 "avatar_thumb": ("t.jpg", b"\xff\xd8\xff" + b"\x00" * 50, "image/jpeg")},
                   allow_redirects=False)
    ok("saved=1" in r.headers["location"], "profile picture uploaded")
    pic = re.search(r'<img class="avatar " src="(/share/media/[^"]+)"', alex.get(b + "/share").text)
    ok(pic and alex.get(b + pic.group(1)).headers["content-type"] == "image/jpeg", "shows on their posts, as the square thumbnail")
    r = sam.post(b + "/settings/avatar", files={"avatar": ("x.txt", b"hello there, not a photo", "text/plain")},
                   allow_redirects=False)
    ok("error=" in r.headers["location"], "non-photo refused")
    sam.post(b + "/settings/avatar/delete")
    ok(pic and alex.get(b + pic.group(1).split("?")[0]).status_code == 404 and '<img class="avatar' not in alex.get(b + "/share").text,
       "removing it deletes the file and goes back to the letter")
    ok(house.post(b + "/settings/avatar", files={"avatar": ("me.png", small_png, "image/png")}, allow_redirects=False)
       .status_code == 303, "household has no picture to set (ignored)")

    # Temporary password (add_user.py --temp): must choose one before anything else
    import sqlite3
    from app.core import auth
    con = sqlite3.connect(dbfile)
    con.execute("INSERT INTO users (username, display_name, pw_hash, must_change) VALUES ('carol', 'Carol', ?, 1)",
                (auth.hash_password("changeme"),))
    con.commit()
    con.close()
    carol, r = login("carol")
    ok(r.status_code == 303, "temporary password signs in")
    r = carol.get(b + "/share", allow_redirects=False)
    ok(r.status_code == 303 and r.headers["location"] == "/password", "every page sends them to choose a password")
    ok(carol.post(b + "/share/posts", data={"body": "x"}, allow_redirects=False).headers.get("location") == "/password",
       "... including posting")
    ok("Choose your own" in carol.get(b + "/password").text, "choose-a-password page shown")
    r = carol.post(b + "/password", data={"new": "changeme", "again": "changeme"}, allow_redirects=False)
    ok("error=" in r.headers["location"], "can't keep the temporary password")
    r = carol.post(b + "/password", data={"new": "carols-own-pass", "again": "carols-own-pass"}, allow_redirects=False)
    ok(r.headers["location"] == "/" and carol.get(b + "/share", allow_redirects=False).status_code == 200,
       "after choosing one, the app opens up")
    ok(carol.get(b + "/password", allow_redirects=False).headers["location"] == "/", "the page isn't shown again")
    ok(login("carol")[1].status_code == 401 and login("carol", "carols-own-pass")[1].status_code == 303,
       "old temporary password stops working, new one works")
    ok(alex.get(b + "/password", allow_redirects=False).headers["location"] == "/", "normal users skip the page")
finally:
    server.terminate()
    err = server.stderr.read() if server.stderr else ""
    ok("Traceback" not in err, "no server errors" + ("" if "Traceback" not in err else ":\n" + err[-2000:]))

print(f"\n{'ALL PASSED' if not FAILED else f'{len(FAILED)} FAILED'}")
sys.exit(1 if FAILED else 0)
