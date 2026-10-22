"""Utilidades compartidas por las pruebas de tests/.

Todo lo que una prueba necesita saber del repositorio (ediciones, listas de
paquetes, file_permissions de profiledef.sh, crates desplegados, a qué
paquete pertenece un comando) se calcula aquí, a partir de los ficheros del
repo. Así una prueba no duplica una tabla que luego se queda vieja.

Solo usa la biblioteca estándar, más PyYAML donde se necesita YAML
(load_yaml_strict). Funciona en el runner de Ubuntu del CI y en el
contenedor Arch.

Modo estricto (CHURROS_STRICT=1, o CI=true como en GitHub Actions): una
herramienta que falta (shellcheck, node, zstd...) es un fallo, no un SKIP.
En local se salta con un aviso para no obligar a instalarlo todo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import unittest

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = Path(__file__).resolve().parents[1]
AIROOTFS = ROOT / "archiso/airootfs"
KNOWN_ISSUES_FILE = ROOT / "tests/known_issues.toml"
PROVIDERS_FILE = ROOT / "tests/command_providers.toml"
UNIT_PROVIDERS_FILE = ROOT / "tests/unit_providers.toml"

STRICT = os.environ.get("CHURROS_STRICT") == "1" or os.environ.get("CI") == "true"


# ----------------------------------------------------------------- herramientas

def require_tool(testcase: unittest.TestCase, name: str) -> str:
    """Ruta de `name`. Sin él: fallo en modo estricto, SKIP en local."""
    path = shutil.which(name)
    if path:
        return path
    message = f"falta la herramienta '{name}'"
    if STRICT:
        testcase.fail(f"{message} (modo estricto: CHURROS_STRICT=1 o CI=true)")
    raise unittest.SkipTest(message)


def require_module(testcase: unittest.TestCase, module: str):
    """Importa un módulo opcional (p. ej. yaml) con la misma política."""
    try:
        return __import__(module)
    except ImportError:
        message = f"falta el módulo de Python '{module}'"
        if STRICT:
            testcase.fail(f"{message} (modo estricto)")
        raise unittest.SkipTest(message)


def run(cmd, *, cwd=ROOT, env=None, input=None, timeout=120, check=False):
    """subprocess.run con texto y salida capturada (stdout y stderr juntos)."""
    result = subprocess.run(
        cmd, cwd=cwd, env=env, input=input, timeout=timeout, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    if check and result.returncode != 0:
        raise AssertionError(f"{cmd!r} salió con {result.returncode}:\n{result.stdout}")
    return result


# ---------------------------------------------------------------------- ficheros

@lru_cache(maxsize=None)
def repo_files() -> tuple[Path, ...]:
    """Ficheros del repo: versionados más los nuevos sin ignorar.

    Incluir los nuevos (sin `git add`) hace que una prueba local vea el
    script que se acaba de crear, no solo lo que ya está en el índice.
    Fuera de un repo git (copia exportada) recorre el árbol.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    if result.returncode == 0:
        names = sorted({name for name in result.stdout.decode().split("\0") if name})
        return tuple(ROOT / name for name in names if (ROOT / name).is_file() or (ROOT / name).is_symlink())
    skip = {".git", "target", "work", "out", "vm", "node_modules", "__pycache__"}
    found = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip]
        found.extend(Path(dirpath) / f for f in filenames)
    return tuple(sorted(found))


def rel(path: Path) -> str:
    """Ruta relativa al repo, para los mensajes."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def airootfs(abs_path: str) -> Path:
    """'/usr/bin/x' -> archiso/airootfs/usr/bin/x."""
    return AIROOTFS / abs_path.lstrip("/")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


SHEBANG_SHELLS = {"sh": "sh", "bash": "bash", "zsh": "zsh", "dash": "sh"}


def shebang(path: Path) -> str | None:
    """Intérprete de la primera línea (#!/usr/bin/env bash -> 'bash')."""
    try:
        with path.open("rb") as handle:
            first = handle.readline(256)
    except OSError:
        return None
    if not first.startswith(b"#!"):
        return None
    parts = first[2:].decode("utf-8", "replace").split()
    if not parts:
        return None
    interpreter = Path(parts[0]).name
    if interpreter == "env":
        args = [p for p in parts[1:] if not p.startswith("-")]
        interpreter = Path(args[0]).name if args else ""
    return interpreter or None


def shell_scripts() -> list[tuple[Path, str]]:
    """Scripts de shell del repo: (ruta, 'bash' | 'sh' | 'zsh').

    Por shebang, no por extensión: la mitad de los scripts que corren en la
    ISO no terminan en .sh. Los ficheros que solo se cargan con `source`
    llevan `# shellcheck shell=bash` en lugar de shebang y también cuentan.
    """
    scripts = []
    for path in repo_files():
        if path.is_symlink() or path.suffix in {".py", ".js", ".rs", ".md"}:
            continue
        interpreter = shebang(path)
        if interpreter in SHEBANG_SHELLS:
            scripts.append((path, SHEBANG_SHELLS[interpreter]))
            continue
        if path.suffix == ".sh" or path.name in {".zlogin", ".zshrc", ".zprofile", ".bashrc", ".bash_profile"}:
            text = read_text(path)[:2048]
            match = re.search(r"^#\s*shellcheck\s+shell=(\w+)", text, re.MULTILINE)
            if match:
                scripts.append((path, SHEBANG_SHELLS.get(match.group(1), match.group(1))))
            elif path.name.startswith(".z"):
                scripts.append((path, "zsh"))
            elif path.name.startswith(".bash") or path.suffix == ".sh":
                scripts.append((path, "bash"))
    return scripts


# ------------------------------------------------------------- ediciones y paquetes

@dataclass(frozen=True)
class Edition:
    """Una combinación edición × arquitectura que build.sh acepta.

    desktop: escritorio de la sesión Live ('niri', 'xfce', 'labwc' o None si
    la lista todavía no lo trae, como i686). installer: la ISO integra
    Calamares (build.sh lo omite en i686).
    """
    name: str
    arch: str
    package_list: str
    desktop: str | None
    installer: bool
    session_cmd: str

    @property
    def id(self) -> str:
        return f"{self.name}/{self.arch}"

    @property
    def list_path(self) -> Path:
        return ROOT / self.package_list


# Espejo de las reglas de scripts/cli/build.sh (case de SESSION_CMD, listas
# packages.<edicion>.<arch>, i686 sin Calamares). tests/static/test_editions.py
# comprueba que build.sh y esta tabla no se separan.
EDITIONS: tuple[Edition, ...] = (
    Edition("niri", "x86_64", "archiso/packages.x86_64", "niri", True, "niri"),
    Edition("niri", "aarch64", "archiso/packages.aarch64", "niri", True, "niri"),
    Edition("niri", "i686", "archiso/packages.i686", None, False, "niri"),
    Edition("xfce", "x86_64", "archiso/packages.xfce.x86_64", "xfce", True, "/usr/bin/churros-xfce-session"),
    Edition("server", "x86_64", "archiso/packages.server.x86_64", "xfce", True, "/usr/bin/churros-xfce-session"),
    Edition("pi", "aarch64", "archiso/packages.pi.aarch64", "labwc", True, "/usr/bin/churros-pi-session"),
)

ARCHES = ("x86_64", "aarch64", "i686")


def edition(name: str, arch: str) -> Edition:
    for item in EDITIONS:
        if item.name == name and item.arch == arch:
            return item
    raise KeyError(f"{name}/{arch}")


def editions_with_desktop(desktop: str) -> list[Edition]:
    return [item for item in EDITIONS if item.desktop == desktop]


def parse_package_list(path: Path) -> list[str]:
    """Entradas de una lista packages.*: sin comentarios ni líneas vacías."""
    entries = []
    for line in read_text(path).splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


@lru_cache(maxsize=None)
def packages(item: Edition) -> frozenset[str]:
    return frozenset(parse_package_list(item.list_path))


@lru_cache(maxsize=None)
def local_packages() -> frozenset[str]:
    """Paquetes del repo local [churros] que compilan los scripts de build."""
    names = {"calamares"}
    text = read_text(ROOT / "scripts/build-aur.sh")
    names.update(re.findall(r"^\s*build_aur\s+(\S+)", text, re.MULTILINE))
    if (ROOT / "scripts/build-bazaar.sh").exists():
        names.update({"bazaar", "libdex"})
    return frozenset(names)


# Dependencias del metapaquete `base` de Arch: están en toda ISO que liste
# `base`. tests/container la contrasta con `pacman -Si base`.
BASE_DEPENDS = frozenset({
    "archlinux-keyring", "bash", "bzip2", "coreutils", "file", "filesystem",
    "findutils", "gawk", "gcc-libs", "gettext", "glibc", "grep", "gzip",
    "iproute2", "iputils", "licenses", "pacman", "pciutils", "procps-ng",
    "psmisc", "sed", "shadow", "systemd", "systemd-sysvcompat", "tar",
    "util-linux", "xz",
})


@lru_cache(maxsize=None)
def providers() -> dict:
    """command_providers.toml y unit_providers.toml: comando/ruta/unidad -> paquete."""
    if tomllib is None:
        raise unittest.SkipTest("tomllib necesita Python >= 3.11")
    data = {}
    for path in (PROVIDERS_FILE, UNIT_PROVIDERS_FILE):
        if path.exists():
            data.update(tomllib.loads(read_text(path)))
    for key in ("commands", "paths", "units", "implicit"):
        data.setdefault(key, {})
    return data


def installed(item: Edition) -> frozenset[str]:
    """Paquetes que cuentan como instalados en una edición.

    La lista de la edición, las dependencias de base y los paquetes marcados
    como implícitos en command_providers.toml (llegan como dependencia de
    otro; el test de contenedor lo comprueba con pacman), hasta un punto fijo.
    Del repo local [churros] solo cuentan los que la lista nombra (pacstrap
    no instala el resto) y Calamares en las ediciones con instalador, que
    customize_airootfs.sh desempaqueta con bsdtar.
    """
    names = set(packages(item))
    if item.installer:
        names.add("calamares")
    if "base" in names:
        names |= BASE_DEPENDS
    implicit = providers()["implicit"]
    changed = True
    while changed:
        changed = False
        for package, rule in implicit.items():
            pulled_by = rule.get("pulled_by", []) if isinstance(rule, dict) else rule
            if package not in names and any(dep in names for dep in pulled_by):
                names.add(package)
                changed = True
    return frozenset(names)


SHELL_BUILTINS = frozenset({
    ".", ":", "[", "[[", "alias", "bg", "break", "builtin", "cd", "command",
    "continue", "declare", "echo", "eval", "exec", "exit", "export", "false",
    "fg", "for", "function", "getopts", "hash", "if", "jobs", "kill", "let",
    "local", "printf", "pwd", "read", "readonly", "return", "set", "shift",
    "source", "test", "then", "times", "trap", "true", "type", "typeset",
    "ulimit", "umask", "unalias", "unset", "wait", "while", "until", "case",
    "do", "done", "fi", "esac", "else", "elif", "{", "}", "!", "time",
})


@dataclass(frozen=True)
class Resolution:
    ok: bool
    how: str  # 'builtin', 'airootfs', 'crate', 'package:<n>', o el motivo del fallo


def resolve_command(command: str, item: Edition) -> Resolution:
    """¿Existe `command` (nombre o ruta absoluta) en la edición `item`?

    Orden: builtin de shell, fichero del airootfs, crate Rust desplegado,
    tabla de command_providers.toml (paquete en la edición), y por último un
    paquete con el mismo nombre que el comando. Sin coincidencia exacta no se
    adivina: un comando nuevo se añade a command_providers.toml.
    """
    table = providers()
    if command in SHELL_BUILTINS:
        return Resolution(True, "builtin")
    if command.startswith("/"):
        if airootfs(command).exists() or airootfs(command).is_symlink():
            return Resolution(True, "airootfs")
        if command in table["paths"]:
            package = table["paths"][command]
            if package in installed(item):
                return Resolution(True, f"package:{package}")
            return Resolution(False, f"{command} es de '{package}', que no está en {item.package_list}")
        if command in generated_paths():
            return Resolution(True, "build")
        match = re.fullmatch(r"/usr/(?:local/)?s?bin/([^/]+)|/bin/([^/]+)", command)
        if not match:
            return Resolution(False, f"{command} no está en el airootfs ni en [paths] de command_providers.toml")
        command = match.group(1) or match.group(2)
    for directory in ("usr/bin", "usr/local/bin"):
        if (AIROOTFS / directory / command).exists():
            return Resolution(True, "airootfs")
    if command in deploy_crate_names():
        return Resolution(True, "crate")
    if command in table["commands"]:
        package = table["commands"][command]
        if package in installed(item):
            return Resolution(True, f"package:{package}")
        return Resolution(False, f"'{command}' es de '{package}', que no está en {item.package_list}")
    if command in installed(item):
        return Resolution(True, f"package:{command}")
    return Resolution(False, f"'{command}' no está en el airootfs, ni es un crate, ni está en command_providers.toml")


def shell_commands(line: str) -> list[str]:
    """Primer token de cada comando de una línea de shell.

    Parte por ; && || | y quita asignaciones (VAR=x), `env`, `exec`, `sudo`,
    `pkexec`, `runuser -u x --` y similares. Es una aproximación: solo se usa
    para encontrar qué binarios ejecuta una línea de configuración.
    """
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = line.split()
    commands, current = [], []
    for token in tokens + [";"]:
        if token and set(token) <= set(";&|()"):
            if current:
                commands.append(current)
            current = []
        else:
            current.append(token)
    wrappers = {"env", "exec", "sudo", "pkexec", "nohup", "setsid", "command", "time", "nice", "ionice", "systemd-cat", "dbus-run-session", "dbus-launch", "timeout", "runuser", "doas", "uwsm", "uwsm-app"}
    found = []
    for words in commands:
        index = 0
        while index < len(words):
            word = words[index]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word) or (word.startswith("-") and index > 0):
                index += 1
                continue
            if word in wrappers:
                if word == "timeout" and index + 1 < len(words) and re.fullmatch(r"[0-9.]+[smhd]?", words[index + 1]):
                    index += 2
                    continue
                if word == "runuser" and "--" in words[index:]:
                    index = words.index("--", index) + 1
                    continue
                if word == "sudo" and index + 1 < len(words) and words[index + 1] == "-u":
                    index += 3
                    continue
                index += 1
                continue
            found.append(word)
            break
    return found


# ------------------------------------------------------------------- profiledef

@lru_cache(maxsize=None)
def profile(arch: str) -> dict:
    """profiledef.sh cargado como lo hace mkarchiso para CHURROS_ARCH=arch.

    Devuelve arch, pacman_conf, bootmodes, install_dir y file_permissions
    ({ruta: 'uid:gid:modo'}).
    """
    script = r'''
set -eu
declare -A file_permissions=()
cd archiso
. ./profiledef.sh
printf 'arch\t%s\n' "$arch"
printf 'pacman_conf\t%s\n' "$pacman_conf"
printf 'install_dir\t%s\n' "$install_dir"
printf 'bootmodes\t%s\n' "${bootmodes[*]}"
for path in "${!file_permissions[@]}"; do
    printf 'perm\t%s\t%s\n' "$path" "${file_permissions[$path]}"
done
'''
    env = dict(os.environ, CHURROS_ARCH=arch, SOURCE_DATE_EPOCH="0")
    result = run(["bash", "-c", script], env=env, check=True)
    data = {"file_permissions": {}}
    for line in result.stdout.splitlines():
        fields = line.split("\t")
        if fields[0] == "perm" and len(fields) == 3:
            data["file_permissions"][fields[1]] = fields[2]
        elif len(fields) == 2:
            data[fields[0]] = fields[1]
    data["bootmodes"] = data.get("bootmodes", "").split()
    return data


def mode_is_executable(spec: str) -> bool:
    """'0:0:755' -> True."""
    try:
        return int(spec.rsplit(":", 1)[1], 8) & 0o111 != 0
    except (IndexError, ValueError):
        return False


# --------------------------------------------------------------------- crates Rust

@dataclass(frozen=True)
class Crate:
    name: str
    directory: Path
    deploy: bool
    bins: tuple[str, ...] = field(default_factory=tuple)


@lru_cache(maxsize=None)
def crates() -> tuple[Crate, ...]:
    if tomllib is None:
        raise unittest.SkipTest("tomllib necesita Python >= 3.11")
    found = []
    for manifest in sorted((ROOT / "rust").glob("*/Cargo.toml")):
        data = tomllib.loads(read_text(manifest))
        package = data.get("package", {})
        metadata = package.get("metadata", {}).get("churros", {})
        bins = tuple(b.get("name", "") for b in data.get("bin", []))
        found.append(Crate(package.get("name", ""), manifest.parent, bool(metadata.get("deploy")), bins))
    return tuple(found)


@lru_cache(maxsize=None)
def deploy_crate_names() -> frozenset[str]:
    return frozenset(crate.name for crate in crates() if crate.deploy)


@lru_cache(maxsize=None)
def generated_paths() -> frozenset[str]:
    """Rutas absolutas que no están en git y crea el build en el airootfs."""
    paths = {f"/usr/bin/{name}" for name in deploy_crate_names()}
    paths |= {"/etc/churros-edition", "/root/customize_airootfs.sh"}
    return frozenset(paths)


# -------------------------------------------------------------- problemas conocidos

@lru_cache(maxsize=None)
def known_issues() -> dict[str, str]:
    """tests/known_issues.toml: {id: nota}."""
    if tomllib is None or not KNOWN_ISSUES_FILE.exists():
        return {}
    data = tomllib.loads(read_text(KNOWN_ISSUES_FILE))
    return {entry["id"]: entry.get("note", "") for entry in data.get("issue", [])}


def assert_findings(testcase: unittest.TestCase, category: str, findings: dict[str, str]) -> None:
    """Falla si hay hallazgos nuevos o si un problema conocido ya se arregló.

    findings: {id: mensaje}. Los id empiezan por `category + ':'`. Un id que
    está en tests/known_issues.toml no hace fallar la prueba (es un fallo
    real que ya está apuntado); uno que ya no aparece obliga a borrar su
    entrada, para que la lista solo se pueda acortar.
    """
    for key in findings:
        if not key.startswith(category + ":"):
            raise ValueError(f"id '{key}' no empieza por '{category}:'")
    known = {key: note for key, note in known_issues().items() if key.startswith(category + ":")}
    new = {key: msg for key, msg in findings.items() if key not in known}
    fixed = sorted(key for key in known if key not in findings)
    lines = []
    if new:
        lines.append(f"{len(new)} problema(s) nuevo(s):")
        lines.extend(f"  - {msg}  [{key}]" for key, msg in sorted(new.items()))
    if fixed:
        lines.append("Ya no fallan; borra su entrada de tests/known_issues.toml:")
        lines.extend(f"  - {key}" for key in fixed)
    if lines:
        testcase.fail("\n".join(lines))
