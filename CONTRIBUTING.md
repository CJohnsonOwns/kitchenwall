# Contributing

Thanks for wanting to help! Kitchenwall is a small hobby project, so please
keep changes small and in the spirit of the app.

## Ground rules
- **Stack stays simple:** FastAPI, Jinja2, plain `sqlite3` and vanilla JS (ES
  modules are fine). No Node, no build step, no new frameworks.
- **Small files, one job each.** `tests/test_structure.py` fails any app file
  over 450 lines: split it rather than grow it.
- **Security:** no inline `<script>` or `on*=` handlers (the CSP is
  `script-src 'self'`); state changes only via POST/PUT/PATCH/DELETE; SQL only
  with `?` placeholders; every new route needs a login.
- **Design choices that are on purpose:** no money tracking, and no
  scorekeeping between people (no read receipts, "done by", streaks or
  per-person stats). PRs adding those won't be merged.

## Running it locally
```
python -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt   # Windows: .venv\Scripts\...
python tests/fake_gmail.py /tmp/demo.db     # demo copy with fake mail at http://127.0.0.1:8010
```
Sign in as Alex, Sam or Household, password `changeme`.

## Tests
```
python tests/run_all.py
```
Runs everything against a fake Gmail and a throwaway database, including
headless-browser UI checks (`playwright`, Edge or Chromium). Please make sure
it passes before opening a PR.
