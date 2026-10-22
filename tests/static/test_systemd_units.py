"""Unidades systemd, enlaces y hooks de pacman del airootfs.

Todo lo que el perfil activa en el arranque de la Live o en cada transacción
de pacman tiene que existir en cada edición:

- unidades de archiso/airootfs/etc/systemd/** y de etc/skel/.config/systemd/user:
  estructura INI, secciones que systemd conoce para su tipo, claves Exec*,
  Type=, ExecStart (systemd rechaza un .service sin él), nombre de los .mount,
  y que cada Exec* exista: fichero del airootfs o comando de un paquete de la
  lista de la edición (el modo 0755 en file_permissions lo exige
  test_file_permissions, categoría exec-mode, para no contar dos veces el
  mismo fallo);
- enlaces de *.wants/*.requires y alias (dbus-org.*): la unidad a la que
  apuntan está en el airootfs o la instala un paquete de la edición
  (tests/unit_providers.toml);
- `enable_unit X` y `systemctl mask X` de root/scripts/services.sh y las
  unidades de Calamares services-systemd.conf (ediciones con instalador);
- hooks de pacman (etc/pacman.d/hooks/*.hook) según alpm-hooks(5): secciones,
  claves y valores, Exec absoluto y existente, Depends instalado.

Cuando un fallo se da en todas las ediciones el id lleva '*' en lugar de la
edición: es un solo problema, no seis.

Ejecutar: python3 -m unittest tests.static.test_systemd_units -v
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import unittest

from tests import testlib

AIROOTFS = testlib.AIROOTFS
SERVICES_SH = AIROOTFS / "root/scripts/services.sh"
CALAMARES = testlib.ROOT / "installer/calamares/modules"
HOOKS_DIR = AIROOTFS / "etc/pacman.d/hooks"

# Directorios de unidades dentro del airootfs y su ámbito (systemd.unit(5)).
UNIT_DIRS = {
    "etc/systemd/system": "system",
    "usr/lib/systemd/system": "system",
    "etc/systemd/user": "user",
    "usr/lib/systemd/user": "user",
    "etc/skel/.config/systemd/user": "user",
}

# Sección propia de cada tipo de unidad (systemd.unit(5)); además van [Unit],
# [Install] y las X-* que systemd ignora a propósito.
TYPE_SECTIONS = {
    ".service": "Service", ".socket": "Socket", ".mount": "Mount",
    ".automount": "Automount", ".swap": "Swap", ".timer": "Timer",
    ".path": "Path", ".slice": "Slice", ".scope": "Scope", ".target": None,
}

# Secciones de los ficheros de configuración de demonios de systemd
# (journald.conf(5), logind.conf(5), resolved.conf(5), ...).
CONF_SECTIONS = {
    "journald.conf.d": {"Journal"}, "logind.conf.d": {"Login"},
    "resolved.conf.d": {"Resolve"}, "timesyncd.conf.d": {"Time"},
    "system.conf.d": {"Manager"}, "user.conf.d": {"Manager"},
    "coredump.conf.d": {"Coredump"}, "sleep.conf.d": {"Sleep"},
    "oomd.conf.d": {"OOM"}, "pstore.conf.d": {"PStore"},
}

# Claves Exec* de systemd 262 (`systemd --dump-configuration-items`). Una
# clave mal escrita (ExecStrat=) se ignora con un aviso y la unidad se queda
# sin comando.
EXEC_COMMANDS = {
    "Service": {"ExecCondition", "ExecStartPre", "ExecStart", "ExecStartPost",
                "ExecReload", "ExecReloadPost", "ExecStop", "ExecStopPost"},
    "Socket": {"ExecStartPre", "ExecStartPost", "ExecStopPre", "ExecStopPost"},
}
EXEC_OTHER = {"ExecPaths", "ExecSearchPath"}
SERVICE_TYPES = {"simple", "exec", "forking", "oneshot", "dbus", "notify", "notify-reload", "idle"}
TIMER_TRIGGERS = {"OnActiveSec", "OnBootSec", "OnStartupSec", "OnUnitActiveSec",
                  "OnUnitInactiveSec", "OnCalendar", "OnClockChange", "OnTimezoneChange"}
# Dependencias que hacen fallar la unidad si la otra no existe (Wants= y el
# orden After=/Before= toleran unidades que faltan).
HARD_DEPS = {"Requires", "Requisite", "BindsTo"}
# systemctl <verbo> <unidad> dentro de un Exec*: la unidad tiene que existir.
SYSTEMCTL_UNIT_VERBS = {"start", "restart", "try-restart", "reload-or-restart", "enable", "reload"}

# alpm-hooks(5) y libalpm/hook.c: claves y valores admitidos.
HOOK_KEYS = {
    "Trigger": {"Operation", "Type", "Target"},
    "Action": {"Description", "When", "Exec", "Depends", "AbortOnFail", "NeedsTargets"},
}
HOOK_VALUES = {
    "Operation": {"Install", "Upgrade", "Remove"},
    "Type": {"Path", "Package", "File"},  # File: alias obsoleto de Path
    "When": {"PreTransaction", "PostTransaction"},
}
SHELLS = {"sh", "bash", "dash", "zsh"}
CALAMARES_ACTIONS = {"enable", "disable", "mask", "unmask"}


# ------------------------------------------------------------- utilidades

def table(name: str) -> dict:
    return testlib.providers().get(name, {})


@lru_cache(maxsize=None)
def available(item: testlib.Edition) -> frozenset[str]:
    """testlib.installed() más lo que llega como dependencia ([pulled_by])."""
    names = set(testlib.installed(item))
    changed = True
    while changed:
        changed = False
        for package, parents in table("pulled_by").items():
            if package not in names and any(parent in names for parent in parents):
                names.add(package)
                changed = True
    return frozenset(names)


def rel(path: Path) -> str:
    return str(path.relative_to(AIROOTFS))


def unit_files() -> list[tuple[Path, str]]:
    """(fichero, ámbito) de cada unidad, drop-in o enlace bajo UNIT_DIRS."""
    found = []
    for directory, scope in UNIT_DIRS.items():
        base = AIROOTFS / directory
        if base.is_dir():
            for dirpath, dirnames, filenames in os.walk(base):
                dirnames.sort()
                found.extend((Path(dirpath) / name, scope) for name in sorted(filenames))
    return found


def template(name: str) -> str | None:
    """'getty@tty1.service' -> 'getty@.service'."""
    match = re.fullmatch(r"([^@/]+@)[^@/]+(\.\w+)", name)
    return match.group(1) + match.group(2) if match else None


@lru_cache(maxsize=None)
def airootfs_units(scope: str) -> frozenset[str]:
    names = set()
    for path, path_scope in unit_files():
        if path_scope == scope and (path.parent.relative_to(AIROOTFS).as_posix() in UNIT_DIRS):
            names.add(path.name)
    return frozenset(names)


def unit_status(name: str, item: testlib.Edition, scope: str = "system") -> tuple[bool, str]:
    """¿Existe la unidad `name` en la edición? (ok, motivo si no)."""
    providers = table("units" if scope == "system" else "user_units")
    for candidate in (name, template(name)):
        if candidate is None:
            continue
        if candidate in airootfs_units(scope):
            # Un enlace del airootfs a /dev/null es una máscara, no una unidad.
            path = next(AIROOTFS / d / candidate for d, s in UNIT_DIRS.items()
                        if s == scope and ((AIROOTFS / d / candidate).is_file() or (AIROOTFS / d / candidate).is_symlink()))
            if not (path.is_symlink() and os.readlink(path) == "/dev/null"):
                return True, ""
        if candidate in providers:
            package = providers[candidate]
            if package in available(item):
                return True, ""
            return False, f"{name} es de '{package}', que no está en {item.package_list}"
    return False, f"{name} no está en el airootfs ni en tests/unit_providers.toml"


def known_unit(name: str, scope: str = "system") -> bool:
    """La unidad existe en alguna parte (airootfs o algún paquete conocido)."""
    providers = table("units" if scope == "system" else "user_units")
    return any(c in airootfs_units(scope) or c in providers for c in (name, template(name)) if c)


def command_status(command: str, item: testlib.Edition, depth: int = 0) -> tuple[bool, str]:
    """¿Existe `command` (ruta absoluta o nombre) en la edición?

    Un nombre sin ruta se busca como systemd (>= 239): /usr/local/sbin,
    /usr/local/bin, /usr/sbin y /usr/bin. Que un fichero del airootfs tenga
    0755 en file_permissions lo comprueba test_file_permissions.
    """
    candidates = [command] if command.startswith("/") else [
        f"/usr/local/sbin/{command}", f"/usr/local/bin/{command}", f"/usr/sbin/{command}", f"/usr/bin/{command}"]
    for path in candidates:
        local = testlib.airootfs(path)
        if local.is_symlink() and depth < 5:
            target = os.readlink(local)
            target = target if target.startswith("/") else str(PurePosixPath(path).parent / target)
            return command_status(os.path.normpath(target), item, depth + 1)
        if local.exists() or path in testlib.generated_paths():
            return True, ""
    result = testlib.resolve_command(command, item)
    if result.ok:
        return True, ""
    name = PurePosixPath(command).name
    in_bin = not command.startswith("/") or re.fullmatch(r"/(?:usr/)?(?:local/)?s?bin/[^/]+", command)
    package = table("unit_commands").get(name) if in_bin else None
    if package:
        if package in available(item):
            return True, ""
        return False, f"'{name}' es de '{package}', que no está en {item.package_list}"
    return False, result.how


def group(failures: dict[tuple[str, str], dict[str, str]], editions) -> dict[str, str]:
    """{(categoría, detalle): {edición: msg}} -> {id: msg}; '*' si fallan todas."""
    ids = {item.id for item in editions}
    findings = {}
    for (category, detail), by_edition in failures.items():
        if set(by_edition) >= ids:
            edition_id, message = next(iter(sorted(by_edition.items())))
            findings[f"{category}:*:{detail}"] = f"todas las ediciones (p. ej. {edition_id}): {message}"
        else:
            for edition_id, message in by_edition.items():
                findings[f"{category}:{edition_id}:{detail}"] = f"{edition_id}: {message}"
    return findings


def parse_ini(path: Path) -> tuple[list[tuple[str | None, str, str]], list[str]]:
    """Asignaciones (sección, clave, valor) y errores de forma, como el parser de systemd.

    Comentarios con # o ;, continuación con \\ al final de línea (los
    comentarios dentro de una continuación se ignoran).
    """
    entries, problems, section, buffer = [], [], None, None
    for raw in testlib.read_text(path).splitlines():
        line = raw.strip()
        if buffer is not None:
            if line.startswith(("#", ";")):
                continue
            line = buffer + line
            buffer = None
        elif not line or line.startswith(("#", ";")):
            continue
        if line.endswith("\\"):
            buffer = line[:-1] + " "
            continue
        if line.startswith("["):
            if not line.endswith("]") or len(line) < 3:
                problems.append(f"cabecera de sección inválida: {line}")
            section = line[1:-1]
            continue
        key, sep, value = line.partition("=")
        if not sep:
            problems.append(f"línea sin '=': {line}")
        elif section is None:
            problems.append(f"asignación fuera de sección: {line}")
        else:
            entries.append((section, key.strip(), value.strip()))
    if buffer is not None:
        problems.append("continuación (\\) al final del fichero")
    return entries, problems


def exec_argv(value: str) -> tuple[str, list[str]]:
    """Prefijos (@-:+!|) y argv de una línea Exec* (systemd.service(5))."""
    match = re.match(r"([@\-:+!|]*)(.*)", value)
    return match.group(1), shlex.split(match.group(2))


def escape_path(path: str) -> str:
    """systemd-escape --path: '/etc/pacman.d/gnupg' -> 'etc-pacman.d-gnupg'."""
    path = "/".join(part for part in path.split("/") if part)
    if not path:
        return "-"
    out = []
    for index, char in enumerate(path):
        if char == "/":
            out.append("-")
        elif char.isascii() and (char.isalnum() or char in ":_.") and not (index == 0 and char == "."):
            out.append(char)
        else:
            out.extend(f"\\x{byte:02x}" for byte in char.encode())
    return "".join(out)


# ------------------------------------------------------------------ pruebas

class UnitFilesTest(unittest.TestCase):
    """Ficheros de unidad y drop-ins: forma, secciones, claves y comandos."""

    def units(self):
        """(fichero, ámbito, sección de tipo, es drop-in) de cada unidad o drop-in."""
        for path, scope in unit_files():
            if path.is_symlink():
                continue
            parent = path.parent.name
            if path.parent.relative_to(AIROOTFS).as_posix() in UNIT_DIRS and path.suffix in TYPE_SECTIONS:
                yield path, scope, path.suffix, False
            elif path.suffix == ".conf" and parent.endswith(".d") and Path(parent[:-2]).suffix in TYPE_SECTIONS:
                yield path, scope, Path(parent[:-2]).suffix, True

    def test_found(self):
        self.assertTrue(list(self.units()), "no encuentro unidades en archiso/airootfs/etc/systemd")

    def test_unit_syntax(self):
        findings = {}

        def problem(path: Path, detail: str, message: str) -> None:
            findings[f"unit-syntax:{rel(path)}:{detail}"] = f"{rel(path)}: {message}"

        for path, scope, suffix, dropin in self.units():
            entries, problems = parse_ini(path)
            for text in problems:
                problem(path, text, text)
            allowed = {"Unit", "Install"} | ({TYPE_SECTIONS[suffix]} if TYPE_SECTIONS[suffix] else set())
            for section in sorted({s for s, _, _ in entries} | set(re.findall(r"^\s*\[([^\]]*)\]", testlib.read_text(path), re.M))):
                if section not in allowed and not section.startswith("X-"):
                    problem(path, f"seccion:{section}", f"sección [{section}] desconocida para {suffix}: systemd la ignora entera")
            for section, key, value in entries:
                if key.startswith("Exec") and key not in EXEC_COMMANDS.get(section, set()) | EXEC_OTHER:
                    problem(path, f"clave:{key}", f"{key}= no existe en [{section}]: systemd lo ignora")
            values = {}
            for section, key, value in entries:
                values.setdefault((section, key), []).append(value)
            service_type = (values.get(("Service", "Type")) or [None])[-1]
            if service_type is not None and service_type not in SERVICE_TYPES:
                problem(path, f"Type={service_type}", f"Type={service_type} no es un tipo de servicio")
            if dropin:
                continue
            if suffix == ".service":
                starts = [v for v in values.get(("Service", "ExecStart"), []) if v]
                if not starts and not values.get(("Service", "ExecStop")) and not values.get(("Unit", "SuccessAction")):
                    problem(path, "sin-ExecStart", "sin ExecStart=: systemd rechaza el servicio (\"Service has no ExecStart=\")")
                if len(starts) > 1 and (service_type or "simple") != "oneshot":
                    problem(path, "varios-ExecStart", "varios ExecStart= solo valen con Type=oneshot")
            if suffix == ".timer" and not any(("Timer", key) in values for key in TIMER_TRIGGERS):
                problem(path, "timer-sin-disparo", "[Timer] sin On*: systemd lo rechaza")
            if suffix == ".mount":
                where = (values.get(("Mount", "Where")) or [""])[-1]
                if not where or not values.get(("Mount", "What")):
                    problem(path, "mount-sin-what-where", "[Mount] necesita What= y Where=")
                elif escape_path(where) + ".mount" != path.name:
                    problem(path, f"Where={where}", f"Where={where} no coincide con el nombre ({escape_path(where)}.mount): systemd lo rechaza")
        # Drop-ins de los demonios (etc/systemd/journald.conf.d/*.conf...): una
        # sección mal escrita hace que se ignore todo su contenido.
        for directory in sorted((AIROOTFS / "etc/systemd").glob("*.conf.d")):
            sections = CONF_SECTIONS.get(directory.name)
            for path in sorted(directory.glob("*.conf")) if sections else []:
                entries, problems = parse_ini(path)
                for text in problems:
                    problem(path, text, text)
                for section in sorted({s for s, _, _ in entries} - sections):
                    problem(path, f"seccion:{section}", f"sección [{section}] desconocida en {directory.name} (se espera {sorted(sections)})")
        testlib.assert_findings(self, "unit-syntax", findings)

    def test_timer_values(self):
        """OnCalendar= y On*Sec= que systemd entiende (systemd-analyze calendar/timespan).

        Un valor que systemd no sabe leer se ignora con un aviso en el diario
        y el temporizador se queda sin disparo: las actualizaciones
        automáticas no corren nunca y ninguna otra prueba lo ve.
        """
        analyze = testlib.require_tool(self, "systemd-analyze")
        findings = {}
        for path, scope, suffix, dropin in self.units():
            if suffix != ".timer":
                continue
            entries, _ = parse_ini(path)
            for section, key, value in entries:
                if section != "Timer" or not value:
                    continue
                if key == "OnCalendar":
                    verb = "calendar"
                elif key in TIMER_TRIGGERS and key.endswith("Sec"):
                    verb = "timespan"
                else:
                    continue
                result = testlib.run([analyze, verb, value], timeout=30)
                if result.returncode != 0:
                    findings[f"timer-value:{rel(path)}:{key}"] = (
                        f"{rel(path)}: {key}={value} no es válido para systemd "
                        f"(systemd-analyze {verb}: {result.stdout.strip().splitlines()[-1:]})")
        testlib.assert_findings(self, "timer-value", findings)

    def test_exec_commands_resolve(self):
        """Cada Exec* se puede ejecutar en cada edición (salvo '-' que falle en alguna)."""
        failures: dict[tuple[str, str], dict[str, str]] = {}
        tolerant: set[tuple[str, str]] = set()
        for path, scope, suffix, dropin in self.units():
            entries, _ = parse_ini(path)
            if any(key == "ExecSearchPath" for _, key, _ in entries):
                continue  # otra ruta de búsqueda: no se modela
            for section, key, value in entries:
                if key not in EXEC_COMMANDS.get(section, set()) or not value:
                    continue
                try:
                    prefix, argv = exec_argv(value)
                except ValueError:
                    continue  # comillas rotas: lo dice systemd-analyze, no esta prueba
                if not argv or re.search(r"[%$]", argv[0]):
                    continue
                detail = f"{rel(path)}:{argv[0]}"
                if "-" in prefix:
                    tolerant.add(("unit-exec", detail))
                for item in testlib.EDITIONS:
                    ok, why = command_status(argv[0], item)
                    if not ok:
                        failures.setdefault(("unit-exec", detail), {})[item.id] = f"{rel(path)} {key}={value}: {why}"
        # '-': systemd ignora el fallo; solo cuenta si no funciona en ninguna edición.
        ids = {item.id for item in testlib.EDITIONS}
        failures = {k: v for k, v in failures.items() if k not in tolerant or set(v) >= ids}
        testlib.assert_findings(self, "unit-exec", group(failures, testlib.EDITIONS))

    def test_dependencies_exist(self):
        """Requires=/BindsTo=, la unidad de un .timer y `systemctl start X` en un Exec*."""
        failures: dict[tuple[str, str], dict[str, str]] = {}

        def require(path: Path, unit: str, scope: str, what: str) -> None:
            for item in testlib.EDITIONS:
                ok, why = unit_status(unit, item, scope)
                if not ok:
                    failures.setdefault(("unit-dep", f"{rel(path)}:{unit}"), {})[item.id] = f"{rel(path)} {what}: {why}"

        for path, scope, suffix, dropin in self.units():
            entries, _ = parse_ini(path)
            for section, key, value in entries:
                if section == "Unit" and key in HARD_DEPS:
                    for unit in value.split():
                        require(path, unit, scope, f"{key}={unit}")
                if key in EXEC_COMMANDS.get(section, set()) and value:
                    try:
                        prefix, argv = exec_argv(value)
                    except ValueError:
                        continue
                    if "-" not in prefix and len(argv) > 2 and PurePosixPath(argv[0]).name == "systemctl" \
                            and argv[1] in SYSTEMCTL_UNIT_VERBS:
                        user = "--user" in argv
                        for unit in (a for a in argv[2:] if not a.startswith("-") and "$" not in a and "%" not in a):
                            require(path, unit, "user" if user else scope, f"{key}={value}")
            if suffix == ".timer" and not dropin:
                target = next((v for s, k, v in entries if s == "Timer" and k == "Unit"), path.stem + ".service")
                require(path, target, scope, "la unidad que activa el timer")
        testlib.assert_findings(self, "unit-dep", group(failures, testlib.EDITIONS))


class UnitLinksTest(unittest.TestCase):
    """Enlaces de *.wants/*.requires, alias y máscaras del airootfs."""

    def links(self):
        return [(path, scope) for path, scope in unit_files() if path.is_symlink()]

    def test_links(self):
        failures: dict[tuple[str, str], dict[str, str]] = {}
        syntax = {}
        for path, scope in self.links():
            link_rel, target = rel(path), os.readlink(path)
            directory = path.parent.relative_to(AIROOTFS).as_posix()
            wants = re.fullmatch(r"(.+)\.(wants|requires|upholds)", path.parent.name)
            if target == "/dev/null" or not (wants or directory in UNIT_DIRS):
                continue  # máscaras (test_masks) y enlaces que no son unidades (generadores)
            target_name = PurePosixPath(target).name
            if wants:
                if target_name != path.name and template(path.name) != target_name:
                    syntax[f"unit-link:{link_rel}"] = (
                        f"{link_rel} -> {target}: systemd usa el nombre del enlace; tiene que ser el de la unidad")
                units = [(wants.group(1), f"la unidad {wants.group(1)} del directorio")]
            else:
                if PurePosixPath(path.name).suffix != PurePosixPath(target_name).suffix:
                    syntax[f"unit-link:{link_rel}"] = f"{link_rel} -> {target}: un alias tiene que ser del mismo tipo"
                units = []
            # Destino: relativo al directorio del enlace o absoluto dentro de la ISO.
            absolute = target if target.startswith("/") else os.path.normpath(f"/{directory}/{target}")
            local = testlib.airootfs(absolute)
            if not (local.is_file() or local.is_symlink()):
                units.append((target_name, f"destino {target}"))
            for unit, what in units:
                for item in testlib.EDITIONS:
                    ok, why = unit_status(unit, item, scope)
                    if not ok:
                        failures.setdefault(("unit-link", link_rel), {})[item.id] = f"{link_rel} ({what}): {why}"
        findings = group(failures, testlib.EDITIONS)
        findings.update(syntax)
        testlib.assert_findings(self, "unit-link", findings)


class ServicesTest(unittest.TestCase):
    """services.sh y Calamares services-systemd.conf activan unidades que existen."""

    def services_sh(self) -> tuple[list[str], list[str]]:
        text = testlib.read_text(SERVICES_SH)
        enables = re.findall(r"^\s*(?:enable_unit|systemctl\s+enable)\s+([^\s;|&$\"']+)", text, re.M)
        masks = re.findall(r"^\s*systemctl\s+mask\s+([^\s;|&$\"']+)", text, re.M)
        return enables, masks

    def calamares_units(self, arch: str) -> list[dict]:
        yaml = testlib.require_module(self, "yaml")
        override = CALAMARES / arch / "services-systemd.conf"
        path = override if override.exists() else CALAMARES / "services-systemd.conf"
        return (yaml.safe_load(testlib.read_text(path)) or {}).get("units") or []

    def test_parsed(self):
        enables, masks = self.services_sh()
        self.assertIn("greetd.service", enables, "no encuentro `enable_unit greetd.service` en services.sh")
        self.assertTrue(masks, "no encuentro `systemctl mask` en services.sh")
        self.assertTrue(self.calamares_units("x86_64"), "services-systemd.conf sin units:")

    def test_enabled_units_exist(self):
        """enable_unit solo avisa si falta la unidad; Calamares aborta si es mandatory."""
        failures: dict[tuple[str, str], dict[str, str]] = {}
        enables, _ = self.services_sh()
        for unit in enables:
            for item in testlib.EDITIONS:
                ok, why = unit_status(unit, item)
                if not ok:
                    failures.setdefault(("unit-enable", unit), {})[item.id] = (
                        f"root/scripts/services.sh: enable_unit {unit}: {why} (la Live arranca sin ella)")
        syntax = {}
        for item in testlib.EDITIONS:
            if not item.installer:
                continue
            for entry in self.calamares_units(item.arch):
                name = entry.get("name", "") if isinstance(entry, dict) else str(entry)
                action = entry.get("action", "enable") if isinstance(entry, dict) else "enable"
                if action not in CALAMARES_ACTIONS:
                    syntax[f"unit-enable:services-systemd.conf:{name}:{action}"] = (
                        f"services-systemd.conf: action '{action}' de {name} no es {sorted(CALAMARES_ACTIONS)}")
                if action != "enable":
                    continue
                ok, why = unit_status(name, item)
                if not ok:
                    mandatory = isinstance(entry, dict) and entry.get("mandatory") is True
                    message = (f"Calamares services-systemd.conf enable {name}: {why}"
                               + (" (mandatory: la instalación aborta)" if mandatory else " (el sistema instalado queda sin ella)"))
                    by_edition = failures.setdefault(("unit-enable", name), {})
                    by_edition[item.id] = f"{by_edition[item.id]}; {message}" if item.id in by_edition else message
        findings = group(failures, testlib.EDITIONS)
        findings.update(syntax)
        testlib.assert_findings(self, "unit-enable", findings)

    def test_masked_units_are_known(self):
        """`systemctl mask` crea el enlace aunque la unidad no exista: un nombre
        mal escrito deja la unidad real sin enmascarar. No hace falta que esté en
        todas las ediciones (enmascarar lo que no está es inocuo)."""
        findings = {}
        _, masks = self.services_sh()
        sources = [(unit, "root/scripts/services.sh") for unit in masks]
        for arch in sorted({item.arch for item in testlib.EDITIONS if item.installer}):
            sources += [(entry.get("name", ""), "installer/calamares/modules/services-systemd.conf")
                        for entry in self.calamares_units(arch) if isinstance(entry, dict) and entry.get("action") == "mask"]
        for path, scope in unit_files():
            if path.is_symlink() and os.readlink(path) == "/dev/null" \
                    and path.parent.relative_to(AIROOTFS).as_posix() in UNIT_DIRS:
                sources.append((path.name, rel(path)))
        for unit, source in sources:
            if not known_unit(unit):
                findings[f"unit-mask:{unit}"] = (
                    f"{source} enmascara {unit}, que no está en el airootfs ni en tests/unit_providers.toml")
        testlib.assert_findings(self, "unit-mask", findings)


class PacmanHooksTest(unittest.TestCase):
    """etc/pacman.d/hooks/*.hook según alpm-hooks(5) y libalpm/hook.c."""

    def hooks(self) -> list[Path]:
        return sorted(HOOKS_DIR.glob("*.hook")) if HOOKS_DIR.is_dir() else []

    @staticmethod
    def parse(path: Path) -> tuple[list[tuple[str, list[tuple[str, str | None]]]], list[str]]:
        """Secciones [(nombre, [(clave, valor o None)])] con el parser ini de libalpm."""
        sections, problems = [], []
        for line in testlib.read_text(path).splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("["):
                if not line.endswith("]"):
                    problems.append(f"cabecera inválida: {line}")
                sections.append((line[1:-1], []))
            elif not sections:
                problems.append(f"clave fuera de sección: {line}")
            else:
                key, sep, value = line.partition("=")
                sections[-1][1].append((key.strip(), value.strip() if sep else None))
        return sections, problems

    def test_found(self):
        self.assertTrue(self.hooks(), "no encuentro hooks en etc/pacman.d/hooks")

    def test_hook_syntax(self):
        findings = {}
        for path in self.hooks():
            name = path.name

            def problem(detail: str, message: str) -> None:
                findings[f"hook:{name}:{detail}"] = f"{name}: {message} (pacman no carga el hook)"

            sections, problems = self.parse(path)
            for text in problems:
                problem(text, text)
            for section, keys in sections:
                if section not in HOOK_KEYS:
                    problem(f"[{section}]", f"sección [{section}] desconocida")
                    continue
                for key, value in keys:
                    if key not in HOOK_KEYS[section]:
                        problem(f"{key}", f"clave '{key}' desconocida en [{section}]")
                    elif key in ("AbortOnFail", "NeedsTargets"):
                        if value is not None:
                            problem(f"{key}={value}", f"{key} no lleva valor")
                    elif not value:
                        problem(f"{key}", f"{key} sin valor")
                    elif key in HOOK_VALUES and value not in HOOK_VALUES[key]:
                        problem(f"{key}={value}", f"{key} = {value} no es {sorted(HOOK_VALUES[key])}")
                if section == "Trigger":
                    present = [key for key, _ in keys]
                    for required in ("Operation", "Type", "Target"):
                        if required not in present:
                            problem(f"Trigger-sin-{required}", f"[Trigger] sin {required}")
            triggers = [keys for section, keys in sections if section == "Trigger"]
            actions = [keys for section, keys in sections if section == "Action"]
            if not triggers:
                problem("sin-Trigger", "falta [Trigger]")
            if len(actions) != 1:
                problem("Action", "tiene que haber exactamente una sección [Action]")
                continue
            action = dict(actions[0])
            for required in ("When", "Exec"):
                if required not in action:
                    problem(f"sin-{required}", f"[Action] sin {required}")
            # libalpm/util.c _alpm_run_chroot: execv(), sin búsqueda en PATH.
            exec_line = action.get("Exec") or ""
            if exec_line and not exec_line.startswith("/"):
                problem("Exec-relativo", f"Exec = {exec_line}: pacman lo lanza con execv, tiene que ser una ruta absoluta")
        testlib.assert_findings(self, "hook", findings)

    def test_hook_exec_and_depends(self):
        """Exec (y lo que ejecuta un `sh -c`) existe; Depends está instalado."""
        failures: dict[tuple[str, str], dict[str, str]] = {}
        for path in self.hooks():
            sections, _ = self.parse(path)
            action = [keys for section, keys in sections if section == "Action"]
            if not action:
                continue
            exec_line = next((v for k, v in action[0] if k == "Exec" and v), "")
            depends = [v for k, v in action[0] if k == "Depends" and v]
            try:
                argv = shlex.split(exec_line)
            except ValueError:
                argv = exec_line.split()
            commands = argv[:1]
            if argv and PurePosixPath(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
                script = argv[argv.index("-c") + 1]
                # testlib.shell_commands parte '>&2' y deja '2' como comando.
                commands += [c for c in testlib.shell_commands(script) if not c.isdigit()]
            for item in testlib.EDITIONS:
                for command in commands:
                    ok, why = command_status(command, item)
                    if not ok:
                        failures.setdefault(("hook-exec", f"{path.name}:{command}"), {})[item.id] = (
                            f"{path.name} Exec: {why}")
                for package in depends:
                    if package not in available(item) and table("provides").get(package) not in available(item):
                        failures.setdefault(("hook-exec", f"{path.name}:Depends={package}"), {})[item.id] = (
                            f"{path.name}: Depends = {package} no está en {item.package_list} (pacman no ejecuta el hook)")
        testlib.assert_findings(self, "hook-exec", group(failures, testlib.EDITIONS))


if __name__ == "__main__":
    unittest.main()
