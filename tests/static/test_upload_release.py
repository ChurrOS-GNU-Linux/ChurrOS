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



class ReleaseNotes(unittest.TestCase):
    """--release-notes: enlaces a las ISO del servidor, comprobados antes de escribirlos (#340)."""

    NIRI, XFCE = "ChurrOS-9.9-niri-x86_64.iso", "ChurrOS-9.9-xfce-x86_64.iso"
    SUMS = f"{'a' * 64}  {NIRI}\n{'b' * 64}  {XFCE}\n"
    ISOS = [(NIRI, 2_813_313_024), (XFCE, 2_634_776_576)]

    def setUp(self):
        self.upload = load_upload_release()
        base = self.upload.DOWNLOAD_BASE
        # Servidor falso: url -> (código, cuerpo, Content-Length).
        self.served = {base + self.NIRI: (200, "", 2_813_313_024),
                       base + self.XFCE: (200, "", 2_634_776_576),
                       base + "SHA256SUMS-9.9": (200, self.SUMS, len(self.SUMS))}
        self.asked = []

    def probe(self, url, method="HEAD"):
        self.asked.append((method, url))
        return self.served.get(url, (404, "", 0))

    def notes(self):
        return self.upload.release_notes("9.9", self.ISOS, self.SUMS, probe=self.probe)

    def test_notes_link_every_iso_with_edition_arch_and_hash(self):
        notes, problems = self.notes()
        self.assertEqual(problems, [])
        base = self.upload.DOWNLOAD_BASE
        self.assertIn(f"| Niri | x86_64 | [{self.NIRI}]({base}{self.NIRI}) | 2,6 GiB | `{'a' * 64}` |", notes)
        self.assertIn(f"| XFCE | x86_64 | [{self.XFCE}]({base}{self.XFCE}) | 2,5 GiB | `{'b' * 64}` |", notes)
        self.assertIn(f"[SHA256SUMS-9.9]({base}SHA256SUMS-9.9)", notes)
        self.assertIn("sha256sum -c SHA256SUMS-9.9", notes)
        self.assertIn("no van firmadas", notes, "las notas tienen que decir que las sumas no están firmadas")
        self.assertNotIn("actions/runs", notes, "nunca un artefacto de workflow")
        self.assertEqual({url for _, url in self.asked}, set(self.served), "hay que comprobar cada enlace")

    def test_a_missing_iso_writes_no_notes(self):
        del self.served[self.upload.DOWNLOAD_BASE + self.XFCE]
        notes, problems = self.notes()
        self.assertEqual(notes, "", "[notes-checked] se escribieron notas con un enlace roto")
        self.assertTrue(any(self.XFCE in p and "HTTP 404" in p for p in problems), problems)

    def test_a_truncated_upload_writes_no_notes(self):
        self.served[self.upload.DOWNLOAD_BASE + self.NIRI] = (200, "", 1_000_000)
        notes, problems = self.notes()
        self.assertEqual(notes, "", "[notes-checked] una ISO a medio subir pasó por buena")
        self.assertTrue(any("1000000 bytes" in p for p in problems), problems)

    def test_sums_on_the_server_must_be_the_local_ones(self):
        self.served[self.upload.DOWNLOAD_BASE + "SHA256SUMS-9.9"] = (200, self.SUMS.replace("a", "c"), 0)
        notes, problems = self.notes()
        self.assertEqual(notes, "", "[notes-checked] el SHA256SUMS del servidor no es el de estas ISO")
        self.assertTrue(any("no coincide" in p for p in problems), problems)

    def test_an_iso_of_another_version_is_refused(self):
        notes, problems = self.upload.release_notes(
            "9.9", [*self.ISOS, ("ChurrOS-9.8-niri-x86_64.iso", 1)], self.SUMS, probe=self.probe)
        self.assertEqual(notes, "")
        self.assertTrue(any("9.8" in p for p in problems), problems)

    def test_busy_server_is_retried_but_404_is_not(self):
        calls = []

        class Response:
            status, headers = 200, {"Content-Length": "7"}
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def read(self): return b""

        def urlopen(request, timeout):
            calls.append(request.full_url)
            if len(calls) < 3:
                raise self.upload.urllib.error.HTTPError(request.full_url, 503, "ocupado", {}, None)
            return Response()

        upload = self.upload
        original_urlopen, original_sleep = upload.urllib.request.urlopen, upload.time.sleep
        upload.urllib.request.urlopen, upload.time.sleep = urlopen, lambda s: None
        try:
            self.assertEqual(upload.probe("https://x/a.iso"), (200, "", 7))
            self.assertEqual(len(calls), 3, "un 503 se reintenta")
            calls.clear()

            def missing(request, timeout):
                calls.append(1)
                raise upload.urllib.error.HTTPError(request.full_url, 404, "no", {}, None)
            upload.urllib.request.urlopen = missing
            self.assertEqual(upload.probe("https://x/b.iso")[0], 404)
            self.assertEqual(len(calls), 1, "un 404 no se reintenta")
        finally:
            upload.urllib.request.urlopen, upload.time.sleep = original_urlopen, original_sleep


if __name__ == "__main__":
    unittest.main()
