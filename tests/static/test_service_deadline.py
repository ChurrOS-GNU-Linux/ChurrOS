"""Contrato del plazo de run(), sin necesitar Cargo ni ejecutar comandos.

Las pruebas Rust de lib.rs reproducen el comportamiento; estas comprobaciones
estructurales detectan regresiones del plazo y de la captura en la capa static
(incluidas las mutaciones propuestas), no sustituyen esas pruebas de ejecución.
"""
from __future__ import annotations

import re
import unittest

from tests import testlib
from tests.static.test_rust_contract import lex_rust


class ServiceDeadlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = testlib.read_text(testlib.ROOT / "rust/services/src/lib.rs")
        code, _ = lex_rust(source)
        cls.run_code = re.sub(
            r"\s+", " ", code.split("pub fn run(", 1)[1].split("pub fn spawn(", 1)[0]
        )
        cls.reader_code = re.sub(
            r"\s+", " ", code.split("fn read_capture(", 1)[1].split("pub fn run(", 1)[0]
        )

    def test_deadline_covers_capture_loop(self):
        code = self.run_code
        self.assertIn(
            "let timeout = (timeout_ms > 0).then(|| Duration::from_millis(timeout_ms));",
            code,
            "[service-deadline:zero-unlimited]",
        )
        loop = code.split("loop {", 1)[1]
        self.assertIn(
            "let remaining = timeout.saturating_sub(started.elapsed()); "
            "if remaining.is_zero() { return None; }",
            loop,
            "[service-deadline:whole-capture]",
        )
        self.assertLess(loop.index("remaining.is_zero()"), loop.index("child.try_wait()"))
        self.assertIn(
            "if status.is_some() && out_eof && err_eof {",
            loop,
            "[service-deadline:both-eof]",
        )
        self.assertIn("remaining.as_millis().clamp(1, 10) as i32", loop)
        self.assertIn("pipes.len() as libc::nfds_t, poll_ms", loop)
        self.assertNotIn("wait_timeout", code)
        self.assertEqual(code.count("Instant::now()"), 1)

    def test_capture_is_nonblocking_and_fair(self):
        self.assertIn(
            "libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK)",
            self.run_code,
            "[service-deadline:nonblocking]",
        )
        self.assertIn("for fd in [out_pipe.as_raw_fd(), err_pipe.as_raw_fd()]", self.run_code)
        for pipe, output in (("out", "stdout"), ("err", "stderr")):
            self.assertIn(
                f"{pipe}_eof = read_capture(&mut {pipe}_pipe, &mut {output}).ok()?;",
                self.run_code,
                "[service-deadline:concurrent-capture]",
            )
        self.assertEqual(self.reader_code.count("pipe.read("), 1)
        self.assertNotRegex(self.reader_code, r"\b(?:loop|while|for)\b")
        self.assertIn("io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted", self.reader_code)
        self.assertNotRegex(self.run_code + self.reader_code, r"read_to_(?:end|string)|\.join\(|thread::")

    def test_failure_reaps_child_and_pipes_are_owned(self):
        self.assertIn("let mut out_pipe = child.stdout.take()?;", self.run_code)
        self.assertIn("let mut err_pipe = child.stderr.take()?;", self.run_code)
        self.assertIn(
            "})(); if result.is_none() { let _ = child.kill(); let _ = child.wait(); } result }",
            self.run_code,
            "[service-deadline:cleanup]",
        )
        self.assertNotRegex(self.run_code, r"into_raw_fd|mem::forget")
        self.assertIn("String::from_utf8(stdout).ok()?", self.run_code)
        self.assertIn("String::from_utf8(stderr).ok()?", self.run_code)


if __name__ == "__main__":
    unittest.main()
