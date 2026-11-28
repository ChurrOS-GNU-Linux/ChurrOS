#!/usr/bin/env python3
"""Pruebas de los helpers que corren como root, sin root y sin tocar /.

- churros-update-utils: instalación sobre un root falso (/ sigue en 755,
  #130), rutas que puede tocar el bundle, validación del tarball y orden
  manifiesto -> firma (#139). Las funciones se cargan con `source`; main no se
  ejecuta.
- El bundle que genera scripts/build-churros-release.sh cabe en esas rutas.
- churros-write-root-config: operaciones acotadas, usuario de PKEXEC_UID,
  sesión de la edición, validación del fondo y del saludo, escape TOML.
- configure-greetd-session y edition-session.sh: tabla edición -> sesión.

Uso: python3 scripts/test-privileged-helpers.py
Las pruebas de tarballs necesitan zstd; si no está, salen como SKIP.
"""
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "archiso/airootfs"
UPDATE_UTILS = OVERLAY / "usr/bin/churros-update-utils"
WRITE_ROOT_CONFIG = OVERLAY / "usr/local/bin/churros-write-root-config"
EDITION_LIB = OVERLAY / "usr/share/churros/scripts/edition-session.sh"
CONFIGURE_GREETD = OVERLAY / "usr/share/churros/scripts/configure-greetd-session"
RELEASE_SCRIPT = ROOT / "scripts/build-churros-release.sh"

HAS_ZSTD = shutil.which("zstd") is not None

SESSIONS = {
    "niri": "/usr/bin/churros-niri-session",
    "xfce": "/usr/bin/churros-xfce-session",
}

GREETER = (
    '[terminal]\nvt = 7\n\n[default_session]\n'
    'command = "env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24 cage -s -- regreet"\n'
    'user = "greeter"\n'
)


def mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def executable(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source)
    path.chmod(0o755)
    return path


def update_utils(script: str, *args, env=None) -> subprocess.CompletedProcess:
    """Ejecuta `script` con las funciones de churros-update-utils cargadas.

    $0 no es la ruta del script, así que su main no se ejecuta; los
    argumentos llegan a `script` como $1, $2...
    """
    return subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", f'source "$1"; shift\n{script}', "prueba", str(UPDATE_UTILS), *map(str, args)],
        capture_output=True, text=True, env=env,
    )


def make_tar_zst(target: Path, members) -> Path:
    """Crea TARGET (.tar.zst) con miembros arbitrarios: (TarInfo, bytes)."""
    plain = target.with_suffix("")
    with tarfile.open(plain, "w", format=tarfile.GNU_FORMAT) as tar:
        for info, data in members:
            if data is None:
                tar.addfile(info)
            else:
                info.size = len(data)
                tar.addfile(info, __import__("io").BytesIO(data))
    subprocess.run(["zstd", "-q", "-f", "--rm", "-o", str(target), str(plain)], check=True)
    return target


def regular(name: str, data: bytes = b"x\n", perm: int = 0o644) -> tuple:
    info = tarfile.TarInfo(name)
    info.mode = perm
    return info, data


def special(name: str, kind, linkname: str = "") -> tuple:
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    info.mode = 0o644
    return info, None


def directory(name: str, perm: int = 0o755) -> tuple:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = perm
    return info, None


# ------------------------------------------------------- churros-update-utils


class UpdateUtilsInstall(unittest.TestCase):
    """install_stage: solo ficheros, nunca atributos de directorio (#130)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-update-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = self.tmp / "root"
        for rel in ("", "usr", "usr/bin", "usr/local", "usr/local/bin", "usr/share", "etc"):
            (self.root / rel).mkdir(exist_ok=True)
            (self.root / rel).chmod(0o755)
        executable(self.root / "usr/bin/churros-settings", "viejo\n")

    def stage(self, files) -> Path:
        # Como `mktemp -d` en el script: el stage es 0700 y sus directorios
        # también, para comprobar que esos modos no llegan al root.
        stage = Path(tempfile.mkdtemp(prefix="stage.", dir=self.tmp))
        self.assertEqual(mode(stage), 0o700)
        for rel, (content, perm) in files.items():
            path = stage / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
            path.chmod(perm)
        for path in stage.rglob("*"):
            if path.is_dir() and not path.is_symlink():
                path.chmod(0o700)
        return stage

    def install(self, stage) -> subprocess.CompletedProcess:
        return update_utils('install_stage "$1" "$2"', stage, self.root)

    def snapshot(self):
        return sorted((str(p.relative_to(self.root)), mode(p), p.read_bytes() if p.is_file() else b"")
                      for p in self.root.rglob("*"))

    def test_root_usr_and_etc_keep_their_mode(self):
        stage = self.stage({
            "usr/bin/churros-settings": ("nuevo\n", 0o755),
            "usr/local/bin/churros-snapshot": ("snap\n", 0o755),
            "usr/share/churros/scripts/edition-session.sh": ("lib\n", 0o644),
            "usr/share/churros/wallpapers/nuevo/fondo.png": ("png\n", 0o600),
            "etc/churros-version": ("1.3\n", 0o644),
        })
        result = self.install(stage)
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in ("", "usr", "usr/bin", "usr/local", "usr/local/bin", "usr/share", "etc"):
            self.assertEqual(mode(self.root / rel), 0o755, f"/{rel}")
        # Directorios nuevos: 0755, no el 0700 del stage.
        for rel in ("usr/share/churros", "usr/share/churros/scripts",
                    "usr/share/churros/wallpapers", "usr/share/churros/wallpapers/nuevo"):
            self.assertEqual(mode(self.root / rel), 0o755, rel)
        self.assertEqual((self.root / "usr/bin/churros-settings").read_text(), "nuevo\n")
        self.assertEqual(mode(self.root / "usr/bin/churros-settings"), 0o755)
        self.assertEqual(mode(self.root / "usr/local/bin/churros-snapshot"), 0o755)
        self.assertEqual(mode(self.root / "usr/share/churros/scripts/edition-session.sh"), 0o644)
        self.assertEqual(mode(self.root / "usr/share/churros/wallpapers/nuevo/fondo.png"), 0o644)
        self.assertEqual((self.root / "etc/churros-version").read_text(), "1.3\n")
        self.assertEqual([p for p in self.root.rglob(".churros-update.*")], [])

    def test_modes_are_normalized(self):
        stage = self.stage({
            "usr/bin/churros-setuid": ("x\n", 0o4755),
            "usr/share/churros/privado": ("x\n", 0o640),
            "usr/share/churros/script": ("x\n", 0o700),
        })
        result = self.install(stage)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(mode(self.root / "usr/bin/churros-setuid"), 0o755)
        self.assertEqual(mode(self.root / "usr/share/churros/privado"), 0o644)
        self.assertEqual(mode(self.root / "usr/share/churros/script"), 0o755)

    def test_replacing_a_file_changes_its_inode(self):
        # rename atómico: un binario en uso conserva su inodo antiguo.
        before = (self.root / "usr/bin/churros-settings").stat().st_ino
        result = self.install(self.stage({"usr/bin/churros-settings": ("nuevo\n", 0o755)}))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual((self.root / "usr/bin/churros-settings").stat().st_ino, before)

    def test_paths_outside_the_allowlist_are_rejected(self):
        before = self.snapshot()
        for bad in ("etc/passwd", "etc/sudoers.d/evil", "etc/systemd/system/evil.service",
                    "etc/pacman.d/hooks/99-evil.hook", "usr/lib/libfoo.so", "usr/local/lib/x.so",
                    "usr/bin/sudo", "usr/bin/churros-x/sub", "usr/share/otro/x",
                    "usr/share/churrosx/a", "etc/churros-version.d/x"):
            with self.subTest(bad=bad):
                stage = self.stage({
                    "usr/bin/churros-settings": ("nuevo\n", 0o755),
                    bad: ("evil\n", 0o755),
                })
                result = self.install(stage)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("no permitida", result.stderr)
                # Nada instalado, ni siquiera lo permitido.
                self.assertEqual(self.snapshot(), before)

    def test_symlinks_in_stage_are_rejected(self):
        stage = self.stage({"usr/share/churros/a": ("x\n", 0o644)})
        (stage / "usr/share/churros/enlace").symlink_to("/etc/shadow")
        result = self.install(stage)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no es un fichero regular", result.stderr)
        self.assertFalse((self.root / "usr/share/churros").exists())


class UpdateUtilsAllowlist(unittest.TestCase):
    def check(self, path) -> bool:
        result = update_utils('member_allowed "$1"', path)
        return result.returncode == 0

    def test_allowed(self):
        for path in ("usr/bin/churros-settings", "usr/bin/churros-update-utils",
                     "usr/local/bin/churros-snapshot", "usr/local/bin/churros-write-root-config",
                     "usr/share/churros/wallpapers/default.png", "usr/share/churros/scripts/x",
                     "etc/churros-version", "etc/churros-edition",
                     "etc/pacman.d/hooks/50-churros-snapshot.hook"):
            with self.subTest(path=path):
                self.assertTrue(self.check(path))

    def test_denied(self):
        for path in ("", "usr/bin/churros-", "usr/bin/churros-a/b", "usr/bin/pacman",
                     "usr/bin/sudo", "usr/lib/libx.so", "usr/local/lib/x", "usr/share/churros",
                     "usr/share/churrosx/a", "etc/churros-version.d/x", "etc/churros-versionx",
                     "etc/passwd", "etc/pacman.d/hooks/zz-evil.hook", "/usr/bin/churros-x",
                     "./usr/bin/churros-x", "usr//bin/churros-x",
                     "usr/share/churros/../../etc/passwd", "usr/share/churros/./x"):
            with self.subTest(path=path):
                self.assertFalse(self.check(path))


@unittest.skipUnless(HAS_ZSTD, "zstd no está instalado")
class UpdateUtilsTarball(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-tarball-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def validate(self, *members) -> subprocess.CompletedProcess:
        tarball = make_tar_zst(self.tmp / "bundle.tar.zst", members)
        return update_utils('validate_tarball "$1"', tarball)

    def test_valid_bundle(self):
        result = self.validate(
            directory("./"), directory("usr/"), directory("usr/bin/", 0o700),
            regular("usr/bin/churros-settings", perm=0o755),
            regular("./usr/local/bin/churros-snapshot", perm=0o755),
            regular("usr/share/churros/wallpapers/default.png"),
            regular("etc/churros-version", b"1.3\n"),
            regular("etc/pacman.d/hooks/50-churros-snapshot.hook"),
            directory("var/lib/vacio/"),
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejected_members(self):
        cases = {
            "ruta absoluta": [regular("/etc/passwd")],
            "..": [regular("usr/share/churros/../../etc/passwd")],
            "directorio con ..": [directory("usr/share/churros/../../etc/")],
            "symlink": [special("usr/share/churros/enlace", tarfile.SYMTYPE, "/etc/shadow")],
            "hardlink": [regular("usr/share/churros/a"),
                         special("usr/share/churros/b", tarfile.LNKTYPE, "usr/share/churros/a")],
            "fifo": [special("usr/share/churros/fifo", tarfile.FIFOTYPE)],
            "fuera de la lista": [regular("etc/shadow")],
            "biblioteca": [regular("usr/lib/libevil.so", perm=0o755)],
        }
        for name, members in cases.items():
            with self.subTest(name):
                result = self.validate(regular("usr/bin/churros-settings", perm=0o755), *members)
                self.assertNotEqual(result.returncode, 0, name)

    def test_extract_and_install_like_main(self):
        tarball = make_tar_zst(self.tmp / "bundle.tar.zst", [
            directory("usr/", 0o700), directory("usr/bin/", 0o700),
            regular("usr/bin/churros-settings", b"bin\n", 0o755),
            directory("etc/", 0o700), regular("etc/churros-version", b"1.3\n"),
        ])
        root = self.tmp / "root"
        for rel in ("", "usr", "usr/bin", "etc"):
            (root / rel).mkdir(exist_ok=True)
            (root / rel).chmod(0o755)
        stage = Path(tempfile.mkdtemp(dir=self.tmp))
        result = update_utils(
            'validate_tarball "$1" && tar --zstd -xf "$1" -C "$2" --no-same-owner && install_stage "$2" "$3"',
            tarball, stage, root)
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in ("", "usr", "usr/bin", "etc"):
            self.assertEqual(mode(root / rel), 0o755, f"/{rel}")
        self.assertEqual(mode(root / "usr/bin/churros-settings"), 0o755)
        self.assertEqual((root / "etc/churros-version").read_text(), "1.3\n")


class UpdateUtilsManifest(unittest.TestCase):
    """La firma se comprueba sobre el manifiesto ya descargado (#139)."""

    MANIFEST = '{"version": "1.3", "file": "churros-utils-1.3.tar.zst", "sha256": "%s"}\n' % ("a" * 64)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-manifest-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.served = self.tmp / "served"
        self.served.mkdir()
        (self.served / "updates.json").write_text(self.MANIFEST)
        # Lo que se firmó: si lo servido no coincide, la firma no valida.
        self.signed = self.tmp / "signed.json"
        self.signed.write_text(self.MANIFEST)
        (self.served / "updates.json.minisig").write_text("firma\n")
        self.log = self.tmp / "log"
        bin_dir = self.tmp / "bin"
        # curl falso: sirve ficheros de `served` y apunta las URL pedidas.
        executable(bin_dir / "curl", f'''#!/bin/sh
out=""; url=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -o) out="$2"; shift 2 ;;
        --proto|--connect-timeout) shift 2 ;;
        -*) shift ;;
        *) url="$1"; shift ;;
    esac
done
echo "curl $url" >> "{self.log}"
cp "{self.served}/${{url##*/}}" "$out"
''')
        # minisign falso: anota el tamaño de lo que recibe y solo valida el
        # manifiesto firmado, completo.
        executable(bin_dir / "minisign", f'''#!/bin/sh
msg=""
while [ "$#" -gt 0 ]; do
    case "$1" in
        -m) msg="$2"; shift 2 ;;
        *) shift ;;
    esac
done
echo "minisign $(wc -c < "$msg")" >> "{self.log}"
cmp -s "$msg" "{self.signed}"
''')
        self.env = {**os.environ, "PATH": f"{bin_dir}:/usr/bin:/bin"}
        self.pubkey = self.tmp / "churros-release.pubkey"

    def fetch(self, pubkey: Path):
        return update_utils(f'PUBKEY="$1"; fetch_manifest "$2" && cat "$2"',
                            pubkey, self.tmp / "manifest", env=self.env)

    def test_signature_checked_after_download(self):
        self.pubkey.write_text("clave\n")
        result = self.fetch(self.pubkey)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Firma del manifiesto verificada", result.stdout)
        log = self.log.read_text().splitlines()
        base = update_utils('printf "%s" "$BASE"').stdout
        self.assertEqual(log[0], f"curl {base}updates.json")
        self.assertEqual(log[1], f"curl {base}updates.json.minisig")
        self.assertEqual(log[2], f"minisign {len(self.MANIFEST.encode())}")

    def test_bad_signature_aborts(self):
        self.pubkey.write_text("clave\n")
        (self.served / "updates.json").write_text(self.MANIFEST.replace("1.3", "6.6.6"))
        result = self.fetch(self.pubkey)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("firma minisign inválida", result.stderr)

    def test_without_pubkey_aborts(self):
        result = self.fetch(self.tmp / "no-existe.pubkey")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("falta la clave pública", result.stderr)
        self.assertNotIn("minisign", self.log.read_text())

    @unittest.skipIf(shutil.which("minisign", path="/usr/bin:/bin"), "minisign instalado en el host")
    def test_pubkey_without_minisign_aborts(self):
        self.pubkey.write_text("clave\n")
        (self.tmp / "bin/minisign").unlink()
        result = self.fetch(self.pubkey)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("falta minisign", result.stderr)

    def env_without_minisign(self) -> dict:
        """PATH con las órdenes del sistema salvo minisign (el host puede tenerlo)."""
        tools = self.tmp / "tools"
        tools.mkdir(exist_ok=True)
        for name in ("sh", "bash", "cp", "cmp", "wc", "mktemp", "rm", "cat", "id", "tr", "grep", "cut",
                     "awk", "python3", "sha256sum", "mv", "chmod", "dirname", "basename", "env", "uname"):
            found = shutil.which(name, path="/usr/bin:/bin")
            if found and not (tools / name).exists():
                (tools / name).symlink_to(found)
        return {**os.environ, "PATH": f"{self.tmp / 'bin'}:{tools}"}

    def test_root_installs_missing_minisign(self):
        """Quien viene de la 1.4 (sin minisign) puede seguir actualizando."""
        self.pubkey.write_text("clave\n")
        real = self.tmp / "bin/minisign"
        hidden = self.tmp / "minisign.pkg"
        real.rename(hidden)
        executable(self.tmp / "pacman", f'''#!/bin/sh
echo "pacman $*" >> "{self.log}"
cp "{hidden}" "{real}"
''')
        result = update_utils(f'PUBKEY="$1"; PACMAN="$3"; am_root() {{ return 0; }}; fetch_manifest "$2"',
                              self.pubkey, self.tmp / "manifest", self.tmp / "pacman",
                              env=self.env_without_minisign())
        self.assertEqual(result.returncode, 0, f"[update-installs-minisign] {result.stderr}")
        log = self.log.read_text()
        self.assertIn("pacman -S --needed --noconfirm minisign", log,
                      "[update-installs-minisign] sin minisign el actualizador 1.5 no se instala lo que necesita")
        self.assertIn("Firma del manifiesto verificada", result.stdout)

    def test_minisign_install_failure_aborts(self):
        self.pubkey.write_text("clave\n")
        (self.tmp / "bin/minisign").unlink()
        executable(self.tmp / "pacman", "#!/bin/sh\nexit 1\n")
        result = update_utils(f'PUBKEY="$1"; PACMAN="$3"; am_root() {{ return 0; }}; fetch_manifest "$2"',
                              self.pubkey, self.tmp / "manifest", self.tmp / "pacman",
                              env=self.env_without_minisign())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no se pudo instalar minisign", result.stderr)

    def test_parse_manifest(self):
        manifest = self.tmp / "m.json"
        manifest.write_text(
            '{"version": "1.3", "arch": "x86_64", "editions": {"niri": {"file": "churros-utils-niri-1.3.tar.zst", '
            '"sha256": "%s"}}}' % ("b" * 64))
        result = update_utils('parse_manifest "$1" niri', manifest)
        self.assertEqual(result.stdout.strip(), f"1.3|churros-utils-niri-1.3.tar.zst|{'b' * 64}")
        manifest.write_text(manifest.read_text().replace('"x86_64"', '"aarch64"'))
        wrong_arch = update_utils('parse_manifest "$1" niri', manifest)
        self.assertNotEqual(wrong_arch.returncode, 0)
        self.assertIn("arquitectura inválida", wrong_arch.stderr)
        manifest.write_text('{"version": "1.3", "arch": "x86_64", "file": "../../etc/x.tar.zst", "sha256": "%s"}' % ("b" * 64))
        self.assertNotEqual(update_utils('parse_manifest "$1" niri', manifest).returncode, 0)


class UpdateTimerOnlyNotifies(unittest.TestCase):
    """El timer de escritorio (usuario) comprueba y avisa; nunca instala (#142)."""

    def run_auto(self, system: str, flatpak: str, version: str):
        tmp = Path(tempfile.mkdtemp(prefix="churros-auto-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        log = tmp / "log"
        log.write_text("")
        executable(tmp / "bin/checkupdates", f"#!/bin/sh\nprintf '{system}'\n")
        executable(tmp / "bin/flatpak", f"#!/bin/sh\nprintf '{flatpak}'\n")
        executable(tmp / "bin/curl", f"#!/bin/sh\necho '{{\"version\": \"{version}\"}}'\n")
        executable(tmp / "bin/notify-send", f'#!/bin/sh\necho "NOTIFY $*" >> "{log}"\n')
        executable(tmp / "bin/churros-pkexec", f'#!/bin/sh\necho "PKEXEC $*" >> "{log}"\n')
        executable(tmp / "bin/id", "#!/bin/sh\necho 1000\n")
        result = subprocess.run(["bash", str(OVERLAY / "usr/local/bin/churros-update-auto")],
                                capture_output=True, text=True,
                                env={**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
                                     "CHURROS_VERSION_FILE": str(OVERLAY / "etc/churros-version")})
        return result, log.read_text()

    def test_pending_updates_are_announced_not_installed(self):
        result, log = self.run_auto("linux 1 -> 2\nmesa 1 -> 2\n", "org.app.One\n", "9.9")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("PKEXEC", log, "[timer-only-notifies] el timer de usuario no puede instalar nada")
        self.assertIn("Hay actualizaciones", log, "[timer-only-notifies] tenía que avisar de lo pendiente")
        self.assertNotIn("Fallo en la actualización", log, "[timer-only-notifies] aviso de fallo falso")
        self.assertIn("2 del sistema", log)
        self.assertIn("Ajustes > Actualizaciones", log)

    def test_nothing_pending_means_no_notification(self):
        installed = (OVERLAY / "etc/churros-version").read_text().strip()
        result, log = self.run_auto("", "", installed)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, "", "sin novedades no se molesta a nadie")


    def test_an_older_manifest_is_not_announced(self):
        # Una copia vieja de updates.json (caché o réplica) no es una actualización.
        result, log = self.run_auto("", "", "0.1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log, "", "[updates-only-newer] avisa de una versión más antigua que la instalada")

class UpdatesOnlyNewerAndSnapshot(unittest.TestCase):
    """Solo se instala una versión más nueva, y con snapshot btrfs antes del bundle."""

    MANIFEST = '{"version": "%s", "arch": "x86_64", "file": "churros-utils-%s-x86_64.tar.zst", "sha256": "%s"}\n'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-newer-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.version_file = self.tmp / "churros-version"
        self.version_file.write_text("1.5.6\n")
        self.snapshot = executable(self.tmp / "churros-snapshot", f'#!/bin/sh\necho "snapshot $*" >> "{self.log}"\n')

    def main(self, served: str):
        manifest = self.tmp / "served.json"
        manifest.write_text(self.MANIFEST % (served, served, "a" * 64))
        # Todo lo de red y reparación, fuera: aquí solo cuenta qué decide main.
        script = (f'VERSION_FILE="{self.version_file}"; UPDATE_ARCH=x86_64; '
                  'clear_stale_pacman_lock() { :; }; repair_cachyos_packages() { :; }; check_boot_images() { :; }; '
                  'detect_edition() { echo niri; }; '
                  f'fetch_manifest() {{ cp "{manifest}" "$1"; }}; '
                  f'download() {{ echo "download $2" >> "{self.log}"; return 1; }}; main')
        return update_utils(script)

    def test_an_older_version_is_not_installed(self):
        result = self.main("1.5.5")
        self.assertNotIn("download", self.log.read_text(),
                         "[updates-only-newer] un updates.json viejo (con su firma válida) bajaba de versión")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("más antigua", result.stdout)

    def test_a_newer_version_is_downloaded(self):
        result = self.main("1.5.10")
        self.assertIn("download", self.log.read_text(), "1.5.10 es más nueva que 1.5.6 (no es orden de texto)")
        self.assertNotEqual(result.returncode, 0, "el download falso falla: main tiene que pararse ahí")

    def test_version_order(self):
        cases = {("1.5.6", "1.5.5"): True, ("1.5.5", "1.5.6"): False, ("1.5.10", "1.5.9"): True,
                 ("1.5.1", "1.5"): True, ("1.5", "1.5.1"): False, ("1.6", "1.5.9"): True, ("1.5.6", "1.5.6"): False}
        for (a, b), newer in cases.items():
            got = update_utils('version_gt "$1" "$2"', a, b).returncode == 0
            self.assertEqual(got, newer, f"[updates-only-newer] version_gt {a} {b}")

    def snapshot_before(self, fstype: str):
        script = (f'SNAPSHOT_BIN="{self.snapshot}"; LIVE_MARKER="{self.tmp}/no-live"; am_root() {{ return 0; }}; '
                  f'findmnt() {{ echo {fstype}; }}; snapshot_before_bundle 1.5.7')
        return update_utils(script)

    def test_btrfs_gets_a_snapshot_before_the_bundle(self):
        result = self.snapshot_before("btrfs")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines(), ["snapshot create churros-utils-pre-1.5.7"],
                         "[snapshot-before-bundle] sin snapshot no hay a dónde volver si el bundle rompe algo")

    def test_a_failed_snapshot_installs_nothing(self):
        executable(self.snapshot, "#!/bin/sh\nexit 1\n")
        result = self.snapshot_before("btrfs")
        self.assertNotEqual(result.returncode, 0, "[snapshot-before-bundle] siguió sin punto de vuelta")
        self.assertIn("no se ha instalado nada", result.stderr)

    def test_ext4_goes_on_without_snapshot(self):
        result = self.snapshot_before("ext4")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text(), "", "en ext4 no hay snapshots que crear")
        self.assertIn("no es btrfs", result.stdout)

    def test_main_snapshots_right_before_installing(self):
        main = (OVERLAY / "usr/bin/churros-update-utils").read_text()
        main = main[main.index("\nmain() {"):]
        self.assertIn('\n    snapshot_before_bundle "$version"\n', main,
                      "[snapshot-before-bundle] main no crea el snapshot")
        self.assertLess(main.index("validate_stage_arch"), main.index("snapshot_before_bundle"),
                        "el snapshot va después de validar: un bundle inválido no deja snapshots de sobra")
        self.assertLess(main.index("snapshot_before_bundle"), main.index("install_stage \"$STAGE\""),
                        "[snapshot-before-bundle] el snapshot tiene que ir antes de instalar")

class PackageManagerPrivileges(unittest.TestCase):
    """Un gestor de paquetes nunca debe quedar disponible sin autenticación."""

    def test_pacman_requires_authentication(self):
        sudoers = (OVERLAY / "etc/sudoers.d/99-churros-pacman").read_text()
        self.assertNotIn("NOPASSWD", "\n".join(
            line for line in sudoers.splitlines() if not line.lstrip().startswith("#")))
        self.assertIn("PASSWD: /usr/bin/pacman", sudoers)

    def test_tour_does_not_bypass_authentication_or_pgp(self):
        source = (ROOT / "rust/churros-tour/src/installation.rs").read_text()
        self.assertNotIn("sudo -n pacman", source)
        self.assertNotIn("--skippgpcheck", source)


@unittest.skipUnless(HAS_ZSTD, "zstd no está instalado")
class ReleaseBundleFits(unittest.TestCase):
    """El bundle real de build-churros-release.sh cabe en la lista del updater."""

    def test_bundle_members_are_allowed(self):
        tmp = Path(tempfile.mkdtemp(prefix="churros-release-test-"))
        self.addCleanup(shutil.rmtree, tmp, True)
        project = tmp / "project"
        (project / "scripts").mkdir(parents=True)
        shutil.copy2(RELEASE_SCRIPT, project / "scripts")
        shutil.copy2(ROOT / "scripts/deploy-rust-assets.sh", project / "scripts")
        shutil.copy2(ROOT / "VERSION", project)
        (project / "archiso").mkdir()
        (project / "archiso/airootfs").symlink_to(OVERLAY)
        for manifest in ROOT.glob("rust/*/Cargo.toml"):
            target = project / manifest.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(manifest, target)
        shutil.copy2(ROOT / "rust/Cargo.toml", project / "rust/Cargo.toml")
        # cargo falso: deja un ejecutable por crate desplegable, como haría
        # `cargo build --release`, sin compilar nada. Un ELF de verdad del
        # equipo (/bin/true): el builder comprueba la arquitectura (#311).
        executable(tmp / "bin/cargo", '''#!/usr/bin/env bash
set -e
while [ "$#" -gt 0 ]; do
    [ "$1" = --manifest-path ] && manifest="$2"
    shift
done
rust_dir="$(dirname "$manifest")"
mkdir -p "$rust_dir/target/release"
for toml in "$rust_dir"/*/Cargo.toml; do
    grep -q '^deploy = true$' "$toml" || continue
    name="$(sed -n 's/^name = "\\(.*\\)"/\\1/p' "$toml" | head -1)"
    cp /bin/true "$rust_dir/target/release/$name"
    chmod 755 "$rust_dir/target/release/$name"
done
''')
        executable(tmp / "bin/minisign", '''#!/usr/bin/env bash
set -e
while [ "$#" -gt 0 ]; do
    case "$1" in
        -x) signature="$2"; shift 2 ;;
        *) shift ;;
    esac
done
printf 'firma de prueba\n' > "$signature"
''')
        secret_key = tmp / "release-test.key"
        secret_key.write_text("clave privada de prueba\n")
        env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}",
               "CHURROS_RELEASE_SECRET_KEY": str(secret_key)}
        build = subprocess.run(["bash", str(project / "scripts/build-churros-release.sh")],
                               capture_output=True, text=True, env=env)
        self.assertEqual(build.returncode, 0, build.stdout + build.stderr)
        bundles = sorted((project / "release").rglob("*.tar.zst"))
        self.assertTrue(bundles, "build-churros-release.sh no generó ningún bundle")
        listing = subprocess.run(["tar", "--zstd", "-tf", str(bundles[0])],
                                 capture_output=True, text=True, check=True).stdout.split()
        for expected in ("usr/bin/churros-settings", "usr/bin/churros-update-utils",
                         "usr/local/bin/churros-write-root-config",
                         "usr/share/churros/scripts/edition-session.sh", "etc/churros-version"):
            self.assertIn(expected, listing)
        for bundle in bundles:
            with self.subTest(bundle=bundle.name):
                result = update_utils('validate_tarball "$1"', bundle)
                self.assertEqual(result.returncode, 0, result.stderr)


# --------------------------------------------------- churros-write-root-config


def world_traversable(path: Path) -> bool:
    return all(mode(p) & 0o001 for p in [path, *path.parents])


@unittest.skipUnless(world_traversable(Path(tempfile.gettempdir())),
                     "el directorio temporal no es accesible para otros usuarios")
class SnapshotRestore(unittest.TestCase):
    """churros-snapshot restore desde la ISO, sobre un volumen btrfs falso."""

    def test_restore_swaps_root_and_home_and_drops_the_pacman_lock(self):
        tmp = Path(tempfile.mkdtemp(prefix="churros-restore-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        top = tmp / "top"
        snap = top / "@snapshots/20261115-052257"
        (snap / "root/var/lib/pacman").mkdir(parents=True)
        (snap / "root/var/lib/pacman/db.lck").write_text("")
        (snap / "root/version").write_text("antes\n")
        (snap / "home").mkdir()
        (snap / "home/nota").write_text("antes\n")
        (top / "@").mkdir()
        (top / "@/version").write_text("roto\n")
        (top / "@home").mkdir()
        bin_dir = tmp / "bin"
        # mount -o subvolid=5 DEV DIR: el punto de montaje pasa a ser el volumen falso.
        executable(bin_dir / "mount", f'#!/bin/sh\nrmdir "$4" && ln -s "{top}" "$4"\n')
        executable(bin_dir / "mountpoint", "#!/bin/sh\nexit 1\n")
        executable(bin_dir / "btrfs", '#!/bin/sh\n[ "$1 $2" = "subvol snapshot" ] && cp -a "$3" "$4"\n')
        result = subprocess.run(["bash", str(OVERLAY / "usr/local/bin/churros-snapshot"), "restore", "-d", "/dev/falso3",
                                 "20261115-052257"], capture_output=True, text=True,
                                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((top / "@/version").read_text(), "antes\n")
        self.assertEqual((top / "@home/nota").read_text(), "antes\n")
        broken = [p.name for p in top.iterdir() if p.name.startswith("@broken-")]
        self.assertEqual(len(broken), 1, "el estado roto queda resguardado")
        self.assertFalse((top / "@/var/lib/pacman/db.lck").exists(),
                         "[restore-drops-lock] el snapshot del hook lleva el candado de pacman: tras restaurar, pacman no funcionaría")
        self.assertTrue((snap / "root/var/lib/pacman/db.lck").exists(), "el snapshot original no se toca")


class GuidedRestore(unittest.TestCase):
    """`churros-snapshot restore` sin argumentos, desde la ISO (#327)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-guided-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.top = self.tmp / "top"
        (self.top / "@").mkdir(parents=True)
        (self.top / "@/version").write_text("roto\n")
        (self.top / "@home").mkdir()
        for stamp, reason, version in (("20261101-100000", "manual", "uno"), ("20261102-100000", "pacman-pre", "dos")):
            d = self.top / "@snapshots" / stamp
            (d / "root").mkdir(parents=True)
            (d / "root/version").write_text(version + "\n")
            (d / "home").mkdir()
            (d / "meta.txt").write_text(f"stamp={stamp}\ndate=2026-11-0{stamp[7]} 10:00:00\nreason={reason}\nkernel=7.3.3\n")
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.bin = self.tmp / "bin"
        executable(self.bin / "lsblk", '#!/bin/sh\ncase "$*" in\n'
                   '    "-rno TYPE "*) echo part ;;\n'
                   '    *) printf "/dev/falso1 vfat\\n/dev/falso2 crypto_LUKS\\n/dev/falso3 btrfs\\n" ;;\nesac\n')
        executable(self.bin / "findmnt", '#!/bin/sh\ncase "$*" in *FSTYPE*) echo overlay ;; *) echo airootfs ;; esac\n')
        executable(self.bin / "mount", f'#!/bin/sh\necho "mount $2 $3" >> "{self.log}"\nrmdir "$4" && ln -s "{self.top}" "$4"\n')
        executable(self.bin / "umount", "#!/bin/sh\nexit 0\n")
        executable(self.bin / "mountpoint", "#!/bin/sh\nexit 1\n")
        executable(self.bin / "btrfs", '#!/bin/sh\n[ "$1 $2" = "subvol snapshot" ] && cp -a "$3" "$4"\n')
        executable(self.bin / "cryptsetup", f'#!/bin/sh\necho "cryptsetup $*" >> "{self.log}"\n')
        executable(self.bin / "id", "#!/bin/sh\necho 0\n")

    def guided(self, answers: str):
        return subprocess.run(["bash", str(OVERLAY / "usr/local/bin/churros-snapshot"), "restore"],
                              input=answers, capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"})

    def broken(self):
        return [p.name for p in self.top.iterdir() if p.name.startswith("@broken-")]

    def test_guided_restore_asks_then_restores_and_checks(self):
        (self.top / "@home/nota").write_text("de hoy\n")
        result = self.guided("n\n2\n\nRESTAURAR\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.top / "@/version").read_text(), "dos\n",
                         "[guided-restore] restaura el snapshot elegido")
        self.assertEqual(len(self.broken()), 1, "[guided-restore] el estado roto queda en @broken-*")
        self.assertIn("pacman-pre", result.stderr, "enseña el motivo de cada snapshot")
        self.assertIn("/home NO se toca", result.stderr, "[restore-home-choice] dice qué subvolúmenes mueve")
        self.assertEqual((self.top / "@home/nota").read_text(), "de hoy\n",
                         "[restore-home-choice] sin decir que sí, los archivos de /home se quedan como están")
        self.assertFalse(any(p.name.startswith("@home.broken") for p in self.top.iterdir()))
        self.assertIn("comprobado", result.stderr, "[guided-restore] comprueba el resultado en el disco")
        mounts = [l for l in self.log.read_text().splitlines() if l.startswith("mount")]
        self.assertIn("mount ro,subvolid=5", mounts[0], "[guided-restore] mira el disco en solo lectura antes de confirmar")

    def test_guided_restore_can_bring_home_back_too(self):
        (self.top / "@home/nota").write_text("de hoy\n")
        result = self.guided("n\n2\ns\nRESTAURAR\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("/home TAMBIÉN vuelve", result.stderr)
        homes = [p for p in self.top.iterdir() if p.name.startswith("@home.broken")]
        self.assertEqual(len(homes), 1, "[restore-home-choice] el /home de antes queda en @home.broken-*")
        self.assertEqual((homes[0] / "nota").read_text(), "de hoy\n", "y no se pierde nada de él")

    def test_anything_but_restaurar_touches_nothing(self):
        result = self.guided("n\n1\ns\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.top / "@/version").read_text(), "roto\n",
                         "[guided-restore] sin escribir RESTAURAR no se toca nada")
        self.assertEqual(self.broken(), [])
        self.assertIn("cancelado", result.stderr)
        self.assertTrue(all("ro," in l for l in self.log.read_text().splitlines() if l.startswith("mount")),
                        "[guided-restore] antes de confirmar todo se monta en solo lectura")

    def test_an_encrypted_disk_is_opened_only_if_asked(self):
        self.guided("s\n1\nno\n")
        self.assertIn("cryptsetup open /dev/falso2 churros-falso2", self.log.read_text(),
                      "[guided-restore] un disco cifrado se abre (sin borrar nada) para encontrar el sistema")
        self.log.write_text("")
        self.guided("n\n1\nno\n")
        self.assertNotIn("cryptsetup", self.log.read_text(), "sin el sí del usuario no se abre")

    def test_no_installed_system_is_explained(self):
        shutil.rmtree(self.top / "@snapshots")
        result = self.guided("n\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no se encontró ningún ChurrOS", result.stderr)


class SnapshotRetention(unittest.TestCase):
    """La retención solo borra snapshots automáticos (#329) y un fallo se explica (#332)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-retention-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.top = self.tmp / "top"
        (self.top / "@").mkdir(parents=True)
        (self.top / "@snapshots").mkdir()
        self.bin = self.tmp / "bin"
        executable(self.bin / "findmnt", '#!/bin/sh\ncase "$*" in *FSTYPE*) echo btrfs ;; *) echo /dev/falso3 ;; esac\n')
        executable(self.bin / "mount", f'#!/bin/sh\nrmdir "$4" && ln -s "{self.top}" "$4"\n')
        executable(self.bin / "mountpoint", "#!/bin/sh\nexit 1\n")
        self.btrfs(ok=True)

    def btrfs(self, ok: bool):
        snapshot = 'cp -a "$4" "$5"' if ok else 'echo "ERROR: cannot snapshot: No space left on device" >&2; exit 1'
        executable(self.bin / "btrfs", "#!/bin/sh\ncase \"$1 $2\" in\n"
                   f"    \"subvol snapshot\") {snapshot} ;;\n"
                   "    \"subvol delete\") rm -rf \"$3\" ;;\n"
                   "    \"subvol create\") mkdir -p \"$3\" ;;\n"
                   "    \"filesystem du\") printf 'Total Exclusive Set-shared Filename\\n4096 104857600 0 %s\\n' \"$5\" ;;\nesac\n")

    def snapshot(self, stamp: str, reason: str):
        d = self.top / "@snapshots" / stamp
        (d / "root").mkdir(parents=True)
        (d / "meta.txt").write_text(f"stamp={stamp}\nreason={reason}\n")

    def run_snapshot(self, *args):
        return subprocess.run(["bash", str(OVERLAY / "usr/local/bin/churros-snapshot"), *args],
                              capture_output=True, text=True,
                              env={**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}"})

    def left(self):
        return sorted(p.name for p in (self.top / "@snapshots").iterdir())

    def test_manual_snapshots_survive_the_retention(self):
        self.snapshot("20261101-000000", "manual")
        self.snapshot("20261102-000000", "antes-de-actualizar")
        for day in range(3, 10):
            self.snapshot(f"202611{day:02d}-000000", "pacman-pre")
        self.snapshot("20261110-000000", "churros-utils-pre-1.5.7")
        result = self.run_snapshot("cleanup", "3")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.left()[:2], ["20261101-000000", "20261102-000000"],
                         "[keep-manual-snapshots] la retención borró un snapshot que el usuario creó a propósito")
        self.assertEqual(self.left()[2:], ["20261108-000000", "20261109-000000", "20261110-000000"],
                         "se quedan los 3 automáticos más recientes (pacman y bundle cuentan igual)")
        self.assertIn("2 snapshots manuales se conservan", result.stderr)

    def test_cleanup_dry_run_shows_the_plan_and_deletes_nothing(self):
        self.snapshot("20261101-000000", "manual")
        for day in range(2, 7):
            self.snapshot(f"202611{day:02d}-000000", "pacman-pre")
        before = self.left()
        result = self.run_snapshot("cleanup", "--dry-run", "2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.left(), before, "[cleanup-dry-run] la vista previa no puede borrar nada")
        lines = result.stdout.splitlines()
        drop = [l for l in lines if "BORRARÍA" in l]
        self.assertEqual([l.split()[1] for l in drop], ["20261102-000000", "20261103-000000", "20261104-000000"],
                         "[cleanup-dry-run] tiene que enseñar los automáticos más viejos que borraría")
        self.assertTrue(any("20261101-000000" in l and "manual" in l and "conserva" in l for l in lines),
                        "el manual aparece como conservado")
        self.assertIn("unos 300.0 MiB", result.stdout, "suma solo lo exclusivo de los que borraría")

    def test_cleanup_rejects_a_keep_that_is_not_a_number(self):
        result = self.run_snapshot("cleanup", "--dry-run", "todo")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tiene que ser un número", result.stderr)

    def test_cleanup_dry_run_without_snapshots(self):
        (self.top / "@snapshots").rmdir()
        result = self.run_snapshot("cleanup", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("no hay snapshots", result.stderr)

    def test_a_failed_snapshot_says_there_is_no_way_back(self):
        self.btrfs(ok=False)
        result = self.run_snapshot("create", "pacman-pre")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no hay punto de vuelta", result.stderr,
                      "[snapshot-failure-explained] un snapshot fallido no puede pasar por protección")
        self.assertIn("btrfs filesystem usage", result.stderr, "dice cómo mirar el espacio")
        self.assertEqual(self.left(), [], "sin restos de un snapshot a medias")

    def test_the_hook_warns_when_a_transaction_has_no_snapshot(self):
        hook = (OVERLAY / "etc/pacman.d/hooks/50-churros-snapshot.hook").read_text()
        self.assertIn("NO tiene snapshot previo", hook, "[snapshot-failure-explained] el hook no avisa claro")

class RestoreWithoutHome(unittest.TestCase):
    """restore -d DEV --sin-home STAMP vuelve el sistema atrás y deja /home (#333)."""

    def test_restore_can_leave_home_alone(self):
        tmp = Path(tempfile.mkdtemp(prefix="churros-restore-home-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        top = tmp / "top"
        snap = top / "@snapshots/20261115-052257"
        (snap / "root").mkdir(parents=True)
        (snap / "root/version").write_text("antes\n")
        (snap / "home").mkdir()
        (snap / "home/nota").write_text("antes\n")
        (top / "@").mkdir()
        (top / "@/version").write_text("roto\n")
        (top / "@home").mkdir()
        (top / "@home/nota").write_text("de hoy\n")
        bin_dir = tmp / "bin"
        executable(bin_dir / "mount", f'#!/bin/sh\nrmdir "$4" && ln -s "{top}" "$4"\n')
        executable(bin_dir / "mountpoint", "#!/bin/sh\nexit 1\n")
        executable(bin_dir / "btrfs", '#!/bin/sh\n[ "$1 $2" = "subvol snapshot" ] && cp -a "$3" "$4"\n')
        result = subprocess.run(["bash", str(OVERLAY / "usr/local/bin/churros-snapshot"), "restore", "-d", "/dev/falso3",
                                 "--sin-home", "20261115-052257"], capture_output=True, text=True,
                                env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((top / "@/version").read_text(), "antes\n", "el sistema vuelve al snapshot")
        self.assertEqual((top / "@home/nota").read_text(), "de hoy\n",
                         "[restore-home-choice] --sin-home tiene que dejar /home como está")
        self.assertFalse(any(p.name.startswith("@home.broken") for p in top.iterdir()))
        self.assertIn("/home no se ha tocado", result.stderr)


class StalePacmanLock(unittest.TestCase):
    """Un apagón a mitad de transacción deja db.lck: pacman no lo quita nunca."""

    def run_clear(self, age_vs_boot: int, running: bool = False):
        tmp = Path(tempfile.mkdtemp(prefix="churros-lock-test-"))
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        lock = tmp / "db.lck"
        lock.write_text("")
        boot = 1_700_000_000
        os.utime(lock, (boot + age_vs_boot, boot + age_vs_boot))
        script = (f'PACMAN_LOCK="$1"; am_root() {{ return 0; }}; boot_time() {{ echo {boot}; }}; '
                  f'pacman_running() {{ {"return 0" if running else "return 1"}; }}; clear_stale_pacman_lock')
        result = update_utils(script, lock)
        return result, lock.exists()

    def test_a_lock_from_before_this_boot_is_removed(self):
        result, exists = self.run_clear(-3600)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(exists, "[stale-pacman-lock] tras un apagón, pacman quedaría bloqueado para siempre")
        self.assertIn("candado", result.stdout)

    def test_a_lock_from_this_boot_is_kept(self):
        result, exists = self.run_clear(+60)
        self.assertTrue(exists, "[stale-pacman-lock] puede ser de un pacman de verdad: no se toca")

    def test_a_lock_is_kept_while_pacman_runs(self):
        result, exists = self.run_clear(-3600, running=True)
        self.assertTrue(exists, "[stale-pacman-lock] con un pacman en marcha nunca se quita")

    def test_main_clears_the_lock_before_repairing(self):
        source = (OVERLAY / "usr/bin/churros-update-utils").read_text()
        main = source[source.index("main() {"):]
        self.assertLess(main.index("clear_stale_pacman_lock"), main.index("repair_cachyos_packages"),
                        "[stale-pacman-lock] la reparación necesita pacman libre")


class BootImages(unittest.TestCase):
    """Un apagón durante los hooks de pacman deja un kernel sin arranque (visto en la VM)."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-boot-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.modules = self.tmp / "modules"
        self.boot = self.tmp / "boot"
        self.boot.mkdir()
        for kver, base in (("7.3.4-arch1-2", "linux"), ("7.3.3-1-cachyos", "linux-cachyos")):
            d = self.modules / kver
            d.mkdir(parents=True)
            (d / "pkgbase").write_text(base + "\n")
            (d / "vmlinuz").write_text(f"kernel {kver}\n")
            (d / "modules.dep").write_text("kernel/x.ko:\n")
            (self.boot / f"vmlinuz-{base}").write_text(f"kernel {kver}\n")
            (self.boot / f"initramfs-{base}.img").write_text(f"usr/lib/modules/{kver}/kernel/x.ko\n")
        self.hook = executable(self.tmp / "mkinitcpio-hook", f'#!/bin/sh\necho "hook $1 $(pwd): $(cat | tr "\\n" " ")" >> "{self.log}"\n')
        self.readable = executable(self.tmp / "readable", f'#!/bin/sh\necho readable >> "{self.log}"\n')

    def check(self, hook_ok=True):
        if not hook_ok:
            executable(self.hook, f'#!/bin/sh\necho "hook falla" >> "{self.log}"; exit 1\n')
        script = (f'MODULES_DIR="{self.modules}"; BOOT_DIR="{self.boot}"; MKINITCPIO_HOOK="{self.hook}"; '
                  f'GRUB_READABLE="{self.readable}"; LIVE_MARKER="{self.tmp}/no-live"; am_root() {{ return 0; }}; '
                  f'lsinitcpio() {{ shift; cat "$1"; }}; depmod() {{ echo "depmod $*" >> "{self.log}"; }}; '
                  f'sync() {{ :; }}; check_boot_images')
        return update_utils(script)

    def commands(self):
        return self.log.read_text().splitlines()

    def test_a_healthy_boot_is_left_alone(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [], "[boot-images] con todo en su sitio no se rehace nada")

    def test_a_missing_initramfs_is_rebuilt(self):
        (self.boot / "initramfs-linux.img").unlink()
        (self.modules / "7.3.4-arch1-2/modules.dep").unlink()
        (self.boot / "vmlinuz-linux-cachyos.grub-rewr").write_text("x")
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        rel = str(self.modules / "7.3.4-arch1-2/vmlinuz").lstrip("/")
        self.assertEqual(self.commands(), ["depmod -- 7.3.4-arch1-2", f"hook install /: {rel} ", "readable"],
                         "[boot-images] solo el kernel roto: depmod, el hook de mkinitcpio desde / y GRUB")
        self.assertFalse((self.boot / "vmlinuz-linux-cachyos.grub-rewr").exists(), "sin temporales de make-boot-grub-readable")

    def test_an_initramfs_of_another_kernel_is_rebuilt(self):
        (self.boot / "initramfs-linux.img").write_text("usr/lib/modules/7.3.3-arch1-1/kernel/x.ko\n")
        self.check()
        self.assertTrue(any(c.startswith("hook install") for c in self.commands()),
                        "[boot-images] un initramfs del kernel anterior no arranca el nuevo")

    def test_a_stale_vmlinuz_is_rebuilt(self):
        (self.boot / "vmlinuz-linux").write_text("kernel viejo\n")
        self.check()
        self.assertTrue(any(c.startswith("hook install") for c in self.commands()),
                        "[boot-images] /boot/vmlinuz no es el del paquete")

    def test_missing_module_indexes_are_rebuilt(self):
        (self.modules / "7.3.4-arch1-2/modules.dep").unlink()
        self.check()
        self.assertIn("depmod -- 7.3.4-arch1-2", self.commands(),
                      "[boot-images] sin modules.dep ni mkinitcpio ni udev encuentran los módulos")

    def test_a_failed_rebuild_is_an_error(self):
        (self.boot / "initramfs-linux.img").unlink()
        result = self.check(hook_ok=False)
        self.assertNotEqual(result.returncode, 0, "[boot-images] un initramfs a medias no puede darse por bueno")
        self.assertIn("no reinicies", result.stderr)

    def test_main_checks_the_boot_before_the_bundle(self):
        source = (OVERLAY / "usr/bin/churros-update-utils").read_text()
        main = source[source.index("main() {"):]
        self.assertIn("\n    check_boot_images\n", main, "[boot-images] main tiene que comprobar el arranque")
        self.assertLess(main.index("repair_cachyos_packages"), main.index("check_boot_images"))
        self.assertLess(main.index("check_boot_images"), main.index("fetch_manifest"),
                        "[boot-images] la comprobación del arranque va antes del bundle")


class RepairCachyosPackages(unittest.TestCase):
    """Reparación única de las ISO 1.4/1.5 (pacman, mesa... de CachyOS).

    Un pacman falso hace de sistema Niri 1.5 instalado: lo que lista -Qi
    (con su Packager), lo que hay en cada repositorio (-Sl) y quién usa los
    headers. Registra cada orden que cambia el sistema.
    """

    # nombre -> Packager: lo que instaló la ISO Niri 1.5.
    INSTALLED = {
        "pacman": "CachyOS <admin@cachyos.org>",
        "mesa": "CachyOS <admin@cachyos.org>",
        "archlinux-keyring": "CachyOS <admin@cachyos.org>",
        "pahole": "CachyOS <admin@cachyos.org>",
        "linux-cachyos": "CachyOS <admin@cachyos.org>",
        "linux-cachyos-headers": "CachyOS <admin@cachyos.org>",
        "cachyos-keyring": "CachyOS <admin@cachyos.org>",
        "cachyos-ananicy-rules": "CachyOS <admin@cachyos.org>",
        "firefox": "Jan Alexander Steffens (heftig) <heftig@archlinux.org>",
        "yay": "Unknown Packager",
    }
    REPOS = {
        "core": ["pacman", "archlinux-keyring", "glibc"],
        "extra": ["mesa", "pahole", "firefox"],
        "multilib": ["lib32-mesa"],
        "cachyos": ["linux-cachyos", "linux-cachyos-headers", "cachyos-keyring", "cachyos-ananicy-rules", "mesa", "yay"],
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-repair-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "log"
        self.log.write_text("")
        self.conf = self.tmp / "pacman.conf"
        self.conf.write_text("[options]\n\n[core]\nInclude = /etc/pacman.d/mirrorlist\n\n"
                             "[extra]\nInclude = /etc/pacman.d/mirrorlist\n")
        self.mirrorlist = self.tmp / "cachyos-mirrorlist"
        self.mirrorlist.write_text("Server = https://mirror.cachyos.org/repo/$arch/$repo\n")
        self.keyring = self.tmp / "cachyos.gpg"
        self.keyring.write_text("clave\n")
        self.headers_required_by = "None"
        self.installed = dict(self.INSTALLED)

    def write_fakes(self):
        installed = self.tmp / "installed"
        installed.write_text("".join(f"{name}\t{packager}\n" for name, packager in self.installed.items()))
        repos = self.tmp / "repos"
        repos.write_text("".join(f"{repo} {name} 1.0-1\n" for repo, names in self.REPOS.items() for name in names))
        executable(self.tmp / "pacman", f'''#!/bin/bash
log() {{ echo "pacman $*" >> "{self.log}"; }}
case "$1" in
  -Qi)
    if [ -n "${{2:-}}" ]; then
      grep -q "^$2	" "{installed}" || exit 1
      printf 'Name            : %s\\nRequired By     : %s\\n' "$2" "{self.headers_required_by}"
    else
      # Como el de Arch: -Qi lee cada desc y avisa del campo que no conoce.
      if grep -rqs '%INSTALLED_DB%' "{self.tmp / 'local'}"; then echo "warning: zstd: unknown key '%INSTALLED_DB%' in local database" >&2; fi
      while IFS="	" read -r n p; do printf 'Name            : %s\\nVersion         : 1.0-1\\nPackager        : %s\\n\\n' "$n" "$p"; done < "{installed}"
      # Como un sistema real (~900 paquetes): mucha salida después, para que
      # un `pacman | grep -q` con pipefail reciba SIGPIPE.
      yes 'Description     : relleno' | head -n 200000
      yes 'warning: relleno' | head -n 20000 >&2
    fi ;;
  -Q) grep -q "^$2	" "{installed}" ;;
  -Qq) cut -f1 "{installed}"; yes 'relleno-paquete' | head -n 200000 ;;
  -Sl) cat "{repos}" ;;
  *) log "$@" ;;
esac
''')
        executable(self.tmp / "pacman-key", f'#!/bin/sh\necho "pacman-key $*" >> "{self.log}"\n')

    def make_local_db(self):
        """Base de datos local: dos paquetes con el campo del pacman de CachyOS."""
        local = self.tmp / "local"
        for name, extra in (("zstd-1.5.7-3", "%INSTALLED_DB%\ncore\n\n"), ("mesa-1:26.2.7-1", "%INSTALLED_DB%\nextra\n\n"),
                            ("firefox-160.0-1", "")):
            (local / name).mkdir(parents=True)
            (local / name / "desc").write_text(
                f"%NAME%\n{name.split('-')[0]}\n\n{extra}%VERSION%\n1.0-1\n\n%PACKAGER%\nArch\n\n")
            (local / name / "desc").chmod(0o644)
        return local

    def live_units(self):
        """Unidades del Live que Calamares no pudo enmascarar (1.4/1.5 instaladas)."""
        systemd = self.tmp / "systemd"
        (systemd / "multi-user.target.wants").mkdir(parents=True, exist_ok=True)
        for unit in ("pacman-init.service", "etc-pacman.d-gnupg.mount", "choose-mirror.service", "livecd-talk.service"):
            (systemd / unit).write_text("[Unit]\n")
        for unit in ("pacman-init.service", "choose-mirror.service", "livecd-talk.service"):
            (systemd / "multi-user.target.wants" / unit).symlink_to(f"../{unit}")
        (systemd / "ModemManager.service").write_text("[Unit]\n")
        return systemd

    def repair(self, free_mb=20000, live=False, mounted=True, umount_ok=True):
        self.write_fakes()
        marker = self.tmp / ("archiso" if live else "no-live")
        if live:
            marker.mkdir()
        script = (
            'PACMAN="$1"; PACMAN_KEY="$2"; PACMAN_CONF="$3"; CACHYOS_MIRRORLIST="$4"; '
            'CACHYOS_KEYRING="$5"; LIVE_MARKER="$6"; LOCAL_DB="$7"; SYSTEMD_DIR="$8"; GNUPG_DIR=/gnupg; '
            f'VOLATILE_JOURNAL="{self.tmp / "volatile-storage.conf"}"; journalctl() {{ log "journalctl $*"; }}; '
            'LOGF="$9"; am_root() { return 0; }; log() { echo "$*" >> "$LOGF"; }; '
            'systemctl() { log "systemctl $*"; }; gpgconf() { log "gpgconf $*"; }; '
            f'mountpoint() {{ log "mountpoint $*"; {"return 0" if mounted else "return 1"}; }}; '
            f'umount() {{ log "umount $*"; {"return 0" if umount_ok else "return 1"}; }}; '
            f'free_mb() {{ echo {free_mb}; }}; repair_cachyos_packages'
        )
        return update_utils(script, self.tmp / "pacman", self.tmp / "pacman-key", self.conf,
                            self.mirrorlist, self.keyring, marker, self.tmp / "local", self.tmp / "systemd", self.log)

    def commands(self):
        return self.log.read_text().splitlines()

    def test_niri_15_is_repaired_in_one_transaction(self):
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        # [cachyos] al final y su clave, antes de sincronizar.
        self.assertEqual(commands[0], "pacman-key --populate cachyos", commands)
        conf = self.conf.read_text()
        self.assertTrue(conf.rstrip().endswith(f"[cachyos]\nInclude = {self.mirrorlist}"),
                        "[repair-cachyos-repo] [cachyos] tiene que quedar al final de pacman.conf")
        self.assertEqual(commands[1], "pacman -Sy --noconfirm")
        # Headers sin DKMS: fuera, antes de la transacción grande.
        self.assertEqual(commands[2], "pacman -Rs --noconfirm linux-cachyos-headers",
                         "[repair-drops-headers] los headers sin uso bloquearían pacman -Syu")
        # Una sola -Su con cada paquete de CachyOS que Arch tiene, desde Arch.
        su = [c for c in commands if c.startswith("pacman -Su")]
        self.assertEqual(len(su), 1, commands)
        targets = set(su[0].split()[3:])
        self.assertEqual(targets, {"core/pacman", "core/archlinux-keyring", "extra/mesa", "extra/pahole"},
                         "[repair-targets] solo lo de CachyOS que Arch también tiene, por su repositorio de Arch")
        self.assertIn("Reinicia", result.stdout)

    def test_the_cachyos_pacman_db_key_is_forgotten(self):
        local = self.make_local_db()
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        for desc in local.glob("*/desc"):
            text = desc.read_text()
            self.assertNotIn("%INSTALLED_DB%", text,
                             "[repair-forgets-db-key] el pacman de Arch avisaría en cada orden por este campo")
            self.assertIn("%NAME%", text)
            self.assertIn("%VERSION%\n1.0-1\n\n%PACKAGER%", text, "el resto de la entrada no se toca")
            self.assertEqual(mode(desc), 0o644)
        self.assertEqual(sorted(p.name for p in local.iterdir()), ["firefox-160.0-1", "mesa-1:26.2.7-1", "zstd-1.5.7-3"],
                         "sin temporales")

    def test_the_live_keyring_tmpfs_goes_away_before_syncing(self):
        systemd = self.live_units()
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        order = [c for c in commands if c.split()[0] in ("umount", "pacman-key", "pacman") and "-Su" not in c]
        self.assertEqual(order[:4], ["umount /gnupg", "pacman-key --init", "pacman-key --populate", "pacman-key --populate cachyos"],
                         f"[repair-live-keyring] el llavero del disco, antes de nada: {commands}")
        self.assertLess(commands.index("pacman-key --populate"), commands.index("pacman -Sy --noconfirm"))
        self.assertLess(commands.index("systemctl stop *@gnupg.socket *@gnupg.service"), commands.index("umount /gnupg"),
                        "[repair-live-keyring] los sockets de gpg de systemd dejan el tmpfs ocupado: hay que pararlos antes")
        self.assertLess(commands.index("systemctl daemon-reload"), commands.index("systemctl start sockets.target"),
                        "los sockets de gpg vuelven, ya sobre el llavero del disco")
        left = sorted(str(p.relative_to(systemd)) for p in systemd.rglob("*") if p.is_file() or p.is_symlink())
        self.assertEqual(left, ["ModemManager.service"],
                         "[repair-live-keyring] pacman-init y compañía siguen: el tmpfs vuelve en el próximo arranque")
        self.assertIn("systemctl daemon-reload", commands)

    def test_the_volatile_journal_goes_away(self):
        volatile = self.tmp / "volatile-storage.conf"
        volatile.write_text("[Journal]\nStorage=volatile\n")
        self.installed = {"firefox": self.INSTALLED["firefox"]}
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(volatile.exists(), "[repair-volatile-journal] el registro se seguiría perdiendo en cada reinicio")
        commands = self.commands()
        self.assertLess(commands.index("systemctl restart systemd-journald.service"), commands.index("journalctl --flush"))

    def test_the_live_keyring_is_left_alone_if_it_cannot_be_unmounted(self):
        systemd = self.live_units()
        result = self.repair(umount_ok=False)
        self.assertNotEqual(result.returncode, 0, "[repair-live-keyring] siguió sin poder desmontar el llavero")
        self.assertIn("no se ha cambiado nada", result.stderr)
        self.assertTrue((systemd / "pacman-init.service").exists(), "[repair-live-keyring] se quitó a medias")
        self.assertFalse([c for c in self.commands() if c.startswith(("pacman-key", "pacman -"))],
                         "[repair-live-keyring] siguió sin poder desmontar el llavero")

    def test_headers_in_use_are_kept_with_cachyos_pahole(self):
        self.headers_required_by = "nvidia-open-dkms"
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        commands = self.commands()
        self.assertFalse([c for c in commands if c.startswith("pacman -R")],
                         "[repair-keeps-dkms-headers] con un DKMS los headers se quedan")
        su = next(c for c in commands if c.startswith("pacman -Su"))
        self.assertNotIn("extra/pahole", su.split(),
                         "[repair-keeps-dkms-headers] el pahole de Arch rompe la dependencia de los headers de CachyOS")
        self.assertIn("AVISO", result.stdout)

    def test_an_installed_dkms_keeps_the_headers(self):
        """Required By vacío, pero hay un *-dkms instalado entre ~200 000 líneas."""
        self.installed["v4l2loopback-dkms"] = "Arch"
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse([c for c in self.commands() if c.startswith("pacman -R")],
                         "[repair-keeps-dkms-headers] había un DKMS instalado y se quitaron los headers")

    def test_xfce_without_cachyos_kernel_does_not_get_the_repo(self):
        for name in ("linux-cachyos", "linux-cachyos-headers", "cachyos-keyring", "cachyos-ananicy-rules", "pahole"):
            del self.installed[name]
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("[cachyos]", self.conf.read_text(), "XFCE 1.4/1.5 lleva el linux de Arch")
        self.assertFalse([c for c in self.commands() if "pacman-key" in c])
        su = next(c for c in self.commands() if c.startswith("pacman -Su"))
        self.assertEqual(set(su.split()[3:]), {"core/pacman", "core/archlinux-keyring", "extra/mesa"})

    def test_nothing_to_do_does_not_touch_the_system(self):
        self.installed = {"pacman": "Pierre Schmitz <pierre@archlinux.org>",
                          "linux-cachyos": "CachyOS <admin@cachyos.org>",
                          "cachyos-keyring": "CachyOS <admin@cachyos.org>"}
        self.conf.write_text(self.conf.read_text() + "\n[cachyos]\nInclude = /etc/pacman.d/cachyos-mirrorlist\n")
        result = self.repair()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commands(), [], "[repair-idempotent] un sistema sano no se toca")

    def test_second_run_does_not_add_the_repo_twice(self):
        self.repair()
        self.repair()
        self.assertEqual(self.conf.read_text().count("[cachyos]"), 1)

    def test_main_repairs_before_installing_the_bundle(self):
        """Las utilidades nuevas se compilan contra el Arch de hoy: primero el sistema sano."""
        source = UPDATE_UTILS.read_text()
        main = source[source.index("\nmain() {"):].splitlines()
        calls = [i for i, line in enumerate(main) if line.strip() == "repair_cachyos_packages"]
        installs = [i for i, line in enumerate(main) if line.strip().startswith("install_stage ")]
        self.assertTrue(calls, "[repair-before-bundle] main no llama a repair_cachyos_packages")
        self.assertTrue(installs, "main sin install_stage")
        self.assertLess(calls[0], installs[0],
                        "[repair-before-bundle] la reparación tiene que ir antes de instalar el bundle")

    def test_live_and_low_space_are_refused_before_touching_anything(self):
        result = self.repair(live=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.commands(), [], "en el Live no hay nada que reparar")
        result = self.repair(free_mb=200)
        self.assertNotEqual(result.returncode, 0, "[repair-free-space] siguió adelante sin espacio libre")
        self.assertIn("libera espacio", result.stderr)
        self.assertEqual(self.commands(), [], "[repair-free-space] sin espacio no se toca nada")
        self.assertNotIn("[cachyos]", self.conf.read_text())


class WriteRootConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-wrc-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tmp.chmod(0o755)
        self.etc = self.tmp / "etc"
        (self.etc / "greetd").mkdir(parents=True)
        (self.etc / "greetd/config.toml").write_text(
            GREETER + '\n[initial_session]\ncommand = "agreety"\nuser = "otro"\n')
        shutil.copy2(OVERLAY / "etc/greetd/regreet.toml", self.etc / "greetd/regreet.toml")
        shutil.copy2(OVERLAY / "etc/greetd/regreet.css", self.etc / "greetd/regreet.css")
        self.set_edition("niri")
        self.wallpapers = self.tmp / "usr/share/churros/wallpapers"
        self.wallpapers.mkdir(parents=True)
        for name in ("fondo.png", 'con "comillas" \\ y espacios.png'):
            (self.wallpapers / name).write_bytes(b"png")
            (self.wallpapers / name).chmod(0o644)
        (self.wallpapers / "secreto.png").write_bytes(b"png")
        (self.wallpapers / "secreto.png").chmod(0o600)
        (self.wallpapers / "fuera.png").symlink_to(self.tmp / "home/ana/foto.png")
        (self.tmp / "home/ana").mkdir(parents=True)
        (self.tmp / "home/ana/foto.png").write_bytes(b"png")
        for path in self.tmp.rglob("*"):
            if path.is_dir():
                path.chmod(0o755)

        lib = EDITION_LIB.read_text().replace("/etc/churros-edition", str(self.etc / "churros-edition"))
        (self.tmp / "lib").mkdir()
        (self.tmp / "lib/edition-session.sh").write_text(lib)
        helper = WRITE_ROOT_CONFIG.read_text()
        helper = helper.replace("/usr/share/churros/scripts/edition-session.sh",
                                str(self.tmp / "lib/edition-session.sh"))
        helper = helper.replace("/etc/greetd", str(self.etc / "greetd"))
        helper = helper.replace("/etc/lightdm", str(self.etc / "lightdm"))
        helper = helper.replace("    /usr/share/", f"    {self.tmp}/usr/share/")
        self.helper = executable(self.tmp / "bin/churros-write-root-config", helper)
        executable(self.tmp / "bin/getent",
                   '#!/bin/sh\n[ "$1 $2" = "passwd 1000" ] && echo "ana:x:1000:1000:Ana:/home/ana:/bin/zsh"\n')
        self.env = {**os.environ, "PATH": f"{self.tmp / 'bin'}:{os.environ['PATH']}",
                    "PKEXEC_UID": "1000"}

    def set_edition(self, edition):
        (self.etc / "churros-edition").write_text(edition + "\n")

    def run_helper(self, *args, env=None):
        return subprocess.run([str(self.helper), *args], capture_output=True,
                              env=env or self.env)

    def greetd(self) -> str:
        return (self.etc / "greetd/config.toml").read_text()

    def regreet(self) -> dict:
        self.assertIsNotNone(tomllib, "hace falta Python >= 3.11 (tomllib)")
        with open(self.etc / "greetd/regreet.toml", "rb") as fh:
            return tomllib.load(fh)

    def assertNoTempFiles(self):
        self.assertEqual(list(self.etc.rglob(".churros-cfg.*")), [])

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_greetd_autologin_uses_pkexec_user_and_edition_session(self):
        for edition, session in SESSIONS.items():
            with self.subTest(edition=edition):
                self.set_edition(edition)
                result = self.run_helper("greetd-autologin", "on")
                self.assertEqual(result.returncode, 0, result.stderr)
                config = tomllib.loads(self.greetd())
                self.assertEqual(config["initial_session"], {"command": session, "user": "ana"})
                self.assertEqual(config["default_session"]["user"], "greeter")
        result = self.run_helper("greetd-autologin", "off")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.greetd(), GREETER)
        self.assertNoTempFiles()

    def test_greetd_autologin_refusals(self):
        before = self.greetd()
        self.set_edition("server")
        self.assertNotEqual(self.run_helper("greetd-autologin", "on").returncode, 0)
        self.set_edition("niri")
        env = dict(self.env)
        del env["PKEXEC_UID"]
        self.assertNotEqual(self.run_helper("greetd-autologin", "on", env=env).returncode, 0)
        for uid in ("0", "1000x", "", "2000"):
            with self.subTest(uid=uid):
                result = self.run_helper("greetd-autologin", "on", env={**self.env, "PKEXEC_UID": uid})
                self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.greetd(), before)

    def test_usage_errors(self):
        before = self.greetd()
        for args in ((), ("greetd-autologin",), ("greetd-autologin", "yes"),
                     ("greetd-autologin", "on", "root"), ("/etc/greetd/config.toml",),
                     ("write", "/etc/shadow"), ("regreet-greeting",)):
            with self.subTest(args=args):
                self.assertEqual(self.run_helper(*args).returncode, 2)
        self.assertEqual(self.greetd(), before)

    def test_lightdm_autologin(self):
        self.set_edition("xfce")
        result = self.run_helper("lightdm-autologin", "on")
        self.assertEqual(result.returncode, 0, result.stderr)
        conf = self.etc / "lightdm/lightdm.conf.d/autologin.conf"
        self.assertEqual(conf.read_text(), "[Seat:*]\nautologin-user=ana\n"
                                           "autologin-user-timeout=0\nautologin-session=xfce\n")
        self.assertEqual(mode(conf), 0o644)
        self.assertEqual(self.run_helper("lightdm-autologin", "off").returncode, 0)
        self.assertFalse(conf.exists())

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def css_marked(self) -> dict:
        """{clave: línea} de las líneas de regreet.css marcadas con churros:<clave>."""
        css = (self.etc / "greetd/regreet.css").read_text()
        return {m.group(2): m.group(1) for m in re.finditer(r"^(.*); /\* churros:([a-z-]+) \*/$", css, re.M)}

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_greeter_set(self):
        css_before = (self.etc / "greetd/regreet.css").read_text()
        toml_before = self.regreet()
        self.assertEqual(set(self.css_marked()),
                         {"accent", "picture-opacity", "avatar-image", "avatar-padding"})
        result = self.run_helper("greeter-set", "dim=30", "avatar=off", "accent=#3B82F6", "clock=12",
                                 "seconds=on", "date=off", "clock_size=large")
        self.assertEqual(result.returncode, 0, result.stderr)
        marked = self.css_marked()
        self.assertEqual(marked["accent"], "@define-color accent_color #3B82F6")
        self.assertEqual(marked["picture-opacity"].strip(), "opacity: 0.70")
        self.assertEqual(marked["avatar-image"].strip(), "background-image: none")
        self.assertEqual(marked["avatar-padding"].strip(), "padding-top: 0")
        after = self.regreet()
        self.assertEqual(after["widget"]["clock"]["format"],
                         "<span size='88pt' weight='bold' font_features='tnum' letter_spacing='-2048'>"
                         "%-I:%M:%S %p</span>")
        # Solo cambia el formato del reloj.
        after["widget"]["clock"].pop("format")
        before_clock = dict(toml_before["widget"]["clock"])
        before_clock.pop("format")
        self.assertEqual(after["widget"]["clock"], before_clock)
        self.assertEqual({k: v for k, v in after.items() if k != "widget"},
                         {k: v for k, v in toml_before.items() if k != "widget"})
        conf = (self.etc / "greetd/churros-greeter.conf").read_text()
        self.assertIn("dim=30\n", conf)
        self.assertIn("accent=#3B82F6\n", conf)
        self.assertEqual(mode(self.etc / "greetd/regreet.css") & 0o777, 0o644)

        # Los valores por defecto devuelven exactamente lo que trae la ISO.
        result = self.run_helper("greeter-set", "dim=48", "avatar=on", "accent=#F97316", "clock=24",
                                 "seconds=off", "date=on", "clock_size=medium")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.etc / "greetd/regreet.css").read_text().rstrip("\n"), css_before.rstrip("\n"),
                         "greeter-set con los valores por defecto no reproduce el regreet.css de la ISO")
        self.assertEqual(self.regreet(), toml_before,
                         "greeter-set con los valores por defecto no reproduce el regreet.toml de la ISO")
        self.assertNoTempFiles()

    def test_greeter_set_keeps_earlier_values(self):
        self.assertEqual(self.run_helper("greeter-set", "accent=#22C55E").returncode, 0)
        self.assertEqual(self.run_helper("greeter-set", "dim=10").returncode, 0)
        marked = self.css_marked()
        self.assertEqual(marked["accent"], "@define-color accent_color #22C55E")
        self.assertEqual(marked["picture-opacity"].strip(), "opacity: 0.90")

    def test_greeter_set_refusals(self):
        files = ("regreet.css", "regreet.toml")
        before = {name: (self.etc / "greetd" / name).read_text() for name in files}
        for args in (["dim=81"], ["dim=-1"], ["dim=4x"], ["accent=red"], ["accent=#12345"],
                     ["accent=#12345G"], ["clock=13"], ["clock_size=huge"], ["avatar=yes"],
                     ["path=/etc/shadow"], ["dim"], ["dim=30", "evil=1"],
                     ["date_pattern=%A"], ['accent=#F97316; } * { color: red'], []):
            with self.subTest(args=args):
                self.assertNotEqual(self.run_helper("greeter-set", *args).returncode, 0)
        for name in files:
            self.assertEqual((self.etc / "greetd" / name).read_text(), before[name], name)
        self.assertFalse((self.etc / "greetd/churros-greeter.conf").exists())

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_greeter_date_pattern_only_as_root(self):
        """configure-greeter-locale lo fija al instalar, como root y sin pkexec."""
        root_env = {k: v for k, v in self.env.items() if k != "PKEXEC_UID"}
        result = self.run_helper("greeter-set", "date_pattern=%A, %-d de %B", env=root_env)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(">%A, %-d de %B</span>", self.regreet()["widget"]["clock"]["format"])
        for bad in ('date_pattern=%A"', "date_pattern=<b>", "date_pattern=a\\b", "date_pattern=" + "x" * 41):
            with self.subTest(bad=bad):
                self.assertNotEqual(self.run_helper("greeter-set", bad, env=root_env).returncode, 0)

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_regreet_greeting(self):
        background = self.regreet()["background"]["path"]
        for text in ("Hola", "¡Bienvenida, Ñandú! 🐧", 'Comillas "dobles" y \\barra\\', "x" * 80, "ñ" * 80):
            with self.subTest(text=text):
                result = self.run_helper("regreet-greeting", text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.regreet()["appearance"]["greeting_msg"], text)
        self.assertEqual(self.regreet()["background"]["path"], background, "cambiar el saludo tocó el fondo")
        self.assertNoTempFiles()

    def test_regreet_greeting_refusals(self):
        before = (self.etc / "greetd/regreet.toml").read_text()
        for text in ("", "x" * 81, "ñ" * 81, "linea\nnueva", 'x"\n[initial_session]\nuser = "root',
                     "tab\tulador", "bell\a"):
            with self.subTest(text=text):
                self.assertNotEqual(self.run_helper("regreet-greeting", text).returncode, 0)
        invalid_utf8 = subprocess.run([str(self.helper), "regreet-greeting", b"caf\xe9"],
                                      capture_output=True, env=self.env)
        self.assertNotEqual(invalid_utf8.returncode, 0)
        self.assertEqual((self.etc / "greetd/regreet.toml").read_text(), before)

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_regreet_greeting_creates_missing_file(self):
        (self.etc / "greetd/regreet.toml").unlink()
        self.assertEqual(self.run_helper("regreet-greeting", "Hola").returncode, 0)
        self.assertEqual(self.regreet(), {"appearance": {"greeting_msg": "Hola"}})


# ------------------------------------------------------- tabla de ediciones


class EditionSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-greetd-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.edition = self.tmp / "churros-edition"
        self.lib = self.tmp / "edition-session.sh"
        self.lib.write_text(EDITION_LIB.read_text().replace("/etc/churros-edition", str(self.edition)))
        (self.tmp / "greetd").mkdir()
        script = CONFIGURE_GREETD.read_text()
        script = script.replace("/usr/share/churros/scripts/edition-session.sh", str(self.lib))
        script = script.replace("/etc/greetd", str(self.tmp / "greetd"))
        self.configure = executable(self.tmp / "configure-greetd-session", script)

    def session(self, edition):
        if edition is None:
            self.edition.unlink(missing_ok=True)
        else:
            self.edition.write_text(f" {edition.upper()}\n")
        return subprocess.run(["bash", "-c", f'source "{self.lib}"; churros_session_command "$(churros_edition)"'],
                              capture_output=True, text=True)

    def test_table(self):
        for edition, expected in [*SESSIONS.items(), ("desconocida", SESSIONS["niri"]), (None, SESSIONS["niri"])]:
            with self.subTest(edition=edition):
                result = self.session(edition)
                self.assertEqual(result.returncode, 0)
                self.assertEqual(result.stdout.strip(), expected)
        self.assertNotEqual(self.session("server").returncode, 0)

    def test_configure_greetd_session_keeps_calamares_user(self):
        config = self.tmp / "greetd/config.toml"
        for edition, session in SESSIONS.items():
            with self.subTest(edition=edition):
                self.edition.write_text(edition + "\n")
                config.write_text('[default_session]\ncommand = "agreety"\n\n'
                                  '[initial_session]\ncommand = "x"\nuser = "ana"\n')
                result = subprocess.run([str(self.configure)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(config.read_text(),
                                 GREETER + f'\n[initial_session]\ncommand = "{session}"\nuser = "ana"\n')
                self.assertEqual((self.tmp / "greetd/environments").read_text(), session + "\n")

    def test_configure_greetd_session_without_autologin_and_server(self):
        config = self.tmp / "greetd/config.toml"
        self.edition.write_text("xfce\n")
        config.write_text('[default_session]\ncommand = "agreety"\n')
        self.assertEqual(subprocess.run([str(self.configure)], capture_output=True).returncode, 0)
        self.assertEqual(config.read_text(), GREETER)
        self.edition.write_text("server\n")
        config.write_text("intacto\n")
        self.assertEqual(subprocess.run([str(self.configure)], capture_output=True).returncode, 0)
        self.assertEqual(config.read_text(), "intacto\n")


if __name__ == "__main__":
    unittest.main(verbosity=2)
