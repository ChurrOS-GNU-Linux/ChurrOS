"""Retry and actionable diagnostics for transient pacman database sync failures."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from tests import testlib

ROOT = testlib.ROOT
HELPER = ROOT / "scripts/lib/pacman-sync-retry.sh"

FAKE_PACMAN = r'''#!/usr/bin/env bash
count_file="$FAKE_PACMAN_COUNT"
count=0
[[ -f "$count_file" ]] && count=$(cat "$count_file")
count=$((count + 1))
printf '%s\n' "$count" > "$count_file"
if (( count <= ${FAKE_PACMAN_FAILS:-0} )); then
    echo "error: failed to retrieve file 'core.db': Resolving timed out" >&2
    exit "${FAKE_PACMAN_STATUS:-1}"
fi
exit 0
'''


class ContainerUpgradeRetry(unittest.TestCase):
    def test_container_entrypoint_uses_retry_for_database_sync(self):
        entrypoint = (ROOT / "scripts/container-entrypoint.sh").read_text()
        self.assertIn("source /churros/scripts/lib/pacman-sync-retry.sh", entrypoint)
        self.assertIn("pacman_sync_with_retry pacman -Sy", entrypoint)

    def run_retry(self, *, attempts: str, failures: int, status: int = 47):
        tmp = Path(tempfile.mkdtemp(prefix="churros-pacman-retry-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)], check=False)
        bindir = tmp / "bin"
        bindir.mkdir()
        pacman = bindir / "pacman"
        pacman.write_text(FAKE_PACMAN)
        pacman.chmod(0o755)
        count = tmp / "count"
        script = (
            f"source {HELPER}\n"
            "pacman_sync_with_retry pacman -Sy --noconfirm\n"
        )
        env = os.environ.copy()
        env.update({
            "PATH": f"{bindir}:{env.get('PATH', '/usr/bin:/bin')}",
            "FAKE_PACMAN_COUNT": str(count),
            "FAKE_PACMAN_FAILS": str(failures),
            "FAKE_PACMAN_STATUS": str(status),
            "CHURROS_PACMAN_SYNC_ATTEMPTS": attempts,
            "CHURROS_PACMAN_SYNC_RETRY_DELAY": "0",
        })
        result = subprocess.run(["bash", "-c", script], cwd=ROOT, env=env,
                                capture_output=True, text=True, timeout=20)
        calls = int(count.read_text()) if count.exists() else 0
        return result, calls

    def test_retries_transient_dns_failure_and_recovers(self):
        result, calls = self.run_retry(attempts="3", failures=2)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, 3)
        self.assertIn("reintento 2/3", result.stderr)
        self.assertIn("reintento 3/3", result.stderr)

    def test_persistent_failure_stops_and_prints_dns_guidance(self):
        result, calls = self.run_retry(attempts="3", failures=9)
        self.assertEqual(result.returncode, 47, result.stderr)
        self.assertEqual(calls, 3)
        self.assertIn("CHURROS_CONTAINER_ARGS", result.stderr)
        self.assertIn("DNS", result.stderr)
        self.assertIn("tras 3 intento(s)", result.stderr)

    def test_invalid_attempt_limit_fails_before_pacman(self):
        result, calls = self.run_retry(attempts="0", failures=9)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(calls, 0)
        self.assertIn("entre 1 y 10", result.stderr)


if __name__ == "__main__":
    unittest.main()
