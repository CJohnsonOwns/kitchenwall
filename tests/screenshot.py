"""Screenshots of the fake-Gmail copy of the app, for checking UI changes.

    python tests/screenshot.py [/path ...] [--phone] [--out DIR] [--user alex|sam|household]

Starts tests/fake_gmail.py on a throwaway DB and a free port, signs in, and
saves a full-page PNG per path (default: every main page) at desktop size,
plus phone size with --phone. Uses headless Edge with a fresh temporary
profile: never your browser profile, cookies or accounts, and never the live app.
Needs the dev extra: pip install -r requirements-dev.txt
"""
import argparse
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ["/", "/list", "/calendar", "/board", "/inbox", "/share", "/settings", "/settings/server"]
SIZES = {"desktop": (1440, 900), "phone": (390, 844)}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=DEFAULT)
    ap.add_argument("--phone", action="store_true", help="also capture at phone size")
    ap.add_argument("--out", default=tempfile.mkdtemp(prefix="shots-"))
    ap.add_argument("--user", default="alex", help="sign in as alex, sam or household")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.mkdtemp()
    port = free_port()
    server = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_gmail.py"), str(Path(tmp) / "shots.db"), str(port)],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=dict(os.environ, SEED_LIST="1"))
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except OSError:
                if server.poll() is not None:
                    sys.exit("fake server died:\n" + server.stderr.read().decode())
                time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            for size in ["desktop"] + (["phone"] if args.phone else []):
                w, h = SIZES[size]
                ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=size == "phone",
                                          has_touch=size == "phone", device_scale_factor=1)
                page = ctx.new_page()
                page.goto(base + "/login")
                if "/login" in args.paths:
                    page.screenshot(path=str(out / f"login-{size}.png"), full_page=True)
                    print(out / f"login-{size}.png")
                page.check(f"input[name=username][value={args.user}]", force=True)
                page.fill("input[name=password]", "changeme")
                page.press("input[name=password]", "Enter")
                page.wait_for_url(base + "/")
                for path in [p for p in args.paths if p != "/login"]:
                    page.goto(base + path)
                    page.wait_for_load_state("networkidle")
                    name = (path.strip("/").replace("/", "_").replace("?", "_") or "home") + f"-{size}.png"
                    page.screenshot(path=str(out / name), full_page=True)
                    print(out / name)
                ctx.close()
            browser.close()
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
