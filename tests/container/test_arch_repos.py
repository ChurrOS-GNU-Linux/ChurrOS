"""Listas de paquetes, kernel y tablas de proveedores contra los repos reales.

Corre en el contenedor de build (Containerfile, Arch Linux) con
`./churros test --container`. Fuera de él (sin /etc/arch-release o sin
CHURROS_IN_CONTAINER=1) el módulo entero se salta, también en modo
estricto: estas pruebas se activan por entorno, no por herramienta.

Quien decide es pacman, igual que en pacstrap:
  - Cada paquete de cada lista existe en los repos de su arquitectura y la
    lista entera resuelve con dependencias (pacman -Sp sobre una base de
    datos local vacía, como un pacstrap a un directorio nuevo). El repo
    local [churros] no existe aquí: sus paquetes (testlib.local_packages())
    se quitan de la petición y sus dependencias no se comprueban.
  - El cierre de dependencias es la verdad de testlib.installed(): lo que da
    por instalado con BASE_DEPENDS o con [implicit] tiene que estar en él.
  - command_providers.toml y unit_providers.toml: el paquete de cada
    comando, ruta o unidad la instala de verdad (pacman -F).
  - El kernel que nombran los arranques (vmlinuz-<k> en GRUB, syslinux,
    unpackfs de Calamares y el preset de mkinitcpio) es un paquete de la
    lista: cambiar linux por linux-zen deja la ISO sin arrancar.

Arquitecturas: la del contenedor siempre. aarch64 (Arch Linux ARM) e i686
(Arch Linux 32) también desde x86_64, porque sus pacman.<arch>.conf nombran
los servidores y pacman -Sp no instala nada (Architecture=<otra> resuelve
igual). pacman.x86_64.conf usa el mirrorlist del equipo, así que el runner
ARM no resuelve x86_64. Las bases de datos de ficheros (pacman -Fy, unos
50 MB) solo se bajan para la arquitectura del contenedor.

Cada arquitectura usa un --dbpath propio en un directorio temporal: la base
de datos del contenedor no se toca.
"""
from __future__ import annotations

from dataclasses import dataclass
import difflib
from functools import lru_cache
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
import unittest

from tests import testlib

HOST_ARCH = platform.machine()
SUDO = [] if os.geteuid() == 0 else ["sudo", "-n"]
WORK: Path | None = None


def skip_reason() -> str | None:
    if not Path("/etc/arch-release").exists():
        return "solo corre en el contenedor Arch de build (no hay /etc/arch-release)"
    if os.environ.get("CHURROS_IN_CONTAINER") != "1":
        return "solo corre dentro del contenedor de build (./churros test --container; CHURROS_IN_CONTAINER != 1)"
    if not shutil.which("pacman"):
        return "no hay pacman"
    return None


def setUpModule():
    global WORK
    reason = skip_reason()
    if reason:
        raise unittest.SkipTest(reason)
    WORK = Path(tempfile.mkdtemp(prefix="churros-repos-"))


def tearDownModule():
    # pacman escribe como root dentro de WORK: hay que borrarlo con sudo.
    if WORK is not None:
        subprocess.run([*SUDO, "rm", "-rf", "--", str(WORK)], check=False)


# ------------------------------------------------------------------- pacman

def without_local_repos(text: str) -> str:
    """pacman.conf sin los repos cuyos Server son todos file:// ([churros]).

    Ese repo lo llenan los scripts de build (archiso/packages/) y aquí no
    existe: pacman -Sy fallaría al sincronizarlo.
    """
    blocks: list[tuple[str | None, list[str]]] = [(None, [])]
    for line in text.splitlines():
        match = re.fullmatch(r"\s*\[([^\]]+)\]\s*", line)
        if match:
            blocks.append((match.group(1), []))
        blocks[-1][1].append(line)
    kept = []
    for name, lines in blocks:
        servers = [line.split("=", 1)[1].strip() for line in lines if re.match(r"\s*Server\s*=", line)]
        if name not in (None, "options") and servers and all(s.startswith("file://") for s in servers):
            continue
        kept.extend(lines)
    return "\n".join(kept) + "\n"


def pacman_conf(arch: str) -> str:
    # El mismo fichero que mkarchiso pasa a pacstrap: pacman_conf de profiledef.sh.
    return without_local_repos(testlib.read_text(testlib.ROOT / "archiso" / testlib.profile(arch)["pacman_conf"]))


@lru_cache(maxsize=None)
def resolvable_arches() -> tuple[str, ...]:
    """La del contenedor, más las que nombran sus servidores (sin Include)."""
    return tuple(
        arch for arch in testlib.ARCHES
        if arch == HOST_ARCH or not re.search(r"^\s*Include\s*=", pacman_conf(arch), re.MULTILINE)
    )


def editions() -> list[testlib.Edition]:
    return [item for item in testlib.EDITIONS if item.arch in resolvable_arches()]


def native_editions() -> list[testlib.Edition]:
    return [item for item in testlib.EDITIONS if item.arch == HOST_ARCH]


def list_name(item: testlib.Edition) -> str:
    return Path(item.package_list).name


class Repos:
    """Copia privada de las bases de datos de pacman de una arquitectura."""

    def __init__(self, arch: str):
        self.arch = arch
        self.dir = WORK / arch
        for sub in ("db", "cache"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.conf = self.dir / "pacman.conf"
        text = pacman_conf(arch)
        self.conf.write_text(text)
        self.names = [name for name in re.findall(r"^\s*\[([^\]]+)\]", text, re.MULTILINE) if name != "options"]

    @property
    def cache(self) -> Path:
        return self.dir / "cache"

    def pacman(self, *args: str, root: bool = False, timeout: int = 300) -> subprocess.CompletedProcess:
        cmd = [*(SUDO if root else []), "pacman", *args,
               "--config", str(self.conf), "--dbpath", str(self.dir / "db"),
               "--cachedir", str(self.cache), "--logfile", str(self.dir / "pacman.log"),
               "--noconfirm"]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def sync(self, operation: str) -> str | None:
        """pacman -Sy o -Fy, con un reintento: la red del CI falla a veces.

        Devuelve el error, o None. Se guarda: un mirror caído no se reintenta
        en cada prueba.
        """
        for _ in range(2):
            result = self.pacman(operation, root=True, timeout=1200)
            if result.returncode == 0:
                return None
        return (f"no se pudieron sincronizar los repos de {self.arch} ({operation}, {', '.join(self.names)}); "
                f"es la red o un mirror, no la lista:\n{result.stdout}{result.stderr}")


@lru_cache(maxsize=None)
def _synced(arch: str, operation: str) -> tuple[Repos, str | None]:
    item = _synced(arch, "-Sy")[0] if operation == "-Fy" else Repos(arch)
    return item, item.sync(operation)


def repos(arch: str) -> Repos:
    item, error = _synced(arch, "-Sy")
    if error:
        raise AssertionError(error)
    return item


def files_repos(arch: str) -> Repos:
    """Repos con las bases de datos de ficheros (pacman -F)."""
    repos(arch)
    item, error = _synced(arch, "-Fy")
    if error:
        raise AssertionError(error)
    return item


@lru_cache(maxsize=None)
def repo_package_names(arch: str) -> tuple[str, ...]:
    return tuple(repos(arch).pacman("-Sql").stdout.split())


@lru_cache(maxsize=None)
def package_files(arch: str, names: tuple[str, ...]) -> dict[str, set[str]]:
    """{paquete: rutas canónicas} con pacman -Fl; un paquete que no existe no sale."""
    found: dict[str, set[str]] = {}
    if not names:
        return found
    result = files_repos(arch).pacman("-Fl", "--machinereadable", *names, timeout=600)
    for line in result.stdout.splitlines():
        fields = line.split("\0")
        if len(fields) == 4:
            found.setdefault(fields[1], set()).add(canonical(fields[3]))
    return found


def owners(arch: str, paths: list[str]) -> dict[str, list[str]]:
    """{ruta canónica: [paquetes]} con pacman -F (para los mensajes)."""
    found: dict[str, list[str]] = {path: [] for path in paths}
    if not paths:
        return found
    result = files_repos(arch).pacman("-F", "--machinereadable", *paths, timeout=600)
    for line in result.stdout.splitlines():
        fields = line.split("\0")
        if len(fields) == 4 and canonical(fields[3]) in found:
            found[canonical(fields[3])].append(f"{fields[0]}/{fields[1]}")
    return found


# filesystem de Arch: /bin, /sbin y /usr/sbin enlazan a usr/bin; /lib,
# /lib64 y /usr/lib64 a usr/lib. Un paquete no puede tener ficheros en ellos.
MERGED_DIRS = (("usr/sbin/", "usr/bin/"), ("usr/lib64/", "usr/lib/"), ("bin/", "usr/bin/"),
               ("sbin/", "usr/bin/"), ("lib/", "usr/lib/"), ("lib64/", "usr/lib/"))


def canonical(path: str) -> str:
    path = path.lstrip("/")
    for old, new in MERGED_DIRS:
        if path.startswith(old):
            return new + path[len(old):]
    return path


# ---------------------------------------------------------------- cierre

@dataclass(frozen=True)
class Closure:
    packages: dict[str, str]          # nombre -> repo, lo que instalaría pacstrap
    missing: tuple[str, ...]          # nombres de la lista que no existen
    problems: tuple[tuple[str, str], ...]  # (id, mensaje) al resolver dependencias


def request(item: testlib.Edition) -> list[str]:
    """Lo que la lista pide a los repos: sin los paquetes del repo local."""
    local = testlib.local_packages()
    return list(dict.fromkeys(name for name in testlib.parse_package_list(item.list_path) if name not in local))


@lru_cache(maxsize=None)
def closure(item: testlib.Edition) -> Closure:
    source = repos(item.arch)
    targets = request(item)
    # --noconfirm acepta todos los miembros de un grupo, como pacstrap.
    result = source.pacman("-Sp", "--print-format", "PKG %n %r", *targets)
    missing = tuple(re.findall(r"^error: target not found: (\S+)$", result.stderr, re.MULTILINE))
    if missing:
        result = source.pacman("-Sp", "--print-format", "PKG %n %r", *[t for t in targets if t not in missing])
    packages = {}
    for line in result.stdout.splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[0] == "PKG":
            packages[fields[1]] = fields[2]
    name = list_name(item)
    problems = [
        (f"repo-dep:{name}:conflict:{first}:{second}",
         f"{item.package_list}: '{first}' y '{second}' están en conflicto y ninguno provee al otro: "
         f"pacstrap aborta con 'unresolvable package conflicts detected'")
        for first, second in fatal_conflicts(item.arch, packages)
    ]
    if result.returncode != 0:
        output = result.stdout + result.stderr
        unsatisfied = re.findall(r"unable to satisfy dependency '([^']+)' required by (\S+)", output)
        for dep, package in unsatisfied:
            dep_name = re.split(r"[<>=]", dep, maxsplit=1)[0]
            problems.append((f"repo-dep:{name}:{package}:{dep_name}",
                             f"{item.package_list}: '{package}' depende de '{dep}' y no hay quien lo dé en {item.arch}"))
        if not unsatisfied:
            problems.append((f"repo-dep:{name}:resolve", f"{item.package_list}: pacman -Sp falló:\n{output.strip()}"))
    return Closure(packages, missing, tuple(problems))


def parse_desc(text: str) -> dict[str, list[str]]:
    """Fichero desc de una base de datos sync: %CAMPO% y una línea por valor."""
    fields = {}
    for block in text.strip().split("\n\n"):
        lines = block.strip().split("\n")
        if lines and lines[0].startswith("%"):
            fields[lines[0].strip("%")] = lines[1:]
    return fields


@lru_cache(maxsize=None)
def sync_metadata(arch: str) -> dict[tuple[str, str], dict[str, list[str]]]:
    """{(repo, paquete): desc} leído de las bases de datos que bajó pacman -Sy."""
    source = repos(arch)
    found = {}
    for repo in source.names:
        with tarfile.open(source.dir / "db/sync" / f"{repo}.db", "r:*") as archive:
            for member in archive:
                if member.isfile() and member.name.endswith("/desc"):
                    fields = parse_desc(archive.extractfile(member).read().decode("utf-8", "replace"))
                    if fields.get("NAME"):
                        found[(repo, fields["NAME"][0])] = fields
    return found


def dep_name(spec: str) -> str:
    return re.split(r"[<>=:]", spec, maxsplit=1)[0]


def fatal_conflicts(arch: str, packages: dict[str, str]) -> list[tuple[str, str]]:
    """Pares del cierre que hacen abortar a pacstrap.

    pacman -Sp no mira conflictos (--print implica NOCONFLICTS), así que se
    repite aquí la comprobación de libalpm (sync.c, "check targets vs
    targets"): A conflicts=B (B por nombre o por provides) aborta, salvo que
    uno provea el nombre del otro, en cuyo caso pacman descarta el otro sin
    error. Solo conflictos sin versión: con versión no se compara.
    """
    metadata = sync_metadata(arch)
    info = {name: metadata.get((repo, name), {}) for name, repo in packages.items()}
    provides = {name: {dep_name(spec) for spec in fields.get("PROVIDES", [])} for name, fields in info.items()}
    satisfiers: dict[str, set[str]] = {}
    for name in info:
        for provided in {name} | provides[name]:
            satisfiers.setdefault(provided, set()).add(name)
    pairs = set()
    for name, fields in info.items():
        for conflict in fields.get("CONFLICTS", []):
            if dep_name(conflict) != conflict:
                continue
            for other in satisfiers.get(conflict, ()):
                if other != name and other not in provides[name] and name not in provides[other]:
                    pairs.add(tuple(sorted((name, other))))
    return sorted(pairs)


# ------------------------------------------------------------------- kernel

# grub_cpu con el que GRUB ejecuta grub.cfg en cada ISO. mkarchiso uefi.grub
# genera BOOTx64.EFI (x86_64-efi) y BOOTIA32.EFI (i386-efi) en x86_64,
# BOOTIA32.EFI en i686 y BOOTAA64.EFI (arm64-efi) en aarch64.
GRUB_CPU = {"x86_64": ("x86_64", "i386"), "i686": ("i386",), "aarch64": ("arm64",)}

GRUB_IF = re.compile(r'(?:el)?if\s+\[\s+"?\$\{?grub_cpu\}?"?\s+(==|=|!=)\s+"?([\w-]+)"?\s+\]')


def grub_active_lines(text: str, cpu: str) -> list[str]:
    """Líneas de un grub.cfg que se ejecutan con grub_cpu=cpu.

    Entiende `if/elif [ "${grub_cpu}" == "x" ]` (y !=) con else y fi; una
    condición distinta cuenta como posible en todas sus ramas.
    """
    stack: list[dict] = []
    active = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        word = line.split()[0].rstrip(";")
        if word in ("if", "elif"):
            match = GRUB_IF.match(line)
            value = None if not match else ((match.group(2) == cpu) != (match.group(1) == "!="))
            if word == "if":
                stack.append({"cur": value, "taken": value is True, "maybe": value is None})
                continue
            frame = stack[-1] if stack else {"cur": None, "taken": False, "maybe": True}
            frame["cur"] = False if frame["taken"] else (None if frame["maybe"] and value is not False else value)
        elif word == "else" and stack:
            frame = stack[-1]
            frame["cur"] = False if frame["taken"] else (None if frame["maybe"] else True)
        elif word == "fi" and stack:
            stack.pop()
            continue
        else:
            if all(frame["cur"] is not False for frame in stack):
                active.append(line)
            continue
        frame["taken"] = frame["taken"] or frame["cur"] is True
        frame["maybe"] = frame["maybe"] or frame["cur"] is None
    return active


def code_lines(path: Path) -> list[str]:
    return [line.strip() for line in testlib.read_text(path).splitlines()
            if line.strip() and not line.strip().startswith("#")]


def preset_dir(arch: str) -> Path:
    """Presets de mkinitcpio de la ISO. En aarch64, build.sh llama a
    scripts/apply-aarch64-mkinitcpio.sh, que aparta el linux.preset x86 y usa
    los de archiso/mkinitcpio/aarch64."""
    own = testlib.ROOT / "archiso/mkinitcpio" / arch
    return own if own.is_dir() else testlib.AIROOTFS / "etc/mkinitcpio.d"


def boot_references(item: testlib.Edition) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """({kernel: ficheros}, {initramfs: ficheros}) que arrancan o copian la ISO.

    Kernel = <k> de /boot/vmlinuz-<k> (pkgbase del paquete del kernel: el
    hook de mkinitcpio instala /boot/vmlinuz-$(cat .../pkgbase)) y el nombre
    de cada preset (mkinitcpio -p <pkgbase>). Solo cuentan los cargadores de
    bootmodes, el unpackfs que apply-calamares.sh deja para la arquitectura
    y los presets.
    """
    arch = item.arch
    bootmodes = " ".join(testlib.profile(arch)["bootmodes"])
    sources: list[tuple[Path, list[str]]] = []
    if "grub" in bootmodes:
        for path in sorted((testlib.ROOT / "archiso/grub").glob("*.cfg")):
            lines = []
            for cpu in GRUB_CPU[arch]:
                lines.extend(grub_active_lines(testlib.read_text(path), cpu))
            sources.append((path, lines))
    if "syslinux" in bootmodes:
        sources += [(path, code_lines(path)) for path in sorted((testlib.ROOT / "archiso/syslinux").glob("*.cfg"))]
    if "systemd-boot" in bootmodes:
        sources += [(path, code_lines(path)) for path in sorted((testlib.ROOT / "archiso/efiboot/loader/entries").glob("*.conf"))]
    if item.installer:
        modules = testlib.ROOT / "installer/calamares/modules"
        unpackfs = modules / arch / "unpackfs.conf"
        unpackfs = unpackfs if unpackfs.exists() else modules / "unpackfs.conf"
        sources.append((unpackfs, code_lines(unpackfs)))
    kernels: dict[str, set[str]] = {}
    initramfs: dict[str, set[str]] = {}
    for path, lines in sources:
        text = "\n".join(lines)
        for name in re.findall(r"\bvmlinuz-([A-Za-z0-9][\w.+-]*)", text):
            kernels.setdefault(name, set()).add(testlib.rel(path))
        for name in re.findall(r"\binitramfs-([A-Za-z0-9][\w.+-]*?)\.img\b", text):
            initramfs.setdefault(name, set()).add(testlib.rel(path))
    for preset in sorted(preset_dir(arch).glob("*.preset")):
        kernels.setdefault(preset.stem, set()).add(testlib.rel(preset))
        for name in re.findall(r"\bvmlinuz-([A-Za-z0-9][\w.+-]*)", "\n".join(code_lines(preset))):
            kernels.setdefault(name, set()).add(testlib.rel(preset))
    return kernels, initramfs


def preset_images(preset: Path) -> set[str]:
    """Initramfs que genera un preset: <p>_image de cada p en PRESETS."""
    script = 'source "$1"; for p in "${PRESETS[@]}"; do v="${p}_image"; printf "%s\\n" "${!v:-}"; done'
    result = testlib.run(["bash", "-c", script, "_", str(preset)], check=True)
    return {Path(line).name for line in result.stdout.split() if line}


# Fichero del kernel: /usr/lib/modules/<ver>/vmlinuz (Arch, Arch Linux 32) o
# /boot/Image (linux-aarch64 de Arch Linux ARM).
KERNEL_IMAGE = re.compile(r"usr/lib/modules/[^/]+/vmlinuz|boot/(?:vmlinuz|Image)[^/]*")


# ------------------------------------------------------------------- pruebas

class PackageListsTest(unittest.TestCase):
    """Cada lista resuelve en sus repos, como lo hará pacstrap."""

    def test_list_packages_exist(self):
        for item in editions():
            with self.subTest(lista=item.package_list):
                result = closure(item)
                findings = {}
                for name in result.missing:
                    hint = difflib.get_close_matches(name, repo_package_names(item.arch), n=1)
                    findings[f"repo-pkg:{list_name(item)}:{name}"] = (
                        f"{item.package_list}: '{name}' no está en los repos de {item.arch} "
                        f"({', '.join(repos(item.arch).names)}); pacstrap aborta con 'target not found'"
                        + (f". ¿Querías '{hint[0]}'?" if hint else "")
                    )
                testlib.assert_findings(self, f"repo-pkg:{list_name(item)}", findings)

    def test_list_dependencies_resolve(self):
        for item in editions():
            with self.subTest(lista=item.package_list):
                testlib.assert_findings(self, f"repo-dep:{list_name(item)}", dict(closure(item).problems))

    def test_installed_matches_closure(self):
        """testlib.installed() no da por instalado nada que pacman no instale."""
        local = testlib.local_packages()
        for item in editions():
            with self.subTest(lista=item.package_list):
                packages = closure(item).packages
                listed = testlib.packages(item)
                assumed = testlib.installed(item)
                findings = {}
                if "base" in listed:
                    for name in sorted(testlib.base_depends(item.arch) - packages.keys()):
                        findings[f"installed:{list_name(item)}:{name}"] = (
                            f"{item.package_list} lista base y testlib.BASE_DEPENDS da '{name}' por instalado, "
                            f"pero pacman no lo instala en {item.arch}"
                        )
                for name, rule in testlib.providers()["implicit"].items():
                    if name not in assumed or name in packages or name in listed:
                        continue
                    pulled_by = rule.get("pulled_by", []) if isinstance(rule, dict) else rule
                    triggers = [dep for dep in pulled_by if dep in assumed and dep != name]
                    if triggers and all(dep in local for dep in triggers):
                        continue  # lo traería un paquete del repo local: sus dependencias no se ven aquí
                    findings[f"installed:{list_name(item)}:{name}"] = (
                        f"[implicit] de tests/command_providers.toml dice que {', '.join(triggers)} trae '{name}', "
                        f"pero pacman no lo instala con {item.package_list}"
                    )
                testlib.assert_findings(self, f"installed:{list_name(item)}", findings)

    def test_base_depends(self):
        """testlib.BASE_DEPENDS ⊆ dependencias de `base` en los repos del contenedor."""
        result = repos(HOST_ARCH).pacman("-Si", "base")
        match = re.search(r"^Depends On\s*:\s*(.*)$", result.stdout, re.MULTILINE)
        self.assertIsNotNone(match, f"pacman -Si base no dio dependencias:\n{result.stdout}{result.stderr}")
        depends = {re.split(r"[<>=]", dep, maxsplit=1)[0] for dep in match.group(1).split() if dep != "None"}
        findings = {
            f"base-depends:{HOST_ARCH}:{name}": f"testlib.BASE_DEPENDS tiene '{name}', que ya no es dependencia de base en {HOST_ARCH}"
            for name in sorted(testlib.base_depends(HOST_ARCH) - depends)
        }
        testlib.assert_findings(self, f"base-depends:{HOST_ARCH}", findings)


class KernelTest(unittest.TestCase):
    """El kernel que nombran los arranques es el que instala la lista."""

    def test_kernel_matches_boot_configs(self):
        for item in editions():
            with self.subTest(lista=item.package_list):
                packages = closure(item).packages
                kernels, initramfs = boot_references(item)
                self.assertTrue(kernels, f"no se encontró ningún vmlinuz-<k> en los arranques de {item.arch}")
                native = item.arch == HOST_ARCH
                files = package_files(item.arch, tuple(sorted(kernels))) if native else {}
                findings = {}
                for kernel, where in sorted(kernels.items()):
                    if kernel not in packages:
                        listed = sorted(name for name in packages if name.startswith("linux"))
                        findings[f"kernel:{list_name(item)}:{kernel}"] = (
                            f"{', '.join(sorted(where))} arrancan vmlinuz-{kernel}, pero {item.package_list} no "
                            f"instala el paquete '{kernel}' (linux* en la lista: {', '.join(listed) or 'ninguno'})"
                        )
                    elif native and not any(KERNEL_IMAGE.fullmatch(path) for path in files.get(kernel, ())):
                        findings[f"kernel:{list_name(item)}:{kernel}"] = (
                            f"{', '.join(sorted(where))} usan '{kernel}' como kernel, pero ese paquete no instala "
                            f"/usr/lib/modules/*/vmlinuz ni /boot/Image"
                        )
                # El initramfs de la ISO lo genera el preset del kernel instalado
                # (o la plantilla de mkinitcpio: initramfs-<k>.img). En aarch64
                # publish-aarch64-kernel lo renombra después: no se comprueba.
                if preset_dir(item.arch) == testlib.AIROOTFS / "etc/mkinitcpio.d":
                    produced: set[str] = set()
                    for kernel in kernels:
                        preset = preset_dir(item.arch) / f"{kernel}.preset"
                        if kernel not in packages:
                            continue
                        if preset.exists():
                            produced |= preset_images(preset)
                        else:
                            produced |= {f"initramfs-{kernel}.img", f"initramfs-{kernel}-fallback.img"}
                    for name, where in sorted(initramfs.items()):
                        if f"initramfs-{name}.img" not in produced:
                            findings[f"kernel:{list_name(item)}:initramfs-{name}.img"] = (
                                f"{', '.join(sorted(where))} cargan initramfs-{name}.img, pero el preset de "
                                f"mkinitcpio solo genera {', '.join(sorted(produced)) or 'nada'}"
                            )
                testlib.assert_findings(self, f"kernel:{list_name(item)}", findings)


class ProviderTablesTest(unittest.TestCase):
    """command_providers.toml y unit_providers.toml dicen la verdad (pacman -F)."""

    def test_provider_tables(self):
        table = testlib.providers()
        local = testlib.local_packages()
        relevant = set().union(*(testlib.installed(item) for item in native_editions()))
        wanted: dict[tuple[str, str], tuple[str, list[str]]] = {}
        for command, package in table["commands"].items():
            wanted[("commands", command)] = (package, [f"usr/bin/{command}"])
        for path, package in table["paths"].items():
            wanted[("paths", path)] = (package, [canonical(path)])
        for unit, package in table["units"].items():
            names = [unit]
            template = re.fullmatch(r"([^@]+@)[^.]+(\.\w+)", unit)
            if template:
                names.append(template.group(1) + template.group(2))
            wanted[("units", unit)] = (package, [f"usr/lib/systemd/{kind}/{name}" for kind in ("system", "user") for name in names])
        packages = tuple(sorted({package for package, _ in wanted.values() if package not in local}))
        files = package_files(HOST_ARCH, packages)
        findings = {}
        misses: list[tuple[str, str, str, list[str]]] = []
        for (kind, name), (package, paths) in sorted(wanted.items()):
            if package in local:
                continue  # repo local: sus ficheros no están en ninguna base de datos de pacman
            key = f"providers:{kind}:{name}"
            if package not in files:
                if package in relevant:
                    findings[key] = f"[{kind}] {name} = '{package}': ese paquete no está en los repos de {HOST_ARCH}"
                continue  # de otra arquitectura: se comprueba en su runner
            if any(path in files[package] or path + "/" in files[package] for path in paths):
                continue
            misses.append((kind, name, package, paths))
        aliases = unit_aliases(sorted({package for kind, _, package, _ in misses if kind == "units"}))
        for kind, name, package, paths in list(misses):
            if kind == "units" and name in aliases.get(package, set()):
                misses.remove((kind, name, package, paths))
        real = owners(HOST_ARCH, sorted({path for _, _, _, paths in misses for path in paths}))
        for kind, name, package, paths in misses:
            found = sorted({owner for path in paths for owner in real.get(path, [])})
            what = f"/{paths[0]}" if kind != "units" else f"{name} (ni como fichero en usr/lib/systemd ni como Alias=)"
            findings[f"providers:{kind}:{name}"] = (
                f"[{kind}] {name} = '{package}', pero '{package}' no instala {what}"
                + (f"; es de {', '.join(found)}" if found else "; no la instala ningún paquete de los repos")
            )
        testlib.assert_findings(self, "providers", findings)


def unit_aliases(packages: list[str]) -> dict[str, set[str]]:
    """{paquete: Alias= de sus unidades}. Un alias (dbus-org.*.service,
    display-manager.service) no es un fichero del paquete: lo crea
    `systemctl enable` a partir de [Install] Alias=. Hace falta el paquete."""
    found: dict[str, set[str]] = {}
    if not packages:
        return found
    source = files_repos(HOST_ARCH)
    result = source.pacman("-Sw", "--nodeps", "--nodeps", *packages, root=True, timeout=900)
    if result.returncode != 0:
        raise AssertionError(f"pacman -Sw {' '.join(packages)} falló:\n{result.stdout}{result.stderr}")
    for package in packages:
        url = source.pacman("-Sp", "--nodeps", "--nodeps", "--print-format", "%l", package).stdout.strip()
        archive = source.cache / url.rsplit("/", 1)[-1]
        target = WORK / "units" / package
        target.mkdir(parents=True, exist_ok=True)
        testlib.run(["bsdtar", "-xf", str(archive), "-C", str(target), "--include", "usr/lib/systemd/*"])
        aliases = set()
        for unit in target.rglob("*"):
            if unit.is_file() and not unit.is_symlink():
                section = None
                for line in testlib.read_text(unit).splitlines():
                    line = line.strip()
                    if line.startswith("["):
                        section = line
                    elif section == "[Install]" and line.startswith("Alias="):
                        aliases.update(line.split("=", 1)[1].split())
        found[package] = aliases
    return found


if __name__ == "__main__":
    unittest.main()
