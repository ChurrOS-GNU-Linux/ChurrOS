"""Contrato entre las apps Rust de rust/ y el resto de la distro, sin compilar.

GTK 4.22 no está en el runner de Ubuntu (rust.yml compila en el contenedor
Arch), así que todo se comprueba leyendo el código: un lexer mínimo de Rust
(comentarios fuera, cada literal aparte, también los raw r#"..."#) y un
parser mínimo de KDL v1 para la configuración de niri.

Qué garantiza:
  1. Despliegue. Se ejecuta scripts/build-rust.sh de verdad, en una copia
     temporal, con un `cargo` falso que crea los binarios que crearía cargo
     (reglas de targets de Cargo sobre cada Cargo.toml). Cada crate con
     deploy = true acaba en /usr/bin/<nombre del paquete>: build-rust.sh
     salta en silencio el binario que falta (su `if [ -x ]` no tiene else).
     Cada binario desplegado es ejecutable según file_permissions de
     profiledef.sh en las tres arquitecturas (mkarchiso copia el airootfs
     con --no-preserve=mode), lo borran el trap cleanup_temp de build.sh y
     clean.sh, .gitignore cubre todo lo que build-rust.sh escribe en el
     airootfs, una copia versionada no está vieja y las RUNTIME_ROOT(S) del
     código apuntan a donde build-rust.sh deja los assets.
  2. Assets. Cada icono, imagen o CSS que el código pide a sus helpers de
     assets existe en rust/<crate>/assets; cada include_str!/include_bytes!
     y cada concat!(env!("CARGO_MANIFEST_DIR"), ...) existe; cada ruta
     absoluta de /usr/share/churros o /etc/skel que lee Rust existe en el
     airootfs.
  3. Lanzadores. Toda invocación de un binario desplegado (niri spawn y
     spawn-sh, .desktop del airootfs incluidos autostart y lanzadores de
     XFCE, Exec= de heredocs y de literales Rust, waybar on-click/exec,
     atajos de xfconf, Whisker Menu, labwc, unidades systemd, hooks de
     pacman, scripts de la ISO y el propio Rust) usa argumentos que el
     binario acepta: churros-popup solo conoce los nombres de POPUPS (con
     otro sale con 64) y cada uno necesita rama en build_window (sin ella,
     unreachable!() aborta); una app que llama a app.run() entrega argv a
     GApplication, que sale con 1 ante una opción que no registra o un
     argumento suelto. El .desktop que churros-welcome lanza como
     instalador pasa su ALLOWED_LAUNCHERS.
  4. Window rules de niri. Toda regla `match/exclude app-id=` que apunta a
     ChurrOS casa con algún application_id real (un id renombrado deja las
     apps sin flotar ni transparencia, sin ningún error).
  5. Tests #[ignore]. Cada uno tiene un script que lo ejecuta con
     --include-ignored. Inventario actual:
       churros-tour::gtk_selection_preview_and_installation_failures
         -> scripts/test-tour.py (cargo test -p churros-tour --
            --include-ignored, sobre Broadway). Que ese script corra en CI
            lo comprueba otro módulo.

Los comandos externos que lanza Rust (wpctl, nmcli...) los resuelve otro
módulo.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET

from tests import testlib

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = testlib.ROOT
AIROOTFS = testlib.AIROOTFS
LIT = r'"(\d+)"'  # un literal de cadena ya enmascarado por lex_rust
MANIFEST_PATH = r'env!\(\s*"(\d+)"\s*\)\s*,\s*"(\d+)"'  # concat!(env!("X"), "ruta")
IMAGE_EXT = (".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp")


def where(path: Path, line: int | None = None) -> str:
    return f"{testlib.rel(path)}:{line}" if line else testlib.rel(path)


# ------------------------------------------------------------------ lexer de Rust

CHAR_LITERAL = re.compile(r"""'(?:\\(?:[nrt\\0'"]|x[0-9a-fA-F]{2}|u\{[0-9a-fA-F_]{1,6}\})|[^\\'\n])'""")
RAW_STRING = re.compile(r'(?:b|c)?r(#*)"')


def decode_rust_string(raw: str) -> str:
    """Contenido de "..." con los escapes de Rust resueltos."""
    out, i = [], 0
    while i < len(raw):
        if raw[i] != "\\" or i + 1 >= len(raw):
            out.append(raw[i])
            i += 1
            continue
        nxt = raw[i + 1]
        if nxt == "\n":  # continuación: se come el salto y la sangría
            i += 2
            while i < len(raw) and raw[i] in " \t\r\n":
                i += 1
        elif nxt == "x":
            out.append(chr(int(raw[i + 2:i + 4], 16)))
            i += 4
        elif nxt == "u":
            end = raw.index("}", i)
            out.append(chr(int(raw[i + 3:end].replace("_", ""), 16)))
            i = end + 1
        else:
            out.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(nxt, nxt))
            i += 2
    return "".join(out)


def skip_block_comment(text: str, start: int) -> int:
    """Offset tras el /* ... */ (anidable en Rust y en KDL) que empieza en start."""
    depth, j = 0, start
    while j < len(text):
        if text.startswith("/*", j):
            depth, j = depth + 1, j + 2
        elif text.startswith("*/", j):
            depth, j = depth - 1, j + 2
            if depth == 0:
                return j
        else:
            j += 1
    return j


def lex_rust(text: str) -> tuple[str, list[str]]:
    """(código con comentarios en blanco y cada literal cambiado por "N", valores)."""
    out, strings, i, n = [], [], 0, len(text)

    def emit(value: str, raw: str) -> None:
        # Los saltos de línea del literal se conservan para que las líneas cuadren.
        out.append(f'"{len(strings)}"' + "\n" * raw.count("\n"))
        strings.append(value)

    while i < n:
        ch = text[i]
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            out.append(" " * (end - i))
            i = end
            continue
        if text.startswith("/*", i):
            end = skip_block_comment(text, i)
            out.append(re.sub(r"[^\n]", " ", text[i:end]))
            i = end
            continue
        after_ident = i > 0 and (text[i - 1].isalnum() or text[i - 1] == "_")
        raw = None if after_ident else RAW_STRING.match(text, i)
        if raw:
            close = '"' + raw.group(1)
            end = text.find(close, raw.end())
            end = n if end < 0 else end
            emit(text[raw.end():end], text[raw.end():end])
            i = end + len(close)
            continue
        if ch in "bc" and not after_ident and text.startswith('"', i + 1):
            i += 1  # b"..." y c"...": el prefijo no importa
            ch = '"'
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            emit(decode_rust_string(text[i + 1:j]), text[i + 1:j])
            i = j + 1
            continue
        if ch == "'":
            char = CHAR_LITERAL.match(text, i)  # '"' no abre una cadena; 'a (lifetime) no casa
            if char:
                out.append("'c'")
                i = char.end()
                continue
        out.append(ch)
        i += 1
    return "".join(out), strings


def group_end(code: str, open_at: int) -> int:
    """Offset justo después del ) ] o } que cierra el abierto en open_at."""
    depth = 0
    for index in range(open_at, len(code)):
        if code[index] in "([{":
            depth += 1
        elif code[index] in ")]}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(code)


def call_args(code: str, open_at: int) -> list[str]:
    """Elementos (texto enmascarado) de la llamada o array abierto en open_at."""
    body = code[open_at + 1:group_end(code, open_at) - 1]
    args, depth, start = [], 0, 0
    for index, ch in enumerate(body):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == "," and depth == 0:
            args.append(body[start:index].strip())
            start = index + 1
    if body[start:].strip():
        args.append(body[start:].strip())
    return args


@dataclass
class RustFile:
    """Un .rs pasado por lex_rust, con los tramos que solo compilan en test."""
    path: Path
    code: str
    strings: list[str]
    test_spans: list[tuple[int, int]] = field(default_factory=list)
    test_only: bool = False

    def line(self, offset: int) -> int:
        return self.code.count("\n", 0, offset) + 1

    def where(self, offset: int) -> str:
        return where(self.path, self.line(offset))

    def in_test(self, offset: int) -> bool:
        return self.test_only or any(start <= offset < end for start, end in self.test_spans)

    def literal(self, expression: str) -> str | None:
        """Valor si la expresión es un literal ("N", &"N", Some("N"))."""
        match = re.fullmatch(r'&?\s*(?:Some\(\s*)?"(\d+)"\s*\)?', expression.strip())
        return self.strings[int(match.group(1))] if match else None

    def literals(self):
        """(valor, offset) de cada literal fuera del código de test."""
        for match in re.finditer(LIT, self.code):
            if not self.in_test(match.start()):
                yield self.strings[int(match.group(1))], match.start()

    def functions(self):
        """(nombre, parámetros, inicio, inicio del cuerpo, fin) de cada fn."""
        for match in re.finditer(r"\bfn\s+(\w+)\s*(?:<[^>{]*>)?\s*\(", self.code):
            params_end = group_end(self.code, match.end() - 1)
            body = re.compile(r"[^{;]*\{").match(self.code, params_end)
            if not body:
                continue  # declaración sin cuerpo (trait)
            params = [re.sub(r"^mut\s+", "", p.split(":")[0].strip())
                      for p in call_args(self.code, match.end() - 1) if ":" in p]
            yield match.group(1), params, match.start(), body.end(), group_end(self.code, body.end() - 1)


@lru_cache(maxsize=None)
def rust_files(crate_dir: Path) -> tuple[RustFile, ...]:
    """Fuentes de un crate (src/ y tests/), con el código de test marcado."""
    files = []
    for path in sorted(crate_dir.glob("src/**/*.rs")) + sorted(crate_dir.glob("tests/**/*.rs")):
        code, strings = lex_rust(testlib.read_text(path))
        files.append(RustFile(path, code, strings, test_only=path.is_relative_to(crate_dir / "tests")))
    by_path = {item.path: item for item in files}
    module = re.compile(r"(?:\s*#\[[^\]]*\])*\s*(?:pub(?:\([^)]*\))?\s+)?mod\s+(\w+)\s*([{;])")
    for item in files:
        for attr in re.finditer(r"#\[cfg\(test\)\]", item.code):
            found = module.match(item.code, attr.end())
            if not found:
                continue
            if found.group(2) == "{":
                item.test_spans.append((attr.start(), group_end(item.code, found.end() - 1)))
                continue
            base = item.path.parent if item.path.stem in {"main", "lib", "mod"} else item.path.with_suffix("")
            for candidate in (base / f"{found.group(1)}.rs", base / found.group(1) / "mod.rs"):
                if candidate in by_path:
                    by_path[candidate].test_only = True
        for attr in re.finditer(r"#\[test\]", item.code):
            body = item.code.find("{", attr.end())
            if body >= 0:
                item.test_spans.append((attr.start(), group_end(item.code, body)))
    return tuple(files)


def crate_files(crate: testlib.Crate) -> tuple[RustFile, ...]:
    return rust_files(crate.directory)


def const_strings(files, name_pattern: str) -> dict[str, list[tuple[str, RustFile, int]]]:
    """const NOMBRE: T = <literales>; -> {NOMBRE: [(valor, fichero, offset)]}."""
    found: dict[str, list] = {}
    for item in files:
        for match in re.finditer(rf"\bconst\s+({name_pattern})\s*:[^=]*=([^;]*);", item.code):
            if item.in_test(match.start()):
                continue
            found.setdefault(match.group(1), []).extend(
                (item.strings[int(lit.group(1))], item, match.start(2) + lit.start())
                for lit in re.finditer(LIT, match.group(2)))
    return found


# ------------------------------------------------------- crates, cargo y build-rust.sh

def deploy_crates() -> list[testlib.Crate]:
    return [crate for crate in testlib.crates() if crate.deploy]


def cargo_binaries(crate: testlib.Crate) -> set[str]:
    """Binarios que `cargo build` crea para un crate (reglas de targets de Cargo).

    Un [[bin]] sin path usa src/main.rs si se llama como el paquete y si no
    src/bin/<nombre>.rs. Con autobins (por defecto) src/main.rs da un binario
    con el nombre del paquete, salvo que un [[bin]] explícito ya use ese
    fichero, y cada src/bin/*.rs da uno con su nombre.
    """
    data = tomllib.loads(testlib.read_text(crate.directory / "Cargo.toml"))
    package = data.get("package", {})
    name, main = package.get("name", ""), crate.directory / "src/main.rs"
    bins, used = set(), set()
    for entry in data.get("bin", []):
        default = "src/main.rs" if entry.get("name") == name and main.is_file() else f"src/bin/{entry.get('name')}.rs"
        bins.add(entry.get("name", ""))
        used.add(os.path.normpath(entry.get("path", default)))
    if package.get("autobins", True):
        if main.is_file() and "src/main.rs" not in used:
            bins.add(name)
        for path in sorted((crate.directory / "src/bin").glob("*.rs")):
            if os.path.normpath(path.relative_to(crate.directory)) not in used:
                bins.add(path.stem)
    return bins


@dataclass(frozen=True)
class Deployment:
    """Lo que build-rust.sh deja en el airootfs: {ruta relativa: sha256}."""
    files: dict

    def bins(self) -> set[str]:
        return {path[len("usr/bin/"):] for path in self.files if path.startswith("usr/bin/")}


@lru_cache(maxsize=None)
def deployment() -> Deployment:
    """Ejecuta scripts/build-rust.sh en una copia mínima del repo con un cargo falso."""
    with tempfile.TemporaryDirectory(prefix="churros-rust-deploy-") as tmp:
        root, fake, target = Path(tmp) / "repo", Path(tmp) / "bin", Path(tmp) / "target"
        for directory in (root / "scripts", root / "rust", root / "archiso/airootfs/usr/bin", fake):
            directory.mkdir(parents=True)
        shutil.copy2(ROOT / "scripts/build-rust.sh", root / "scripts/build-rust.sh")
        shutil.copy2(ROOT / "scripts/deploy-rust-assets.sh", root / "scripts/deploy-rust-assets.sh")
        shutil.copy2(ROOT / "rust/Cargo.toml", root / "rust/Cargo.toml")
        names = set()
        for crate in testlib.crates():
            copy = root / "rust" / crate.directory.name
            copy.mkdir()
            shutil.copy2(crate.directory / "Cargo.toml", copy / "Cargo.toml")
            if (crate.directory / "assets").is_dir():
                shutil.copytree(crate.directory / "assets", copy / "assets")
            names |= cargo_binaries(crate)
        (fake / "cargo").write_text(
            "#!/bin/sh\nset -e\nmkdir -p \"$CARGO_TARGET_DIR/release\"\n"
            f"for b in {' '.join(shlex.quote(n) for n in sorted(names))}; do\n"
            "    printf '#!/bin/sh\\n' > \"$CARGO_TARGET_DIR/release/$b\"\n"
            "    chmod 755 \"$CARGO_TARGET_DIR/release/$b\"\n"
            "done\n")
        (fake / "cargo").chmod(0o755)
        env = dict(os.environ, PATH=f"{fake}:{os.environ.get('PATH', '/usr/bin:/bin')}", CARGO_TARGET_DIR=str(target))
        result = testlib.run(["bash", str(root / "scripts/build-rust.sh")], cwd=root, env=env, timeout=60)
        if result.returncode != 0:
            raise AssertionError(f"build-rust.sh (con cargo falso) salió con {result.returncode}:\n{result.stdout}")
        tree = root / "archiso/airootfs"
        return Deployment({str(p.relative_to(tree)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in tree.rglob("*") if p.is_file()})


def build_rust_view(crate: testlib.Crate) -> tuple[bool, str]:
    """(deploy, nombre) como los lee build-rust.sh: grep '^deploy = true$' y el primer sed."""
    lines = testlib.read_text(crate.directory / "Cargo.toml").split("\n")
    names = [re.sub(r'^name = "(.*)"', r"\1", line) for line in lines if re.match(r'^name = ".*"', line)]
    return "deploy = true" in lines, names[0] if names else ""


def owner_of(path: str) -> str:
    """App de una ruta generada (usr/bin/X o usr/share/churros/X/...)."""
    parts = path.split("/")
    return parts[2] if parts[:2] == ["usr", "bin"] else parts[3]


# --------------------------------------------------------------- shell y .desktop

WRAPPERS = {"env", "exec", "nohup", "setsid", "command", "nice", "ionice", "systemd-cat", "stdbuf",
            "dbus-run-session", "dbus-launch", "sudo", "doas", "pkexec", "runuser", "timeout", "uwsm", "uwsm-app"}
PUNCTUATION = set(";&|()<>")


def shell_tokens(text: str, posix: bool) -> list[str]:
    try:
        lexer = shlex.shlex(text, posix=posix, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


def shell_argvs(text: str) -> list[list[str | None]]:
    """argv de cada comando simple de una línea de shell (None = dinámico).

    Parte por ; & && | || ( ), quita redirecciones (2>/dev/null), variables
    (A=b) y envoltorios (env, exec, sudo -u x, timeout 5...). Una palabra
    con $ o ` vale None: su valor solo se sabe al ejecutar.
    """
    tokens, raw = shell_tokens(text, True), shell_tokens(text, False)
    commands, current, skip = [], [], False
    for index, token in enumerate(tokens):
        if skip:
            skip = False
        elif token and set(token) <= PUNCTUATION:
            if "<" in token or ">" in token:
                if current and current[-1] is not None and current[-1].isdigit():
                    current.pop()  # 2>/dev/null: el 2 es el descriptor
                skip = True  # el destino de la redirección
            elif current:
                commands.append(current)
                current = []
        else:
            dynamic = len(raw) == len(tokens) and ("$" in raw[index] or "`" in raw[index])
            current.append(None if dynamic else token)
    if current:
        commands.append(current)
    argvs = []
    for words in commands:
        index = 0
        while index < len(words):
            word = words[index]
            if word is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word):
                index += 1
            elif word in WRAPPERS:
                index += 1
                if word == "timeout" and index < len(words) and re.fullmatch(r"[0-9.]+[smhd]?", words[index] or ""):
                    index += 1
                while index < len(words) and (words[index] or "").startswith("-"):
                    index += 2 if words[index] in {"-u", "-g"} else 1
            else:
                break
        if index < len(words):
            argvs.append(words[index:])
    return argvs


def desktop_exec_argv(value: str) -> list[str] | None:
    """argv de un Exec= según la Desktop Entry Specification.

    Los field codes (%f, %U...) solo se convierten en argumentos si se abre
    un fichero; lanzado desde un menú o autostart desaparecen.
    """
    value = re.sub(r"\\([sntr\\])", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}[m.group(1)], value)
    try:
        words = shlex.split(value)
    except ValueError:
        return None
    return [w.replace("%%", "%") for w in words if not re.fullmatch(r"%[fFuUdDnNickvm]", w)]


def desktop_entry_lines(text: str) -> list[tuple[int, str]]:
    """(número, línea) de [Desktop Entry] y [Desktop Action *], donde Exec lanza algo."""
    lines, group = [], None
    for number, line in enumerate(text.split("\n"), 1):
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            group = line
        elif group and (group == "[Desktop Entry]" or group.startswith("[Desktop Action")):
            lines.append((number, line))
    return lines


def logical_lines(text: str):
    """(número, línea) de un script, uniendo las continuaciones con barra final."""
    buffer, start = "", 1
    for number, line in enumerate(text.split("\n"), 1):
        if not buffer:
            start = number
        if line.endswith("\\") and not line.endswith("\\\\"):
            buffer += line[:-1] + " "
            continue
        yield start, buffer + line
        buffer = ""
    if buffer:
        yield start, buffer


# ------------------------------------------------------------------- parser de KDL

@dataclass
class KdlNode:
    name: str
    args: list[str]
    props: dict[str, str]
    children: list["KdlNode"]
    line: int

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


KDL_BARE = re.compile(r'[^\s\\/(){}<>;\[\]=,"]+')
KDL_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "/": "/", '"': '"', "b": "\b", "f": "\f"}


def kdl_tokens(text: str):
    """(tipo, valor, línea): nl, str, id, slashdash y { } ; = ( )."""
    i, n, line = 0, len(text), 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            yield "nl", None, line
            line += 1
            i += 1
        elif ch in " \t\r﻿":
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = skip_block_comment(text, i)
            line += text.count("\n", i, end)
            i = end
        elif text.startswith("/-", i):
            yield "slashdash", None, line
            i += 2
        elif ch == "\\":  # continuación de línea
            end = text.find("\n", i)
            i = n if end < 0 else end + 1
            line += 1
        elif ch == '"':
            out, j = [], i + 1
            while j < n and text[j] != '"':
                if text[j] == "\\" and j + 1 < n:
                    if text[j + 1] == "u":
                        end = text.index("}", j)
                        out.append(chr(int(text[j + 3:end], 16)))
                        j = end + 1
                    else:
                        out.append(KDL_ESCAPES.get(text[j + 1], text[j + 1]))
                        j += 2
                else:
                    out.append(text[j])
                    j += 1
            yield "str", "".join(out), line
            line += text.count("\n", i, j)
            i = j + 1
        elif (raw := re.compile(r'r(#*)"').match(text, i)):
            end = text.find('"' + raw.group(1), raw.end())
            end = n if end < 0 else end
            yield "str", text[raw.end():end], line
            line += text.count("\n", i, end)
            i = end + 1 + len(raw.group(1))
        elif ch in "{};=()":
            yield ch, ch, line
            i += 1
        elif (bare := KDL_BARE.match(text, i)):
            yield "id", bare.group(), line
            i = bare.end()
        else:
            i += 1


def kdl_parse(text: str) -> list[KdlNode]:
    """Nodos de un documento KDL v1, sin comentarios ni lo anulado con /-."""
    tokens = list(kdl_tokens(text))
    pos = 0

    def skip_annotation():
        nonlocal pos
        if pos < len(tokens) and tokens[pos][0] == "(":
            while pos < len(tokens) and tokens[pos][0] != ")":
                pos += 1
            pos += 1

    def entries(node: KdlNode):
        nonlocal pos
        skip_next = False
        while pos < len(tokens):
            kind = tokens[pos][0]
            if kind in ("nl", ";"):
                pos += 1
                return
            if kind == "}":
                return
            if kind == "slashdash":
                skip_next, pos = True, pos + 1
                continue
            if kind == "{":
                pos += 1
                children = nodes(True)
                if not skip_next:
                    node.children = children
            else:
                skip_annotation()
                if pos >= len(tokens):
                    return
                kind, value, _ = tokens[pos]
                if kind in ("id", "str") and pos + 1 < len(tokens) and tokens[pos + 1][0] == "=":
                    pos += 2
                    skip_annotation()
                    if not skip_next and pos < len(tokens):
                        node.props[value] = tokens[pos][1]
                elif not skip_next and kind in ("id", "str"):
                    node.args.append(value)
                pos += 1
            skip_next = False

    def nodes(in_block: bool) -> list[KdlNode]:
        nonlocal pos
        result = []
        while pos < len(tokens):
            kind = tokens[pos][0]
            if kind in ("nl", ";"):
                pos += 1
                continue
            if kind == "}":
                pos += 1
                if in_block:
                    return result
                continue
            discard = kind == "slashdash"
            pos += 1 if discard else 0
            skip_annotation()
            if pos >= len(tokens):
                break
            node = KdlNode(str(tokens[pos][1]), [], {}, [], tokens[pos][2])
            pos += 1
            entries(node)
            if not discard:
                result.append(node)
        return result

    return nodes(False)


# ------------------------------------------------------------------ ficheros del airootfs

def airootfs_files() -> list[Path]:
    """Ficheros regulares del airootfs (los enlaces de systemd apuntan fuera del repo)."""
    return [p for p in testlib.repo_files() if p.is_relative_to(AIROOTFS) and not p.is_symlink() and p.is_file()]


def niri_configs() -> list[Path]:
    return [path for path in airootfs_files() if path.suffix == ".kdl"]


@lru_cache(maxsize=None)
def product_scripts() -> tuple[Path, ...]:
    """Scripts de shell que van a la ISO o corren al construirla (no los de desarrollo)."""
    tops = (ROOT / "archiso", ROOT / "branding", ROOT / "installer")
    return tuple(path for path, _ in testlib.shell_scripts() if any(path.is_relative_to(top) for top in tops))


def strip_jsonc_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("\n" * text.count("\n", i, end))
            i = end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


# ------------------------------------------------------------- invocaciones

@dataclass(frozen=True)
class Invocation:
    source: str
    argv: tuple[str | None, ...]


def deploy_binary(word: str | None) -> str | None:
    """Nombre del binario Rust desplegado al que se refiere `word`, si lo es."""
    if not word:
        return None
    match = re.fullmatch(r"/usr/(?:local/)?bin/([^/]+)", word)
    name = match.group(1) if match else word
    return name if name in testlib.deploy_crate_names() else None


def from_shell(source: str, text: str) -> list[Invocation]:
    return [Invocation(source, tuple(argv)) for argv in shell_argvs(text)]


def from_argv(source: str, argv: list[str | None]) -> list[Invocation]:
    if len(argv) >= 3 and Path(argv[0] or "").name in {"sh", "bash"} and argv[1] == "-c" and argv[2]:
        return from_shell(source, argv[2])
    return [Invocation(source, tuple(argv))] if argv else []


def from_exec_line(source: str, line: str) -> list[Invocation]:
    argv = desktop_exec_argv(line[len("Exec="):]) if line.startswith("Exec=") else None
    return [Invocation(source, tuple(argv))] if argv else []


def niri_invocations() -> list[Invocation]:
    found = []
    for path in niri_configs():
        for top in kdl_parse(testlib.read_text(path)):
            for node in top.walk():
                if node.name in ("spawn", "spawn-at-startup"):
                    found += from_argv(where(path, node.line), list(node.args))
                elif node.name in ("spawn-sh", "spawn-sh-at-startup") and node.args:
                    found += from_shell(where(path, node.line), node.args[0])
    return found


def desktop_invocations() -> list[Invocation]:
    """Exec= de los .desktop del airootfs y de los que escriben scripts (heredoc) y Rust."""
    found = []
    for path in airootfs_files():
        if path.suffix == ".desktop":
            for number, line in desktop_entry_lines(testlib.read_text(path)):
                found += from_exec_line(where(path, number), line)
    for path in product_scripts():
        for number, line in enumerate(testlib.read_text(path).split("\n"), 1):
            found += from_exec_line(where(path, number), line)
    for crate in testlib.crates():
        for item in crate_files(crate):
            for value, offset in item.literals():
                for line in value.split("\n"):
                    found += from_exec_line(item.where(offset), line)
    return found


def config_invocations() -> list[Invocation]:
    """waybar, atajos de XFCE, Whisker Menu, labwc, unidades systemd y hooks de pacman."""
    found = []
    for path in airootfs_files():
        text = testlib.read_text(path)
        if "waybar" in path.parts and path.suffix in (".jsonc", ".json", ""):
            # waybar lanza on-click*, on-scroll-* y exec con sh -c.
            clean = strip_jsonc_comments(text)
            for match in re.finditer(r'"(on-[a-z-]+|exec(?:-if|-on-event)?)"\s*:\s*("(?:[^"\\]|\\.)*")', clean):
                found += from_shell(where(path, clean.count("\n", 0, match.start()) + 1), json.loads(match.group(2)))
        elif path.name == "xfce4-keyboard-shortcuts.xml":
            # Los comandos van bajo <property name="commands">; xfsettingsd los lanza
            # con g_spawn_command_line_async (argv de shell, sin shell).
            for commands in ET.parse(path).iter("property"):
                if commands.get("name") == "commands":
                    for prop in commands.iter("property"):
                        if prop.get("type") == "string" and prop.get("value"):
                            found += from_shell(f"{testlib.rel(path)} ({prop.get('name')})", prop.get("value"))
        elif re.fullmatch(r"whiskermenu-\d+\.rc", path.name):
            for number, line in enumerate(text.split("\n"), 1):
                if (match := re.match(r"command-[\w-]+=(.+)", line)):
                    found += from_shell(where(path, number), match.group(1))
        elif "labwc" in path.parts and path.suffix == ".xml":
            for command in ET.parse(path).iter("command"):
                if command.text:
                    found += from_shell(testlib.rel(path), command.text.strip())
        elif path.suffix in (".service", ".hook"):
            for number, line in enumerate(text.split("\n"), 1):
                match = re.match(r"\s*Exec(?:Start|StartPre|StartPost|Stop|StopPost|Reload|Condition)?\s*=\s*(.+)", line)
                if match:
                    try:
                        found += from_argv(where(path, number), shlex.split(re.sub(r"^[-@:+!]+", "", match.group(1).strip())))
                    except ValueError:
                        pass
    return found


def script_invocations() -> list[Invocation]:
    found = []
    for path in product_scripts():
        for number, line in logical_lines(testlib.read_text(path)):
            if not line.lstrip().startswith("#"):
                found += from_shell(where(path, number), line)
    return found


def rust_invocations() -> list[Invocation]:
    """Arrays ["churros-x", ...] y Command::new("churros-x") del código Rust.

    Un argumento que es un parámetro de la función envolvente se resuelve en
    cada llamada con literal: open_popup(&win, "battery") -> churros-popup battery.
    """
    found = []
    for crate in testlib.crates():
        files = crate_files(crate)
        for item in files:
            for match in re.finditer(r"\[\s*" + LIT, item.code):
                head = item.strings[int(match.group(1))]
                # const PROTECTED_PACKAGES: &[&str] = &["churros-settings", ...]
                # es una lista de nombres, no la línea de órdenes de un lanzador.
                listed = re.search(r"\b(?:const|static)\s+\w+\s*:[^=;{}]*=\s*&?\s*$",
                                   item.code[max(0, match.start() - 200):match.start()])
                if deploy_binary(head) and not listed and not item.in_test(match.start()):
                    found += resolve_args(files, item, match.start(), head, call_args(item.code, match.start())[1:])
            for match in re.finditer(r"Command::new\(\s*" + LIT + r"\s*\)", item.code):
                head = item.strings[int(match.group(1))]
                if not deploy_binary(head) or item.in_test(match.start()):
                    continue
                args, pos = [], match.end()
                while (call := re.compile(r"\s*\.(args?)\(").match(item.code, pos)):
                    inner = call_args(item.code, call.end() - 1)
                    if call.group(1) == "args" and inner and re.match(r"&?\[", inner[0]):
                        inner = call_args(item.code, item.code.index("[", call.end()))
                    args += inner
                    pos = group_end(item.code, call.end() - 1)
                found += resolve_args(files, item, match.start(), head, args)
    return found


def resolve_args(files, item: RustFile, offset: int, head: str, args: list[str]) -> list[Invocation]:
    if all(item.literal(arg) is not None for arg in args):
        return [Invocation(item.where(offset), (head, *(item.literal(arg) for arg in args)))]
    enclosing = [(name, params, start) for name, params, start, body, end in item.functions() if body <= offset < end]
    if not enclosing:
        return [Invocation(item.where(offset), (head, *(item.literal(arg) for arg in args)))]
    name, params, _ = max(enclosing, key=lambda f: f[2])
    found = []
    for other in files:
        for call in re.finditer(rf"(?<![\w.]){name}\s*\(", other.code):
            if other.in_test(call.start()) or re.search(r"\bfn\s+$", other.code[max(0, call.start() - 8):call.start()]):
                continue
            actual = call_args(other.code, call.end() - 1)
            argv = [head]
            for arg in args:
                if item.literal(arg) is not None:
                    argv.append(item.literal(arg))
                elif arg in params and params.index(arg) < len(actual):
                    argv.append(other.literal(actual[params.index(arg)]))
                else:
                    argv.append(None)
            found.append(Invocation(other.where(call.start()), tuple(argv)))
    return found or [Invocation(item.where(offset), (head, *(item.literal(arg) for arg in args)))]


@lru_cache(maxsize=None)
def invocations() -> tuple[Invocation, ...]:
    everything = (niri_invocations() + desktop_invocations() + config_invocations()
                  + script_invocations() + rust_invocations())
    return tuple(inv for inv in everything if inv.argv and deploy_binary(inv.argv[0]))


# --------------------------------------------------------- modelo de la CLI de cada app

@dataclass
class CliModel:
    """Qué argumentos acepta un binario desplegado, leído de su código."""
    name: str
    hands_argv: bool | None  # True: app.run() pasa argv a GApplication. None: no se sabe
    options: set[str]
    handles_open: bool
    handles_command_line: bool
    where: str
    popups: list[str] | None = None
    popup_arms: set[str] = field(default_factory=set)
    wildcard_aborts: bool = False


@lru_cache(maxsize=None)
def cli_models() -> dict[str, CliModel]:
    models = {}
    for crate in deploy_crates():
        files = [f for f in crate_files(crate) if not f.test_only]
        app_files = [f for f in files if re.search(r"\bApplication::(?:builder|new)\b", f.code)]
        code = "\n".join(f.code for f in app_files)
        plain_run, with_args = re.search(r"\.run\(\s*\)", code), re.search(r"\.run_with_args\(", code)
        # Si conviven los dos no se sabe qué rama toma cada lanzador: no se juzga.
        hands_argv = bool(plain_run) if bool(plain_run) != bool(with_args) else None
        options = {item.strings[int(m.group(1))] for item in files
                   for m in re.finditer(r"\b(?:add_main_option|OptionEntry::builder)\(\s*" + LIT, item.code)}
        everything = "\n".join(f.code for f in files)
        model = CliModel(crate.name, hands_argv, options,
                         "HANDLES_OPEN" in everything or "connect_open" in everything,
                         "HANDLES_COMMAND_LINE" in everything or "connect_command_line" in everything,
                         ", ".join(testlib.rel(f.path) for f in app_files))
        popups = const_strings(files, "POPUPS")
        if popups:
            model.popups = [value for value, _, _ in popups["POPUPS"]]
            model.popup_arms, model.wildcard_aborts = popup_arms(files)
        models[crate.name] = model
    return models


def popup_arms(files) -> tuple[set[str], bool]:
    """Nombres con rama propia en build_window y si el comodín `_` aborta."""
    for item in files:
        function = re.search(r"\bfn\s+build_window\b[^{]*\{", item.code)
        if function:
            body = item.code[function.end():group_end(item.code, function.end() - 1)]
            arms = {item.strings[int(n)] for arm in re.finditer(r'((?:"\d+"\s*\|\s*)*"\d+")\s*=>', body)
                    for n in re.findall(r'"(\d+)"', arm.group(1))}
            return arms, bool(re.search(r"\b_\s*=>\s*(?:unreachable|panic|todo|unimplemented)!", body))
    return set(), False


def gapplication_problem(model: CliModel, args: list[str | None]) -> str | None:
    """Por qué GApplication rechaza estos argumentos, o None si los acepta.

    g_application_run() pasa argv a local_command_line: un GOptionContext con
    las opciones registradas (add_main_option*) más --help. Una opción
    desconocida sale con "Unknown option" y código 1; un argumento suelto
    sin HANDLES_OPEN, con "This application can not open files" y código 1
    (comprobado con GLib 2.80). Con HANDLES_COMMAND_LINE y sin opciones
    propias GLib ignora lo desconocido y lo trata el handler.
    """
    if model.hands_argv is not True or (model.handles_command_line and not model.options):
        return None
    for arg in args:
        if arg is None:
            continue
        if arg == "--":
            return None
        if arg.startswith("--"):
            if arg[2:].split("=", 1)[0] not in model.options | {"help", "help-all", "help-gapplication"}:
                return (f"GApplication rechaza '{arg}' (\"Unknown option\", sale con 1): {model.where} llama a "
                        "app.run(), que le entrega std::env::args(), y no registra la opción con add_main_option")
        elif arg.startswith("-") and len(arg) > 1:
            if not model.options and arg not in {"-h", "-?"}:
                return f"GApplication rechaza '{arg}' (\"Unknown option\", sale con 1): {model.where} no registra opciones"
        elif not (model.handles_open or model.handles_command_line):
            return (f"GApplication toma '{arg}' por un fichero y sale con 1 (\"This application can not open "
                    f"files\"): {model.where} llama a app.run() sin HANDLES_OPEN")
    return None


def invocation_problem(model: CliModel, args: list[str | None]) -> str | None:
    if model.popups is not None and (name := args[0] if args else "") is not None:
        if name not in model.popups:
            return (f"'{name}' no está en POPUPS de rust/popups/src/main.rs ({', '.join(model.popups)}): "
                    "churros-popup sale con 64 sin abrir nada")
        if name not in model.popup_arms and model.wildcard_aborts:
            return f"'{name}' no tiene rama en build_window: unreachable!() aborta (panic = \"abort\")"
    return gapplication_problem(model, args)


# ------------------------------------------------------------------- application ids

@lru_cache(maxsize=None)
def application_ids() -> dict[str, str]:
    """{app id real: crate}. format!("org.churros.popup.{name}") se expande con POPUPS."""
    ids = {}
    for crate in deploy_crates():
        files = crate_files(crate)
        consts = const_strings(files, r"[A-Z_][A-Z0-9_]*")
        popups = [value for value, _, _ in consts.get("POPUPS", [])]
        for item in files:
            for match in re.finditer(r"\.application_id\(\s*|\bApplication::new\(\s*Some\(\s*", item.code):
                if item.in_test(match.start()):
                    continue
                literal = re.compile(LIT).match(item.code, match.end())
                constant = re.compile(r"([A-Z_][A-Z0-9_]*)\b").match(item.code, match.end())
                template = re.compile(r"&?format!\(\s*" + LIT).match(item.code, match.end())
                if literal:
                    ids[item.strings[int(literal.group(1))]] = crate.name
                elif constant and constant.group(1) in consts:
                    ids.update({value: crate.name for value, _, _ in consts[constant.group(1)]})
                elif template:
                    pattern = item.strings[int(template.group(1))]
                    ids.update({re.sub(r"\{[^}]*\}", sample, pattern): crate.name for sample in popups or ["x"]})
    return ids


def desktop_exec_sources(desktop_id: str) -> list[tuple[str, str]]:
    """(origen, valor de Exec) del .desktop en el airootfs y en heredocs que lo escriben."""
    found, target = [], f"/usr/share/applications/{desktop_id}"
    path = testlib.airootfs(target)
    if path.is_file():
        found += [(where(path, n), line[5:]) for n, line in desktop_entry_lines(testlib.read_text(path)) if line.startswith("Exec=")]
    heredoc = re.compile(rf"cat\s+>\s*['\"]?{re.escape(target)}['\"]?\s*<<-?\s*['\"]?(\w+)['\"]?\n(.*?)\n\s*\1\n", re.DOTALL)
    for script in product_scripts():
        text = testlib.read_text(script)
        for match in heredoc.finditer(text):
            first = text.count("\n", 0, match.start(2)) + 1
            found += [(where(script, first + n - 1) + " (heredoc)", line[5:])
                      for n, line in desktop_entry_lines(match.group(2)) if line.startswith("Exec=")]
    return found


# ======================================================================= pruebas

class DeployContract(unittest.TestCase):
    """build-rust.sh, profiledef.sh, build.sh, clean.sh y .gitignore."""

    @classmethod
    def setUpClass(cls):
        if tomllib is None:
            raise unittest.SkipTest("tomllib necesita Python >= 3.11")
        cls.deployed = deployment()
        cls.bins = cls.deployed.bins()
        cls.names = sorted(set(testlib.deploy_crate_names()) | cls.bins)

    def test_every_deploy_crate_reaches_usr_bin(self):
        findings = {}
        for crate in deploy_crates():
            if crate.name in self.bins:
                continue
            produced = cargo_binaries(crate)
            grep_deploy, sed_name = build_rust_view(crate)
            if crate.name not in produced:
                why = f"cargo produce {sorted(produced) or 'ningún binario'} y build-rust.sh copia target/release/{crate.name}"
            elif not grep_deploy:
                why = "build-rust.sh no lo ve: busca la línea exacta 'deploy = true' (grep '^deploy = true$')"
            elif sed_name != crate.name:
                why = f"build-rust.sh toma el primer 'name = ' del TOML ('{sed_name}'), no el del paquete"
            else:
                why = "build-rust.sh no lo despliega"
            findings[f"deploy:bin:{crate.name}"] = (
                f"{testlib.rel(crate.directory / 'Cargo.toml')}: {why}; como su `if [ -x ]` no tiene else, "
                f"lo salta en silencio y la ISO sale sin /usr/bin/{crate.name}")
        for name in sorted(self.bins - testlib.deploy_crate_names()):
            findings[f"deploy:bin:{name}"] = f"build-rust.sh despliega /usr/bin/{name}, que no es un crate con deploy = true"
        testlib.assert_findings(self, "deploy:bin", findings)

    def test_binaries_are_executable_in_every_arch(self):
        # mkarchiso copia el airootfs con cp --no-preserve=mode: el +x solo lo da file_permissions.
        findings = {}
        for name in self.names:
            missing = [arch for arch in testlib.ARCHES if not testlib.mode_is_executable(
                testlib.profile(arch)["file_permissions"].get(f"/usr/bin/{name}", ""))]
            if missing:
                findings[f"deploy:perm:{name}"] = (
                    f"archiso/profiledef.sh no da modo ejecutable a /usr/bin/{name} en {', '.join(missing)}: "
                    "llega a la ISO con 0644 y todo lanzador falla con 'permission denied'")
        testlib.assert_findings(self, "deploy:perm", findings)

    def check_removed(self, category: str, script: str, label: str):
        """Ejecuta `script` (bash) en un árbol temporal con los binarios desplegados.

        Se comprueba el efecto, no el texto: da igual que el script enumere los
        `rm` o recorra los crates con deploy = true. sudo, findmnt y mountpoint
        son falsos y nada sale del directorio temporal.
        """
        with tempfile.TemporaryDirectory(prefix="churros-clean-") as tmp:
            root = Path(tmp)
            for manifest in (ROOT / "rust").glob("*/Cargo.toml"):
                dest = root / manifest.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(manifest.read_bytes())
            for helper in ("scripts/apply-aarch64-mkinitcpio.sh",):
                (root / helper).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / helper, root / helper)
            bin_dir = root / "archiso/airootfs/usr/bin"
            bin_dir.mkdir(parents=True)
            for name in self.names:
                (bin_dir / name).write_bytes(b"\x7fELF fake")
            tracked = [path.name for path in (AIROOTFS / "usr/bin").iterdir() if path.is_file()]
            for name in tracked:
                shutil.copy2(AIROOTFS / "usr/bin" / name, bin_dir / name)
            stubs = root / ".stubs"
            stubs.mkdir()
            for name, body in {"sudo": 'exec "$@"', "findmnt": "exit 0", "mountpoint": "exit 1"}.items():
                (stubs / name).write_text(f"#!/bin/sh\n{body}\n")
                (stubs / name).chmod(0o755)
            (root / "run.sh").write_text(script)
            env = testlib.scratch_env(PATH=f"{stubs}:{os.environ.get('PATH', '/usr/bin:/bin')}")
            result = testlib.run(["bash", "run.sh"], cwd=root, env=env, timeout=60)
            left = {name for name in self.names if (bin_dir / name).exists()}
            lost = sorted(name for name in tracked if not (bin_dir / name).exists())
        self.assertFalse(lost, f"{label} borra scripts versionados de archiso/airootfs/usr/bin: {lost}")
        findings = {
            f"{category}:{name}": (f"{label} no borra archiso/airootfs/usr/bin/{name}, que build-rust.sh crea "
                                   f"en cada build (salida del script: {result.stdout.strip()[-300:]!r})")
            for name in sorted(left)}
        testlib.assert_findings(self, category, findings)

    def test_cleanup_trap_removes_binaries(self):
        text = testlib.read_text(ROOT / "scripts/cli/build.sh")
        body = re.search(r"^cleanup_temp\(\)\s*\{\n.*?^\}", text, re.MULTILINE | re.DOTALL)
        self.assertIsNotNone(body, "scripts/cli/build.sh ya no define cleanup_temp() { ... }: actualiza esta prueba")
        self.assertRegex(text, r"(?m)^trap cleanup_temp EXIT", "scripts/cli/build.sh ya no instala cleanup_temp como trap EXIT")
        # El trap usa variables y funciones de build.sh: se dan valores neutros.
        script = ("unmount_work_submounts() { :; }\nHOST_REPO_SYMLINK=0\nPACKAGES_BACKED_UP=0\n"
                  "PACKAGE_LIST=archiso/packages.x86_64\n" + body.group(0) + "\ncleanup_temp\n")
        self.check_removed("deploy:trap", script, "el trap cleanup_temp de scripts/cli/build.sh")

    def test_clean_removes_binaries(self):
        self.check_removed("deploy:clean", testlib.read_text(ROOT / "scripts/cli/clean.sh"),
                           "scripts/cli/clean.sh (./churros clean)")

    def test_generated_files_are_gitignored(self):
        git = testlib.require_tool(self, "git")
        paths = sorted(f"archiso/airootfs/{p}" for p in self.deployed.files)
        # --no-index: mira solo los patrones, también para lo que ya está versionado.
        result = testlib.run([git, "-c", "core.excludesFile=/dev/null", "check-ignore", "--no-index", *paths])
        if result.returncode not in (0, 1):
            self.fail(f"git check-ignore falló:\n{result.stdout}")
        ignored, missing = set(result.stdout.split()), {}
        for path in paths:
            if path not in ignored:
                missing.setdefault(owner_of(path.split("/", 2)[2]), set()).add(
                    re.sub(r"^(archiso/airootfs/usr/share/churros/[^/]+/).*", r"\1", path))
        testlib.assert_findings(self, "deploy:gitignore", {
            f"deploy:gitignore:{name}": (
                f".gitignore no cubre {', '.join(sorted(items))}: build-rust.sh lo escribe en el árbol del repo, "
                "aparece en git status y acaba versionado")
            for name, items in missing.items()})

    def test_tracked_copies_are_not_stale(self):
        git = testlib.require_tool(self, "git")
        targets = [f"archiso/airootfs/{d}/{n}" for n in self.names for d in ("usr/bin", "usr/share/churros")]
        result = testlib.run([git, "ls-files", "-z", "--", *targets])
        if result.returncode != 0:
            self.skipTest("no es un repositorio git")
        stale: dict[str, list[str]] = {}
        for path in filter(None, result.stdout.split("\0")):
            rel = path.split("/", 2)[2]
            if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != self.deployed.files.get(rel):
                stale.setdefault(owner_of(rel), []).append(path)
        testlib.assert_findings(self, "deploy:stale", {
            f"deploy:stale:{name}": (
                f"{', '.join(paths[:3])}{' ...' if len(paths) > 3 else ''}: versionado en git y distinto de lo que "
                "build-rust.sh despliega desde rust/ (cada build lo sobrescribe; un checkout limpio lleva la copia vieja)")
            for name, paths in stale.items()})

    def test_runtime_roots_point_to_deployed_assets(self):
        findings = {}
        for crate in deploy_crates():
            assets = crate.directory / "assets"
            if not assets.is_dir():
                continue
            files = crate_files(crate)
            roots = [(value, item, offset) for name, values in const_strings(files, r"[A-Z_]*ROOTS?").items()
                     if name != "DEV_ROOT" for value, item, offset in values if value.startswith("/")]
            if not roots:
                reads_dev = any(item.strings[int(m.group(1))] == "CARGO_MANIFEST_DIR" and item.strings[int(m.group(2))] == "/assets"
                                and not item.in_test(m.start()) for item in files for m in re.finditer(MANIFEST_PATH, item.code))
                if reads_dev:
                    findings[f"deploy:runtime-root:{crate.name}"] = (
                        f"{testlib.rel(crate.directory)} lee assets de CARGO_MANIFEST_DIR/assets y no tiene RUNTIME_ROOT: "
                        "en la ISO esa ruta del host de build no existe")
                continue
            asset_files = [p.relative_to(assets).as_posix() for p in assets.rglob("*") if p.is_file()]
            # control-center y preferences prueban también <raíz>/assets/<fichero>.
            nested = any(value.startswith("assets/") for item in files for value, _ in item.literals())
            if any(all(f"{prefix}/{rel}" in self.deployed.files for rel in asset_files)
                   for value, _, _ in roots for prefix in [value.strip("/")] + ([value.strip("/") + "/assets"] if nested else [])):
                continue
            first = asset_files[0] if asset_files else ""
            deployed_dirs = sorted("/" + p[:-len(first) - 1] for p in self.deployed.files
                                   if first and p.endswith("/" + first) and owner_of(p) == crate.name)
            findings[f"deploy:runtime-root:{crate.name}"] = (
                f"{', '.join(f'{v} ({i.where(o)})' for v, i, o in roots)}: build-rust.sh deja los assets en "
                f"{', '.join(deployed_dirs) or '(ningún sitio)'}; en la ISO is_dir() falla, se cae a CARGO_MANIFEST_DIR "
                "(una ruta del host de build) y faltan iconos y CSS")
        testlib.assert_findings(self, "deploy:runtime-root", findings)


class RustAssets(unittest.TestCase):
    """Literales de Rust que nombran ficheros del crate o del airootfs."""

    @classmethod
    def setUpClass(cls):
        if tomllib is None:
            raise unittest.SkipTest("tomllib necesita Python >= 3.11")

    @staticmethod
    def asset_helpers(files) -> tuple[list[RustFile], set[str]]:
        """Ficheros que definen la raíz de assets y las funciones que exponen.

        Un CSS que se pasa a una de esas funciones (PopupWindow::new(.., "audio.css"),
        load_css("x.css")) o que aparece en esos ficheros se lee de assets/.
        """
        root_files = [f for f in files if re.search(r"\bconst\s+[A-Z_]*ROOTS?\b|\bfn\s+assets_root\b", f.code)]
        helpers = set()
        for item in root_files:
            impls = [(m.group(1), m.end(), group_end(item.code, m.end() - 1))
                     for m in re.finditer(r"\bimpl\s+(\w+)\s*\{", item.code)]
            for name, _, start, _, _ in item.functions():
                owner = next((impl for impl, open_at, end in impls if open_at <= start < end), None)
                helpers.add(f"{owner}::{name}" if owner else name)
        return root_files, helpers

    def test_asset_references_exist(self):
        findings = {}
        for crate in testlib.crates():
            files = crate_files(crate)
            assets = crate.directory / "assets"
            names = {p.name for p in assets.rglob("*") if p.is_file()} if assets.is_dir() else set()
            root_files, helpers = self.asset_helpers(files)
            for item in files:
                for value, offset in item.literals() if assets.is_dir() else ():
                    before = item.code[max(0, offset - 200):offset]
                    call = re.search(r"\b([A-Z]\w*::\w+|\w+)\s*\([^()]*$", before)
                    problem = None
                    # ".png" a secas es un sufijo (strip_suffix(".png")), no un fichero.
                    if re.fullmatch(r"[\w-][\w.-]*", value) and value.lower().endswith(IMAGE_EXT):
                        direct = re.search(r"\b(icon_path|icons_path|icon_image|image_path)\(\s*$", before)
                        if direct:
                            sub = "" if direct.group(1) == "image_path" else "icons/"
                            if not (assets / sub / value).is_file():
                                problem = f"{direct.group(1)}(\"{value}\") busca assets/{sub}{value}, que no existe"
                        elif value not in names and not (call and call.group(1) == "join" and item not in root_files):
                            # .join("x.png") fuera del módulo de assets construye otra ruta (HOME, wallpapers).
                            problem = f"'{value}' no existe en {testlib.rel(assets)}: GTK muestra el icono de imagen rota"
                    elif re.fullmatch(r"[\w.-]+\.(?:css|ui)", value) and value not in names:
                        if item in root_files or (call and call.group(1) in helpers):
                            problem = f"'{value}' se lee de los assets del crate y no existe en {testlib.rel(assets)}"
                    elif re.fullmatch(r"assets/[\w./-]+", value) and not (crate.directory / value).exists():
                        problem = f"'{value}' no existe en {testlib.rel(crate.directory)}"
                    if problem:
                        findings[f"rust-asset:{crate.name}:{value}"] = f"{item.where(offset)}: {problem}"
                # include_str!/include_bytes! y concat!(env!("CARGO_MANIFEST_DIR"), ...), también en tests.
                for match in re.finditer(r"\binclude_(?:str|bytes)!\(\s*" + LIT, item.code):
                    rel_path = item.strings[int(match.group(1))]
                    if not (item.path.parent / rel_path).exists():
                        findings[f"rust-asset:{crate.name}:{rel_path}"] = (
                            f"{item.where(match.start())}: include!(\"{rel_path}\") apunta a un fichero que no existe: "
                            "el crate no compila")
                for match in re.finditer(MANIFEST_PATH, item.code):
                    rel_path = item.strings[int(match.group(2))]
                    if item.strings[int(match.group(1))] == "CARGO_MANIFEST_DIR" and not (crate.directory / rel_path.lstrip("/")).exists():
                        findings[f"rust-asset:{crate.name}:{rel_path}"] = f"{item.where(match.start())}: CARGO_MANIFEST_DIR{rel_path} no existe"
        testlib.assert_findings(self, "rust-asset", findings)

    def test_system_paths_exist_in_airootfs(self):
        """Rutas de /usr/share/churros y /etc/skel que el código Rust lee en la ISO."""
        generated = {f"/{p}" for p in deployment().files}
        findings = {}
        for crate in testlib.crates():
            files = crate_files(crate)
            # Las RUNTIME_ROOT(S) son candidatas con fallback: las juzga DeployContract.
            roots = {offset for values in const_strings(files, r"[A-Z_]*ROOTS?").values() for _, _, offset in values}
            for item in files:
                for value, offset in item.literals():
                    if offset in roots or not re.fullmatch(r"/(?:usr/share/churros|etc/skel)(?:/[^\s{}*\"]*)?", value):
                        continue
                    path = value.rstrip("/")
                    if not testlib.airootfs(path).exists() and not any(g == path or g.startswith(path + "/") for g in generated):
                        findings[f"rust-path:{path}"] = f"{item.where(offset)}: {path} no existe en archiso/airootfs ni lo genera build-rust.sh"
        testlib.assert_findings(self, "rust-path", findings)


class LauncherArguments(unittest.TestCase):
    """Cada lanzador de un binario Rust usa argumentos que ese binario acepta."""

    @classmethod
    def setUpClass(cls):
        if tomllib is None:
            raise unittest.SkipTest("tomllib necesita Python >= 3.11")

    def test_collectors_see_the_launchers(self):
        # Si un parser deja de ver los lanzadores, las demás pruebas pasarían sin mirar nada.
        self.assertTrue(invocations(), "no se encontró ninguna invocación de un binario Rust desplegado")
        sources = {inv.source.split(":")[0].split(" ")[0] for inv in invocations()}
        for path in niri_configs():
            text = testlib.read_text(path)
            self.assertTrue(kdl_parse(text), f"{testlib.rel(path)}: el parser KDL no ve ningún nodo")
            if re.search(r'^[^/\n]*\bspawn(?:-sh)?(?:-at-startup)?\s+"[^"]*churros-', text, re.MULTILINE):
                self.assertIn(testlib.rel(path), sources, f"{testlib.rel(path)} lanza apps Rust y el parser no lo ve")
        for name, model in cli_models().items():
            if model.where:
                self.assertIsNotNone(model.hands_argv, f"{model.where}: no se reconoce cómo arranca GApplication; actualiza esta prueba")

    def test_launcher_arguments_are_accepted(self):
        models = cli_models()
        popup = next((m for m in models.values() if m.popups is not None), None)
        self.assertIsNotNone(popup, "rust/popups ya no define POPUPS: actualiza esta prueba")
        findings = {}
        for inv in invocations():
            name = deploy_binary(inv.argv[0])
            problem = invocation_problem(models[name], list(inv.argv[1:])) if name in models else None
            if problem:
                shown = " ".join(a if a is not None else "<dinámico>" for a in (name, *inv.argv[1:]))
                key = f"rust-cli:{shown}"
                findings[key] = f"{findings[key]}; también {inv.source}" if key in findings else f"{inv.source}: `{shown}`: {problem}"
        for name in popup.popups:
            if name not in popup.popup_arms and popup.wildcard_aborts:
                findings.setdefault(f"rust-cli:{popup.name} {name}", (
                    f"rust/popups/src/main.rs: '{name}' está en POPUPS pero build_window no tiene rama: "
                    f"`churros-popup {name}` llega a unreachable!() y aborta (panic = \"abort\")"))
        testlib.assert_findings(self, "rust-cli", findings)

    def test_installer_desktop_passes_welcome_allowlist(self):
        """churros-welcome solo lanza el .desktop del instalador si su Exec está en ALLOWED_LAUNCHERS."""
        findings = {}
        for crate in deploy_crates():
            files = [f for f in crate_files(crate) if not f.test_only]
            allowed = {value for values in const_strings(files, r"ALLOWED_\w+").values() for value, _, _ in values}
            if not allowed:
                continue
            # Funciones que buscan en .../applications/ y, por transitividad, las que las llaman.
            bodies = [(name, item, item.code[body:end]) for item in files for name, _, _, body, end in item.functions()]
            lookups = {name for name, item, body in bodies
                       if any(item.strings[int(n)] == "applications" for n in re.findall(LIT, body))}
            while (more := {name for name, _, body in bodies if name not in lookups
                            and any(re.search(rf"\b{f}\s*\(", body) for f in lookups)}):
                lookups |= more
            ids = {(item.strings[int(call.group(1))], item.where(call.start()))
                   for item in files for name in lookups
                   for call in re.finditer(rf"(?<!fn )\b{name}\(\s*" + LIT, item.code)
                   if item.strings[int(call.group(1))].endswith(".desktop") and not item.in_test(call.start())}
            for desktop_id, source in sorted(ids):
                sources = desktop_exec_sources(desktop_id)
                if not sources:
                    findings[f"rust-launch:{desktop_id}"] = (
                        f"{source}: ningún fichero del airootfs ni heredoc instala /usr/share/applications/{desktop_id}")
                for origin, exec_value in sources:
                    # Como actions.rs: corta en " %" y tokeniza con comillas dobles.
                    argv = desktop_exec_argv(exec_value.split(" %")[0]) or [""]
                    if argv[0] not in allowed:
                        findings[f"rust-launch:{desktop_id}:{origin.split(':')[0]}"] = (
                            f"{origin}: Exec={exec_value} empieza por '{argv[0]}', que no está en ALLOWED_LAUNCHERS de "
                            f"{crate.name} ({', '.join(sorted(allowed))}): {source} no lo lanza y el botón solo dice "
                            "'Installer not available'")
        testlib.assert_findings(self, "rust-launch", findings)


class NiriWindowRules(unittest.TestCase):
    def test_window_rules_match_real_app_ids(self):
        ids = application_ids()
        self.assertTrue(ids, "no se encontró ningún application_id en los crates desplegados")
        findings = {}
        for path in niri_configs():
            for top in kdl_parse(testlib.read_text(path)):
                for node in top.children if top.name == "window-rule" else ():
                    pattern = node.props.get("app-id") if node.name in ("match", "exclude") else None
                    if not pattern or "churros" not in pattern.lower():
                        continue
                    try:
                        regex = re.compile(pattern)
                    except re.error:
                        continue  # sintaxis solo de la crate regex de Rust: aquí no se puede evaluar
                    # niri usa Regex::is_match: busca en cualquier parte del app id.
                    if not any(regex.search(app_id) for app_id in ids):
                        findings[f"rust-appid:{pattern}"] = (
                            f"{where(path, node.line)}: {node.name} app-id=\"{pattern}\" no casa con ningún application_id "
                            f"de las apps Rust ({', '.join(sorted(ids))}): la regla deja de aplicarse sin aviso")
        testlib.assert_findings(self, "rust-appid", findings)


class IgnoredTests(unittest.TestCase):
    def test_ignored_tests_have_a_runner(self):
        """Un #[ignore] solo corre si algún script o workflow pasa --include-ignored/--ignored."""
        if tomllib is None:
            self.skipTest("tomllib necesita Python >= 3.11")
        runners = []
        for path in testlib.repo_files():
            if path.is_symlink() or not path.is_file() or not any(path.is_relative_to(ROOT / d) for d in ("scripts", ".github")):
                continue
            text = testlib.read_text(path)
            if re.search(r"--include-ignored|--ignored\b", text):
                runners.append(set(re.findall(r"(?:-p|--package)[\"',\s=]+([\w-]+)", text)))  # vacío: todo el workspace
        findings = {}
        for crate in testlib.crates():
            for item in crate_files(crate):
                for match in re.finditer(r"#\[ignore\b", item.code):
                    fn = re.compile(r"[^{;]*?\bfn\s+(\w+)").match(item.code, match.end())
                    if not any(not packages or crate.name in packages for packages in runners):
                        findings[f"rust-ignored:{crate.name}::{fn.group(1) if fn else '?'}"] = (
                            f"{item.where(match.start())}: #[ignore] y ningún script de scripts/ ni workflow lo ejecuta "
                            "con --include-ignored: el test no corre nunca")
        testlib.assert_findings(self, "rust-ignored", findings)


if __name__ == "__main__":
    unittest.main()
