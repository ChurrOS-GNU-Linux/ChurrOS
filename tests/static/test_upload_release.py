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


def tiny_iso(directory: Path, arch: str, version: str, edition: str, pkglist: str | None = None) -> Path:
    """ISO mínima con /churros/<arch>/airootfs.sfs (y pkglist.<arch>.txt), como las de mkarchiso."""
    root = directory / "root"
    (root / "etc").mkdir(parents=True)
    (root / "etc/os-release").write_text(f'NAME="ChurrOS"\nVERSION_ID={version}\n')
    (root / "etc/churros-edition").write_text(f"{edition}\n")
    sfs = directory / "airootfs.sfs"
    subprocess.run(["mksquashfs", str(root), str(sfs), "-quiet", "-noappend", "-no-progress"], check=True,
                   stdout=subprocess.DEVNULL)
    iso = directory / "imagen.iso"
    grafts = [f"/churros/{arch}/airootfs.sfs={sfs}"]
    if pkglist is not None:
        (directory / "pkglist.txt").write_text(pkglist)
        grafts.append(f"/churros/pkglist.{arch}.txt={directory / 'pkglist.txt'}")
    subprocess.run(["xorriso", "-as", "mkisofs", "-quiet", "-R", "-o", str(iso), "-graft-points", *grafts],
                   check=True, stderr=subprocess.DEVNULL)
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
        self.inventories = {self.NIRI: "# niri\nniri 26.04-1\n", self.XFCE: "# xfce\nxfce4-session 4.20.4-1\n"}
        self.served = {base + self.NIRI: (200, "", 2_813_313_024),
                       base + self.XFCE: (200, "", 2_634_776_576),
                       base + "ChurrOS-9.9-niri-x86_64.paquetes.txt": (200, self.inventories[self.NIRI], 0),
                       base + "ChurrOS-9.9-xfce-x86_64.paquetes.txt": (200, self.inventories[self.XFCE], 0),
                       base + "SHA256SUMS-9.9": (200, self.SUMS, len(self.SUMS))}
        self.asked = []

    def probe(self, url, method="HEAD"):
        self.asked.append((method, url))
        return self.served.get(url, (404, "", 0))

    def notes(self):
        return self.upload.release_notes("9.9", self.ISOS, self.SUMS, self.inventories, probe=self.probe)

    def test_notes_link_every_iso_with_edition_arch_and_hash(self):
        notes, problems = self.notes()
        self.assertEqual(problems, [])
        base = self.upload.DOWNLOAD_BASE
        self.assertIn(f"| Niri | x86_64 | [{self.NIRI}]({base}{self.NIRI}) | 2,6 GiB "
                      f"| [lista]({base}ChurrOS-9.9-niri-x86_64.paquetes.txt) | `{'a' * 64}` |", notes)
        self.assertIn(f"| XFCE | x86_64 | [{self.XFCE}]({base}{self.XFCE}) | 2,5 GiB "
                      f"| [lista]({base}ChurrOS-9.9-xfce-x86_64.paquetes.txt) | `{'b' * 64}` |", notes)
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

    def test_the_package_inventory_must_be_published_as_is(self):
        base = self.upload.DOWNLOAD_BASE
        self.served[base + "ChurrOS-9.9-xfce-x86_64.paquetes.txt"] = (200, "# de otra ISO\n", 0)
        notes, problems = self.notes()
        self.assertEqual(notes, "", "[packages-inventory] las notas enlazan un inventario que no es el de la ISO")
        self.assertTrue(any("no es el inventario" in p for p in problems), problems)
        del self.served[base + "ChurrOS-9.9-niri-x86_64.paquetes.txt"]
        self.assertTrue(any("paquetes.txt: HTTP 404" in p for p in self.notes()[1]))

    def test_an_iso_of_another_version_is_refused(self):
        notes, problems = self.upload.release_notes(
            "9.9", [*self.ISOS, ("ChurrOS-9.8-niri-x86_64.iso", 1)], self.SUMS, self.inventories, probe=self.probe)
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


class PackageInventory(unittest.TestCase):
    """#339: inventario de paquetes sacado de la ISO final, ligado a ella."""

    ISO = "ChurrOS-1.5.7-niri-x86_64.iso"
    SOURCE = "/churros/pkglist.x86_64.txt"
    PKGLIST = "niri 26.04-1\nlinux-cachyos 7.3.5-2\nbazaar 0.9.9-1\n"

    def test_inventory_is_bound_to_name_version_arch_and_hash(self):
        upload = load_upload_release()
        text, problems = upload.packages_inventory(self.ISO, "e" * 64, self.SOURCE, self.PKGLIST)
        self.assertEqual(problems, [])
        self.assertEqual(upload.packages_name(self.ISO), "ChurrOS-1.5.7-niri-x86_64.paquetes.txt")
        for expected in (f"# Paquetes de {self.ISO}", "Versión 1.5.7, edición niri, arquitectura x86_64",
                         f"SHA-256 de la ISO: {'e' * 64}", self.SOURCE, "Calamares", "3 paquetes"):
            self.assertIn(expected, text, f"[packages-inventory] falta {expected!r}")
        body = [line for line in text.splitlines() if not line.startswith("#")]
        self.assertEqual(body, ["bazaar 0.9.9-1", "linux-cachyos 7.3.5-2", "niri 26.04-1"], "ordenado y completo")

    def test_lists_that_are_not_a_clean_pkglist_are_refused(self):
        upload = load_upload_release()
        cases = {
            "/tmp/build/x 1.0-1\n": "no es «paquete versión»",          # una ruta temporal
            "niri 26.04-1 extra\n": "no es «paquete versión»",
            "niri 26.04-1\nniri 26.04-2\n": "niri aparece 2 veces",
            "\n": "está vacía",
        }
        for pkglist, expected in cases.items():
            text, problems = upload.packages_inventory(self.ISO, "e" * 64, self.SOURCE, pkglist)
            self.assertEqual(text, "", f"[packages-inventory] {pkglist!r} se publicó")
            self.assertIn(expected, " ".join(problems), problems)
        wrong_arch = upload.packages_inventory(self.ISO, "e" * 64, "/churros/pkglist.aarch64.txt", self.PKGLIST)
        self.assertIn("no la de x86_64", " ".join(wrong_arch[1]))
        self.assertIn("no tiene pkglist", " ".join(upload.packages_inventory(self.ISO, "e" * 64, None, None)[1]))

    def test_reads_the_pkglist_from_inside_a_real_iso(self):
        testlib.require_tool(self, "xorriso")
        testlib.require_tool(self, "mksquashfs")
        upload = load_upload_release()
        with tempfile.TemporaryDirectory() as tmp:
            iso = tiny_iso(Path(tmp), "x86_64", "1.5.7", "niri", pkglist=self.PKGLIST)
            self.assertEqual(upload.read_iso_pkglist(iso), (self.SOURCE, self.PKGLIST),
                             "[packages-inventory] no lee pkglist.<arch>.txt de la ISO")
            named = Path(tmp) / self.ISO
            iso.rename(named)
            out = Path(tmp) / "out"
            out.mkdir()
            written, problems = upload.iso_inventories([named], f"{'e' * 64}  {self.ISO}\n", out)
            self.assertEqual(problems, [])
            self.assertEqual([p.name for p in written], ["ChurrOS-1.5.7-niri-x86_64.paquetes.txt"])
            self.assertIn(f"SHA-256 de la ISO: {'e' * 64}", written[0].read_text())
            (Path(tmp) / "sin").mkdir()
            bare = tiny_iso(Path(tmp) / "sin", "x86_64", "1.5.7", "niri")
            self.assertEqual(upload.read_iso_pkglist(bare), (None, None), "una ISO sin pkglist no se inventa una")


if __name__ == "__main__":
    unittest.main()
