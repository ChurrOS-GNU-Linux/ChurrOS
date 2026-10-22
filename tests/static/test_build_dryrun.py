"""Ensayo en seco de `./churros build` (scripts/cli/build.sh) sin Arch ni root.

Ejecuta el build.sh real de punta a punta, para cada edición × arquitectura
que acepta, en una copia del repo con las herramientas de Arch simuladas
(tests/static/build_stubs/). Comprueba lo que recibiría mkarchiso y que el
árbol queda como estaba. Sin esta prueba, un fallo en build.sh,
installer/apply-calamares.sh, scripts/build-rust.sh,
branding/stamp-os-release.sh o apply-aarch64-mkinitcpio.sh solo se ve tras
un build de una hora, o nunca: un SESSION_CMD vacío en greetd, la lista de
paquetes de la edición sin restaurar, los binarios Rust sin desplegar.

Qué es real y qué no:
- Real: churros, build.sh, scripts/lib/*.sh, build-grub-theme.sh,
  stamp-os-release.sh, apply-calamares.sh, build-rust.sh,
  apply-aarch64-mkinitcpio.sh y patch-mkarchiso-grubmodules.sh (este sobre un
  /usr/bin/mkarchiso falso).
- Simulado: mkarchiso (guarda lo que leería), sudo (sin privilegios, con el
  entorno limpio como env_reset; /root/packages va a un directorio
  temporal), cargo, bsdtar, repo-add y los compiladores de paquetes locales
  (build-calamares/aur/bazaar.sh), que dejan paquetes falsos con los nombres
  reales. git, pacman, makepkg, curl, mount... fallan si se llaman.
- aarch64 se ejecuta como dentro del contenedor de build
  (CHURROS_IN_CONTAINER=1 y CARGO_TARGET_DIR propio, igual que
  scripts/lib/container.sh). Fuera del contenedor, en un host que no es
  aarch64, build.sh lo rechaza, y eso también se comprueba.

No necesita root ni red. Todo ocurre en un directorio temporal: el sudo
falso rechaza cualquier ruta absoluta fuera de él.
CHURROS_KEEP_DRYRUN=1 conserva ese directorio para depurar.
"""
from __future__ import annotations

from dataclasses import dataclass
import getpass
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import unittest

from tests import testlib

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

STUBS = Path(__file__).resolve().parent / "build_stubs"
SUB_BUILDERS = ("scripts/build-calamares.sh", "scripts/build-aur.sh", "scripts/build-bazaar.sh")
NOOP_TOOLS = ("mksquashfs", "xorriso", "grub-mkstandalone", "mkfs.fat", "mcopy", "mmd")
FORBIDDEN_TOOLS = (
    "git", "curl", "wget", "makepkg", "pacman", "pacstrap", "arch-chroot", "repo-remove",
    "apt", "apt-get", "dnf", "podman", "docker", "mount", "umount", "runuser",
)
# Salidas que el build deja a propósito (.gitignore): el repo local de
# paquetes, la caché de cargo y la ISO. Los assets que copia build-rust.sh
# (usr/share/churros/<crate>/) se añaden en Sandbox.persistent().
PERSISTENT = ("archiso/packages/", "rust/target/", "out/")
KNOWN_ISSUE_CATEGORY = "build"

# Lo justo de mkarchiso para que patch-mkarchiso-grubmodules.sh lo parchee
# (archiso: _make_common_bootmode_grub_cfg / grub-mkstandalone).
FAKE_MKARCHISO = r"""#!/usr/bin/env bash
# mkarchiso falso de test_build_dryrun: solo el array grubmodules.
_make_grub_efi() {
    local grubmodules=()
    grubmodules=(all_video at_keyboard boot btrfs cat chain configfile echo efifwsetup \
                 fat font gfxmenu gfxterm gzio halt iso9660 keylayouts linux loadenv \
                 normal part_gpt part_msdos png search usb usbserial_common video zstd)
    grub-mkstandalone -O "${grub_target}" --modules="${grubmodules[*]}"
}
"""


def tail(text: str, lines: int = 25) -> str:
    return "\n".join(text.splitlines()[-lines:])


def parse_os_release(path: Path) -> dict[str, str]:
    """os-release con comillas de shell (os-release(5))."""
    fields = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        words = shlex.split(value)
        fields[key] = words[0] if words else ""
    return fields


def tree_digest(base: Path) -> dict[str, tuple]:
    """{ruta relativa: (modo, contenido o destino del enlace)} de un árbol."""
    digest = {}
    for path in sorted(base.rglob("*")):
        rel = str(path.relative_to(base))
        if path.is_symlink():
            digest[rel] = ("link", os.readlink(path))
        elif path.is_file():
            digest[rel] = (path.stat().st_mode & 0o777, path.read_bytes())
    return digest


def pkg_files(directory: Path) -> set[str]:
    """Paquetes de un repo local (sin firmas), como churros_pkg_archives."""
    if not directory.is_dir():
        return set()
    return {p.name for p in directory.glob("*.pkg.tar.*") if not p.name.endswith(".sig")}


def pkginfo_arch(path: Path) -> str:
    """Campo arch del .PKGINFO de un paquete falso (el paquete es su .PKGINFO)."""
    match = re.search(r"^arch = (\S+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    return match.group(1) if match else ""


@dataclass
class BuildResult:
    args: list[str]
    code: int
    output: str
    log: Path
    cargo_target: Path

    @property
    def snapshots(self) -> list[Path]:
        return sorted(self.log.glob("mkarchiso.*"), key=lambda p: int(p.suffix[1:]))

    @property
    def forbidden(self) -> str:
        path = self.log / "forbidden.log"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def logged(self, name: str) -> str:
        path = self.log / name
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def describe(self) -> str:
        return f"./churros build {' '.join(self.args)} (salida {self.code}):\n{tail(self.output)}"


class Sandbox:
    """Copia del repo con git propio, stubs en el PATH y un /root falso."""

    def __init__(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="churros-dryrun-")).resolve()
        self.repo = self.tmp / "repo"
        self.bin = self.tmp / "bin"
        self.fake_root = self.tmp / "fakeroot"
        self.home = self.tmp / "home"
        self.logs = self.tmp / "logs"
        for directory in (self.repo, self.bin, self.fake_root / "usr/bin", self.home, self.logs):
            directory.mkdir(parents=True)
        self.runs = 0
        # scratch_env: sin GIT_INDEX_FILE/GIT_DIR de un hook, este git no
        # puede tocar el repositorio de verdad.
        self.git_env = testlib.scratch_env(
            GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
            GIT_AUTHOR_NAME="dryrun", GIT_AUTHOR_EMAIL="dryrun@invalid",
            GIT_COMMITTER_NAME="dryrun", GIT_COMMITTER_EMAIL="dryrun@invalid",
        )
        self._copy_repo()
        self._install_stubs()
        self.git("init", "-q")
        self.git("add", "-A", "-f")
        self.git("commit", "-q", "--no-verify", "--no-gpg-sign", "-m", "dry-run base")
        self.reset()

    def _copy_repo(self):
        for source in testlib.repo_files():
            target = self.repo / source.relative_to(testlib.ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                os.symlink(os.readlink(source), target)
            else:
                shutil.copy2(source, target)

    def _install_stubs(self):
        def install(stub: str, name: str):
            shutil.copyfile(STUBS / stub, self.bin / name)
            (self.bin / name).chmod(0o755)
        for name in ("sudo", "mkarchiso", "cargo"):
            install(name, name)
        for name in ("bsdtar", "repo-add", *NOOP_TOOLS, *FORBIDDEN_TOOLS):
            install("tool", name)
        # Los compiladores de paquetes locales se sustituyen en la copia; el
        # commit base ya los incluye, así que no ensucian git status.
        for path in SUB_BUILDERS:
            shutil.copyfile(STUBS / "fake-builder.sh", self.repo / path)

    def git(self, *args) -> str:
        return testlib.run(["git", *args], cwd=self.repo, env=self.git_env, check=True).stdout

    def reset(self):
        """Vuelve al commit base: sin paquetes locales, caché de cargo ni ISO."""
        self.git("reset", "-q", "--hard", "HEAD")
        self.git("clean", "-q", "-f", "-f", "-d", "-x")
        link = self.fake_root / "packages"
        if link.is_symlink() or link.exists():
            link.unlink()
        (self.fake_root / "usr/bin/mkarchiso").write_text(FAKE_MKARCHISO, encoding="utf-8")

    def persistent(self, path: str, allow_work: bool) -> bool:
        if path.startswith(PERSISTENT) or (allow_work and path.startswith("work/")):
            return True
        # build-rust.sh copia rust/<crate>/assets a usr/share/churros/<crate>/
        # y no se borra (.gitignore lo declara salida del build).
        return any(path.startswith(f"archiso/airootfs/usr/share/churros/{name}/")
                   for name in testlib.deploy_crate_names())

    def status(self, allow_work: bool = False) -> list[str]:
        """git status de todo lo que no es salida persistente (incluye ignorados)."""
        raw = self.git("status", "--porcelain=v1", "-z", "--ignored", "--untracked-files=all")
        entries = [entry for entry in raw.split("\0") if entry]
        return sorted(e for e in entries if not self.persistent(e[3:], allow_work))

    def build(self, *args: str, pkg_arch: str = "x86_64", mkarchiso: str = "ok",
              container: bool = False) -> BuildResult:
        self.runs += 1
        log = self.logs / f"run{self.runs}"
        log.mkdir()
        user = os.environ.get("USER") or getpass.getuser()
        env = {
            "PATH": f"{self.bin}:{os.environ.get('PATH', '/usr/bin:/bin')}",
            "HOME": str(self.home), "USER": user, "LOGNAME": user,
            "LANG": "C.UTF-8", "TERM": "dumb",
            "DRYRUN_ROOT": str(self.tmp), "DRYRUN_FAKE_ROOT": str(self.fake_root),
            "DRYRUN_LOG": str(log), "DRYRUN_STUBS": str(self.bin),
            "DRYRUN_MKARCHISO": mkarchiso, "DRYRUN_PKG_ARCH": pkg_arch,
        }
        cargo_target = self.repo / "rust/target"
        if container:
            # Lo que exporta scripts/lib/container.sh dentro del contenedor.
            cargo_target = self.repo / "rust/target/container-aarch64"
            env.update(CHURROS_IN_CONTAINER="1", CARGO_TARGET_DIR=str(cargo_target))
        result = subprocess.run(
            ["bash", "churros", "build", *args], cwd=self.repo, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120,
            start_new_session=True,
            # Lanzada en segundo plano desde un script, la batería hereda
            # SIGINT ignorado y bash no puede volver a activarlo: el caso
            # 'int' (Ctrl-C simulado) no interrumpiría nada.
            preexec_fn=lambda: signal.signal(signal.SIGINT, signal.SIG_DFL),
        )
        return BuildResult(list(args), result.returncode, result.stdout, log, cargo_target)

    def cleanup(self):
        if os.environ.get("CHURROS_KEEP_DRYRUN") == "1":
            print(f"\n[test_build_dryrun] directorio conservado: {self.tmp}")
            return
        shutil.rmtree(self.tmp, ignore_errors=True)


def build_args(item: testlib.Edition) -> list[str]:
    # pi usa el alias arm64, como en AGENTS.md (./churros build --arch arm64).
    arch = "arm64" if item.name == "pi" else item.arch
    return ["--edition", item.name, "--arch", arch]


class BuildDryRunTest(unittest.TestCase):
    box: Sandbox | None = None

    @classmethod
    def setUpClass(cls):
        if tomllib is None or not shutil.which("git") or platform.system() != "Linux":
            cls.box = None
            return
        cls.box = Sandbox()

    @classmethod
    def tearDownClass(cls):
        if cls.box:
            cls.box.cleanup()

    def setUp(self):
        if tomllib is None:
            self.skipTest("tomllib necesita Python >= 3.11")
        if platform.system() != "Linux":
            self.skipTest("build.sh solo corre en Linux (find -printf, cp -a, sed -i de GNU)")
        testlib.require_tool(self, "git")
        self.box.reset()

    # ----------------------------------------------------------- comprobaciones

    def check_build(self, item: testlib.Edition, result: BuildResult) -> list[str]:
        """Lo que mkarchiso recibió en un build correcto de `item`."""
        if result.code != 0:
            return [f"el build falló: {result.describe()}"]
        problems = []
        if result.forbidden:
            problems.append(f"usó herramientas no permitidas:\n{result.forbidden}")
        snaps = result.snapshots
        if len(snaps) != 1:
            return problems + [f"mkarchiso se llamó {len(snaps)} veces (se espera 1)"]
        snap = snaps[0]
        air = snap / "airootfs"
        manifest = {line.split(" ", 2)[2] for line in (snap / "manifest").read_text().splitlines()}
        repo = self.box.repo

        # Invocación: sudo env CHURROS_ARCH=<arch> mkarchiso -w work -o out archiso.
        env = dict(line.split("=", 1) for line in (snap / "env").read_text().splitlines())
        argv = (snap / "argv").read_bytes().decode().split("\0")[:-1]
        if env["via_sudo"] != "1":
            problems.append("mkarchiso no se lanzó con sudo (el real exige root)")
        if env["CHURROS_ARCH"] != item.arch:
            problems.append(f"mkarchiso recibió CHURROS_ARCH={env['CHURROS_ARCH']}, no {item.arch} "
                            "(sudo limpia el entorno: hay que pasarla con `sudo env`)")
        if Path(env["cwd"]) != repo:
            problems.append(f"mkarchiso corrió en {env['cwd']}, no en la raíz del repo")
        for flag, value in (("-w", "work"), ("-o", "out")):
            if flag not in argv[:-1] or argv[argv.index(flag) + 1] != value:
                problems.append(f"mkarchiso sin `{flag} {value}`: {argv}")
        if not argv or argv[-1] != "archiso":
            problems.append(f"el perfil de mkarchiso no es archiso: {argv}")
        profile = dict(line.split("=", 1) for line in (snap / "profile").read_text().splitlines())
        if profile.get("arch") != item.arch:
            problems.append(f"profiledef.sh dio arch={profile.get('arch')} con ese entorno, no {item.arch}")

        # La lista que lee pacstrap (packages.<arch> según profiledef.sh).
        expected = (testlib.ROOT / item.package_list).read_text(encoding="utf-8")
        got = (snap / "packages").read_text(encoding="utf-8")
        if got != expected:
            seen = set(testlib.parse_package_list(snap / "packages"))
            wanted = set(testlib.parse_package_list(item.list_path))
            extra, missing = sorted(seen - wanted), sorted(wanted - seen)
            problems.append(f"archiso/packages.{item.arch} no es {item.package_list} al llamar a mkarchiso "
                            f"(sobran {extra[:5]}, faltan {missing[:5]})")

        # greetd: autologin Live con la sesión de la edición; greeter cage+regreet.
        try:
            greetd = tomllib.loads((air / "etc/greetd/config.toml").read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as error:
            problems.append(f"etc/greetd/config.toml no es TOML válido: {error}")
        else:
            initial = greetd.get("initial_session", {})
            if initial.get("command") != item.session_cmd:
                problems.append(f"greetd initial_session.command = {initial.get('command')!r}, "
                                f"se espera {item.session_cmd!r}")
            if initial.get("user") != "churros":
                problems.append(f"greetd initial_session.user = {initial.get('user')!r}: el usuario Live "
                                "es churros (root/scripts/users.sh)")
            default = greetd.get("default_session", {})
            words = shlex.split(default.get("command", ""))
            if "cage" not in words or words[-1:] != ["regreet"] or default.get("user") != "greeter":
                problems.append(f"greetd default_session no es cage+regreet como greeter: {default}")
            if "vt" not in greetd.get("terminal", {}):
                problems.append("greetd sin [terminal] vt")

        edition_file = air / "etc/churros-edition"
        if not edition_file.is_file() or edition_file.read_text().strip() != item.name:
            problems.append(f"etc/churros-edition no contiene '{item.name}'")

        # os-release que customize_airootfs.sh copia a /etc y /usr/lib.
        version = (testlib.ROOT / "VERSION").read_text().strip()
        os_release = air / "root/branding/files/os-release"
        fields = parse_os_release(os_release) if os_release.is_file() else {}
        for key, value in (("ID", "churros"), ("VERSION_ID", version), ("VERSION", version), ("VARIANT_ID", item.name)):
            if fields.get(key) != value:
                problems.append(f"os-release {key}={fields.get(key)!r}, se espera {value!r}")

        # customize_airootfs.sh (lo ejecuta mkarchiso en el chroot) y lo que lee de /root/branding.
        customize = air / "root/customize_airootfs.sh"
        source = testlib.ROOT / "branding/customize_airootfs.sh"
        if not customize.is_file() or customize.read_bytes() != source.read_bytes():
            problems.append("root/customize_airootfs.sh no es la copia de branding/customize_airootfs.sh")
        for ref in sorted(set(re.findall(r"/root/branding/[\w.-]+(?:/[\w.-]+)*", source.read_text()))):
            ref = re.sub(r"/\.?$", "", ref)
            if not (air / ref.lstrip("/")).exists():
                problems.append(f"customize_airootfs.sh lee {ref}, que no está en el airootfs")

        # Binarios Rust (deploy = true): los que compiló cargo en su target.
        for name in sorted(testlib.deploy_crate_names()):
            deployed = air / "usr/bin" / name
            built = result.cargo_target / "release" / name
            if not deployed.is_file():
                problems.append(f"usr/bin/{name} no se desplegó (build-rust.sh)")
            elif not deployed.stat().st_mode & 0o111:
                problems.append(f"usr/bin/{name} no es ejecutable")
            elif not built.is_file() or deployed.read_bytes() != built.read_bytes():
                problems.append(f"usr/bin/{name} no es el binario de {built.relative_to(repo)} "
                                "(¿se ignora CARGO_TARGET_DIR?)")

        # Repo local [churros]: pacstrap lo lee por file:///root/packages del host.
        local_repo = repo / ("archiso/packages/aarch64" if item.arch == "aarch64" else "archiso/packages")
        host_repo = (snap / "host-repo").read_text().strip()
        if host_repo != str(local_repo):
            problems.append(f"/root/packages del host apunta a {host_repo!r}, no a {local_repo}")

        problems += self.check_installer(item, air, manifest, local_repo)
        problems += self.check_mkinitcpio(item, snap, air, manifest, result)
        return problems

    def check_installer(self, item, air: Path, manifest: set[str], local_repo: Path) -> list[str]:
        problems = []
        calamares = air / "etc/calamares"
        packages = air / "root/packages"
        rule = "etc/polkit-1/rules.d/49-calamares.rules"
        if not item.installer:
            for path in ("etc/calamares/settings.conf", rule, "root/packages"):
                if (air / path).exists():
                    problems.append(f"{item.id} no lleva instalador, pero hay {path}")
            return problems
        source = testlib.ROOT / "installer/calamares"
        if not (calamares / "settings.conf").is_file() or \
                (calamares / "settings.conf").read_bytes() != (source / "settings.conf").read_bytes():
            return problems + ["etc/calamares/settings.conf falta o no es installer/calamares/settings.conf"]
        # Módulos: los comunes, con encima los de modules/<arch>/ (apply-calamares.sh).
        modules = {p.name: p for p in sorted((source / "modules").glob("*.conf"))}
        modules.update({p.name: p for p in (source / "modules").glob("*.yaml")})
        modules.update({p.name: p for p in (source / "modules" / item.arch).glob("*.conf")})
        for name, expected in sorted(modules.items()):
            deployed = calamares / "modules" / name
            if not deployed.is_file() or deployed.read_bytes() != expected.read_bytes():
                problems.append(f"etc/calamares/modules/{name} no es {expected.relative_to(testlib.ROOT)}")
        branding = source / "branding/churros"
        for path in sorted(p for p in branding.rglob("*") if p.is_file()):
            rel = path.relative_to(branding)
            if not (calamares / "branding/churros" / rel).is_file():
                problems.append(f"falta etc/calamares/branding/churros/{rel}")
        show = calamares / "branding/churros/show.qml"
        template = (branding / "show.qml").read_text(encoding="utf-8")
        if show.is_file() and "@EDITION@" in template:
            text = show.read_text(encoding="utf-8")
            pattern = re.escape(template).replace(re.escape("@EDITION@"), r"([^\n\"@]+)")
            if "@EDITION@" in text or not re.fullmatch(pattern, text):
                problems.append("show.qml conserva @EDITION@ o cambió algo más que el marcador")
        if rule not in manifest:
            problems.append(f"falta {rule} (pkexec de Calamares para el usuario churros)")
        # /root/packages: customize_airootfs.sh instala calamares-[0-9]* con
        # bsdtar; el resto del repo local va al sistema instalado.
        copied = pkg_files(packages)
        if not any(re.match(r"calamares-[0-9]", name) for name in copied):
            problems.append("root/packages no tiene calamares-[0-9]*.pkg.tar.* (customize_airootfs.sh lo instala de ahí)")
        if copied != pkg_files(local_repo):
            problems.append(f"root/packages {sorted(copied)} no es el repo local {local_repo.name}/ "
                            f"{sorted(pkg_files(local_repo))}")
        for name in sorted(copied):
            if pkginfo_arch(packages / name) not in (item.arch, "any"):
                problems.append(f"root/packages/{name} es de otra arquitectura ({pkginfo_arch(packages / name)})")
        if not any(p.name.startswith("churros.db") for p in packages.glob("churros.db*")):
            problems.append("root/packages sin churros.db")
        return problems

    def check_mkinitcpio(self, item, snap: Path, air: Path, manifest: set[str], result: BuildResult) -> list[str]:
        """Preset y hooks de mkinitcpio, y el parche de módulos GRUB, según la arquitectura."""
        problems = []
        share = "usr/share/churros/mkinitcpio/aarch64"
        conf = (air / "etc/mkinitcpio.conf.d/archiso.conf").read_bytes()
        if item.arch == "aarch64":
            # customize_airootfs.sh instala el preset ARM desde /usr/share/churros.
            if "etc/mkinitcpio.d/linux.preset" in manifest:
                problems.append("aarch64 con el preset x86 etc/mkinitcpio.d/linux.preset (pacstrap buscaría vmlinuz-linux)")
            for name in ("linux-aarch64.preset", "archiso.conf"):
                if f"{share}/{name}" not in manifest:
                    problems.append(f"falta {share}/{name} (customize_airootfs.sh lo instala)")
            if conf != (testlib.ROOT / "archiso/mkinitcpio/aarch64/archiso.conf").read_bytes():
                problems.append("etc/mkinitcpio.conf.d/archiso.conf no tiene los hooks aarch64")
            if (snap / "grubmodules").read_text().strip() != "patched":
                problems.append("no se parcheó grubmodules en mkarchiso (patch-mkarchiso-grubmodules.sh)")
        else:
            if "etc/mkinitcpio.d/linux.preset" not in manifest or any(p.startswith(share) for p in manifest):
                problems.append(f"{item.id} no tiene el preset x86 tal como está en git")
            if conf != (testlib.AIROOTFS / "etc/mkinitcpio.conf.d/archiso.conf").read_bytes():
                problems.append(f"{item.id} cambió etc/mkinitcpio.conf.d/archiso.conf")
            if "patch-mkarchiso-grubmodules" in result.logged("sudo.log"):
                problems.append(f"{item.id} parcheó mkarchiso (solo hace falta en aarch64)")
        return problems

    def assert_no_problems(self, problems: list[str], header: str):
        if problems:
            self.fail(f"{header}:\n  - " + "\n  - ".join(problems))

    def assert_clean(self, result: BuildResult, allow_work: bool = False):
        leftovers = self.box.status(allow_work)
        if leftovers:
            self.fail("el árbol no quedó como estaba (?? sin seguimiento, !! ignorado, M modificado, "
                      "D borrado):\n  " + "\n  ".join(leftovers) + f"\n\ntras {result.describe()}")
        link = self.box.fake_root / "packages"
        self.assertFalse(link.is_symlink() or link.exists(), "quedó el enlace /root/packages del host")

    # ------------------------------------------------------------------- pruebas

    def test_every_edition_builds_what_mkarchiso_needs(self):
        """Cada edición × arquitectura: lo que lee mkarchiso y el árbol limpio después."""
        order = {"x86_64": 0, "i686": 1, "aarch64": 2}
        # aarch64 al final: rust/target/release ya tiene binarios de x86_64,
        # así que desplegar desde ahí (sin CARGO_TARGET_DIR) se nota.
        for item in sorted(testlib.EDITIONS, key=lambda e: order[e.arch]):
            with self.subTest(edition=item.id):
                result = self.box.build(*build_args(item), pkg_arch=item.arch, container=item.arch == "aarch64")
                problems = self.check_build(item, result)
                self.assert_no_problems(problems, item.id)
                self.assert_clean(result)

    def test_failed_or_interrupted_build_restores_tree(self):
        """Si mkarchiso falla o se pulsa Ctrl-C, el trap deja el árbol como estaba."""
        cases = (
            (testlib.edition("xfce", "x86_64"), "fail"),
            (testlib.edition("niri", "aarch64"), "fail"),
            (testlib.edition("server", "x86_64"), "int"),
        )
        for item, mode in cases:
            with self.subTest(edition=item.id, mkarchiso=mode):
                result = self.box.build(*build_args(item), pkg_arch=item.arch, mkarchiso=mode,
                                        container=item.arch == "aarch64")
                self.assertNotEqual(result.code, 0, f"el build no falló: {result.describe()}")
                self.assertEqual(len(result.snapshots), 1, f"mkarchiso no llegó a ejecutarse: {result.describe()}")
                # work/ se queda para inspeccionar el fallo; el siguiente build lo borra.
                self.assert_clean(result, allow_work=True)

    def test_unsupported_combinations_are_rejected(self):
        """Ediciones o arquitecturas que build.sh no soporta: error claro y nada tocado."""
        names = sorted({item.name for item in testlib.EDITIONS})
        supported = {(item.name, item.arch) for item in testlib.EDITIONS}
        cases = [(["--edition", "kde"], "kde"), (["--arch", "riscv64"], "riscv64")]
        cases += [(["--edition", name, "--arch", arch], f"packages.{name}.{arch}")
                  for name in names for arch in testlib.ARCHES if (name, arch) not in supported]
        for args, hint in cases:
            with self.subTest(args=" ".join(args)):
                result = self.box.build(*args)
                self.assertNotEqual(result.code, 0, f"build.sh aceptó {args}: {result.describe()}")
                self.assertIn(hint, result.output, f"el error no menciona {hint!r}: {result.describe()}")
                self.assertEqual(result.snapshots, [], "se llegó a llamar a mkarchiso")
                self.assertEqual(result.logged("builders.log"), "", "se compilaron paquetes antes de rechazarlo")
                self.assertEqual(result.forbidden, "", f"usó herramientas no permitidas: {result.forbidden}")
                self.assert_clean(result)

    def test_aarch64_outside_container_is_refused(self):
        """En un host x86_64, la ISO aarch64 sin --container se rechaza (no usa pacstrap x86)."""
        if platform.machine() in ("aarch64", "arm64"):
            self.skipTest("en un host aarch64 el build ARM es nativo")
        result = self.box.build("--arch", "arm64", pkg_arch="aarch64")
        self.assertNotEqual(result.code, 0, f"build.sh construyó aarch64 fuera del contenedor: {result.describe()}")
        self.assertIn("--container", result.output, f"el error no dice cómo hacerlo: {result.describe()}")
        self.assertEqual(result.snapshots, [], "se llegó a llamar a mkarchiso")
        self.assert_clean(result)

    def test_second_build_is_identical(self):
        """Dos builds seguidos de la misma edición dan a mkarchiso exactamente lo mismo."""
        item = testlib.edition("xfce", "x86_64")
        first = self.box.build(*build_args(item))
        self.assert_no_problems(self.check_build(item, first), "primer build xfce/x86_64")
        second = self.box.build(*build_args(item))
        self.assert_no_problems(self.check_build(item, second), "segundo build xfce/x86_64")
        before, after = tree_digest(first.snapshots[0]), tree_digest(second.snapshots[0])
        changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
        self.assertEqual(changed, [], "el segundo build dio a mkarchiso otra cosa en: " + ", ".join(changed[:20]))
        self.assert_clean(second)

    def test_known_build_hazards(self):
        """Builds interrumpidos (SIGKILL) y builds de varias arquitecturas seguidos.

        Lo correcto: el siguiente build normal recupera la lista de paquetes
        que dejó a medias el interrumpido, lo que deja un build interrumpido
        está en .gitignore (no acaba en un `git add -A`), y un build aarch64
        no borra los paquetes locales de x86_64 (tienen directorios
        distintos). Lo que falla hoy está en tests/known_issues.toml.
        """
        findings = {}
        list_path = "archiso/packages.x86_64"
        base_list = (testlib.ROOT / list_path).read_text(encoding="utf-8")
        xfce = testlib.edition("xfce", "x86_64")

        def split_list_problems(problems: list[str], leftovers: list[str]):
            """Separa lo que toca a packages.x86_64 (el problema conocido) del resto."""
            about_list = [p for p in problems + leftovers if list_path in p]
            others = [p for p in problems + leftovers if list_path not in p]
            return about_list, others

        # 1. SIGKILL en un build --edition xfce, luego --edition server.
        killed = self.box.build(*build_args(xfce), mkarchiso="kill")
        self.assertEqual(len(killed.snapshots), 1, f"mkarchiso no llegó a ejecutarse: {killed.describe()}")
        self.assertNotEqual(killed.code, 0, f"el build no se interrumpió: {killed.describe()}")
        for entry in self.box.status():
            if entry.startswith("?? "):
                findings[f"build:not-ignored-after-interrupt:{entry[3:]}"] = (
                    f"{entry[3:]} queda tras un build interrumpido y no está en .gitignore (`git add -A` lo sube)")
        server = testlib.edition("server", "x86_64")
        result = self.box.build(*build_args(server))
        about_list, others = split_list_problems(self.check_build(server, result), self.box.status())
        self.assert_no_problems(others, "server/x86_64 tras xfce interrumpido")
        if (self.box.repo / list_path).read_text(encoding="utf-8") != base_list:
            findings["build:edition-list-backup-overwritten"] = (
                "tras un build --edition xfce interrumpido, un build --edition server deja "
                f"{list_path} con otra lista y no la de niri ({'; '.join(about_list)})")

        # 2. SIGKILL en un build --edition xfce, luego el build por defecto (niri).
        self.box.reset()
        self.box.build(*build_args(xfce), mkarchiso="kill")
        niri = testlib.edition("niri", "x86_64")
        result = self.box.build(*build_args(niri))
        about_list, others = split_list_problems(self.check_build(niri, result), self.box.status())
        self.assert_no_problems(others, "niri/x86_64 tras xfce interrumpido")
        if about_list:
            findings["build:edition-list-not-restored-for-niri"] = (
                "tras un build --edition xfce interrumpido, el build niri siguiente usa y deja "
                f"otra lista en {list_path}: {'; '.join(about_list)}")

        # 3. Build x86_64 y después aarch64 (contenedor): los paquetes x86_64 siguen.
        self.box.reset()
        result = self.box.build(*build_args(niri))
        self.assert_no_problems(self.check_build(niri, result), "niri/x86_64")
        x86_packages = pkg_files(self.box.repo / "archiso/packages")
        arm = testlib.edition("niri", "aarch64")
        result = self.box.build(*build_args(arm), pkg_arch="aarch64", container=True)
        self.assert_no_problems(self.check_build(arm, result), "niri/aarch64 tras niri/x86_64")
        lost = sorted(x86_packages - pkg_files(self.box.repo / "archiso/packages"))
        if lost:
            findings["build:aarch64-build-deletes-x86_64-local-packages"] = (
                f"un build aarch64 borra los paquetes locales x86_64 de archiso/packages/: {', '.join(lost)}")

        testlib.assert_findings(self, KNOWN_ISSUE_CATEGORY, findings)


if __name__ == "__main__":
    unittest.main()
