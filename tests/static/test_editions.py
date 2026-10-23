"""Matriz edición × arquitectura: build.sh, testlib.EDITIONS y las listas.

scripts/cli/build.sh decide qué combinaciones existen (ediciones aceptadas,
solo niri y pi en aarch64, i686 sin Calamares), qué lista de paquetes recibe
pacstrap y con qué comando arranca la sesión Live. testlib.EDITIONS es la
copia que usan las demás pruebas. Aquí se comprueba:

- que build.sh y EDITIONS no se separan (pares, lista, SESSION_CMD, instalador);
- que edition-session.sh (sistema instalado) y stamp-os-release.sh conocen
  todas las ediciones y no caen en el brazo por defecto (niri);
- que las listas archiso/packages.* están limpias: mkarchiso pasa cada línea
  tal cual a pacstrap (`sed 's/#.*//'`, sin quitar espacios), así que un
  espacio, un CRLF o un `echo foo >> lista` sin salto final rompen el build;
- que cada edición trae los paquetes que su configuración da por hechos
  (tabla REQUIRED más los que se derivan de unpackfs, profiledef, Calamares y
  la sesión). Las unidades que activa services.sh las cubre test_systemd_units.
- que pacman.<arch>.conf tiene la arquitectura, [churros] primero y
  [multilib] si alguna lista pide lib32-*.

Un paquete que no está en la lista pero llega como dependencia cuenta como
instalado si figura en [pulled_by] de tests/unit_providers.toml (comprobado
con pacman -Sp de cada lista en el contenedor Arch).

Ejecutar: python3 -m unittest tests.static.test_editions -v
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

from tests import testlib

ROOT = testlib.ROOT
BUILD_SH = ROOT / "scripts/cli/build.sh"
EDITION_LIB = testlib.AIROOTFS / "usr/share/churros/scripts/edition-session.sh"
STAMP = ROOT / "branding/stamp-os-release.sh"
CALAMARES = ROOT / "installer/calamares/modules"
UNKNOWN_EDITION = "zz-sin-edicion"
LIST_NAME = re.compile(r"packages\.(?:([a-z0-9-]+)\.)?(x86_64|aarch64|i686)")

# Comando de [initial_session] que escribe build.sh -> (escritorio de
# testlib.Edition, paquetes que ese comando ejecuta). pacman -F:
# /usr/bin/startxfce4 es de xfce4-session y /usr/bin/startx de xorg-xinit
# (churros-xfce-session hace exec de los dos); churros-pi-session lanza
# waybar y hace exec de /usr/bin/labwc.
SESSIONS = {
    "niri": ("niri", ("niri",)),
    # startx (xorg-xinit) necesita el servidor X: sin xorg-server, pantalla negra.
    "/usr/bin/churros-xfce-session": ("xfce", ("xfce4-session", "xorg-xinit", "xorg-server")),
    "/usr/bin/churros-pi-session": ("labwc", ("labwc", "waybar")),
}

# Paquetes que la configuración da por instalados. (paquete, ediciones
# ['all' o 'installer'], fichero que lo necesita, patrón que demuestra que lo
# sigue necesitando o None, motivo). Si el patrón desaparece del fichero la
# fila está obsoleta y la prueba lo dice, para que la tabla no mienta.
REQUIRED = (
    ("base", "all", None, None,
     "pacstrap solo instala la lista: base trae systemd, pacman y coreutils"),
    ("mkinitcpio-archiso", "all", "archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf",
     r"HOOKS=\([^)]*\barchiso\b", "hooks archiso* del initramfs de la Live"),
    ("greetd", "all", "scripts/cli/build.sh", r"etc/greetd/config\.toml",
     "build.sh escribe el autologin de greetd de la sesión Live"),
    ("greetd-regreet", "all", "scripts/cli/build.sh", r"cage -s -- regreet",
     "default_session de greetd: cage -s -- regreet"),
    ("cage", "all", "scripts/cli/build.sh", r"cage -s -- regreet",
     "default_session de greetd: cage -s -- regreet"),
    ("zsh", "all", "archiso/airootfs/root/scripts/users.sh", r"-s /bin/zsh",
     "shell del usuario churros (useradd -s /bin/zsh)"),
    ("zsh", "all", "archiso/airootfs/etc/passwd", r"(?m)^root:.*:/usr/bin/zsh$",
     "shell de root en etc/passwd"),
    ("sudo", "all", "archiso/airootfs/root/scripts/users.sh", r"/etc/sudoers\.d",
     "sudo sin contraseña del usuario Live"),
    ("sudo", "installer", "archiso/airootfs/usr/local/bin/calamares", r"exec sudo -n",
     "el lanzador de Calamares se eleva con sudo -n"),
    ("grub", "installer", "installer/calamares/modules/bootloader.conf",
     r'grubInstall:\s*"grub-install"', "el paso bootloader de Calamares ejecuta grub-install"),
    ("efibootmgr", "installer", "installer/calamares/modules/bootloader.conf",
     r'efiBootMgr:\s*"efibootmgr"', "el paso bootloader de Calamares ejecuta efibootmgr"),
    ("qemu-guest-agent", "all", None, None,
     "tests/vm (arranque en QEMU) habla con la Live por qemu-guest-agent"),
)

# Hook de mkinitcpio que Calamares añade (initcpiocfg) -> paquete que lo trae
# (pacman -F /usr/lib/initcpio/install/<hook>). Sin él mkinitcpio falla con
# "Hook 'plymouth' cannot be found" y la instalación se para en initcpio.
INITCPIO_HOOK_PACKAGES = {"plymouth": "plymouth"}


# ---------------------------------------------------------------- build.sh

def case_arms(text: str, subject: str, needle: str) -> list[tuple[list[str], str]]:
    """Brazos (patrones, cuerpo) del primer `case "$subject" in` que contiene needle."""
    for match in re.finditer(r'case "\$%s" in\n(.*?)\n\s*esac' % subject, text, re.S):
        if needle in match.group(1):
            arms = re.findall(r'^\s*([^\s()#][^()\n]*?)\)(.*?);;', match.group(1), re.M | re.S)
            return [(patterns.split("|"), body.strip()) for patterns, body in arms]
    return []


def if_blocks(text: str) -> list[tuple[list[tuple[str, str, str]], str]]:
    """`if [ "$X" op v ] && ...; then CUERPO` -> ([(X, op, v)], rama then)."""
    blocks = []
    pattern = r'^\s*if ((?:\[ [^\]]+ \]\s*(?:&&\s*)?)+); then\n(.*?)\n\s*(?:fi|else|elif)\b'
    for conditions, body in re.findall(pattern, text, re.M | re.S):
        parsed = re.findall(r'\[ "\$(\w+)" (!?=) "?([\w.-]+)"? \]', conditions)
        if len(parsed) == conditions.count("["):
            blocks.append((parsed, body))
    return blocks


@lru_cache(maxsize=None)
def build_matrix() -> dict:
    """Lo que build.sh acepta, leído de su código (no de una copia)."""
    text = testlib.read_text(BUILD_SH)
    arches = set()
    for patterns, body in case_arms(text, "TARGET_ARCH", 'TARGET_ARCH="aarch64"'):
        if patterns != ["*"]:
            assigned = re.search(r'TARGET_ARCH="?([\w-]+)"?', body)
            arches |= {assigned.group(1)} if assigned else set(patterns)
    editions, allowed, no_installer, default, other_list = set(), {}, set(), None, None
    for conditions, body in if_blocks(text):
        variables = {var for var, _, _ in conditions}
        excluded = {value for var, op, value in conditions if var == "EDITION" and op == "!="}
        if variables == {"EDITION"} and len(conditions) > 1 and "exit 1" in body:
            editions = excluded
        arch_eq = [value for var, op, value in conditions if var == "TARGET_ARCH" and op == "="]
        if arch_eq and excluded and "exit 1" in body:
            allowed[arch_eq[0]] = excluded
        if arch_eq and len(conditions) == 1 and re.search(r'^\s*CALAMARES_PKG=""', body, re.M):
            no_installer.add(arch_eq[0])
        list_match = re.search(r'^\s*PKG_LIST="([^"]+)"', body, re.M)
        if variables == {"EDITION"} and len(conditions) == 1 and list_match:
            default, other_list = next(iter(excluded)), list_match.group(1)
    default_list = re.search(r'^PACKAGE_LIST="([^"]+)"', text, re.M)
    sessions = {}
    for patterns, body in case_arms(text, "EDITION", "SESSION_CMD="):
        command = re.search(r'SESSION_CMD="([^"]*)"', body)
        for pattern in patterns:
            if pattern != "*" and command:
                sessions[pattern] = command.group(1)
    pairs = {}
    for name in editions:
        for arch in arches:
            if arch in allowed and name not in allowed[arch]:
                continue
            template = default_list.group(1) if name == default else other_list
            path = re.sub(r"\$\{?EDITION\}?", name, re.sub(r"\$\{?TARGET_ARCH\}?", arch, template or ""))
            # build.sh sale con "Error: <lista> not found!" si una edición
            # que no es la de por defecto no tiene lista para esa arquitectura.
            if name != default and not (ROOT / path).is_file():
                continue
            pairs[(name, arch)] = path
    return {"arches": arches, "editions": editions, "allowed": allowed, "default": default,
            "no_installer": no_installer, "sessions": sessions, "pairs": pairs}


# ------------------------------------------------------------ paquetes

@lru_cache(maxsize=None)
def available(item: testlib.Edition) -> frozenset[str]:
    """testlib.installed() más lo que llega como dependencia ([pulled_by])."""
    names = set(testlib.installed(item))
    pulled_by = testlib.providers().get("pulled_by", {})
    changed = True
    while changed:
        changed = False
        for package, parents in pulled_by.items():
            if package not in names and any(parent in names for parent in parents):
                names.add(package)
                changed = True
    return frozenset(names)


def calamares_conf(arch: str, name: str) -> Path:
    """Fichero que apply-calamares.sh despliega: modules/<arch>/ pisa al común."""
    override = CALAMARES / arch / name
    return override if override.exists() else CALAMARES / name


def calamares_block() -> list[str]:
    """Paquetes del bloque '# Calamares installer dependencies' de packages.x86_64.

    Calamares se desempaqueta con bsdtar (customize_airootfs.sh): pacman no
    resuelve sus dependencias y la lista tiene que traerlas.
    """
    entries, inside = [], False
    for line in testlib.read_text(ROOT / "archiso/packages.x86_64").splitlines():
        if re.match(r"#\s*Calamares installer dependencies", line):
            inside = True
            continue
        if inside:
            if not line.strip() or line.lstrip().startswith("#"):
                break
            entries.append(line.split("#", 1)[0].strip())
    return entries


def kernels(arch: str) -> dict[str, str]:
    """Paquete del kernel -> fichero que arranca /boot/vmlinuz-<paquete>."""
    found = {}
    unpackfs = calamares_conf(arch, "unpackfs.conf")
    for name in re.findall(r'destination:\s*"/boot/vmlinuz-([\w.+-]+)"', testlib.read_text(unpackfs)):
        found[name] = testlib.rel(unpackfs)
    if "bios.syslinux" in testlib.profile(arch)["bootmodes"]:
        for cfg in sorted((ROOT / "archiso/syslinux").glob("*.cfg")):
            for name in re.findall(r"^\s*LINUX\s+\S*/vmlinuz-([\w.+-]+)\s*$", testlib.read_text(cfg), re.M):
                found.setdefault(name, testlib.rel(cfg))
    return found


def requirements(item: testlib.Edition) -> dict[str, list[str]]:
    """{paquete: [motivos]} que la edición tiene que traer."""
    needs: dict[str, list[str]] = {}

    def need(package: str, why: str) -> None:
        needs.setdefault(package, []).append(why)

    for package, scope, path, pattern, why in REQUIRED:
        if scope == "installer" and not item.installer:
            continue
        need(package, f"{path}: {why}" if path else why)
    aliases = testlib.kernel_aliases()
    listed = set(testlib.packages(item))
    for package, source in kernels(item.arch).items():
        # vmlinuz-linux puede ser un enlace (customize_airootfs.sh) al kernel propio.
        provider = aliases.get(package)
        if provider and provider in listed:
            need(provider, f"{source} arranca /boot/vmlinuz-{package}, enlace a vmlinuz-{provider}")
        else:
            need(package, f"{source} arranca /boot/vmlinuz-{package}")
    if item.desktop is not None:
        for package in SESSIONS.get(item.session_cmd, ("", ()))[1]:
            need(package, f"la sesión Live ejecuta {item.session_cmd} (build.sh SESSION_CMD)")
    if item.installer:
        for package in calamares_block():
            need(package, "dependencia de Calamares (bloque 'Calamares installer dependencies' de packages.x86_64)")
        pacman_init = calamares_conf(item.arch, "shellprocess-pacman.conf")
        for names in re.findall(r"pacman-key --populate ([\w ]+)", testlib.read_text(pacman_init)):
            for keyring in names.split():
                need(f"{keyring}-keyring", f"{testlib.rel(pacman_init)}: pacman-key --populate {keyring}")
    return needs


# ------------------------------------------------------------------ pruebas

class BuildMatrixTest(unittest.TestCase):
    """testlib.EDITIONS es lo que build.sh acepta, ni más ni menos."""

    def test_build_sh_parsed(self):
        matrix = build_matrix()
        self.assertTrue(matrix["arches"], "no encuentro el case de TARGET_ARCH en build.sh")
        self.assertTrue(matrix["editions"], "no encuentro la validación de --edition en build.sh")
        self.assertTrue(matrix["default"], "no encuentro la edición por defecto (if != ...; PKG_LIST=) en build.sh")
        self.assertTrue(matrix["sessions"], "no encuentro el case de SESSION_CMD en build.sh")

    def test_editions_mirror_build_sh(self):
        matrix = build_matrix()
        accepted = set(matrix["pairs"])
        declared = {(item.name, item.arch) for item in testlib.EDITIONS}
        self.assertEqual(sorted(accepted - declared), [],
                         "build.sh acepta estas combinaciones y testlib.EDITIONS no las tiene")
        self.assertEqual(sorted(declared - accepted), [],
                         "testlib.EDITIONS tiene combinaciones que build.sh rechaza o sin lista")
        for item in testlib.EDITIONS:
            with self.subTest(edition=item.id):
                self.assertEqual(matrix["pairs"][(item.name, item.arch)], item.package_list,
                                 "build.sh copia otra lista de paquetes")
                self.assertTrue(item.list_path.is_file(), f"falta {item.package_list}")
                self.assertIn(item.name, matrix["sessions"],
                              f"build.sh no tiene brazo SESSION_CMD para '{item.name}': el build se para")
                self.assertEqual(matrix["sessions"][item.name], item.session_cmd,
                                 "SESSION_CMD de build.sh distinto del de testlib.EDITIONS")
                self.assertEqual(item.arch not in matrix["no_installer"], item.installer,
                                 "build.sh integra Calamares (o lo omite) al revés que testlib.EDITIONS")

    def test_session_table(self):
        """Cada SESSION_CMD está en SESSIONS, su wrapper es ejecutable y el escritorio cuadra."""
        for item in testlib.EDITIONS:
            with self.subTest(edition=item.id):
                self.assertIn(item.session_cmd, SESSIONS,
                              f"añade '{item.session_cmd}' a SESSIONS con su escritorio y sus paquetes")
                desktop, packages = SESSIONS[item.session_cmd]
                if item.session_cmd.startswith("/"):
                    self.assertTrue(testlib.airootfs(item.session_cmd).is_file(),
                                    f"{item.session_cmd} no está en el airootfs")
                    spec = testlib.profile(item.arch)["file_permissions"].get(item.session_cmd, "")
                    self.assertTrue(testlib.mode_is_executable(spec),
                                    f"{item.session_cmd} sin modo ejecutable en file_permissions "
                                    f"({item.arch}): mkarchiso lo copia 0644 y greetd no puede lanzarlo")
                if item.desktop is None:
                    # i686: la lista todavía no trae el escritorio (packages.i686).
                    self.assertFalse(set(packages) <= available(item),
                                     f"{item.package_list} ya trae {packages}: pon desktop='{desktop}' en testlib.EDITIONS")
                else:
                    self.assertEqual(item.desktop, desktop,
                                     "el escritorio de testlib.EDITIONS no es el que lanza la sesión")

    def test_installed_session_table(self):
        """edition-session.sh: cada edición tiene su brazo y su sesión existe."""
        names = sorted({item.name for item in testlib.EDITIONS}) + [UNKNOWN_EDITION]
        script = ('. "$1"; shift; for e; do if out=$(churros_session_command "$e"); '
                  'then printf "%s\\t%s\\n" "$e" "$out"; else printf "%s\\t-\\n" "$e"; fi; done')
        result = testlib.run(["bash", "-c", script, "_", str(EDITION_LIB), *names], check=True)
        table = dict(line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line)
        default = build_matrix()["default"]
        for item in testlib.EDITIONS:
            with self.subTest(edition=item.id):
                command = table.get(item.name)
                self.assertIsNotNone(command, result.stdout)
                if item.name != default:
                    self.assertNotEqual(command, table[UNKNOWN_EDITION],
                                        f"churros_session_command no tiene brazo para '{item.name}': "
                                        "el sistema instalado arrancaría la sesión por defecto")
                if command == "-":
                    continue  # server: el sistema instalado no tiene sesión gráfica
                spec = testlib.profile(item.arch)["file_permissions"].get(command, "")
                self.assertTrue(testlib.airootfs(command).is_file() and testlib.mode_is_executable(spec),
                                f"{command} (sesión del sistema instalado) no existe o no es ejecutable "
                                f"según file_permissions ({item.arch})")
                if item.session_cmd.startswith("/"):
                    self.assertEqual(command, item.session_cmd,
                                     "la sesión instalada y la Live (build.sh SESSION_CMD) no coinciden")

    def test_os_release_variants(self):
        """stamp-os-release.sh, ejecutado como en build.sh y customize_airootfs.sh."""
        with tempfile.TemporaryDirectory() as tmp:
            for name in sorted({item.name for item in testlib.EDITIONS}):
                with self.subTest(edition=name):
                    target = Path(tmp) / f"os-release-{name}"
                    shutil.copyfile(ROOT / "branding/files/os-release", target)
                    testlib.run(["bash", str(STAMP), str(target), "2.0.0", name], check=True)
                    fields = dict(line.split("=", 1) for line in testlib.read_text(target).splitlines() if "=" in line)
                    self.assertEqual(fields.get("VARIANT_ID", "").strip('"'), name,
                                     "stamp-os-release.sh no tiene variante para esta edición")
                    self.assertEqual(fields.get("VERSION_ID"), "2.0.0")


class PackageListTest(unittest.TestCase):
    """archiso/packages.*: limpias y con lo que la configuración necesita."""

    def lists(self) -> list[Path]:
        return sorted(path for path in (ROOT / "archiso").glob("packages.*")
                      if path.is_file() and LIST_NAME.fullmatch(path.name))

    def test_every_list_has_an_edition(self):
        used = {item.list_path for item in testlib.EDITIONS}
        orphans = [path.name for path in self.lists() if path not in used]
        self.assertEqual(orphans, [], "listas que build.sh no usa con ninguna edición")

    def test_lists_are_clean(self):
        findings = {}
        for path in self.lists():
            data = path.read_bytes()
            name = path.name
            if data and not data.endswith(b"\n"):
                findings[f"pkg-list:{name}:sin-salto-final"] = (
                    f"{name} no termina en salto de línea: `echo paquete >> {name}` lo pegaría a la última entrada")
            if b"\r" in data:
                findings[f"pkg-list:{name}:crlf"] = f"{name} tiene finales CRLF: pacstrap recibe 'paquete\\r'"
            tokens = []
            for line in data.decode("utf-8", "replace").replace("\r", "").split("\n"):
                entry = line.split("#", 1)[0]  # mkarchiso: sed 's/#.*//'
                if not entry.strip():
                    continue
                if entry != entry.strip() or "\t" in entry:
                    findings[f"pkg-list:{name}:espacios:{entry.strip()}"] = (
                        f"{name}: '{entry}' lleva espacios o tabuladores; mkarchiso pasa la línea entera a pacstrap")
                words = entry.split()
                if len(words) > 1:
                    findings[f"pkg-list:{name}:varios:{entry.strip()}"] = f"{name}: un paquete por línea, no '{entry.strip()}'"
                for word in words:
                    # makepkg: alfanuméricos y @._+-, sin empezar por guion ni punto
                    if not re.fullmatch(r"[A-Za-z0-9@_+][A-Za-z0-9@._+-]*", word):
                        findings[f"pkg-list:{name}:nombre:{word}"] = f"{name}: '{word}' no es un nombre de paquete válido"
                    tokens.append(word)
            for word, count in Counter(tokens).items():
                if count > 1:
                    findings[f"pkg-list:{name}:duplicado:{word}"] = f"{name}: '{word}' aparece {count} veces"
        testlib.assert_findings(self, "pkg-list", findings)

    def test_rules_still_apply(self):
        """Cada fila de REQUIRED cita un fichero y un patrón que siguen ahí."""
        for package, _, path, pattern, _ in REQUIRED:
            if path:
                with self.subTest(package=package, path=path):
                    self.assertTrue((ROOT / path).is_file(), f"{path} ya no existe: revisa REQUIRED")
                    self.assertRegex(testlib.read_text(ROOT / path), pattern,
                                     f"{path} ya no necesita '{package}' así: actualiza la fila de REQUIRED")
        self.assertTrue(calamares_block(), "no encuentro '# Calamares installer dependencies' en packages.x86_64")
        for arch in sorted({item.arch for item in testlib.EDITIONS}):
            self.assertTrue(kernels(arch), f"no encuentro /boot/vmlinuz-* en unpackfs.conf de {arch}")

    def test_required_packages(self):
        findings = {}
        initcpio = testlib.require_module(self, "yaml").safe_load(
            testlib.read_text(CALAMARES / "initcpiocfg.conf")) or {}
        hooks = initcpio.get("hooks") or {}
        initcpio_hooks = [hook for key in ("prepend", "append") for hook in hooks.get(key) or []]
        for item in testlib.EDITIONS:
            needs = requirements(item)
            if item.installer:
                for hook in initcpio_hooks:
                    if hook in INITCPIO_HOOK_PACKAGES:
                        needs.setdefault(INITCPIO_HOOK_PACKAGES[hook], []).append(
                            f"installer/calamares/modules/initcpiocfg.conf añade el hook '{hook}'")
            have = available(item)
            for package, reasons in sorted(needs.items()):
                if package not in have:
                    findings[f"edition-pkg:{item.id}:{package}"] = (
                        f"{item.id}: falta '{package}' en {item.package_list} ({'; '.join(reasons)})")
            # mkarchiso (_validate_requirements_bootmode_bios.syslinux) busca
            # 'syslinux' literalmente en la lista, no en sus dependencias.
            if "bios.syslinux" in testlib.profile(item.arch)["bootmodes"] and "syslinux" not in testlib.packages(item):
                findings[f"edition-pkg:{item.id}:syslinux"] = (
                    f"{item.id}: bootmode bios.syslinux sin 'syslinux' en {item.package_list}: mkarchiso aborta")
        testlib.assert_findings(self, "edition-pkg", findings)


class LocalPackagesTest(unittest.TestCase):
    """Lo que instalan los paquetes locales (pkgs/*/PKGBUILD) no está también en el airootfs."""

    def test_local_packages_do_not_collide_with_airootfs(self):
        # mkarchiso copia el airootfs antes de pacstrap: si un paquete trae un
        # fichero que ya está ahí, pacman aborta con "conflicting files ...
        # exists in filesystem" y no hay ISO (el preset de linux-churrosvyper).
        findings = {}
        recipes = sorted((ROOT / "pkgs").glob("*/PKGBUILD"))
        for recipe in recipes:
            pkgbase = recipe.parent.name
            text = testlib.read_text(recipe)
            for raw in re.findall(r'"\$pkgdir(/[^"\s]+)"', text):
                path = raw.replace("$pkgbase", pkgbase).replace("${pkgbase}", pkgbase)
                if "$" in path or "*" in path:
                    continue  # rutas que dependen de variables del build: no se modelan
                target = testlib.AIROOTFS / path.lstrip("/")
                if target.is_file() or target.is_symlink():  # un directorio común no choca
                    findings[f"pkg-collision:{pkgbase}:{path}"] = (
                        f"{testlib.rel(recipe)} instala {path}, que también está en archiso/airootfs: mkarchiso "
                        "lo copia antes de pacstrap y pacman aborta ('exists in filesystem')")
        testlib.assert_findings(self, "pkg-collision", findings)


class BootLinksTest(unittest.TestCase):
    """Enlaces en /boot que crean los scripts del chroot de build.

    mkarchiso copia /boot fuera del airootfs con `cp -a` (un enlace sigue
    siendo enlace) y luego `install` copia /boot/vmlinuz-* e initramfs-*.img
    a la ISO resolviendo los enlaces en el equipo de build: un destino
    absoluto apunta al /boot del host. En el CI no existe y no hay ISO; en un
    equipo con ese kernel instalado, la ISO se lleva el kernel del host.
    """

    def test_boot_links_are_relative(self):
        scripts = [ROOT / "branding/customize_airootfs.sh",
                   *sorted((testlib.AIROOTFS / "root/scripts").glob("*.sh"))]
        findings = {}
        for script in scripts:
            for line in testlib.read_text(script).splitlines():
                try:
                    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
                    lexer.whitespace_split = True
                    lexer.commenters = "#"
                    tokens = list(lexer)
                except ValueError:
                    continue
                command: list[str] = []
                for token in tokens + [";"]:
                    if token and set(token) <= set(";&|()"):
                        words = [word for word in command if word not in ("then", "do", "else")]
                        if words[:1] == ["ln"]:
                            flags = [word for word in words[1:] if word.startswith("-")]
                            args = [word for word in words[1:] if not word.startswith("-")]
                            if any(flag == "--symbolic" or (not flag.startswith("--") and "s" in flag) for flag in flags) \
                                    and len(args) == 2 and args[1].startswith("/boot/") and args[0].startswith("/"):
                                findings[f"boot-link:{testlib.rel(script)}:{args[1]}"] = (
                                    f"{testlib.rel(script)}: `ln -s {args[0]} {args[1]}` es absoluto; mkarchiso lo "
                                    "resuelve fuera del chroot, en el /boot del equipo de build. Usa un destino "
                                    "relativo (sin /boot/).")
                        command = []
                    else:
                        command.append(token)
        self.assertIn("linux", testlib.kernel_aliases(), "no encuentro el enlace vmlinuz-linux en customize_airootfs.sh")
        testlib.assert_findings(self, "boot-link", findings)


class PacmanConfTest(unittest.TestCase):
    """pacman.<arch>.conf con el que pacstrap construye cada arquitectura."""

    @staticmethod
    def parse(path: Path) -> list[tuple[str, dict[str, list[str]]]]:
        sections: list[tuple[str, dict[str, list[str]]]] = []
        for line in testlib.read_text(path).splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            header = re.fullmatch(r"\[([^\]]+)\]", line)
            if header:
                sections.append((header.group(1), {}))
            elif sections:
                key, _, value = line.partition("=")
                sections[-1][1].setdefault(key.strip(), []).append(value.strip())
        return sections

    def test_pacman_conf(self):
        for arch in sorted({item.arch for item in testlib.EDITIONS}):
            with self.subTest(arch=arch):
                path = ROOT / "archiso" / testlib.profile(arch)["pacman_conf"]
                sections = self.parse(path)
                options = dict(sections).get("options", {})
                self.assertEqual(options.get("Architecture"), [arch], f"{path.name}: Architecture")
                repos = [(name, keys) for name, keys in sections if name != "options"]
                self.assertTrue(repos, f"{path.name} sin repositorios")
                # pacman.conf(5): gana el primer repositorio que tiene el
                # paquete; bazaar/libdex parcheados tienen que salir de [churros].
                name, keys = repos[0]
                self.assertEqual(name, "churros", f"{path.name}: [churros] tiene que ser el primer repositorio")
                self.assertEqual(keys.get("Server"), ["file:///root/packages"], f"{path.name}: Server de [churros]")
                levels = " ".join(keys.get("SigLevel", [])).split()
                self.assertTrue({"Optional", "Never", "PackageOptional", "PackageNever"} & set(levels),
                                f"{path.name}: los paquetes de [churros] no van firmados; SigLevel tiene que admitirlo")
                lib32 = sorted({pkg for item in testlib.EDITIONS if item.arch == arch
                                for pkg in testlib.packages(item) if pkg.startswith("lib32-")})
                if lib32:
                    self.assertIn("multilib", [repo for repo, _ in repos],
                                  f"{path.name} sin [multilib] y las listas piden {lib32}")


if __name__ == "__main__":
    unittest.main()
