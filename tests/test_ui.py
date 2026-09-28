"""Click-through checks of the JavaScript, in headless Edge on the fake-Gmail copy.

PC only (needs playwright from requirements-dev.txt); skipped if it isn't
installed. Every page visited must also finish without a JavaScript error.
Covers the parts with real behaviour: inbox (list, reading pane, shortcuts,
composer, autocomplete), whiteboard, shopping list, and the confirm/auto-submit
helpers in app.js.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("SKIP playwright not installed (pip install -r requirements-dev.txt)")
    sys.exit(0)

ROOT = Path(__file__).resolve().parents[1]
FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


port = free_port()
server = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_gmail.py"), str(Path(tempfile.mkdtemp()) / "ui.db"), str(port)],
                          cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=dict(os.environ, SEED_LIST="1"))
base = f"http://127.0.0.1:{port}"
try:
    for _ in range(60):
        try:
            urllib.request.urlopen(base + "/login", timeout=1)
            break
        except OSError:
            time.sleep(0.5)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
        # Remote images in email are blocked on purpose (tracking pixels): not an error.
        page.on("console", lambda m: errors.append(f"{page.url}: {m.text}")
                if m.type == "error" and "Loading the image 'http" not in m.text else None)

        page.goto(base + "/login")
        page.check("input[name=username][value=alex]", force=True)
        page.fill("input[name=password]", "changeme")
        page.press("input[name=password]", "Enter")
        page.wait_for_url(base + "/")

        # ---- Inbox (wide: reading pane)
        page.goto(base + "/inbox")
        page.wait_for_load_state("networkidle")
        ok(page.locator(".mail-item.kb-focus").count() == 1, "inbox: first row gets keyboard focus on load")
        page.locator(".mail-item a.mail-row").first.click()
        page.wait_for_selector("#reading-pane #thread", timeout=5000)
        ok("open=" in page.url, "inbox: row opens in the reading pane and the URL remembers it")
        page.keyboard.press("r")
        page.wait_for_timeout(400)
        ok(page.evaluate("document.activeElement && document.activeElement.name") == "body", "inbox: r opens reply with the cursor in the body")
        page.keyboard.press("Escape")
        page.locator(".mail-item .star-btn").first.click()
        page.wait_for_selector("#toast.show", timeout=5000)
        ok(page.locator("#toast-text").inner_text() in ("Starred", "Unstarred"), "inbox: star shows a toast")
        page.locator("label:has(#select-all)").click()
        ok(page.locator("#bulk-actions").is_visible(), "inbox: select all shows the bulk bar")
        page.locator("label:has(#select-all)").click()
        page.keyboard.press("Escape")  # leave the checkbox, so shortcuts apply
        page.keyboard.press("c")
        ok(page.locator("#compose[open]").count() == 1, "inbox: c opens New message")
        page.locator("#compose input[name=to_address]").type("mo")
        page.wait_for_timeout(500)
        ok(page.locator("#compose .ac-list:not([hidden]) li").count() > 0, "inbox: address autocomplete suggests contacts")
        page.keyboard.press("Escape")

        # ---- Conversation, full page
        page.goto(base + "/inbox/m/1/m1")
        page.wait_for_load_state("networkidle")
        ok(page.locator("#thread .msg").count() >= 1, "thread page renders messages")
        h = page.evaluate("Math.max(...[...document.querySelectorAll('.message-body-frame')].map(f => f.offsetHeight), 0)")
        ok(h == 0 or h > 80, "thread: email frames are sized to their content")

        # ---- Whiteboard
        page.goto(base + "/whiteboard")
        page.wait_for_load_state("networkidle")
        ok(page.locator(".sticky-note").count() > 0, "whiteboard renders notes")
        note = page.locator(".sticky-note").first
        box_ = note.bounding_box()
        with page.expect_request(lambda r: "/position" in r.url and r.method == "PATCH", timeout=5000) as req:
            page.mouse.move(box_["x"] + box_["width"] / 2, box_["y"] + box_["height"] / 2)
            page.mouse.down()
            page.mouse.move(box_["x"] + box_["width"] / 2 + 60, box_["y"] + box_["height"] / 2 + 40, steps=5)
            page.mouse.up()
        ok(req.value is not None, "whiteboard: dragging a note saves its position")
        before = page.locator("#zoom-reset").inner_text()
        page.locator("#zoom-in").click()
        ok(page.locator("#zoom-reset").inner_text() != before, "whiteboard: zoom in changes the zoom level")
        page.locator(".sticky-note .sticky-tag-btn").first.click(force=True)
        ok(page.locator(".cat-popover").count() == 1, "whiteboard: tag button opens the category popover")
        page.keyboard.press("Escape")
        page.locator("#mode-draw").click()
        ok("drawing" in (page.locator("#board").get_attribute("class") or ""), "whiteboard: Draw mode switches on")

        # ---- Shopping list: add an item, it appears without a reload
        page.goto(base + "/list")
        page.wait_for_load_state("networkidle")
        box = page.locator("input[name=text]").first
        box.fill("ui-test milk")
        box.press("Enter")
        page.wait_for_timeout(800)
        ok(page.get_by_text("ui-test milk").count() > 0, "list: adding an item shows it")

        # ---- app.js helpers: data-confirm cancels when declined
        page.goto(base + "/calendar")
        page.wait_for_load_state("networkidle")
        forms = page.locator("form[data-confirm]")
        if forms.count():
            page.once("dialog", lambda d: d.dismiss())
            before = page.url
            forms.first.locator("button").first.click(force=True)
            page.wait_for_timeout(500)
            ok(page.url == before, "data-confirm: declining keeps you on the page")

        for path in ["/", "/share", "/settings", "/settings/server", "/inbox/accounts"]:
            page.goto(base + path)
            page.wait_for_load_state("networkidle")

        ok(not errors, "no JavaScript errors" + (": " + " | ".join(errors[:5]) if errors else ""))
        browser.close()
finally:
    server.terminate()

print(f"\n{'FAILED: ' + str(len(FAILED)) if FAILED else 'all passed'}")
sys.exit(1 if FAILED else 0)
