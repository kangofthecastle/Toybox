"""Helper: launch a .pyw toy in smoke mode (auto-close) and report its exit.

Sets TOYBOX_SMOKE=<ms> so the toy builds its real UI, runs briefly, then
destroys itself and exits 0. Run via console python so we capture stderr.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_smoke(script_name, timeout_ms=1500):
    env = dict(os.environ)
    env["TOYBOX_SMOKE"] = str(timeout_ms)
    proc = subprocess.run(
        [sys.executable, os.path.join(ROOT, script_name)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=(timeout_ms / 1000.0) + 15,
    )
    return proc.returncode, (proc.stderr or "")
