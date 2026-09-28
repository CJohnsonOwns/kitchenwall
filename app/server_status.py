"""What Settings → Server shows. Everything here only reads: service state
from systemd, the journal, the backup folder, an optional deploy record and
whether each .env secret is set (never its value). Every probe tolerates
failure (no systemd on a PC or in Docker) and shows "unknown" instead."""
import json
import os
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from . import __version__, db
from .settings_store import get_setting

HOME = Path.home()
BACKUPS = HOME / "household-dashboard-backups"
# Optional: a deploy tool may leave deployed.json (sha, subject, at) and a
# rollback/ folder here. Without it the page shows the app version instead.
DEPLOY_RECORD = Path(os.environ.get("DEPLOY_RECORD_DIR") or HOME / "claude-bridge")


def _unit_name() -> str:
    """The systemd unit this process runs in, from its cgroup, so the unit can
    be named anything. Falls back to 'kitchenwall'."""
    try:
        for line in Path("/proc/self/cgroup").read_text().splitlines():
            m = re.search(r"/([^/]+)\.service$", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return "kitchenwall"


SERVICE = _unit_name()
PROBLEM = re.compile(r"Traceback|ERROR|WARNING|Exception|Error:|\" 5\d\d ")


def _run(args) -> str | None:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return p.stdout if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _show(unit: str, props: str) -> dict:
    out = _run(["systemctl", "show", unit, "-p", props]) or ""
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _systemd_time(value: str | None) -> datetime | None:
    """'Fri 2026-09-25 23:35:08 UTC' -> datetime (local)."""
    parts = (value or "").split()
    try:
        return datetime.strptime(" ".join(parts[1:3]), "%Y-%m-%d %H:%M:%S")
    except (ValueError, IndexError):
        return None


def _mb(n) -> str:
    try:
        return f"{int(n) / 2**20:.0f} MB" if int(n) >= 2**20 else f"{int(n) / 1024:.0f} KB"
    except (TypeError, ValueError):
        return "unknown"


def _ago(when: datetime | None, now: datetime) -> str:
    if not when:
        return "unknown"
    s = int((now - when).total_seconds())
    if s < 90:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600}h {s % 3600 // 60:02d}m ago"
    return f"{s // 86400} days ago"


def _span(since: datetime | None, now: datetime) -> str:
    if not since:
        return "unknown"
    s = int((now - since).total_seconds())
    d, h, m = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return f"{d}d {h}h" if d else f"{h}h {m:02d}m"


def _nice(when: datetime | None, now: datetime) -> str:
    if not when:
        return "unknown"
    t = when.strftime("%I:%M %p").lstrip("0")
    if when.date() == now.date():
        return f"{t} today"
    return f"{when.strftime('%b')} {when.day}, {t}"


def logs(problems_only: bool = False, lines: int = 150) -> list[dict] | None:
    out = _run(["journalctl", "-u", SERVICE, "-u", SERVICE + "-backup", "--no-pager", "-o", "short-iso",
                "-n", str(2000 if problems_only else lines)])
    if out is None:
        return None
    rows = []
    for line in out.splitlines():
        m = re.match(r"(\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d))\S*\s+\S+\s+[^:]+:\s?(.*)", line)
        if not m:
            continue
        text = m.group(3)
        problem = bool(PROBLEM.search(text))
        if problems_only and not problem:
            continue
        rows.append({"day": m.group(1)[:10], "time": m.group(2), "text": text, "problem": problem})
    return rows[-lines:]


def status() -> dict:
    now = datetime.now()
    svc = _show(SERVICE, "ActiveState,SubState,ActiveEnterTimestamp,NRestarts,MemoryCurrent")
    started = _systemd_time(svc.get("ActiveEnterTimestamp"))
    timer = _show(SERVICE + "-backup.timer", "NextElapseUSecRealtime")
    backups = sorted(BACKUPS.glob("household-*.db")) if BACKUPS.exists() else []
    newest = datetime.fromtimestamp(backups[-1].stat().st_mtime) if backups else None
    try:
        deployed = json.loads((DEPLOY_RECORD / "deployed.json").read_text())
    except (OSError, ValueError):
        deployed = {}
    try:
        deployed_at = datetime.strptime(deployed.get("at", ""), "%Y%m%d-%H%M%S")
    except ValueError:
        deployed_at = None
    rollbacks = len([p for p in (DEPLOY_RECORD / "rollback").iterdir() if p.is_dir()]) if (DEPLOY_RECORD / "rollback").exists() else 0
    syncs = [a["last_synced_at"] for a in db.list_email_accounts() if a["last_synced_at"]]
    try:
        last_sync = datetime.fromisoformat(max(syncs)) if syncs else None
    except ValueError:
        last_sync = None
    problems = logs(problems_only=True, lines=50) or []
    recent = [r for r in problems if (now - datetime.fromisoformat(r["day"] + "T" + r["time"])).total_seconds() < 86400]
    disk = shutil.disk_usage(db.DB_PATH.parent)
    minutes = get_setting("mail_sync_minutes")
    pw = os.environ.get("HOUSEHOLD_PASSWORD", "")
    state = svc.get("ActiveState")
    return {
        "checked": now.strftime("%I:%M:%S %p").lstrip("0"),
        "systemd": bool(svc),
        "state": state or "unknown",
        "substate": svc.get("SubState", ""),
        "running": state == "active",
        "started": _nice(started, now),
        "uptime": _span(started, now),
        "restarts": svc.get("NRestarts", "unknown"),
        "memory": _mb(svc.get("MemoryCurrent")) if (svc.get("MemoryCurrent") or "").isdigit() else "unknown",
        "db_size": _mb(db.DB_PATH.stat().st_size) if db.DB_PATH.exists() else "unknown",
        "python": platform.python_version(),
        "version": (deployed.get("sha") or "")[:7] or __version__,
        "has_deploy_record": bool(deployed),
        "version_subject": deployed.get("subject") or "",
        "deployed": _nice(deployed_at, now),
        "rollbacks": rollbacks,
        "backups": len(backups),
        "newest_backup": backups[-1].name if backups else "none yet",
        "newest_backup_when": _nice(newest, now),
        "backup_fresh": bool(newest and (now - newest).total_seconds() < 36 * 3600),
        "next_backup": _nice(_systemd_time(timer.get("NextElapseUSecRealtime")), now),
        "mail_every": "only on Refresh" if minutes == "0" else f"every {minutes} min",
        "last_sync": _ago(last_sync, now) if syncs else "no accounts",
        "errors_24h": len(recent),
        "disk_free": f"{disk.free // 2**30} GB",
        "secrets": [
            ("Household password", bool(pw) and pw != "changeme", "set" if pw and pw != "changeme" else ("default “changeme”" if pw else "not set")),
            ("Session secret", bool(os.environ.get("SESSION_SECRET")), None),
            ("Mail encryption key", bool(os.environ.get("EMAIL_ENC_KEY")), None),
            ("Google sign-in", bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET")), None),
        ],
    }
