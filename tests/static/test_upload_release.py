"""scripts/upload-release.py: qué sumas de verificación se publican."""

import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import testlib


def load_upload_release():
    spec = importlib.util.spec_from_file_location("upload_release", testlib.ROOT / "scripts/upload-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IsoSums(unittest.TestCase):
    def test_each_version_keeps_its_own_sums(self):
        upload = load_upload_release()
        text = "a" * 64 + "  ChurrOS-1.5.7-niri-x86_64.iso\n"
        with tempfile.TemporaryDirectory() as tmp:
            files = upload.iso_sums_files(Path(tmp), "1.5.7", text)
            names = [path.name for path in files]
            self.assertIn("SHA256SUMS-1.5.7", names,
                          "[versioned-sha256sums] sin SHA256SUMS-<versión>, publicar una versión deja las ISO "
                          "anteriores del historial de la web sin suma con la que verificarlas")
            self.assertEqual(names[-1], "SHA256SUMS", "SHA256SUMS (la versión actual) se sube el último")
            for path in files:
                self.assertEqual(path.read_text(encoding="utf-8"), text)


def tiny_iso(directory: Path, arch: str, version: str, edition: str) -> Path:
    """ISO mínima con /churros/<arch>/airootfs.sfs, como las de mkarchiso."""
    root = directory / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc/os-release").write_text(f'NAME="ChurrOS"\nVERSION_ID={version}\n')
    (root / "etc/churros-edition").write_text(f"{edition}\n")
    sfs = directory / "airootfs.sfs"
    subprocess.run(["mksquashfs", str(root), str(sfs), "-quiet", "-noappend", "-no-progress"], check=True,
                   stdout=subprocess.DEVNULL)
    iso = directory / "imagen.iso"
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-R", "-o", str(iso), "-graft-points",
                    f"/churros/{arch}/airootfs.sfs={sfs}"], check=True, stderr=subprocess.DEVNULL)
    return iso


class IsoIdentity(unittest.TestCase):
    """#344: antes de subir, cada ISO es lo que dice su nombre."""

    IDENTITY = {"archs": ["x86_64"], "version": "1.5.7", "edition": "niri"}

    def test_matching_iso_has_no_problems(self):
        upload = load_upload_release()
        self.assertEqual(upload.iso_problems("ChurrOS-1.5.7-niri-x86_64.iso", "1.5.7", self.IDENTITY), [])

    def test_each_mismatch_is_reported(self):
        upload = load_upload_release()
        cases = {
            "ChurrOS-1.5.7-xfce-x86_64.iso": "churros-edition dice niri",
            "ChurrOS-1.5.7-niri-aarch64.iso": "no solo para aarch64",
            "ChurrOS-1.5.6-niri-x86_64.iso": "se publica la 1.5.7",
            "ChurrOS-1.5.7-gnome-x86_64.iso": "edición desconocida",
            "churros-niri.iso": "el nombre no es",
        }
        for name, expected in cases.items():
            problems = " ".join(upload.iso_problems(name, "1.5.7", self.IDENTITY))
            self.assertIn(expected, problems, f"[iso-identity] {name}: {problems or 'sin problemas'}")
        stale = dict(self.IDENTITY, version="1.5.6")
        self.assertIn("VERSION_ID=1.5.6", " ".join(upload.iso_problems("ChurrOS-1.5.7-niri-x86_64.iso", "1.5.7", stale)),
                      "[iso-identity] una ISO vieja renombrada a la versión nueva")

    def test_reads_the_identity_from_inside_a_real_iso(self):
        testlib.require_tool(self, "xorriso")
        testlib.require_tool(self, "mksquashfs")
        testlib.require_tool(self, "unsquashfs")
        upload = load_upload_release()
        with tempfile.TemporaryDirectory() as tmp:
            iso = tiny_iso(Path(tmp), "x86_64", "1.5.7", "xfce")
            identity = upload.read_iso_identity(iso)
        self.assertEqual(identity, {"archs": ["x86_64"], "version": "1.5.7", "edition": "xfce"},
                         "[iso-identity] no lee arquitectura, versión y edición de dentro de la ISO")

    def test_sums_list_each_iso_exactly_once(self):
        upload = load_upload_release()
        a, b = "ChurrOS-1.5.7-niri-x86_64.iso", "ChurrOS-1.5.7-xfce-x86_64.iso"
        line = lambda name: "0" * 64 + "  " + name
        self.assertEqual(upload.sums_problems(f"{line(a)}\n{line(b)}\n", [a, b]), [])
        problems = " ".join(upload.sums_problems(f"{line(a)}\n{line(a)}\n{line('otra.iso')}\nbasura\n", [a, b]))
        for expected in ("aparece 2 veces", "otra.iso no está", f"falta {b}", "mal formada"):
            self.assertIn(expected, problems, f"[sums-once] {problems}")


if __name__ == "__main__":
    unittest.main()
