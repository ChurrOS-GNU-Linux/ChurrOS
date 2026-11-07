"""Tour: terminal de usuario, autenticación interactiva e informe exacto.

Ejecuta el INSTALL_SCRIPT real con una PTY y yay/sudo/git/gpg simulados.
No necesita GTK, sudo real, red ni instalar paquetes.
"""
from __future__ import annotations

import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import shutil
import subprocess
import tempfile
import termios
import time
import unittest

from tests import testlib

TOUR = testlib.ROOT / "rust/churros-tour/src"


class TourAuthentication(unittest.TestCase):
    def test_launcher_uses_a_waited_unprivileged_terminal(self):
        protocol = (TOUR / "installation.rs").read_text()
        page = (TOUR / "pages/install.rs").read_text()
        helper = protocol.split("pub fn terminal_args(", 1)[1].split("#[derive", 1)[0]
        self.assertIn('["foot", "-e"]', helper, "tour:terminal:foot")
        self.assertIn('["xfce4-terminal", "--disable-server", "--execute"]', helper,
                      "tour:terminal:xfce-wait")
        self.assertIn('edition == "xfce"', helper)
        launcher = page.split("let mut args:", 1)[1].split("let feedback =", 1)[0]
        self.assertIn("terminal_args(&churros_services::version::edition())", launcher,
                      "tour:terminal:launcher")
        self.assertIn('args.extend([\n        "sh".into(),', launcher)
        self.assertIn("INSTALL_SCRIPT.into()", launcher)
        self.assertIn("pkg.clone()", launcher)
        self.assertNotRegex(helper + launcher, r'"(?:sudo|pkexec)"',
                            "tour:terminal:unprivileged")
        self.assertIn("gio::SubprocessFlags::NONE", launcher,
                      "tour:terminal:no-subprocess-pipes")
        self.assertIn("result.is_ok() && waited.is_successful() && report.succeeded()", page,
                      "tour:report:both-required")
        self.assertIn("timer.remove();", page)
        self.assertIn("index, total, true)", page, "tour:progress:final-drain")

    def run_install(self, code: int, cancel: bool = False):
        source = (TOUR / "installation.rs").read_text()
        script = re.search(r'pub const INSTALL_SCRIPT: &str = r#"(.*?)"#;', source, re.S)
        self.assertIsNotNone(script, "tour:authentication:installation-script")
        with tempfile.TemporaryDirectory(prefix="tour-auth-") as tmp:
            root = Path(tmp)
            bin_dir = root / "bin"
            bin_dir.mkdir()
            for name in ("sudo", "git", "gpg"):
                path = bin_dir / name
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o700)
            tee = shutil.which("tee")
            self.assertIsNotNone(tee, "tour:progress:tee-required")
            (bin_dir / "tee").symlink_to(tee)
            yay = bin_dir / "yay"
            yay.write_text('''#!/bin/sh
[ -t 0 ] || { echo NO_TERMINAL_INPUT; exit 90; }
printf 'Downloading 25%%\r'
printf 'TOUR_AUTHENTICATE:' > /dev/tty || exit 91
IFS= read -r answer < /dev/tty || exit 92
[ "$answer" = 'test-password' ] || exit 93
printf '%s\\0' "$@" > "$TOUR_TEST_ARGS"
printf 'Installing 100%%\\rfinal detail without newline'
exit "$TOUR_TEST_EXIT"
''')
            yay.chmod(0o700)
            report = root / "status"
            args_file = root / "args"
            packages = ["firefox", "literal; echo injected", "$(false)", "two words"]
            env = {**os.environ, "PATH": str(bin_dir), "TOUR_TEST_EXIT": str(code),
                   "TOUR_TEST_ARGS": str(args_file)}
            master, slave = pty.openpty()

            def acquire_terminal():
                os.setsid()
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

            process = None
            try:
                process = subprocess.Popen(
                    ["/bin/sh", "-c", script.group(1), "churros-tour", str(report), *packages],
                    env=env, stdin=slave, stdout=slave, stderr=slave,
                    preexec_fn=acquire_terminal,
                )
                output = b""
                deadline = time.monotonic() + 5
                while b"TOUR_AUTHENTICATE:" not in output and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.05)[0]:
                        try:
                            output += os.read(master, 4096)
                        except OSError:
                            break
                    if process.poll() is not None:
                        break
                self.assertIn(b"TOUR_AUTHENTICATE:", output,
                              "tour:authentication:controlling-tty-and-stdin")
                log = Path(str(report) + ".output")
                while (not log.exists() or "25%" not in log.read_text()) and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(log.exists(), "tour:progress:live-log")
                self.assertIn("25%", log.read_text(), "tour:progress:live-log")
                self.assertFalse(report.exists(), "tour:report:not-before-yay-exits")
                if cancel:
                    os.killpg(process.pid, signal.SIGTERM)
                    self.assertNotEqual(process.wait(timeout=5), 0)
                    self.assertFalse(report.exists(), "tour:report:cancellation-is-not-success")
                else:
                    os.write(master, b"test-password\n")
                    self.assertEqual(process.wait(timeout=5), code, "tour:report:exact-exit")
                    self.assertEqual(report.read_text(), f"{code}\n", "tour:report:exact-status")
                    self.assertEqual(args_file.read_bytes().split(b"\0")[:-1],
                                     [arg.encode() for arg in [
                                         "-S", "--needed", "--noconfirm",
                                         "--answerclean", "None", "--answerdiff", "None", "--", *packages,
                                     ]], "tour:arguments:exact")
                    self.assertIn("final detail without newline", log.read_text())
                    self.assertNotIn("test-password", log.read_text(), "tour:authentication:no-password-log")
            finally:
                if process is not None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)
                os.close(slave)
                os.close(master)

    def test_authentication_and_exact_status_with_a_real_pty(self):
        for code in (0, 1, 42, 130):
            with self.subTest(code=code):
                self.run_install(code)

    def test_interruption_during_authentication_never_reports_success(self):
        self.run_install(0, cancel=True)


if __name__ == "__main__":
    unittest.main()
