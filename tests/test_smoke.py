"""End-to-end smoke test: starts the app with the fake Gmail on a spare port and
checks every page and the main flows over HTTP.

Includes a regression check for the bug where list rows carried
"<built-in method keys ...>" instead of message ids, which made the list and
toolbar buttons silently do nothing."""
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
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
dbfile = os.path.join(tempfile.mkdtemp(), "smoke.db")
env = dict(os.environ, HOUSEHOLD_PASSWORD="changeme", SESSION_SECRET="smoke-test-secret")
server = subprocess.Popen([sys.executable, str(HERE / "fake_gmail.py"), dbfile, str(port)], env=env,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
b = f"http://127.0.0.1:{port}"
try:
    for _ in range(60):
        try:
            requests.get(b + "/login", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.25)
    s = requests.Session()

    r = s.get(b + "/", allow_redirects=False)
    ok(r.status_code == 303 and r.headers["location"] == "/login", "pages need a login")
    ok(s.post(b + "/login", data={"password": "nope"}).status_code == 401, "wrong password refused")
    s.post(b + "/login", data={"password": "changeme"})

    for path in ["/", "/calendar", "/calendar?month=2026-11", "/whiteboard", "/inbox", "/inbox?view=starred",
                 "/inbox?view=sent", "/inbox?view=search&q=roast", "/inbox/accounts", "/settings", "/share",
                 "/inbox/m/1/m1", "/inbox/m/2/m4?pane=1", "/inbox?open=2%3Am4"]:
        r = s.get(b + path)
        ok(r.status_code == 200, f"GET {path}")

    t = s.get(b + "/inbox").text
    keys = re.findall(r'data-keys="([^"]*)"', t)
    ok(bool(keys) and all(re.fullmatch(r"(\d+:[\w-]+)(,\d+:[\w-]+)*", k) for k in keys), "list rows carry real message ids")
    t = s.get(b + "/inbox/m/2/m4").text
    ok(re.search(r'id="thread" data-keys="\d+:', t) is not None, "conversation toolbar carries real message ids")

    r = s.post(b + "/inbox/action", json={"action": "archive", "keys": ["1:m6"]}).json()
    ok(r["ok"] and r["done"] == 1 and 'data-key="1:m6"' not in s.get(b + "/inbox").text, "archive removes it from the inbox")
    s.post(b + "/inbox/action", json=r["undo"])
    ok('data-key="1:m6"' in s.get(b + "/inbox").text, "undo brings it back")
    r = s.post(b + "/inbox/action", json={"action": "archive", "keys": ["junk"]})
    ok(r.status_code == 409 and not r.json()["ok"], "an action that changes nothing reports an error")

    r = s.post(b + "/inbox/send", data={"account_id": 1, "mode": "reply", "ref_uid": "m5", "to_address": "mom@example.com",
                                        "subject": "Re: Sunday dinner?", "body": "Yes!", "next": "/inbox"},
               files=[("files", ("a.txt", b"hi", "text/plain"))], allow_redirects=False)
    sent = s.get(b + "/__test/sent").json()
    ok(r.status_code == 303 and "sent=1" in r.headers["location"] and sent and sent[-1]["uploads"] == [["a.txt", 2]], "send with an attachment")
    r = s.post(b + "/inbox/send", data={"account_id": 1, "body": "x", "next": "/inbox"}, allow_redirects=False)
    ok("error=" in r.headers["location"], "sending with no recipients is refused")
    r = s.post(b + "/inbox/send", data={"account_id": 1, "to_address": "a@b.c", "body": "x", "next": "/\\evil.example"}, allow_redirects=False)
    ok(r.headers["location"].startswith("/inbox"), "redirects can't leave the site")

    ok("data-hd-block" in s.get(b + "/inbox/m/1/m8").text, "remote images blocked until asked for")
    r = s.get(b + "/inbox/att/1/m1/6")
    ok(r.headers.get("content-type") == "application/pdf", "PDF attachment opens inline")
    r = s.get(b + "/inbox/att/1/m1/5")
    ok("sandbox" in r.headers.get("content-security-policy", ""), "other attachments are sandboxed")

    # ---- shopping lists ----
    ok(s.get(b + "/list").status_code == 200, "GET /list")
    lists = s.get(b + "/list/items", params={"l": 1}).json()["lists"]
    L = lists[0]["id"]
    ok(len(lists) == 1 and lists[0]["name"] == "Shopping", "there's a first list called Shopping")
    P = {"l": L}
    st = s.post(b + "/list/items", params=P, json={"text": "  Eggs  "}).json()
    eggs = st["id"]
    ok(st["ok"] and [i["text"] for i in st["items"]] == ["Eggs"], "add a list item (whitespace trimmed)")
    s.post(b + "/list/items", params=P, json={"text": "Basil"})
    st = s.post(b + "/list/items", params=P, json={"text": "eggs"}).json()
    ok(len(st["items"]) == 2, "adding something already on the list doesn't duplicate it")
    ok(s.post(b + "/list/items", params=P, json={"text": "   "}).status_code == 400, "empty item refused")
    ok(s.get(b + "/list/items", params={**P, "since": st["version"]}).json().get("same"), "poll with an unchanged version says so")
    st = s.post(b + f"/list/items/{eggs}", params=P, json={"checked": True}).json()
    ok([i["text"] for i in st["items"] if i["checked"]] == ["Eggs"], "tick moves it to Got it")
    ok(s.get(b + "/list/items", params={**P, "since": "stale"}).json()["items"] == st["items"], "poll with an old version gets the list")
    st = s.post(b + "/list/items", params=P, json={"text": "Eggs"}).json()
    ok(not any(i["checked"] for i in st["items"]), "re-adding a ticked item puts it back on the list")
    st = s.post(b + f"/list/items/{eggs}", params=P, json={"text": "Eggs <b>x12</b>"}).json()
    ok(any(i["text"] == "Eggs <b>x12</b>" for i in st["items"]), "edit an item")
    ok("Eggs &lt;b&gt;x12&lt;/b&gt;" in s.get(b + "/list").text, "item text is escaped on the page")
    ok('id="nav-list-badge"' in s.get(b + "/").text, "List tab shows a count")
    st = s.post(b + f"/list/items/{eggs}/delete", params=P).json()
    ok(st["undo"] == [eggs] and len(st["items"]) == 1, "delete an item")
    st = s.post(b + "/list/restore", params=P, json={"ids": st["undo"]}).json()
    ok(len(st["items"]) == 2, "undo brings it back")
    s.post(b + f"/list/items/{eggs}", params=P, json={"checked": True})
    st = s.post(b + "/list/clear", params=P).json()
    ok(st["undo"] == [eggs] and [i["text"] for i in st["items"]] == ["Basil"], "Clear all removes only ticked items")
    ok(s.post(b + f"/list/items/{eggs}", params=P, json={"checked": False}).status_code == 404, "changing a deleted item says it's gone")

    # separate lists
    r = s.post(b + "/lists", json={"name": "  Costco  "}).json()
    C = r["id"]
    ok(r["ok"], "create a second list")
    ok(s.post(b + "/lists", json={"name": "costco"}).status_code == 409, "duplicate list names refused")
    ok(s.post(b + "/lists", json={"name": " "}).status_code == 400, "a list needs a name")
    st = s.post(b + "/list/items", params={"l": C}, json={"text": "Basil"}).json()
    ok([i["text"] for i in st["items"]] == ["Basil"], "the same item on another list is separate")
    ok([i["text"] for i in s.get(b + "/list/items", params=P).json()["items"]] == ["Basil"], "lists don't mix")
    ok({l["name"]: l["to_get"] for l in st["lists"]} == {"Shopping": 1, "Costco": 1}, "switcher counts per list")
    ok(">2<" in s.get(b + "/").text.split('id="nav-list-badge"')[1][:40], "tab badge counts every list")
    t = s.get(b + "/list", params={"l": C}).text
    ok('aria-current="page"' in t and "Add to Costco" in t, "open a list by id")
    ok("Add to Costco" in s.get(b + "/list").text, "the page remembers the last list opened")
    ok("Add to Shopping" in s.get(b + "/list", params={"l": 99999}).text, "an unknown list falls back to the first")
    st = s.post(b + f"/lists/{C}", json={"name": "Costco run"}).json()
    ok(any(l["name"] == "Costco run" for l in st["lists"]), "rename a list")
    ok(s.post(b + f"/lists/{C}", json={"name": "shopping"}).status_code == 409, "rename can't take another list's name")
    r = s.post(b + f"/lists/{C}/delete").json()
    ok(r["ok"] and r["next"] == L, "delete a list")
    ok(s.get(b + "/list/items", params={"l": C}).json().get("gone"), "a deleted list reports it's gone")
    ok(s.post(b + f"/lists/{L}/delete").status_code == 409, "the last list can't be deleted")

    # ---- server page (no systemd on the PC: it must still render) ----
    for path in ["/settings/server", "/settings/server?log=problems"]:
        ok(s.get(b + path).status_code == 200, f"GET {path}")
    ok('href="/settings/server"' in s.get(b + "/settings").text, "Settings links to the Server page")
    t = s.get(b + "/settings/server").text
    ok("changeme" not in t.replace("default “changeme”", "") and "smoke-test-secret" not in t,"server page never shows secret values")

    r = s.post(b + "/calendar", data={"name": "Smoke item", "due_date": "2026-10-02", "recurring": "weekly"}, allow_redirects=False)
    ok(r.status_code == 303, "add a calendar item")

    # ---- times on calendar items ----
    s.post(b + "/calendar", data={"name": "Eye exam", "due_date": "2031-03-04", "due_time": "15:30"})
    s.post(b + "/calendar", data={"name": "Early run", "due_date": "2031-03-04", "due_time": "09:00"})
    s.post(b + "/calendar", data={"name": "Bins all day", "due_date": "2031-03-04", "due_time": ""})
    s.post(b + "/calendar", data={"name": "Bad time", "due_date": "2031-03-05", "due_time": "25:99"})
    t = s.get(b + "/calendar?month=2031-03").text
    ok("3:30pm</b> Eye exam" in t and "9am</b> Early run" in t, "month grid shows short times")
    ok("Mar 4 · 3:30 PM" in t, "upcoming list shows the time")
    ok(t.index("Bins all day") < t.index("Early run") < t.index("Eye exam"), "all-day items first, then by time")
    ok(re.search(r"Bad time</span>\s*<span class=\"due[^\"]*\">[^<]*Mar 5</span>", t) is not None, "an invalid time is saved as all day")
    ok('"time": "3:30 PM"' in t, "day sheet data carries the time")
    eye_exam = re.search(r'<span class="name">Eye exam.*?/calendar/(\d+)/edit', t, re.S).group(1)
    ok('value="15:30"' in s.get(b + f"/calendar/{eye_exam}/edit").text, "edit page shows the saved time")
    s.post(b + f"/calendar/{eye_exam}/edit", data={"name": "Eye exam", "due_date": "2031-03-04", "due_time": "", "recurring": "none"})
    ok("3:30" not in s.get(b + "/calendar?month=2031-03").text, "clearing the time makes it all day")
    r = s.post(b + "/board/items", data={"text": "Smoke note", "next": "/"}, allow_redirects=False)
    ok(r.status_code == 303 and "Smoke note" in s.get(b + "/").text, "add a whiteboard note")

    # ---- photos on notes ----
    JPEG = b"\xff\xd8\xff\xe0" + b"full-size-photo" * 50
    THUMB = b"\xff\xd8\xff\xe0" + b"small"
    PNG = b"\x89PNG\r\n\x1a\n" + b"another-photo" * 20
    r = s.post(b + "/board/items", data={"text": "Sink leak", "next": "/whiteboard"},
               files={"photo": ("sink.jpg", JPEG, "image/jpeg"), "photo_thumb": ("thumb.jpg", THUMB, "image/jpeg")},
               allow_redirects=False)
    ok(r.status_code == 303 and "photo_error" not in r.headers["location"], "add a note with a photo")
    t = s.get(b + "/whiteboard").text
    m = re.search(r'data-id="(\d+)"(?:(?!sticky-note).)*?Sink leak.*?src="(/board/photos/([^"?]+))\?size=thumb"', t, re.S)
    ok(m is not None, "the note shows the photo's thumbnail")
    note_id, full_url, photo_name = m.group(1), m.group(2), m.group(3)
    r = s.get(b + full_url)
    ok(r.content == JPEG and r.headers["content-type"] == "image/jpeg", "full-size photo is the untouched original")
    ok(r.headers.get("x-content-type-options") == "nosniff" and "sandbox" in r.headers.get("content-security-policy", ""),
       "photos are served locked down")
    ok(s.get(b + full_url, params={"size": "thumb"}).content == THUMB, "thumbnail is the small copy")
    ok(requests.get(b + full_url, allow_redirects=False).status_code == 303, "photos need a login")
    for bad in ["/board/photos/..%2F..%2Fdata%2Fhousehold.db", "/board/photos/nope.jpg", "/board/photos/AAAAAAAAAAAAAAAA.exe"]:
        ok(s.get(b + bad).status_code == 404, f"no file served for {bad}")
    r = s.post(b + f"/board/items/{note_id}/photo", files={"photo": ("p.png", PNG, "image/png")}).json()
    ok(r["ok"] and s.get(b + r["full"]).content == PNG, "replace a note's photo")
    ok(s.get(b + r["thumb"]).content == PNG, "no thumbnail from the browser: the original stands in")
    ok(s.get(b + full_url).status_code == 404, "the replaced photo's files are deleted")
    r2 = s.post(b + f"/board/items/{note_id}/photo", files={"photo": ("x.txt", b"not an image", "text/plain")})
    ok(r2.status_code == 400 and "JPEG" in r2.json()["error"], "non-images refused")
    ok(s.post(b + f"/board/items/{note_id}/photo/delete").json()["ok"] and s.get(b + r["full"]).status_code == 404,
       "remove a photo")
    r = s.post(b + "/board/items", data={"text": "Bad photo note", "next": "/whiteboard"},
               files={"photo": ("x.txt", b"hello", "text/plain")}, allow_redirects=False)
    ok("photo_error=" in r.headers["location"] and "Bad photo note" in s.get(b + "/whiteboard").text,
       "a bad photo still keeps the note and says why")
    r = s.post(b + f"/board/items/{note_id}/photo", files={"photo": ("sink.jpg", JPEG, "image/jpeg")}).json()
    s.post(b + f"/board/items/{note_id}/delete", data={"next": "/whiteboard"})
    ok(s.get(b + r["full"]).status_code == 404, "deleting a note deletes its photo")
    ok(s.post(b + "/board/items/999999/photo", files={"photo": ("sink.jpg", JPEG, "image/jpeg")}).status_code == 404,
       "no photo for a note that doesn't exist")
finally:
    server.terminate()
    try:
        _, err = server.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        _, err = server.communicate()
    tracebacks = [ln for ln in (err or "").splitlines() if "Traceback" in ln]
    ok(not tracebacks, "no server errors")
    if tracebacks:
        print(err[-2000:])

sys.exit(1 if FAILED else 0)
