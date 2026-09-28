"""deploy/backup.py's photo mirror against temp folders: new photos are copied,
a photo deleted from the app is kept for KEEP days and then dropped."""
import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "deploy"))
import backup  # noqa: E402

FAILED = []


def ok(cond, label):
    print(("PASS " if cond else "FAIL ") + label)
    if not cond:
        FAILED.append(label)


tmp = Path(tempfile.mkdtemp())
backup.APP, backup.DEST_DIR = tmp / "app", tmp / "backups"
src = tmp / "app" / "data" / "photos"
(src / "thumb").mkdir(parents=True)
(src / "a.jpg").write_bytes(b"A")
(src / "thumb" / "a.jpg").write_bytes(b"a")
backup.DEST_DIR.mkdir()
dest = backup.DEST_DIR / "photos"

backup.backup_photos()
ok((dest / "a.jpg").read_bytes() == b"A" and (dest / "thumb" / "a.jpg").read_bytes() == b"a", "new photos are copied")

(src / "a.jpg").unlink()
(src / "thumb" / "a.jpg").unlink()
backup.backup_photos()
ok((dest / "a.jpg").exists(), "a photo deleted from the app is still kept")
gone = json.loads((dest / "gone.json").read_text())
gone = {k: (date.today() - timedelta(days=backup.KEEP)).isoformat() for k in gone}
(dest / "gone.json").write_text(json.dumps(gone))
backup.backup_photos()
ok(not (dest / "a.jpg").exists() and not (dest / "thumb" / "a.jpg").exists(), f"...and dropped after {backup.KEEP} days")

sys.exit(1 if FAILED else 0)
