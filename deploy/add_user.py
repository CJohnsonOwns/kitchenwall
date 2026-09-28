#!/usr/bin/env python3
"""Create a personal login, or reset someone's forgotten password.

Run from the app folder with the app's Python. The password is asked for
(hidden) or read from stdin, never taken from the command line, so it
doesn't land in shell history:

    .venv/bin/python deploy/add_user.py sam Sam

--temp makes it a temporary password (any length, e.g. piped in with printf):
that person has to choose their own right after they first sign in.

    printf 'changeme\n' | .venv/bin/python deploy/add_user.py --temp sam Sam

Resetting a password signs that person out on all their devices. Everyone
can change their own password later in Settings.
"""
import getpass
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import auth  # noqa: E402
from app import db


def main() -> None:
    args = sys.argv[1:]
    temp = "--temp" in args
    args = [a for a in args if a != "--temp"]
    if len(args) != 2:
        raise SystemExit("usage: add_user.py [--temp] <username> <Display Name>")
    username, display = args[0].strip().lower(), args[1].strip()
    if not re.fullmatch(r"[a-z0-9_-]{1,30}", username) or username == "household":
        raise SystemExit("Refusing: username must be letters/numbers (and not 'household').")
    if not display or len(display) > 40:
        raise SystemExit("Refusing: display name must be 1-40 characters.")
    if sys.stdin.isatty():
        password = getpass.getpass(f"Password for {display}: ")
        if getpass.getpass("Again: ") != password:
            raise SystemExit("Refusing: the two passwords didn't match.")
    else:
        password = sys.stdin.readline().rstrip("\r\n")
    if not password:
        raise SystemExit("Refusing: empty password.")
    if len(password) < auth.MIN_PASSWORD and not temp:
        raise SystemExit(f"Refusing: password must be at least {auth.MIN_PASSWORD} characters.")
    db.init_db()
    created = db.upsert_user(username, display, auth.hash_password(password), must_change=temp)
    note = "; they choose their own password when they first sign in" if temp else ""
    print(f"{'Created' if created else 'Updated'} {display} (sign in as '{display}' on the login page{note}).")


if __name__ == "__main__":
    main()
