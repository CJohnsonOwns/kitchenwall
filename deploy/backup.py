#!/usr/bin/env python3
"""Nightly backup of the dashboard database, photos and Sharing videos.

Uses SQLite's online backup API, so it's safe while the app is running.
Keeps the last 30 daily copies in ~/household-dashboard-backups (outside the
app folder, so a redeploy can never touch them). The .env file is NOT copied:
keep one copy of it somewhere else, since connected email accounts can't be
decrypted without its EMAIL_ENC_KEY.

Run by household-dashboard-backup.timer, or by hand:  python3 deploy/backup.py
"""
import json
import shutil
import sqlite3
from datetime import date
from pathlib import Path

APP = Path(__file__).resolve().parent.parent
SRC = APP / "data" / "household.db"
DEST_DIR = Path.home() / "household-dashboard-backups"
KEEP = 30


def main() -> None:
    DEST_DIR.mkdir(mode=0o700, exist_ok=True)
    dest = DEST_DIR / f"household-{date.today().isoformat()}.db"
    src = sqlite3.connect(f"file:{SRC}?mode=ro", uri=True)
    out = sqlite3.connect(dest)
    try:
        src.backup(out)
    finally:
        out.close()
        src.close()
    dest.chmod(0o600)
    # Sanity check the copy before pruning older ones.
    check = sqlite3.connect(dest).execute("PRAGMA integrity_check").fetchone()[0]
    if check != "ok":
        raise SystemExit(f"backup {dest} failed integrity check: {check}")
    for old in sorted(DEST_DIR.glob("household-*.db"))[:-KEEP]:
        old.unlink()
    print(f"backed up to {dest}")
    backup_photos()
    backup_videos()


def backup_photos() -> None:
    mirror("photos", ("", "thumb"))


def backup_videos() -> None:
    mirror("videos", ("",))


def mirror(folder: str, subs: tuple) -> None:
    """Mirror data/<folder> into DEST_DIR/<folder>. Names are random and never
    reused, so only new files need copying. A file deleted from the app is
    kept here for KEEP more days (like the database copies), then removed."""
    src, dest = APP / "data" / folder, DEST_DIR / folder
    if not src.is_dir():
        return
    for sub in subs:
        (dest / sub).mkdir(parents=True, exist_ok=True)
    dest.chmod(0o700)
    copied = 0
    for sub in subs:
        if not (src / sub).is_dir():
            continue
        for f in (src / sub).iterdir():
            if f.is_file() and not (dest / sub / f.name).exists():
                shutil.copy2(f, dest / sub / f.name)
                (dest / sub / f.name).chmod(0o600)
                copied += 1
    # Remember when each deleted photo was first missing; drop it KEEP days later.
    gone_file = dest / "gone.json"
    try:
        gone = json.loads(gone_file.read_text())
    except (OSError, ValueError):
        gone = {}
    today = date.today()
    for sub in subs:
        for f in (dest / sub).iterdir():
            key = f"{sub}/{f.name}"
            if not f.is_file() or f.name == "gone.json":
                continue
            if (src / sub / f.name).exists():
                gone.pop(key, None)
            elif key not in gone:
                gone[key] = today.isoformat()
            elif (today - date.fromisoformat(gone[key])).days >= KEEP:
                f.unlink()
                del gone[key]
    gone_file.write_text(json.dumps(gone))
    print(f"{folder}: {copied} new file(s) copied to {dest}")


if __name__ == "__main__":
    main()
