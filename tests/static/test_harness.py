"""Pruebas unitarias del propio arnés: lo que lee la ISO, la VM y las mutaciones.

tests/iso, tests/vm y tests/mutations solo se ejecutan con una ISO, con QEMU o
en el job de mutaciones. Un error en su análisis (una columna mal leída, una
cabecera XWD mal interpretada) haría que una comprobación no pudiera fallar
nunca, y nadie lo notaría: aquí se prueban sus funciones puras con entradas
conocidas, en segundos y sin ISO.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

from tests import testlib
from tests.iso import check_iso
from tests.mutations import run_mutations
from tests.vm import boot_smoke, qemu

# Líneas reales de `unsquashfs -lln -d ''` sobre el airootfs.sfs de una ISO niri.
LISTING = """\
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /etc
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /etc/systemd
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /etc/systemd/system
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr/bin
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr/lib
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr/lib/systemd
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr/share
drwxr-xr-x 0/0                      20 2026-10-22 04:26 /usr/share/churros
dr-xr-xr-x 0/0                       3 2026-10-22 04:26 /dev
-r-------- 0/0                     871 2026-10-22 04:26 /etc/shadow
lrwxrwxrwx 0/0                      38 2026-10-22 04:26 /etc/systemd/system/display-manager.service -> /usr/lib/systemd/system/greetd.service
-rwxr-xr-x 0/0                  594584 2026-10-22 04:26 /usr/bin/churros-welcome
-rwsr-xr-x 0/0                  261304 2026-06-16 09:31 /usr/bin/sudo
-rw-r--r-- 1000/1000              12 2026-10-22 04:26 /usr/share/churros/con espacio.txt
drwxr-xr-x 0/0                       4 2026-10-22 04:26 /usr/lib/systemd/system
-rw-r--r-- 0/0                     512 2026-10-22 04:26 /usr/lib/systemd/system/greetd.service
lrwxrwxrwx 0/0                       7 2026-10-22 04:26 /lib -> usr/lib
"""


class CheckIsoTest(unittest.TestCase):
    def test_listing(self):
        entries = check_iso.parse_listing(LISTING)
        self.assertEqual(entries["/etc/shadow"]["mode"], 0o400)
        self.assertEqual(entries["/usr/bin/churros-welcome"]["mode"], 0o755)
        self.assertEqual(entries["/usr/bin/sudo"]["mode"], 0o4755, "el bit setuid no se lee")
        self.assertEqual(entries["/usr/share/churros/con espacio.txt"]["uid"], 1000,
                         "una ruta con espacios rompe el análisis de unsquashfs -lln")
        link = entries["/etc/systemd/system/display-manager.service"]
        self.assertEqual((link["type"], link["target"]), ("l", "/usr/lib/systemd/system/greetd.service"))

    def test_resolve_follows_links(self):
        squash = object.__new__(check_iso.Squash)
        squash.entries = check_iso.parse_listing(LISTING)
        self.assertEqual(squash.resolve("/etc/systemd/system/display-manager.service"),
                         "/usr/lib/systemd/system/greetd.service")
        self.assertEqual(squash.resolve("/lib/systemd/system/greetd.service"),
                         "/usr/lib/systemd/system/greetd.service", "enlace relativo en un directorio")
        self.assertIsNone(squash.resolve("/usr/bin/no-existe"))

    def test_perm_bits_and_normalize(self):
        self.assertEqual(check_iso.perm_bits("-rwxr-sr-t"), 0o3755)
        self.assertEqual(check_iso.perm_bits("-rw-r--r--"), 0o644)
        self.assertEqual(check_iso.normalize("/usr/lib/../bin/./x"), "/usr/bin/x")

    def test_elf_info_reads_machine_and_needed(self):
        machine = {"x86_64": 62, "aarch64": 183, "i686": 3, "i386": 3}.get(platform.machine())
        if machine is None:
            self.skipTest(f"arquitectura del equipo sin tabla: {platform.machine()}")
        info = check_iso.elf_info(Path(os.path.realpath(sys.executable)))
        self.assertIsNotNone(info, "el intérprete de Python no se reconoce como ELF")
        self.assertEqual(info["machine"], machine)
        self.assertTrue(any(name.startswith("libc.so") for name in info["needed"]),
                        f"DT_NEEDED sin libc: {info['needed']}")


class BootSmokeTest(unittest.TestCase):
    def test_parse_coredumps(self):
        sample = json.dumps([
            {"time": 1, "pid": 812, "uid": 1000, "gid": 1000, "sig": 11, "corefile": "present",
             "exe": "/usr/bin/niri", "size": 1234},
            {"time": 2, "pid": 900, "uid": 1000, "gid": 1000, "sig": 6, "corefile": "none",
             "exe": "/usr/bin/churros-welcome", "size": None},
        ])
        self.assertEqual(boot_smoke.parse_coredumps(sample), ["churros-welcome", "niri"])
        self.assertEqual(boot_smoke.parse_coredumps(""), [])
        self.assertEqual(boot_smoke.parse_coredumps("No coredumps found."), [])

    def test_ppm_png_roundtrip_and_stats(self):
        rgb = bytes([0, 0, 0, 255, 128, 0, 10, 200, 30, 255, 255, 255])  # 2x2
        with tempfile.TemporaryDirectory() as tmp:
            ppm = Path(tmp) / "s.ppm"
            ppm.write_bytes(b"P6\n# comentario\n2 2\n255\n" + rgb)
            self.assertEqual(boot_smoke.read_ppm(ppm), (2, 2, rgb))
            png = Path(tmp) / "s.png"
            boot_smoke.write_png(png, 2, 2, rgb)
            data = png.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        width, height = struct.unpack(">II", data[16:24])
        self.assertEqual((width, height), (2, 2))
        idat = data[data.index(b"IDAT") + 4:data.index(b"IEND") - 8]
        self.assertEqual(zlib.decompress(idat), b"\0" + rgb[:6] + b"\0" + rgb[6:])
        bright, colours = boot_smoke.screen_stats(rgb)
        self.assertEqual((bright, colours), (0.75, 4))
        self.assertEqual(boot_smoke.screen_stats(bytes(12)), (0.0, 1), "una pantalla negra cuenta como escritorio")


class QemuTest(unittest.TestCase):
    def xwd(self, pixels: list[tuple[int, int, int]], width: int) -> bytes:
        height = len(pixels) // width
        header = struct.pack(">25I", 100 + 8, 7, 2, 24, width, height, 0, 0, 32, 0, 32, 32, width * 4,
                             4, 0xFF0000, 0x00FF00, 0x0000FF, 8, 256, 0, width, height, 0, 0, 0)
        body = b"".join(bytes([b, g, r, 0]) for r, g, b in pixels)  # LSBFirst: B G R X
        return header + b"churros\0" + body

    def test_xwd_to_rgb(self):
        data = self.xwd([(255, 0, 0), (0, 255, 0), (0, 0, 255), (10, 20, 30)], width=2)
        self.assertEqual(qemu.xwd_to_rgb(data), (2, 2, bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 10, 20, 30])))

    def test_crop_to_content(self):
        width, height = 4, 3
        rgb = bytearray(width * height * 3)
        rgb[(1 * width + 1) * 3:(1 * width + 3) * 3] = b"\x10\x20\x30\x40\x50\x60"
        self.assertEqual(qemu.crop_to_content(width, height, bytes(rgb)), (2, 1, b"\x10\x20\x30\x40\x50\x60"))
        self.assertEqual(qemu.crop_to_content(2, 2, bytes(12))[:2], (1, 1))


class MutationsTest(unittest.TestCase):
    def test_mutated_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "lista").write_text("foot\nfuzzel\nfoot-terminfo\n")
            self.assertEqual(run_mutations.mutated_text({"file": "lista", "find_re": "^foot\n", "replace": ""}, root),
                             ("fuzzel\nfoot-terminfo\n", None))
            self.assertEqual(run_mutations.mutated_text(
                {"file": "lista", "find_re": r"^(fuzzel)$", "replace": r"\1x"}, root)[0], "foot\nfuzzelx\nfoot-terminfo\n")
            text, error = run_mutations.mutated_text({"file": "lista", "find": "foot", "replace": ""}, root)
            self.assertIsNone(text)
            self.assertIn("2 veces", error)
            self.assertIn("no existe", run_mutations.mutated_text({"file": "otra", "delete": True}, root)[1])


class TestlibTest(unittest.TestCase):
    def test_shell_commands(self):
        self.assertEqual(testlib.shell_commands("env A=1 foo --x && bar | baz; exec sudo -u churros qux"),
                         ["foo", "bar", "baz", "qux"])

    def test_assert_findings_ratchet(self):
        class Probe(unittest.TestCase):
            def runTest(self):
                pass
        probe = Probe()
        known = {"cat:conocido": "nota", "cat:arreglado": "nota", "otra:x": "nota"}
        with mock.patch.object(testlib, "known_issues", return_value=known):
            testlib.assert_findings(probe, "cat", {"cat:conocido": "m", "cat:arreglado": "m"})
            with self.assertRaises(AssertionError) as new:
                testlib.assert_findings(probe, "cat", {"cat:conocido": "m", "cat:arreglado": "m", "cat:nuevo": "m"})
            self.assertIn("cat:nuevo", str(new.exception))
            with self.assertRaises(AssertionError) as fixed:
                testlib.assert_findings(probe, "cat", {"cat:conocido": "m"})
            self.assertIn("cat:arreglado", str(fixed.exception))


if __name__ == "__main__":
    unittest.main()
