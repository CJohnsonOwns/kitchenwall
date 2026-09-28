#!/usr/bin/env python3
"""Set HOUSEHOLD_PASSWORD and generate a fresh SESSION_SECRET in .env.

The password is read from stdin (never from the command line, so it doesn't
land in shell history). Other .env lines are kept exactly as they are. A copy
of the old file is saved as .env.bak-<date> first.

    python3 deploy/set_secrets.py < password.txt
"""
import secrets
import shutil
import sys
from datetime import datetime
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"


def main() -> None:
    password = sys.stdin.readline().strip()
    if len(password) < 12:
        raise SystemExit("Refusing: password must be at least 12 characters.")
    lines = ENV.read_text(encoding="utf-8").splitlines()
    backup = ENV.with_name(f".env.bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(ENV, backup)
    backup.chmod(0o600)
    new = {"HOUSEHOLD_PASSWORD": password, "SESSION_SECRET": secrets.token_urlsafe(48)}
    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in new:
            out.append(f"{key}={new[key]}")
            seen.add(key)
        else:
            out.append(line)
    out += [f"{k}={v}" for k, v in new.items() if k not in seen]
    ENV.write_text("\n".join(out) + "\n", encoding="utf-8")
    ENV.chmod(0o600)
    print(f"Updated {ENV.name} (old copy: {backup.name}). Restart the service to apply; everyone will need to log in again.")


if __name__ == "__main__":
    main()
