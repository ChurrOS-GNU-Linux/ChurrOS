"""Sintaxis de los ficheros de configuración que van en la ISO o en el instalador.

Cada fichero se lee con las reglas de quien lo consume, no con las de su
extensión: el config.jsonc de fastfetch se ejecuta en cada zsh (.zshrc), el de
waybar lo leen waybar y churros-settings, el XML de xfconf lo carga xfconfd,
config.kdl lo carga niri al iniciar sesión, theme.txt lo carga GRUB. Un error
de sintaxis en cualquiera de ellos pasa ./churros check y deja el escritorio,
el login o el menú de arranque sin su configuración.

Los ficheros se descubren por extensión y ubicación (archiso/, installer/,
branding/ y rust/<crate>/assets/), así que uno nuevo entra solo. Hay un
subTest por fichero y los hallazgos llevan id `<categoria>:<ruta>:<detalle>`
contra tests/known_issues.toml.

También comprueba referencias entre ficheros (imágenes y fuentes del tema de
GRUB, splash e INCLUDE de syslinux, placeholders de mkarchiso, rutas de
/usr/share/churros dentro de las configuraciones, @import de CSS) y que la
versión escrita a mano en la ISO coincide con VERSION.

No sustituye a `niri validate` ni a los validadores reales de cada programa,
que necesitan los paquetes de Arch (capa tests/container): aquí solo sintaxis.
"""
from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET

from tests import testlib

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = testlib.ROOT
rel = testlib.rel
SKEL_CONFIG = testlib.AIROOTFS / "etc/skel/.config"
PRODUCT_PREFIXES = ("archiso/", "installer/", "branding/")
RUST_ASSETS = re.compile(r"rust/[^/]+/assets/")


class Problem(Exception):
    """Error de sintaxis con el mensaje que verá quien rompió el fichero."""


# ------------------------------------------------------------------ utilidades

def product_files(*suffixes: str, names: tuple[str, ...] = ()) -> list[Path]:
    """Ficheros del producto con esa extensión (o ese nombre exacto)."""
    found = []
    for path in testlib.repo_files():
        name = rel(path)
        if not (name.startswith(PRODUCT_PREFIXES) or RUST_ASSETS.match(name)):
            continue
        if name.startswith("archiso/packages/") or path.is_symlink() or not path.is_file():
            continue
        if path.suffix in suffixes or path.name in names:
            found.append(path)
    return found


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def check_each(testcase: unittest.TestCase, category: str, paths: list[Path], check, required: bool = True) -> None:
    """Un subTest por fichero con el trinquete de tests/known_issues.toml.

    check(path) -> {detalle: mensaje}; el id es `<category>:<ruta>:<detalle>`.
    Igual que testlib.assert_findings, pero acotado a cada fichero para poder
    usar subTest. Un id conocido que ya no aparece (o de un fichero que ya no
    se comprueba) también falla: la lista solo puede acortarse. required:
    que no haya ningún fichero es un fallo (el descubrimiento se ha roto).
    """
    if required and not paths:
        testcase.fail(f"{category}: no se ha encontrado ningún fichero que comprobar")
    known = {key for key in testlib.known_issues() if key.startswith(category + ":")}
    checked = set()
    for path in paths:
        name = rel(path)
        checked.add(name)
        prefix = f"{category}:{name}:"
        with testcase.subTest(file=name):
            findings = {prefix + detail: message for detail, message in check(path).items()}
            lines = [f"  - {name}: {message}  [{key}]"
                     for key, message in sorted(findings.items()) if key not in known]
            fixed = sorted(key for key in known if key.startswith(prefix) and key not in findings)
            if fixed:
                lines.append("Ya no fallan; borra su entrada de tests/known_issues.toml:")
                lines.extend(f"  - {key}" for key in fixed)
            if lines:
                testcase.fail("\n".join(lines))
    stale = sorted(key for key in known if key.split(":", 2)[1] not in checked)
    if stale:
        testcase.fail("tests/known_issues.toml apunta a ficheros que ya no se comprueban:\n"
                      + "\n".join(f"  - {key}" for key in stale))


def single(detail: str, function, *args) -> dict[str, str]:
    """{detail: mensaje} si function(*args) lanza Problem; {} si no."""
    try:
        function(*args)
    except Problem as error:
        return {detail: str(error)}
    return {}


@lru_cache(maxsize=None)
def crate_assets() -> dict[str, Path]:
    return {crate.name: crate.directory / "assets" for crate in testlib.crates() if crate.deploy}


def shipped(abs_path: str) -> bool:
    """¿Estará `abs_path` en la ISO? Fichero del airootfs o generado por el build."""
    abs_path = abs_path.rstrip("/") or "/"
    target = testlib.airootfs(abs_path)
    if target.exists() or abs_path in testlib.generated_paths():
        return True
    # build.sh copia branding/grub-theme a /usr/share/churros/grub-theme y
    # build-rust.sh copia rust/<crate>/assets a /usr/share/churros/<crate>/assets.
    match = re.fullmatch(r"/usr/share/churros/grub-theme(?:/(.*))?", abs_path)
    if match:
        return (ROOT / "branding/grub-theme" / (match.group(1) or "")).exists()
    match = re.fullmatch(r"/usr/share/churros/([^/]+)/assets(?:/(.*))?", abs_path)
    if match and match.group(1) in crate_assets():
        return (crate_assets()[match.group(1)] / (match.group(2) or "")).exists()
    return False


def strings_in(value):
    """Todas las cadenas de un documento JSON/TOML ya cargado."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings_in(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings_in(item)


# ------------------------------------------------------------------- JSON/JSONC

# Cada consumidor acepta un dialecto distinto (descripción, comentarios, comas finales):
#  - fastfetch: src/fastfetch.c (parseJsoncFile) lee *.jsonc con
#    YYJSON_READ_ALLOW_COMMENTS | YYJSON_READ_ALLOW_TRAILING_COMMAS.
#  - waybar: include/util/json.hpp usa Json::CharReaderBuilder con los valores
#    por defecto de jsoncpp (allowComments y allowTrailingCommas a true).
#  - churros-settings lee ~/.config/waybar/config.jsonc (copia del skel) y el
#    de defaults (include_str! + restaurar) con rust/services/src/jsonc.rs,
#    que solo quita comentarios // y comas finales: un /* */ deja la página de
#    waybar de Ajustes sin configuración ("config.jsonc ilegible").
#  - *.json (paletas de Noctalia): JSON estricto.
NO_COMMENTS, LINE_COMMENTS, ALL_COMMENTS = "none", "line", "all"
SETTINGS_WAYBAR = (
    "archiso/airootfs/etc/skel/.config/waybar/",
    "archiso/airootfs/usr/share/churros/defaults/waybar/",
)


def json_dialect(name: str) -> tuple[str, str, bool]:
    parts = name.split("/")
    if name.endswith(".json"):
        return "JSON estricto", NO_COMMENTS, False
    if "fastfetch" in parts:
        return "fastfetch (yyjson)", ALL_COMMENTS, True
    if name.startswith(SETTINGS_WAYBAR):
        return "waybar + churros-settings (jsonc.rs)", LINE_COMMENTS, True
    if "waybar" in parts:
        return "waybar (jsoncpp)", ALL_COMMENTS, True
    return "JSONC sin consumidor conocido", ALL_COMMENTS, False


def strip_jsonc(text: str, comments: str, trailing_commas: bool, consumer: str) -> str:
    """Quita comentarios y comas finales fuera de cadenas.

    Lo quitado se cambia por espacios, así json.loads da la línea y columna
    reales. Primero los comentarios y luego las comas: `1, // x` + `}` es
    válido para yyjson, jsoncpp y jsonc.rs.
    """
    chars, i, n, in_string = list(text), 0, len(text), False
    while i < n:
        c = text[i]
        if in_string:
            if c == "\\":
                i += 2
                continue
            in_string = c != '"'
        elif c == '"':
            in_string = True
        elif comments != NO_COMMENTS and text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            chars[i:end] = " " * (end - i)
            i = end
            continue
        elif comments != NO_COMMENTS and text.startswith("/*", i):
            if comments == LINE_COMMENTS:
                raise Problem(f"comentario /* */ en la línea {line_of(text, i)}: {consumer} solo acepta //")
            end = text.find("*/", i + 2)
            if end < 0:
                raise Problem(f"comentario /* sin cerrar (línea {line_of(text, i)})")
            chars[i:end + 2] = [ch if ch == "\n" else " " for ch in text[i:end + 2]]
            i = end + 2
            continue
        i += 1
    if not trailing_commas:
        return "".join(chars)
    text, in_string = "".join(chars), False
    for i, c in enumerate(text):
        if in_string:
            in_string = not (c == '"' and not escaped(text, i))
        elif c == '"':
            in_string = True
        elif c == ",":
            rest = text[i + 1:].lstrip(" \t\r\n")
            if rest[:1] in ("}", "]") and rest:
                chars[i] = " "
    return "".join(chars)


def escaped(text: str, index: int) -> bool:
    """¿El carácter de `index` va precedido de un número impar de '\\'?"""
    count = 0
    while index - count - 1 >= 0 and text[index - count - 1] == "\\":
        count += 1
    return count % 2 == 1


def load_jsonc(path: Path):
    """Carga un .json/.jsonc con el dialecto de su consumidor (o lanza Problem)."""
    consumer, comments, trailing = json_dialect(rel(path))
    text = testlib.read_text(path)
    if consumer == "waybar (jsoncpp)":
        text = text.removeprefix("\ufeff")  # jsoncpp: skipBom = true
    cleaned = strip_jsonc(text, comments, trailing, consumer)

    def reject(constant):
        raise Problem(f"{constant} no es JSON")

    try:
        return json.loads(cleaned, parse_constant=reject)
    except json.JSONDecodeError as error:
        raise Problem(f"{error.msg} (línea {error.lineno}, columna {error.colno}; dialecto: {consumer})")


# ------------------------------------------------------------------------ TOML

# etc/greetd/config.toml no es TOML para su consumidor (greetd usa su parser
# `inish`) y además no llega a la ISO: build.sh la guarda en .bak, escribe la
# de la sesión Live y la restaura al salir. Se deja fuera. regreet.toml
# (serde + toml) y config.toml de Noctalia sí son TOML 1.0.
GREETD_CONFIG = "archiso/airootfs/etc/greetd/config.toml"


def load_toml(path: Path):
    if tomllib is None:
        raise unittest.SkipTest("tomllib necesita Python >= 3.11")
    try:
        return tomllib.loads(testlib.read_text(path))
    except tomllib.TOMLDecodeError as error:
        raise Problem(f"TOML inválido: {error}")


def config_files() -> list[Path]:
    """*.json, *.jsonc y *.toml que se cargan como datos (todos menos greetd)."""
    return [p for p in product_files(".json", ".jsonc", ".toml") if rel(p) != GREETD_CONFIG]


def load_config(path: Path):
    return load_toml(path) if path.suffix == ".toml" else load_jsonc(path)


# ------------------------------------------------------------------------- XML

# xfconfd/xfconf-backend-perchannel-xml.c y common/xfconf-gvaluefuncs.c: un
# fichero que no cumple esto se descarta entero y el canal (panel, atajos,
# escritorio) vuelve a los valores por defecto de XFCE.
XFCONF_INT_RANGES = {
    "int": (-2**31, 2**31 - 1), "uint": (0, 2**32 - 1), "char": (-128, 127),
    "uchar": (0, 255), "int16": (-2**15, 2**15 - 1), "uint16": (0, 2**16 - 1),
    "int64": None, "uint64": None,  # g_ascii_strtoll/strtoull sin comprobar rango
}
XFCONF_TYPES = {"empty", "string", "bool", "double", "array"} | set(XFCONF_INT_RANGES)


def c_integer(text: str) -> int | None:
    """strtol(text, &end, 0) que consume todo el texto, o None."""
    match = re.fullmatch(r"[ \t\n\r\f\v]*([+-]?)(0[xX][0-9a-fA-F]+|0[0-7]*|[1-9][0-9]*)", text)
    if not match:
        return None
    digits = match.group(2)
    if digits[:2].lower() == "0x":
        value = int(digits, 16)
    elif digits.startswith("0"):
        value = int(digits, 8)
    else:
        value = int(digits)
    return -value if match.group(1) == "-" else value


def xfconf_value_error(kind: str, value: str | None) -> str | None:
    """Motivo por el que _xfconf_gvalue_from_string rechazaría `value`."""
    if kind in ("empty", "string", "array"):
        return None
    if value is None:
        return f"type=\"{kind}\" sin atributo value"
    if kind == "bool":
        return None if value in ("true", "false") else f"bool solo admite true/false, no {value!r}"
    if kind == "double":
        try:
            float(value)
        except ValueError:
            try:
                float.fromhex(value)
            except ValueError:
                return f"{value!r} no es un double"
        return None
    number = c_integer(value)
    if number is None:
        return f"{value!r} no es un {kind}"
    bounds = XFCONF_INT_RANGES[kind]
    if bounds and not bounds[0] <= number <= bounds[1]:
        return f"{value!r} fuera del rango de {kind}"
    return None


def xfconf_problems(path: Path, root: ET.Element) -> list[str]:
    # Los ficheros del skel acaban en ~/.config: para xfconfd no son de
    # sistema y `locked`/`unlocked` se rechazan.
    system = "/etc/xdg/" in "/" + rel(path)
    lock_attrs = {"locked", "unlocked"} if system else set()
    problems = []
    if root.tag != "channel":
        return [f"la raíz es <{root.tag}>, xfconfd exige <channel>"]
    extra = set(root.attrib) - {"name", "version"} - lock_attrs
    if extra:
        problems.append(f"<channel> con atributos no admitidos: {sorted(extra)}")
    if not root.get("name") or not root.get("version"):
        problems.append("<channel> necesita name y version")
    elif root.get("version").split(".")[0] != "1":
        problems.append(f"version=\"{root.get('version')}\" incompatible (xfconfd exige 1.x)")
    elif root.get("name") != path.stem:
        # xfconfd guarda cada canal con name igual al fichero
        # (perchannel.c, flush): distinto es contenido copiado de otro canal.
        problems.append(f"<channel name=\"{root.get('name')}\"> en {path.name}: el nombre debe coincidir con el fichero")

    def walk(element: ET.Element, where: str, is_array: bool):
        for child in element:
            if child.tag == "property":
                extra = set(child.attrib) - {"name", "type", "value"} - lock_attrs
                name, kind = child.get("name"), child.get("type")
                label = f"{where}/{name}"
                if extra:
                    problems.append(f"{label}: atributos no admitidos {sorted(extra)}")
                if not name or not kind:
                    problems.append(f"{where}: <property> necesita name y type")
                    continue
                if kind not in XFCONF_TYPES:
                    problems.append(f"{label}: type=\"{kind}\" no existe en xfconf")
                    continue
                reason = xfconf_value_error(kind, child.get("value"))
                if reason:
                    problems.append(f"{label}: {reason}")
                walk(child, label, kind == "array")
            elif child.tag == "value" and is_array:
                kind = child.get("type")
                extra = set(child.attrib) - {"type", "value"}
                if extra:
                    problems.append(f"{where}: <value> con atributos no admitidos {sorted(extra)}")
                if kind not in XFCONF_TYPES - {"array", "empty"}:
                    problems.append(f"{where}: <value type=\"{kind}\"> no es un tipo de elemento de array")
                    continue
                reason = xfconf_value_error(kind, child.get("value"))
                if reason:
                    problems.append(f"{where}: {reason}")
                if len(child):
                    problems.append(f"{where}: <value> no admite elementos dentro")
            else:
                problems.append(f"{where}: <{child.tag}> no está permitido aquí (solo <property>, y <value> en arrays)")

    walk(root, "", False)
    return problems


# --------------------------------------------------------------------- .desktop

def desktop_problems(path: Path) -> list[str]:
    """Lo que hace fallar a GKeyFile o a la especificación Desktop Entry 1.5."""
    groups: list[str] = []
    entries: dict[str, dict[str, str]] = {}
    for number, raw in enumerate(testlib.read_text(path).splitlines(), 1):
        line = raw.lstrip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"\[([^\[\]]+)\]\s*", line)
        if match:
            groups.append(match.group(1))
            entries.setdefault(match.group(1), {})
            continue
        # g_key_file_is_key_name: sin '=', '[' ni ']' salvo un [locale] final,
        # y sin espacio al principio o al final.
        key = re.match(r"([^=\[\]]+?(?:\[[^\]=]*\])?)\s*=", line)
        if not key or key.group(1) != key.group(1).strip():
            return [f"línea {number}: no es grupo, clave=valor ni comentario ({line!r}); GKeyFile rechaza el fichero"]
        if not groups:
            return [f"línea {number}: clave antes del primer grupo; GKeyFile exige empezar por [Desktop Entry]"]
        entries[groups[-1]][key.group(1)] = line.split("=", 1)[1].strip()
    if not groups or groups[0] != "Desktop Entry":
        return ["el primer grupo debe ser [Desktop Entry]"]
    entry, problems = entries["Desktop Entry"], []
    for required in ("Type", "Name"):
        if not entry.get(required):
            problems.append(f"falta {required} en [Desktop Entry]")
    if entry.get("Type") == "Application" and not entry.get("Exec") and entry.get("DBusActivatable") != "true":
        problems.append("Type=Application sin Exec")
    if entry.get("Type") == "Link" and not entry.get("URL"):
        problems.append("Type=Link sin URL")
    return problems


# ------------------------------------------------------------------------- KDL

def kdl_check(text: str) -> None:
    """Llaves equilibradas, cadenas y comentarios cerrados (KDL v1 y v2).

    niri (knuffel) rechaza el fichero entero ante cualquiera de estos errores
    y arranca con la configuración por defecto. Tolera: //, /* */ anidados,
    /- (slashdash), "..." con escapes, r#"..."# (v1), #"..."# y las cadenas
    multilínea de triple comilla (v2).
    """
    i, n, opened = 0, len(text), []
    raw_start = re.compile(r'r(#*)"|(#+)"')
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            depth, j = 1, i + 2
            while depth and j < n:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
            if depth:
                raise Problem(f"comentario /* de la línea {line_of(text, i)} sin cerrar")
            i = j
            continue
        boundary = i == 0 or text[i - 1] in " \t\r\n=(){};[]<>,\\"
        match = raw_start.match(text, i) if boundary else None
        if match:
            hashes = match.group(1) if match.group(1) is not None else match.group(2)
            start = match.end()
            closing = '"' + hashes
            if hashes and text.startswith('""', start):  # v2: raw multilínea
                closing, start = '"""' + hashes, start + 2
            end = text.find(closing, start)
            if end < 0:
                raise Problem(f"cadena raw de la línea {line_of(text, i)} sin cerrar (falta {closing})")
            i = end + len(closing)
            continue
        if c == '"':
            closing = '"""' if text.startswith('"""', i) else '"'
            j = i + len(closing)
            while j < n and not text.startswith(closing, j):
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise Problem(f"cadena de la línea {line_of(text, i)} sin cerrar")
            i = j + len(closing)
            continue
        if c == "{":
            opened.append(i)
        elif c == "}":
            if not opened:
                raise Problem(f"'}}' de la línea {line_of(text, i)} no cierra ningún bloque")
            opened.pop()
        i += 1
    if opened:
        lines = ", ".join(str(line_of(text, index)) for index in opened)
        raise Problem(f"bloque(s) abierto(s) con '{{' sin '}}' de cierre (línea(s) {lines})")


# ------------------------------------------------------------------------- CSS

def css_check(text: str) -> None:
    """{} () [] equilibrados, cadenas y comentarios cerrados (GTK, Qt QSS).

    GTK (gtkcsstokenizer.c) y Qt descartan las reglas desde el error: con una
    llave sin cerrar se pierde el resto de la hoja; waybar no arranca si su
    style.css no carga.
    """
    pairs, i, n, opened = {"{": "}", "(": ")", "[": "]"}, 0, len(text), []
    while i < n:
        c = text[i]
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise Problem(f"comentario /* de la línea {line_of(text, i)} sin cerrar")
            i = end + 2
            continue
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\n":
                    raise Problem(f"cadena de la línea {line_of(text, i)} sin cerrar")
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise Problem(f"cadena de la línea {line_of(text, i)} sin cerrar")
            i = j + 1
            continue
        if c == "\\":
            i += 2
            continue
        if c in pairs:
            opened.append(i)
        elif c in ")]}":
            if not opened or pairs[text[opened[-1]]] != c:
                raise Problem(f"'{c}' de la línea {line_of(text, i)} no cierra nada (o cierra otro tipo de bloque)")
            opened.pop()
        i += 1
    if opened:
        index = opened[-1]
        raise Problem(f"'{text[index]}' de la línea {line_of(text, index)} sin cerrar")


CSS_IMPORT = re.compile(r"""@import\s+(?:url\(\s*)?["']?([^"')\s;]+)""")


# ------------------------------------------------------------------- tema GRUB

# grub-core/gfxmenu/theme_loader.c: theme_set_string() solo acepta estas
# propiedades globales; cualquier otra (p. ej. title-align) es un error y GRUB
# descarta el tema entero (menú de texto).
GRUB_GLOBALS = {
    "title-font", "message-font", "terminal-font", "title-color", "message-color",
    "message-bg-color", "desktop-image", "desktop-image-scale-method",
    "desktop-image-h-align", "desktop-image-v-align", "desktop-color",
    "terminal-box", "terminal-border", "terminal-left", "terminal-top",
    "terminal-width", "terminal-height", "title-text",
}
GRUB_ENUMS = {
    "desktop-image-scale-method": {"stretch", "crop", "padding", "fitwidth", "fitheight"},
    "desktop-image-h-align": {"left", "center", "right"},
    "desktop-image-v-align": {"top", "center", "bottom"},
}
GRUB_COMPONENTS = {"label", "image", "vbox", "hbox", "canvas", "progress_bar", "circular_progress", "boot_menu"}
GRUB_CONTAINERS = {"vbox", "hbox", "canvas"}
# grub-mkconfig (00_header) carga además unicode.pf2 de GRUB con loadfont.
GRUB_BUILTIN_FONTS = {"Unifont Regular 16"}
GRUB_IMAGE = re.compile(r".*\.(png|jpe?g|tga)", re.IGNORECASE)


class GrubTheme:
    """Port del lector de theme_loader.c: mismos tokens y mismos errores."""

    def __init__(self, text: str):
        self.text, self.pos = text, 0
        self.props: list[tuple[str | None, str, str, int]] = []  # (componente, clave, valor, línea)

    def peek(self) -> str:
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def fail(self, message: str):
        raise Problem(f"línea {line_of(self.text, self.pos)}: {message}")

    def skip_ws(self):
        while self.peek() and self.peek() in " \t\r\n\f":
            self.pos += 1

    def next_line(self):
        end = self.text.find("\n", self.pos)
        self.pos = len(self.text) if end < 0 else end + 1

    def identifier(self) -> str:
        self.skip_ws()
        start = self.pos
        while self.peek() and (self.peek().isascii() and self.peek().isalnum() or self.peek() in "_-"):
            self.pos += 1
        return self.text[start:self.pos]

    def expression(self) -> str:
        self.skip_ws()
        c = self.peek()
        if not c:
            self.fail("se esperaba un valor y se acabó el fichero")
        if c in '"(':
            closing = '"' if c == '"' else ")"
            end = self.text.find(closing, self.pos + 1)
            end = len(self.text) if end < 0 else end
            value = self.text[self.pos + 1:end] if c == '"' else self.text[self.pos:end + 1]
            self.pos = end + 1
            return value
        start = self.pos
        while self.peek() and self.peek() not in " \t\r\n\f":
            self.pos += 1
        return self.text[start:self.pos]

    def parse(self):
        while self.pos < len(self.text):
            if self.peek() == "#":
                self.next_line()
                continue
            self.skip_ws()
            if self.peek() == "+":
                self.pos += 1
                self.read_object()
            else:
                self.read_property()
        return self.props

    def read_property(self):
        line = line_of(self.text, self.pos)
        name = self.identifier()
        if not name:  # read_property: sin identificador GRUB salta la línea
            self.next_line()
            return
        self.skip_ws()
        if self.peek() != ":":
            self.fail(f"falta ':' tras la propiedad '{name}'")
        self.pos += 1
        self.skip_ws()
        if self.peek() != '"':
            self.fail(f"el valor de '{name}' va sin comillas; GRUB exige \"...\" en las propiedades globales")
        self.props.append((None, name, self.expression(), line))

    def read_object(self):
        kind = self.identifier()
        if not kind:
            return
        if kind not in GRUB_COMPONENTS:
            self.fail(f"tipo de objeto desconocido '+ {kind}'")
        self.skip_ws()
        if self.peek() != "{":
            self.fail(f"falta '{{' tras '+ {kind}'")
        self.pos += 1
        while self.pos < len(self.text):
            self.skip_ws()
            c = self.peek()
            if c == "}":
                self.pos += 1
                return
            if c == "#":
                self.next_line()
                continue
            if c == "+":
                self.pos += 1
                if kind not in GRUB_CONTAINERS:
                    self.fail(f"'+' dentro de '{kind}', que no es un contenedor (¿falta un '}}'?)")
                self.read_object()
                continue
            line = line_of(self.text, self.pos)
            name = self.identifier()
            if not name:
                self.fail(f"se esperaba una propiedad o '}}' dentro de '+ {kind}'")
            self.skip_ws()
            if self.peek() != "=":
                self.fail(f"falta '=' tras '{name}' en '+ {kind}'")
            self.pos += 1
            self.props.append((kind, name, self.expression(), line))


def pf2_name(path: Path) -> str | None:
    """Campo NAME de una fuente PFF2 (chunks: 4 bytes de nombre + longitud BE)."""
    data, pos = path.read_bytes(), 0
    if data[:12] != b"FILE\x00\x00\x00\x04PFF2":
        return None
    while pos + 8 <= len(data):
        tag, length = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "big")
        if tag == b"NAME":
            return data[pos + 8:pos + 8 + length].split(b"\0", 1)[0].decode("utf-8", "replace")
        if tag == b"DATA":
            return None
        pos += 8 + length
    return None


@lru_cache(maxsize=None)
def grub_theme_rebuilt() -> dict[Path, frozenset[str]]:
    """Ficheros que scripts/build-grub-theme.sh regenera con `cp` en cada build.

    build.sh lo ejecuta antes de copiar el tema: si falta background.png lo
    vuelve a copiar de los wallpapers, así que su ausencia no es un fallo
    mientras el origen exista. (Las .pf2 dependen de grub-mkfont y de
    ttf-dejavu, que el contenedor no trae: esas sí deben estar en git.)
    """
    script = ROOT / "scripts/build-grub-theme.sh"
    if not script.exists():
        return {}
    text = testlib.read_text(script)
    variables = {name: (ROOT / "scripts" / value).resolve()
                 for name, value in re.findall(r'^(\w+)="\$SCRIPT_DIR/([^"$]+)"', text, re.MULTILINE)}
    theme_dir = variables.get("THEME_DIR")
    if theme_dir is None:
        return {}
    made = set()
    for var, sub, target in re.findall(r'\bcp\s+"\$(\w+)((?:/[^"]*)?)"\s+"\$THEME_DIR/([^"/]+)"', text):
        source = variables.get(var)
        if source is not None and Path(str(source) + sub).exists():
            made.add(target)
    return {theme_dir: frozenset(made)}


# --------------------------------------------------------------------- versión

def distro_version() -> str:
    return testlib.read_text(ROOT / "VERSION").strip()


def version_ok(found: str, version: str) -> bool:
    """`found` es VERSION o un prefijo X.Y de ella (ChurrOS 1.3 vale para 1.3.1)."""
    parts, wanted = found.split("."), version.split(".")
    return found == version or (len(parts) >= 2 and wanted[:len(parts)] == parts)


def semver(version: str) -> str:
    parts = version.split(".")
    return ".".join(parts + ["0"] * (3 - len(parts))) if len(parts) <= 3 else version


CHURROS_VERSION = re.compile(r"\bChurrOS\s+v?(\d+(?:\.\d+)+)\b")


# ----------------------------------------------------------------------- tests

class JsonConfigs(unittest.TestCase):
    """*.json y *.jsonc con el dialecto de quien los lee."""

    def test_json_and_jsonc_parse(self):
        check_each(self, "syntax-json", product_files(".json", ".jsonc"),
                   lambda path: single("parse", load_jsonc, path))


class TomlConfigs(unittest.TestCase):

    def test_toml_parse(self):
        """regreet.toml, config.toml de Noctalia y cualquier *.toml de la ISO."""
        paths = [p for p in config_files() if p.suffix == ".toml"]
        check_each(self, "syntax-toml", paths, lambda path: single("parse", load_toml, path))


class XmlConfigs(unittest.TestCase):

    def test_xml_well_formed(self):
        """*.xml (xfconf, labwc) y *.svg (iconos de apps, Calamares, Ajustes)."""
        def check(path):
            try:
                ET.parse(path)
            except ET.ParseError as error:
                return {"parse": f"XML mal formado: {error}"}
            return {}
        check_each(self, "syntax-xml", product_files(".xml", ".svg"), check)

    def test_xfconf_channels(self):
        """Lo que xfconfd exige a cada xfce-perchannel-xml/<canal>.xml."""
        paths = [p for p in product_files(".xml") if p.parent.name == "xfce-perchannel-xml"]

        def check(path):
            try:
                root = ET.parse(path).getroot()
            except ET.ParseError:
                return {}  # lo informa test_xml_well_formed
            return {f"schema:{index}": message
                    for index, message in enumerate(xfconf_problems(path, root))}
        check_each(self, "xfconf", paths, check)


class DesktopEntries(unittest.TestCase):

    def test_desktop_entry_structure(self):
        """Grupos y claves que GKeyFile y la especificación exigen."""
        check_each(self, "syntax-desktop", product_files(".desktop"),
                   lambda path: {f"spec:{i}": m for i, m in enumerate(desktop_problems(path))})

    def test_desktop_file_validate(self):
        """desktop-file-validate: falla con errores, no con warnings ni hints."""
        tool = testlib.require_tool(self, "desktop-file-validate")

        def check(path):
            result = testlib.run([tool, str(path)])
            errors = [line.split(": error: ", 1)[1] for line in result.stdout.splitlines() if ": error: " in line]
            if result.returncode != 0 and not errors:
                errors = [result.stdout.strip() or f"salió con {result.returncode}"]
            return {"validate": "; ".join(errors)} if errors else {}
        check_each(self, "desktop-validate", product_files(".desktop"), check)


class NiriKdl(unittest.TestCase):

    def test_kdl_syntax(self):
        """config.kdl de niri (skel y defaults): llaves, cadenas y comentarios."""
        check_each(self, "syntax-kdl", product_files(".kdl"),
                   lambda path: single("parse", kdl_check, testlib.read_text(path)))


class Stylesheets(unittest.TestCase):

    def test_css_balanced(self):
        """GTK CSS (waybar, regreet, wlogout, apps Rust) y QSS de Calamares."""
        check_each(self, "syntax-css", product_files(".css", ".qss"),
                   lambda path: single("parse", css_check, testlib.read_text(path)))

    def test_css_relative_imports_exist(self):
        """@import relativo: el fichero existe junto a la hoja (como en ~/.config)."""
        def check(path):
            findings = {}
            code = re.sub(r"/\*.*?\*/", "", testlib.read_text(path), flags=re.DOTALL)
            for target in CSS_IMPORT.findall(code):
                if re.match(r"[a-z]+:", target):
                    continue
                if target.startswith("/") and not target.startswith("/usr/share/churros/"):
                    continue  # de un paquete: no se puede comprobar aquí
                exists = shipped(target) if target.startswith("/") else (path.parent / target).exists()
                if not exists:
                    findings[f"import:{target}"] = f"@import \"{target}\" no existe"
            return findings
        check_each(self, "css-import", product_files(".css", ".qss"), check)


class GrubThemes(unittest.TestCase):

    def themes(self) -> list[Path]:
        return [p for p in product_files(names=("theme.txt",)) if "grub" in rel(p)]

    def test_theme_syntax_and_assets(self):
        """theme.txt: sintaxis de theme_loader.c, propiedades, imágenes y fuentes."""
        def check(path):
            text = testlib.read_text(path)
            try:
                props = GrubTheme(text).parse()
            except Problem as error:
                return {"parse": str(error)}
            theme_dir, findings = path.parent, {}
            rebuilt = grub_theme_rebuilt().get(theme_dir.resolve(), frozenset())
            fonts = {}
            for font in sorted([*theme_dir.glob("*.pf2"), *theme_dir.glob("f/*.pf2")]):
                name = pf2_name(font)
                if name is None:
                    findings[f"pf2:{font.name}"] = f"{font.name} no es una fuente PFF2 válida (sin NAME)"
                else:
                    fonts[name] = font.name
                if re.search(r"\s", font.name):
                    findings[f"pf2-space:{font.name}"] = (f"{font.name}: grub-mkconfig escribe `loadfont <ruta>` "
                                                          "sin comillas y GRUB corta la ruta en el espacio")
            for component, key, value, line in props:
                where = f"línea {line}: {key}" if component is None else f"línea {line}: {component}.{key}"
                if component is None and key not in GRUB_GLOBALS:
                    findings[f"property:{key}"] = f"{where}: propiedad global desconocida; GRUB descarta el tema"
                if component is None and key in GRUB_ENUMS and value not in GRUB_ENUMS[key]:
                    findings[f"value:{key}"] = f"{where} = {value!r} no es uno de {sorted(GRUB_ENUMS[key])}"
                if re.search(r"(^|[-_])font$", key) and value not in fonts and value not in GRUB_BUILTIN_FONTS:
                    findings[f"font:{value}"] = (f"{where} = {value!r}: ninguna .pf2 del tema se llama así "
                                                 f"(NAME disponibles: {sorted(fonts)}); GRUB usaría otra fuente")
                if key == "desktop-image" or GRUB_IMAGE.fullmatch(value):
                    if "*" in value:
                        ok = any(theme_dir.glob(value))
                    else:
                        ok = (theme_dir / value).is_file() or value in rebuilt
                    if not ok:
                        findings[f"image:{value}"] = f"{where} = {value!r} no existe en {rel(theme_dir)}"
            return findings
        check_each(self, "grub-theme", self.themes(), check)


# mkarchiso (_make_bootmode_bios.syslinux y _make_common_bootmode_grub_cfg)
# sustituye estos placeholders; otro %ALGO% llega tal cual al menú de arranque
# (p. ej. archisobasedir=%INSTAL_DIR% y la Live no encuentra airootfs.sfs).
SYSLINUX_PLACEHOLDERS = {"ARCHISO_LABEL", "ARCHISO_UUID", "INSTALL_DIR", "KERNEL_PARAMS", "ARCH"}
GRUB_PLACEHOLDERS = SYSLINUX_PLACEHOLDERS | {"ARCHISO_SEARCH_FILENAME"}


class BootConfigs(unittest.TestCase):

    def boot_files(self) -> list[tuple[Path, set[str]]]:
        files = [(p, GRUB_PLACEHOLDERS) for p in sorted((ROOT / "archiso/grub").glob("*.cfg"))]
        files += [(p, SYSLINUX_PLACEHOLDERS) for p in sorted((ROOT / "archiso/syslinux").glob("*.cfg"))]
        # efiboot solo lo lee mkarchiso en los bootmodes de systemd-boot, y
        # solo sustituye en entries/*.conf (loader.conf se copia tal cual).
        if any("systemd-boot" in mode for arch in testlib.ARCHES for mode in testlib.profile(arch)["bootmodes"]):
            entries = sorted((ROOT / "archiso/efiboot/loader/entries").glob("*.conf"))
            files += [(p, SYSLINUX_PLACEHOLDERS) for p in entries]
            files += [(p, set()) for p in (ROOT / "archiso/efiboot/loader").glob("loader.conf")]
        return files

    def test_mkarchiso_placeholders(self):
        allowed = dict(self.boot_files())

        def check(path):
            return {f"placeholder:{name}": f"%{name}% no lo sustituye mkarchiso en {path.name}"
                    for name in sorted(set(re.findall(r"%([A-Za-z_]+)%", testlib.read_text(path))) - allowed[path])}
        check_each(self, "boot-cfg", list(allowed), check)

    def test_live_cmdlines_find_the_medium(self):
        """Cada entrada que arranca la Live dice dónde está el medio.

        El initramfs de archiso necesita archisobasedir= y una forma de
        encontrar el medio (archisosearchuuid=, archisolabel=, archisodevice=,
        img_dev= desde loopback.cfg o un servidor PXE). Sin ella la entrada
        se queda en "Waiting for device" y acaba en la shell de emergencia;
        en un PR solo se arranca por UEFI, así que BIOS no lo vería nadie.
        """
        medium = re.compile(r"\b(?:archisosearchuuid=%ARCHISO_UUID%|archisolabel=\S|archisodevice=\S|img_dev=\S"
                            r"|archiso_(?:nbd|nfs|http)_srv=\S)")
        files = sorted((ROOT / "archiso/grub").glob("*.cfg")) + sorted((ROOT / "archiso/syslinux").glob("*.cfg"))
        files += sorted((ROOT / "archiso/efiboot/loader/entries").glob("*.conf"))

        def entries(path):
            """(entrada, línea de comandos o None) de cada entrada que arranca la Live.

            Por bloque (LABEL de syslinux, menuentry de GRUB, fichero de
            systemd-boot): una entrada que ha perdido su APPEND u options
            arranca el kernel sin parámetros y también es un fallo.
            """
            text = testlib.read_text(path)
            live = re.compile(r"^\s*(?:linux|LINUX|KERNEL|kernel)\s+(?:::)?/%INSTALL_DIR%/")
            if path.suffix == ".conf":
                if re.search(r"^\s*linux\s+/%INSTALL_DIR%/", text, re.M):
                    options = re.findall(r"^\s*options\s+(.*)$", text, re.M)
                    yield path.stem, options[0] if options else None
                return
            if path.parent.name == "syslinux":
                for block in re.split(r"(?m)^(?=\s*LABEL\s)", text):
                    label = re.match(r"\s*LABEL\s+(\S+)", block)
                    if label and any(live.match(line) for line in block.splitlines()):
                        append = re.findall(r"^\s*APPEND\s+(.*)$", block, re.M | re.I)
                        yield label.group(1), append[0] if append else None
                return
            for match in re.finditer(r"^\s*menuentry\s+([\"'])(.*?)\1[^\n]*\{\n(.*?)^\s*\}", text, re.M | re.S):
                body = match.group(3)
                if "%INSTALL_DIR%" not in body:
                    continue  # memtest, shell EFI...
                linux = re.search(r"^\s*linux\s+/%INSTALL_DIR%/\S+\s*(.*)$", body, re.M)
                yield match.group(2), linux.group(1) if linux else None

        def check(path):
            findings = {}
            for name, line in entries(path):
                if line is None:
                    findings[f"no-cmdline:{name}"] = (f"la entrada {name!r} arranca el kernel de la Live sin "
                                                      "línea de comandos (APPEND/options/linux)")
                    continue
                if "archisobasedir=%INSTALL_DIR%" not in line.split():
                    findings[f"basedir:{name}"] = f"la entrada {name!r} no lleva archisobasedir=%INSTALL_DIR%: {line}"
                if not medium.search(line):
                    findings[f"medium:{name}"] = (f"la entrada {name!r} no sabe encontrar el medio "
                                                  f"(archisosearchuuid=%ARCHISO_UUID%...): {line}")
            return findings
        check_each(self, "boot-cmdline", files, check)
        found = sum(1 for path in files for _ in entries(path))
        self.assertGreaterEqual(found, 8, f"solo {found} líneas de arranque de la Live: ¿cambió el formato de los cfg?")

    def test_syslinux_references(self):
        """INCLUDE/CONFIG/MENU BACKGROUND apuntan a ficheros que mkarchiso copia.

        mkarchiso solo copia a /boot/syslinux los *.cfg del perfil y splash.png
        (más los .c32 del paquete syslinux, que no se comprueban aquí).
        """
        profile_dir = ROOT / "archiso/syslinux"
        copied = {p.name for p in profile_dir.glob("*.cfg")} | ({"splash.png"} & {p.name for p in profile_dir.iterdir()})

        def check(path):
            findings = {}
            for number, raw in enumerate(testlib.read_text(path).splitlines(), 1):
                match = re.match(r"\s*(INCLUDE|CONFIG|MENU\s+INCLUDE|MENU\s+BACKGROUND)\s+(\S+)", raw, re.IGNORECASE)
                if not match:
                    continue
                target = match.group(2)
                name = target[len("/boot/syslinux/"):] if target.startswith("/boot/syslinux/") else target
                if "/" in name or name.startswith(("::", "%")):
                    continue
                if name not in copied:
                    directive = " ".join(match.group(1).upper().split())
                    findings[f"ref:{name}"] = (f"línea {number}: {directive} {target}: mkarchiso no lo copia a "
                                               "/boot/syslinux (solo *.cfg y splash.png de archiso/syslinux)")
            return findings
        check_each(self, "boot-cfg-ref", sorted(profile_dir.glob("*.cfg")), check)


class PlymouthThemes(unittest.TestCase):

    # src/plugins/splash/meson.build: ModuleName carga <plugin_dir>/<ModuleName>.so
    # (ply-boot-splash.c); otro nombre deja plymouthd sin splash.
    SPLASH_PLUGINS = {"console-viewer", "details", "fade-throbber", "script", "space-flares", "text", "tribar", "two-step"}

    @staticmethod
    def key_file(text: str) -> dict[str, dict[str, str]]:
        """Como ply-key-file.c: la primera línea que no es grupo, `clave = valor`
        ni comentario corta la lectura y lo que sigue se ignora sin error."""
        groups: dict[str, dict[str, str]] = {}
        current = None
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            group = re.fullmatch(r"\[\s*([^\]]+)\]", line)
            entry = re.fullmatch(r"([^=\s]+)\s*=\s*(\S.*)", line)
            if group:
                current = groups.setdefault(group.group(1), {})
            elif entry and current is not None:
                current[entry.group(1)] = entry.group(2).strip()
            else:
                break
        return groups

    def test_theme_files(self):
        def check(path):
            groups = self.key_file(testlib.read_text(path))
            module = groups.get("Plymouth Theme", {}).get("ModuleName")
            if not module:
                return {"module": "plymouth no lee [Plymouth Theme] ModuleName (falta, o una línea "
                                  "inválida anterior corta la lectura del fichero)"}
            findings = {}
            if module not in self.SPLASH_PLUGINS:
                findings["module"] = f"ModuleName={module} no es un plugin de plymouth ({sorted(self.SPLASH_PLUGINS)})"
            if module == "script" and not groups.get("script", {}).get("ScriptFile"):
                findings["script"] = "ModuleName=script sin [script] ScriptFile"
            for group, keys in groups.items():
                for key in ("ImageDir", "ScriptFile"):
                    value = keys.get(key)
                    if value and value.startswith("/") and not shipped(value):
                        findings[f"path:{group}.{key}"] = f"[{group}] {key}={value} no existe en la ISO"
            return findings
        # required=False: shellprocess-cleanup.conf vuelve a escribir el tema al instalar.
        check_each(self, "plymouth", product_files(".plymouth"), check, required=False)


class ConfigReferences(unittest.TestCase):

    def test_paths_inside_configs_exist(self):
        """Rutas que una configuración da por existentes.

        /usr/share/churros es de ChurrOS: todo lo que hay ahí lo pone el
        airootfs o el build (fondo de regreet, wallpapers de Noctalia...). El
        logo de fastfetch (~/.config/...) sale del skel.
        """
        def check(path):
            try:
                data = load_config(path)
            except Problem:
                return {}  # lo informa el test de sintaxis
            findings = {}
            for value in strings_in(data):
                if re.fullmatch(r"/usr/share/churros/\S*", value) and not shipped(value):
                    findings[f"path:{value}"] = f"{value} no existe en la ISO"
            logo = data.get("logo") if isinstance(data, dict) and "fastfetch" in path.parts else None
            logo = logo.get("source") if isinstance(logo, dict) else None
            if isinstance(logo, str) and logo.startswith("~/.config/") and not (SKEL_CONFIG / logo[10:]).exists():
                findings[f"path:{logo}"] = f"logo.source={logo} no está en etc/skel/.config: fastfetch pierde el logo"
            return findings
        check_each(self, "config-ref", config_files(), check)


class DistroVersion(unittest.TestCase):
    """La versión escrita a mano en la ISO, el instalador y los crates == VERSION.

    os-release se sella en el build (stamp-os-release.sh) y las apps Rust leen
    VERSION al compilar: eso ya lo vigila check.sh. Esto cubre el resto:
    /etc/churros-version (Ajustes y churros-update-utils lo comparan con el
    manifiesto de actualizaciones), el banner de fastfetch y cualquier
    "ChurrOS X.Y" en una configuración, branding.desc de Calamares y la
    versión de los crates (cada release las sube juntas).
    """

    def test_hardcoded_versions_match(self):
        version = distro_version()
        self.assertRegex(version, r"^\d+(\.\d+)*$", "VERSION debe ser numérico con puntos")
        configs = config_files()
        branding = product_files(names=("branding.desc",))
        cargo = sorted((ROOT / "rust").glob("*/Cargo.toml")) + [ROOT / "rust/Cargo.toml"]
        version_file = testlib.AIROOTFS / "etc/churros-version"

        def check(path):
            text, findings = testlib.read_text(path), {}
            if path == version_file:
                if text.strip() != version:
                    findings["churros-version"] = f"contiene {text.strip()!r} y VERSION es {version}"
            elif path in branding:
                for key, raw in re.findall(r"^\s+(version|shortVersion|versionedName|shortVersionedName)\s*:\s*(.+?)\s*$",
                                           text, re.MULTILINE):
                    value = raw.strip("\"'")
                    for found in re.findall(r"\d+(?:\.\d+)*", value):
                        good = version_ok(found, version) if key.startswith("short") else found == version
                        if not good:
                            findings[f"branding:{key}"] = f"strings.{key}: {value} y VERSION es {version}"
            elif path in cargo:
                data = load_toml(path)
                for table in (data.get("workspace", {}).get("package", {}), data.get("package", {})):
                    found = table.get("version")
                    if isinstance(found, str) and found != semver(version):
                        findings["cargo"] = f"version = \"{found}\" y VERSION es {version} (se espera {semver(version)})"
            else:
                try:
                    data = load_config(path)
                except Problem:
                    return {}
                for value in strings_in(data):
                    for found in CHURROS_VERSION.findall(value):
                        if not version_ok(found, version):
                            findings[f"banner:{found}"] = f"\"{value.strip()}\" y VERSION es {version}"
            return findings
        check_each(self, "version", [version_file, *branding, *cargo, *configs], check)


if __name__ == "__main__":
    unittest.main()
