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
        ["bash", "-c", f'source "$1"; shift\n{script}', "prueba", str(UPDATE_UTILS), *map(str, args)],
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
        self.assertEqual(log[0], "curl https://download.churroslinux.org/churros/updates.json")
        self.assertEqual(log[1], "curl https://download.churroslinux.org/churros/updates.json.minisig")
        self.assertEqual(log[2], f"minisign {len(self.MANIFEST.encode())}")

    def test_bad_signature_aborts(self):
        self.pubkey.write_text("clave\n")
        (self.served / "updates.json").write_text(self.MANIFEST.replace("1.3", "6.6.6"))
        result = self.fetch(self.pubkey)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("firma minisign inválida", result.stderr)

    def test_without_pubkey_only_warns(self):
        result = self.fetch(self.tmp / "no-existe.pubkey")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("AVISO", result.stdout)
        self.assertNotIn("minisign", self.log.read_text())

    @unittest.skipIf(shutil.which("minisign", path="/usr/bin:/bin"), "minisign instalado en el host")
    def test_pubkey_without_minisign_aborts(self):
        self.pubkey.write_text("clave\n")
        (self.tmp / "bin/minisign").unlink()
        result = self.fetch(self.pubkey)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("falta minisign", result.stderr)

    def test_parse_manifest(self):
        manifest = self.tmp / "m.json"
        manifest.write_text(
            '{"version": "1.3", "editions": {"niri": {"file": "churros-utils-niri-1.3.tar.zst", '
            '"sha256": "%s"}}}' % ("b" * 64))
        result = update_utils('parse_manifest "$1" niri', manifest)
        self.assertEqual(result.stdout.strip(), f"1.3|churros-utils-niri-1.3.tar.zst|{'b' * 64}")
        manifest.write_text('{"version": "1.3", "file": "../../etc/x.tar.zst", "sha256": "%s"}' % ("b" * 64))
        self.assertNotEqual(update_utils('parse_manifest "$1" niri', manifest).returncode, 0)


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
        # `cargo build --release`, sin compilar nada.
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
    printf '#!/bin/sh\\n' > "$rust_dir/target/release/$name"
    chmod 755 "$rust_dir/target/release/$name"
done
''')
        env = {**os.environ, "PATH": f"{tmp / 'bin'}:{os.environ['PATH']}"}
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
    def test_regreet_wallpaper(self):
        before = self.regreet()
        for name in ("fondo.png", 'con "comillas" \\ y espacios.png'):
            with self.subTest(name=name):
                result = self.run_helper("regreet-wallpaper", str(self.wallpapers / name))
                self.assertEqual(result.returncode, 0, result.stderr)
                after = self.regreet()
                self.assertEqual(after["background"]["path"], str(self.wallpapers / name))
                # El resto del fichero no cambia.
                self.assertEqual({k: v for k, v in after.items() if k != "background"},
                                 {k: v for k, v in before.items() if k != "background"})
                self.assertEqual(after["background"]["fit"], before["background"]["fit"])
        self.assertNoTempFiles()

    def test_regreet_wallpaper_refusals(self):
        before = (self.etc / "greetd/regreet.toml").read_text()
        for path in ("fondo.png", str(self.tmp / "home/ana/foto.png"), str(self.wallpapers / "fuera.png"),
                     str(self.wallpapers / "secreto.png"), str(self.wallpapers / "no-existe.png"),
                     str(self.wallpapers), str(self.wallpapers / "../wallpapers/x\ny.png"), "/etc/shadow"):
            with self.subTest(path=path):
                self.assertNotEqual(self.run_helper("regreet-wallpaper", path).returncode, 0)
        self.assertEqual((self.etc / "greetd/regreet.toml").read_text(), before)

    @unittest.skipIf(tomllib is None, "Python sin tomllib")
    def test_regreet_greeting(self):
        for text in ("Hola", "¡Bienvenida, Ñandú! 🐧", 'Comillas "dobles" y \\barra\\', "x" * 80, "ñ" * 80):
            with self.subTest(text=text):
                result = self.run_helper("regreet-greeting", text)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.regreet()["appearance"]["greeting_msg"], text)
        self.assertEqual(self.regreet()["background"]["path"], "/usr/share/churros/wallpapers/default.png")
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
