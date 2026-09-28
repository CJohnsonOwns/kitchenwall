"""Computed-style fingerprint of every page, for proving a CSS/JS refactor changed nothing.

    python tests/style_snapshot.py OUT.json            # record
    python tests/style_snapshot.py OUT.json --diff OLD.json

Starts the fake-Gmail copy (like screenshot.py), visits each page at desktop and
phone size, and stores for every element its tag path and a digest of all its
computed style properties, plus any JavaScript errors. --diff lists elements
whose style changed and any new JS errors. PC only (needs playwright).
"""
import argparse
import json
import re
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
PAGES = ["/", "/list", "/calendar", "/board", "/inbox", "/inbox/m/1/m1", "/inbox/accounts", "/share",
         "/settings", "/settings/server", "/password", "/calendar/1/edit", "/whiteboard"]
SIZES = {"desktop": (1440, 900), "phone": (390, 844)}
# Values that depend on text that changes minute to minute (clock, "5 minutes ago").
SKIP = {"width", "inline-size", "block-size", "height", "min-width", "perspective-origin", "transform-origin",
        "grid-template-columns", "grid-template-rows"}

JS = """(skip) => {
  const out = [];
  const walk = (el, path) => {
    const cs = getComputedStyle(el);
    let s = '';
    for (let i = 0; i < cs.length; i++) { const p = cs[i]; if (!skip.includes(p)) s += p + ':' + cs.getPropertyValue(p) + ';'; }
    out.push([path, s]);
    let i = 0;
    for (const c of el.children) walk(c, path + '>' + c.tagName.toLowerCase() + (c.className && typeof c.className === 'string' ? '.' + c.className.trim().split(/\\s+/).join('.') : '') + '#' + (i++));
  };
  walk(document.documentElement, 'html');
  return out;
}"""


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def record(out_file: Path):
    tmp = tempfile.mkdtemp()
    port = free_port()
    server = subprocess.Popen([sys.executable, str(ROOT / "tests" / "fake_gmail.py"), str(Path(tmp) / "s.db"), str(port)],
                              cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, env=dict(os.environ, SEED_LIST="1"))
    base = f"http://127.0.0.1:{port}"
    result = {}
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(base + "/login", timeout=1)
                break
            except OSError:
                time.sleep(0.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge", headless=True)
            for size, (w, h) in SIZES.items():
                ctx = browser.new_context(viewport={"width": w, "height": h}, is_mobile=size == "phone",
                                          has_touch=size == "phone", device_scale_factor=1)
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
                page.goto(base + "/login")
                page.wait_for_timeout(1200)  # let the fade-in finish
                result[f"{size} /login"] = {"styles": dict(page.evaluate(JS, sorted(SKIP))), "errors": list(errors)}
                page.check("input[name=username][value=alex]", force=True)
                page.fill("input[name=password]", "changeme")
                page.press("input[name=password]", "Enter")
                page.wait_for_url(base + "/")
                for path in PAGES:
                    errors.clear()
                    page.goto(base + path)
                    page.wait_for_load_state("networkidle")
                    styles = dict(page.evaluate(JS, sorted(SKIP)))
                    result[f"{size} {path}"] = {"styles": styles, "errors": list(errors)}
                ctx.close()
            browser.close()
    finally:
        server.terminate()
    out_file.write_text(json.dumps(result, indent=0), encoding="utf-8")
    print(f"recorded {len(result)} pages -> {out_file}")
    return result


def _props(s: str) -> dict:
    """Style string -> {property: value}, numbers rounded to 1px so sub-pixel
    layout jitter between runs doesn't count (custom properties come in any order)."""
    return {k: re.sub(r"\d+\.\d+", lambda m: f"{float(m.group()):.0f}", v)
            for k, v in (x.split(":", 1) for x in s.split(";") if ":" in x) if k not in SKIP}


def diff(new: dict, old: dict) -> int:
    problems = 0
    for key in sorted(set(old) | set(new)):
        o, n = old.get(key), new.get(key)
        if o is None or n is None:
            print(f"{key}: only in {'new' if o is None else 'old'}")
            problems += 1
            continue
        changed = [p for p in n["styles"] if not p.startswith("html>head") and p in o["styles"] and _props(o["styles"][p]) != _props(n["styles"][p])]
        added = [p for p in n["errors"] if p not in o["errors"]]
        if changed:
            problems += 1
            first = changed[0]
            po, pn = _props(o["styles"][first]), _props(n["styles"][first])
            what = {k: (po.get(k), pn.get(k)) for k in set(po) | set(pn) if po.get(k) != pn.get(k)}
            print(f"{key}: {len(changed)} element(s) styled differently, e.g. {first}: {dict(list(what.items())[:4])}")
        if added:
            problems += 1
            print(f"{key}: new JS errors {added[:3]}")
    print("no differences" if not problems else f"{problems} page(s) differ")
    return problems


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--diff")
    a = ap.parse_args()
    res = record(Path(a.out))
    if a.diff:
        sys.exit(1 if diff(res, json.loads(Path(a.diff).read_text(encoding="utf-8"))) else 0)
