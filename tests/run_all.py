"""Run every test:  python tests/run_all.py   (exit code 0 = all passed)"""
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
results = {}
for name in ("test_backends.py", "test_sending.py", "test_smoke.py", "test_sharing.py", "test_bridge.py", "test_migrations.py", "test_backup.py",
             "test_structure.py", "test_security.py", "test_efficiency.py", "test_ui.py"):
    if not (HERE / name).exists():  # the deploy-bridge test isn't in every copy
        continue
    print(f"\n===== {name} =====", flush=True)
    results[name] = subprocess.run([sys.executable, str(HERE / name)], cwd=HERE.parent).returncode
print("\n" + "\n".join(f"{'ok  ' if rc == 0 else 'FAIL'} {n}" for n, rc in results.items()))
sys.exit(0 if all(rc == 0 for rc in results.values()) else 1)
