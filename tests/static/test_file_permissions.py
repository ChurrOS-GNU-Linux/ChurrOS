"""Permisos de ejecución del airootfs: el contrato de profiledef.sh.

mkarchiso (archiso 91, _make_custom_airootfs) copia el airootfs con
`cp -af --no-preserve=ownership,mode` bajo `umask 0022` y después solo
aplica `file_permissions` de profiledef.sh. Comprobado en el contenedor
churros-builder (coreutils 9.12): un fichero 4755 en el perfil sale 0644.
Así que el bit +x de git no llega a la ISO: sin entrada en file_permissions,
un script sale 0644 y systemd, greetd, pacman o Calamares fallan con
"Permission denied" (203/EXEC en systemd; el '-' de shellprocess lo calla).

Para cada arquitectura (testlib.ARCHES, profiledef.sh cargado como mkarchiso):
- exec-mode: tiene entrada con bit de ejecución todo lo que se ejecuta
  directamente: los ficheros de EXEC_DIRS (salvo bibliotecas para `source`)
  y las rutas del airootfs que se lanzan desde unidades systemd, hooks de
  pacman, greetd, .desktop, niri, Calamares, build.sh (SESSION_CMD) o los
  scripts del propio airootfs. Los crates deploy=true necesitan
  /usr/bin/<crate> = 0:0:755.
- stale-permission: cada clave existe en el airootfs o la genera el build.
- permission-sanity: uid:gid:octal, /etc/shadow 0:0:400, nada escribible por
  todos y nada setuid/setgid sin una razón apuntada en SETID_ALLOWED.

Informativo (no falla): el modo de git y el del perfil no coinciden en
usr/bin/churros-niri-session y usr/share/churros/scripts/configure-greeter-locale
(100644 en git, 0755 en el perfil: correcto, manda el perfil) ni en
usr/local/bin/livecd-sound e Installation_guide (100755 en git, sin entrada:
salen 0644, ver tests/known_issues.toml).
"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
import re
import shlex
import unittest

from tests import testlib

# Directorios del airootfs cuyo contenido se ejecuta tal cual (quién lo hace).
EXEC_DIRS = (
    "usr/bin", "usr/local/bin", "usr/local/sbin",       # PATH
    "usr/share/churros/scripts",                         # Calamares, hooks, customize_airootfs
    "etc/systemd/system-generators", "etc/systemd/user-generators",          # systemd.generator(7)
    "usr/lib/systemd/system-generators", "usr/lib/systemd/user-generators",
    "usr/lib/systemd/system-sleep", "usr/lib/systemd/system-shutdown",       # systemd-suspend/halt.service(8)
    "etc/NetworkManager/dispatcher.d", "usr/lib/NetworkManager/dispatcher.d",  # NetworkManager-dispatcher(8)
    "etc/grub.d",                                        # grub-mkconfig solo lanza los que tienen +x
)

# Ficheros de datos que pueden convivir con los ejecutables sin serlo.
DATA_SUFFIXES = {".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".css", ".svg", ".png", ".desktop"}

# Rutas con setuid/setgid permitidas: {ruta: motivo}. Hoy ninguna.
SETID_ALLOWED: dict[str, str] = {}

MODE_RE = re.compile(r"(\d+):(\d+):([0-7]{3,4})")
SHELLS = {"sh", "bash", "dash", "zsh"}
KEYWORDS = {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time"}
CASE_PATTERN = re.compile(r"^\s*\(?[^\s()]+\)\s*")
ARRAY_ASSIGNMENT = re.compile(r"(?<![\w$])[A-Za-z_]\w*(\[[^]]*\])?\+?=\([^()]*\)")
HEREDOC = re.compile(r"(?<!<)<<(?!<)(-?)\s*\\?(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")
UNIT_SUFFIXES = {".service", ".socket", ".timer", ".path", ".mount", ".automount", ".swap"}
UNIT_EXEC = re.compile(r"^(Exec(?:Start|StartPre|StartPost|Stop|StopPost|Reload|Condition))\s*=\s*(.*)$")
NIRI_SPAWN = re.compile(r'(?<![\w-])(spawn-sh-at-startup|spawn-sh|spawn-at-startup|spawn)\s+"((?:[^"\\]|\\.)*)"')


# ------------------------------------------------------------------- ficheros

@lru_cache(maxsize=None)
def airootfs_files() -> dict[str, Path]:
    """'/usr/bin/x' -> ruta del repo, para lo versionado (o nuevo) bajo el airootfs."""
    files = {}
    for path in testlib.repo_files():
        try:
            files["/" + path.relative_to(testlib.AIROOTFS).as_posix()] = path
        except ValueError:
            continue
    return files


def head(path: Path, size: int = 2048) -> bytes:
    with path.open("rb") as handle:
        return handle.read(size)


def is_elf(path: Path) -> bool:
    return head(path, 4) == b"\x7fELF"


def is_sourced_library(path: Path) -> bool:
    """Sin shebang y con `# shellcheck shell=...`: se carga con `.`, no se ejecuta."""
    data = head(path)
    return not data.startswith(b"#!") and re.search(rb"^#\s*shellcheck\s+shell=", data, re.MULTILINE) is not None


def link_target(abs_path: str) -> str | None:
    """Destino dentro del airootfs de un symlink del airootfs (None si es de un paquete)."""
    seen = set()
    while abs_path in airootfs_files() and airootfs_files()[abs_path].is_symlink() and abs_path not in seen:
        seen.add(abs_path)
        target = os.readlink(airootfs_files()[abs_path])
        abs_path = os.path.normpath(target if target.startswith("/") else os.path.join(os.path.dirname(abs_path), target))
    path = airootfs_files().get(abs_path)
    return abs_path if path is not None and path.is_file() and not path.is_symlink() else None


def exec_dir_files() -> dict[str, str]:
    """Ficheros de EXEC_DIRS que se ejecutan: {ruta absoluta: de dónde sale}.

    Un symlink cuenta por su destino si está en el airootfs. Las bibliotecas
    para `source` y los ficheros de datos (DATA_SUFFIXES) quedan fuera;
    test_shell_scripts comprueba que nadie ejecuta esas bibliotecas.
    """
    found = {}
    for abs_path, path in airootfs_files().items():
        if not any(abs_path.startswith(f"/{directory}/") for directory in EXEC_DIRS) or path.suffix in DATA_SUFFIXES:
            continue
        target = link_target(abs_path)
        if target is None or is_sourced_library(airootfs_files()[target]):
            continue
        found[target] = f"está en {os.path.dirname(abs_path)}" + (f" (vía {abs_path})" if target != abs_path else "")
    return found


# ------------------------------------------------------------ qué se ejecuta

def line_commands(line: str) -> list[str]:
    """Programas que lanza una línea de shell: testlib.shell_commands por segmento,
    saltando palabras clave (then, do...), patrones de case y `command -v`."""
    line = CASE_PATTERN.sub("", line, count=1)  # `xfce) cmd` -> `cmd`; `f() {` no casa
    line = ARRAY_ASSIGNMENT.sub(" ", line)      # los elementos de X=(a b) no son órdenes
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return testlib.shell_commands(line)
    found, segment = [], []
    for token in tokens + [";"]:
        if token and set(token) <= set(";&|()"):
            while segment and segment[0] in KEYWORDS:
                segment.pop(0)
            if segment and not (segment[0] == "command" and segment[1:2] in (["-v"], ["-V"])):
                found += testlib.shell_commands(shlex.join(segment))
            segment = []
        else:
            segment.append(token)
    return found


def argv_commands(value: str) -> list[str]:
    """Programas de una línea que se ejecuta sin shell (ExecStart, Exec de un hook o
    de un .desktop): argv[0] tras `env`, y los de CMD si es `sh -c CMD`."""
    try:
        argv = shlex.split(value)
    except ValueError:
        return []
    while argv and (Path(argv[0]).name == "env" or re.fullmatch(r"[A-Za-z_]\w*=.*", argv[0]) or (argv[0].startswith("-") and len(argv) > 1)):
        argv = argv[1:]
    if not argv:
        return []
    found = [argv[0]]
    if Path(argv[0]).name in SHELLS and "-c" in argv[1:-1]:
        found += line_commands(argv[argv.index("-c") + 1])
    return found


def paren_balance(line: str) -> int:
    """( menos ) fuera de comillas y comentarios."""
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars="()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return 0
    return sum(t.count("(") - t.count(")") for t in tokens if set(t) <= set("()"))


def script_lines(text: str):
    """Órdenes de un script, una por elemento: sin comentarios, cuerpos de
    heredoc ni elementos de arrays de varias líneas; las continuaciones `\\` y
    las cadenas entre comillas de varias líneas (awk, sed) van unidas a su orden."""
    terminators, array_depth, pending, held = [], 0, "", 0
    for raw in text.splitlines():
        if terminators:
            dash, word = terminators[0]
            if (raw.lstrip("\t") if dash else raw) == word:
                terminators.pop(0)
            continue
        if array_depth > 0:
            array_depth += paren_balance(raw)
            continue
        if not pending and (not raw.strip() or raw.strip().startswith("#")):
            continue
        line = pending + raw
        if line.rstrip().endswith("\\"):
            pending = line.rstrip()[:-1] + " "
            continue
        try:
            shlex.split(line, comments=True)
        except ValueError:  # comilla sin cerrar: la orden sigue en la línea siguiente
            held += 1
            pending = line + "\n" if held < 200 else ""
            held %= 200
            continue
        pending, held = "", 0
        if re.search(r"(^|\s)[A-Za-z_]\w*(\[[^]]*\])?\+?=\(", line) and paren_balance(line) > 0:
            array_depth = paren_balance(line)  # `X=(` sin cerrar: siguen elementos, no órdenes
            continue
        terminators += [(m.group(1) == "-", m.group(3)) for m in HEREDOC.finditer(line)]
        yield line


def ini_values(text: str, keys: re.Pattern):
    """(clave, valor) de un fichero tipo INI (unidades, hooks, .desktop), con continuaciones."""
    joined = re.sub(r"\\\n", " ", text)
    for line in joined.splitlines():
        match = keys.match(line.strip())
        if match:
            yield match.group(1), match.group(2)


def exec_references(testcase: unittest.TestCase) -> dict[str, set[str]]:
    """Rutas absolutas que se ejecutan como programa: {ruta: {quién la lanza}}.

    Solo se buscan rutas literales en posición de orden (no en argumentos):
    otro módulo resuelve los comandos por nombre contra los paquetes.
    """
    yaml = testlib.require_module(testcase, "yaml")
    refs: dict[str, set[str]] = {}

    def add(commands, origin: str, home: str | None = None):
        for command in commands:
            if home and command.startswith("~/"):
                command = home + command[1:]
            if command.startswith("/"):
                refs.setdefault(os.path.normpath(command), set()).add(origin)

    for abs_path, path in airootfs_files().items():
        if path.is_symlink() or not path.is_file():
            continue
        origin = testlib.rel(path)
        is_unit = (path.suffix in UNIT_SUFFIXES or (path.suffix == ".conf" and path.parent.name.endswith(".d"))) \
            and "/systemd/" in abs_path
        if is_unit:
            # systemd.service(5): los prefijos @ - : + ! van pegados a la ruta.
            for key, value in ini_values(testlib.read_text(path), UNIT_EXEC):
                add(argv_commands(value.lstrip("@-:+!")), f"{origin} ({key})")
        elif path.suffix == ".hook":
            # alpm-hooks(5): Exec se ejecuta sin shell, partido por espacios.
            for key, value in ini_values(testlib.read_text(path), re.compile(r"^(Exec)\s*=\s*(.*)$")):
                add(argv_commands(value), f"{origin} ({key})")
        elif path.suffix == ".desktop":
            for key, value in ini_values(testlib.read_text(path), re.compile(r"^(Exec|TryExec)\s*=\s*(.*)$")):
                add(argv_commands(value), f"{origin} ({key})")
        elif path.suffix == ".kdl":
            # niri: spawn "prog" "arg"... lanza prog; spawn-sh "cmd" pasa cmd a sh -c.
            for line in testlib.read_text(path).splitlines():
                if line.strip().startswith("//"):
                    continue
                for kind, value in NIRI_SPAWN.findall(line):
                    value = value.replace('\\"', '"').replace("\\\\", "\\")
                    add(line_commands(value) if kind.startswith("spawn-sh") else [value], f"{origin} ({kind})")
        elif abs_path.startswith("/etc/greetd/") and path.suffix == ".toml" and testlib.tomllib:
            # greetd lanza `command` con /bin/sh -c.
            for table in testlib.tomllib.loads(testlib.read_text(path)).values():
                if isinstance(table, dict) and isinstance(table.get("command"), str):
                    add(line_commands(table["command"]), f"{origin} (command)")

    # Scripts que corren en el sistema: los del airootfs y customize_airootfs.sh
    # (mkarchiso lo ejecuta en arch-chroot después de aplicar file_permissions).
    for path, _dialect in testlib.shell_scripts():
        if path.is_relative_to(testlib.AIROOTFS) or path == testlib.ROOT / "branding/customize_airootfs.sh":
            home = "/root" if path.is_relative_to(testlib.AIROOTFS / "root") else None
            for line in script_lines(testlib.read_text(path)):
                add(line_commands(line), testlib.rel(path), home)

    # Calamares: shellprocess pasa cada orden (sin el '-' inicial) a /bin/sh -c;
    # displaymanager escribe `executable` como sesión.
    def walk(node, origin):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "executable" and isinstance(value, str):
                    add([value], f"{origin} (executable)")
                walk(value, origin)
        elif isinstance(node, list):
            for item in node:
                walk(item, origin)

    for conf in sorted((testlib.ROOT / "installer/calamares/modules").rglob("*.conf")):
        try:
            data = yaml.safe_load(testlib.read_text(conf)) or {}
        except yaml.YAMLError:
            continue  # el YAML roto lo señala la prueba de Calamares, no esta
        if not isinstance(data, dict):
            continue
        origin = testlib.rel(conf)
        walk(data, origin)
        if conf.name.startswith("shellprocess"):
            for entry in data.get("script") or []:
                command = entry.get("command") if isinstance(entry, dict) else entry
                if isinstance(command, str):
                    add(line_commands(command.removeprefix("-")), f"{origin} (script)")

    # build.sh escribe SESSION_CMD en el initial_session de greetd.
    for item in testlib.EDITIONS:
        add(line_commands(item.session_cmd), f"scripts/cli/build.sh (SESSION_CMD de {item.id})")
    return refs


def airootfs_exec_references(testcase: unittest.TestCase) -> dict[str, set[str]]:
    """exec_references limitado a ficheros del airootfs (con los symlinks resueltos)."""
    found: dict[str, set[str]] = {}
    for abs_path, origins in exec_references(testcase).items():
        target = link_target(abs_path)
        if target is not None:
            found.setdefault(target, set()).update(origins)
    return found


# -------------------------------------------------------------------- modos

def parse_mode(spec: str) -> tuple[int, int, int] | None:
    match = MODE_RE.fullmatch(spec)
    return (int(match.group(1)), int(match.group(2)), int(match.group(3), 8)) if match else None


def effective_mode(abs_path: str, permissions: dict[str, str]) -> str | None:
    """Entrada que deja el modo de abs_path: la suya o la de un directorio con
    '/' final (mkarchiso hace chmod -R en ese caso)."""
    if abs_path in permissions:
        return permissions[abs_path]
    parent = abs_path
    while parent not in ("", "/"):
        parent = os.path.dirname(parent)
        if parent.rstrip("/") + "/" in permissions:
            return permissions[parent.rstrip("/") + "/"]
    return None


@lru_cache(maxsize=None)
def build_generated() -> tuple[str, ...]:
    """Rutas del airootfs que crea build.sh: las que borra su trap cleanup_temp."""
    text = testlib.read_text(testlib.ROOT / "scripts/cli/build.sh")
    body = re.search(r"^cleanup_temp\(\) \{\n(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    paths = re.findall(r"^\s*rm\s+-r?f\s+(?:--one-file-system\s+)?archiso/airootfs/(\S+)", body.group(1) if body else "", re.MULTILINE)
    return tuple("/" + p.rstrip("/") for p in paths)


def arch_permissions():
    """(arch, file_permissions) para cada arquitectura de testlib.ARCHES."""
    return [(arch, testlib.profile(arch)["file_permissions"]) for arch in testlib.ARCHES]


class ArchFindings:
    """Hallazgos por id, con las arquitecturas en las que aparece cada mensaje."""

    def __init__(self):
        self.by_id: dict[str, dict[str, list[str]]] = {}

    def add(self, key: str, arch: str, message: str) -> None:
        self.by_id.setdefault(key, {}).setdefault(message, []).append(arch)

    def findings(self) -> dict[str, str]:
        return {key: " | ".join(f"{message} [{', '.join(arches)}]" for message, arches in messages.items())
                for key, messages in self.by_id.items()}


def exists_in_build(key: str) -> bool:
    path = key.rstrip("/") or "/"
    files = airootfs_files()
    if path in files or any(name.startswith(path + "/") for name in files):
        return True
    if path in testlib.generated_paths():
        return True
    return any(path == g or path.startswith(g + "/") for g in build_generated())


class FilePermissions(unittest.TestCase):
    def test_executables_have_exec_mode(self):
        """Lo que se ejecuta tiene en file_permissions una entrada con bit x."""
        required: dict[str, list[str]] = {}
        for abs_path, why in exec_dir_files().items():
            required.setdefault(abs_path, []).append(why)
        for abs_path, origins in airootfs_exec_references(self).items():
            required.setdefault(abs_path, []).append("lo ejecuta " + ", ".join(sorted(origins)))
        self.assertTrue(required, "no se encontró ningún ejecutable en el airootfs: ¿cambió la estructura?")

        problems = ArchFindings()
        for arch, permissions in arch_permissions():
            for abs_path, reasons in required.items():
                spec = effective_mode(abs_path, permissions)
                if spec is None:
                    problems.add(f"exec-mode:{abs_path}", arch,
                                 f"{abs_path} no tiene entrada en file_permissions de archiso/profiledef.sh: "
                                 f"mkarchiso lo copia 0644 y no se puede ejecutar ({'; '.join(reasons)})")
                elif not testlib.mode_is_executable(spec):
                    problems.add(f"exec-mode:{abs_path}", arch,
                                 f"{abs_path} tiene '{spec}' en file_permissions, sin bit de ejecución ({'; '.join(reasons)})")
            for name in sorted(testlib.deploy_crate_names()):
                abs_path = f"/usr/bin/{name}"
                spec = permissions.get(abs_path)
                if spec is None or parse_mode(spec) != (0, 0, 0o755):
                    problems.add(f"exec-mode:{abs_path}", arch,
                                 f"el crate deploy=true '{name}' se instala en {abs_path} (scripts/build-rust.sh) y "
                                 f"necesita [\"{abs_path}\"]=\"0:0:755\" en file_permissions; hay {spec!r}")
        testlib.assert_findings(self, "exec-mode", problems.findings())

    def test_entries_exist(self):
        """Cada clave de file_permissions existe en el airootfs o la genera el build."""
        problems = ArchFindings()
        for arch, permissions in arch_permissions():
            for key in permissions:
                if not exists_in_build(key):
                    problems.add(f"stale-permission:{key}", arch,
                                 f"file_permissions declara {key}, que no existe en archiso/airootfs ni lo genera el "
                                 f"build (testlib.generated_paths, trap de build.sh): mkarchiso solo avisa, y si es "
                                 f"una errata el fichero real se quedó sin su modo")
        testlib.assert_findings(self, "stale-permission", problems.findings())

    def test_modes_are_sane(self):
        """uid:gid:octal, /etc/shadow 0:0:400, nada escribible por todos ni setuid sin motivo."""
        problems = ArchFindings()
        for arch, permissions in arch_permissions():
            self.assertTrue(permissions, f"profiledef.sh ({arch}) no declara file_permissions")
            for key, spec in permissions.items():
                parsed = parse_mode(spec)
                if parsed is None:
                    problems.add(f"permission-sanity:{key}:formato", arch,
                                 f"file_permissions[{key}]='{spec}' no es uid:gid:modo-octal (p. ej. 0:0:755)")
                    continue
                mode = parsed[2]
                is_dir = testlib.airootfs(key).is_dir() or key.endswith("/")
                if mode & 0o002 and not (is_dir and mode & 0o1000):
                    problems.add(f"permission-sanity:{key}:world-writable", arch,
                                 f"file_permissions[{key}]='{spec}' deja {key} escribible por cualquier usuario")
                if mode & 0o6000 and key not in SETID_ALLOWED:
                    problems.add(f"permission-sanity:{key}:setid", arch,
                                 f"file_permissions[{key}]='{spec}' pone setuid/setgid; si es a propósito, "
                                 f"apúntalo con su motivo en SETID_ALLOWED")
            for secret in ("/etc/shadow", "/etc/gshadow"):
                if secret in airootfs_files() and parse_mode(permissions.get(secret, "")) != (0, 0, 0o400):
                    problems.add(f"permission-sanity:{secret}:modo", arch,
                                 f"{secret} necesita [\"{secret}\"]=\"0:0:400\" (hay {permissions.get(secret)!r}): "
                                 f"sin ella mkarchiso la copia 0644 y cualquiera lee los hashes")
        testlib.assert_findings(self, "permission-sanity", problems.findings())


if __name__ == "__main__":
    unittest.main()
