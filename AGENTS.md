# Notes for AI coding agents

## If you were asked to install Kitchenwall
Goal: Kitchenwall running in Docker on this machine, reachable on the home
network. Work in the user's home directory unless they say otherwise.

1. Check `docker compose version` and `docker info`. If Docker is missing or
   not usable, tell the user how to install it for their OS
   (https://docs.docker.com/engine/install/) and ask before installing system
   packages or using sudo yourself.
2. Ask the user (don't invent these):
   - a shared **household password**, 12+ characters, no `'`
     (used by the wall screen; it will appear in this session's history, so
     suggest they change it in `.env` later if that matters to them);
   - the **first names** of the people who live there (or none);
   - confirm the **time zone** and **port** (default: this machine's zone, 8000).
3. Run the installer without prompts:
   ```sh
   git clone --depth 1 https://github.com/CJohnsonOwns/kitchenwall.git && cd kitchenwall
   KW_PASSWORD='...' KW_PEOPLE='Alex Sam' KW_TZ='Europe/Berlin' KW_PORT=8000 ./install.sh
   ```
   Use `KW_PEOPLE=-` for nobody. Prefix with `sudo -E` only if Docker needs it.
4. Give the user the address and the one-time passwords the installer prints,
   exactly as printed. Then point them to the README sections "Settings" and
   "Connecting Gmail". Don't set up Gmail yourself: it needs their Google login
   in a browser.
5. Don't open firewall ports or expose it to the internet. If they want access
   away from home, point them to the README section "Reaching it from outside
   your home".

Updating later: run `./install.sh` again in the same folder.

## If you're changing the code
Read `CONTRIBUTING.md` first. Short version: FastAPI + Jinja2 + `sqlite3` +
vanilla JS, no build step, no new frameworks; no inline scripts (CSP
`script-src 'self'`); state changes never via GET; `?` placeholders only;
every route needs a login; app files stay under 450 lines. Run
`python tests/run_all.py` before you finish; it must pass.
