"""Todo lo que el sistema ejecuta existe en la edición que lo ejecuta.

Recorre cada sitio de la configuración que lanza un programa y lo resuelve
contra la lista de paquetes de cada edición donde ese sitio está vivo
(testlib.EDITIONS), sin heurísticas de subcadena:

- niri (config.kdl de skel y de defaults): spawn, spawn-sh, spawn-at-startup
  y spawn-sh-at-startup, con comentarios, /- y cadenas raw de KDL. Solo en
  las ediciones con escritorio niri.
- .desktop: usr/share/applications (y el calamares.desktop que escribe
  customize_airootfs.sh), ~/.config/autostart (solo donde un escritorio lo
  procesa, filtrado por OnlyShowIn/NotShowIn) y los lanzadores del panel XFCE.
- Atajos de XFCE (xfconf), acciones Execute de labwc, waybar (on-click*,
  on-scroll*, exec de los módulos que la barra usa), wlogout, la acción
  "command" del menú de sesión de Noctalia, launch-prefix de fuzzel.
- greetd: SESSION_CMD y el config.toml que genera scripts/cli/build.sh, la
  tabla de edition-session.sh del sistema instalado, los [commands] de
  regreet.toml, el `exec` final de cada wrapper de sesión y el ejecutable
  de displaymanager de Calamares.
- systemd (Exec*= de etc/systemd y de las unidades de usuario de skel, más
  las unidades que arranca `systemctl start`), hooks de pacman (Exec, y el
  script de `sh -c`), comandos de Calamares (shellprocess, restartNowCommand,
  shell de users.conf) y las shells de login (etc/passwd, users.sh).
- Rust: Command::new("x") y los helpers que envuelven Command::new(args[0])
  (run, spawn, run_checked...), detectados leyendo el código.

Además: una ruta del airootfs que se ejecuta necesita modo ejecutable en
file_permissions de profiledef.sh (mkarchiso copia el airootfs sin modos), y
un binario Rust que recibe argumentos tiene que aceptarlos.

Un comando cuyo binario no se llama como su paquete se declara en
tests/command_providers.toml.

Uso: python3 -m unittest tests.static.test_references -v
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
from pathlib import Path
import re
import shlex
import unittest
import xml.etree.ElementTree as ET

from tests import testlib

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None

ROOT = testlib.ROOT
AIROOTFS = testlib.AIROOTFS
EDITIONS = testlib.EDITIONS
DESKTOP_EDITIONS = tuple(item for item in EDITIONS if item.desktop)
NIRI = tuple(testlib.editions_with_desktop("niri"))
XFCE = tuple(testlib.editions_with_desktop("xfce"))
LABWC = tuple(testlib.editions_with_desktop("labwc"))
INSTALLER = tuple(item for item in EDITIONS if item.installer)

# Escritorios que procesan ~/.config/autostart y el valor de
# XDG_CURRENT_DESKTOP con el que comparan OnlyShowIn/NotShowIn.
# xfce4-session sí. niri no: el Live lo arranca greetd como `niri` y el
# instalado churros-niri-session hace `exec niri` sin --session, así que
# nunca se activa xdg-desktop-autostart.target (por eso config.kdl comprueba
# churros-tour.desktop a mano). labwc tampoco: solo lee su script autostart.
AUTOSTART_DESKTOPS = {"xfce": "XFCE"}

# Comandos que el código Rust solo lanza en la rama de un escritorio (o cuyo
# fallo descarta a propósito fuera de él). Los demás se exigen en las
# ediciones niri, el escritorio para el que están hechas las apps.
#   None: rama de un compositor que ChurrOS no trae; no se resuelve.
RUST_DESKTOP_ONLY = {
    # services/src/power.rs: lock() y logout() solo si XDG_CURRENT_DESKTOP
    # contiene "xfce".
    "xflock4": "xfce",
    "xfce4-session-logout": "xfce",
    # preferences/src/pages/{display,keyboard,input,appearance}.rs: botones
    # que solo se crean dentro de `if is_xfce`.
    "xfce4-display-settings": "xfce",
    "xfce4-keyboard-settings": "xfce",
    "xfce4-mouse-settings": "xfce",
    "xfce4-settings-manager": "xfce",
    # preferences/src/services/{theme,cursor,fonts,icons}.rs: sincroniza
    # xsettings. theme.rs lo condiciona a XFCE; los demás lo lanzan siempre
    # con `let _ = ...output()`, que en niri es un no-op deliberado.
    "xfconf-query": "xfce",
    # services/src/power.rs y preferences/src/services/display.rs: ramas de
    # Hyprland y Sway (XDG_CURRENT_DESKTOP), que ChurrOS no distribuye.
    "hyprctl": None,
    "swaymsg": None,
}

SHELLS = {"sh", "bash", "dash", "zsh"}


@dataclass(frozen=True)
class Ref:
    """Un programa (o una unidad) que una fuente ejecuta.

    optional: el consumidor tolera que falte (prefijo '-' de systemd o de
    Calamares, `command -v`/`[ -x ]` antes del exec). Entonces basta con que
    exista en alguna de sus ediciones: así se cazan las erratas.
    """
    source: str
    command: str
    editions: tuple
    where: str
    optional: bool = False
    args: tuple = ()
    kind: str = "command"  # 'command' | 'unit'


def rel(path: Path) -> str:
    return testlib.rel(path)


def read(path: Path) -> str:
    return testlib.read_text(path)


def resolves(command: str, item) -> bool:
    return testlib.resolve_command(command, item).ok


# ------------------------------------------------------------------ shell

# Envoltorios que ejecutan el resto de la línea como otro programa; el valor
# es el conjunto de opciones que consumen el argumento siguiente.
WRAPPERS = {
    "env": {"-u", "--unset", "-C", "--chdir"},
    "sudo": {"-u", "--user", "-g", "--group", "-C", "-D", "-h", "-p", "-r", "-t", "-U"},
    "pkexec": {"--user"},
    "setsid": set(),
    "nohup": set(),
    "nice": {"-n", "--adjustment"},
    "ionice": {"-c", "-n", "-p", "-P", "-u"},
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "runuser": {"-u", "-g", "-G", "--user", "--group", "--supp-group", "-s", "--shell"},
    "doas": {"-u", "-C"},
    "systemd-cat": {"-t", "--identifier", "-p", "--priority", "--stderr-priority"},
    "dbus-run-session": {"--config-file", "--dbus-daemon"},
    # cage [-dhmrsv] [--] aplicación
    "cage": {"-m"},
}
# Palabras de shell que preceden al comando sin ser el comando.
SHELL_PREFIXES = {"exec", "time", "builtin", "!", "if", "then", "else", "elif", "do", "while", "until", "{"}
SHELL_ENDS = {"fi", "done", "esac", "}", "]]", "for", "case", "function", "in"}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*")


def command_words(line: str) -> list[list[str]]:
    """argv de cada comando simple de una línea de shell.

    Amplía testlib.shell_commands: conserva los argumentos, descarta las
    redirecciones (`2>&1`, `>&2` no son comandos), no confunde `command -v X`
    con ejecutar X y devuelve tanto el envoltorio (env, cage, setsid...) como
    el programa que envuelve. Un comando con `$` o una ruta relativa no se
    puede resolver y se omite.
    """
    try:
        lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        tokens = line.split()
    segments, current, index = [], [], 0
    while index < len(tokens):
        token = tokens[index]
        if token and set(token) <= set(";&|()"):
            segments.append(current)
            current = []
        elif token and set(token) & set("<>"):
            if current and current[-1].isdigit():
                current.pop()  # el '2' de '2>/dev/null'
            index += 1  # el destino de la redirección
        else:
            current.append(token)
        index += 1
    segments.append(current)

    found = []
    for words in segments:
        index = 0
        while index < len(words):
            word = words[index]
            if ASSIGNMENT.fullmatch(word) or word in SHELL_PREFIXES:
                index += 1
                continue
            if word == "command":
                if index + 1 < len(words) and words[index + 1] in ("-v", "-V"):
                    break  # comprueba, no ejecuta
                index += 1
                continue
            if word in SHELL_ENDS or "$" in word or "`" in word or word.startswith(("~", "-")):
                break
            if "/" in word and not word.startswith("/"):
                break
            found.append(words[index:])
            wrapped = wrapped_command(words, index)
            if wrapped is None:
                break
            index = wrapped
    return found


def wrapped_command(words: list[str], index: int) -> int | None:
    """Índice del programa que ejecuta el envoltorio words[index], o None."""
    name = Path(words[index]).name
    if name not in WRAPPERS:
        return None
    takes_value, position = WRAPPERS[name], index + 1
    while position < len(words):
        word = words[position]
        if word == "--":
            position += 1
            break
        if word in takes_value:
            position += 2
        elif word.startswith("-") or (name == "env" and ASSIGNMENT.fullmatch(word)):
            position += 1
        else:
            break
    if name == "timeout" and position < len(words):
        position += 1  # la duración
    return position if position < len(words) else None


def shell_refs(line: str, source: str, editions, where: str, optional: bool = False) -> list[Ref]:
    return [Ref(source, argv[0], tuple(editions), where, optional, tuple(argv[1:]))
            for argv in command_words(line)]


def guarded_commands(text: str) -> set[str]:
    """Programas cuya existencia comprueba el propio script antes de usarlos."""
    found = set()
    for pattern in (r"command\s+-v\s+(?:--\s+)?[\"']?([^\s\"'>;|&)]+)",
                    r"\bwhich\s+[\"']?([^\s\"'>;|&)]+)",
                    r"\[\[?\s+-x\s+[\"']?([^\s\"'\]]+)",
                    r"\btest\s+-x\s+[\"']?([^\s\"']+)"):
        for match in re.finditer(pattern, text):
            found.add(match.group(1))
    return found | {Path(name).name for name in found}


# -------------------------------------------------------------------- KDL

@dataclass
class KdlNode:
    name: str
    args: list
    children: list


KDL_STRING_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", "/": "/", '"': '"', "b": "\b", "f": "\f", "s": " "}
KDL_BARE_STOP = set(" \t\r\n{}();=\"\\")
# Cadena raw: r"..." y r#"..."# (KDL v1), #"..."# y #"""..."""# (v2).
KDL_RAW = re.compile(r'r?(#*)"(?:"")?')


def kdl_tokens(text: str) -> list[tuple[str, str]]:
    """Tokens de un documento KDL (v1 y v2): ('str'|'word'|'{'|'}'|';'|'nl'|'='|'/-', valor)."""
    tokens, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t﻿":
            i += 1
        elif c == "\n" or c == "\r":
            tokens.append(("nl", ""))
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            depth, i = 1, i + 2  # los comentarios de bloque se anidan
            while i < n and depth:
                if text.startswith("/*", i):
                    depth, i = depth + 1, i + 2
                elif text.startswith("*/", i):
                    depth, i = depth - 1, i + 2
                else:
                    i += 1
        elif text.startswith("/-", i):
            tokens.append(("/-", ""))
            i += 2
        elif c == "\\":  # continuación de línea
            i += 1
            while i < n and text[i] in " \t":
                i += 1
            if text.startswith("//", i):
                while i < n and text[i] != "\n":
                    i += 1
            if i < n and text[i] == "\r":
                i += 1
            if i < n and text[i] == "\n":
                i += 1
        elif c in "{};=":
            tokens.append((c, c))
            i += 1
        elif c == "(":  # anotación de tipo: se descarta
            i = text.index(")", i) + 1
        elif (raw := KDL_RAW.match(text, i)) and (c == "r" or raw.group(1)):
            hashes = raw.group(1)
            quote = '"""' if raw.group(0).endswith('"""') else '"'
            start = i + len(raw.group(0))
            end = text.index(quote + hashes, start)
            tokens.append(("str", text[start:end]))
            i = end + len(quote + hashes)
        elif c == '"':
            if text.startswith('"""', i):
                end = text.index('"""', i + 3)
                tokens.append(("str", text[i + 3:end]))
                i = end + 3
                continue
            i, value = i + 1, []
            while text[i] != '"':
                if text[i] == "\\":
                    escape = text[i + 1]
                    if escape == "u":
                        close = text.index("}", i)
                        value.append(chr(int(text[i + 3:close], 16)))
                        i = close + 1
                        continue
                    if escape in " \t\r\n":  # v2: escape de espacio en blanco
                        i += 1
                        while text[i] in " \t\r\n":
                            i += 1
                        continue
                    value.append(KDL_STRING_ESCAPES.get(escape, escape))
                    i += 2
                else:
                    value.append(text[i])
                    i += 1
            tokens.append(("str", "".join(value)))
            i += 1
        else:
            start = i
            while i < n and text[i] not in KDL_BARE_STOP and not text.startswith(("//", "/*", "/-"), i):
                i += 1
            if i == start:  # carácter suelto que KDL no admite: se salta
                i += 1
                continue
            tokens.append(("word", text[start:i]))
    return tokens


def kdl_parse(text: str) -> list[KdlNode]:
    """Árbol de nodos KDL. Lo comentado con `/-` (nodo, argumento o bloque) no aparece."""
    tokens = kdl_tokens(text)

    def skip_blank(i):
        while i < len(tokens) and tokens[i][0] == "nl":
            i += 1
        return i

    def nodes(i, in_block):
        found = []
        while i < len(tokens):
            kind = tokens[i][0]
            if kind in ("nl", ";"):
                i += 1
            elif kind == "}":
                if in_block:
                    return found, i + 1
                i += 1
            else:
                disabled = kind == "/-"
                if disabled:
                    i = skip_blank(i + 1)
                    if i >= len(tokens):
                        break
                node, i = parse_node(i)
                if not disabled:
                    found.append(node)
        return found, i

    def skip_value(i):
        if i + 1 < len(tokens) and tokens[i + 1][0] == "=":
            return i + 3
        return i + 1

    def parse_node(i):
        node = KdlNode(tokens[i][1], [], [])
        i += 1
        while i < len(tokens):
            kind, value = tokens[i]
            if kind in ("nl", ";"):
                return node, i + 1
            if kind == "}":
                return node, i
            if kind == "/-":
                i = skip_blank(i + 1)
                if i < len(tokens) and tokens[i][0] == "{":
                    _, i = nodes(i + 1, True)
                else:
                    i = skip_value(i)
            elif kind == "{":
                node.children, i = nodes(i + 1, True)
            elif i + 1 < len(tokens) and tokens[i + 1][0] == "=":
                i += 3  # propiedad clave=valor
            else:
                node.args.append(value)
                i += 1
        return node, i

    return nodes(0, False)[0]


def kdl_walk(nodes):
    for node in nodes:
        yield node
        yield from kdl_walk(node.children)


NIRI_CONFIGS = ("etc/skel/.config/niri/config.kdl", "usr/share/churros/defaults/niri/config.kdl")


def niri_refs() -> list[Ref]:
    # Acciones de niri que lanzan procesos (wiki de niri, Configuration:
    # Key Bindings y Miscellaneous): spawn/spawn-at-startup reciben argv,
    # spawn-sh/spawn-sh-at-startup una línea que ejecuta `sh -c`.
    refs = []
    for name in NIRI_CONFIGS:
        path = AIROOTFS / name
        for node in kdl_walk(kdl_parse(read(path))):
            if node.name in ("spawn", "spawn-at-startup") and node.args:
                refs.append(Ref(rel(path), node.args[0], NIRI, node.name, args=tuple(node.args[1:])))
            elif node.name in ("spawn-sh", "spawn-sh-at-startup") and node.args:
                refs += shell_refs(node.args[0], rel(path), NIRI, node.name)
    return refs


# --------------------------------------------------------------- .desktop

def desktop_groups(text: str) -> dict[str, dict[str, str]]:
    """Grupos de un fichero .desktop: {grupo: {clave: valor}} (sin claves localizadas)."""
    groups, current = {}, None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = groups.setdefault(line[1:-1], {})
        elif current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = value.strip()
    return groups


def desktop_exec_argv(value: str) -> list[str]:
    """argv de Exec= según la Desktop Entry Specification ("The Exec key").

    Primero los escapes de cadena del fichero (\\s, \\n, \\\\), luego las
    comillas dobles de Exec y por último se quitan los códigos de campo
    (%f %U...), que el lanzador sustituye.
    """
    value = re.sub(r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r"}.get(m.group(1), "\\" + m.group(1)), value)
    argv, word, quoted, i, started = [], [], False, 0, False
    while i < len(value):
        c = value[i]
        if quoted:
            if c == "\\" and i + 1 < len(value):
                word.append(value[i + 1])
                i += 2
                continue
            if c == '"':
                quoted = False
            else:
                word.append(c)
        elif c == '"':
            quoted, started = True, True
        elif c == " ":
            if word or started:
                argv.append("".join(word))
            word, started = [], False
        else:
            word.append(c)
        i += 1
    if word or started:
        argv.append("".join(word))
    argv = [arg for arg in argv if not re.fullmatch(r"%[a-zA-Z]", arg)]
    return [arg.replace("%%", "%") for arg in argv]


def desktop_file_refs(source: str, text: str, editions) -> list[Ref]:
    refs = []
    for group, keys in desktop_groups(text).items():
        if group != "Desktop Entry" and not group.startswith("Desktop Action "):
            continue
        if keys.get("TryExec"):
            # Sin TryExec en el PATH el lanzador oculta la entrada.
            refs.append(Ref(source, keys["TryExec"], tuple(editions), f"[{group}] TryExec"))
        argv = desktop_exec_argv(keys.get("Exec", ""))
        if argv:
            refs.append(Ref(source, argv[0], tuple(editions), f"[{group}] Exec", args=tuple(argv[1:])))
    return refs


def autostart_editions(keys: dict[str, str]):
    """Ediciones cuyo escritorio arrancaría esta entrada de autostart."""
    if keys.get("Hidden", "").lower() == "true":
        return ()
    only = [value for value in keys.get("OnlyShowIn", "").split(";") if value]
    hidden = [value for value in keys.get("NotShowIn", "").split(";") if value]
    picked = []
    for item in DESKTOP_EDITIONS:
        name = AUTOSTART_DESKTOPS.get(item.desktop)
        if name and (not only or name in only) and name not in hidden:
            picked.append(item)
    return tuple(picked)


def heredoc_files(text: str) -> list[tuple[str, str]]:
    """(ruta destino, contenido) de cada `cat > RUTA << 'X'` de un script."""
    found = []
    for match in re.finditer(r"cat\s+>\s*[\"']?(\S+?)[\"']?\s+<<-?\s*[\"']?(\w+)[\"']?\n(.*?)\n\s*\2\n", text, re.S):
        found.append((match.group(1), match.group(3)))
    return found


def desktop_refs() -> list[Ref]:
    refs = []
    for path in sorted((AIROOTFS / "usr/share/applications").glob("*.desktop")):
        refs += desktop_file_refs(rel(path), read(path), DESKTOP_EDITIONS)
    # customize_airootfs.sh sobrescribe calamares.desktop al construir la ISO.
    script = ROOT / "branding/customize_airootfs.sh"
    for target, body in heredoc_files(read(script)):
        if target.startswith("/usr/share/applications/") and target.endswith(".desktop"):
            refs += desktop_file_refs(f"{rel(script)}:{target}", body, DESKTOP_EDITIONS)
    for path in sorted((AIROOTFS / "etc/skel/.config/autostart").glob("*.desktop")):
        keys = desktop_groups(read(path)).get("Desktop Entry", {})
        refs += desktop_file_refs(rel(path), read(path), autostart_editions(keys))
    for path in sorted((AIROOTFS / "etc/skel/.config/xfce4/panel").glob("launcher-*/*.desktop")):
        refs += desktop_file_refs(rel(path), read(path), XFCE)
    return refs


def session_file_refs() -> list[Ref]:
    """Exec= que los scripts reescriben en las sesiones de wayland-sessions/xsessions."""
    refs = []
    scripts = [ROOT / "branding/customize_airootfs.sh", *sorted((AIROOTFS / "root/scripts").glob("*.sh")),
               *sorted(p for p in (AIROOTFS / "usr/share/churros/scripts").iterdir() if p.is_file())]
    for path in scripts:
        text = read(path)
        session_cmd = re.search(r"^SESSION_CMD=(\S+)$", text, re.M)
        for match in re.finditer(r"s\|\^Exec=\.\*\|Exec=([^|]+)\|", text):
            command = match.group(1)
            if command == "$SESSION_CMD" and session_cmd:
                command = session_cmd.group(1)
            if "$" not in command:
                refs.append(Ref(rel(path), command, DESKTOP_EDITIONS, "sed Exec= de la sesión"))
    return refs


# ------------------------------------------------- otros escritorios y apps

def xfconf_refs() -> list[Ref]:
    # xfce4-keyboard-shortcuts: canal commands/{default,custom}; xfsettingsd
    # lanza el valor con xfce_spawn_command_line (g_shell_parse_argv).
    path = AIROOTFS / "etc/skel/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-keyboard-shortcuts.xml"
    refs = []
    for commands in ET.parse(path).getroot().findall("property[@name='commands']"):
        for group in commands.findall("property"):
            for shortcut in group.findall("property[@type='string']"):
                refs += shell_refs(shortcut.get("value", ""), rel(path), XFCE, f"atajo {shortcut.get('name')}")
    return refs


def labwc_refs() -> list[Ref]:
    # labwc (src/action.c): Execute toma `command` (atributo o hijo; `execute`
    # en configuraciones antiguas) y lo lanza sin shell.
    refs = []
    for path in sorted((AIROOTFS / "etc/xdg/labwc").glob("*.xml")):
        for action in ET.parse(path).getroot().iter("action"):
            if action.get("name", "").lower() != "execute":
                continue
            command = action.get("command") or action.findtext("command") or action.findtext("execute") or ""
            refs += shell_refs(command.strip(), rel(path), LABWC, "Execute")
    return refs


def jsonc_load(text: str):
    """JSON con comentarios // y /* */ y comas finales (como lo lee waybar)."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            j = i + 1
            while text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            i = text.index("*/", i) + 2
        else:
            out.append(c)
            i += 1
    return json.loads(re.sub(r",(\s*[}\]])", r"\1", "".join(out)))


def waybar_module_names(bar: dict, names) -> set[str]:
    used = set()
    for name in names:
        if name in used:
            continue
        used.add(name)
        if name.startswith("group/") and isinstance(bar.get(name), dict):
            used |= waybar_module_names(bar, bar[name].get("modules", []))
    return used


def waybar_refs() -> list[Ref]:
    # waybar ejecuta exec/exec-if y los on-* de cada módulo con `sh -c`. Solo
    # cuentan los módulos que la barra coloca (modules-left/center/right y
    # los grupos). La config de skel es la alternativa a Noctalia en niri;
    # la de Pi la pasa churros-pi-session con --config.
    configs = {
        "etc/skel/.config/waybar/config.jsonc": NIRI,
        "usr/share/churros/defaults/waybar/config.jsonc": NIRI,
        "usr/share/churros/pi/waybar/config.jsonc": LABWC,
    }
    refs = []
    for name, editions in configs.items():
        path = AIROOTFS / name
        data = jsonc_load(read(path))
        for bar in data if isinstance(data, list) else [data]:
            names = [m for key in ("modules-left", "modules-center", "modules-right") for m in bar.get(key, [])]
            for module in sorted(waybar_module_names(bar, names)):
                for key, value in (bar.get(module) or {}).items():
                    if isinstance(value, str) and (key in ("exec", "exec-if") or key.startswith("on-")):
                        refs += shell_refs(value, rel(path), editions, f"{module} {key}")
    return refs


def wlogout_refs() -> list[Ref]:
    # wlogout lee una secuencia de objetos JSON; `action` va a una shell.
    path = AIROOTFS / "etc/skel/.config/wlogout/layout"
    text, decoder, index, refs = read(path), json.JSONDecoder(), 0, []
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        entry, index = decoder.raw_decode(text, index)
        refs += shell_refs(entry.get("action", ""), rel(path), NIRI, f"botón {entry.get('label')}")
    return refs


def noctalia_refs() -> list[Ref]:
    refs = []
    for name in ("etc/skel/.config/noctalia/config.toml", "usr/share/churros/defaults/noctalia/config.toml"):
        path = AIROOTFS / name
        data = tomllib.loads(read(path))
        for action in data.get("shell", {}).get("session", {}).get("actions", []):
            if action.get("action") == "command" and action.get("command"):
                refs += shell_refs(action["command"], rel(path), NIRI, f"acción de sesión {action.get('label')}")
    return refs


def fuzzel_refs() -> list[Ref]:
    # fuzzel.ini [main]: launch-prefix antepone ese comando a cada app.
    refs = []
    for name in ("etc/skel/.config/fuzzel/fuzzel.ini", "usr/share/churros/defaults/fuzzel/fuzzel.ini"):
        path = AIROOTFS / name
        editions = tuple(item for item in DESKTOP_EDITIONS if item.desktop in ("niri", "labwc") and resolves("fuzzel", item))
        for line in read(path).splitlines():
            match = re.match(r"\s*(launch-prefix|terminal)\s*=\s*(.+)", line)
            if match:
                refs += shell_refs(match.group(2), rel(path), editions, match.group(1))
    return refs


# ------------------------------------------------------------ greetd y sesión

BUILD_SH = ROOT / "scripts/cli/build.sh"
EDITION_SESSION = AIROOTFS / "usr/share/churros/scripts/edition-session.sh"


def case_table(text: str, pattern: str) -> dict[str, str | None]:
    """Brazos `nombre|otro) ... ;;` cuyo cuerpo casa con `pattern` (grupo 1) o hace return."""
    table = {}
    for match in re.finditer(r"^\s*([\w|*]+)\)\s*(.*?)\s*;;", text, re.M):
        body = match.group(2)
        found = re.search(pattern, body)
        value = found.group(1) if found else (None if "return 1" in body else "")
        if value == "":
            continue
        for name in match.group(1).split("|"):
            table[name] = value
    return table


def build_session_commands() -> dict[str, str]:
    """SESSION_CMD de cada edición según el case de scripts/cli/build.sh."""
    for block in re.findall(r'case "\$EDITION" in\n(.*?)\n\s*esac', read(BUILD_SH), re.S):
        if "SESSION_CMD=" in block:
            return {name: cmd for name, cmd in case_table(block, r'SESSION_CMD="([^"]*)"').items() if cmd}
    return {}


def build_greetd_config(session_cmd: str) -> dict:
    """config.toml de greetd tal como lo escribe build.sh para un SESSION_CMD."""
    text = read(BUILD_SH)
    match = re.search(r"cat > archiso/airootfs/etc/greetd/config\.toml << EOF\n(.*?)\nEOF\n", text, re.S)
    return tomllib.loads(match.group(1).replace("$SESSION_CMD", session_cmd))


def installed_session_commands() -> dict[str, str | None]:
    """churros_session_command de edition-session.sh: edición -> comando (None: sin sesión)."""
    text = read(EDITION_SESSION)
    body = re.search(r"churros_session_command\(\)\s*\{(.*?)\n\}", text, re.S).group(1)
    return case_table(body, r"printf '%s\\n' (\S+)")


def session_for(table: dict, name: str):
    return table[name] if name in table else table.get("*")


def wrapper_refs(command: str, item, origin: str) -> list[Ref]:
    """Programas que lanza un wrapper de sesión: sus `exec` y lo que deja en segundo plano."""
    path = AIROOTFS / command.lstrip("/")
    if not command.startswith("/") or not path.is_file() or testlib.shebang(path) not in testlib.SHEBANG_SHELLS:
        return []
    text = read(path)
    guarded = guarded_commands(text)
    # Funciones del propio script (`f() { ...; }`): lanzar `f &` no ejecuta
    # un programa llamado f, sino los comandos de su cuerpo.
    functions = {match.group(1): match.group(2) for match in re.finditer(
        r"^\s*(?:function\s+)?([A-Za-z_][\w-]*)\s*\(\s*\)\s*\{(.*?)^\s*\}", text, re.M | re.S)}
    refs = []

    def add(line: str, where: str) -> None:
        for ref in shell_refs(line, rel(path), (item,), where):
            if ref.command in functions:
                for body_line in functions.pop(ref.command).splitlines():
                    body_line = body_line.strip().rstrip("&").strip()
                    if body_line and not body_line.startswith("#"):
                        add(body_line, f"{where}, función {ref.command}")
                continue
            optional = ref.command in guarded or Path(ref.command).name in guarded
            refs.append(Ref(ref.source, ref.command, ref.editions, ref.where, optional, ref.args))

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith("exec ") or re.search(r"[^&]&\s*$", stripped):
            add(stripped.rstrip("&"), f"línea {number} ({origin})")
    return refs


def greetd_refs() -> list[Ref]:
    refs = []
    sessions = build_session_commands()
    for item in EDITIONS:
        if not resolves("greetd", item):
            continue  # sin greetd ese config.toml no lo lee nadie
        session_cmd = sessions.get(item.name)
        if session_cmd is None:
            continue  # build.sh se para antes (lo vigila test_editions)
        config = build_greetd_config(session_cmd)
        for section in ("default_session", "initial_session"):
            command = config.get(section, {}).get("command", "")
            source = f"{rel(BUILD_SH)}:{section}"
            refs += shell_refs(command, source, (item,), section)
            for argv in command_words(command):
                refs += wrapper_refs(argv[0], item, f"sesión Live {item.id}")
    installed = installed_session_commands()
    text = read(EDITION_SESSION)
    greeter = re.search(r'\[default_session\]\ncommand = "(.*)"', text).group(1)
    for item in INSTALLER:
        if not resolves("greetd", item):
            continue
        refs += shell_refs(greeter, f"{rel(EDITION_SESSION)}:default_session", (item,), "greeter instalado")
        command = session_for(installed, item.name)
        if command:
            refs.append(Ref(f"{rel(EDITION_SESSION)}:initial_session", command, (item,), "sesión instalada"))
            refs += wrapper_refs(command, item, f"sesión instalada {item.id}")
    regreet = AIROOTFS / "etc/greetd/regreet.toml"
    editions = tuple(item for item in EDITIONS if resolves("greetd", item) and resolves("regreet", item))
    for key, argv in tomllib.loads(read(regreet)).get("commands", {}).items():
        if isinstance(argv, list) and argv:
            refs.append(Ref(rel(regreet), argv[0], editions, f"[commands] {key}", args=tuple(argv[1:])))
    return refs


# --------------------------------------------------------- systemd y pacman

EXEC_KEYS = {"ExecStart", "ExecStartPre", "ExecStartPost", "ExecStop", "ExecStopPost",
             "ExecReload", "ExecCondition"}
SYSTEMCTL_STARTS = {"start", "restart", "reload", "try-restart", "reload-or-restart", "enable", "reenable"}


def unit_command_refs(path: Path, line: str, key: str) -> list[Ref]:
    # systemd.service(5), "Command lines": prefijos @ - : + ! !!; con '-' un
    # fallo (también 203/EXEC) no cuenta. El resto se separa como palabras
    # entre comillas.
    prefix = re.match(r"[@\-:+!]*", line).group(0)
    words = shlex.split(line[len(prefix):])
    if not words:
        return []
    optional = "-" in prefix
    refs = [Ref(rel(path), words[0], EDITIONS, key, optional, tuple(words[1:]))]
    if Path(words[0]).name == "systemctl":
        verbs = [word for word in words[1:] if not word.startswith("-")]
        if verbs and verbs[0] in SYSTEMCTL_STARTS:
            refs += [Ref(rel(path), unit, EDITIONS, f"{key} systemctl {verbs[0]}", optional, kind="unit")
                     for unit in verbs[1:] if re.search(r"\.(service|socket|timer|target|path|mount)$", unit)]
    return refs


def systemd_refs() -> list[Ref]:
    refs = []
    roots = [AIROOTFS / "etc/systemd", AIROOTFS / "etc/skel/.config/systemd"]
    for base in roots:
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            for line in read(path).splitlines():
                match = re.match(r"\s*(Exec\w+)\s*=\s*(.+)", line)
                if match and match.group(1) in EXEC_KEYS:
                    refs += unit_command_refs(path, match.group(2).strip(), match.group(1))
    return refs


def hook_refs() -> list[Ref]:
    # alpm-hooks(5): Exec se parte en palabras y se ejecuta sin shell.
    refs = []
    for path in sorted((AIROOTFS / "etc/pacman.d/hooks").glob("*.hook")):
        for line in read(path).splitlines():
            match = re.match(r"\s*Exec\s*=\s*(.+)", line)
            if not match:
                continue
            words = shlex.split(match.group(1))
            refs.append(Ref(rel(path), words[0], EDITIONS, "Exec", args=tuple(words[1:])))
            if Path(words[0]).name in SHELLS and len(words) > 2 and words[1] == "-c":
                refs += shell_refs(words[2], rel(path), EDITIONS, "Exec sh -c")
    return refs


# ---------------------------------------------------------------- Calamares

CALAMARES = ROOT / "installer/calamares"


def calamares_module(name: str, arch: str) -> Path:
    """Config efectiva de un módulo: la de modules/<arch>/ pisa la común (apply-calamares.sh)."""
    override = CALAMARES / "modules" / arch / name
    return override if override.exists() else CALAMARES / "modules" / name


def calamares_refs(yaml) -> list[Ref]:
    refs = []
    settings = yaml.safe_load(read(CALAMARES / "settings.conf"))
    configs = [entry["config"] for entry in settings.get("instances", []) if entry.get("module") == "shellprocess"]
    for item in INSTALLER:
        for name in configs:
            path = calamares_module(name, item.arch)
            data = yaml.safe_load(read(path)) or {}
            script = data.get("script", [])
            for entry in script if isinstance(script, list) else [script]:
                command = entry.get("command", "") if isinstance(entry, dict) else str(entry)
                # ShellProcessJob: un '-' inicial ignora el código de salida;
                # el resto va a `/bin/sh -c`.
                optional = command.startswith("-")
                refs += shell_refs(command.lstrip("-"), rel(path), (item,), "script", optional)
        finished = yaml.safe_load(read(calamares_module("finished.conf", item.arch))) or {}
        if finished.get("restartNowCommand"):
            refs += shell_refs(finished["restartNowCommand"], rel(calamares_module("finished.conf", item.arch)), (item,), "restartNowCommand")
        dm = yaml.safe_load(read(calamares_module("displaymanager.conf", item.arch))) or {}
        executable = dm.get("defaultDesktopEnvironment", {}).get("executable")
        if executable:
            refs.append(Ref(rel(calamares_module("displaymanager.conf", item.arch)), executable, (item,), "defaultDesktopEnvironment.executable"))
        users = yaml.safe_load(read(calamares_module("users.conf", item.arch))) or {}
        shell = (users.get("user") or {}).get("shell")
        if shell:
            refs.append(Ref(rel(calamares_module("users.conf", item.arch)), shell, (item,), "user.shell"))
    return refs


def login_shell_refs() -> list[Ref]:
    refs = []
    passwd = AIROOTFS / "etc/passwd"
    for line in read(passwd).splitlines():
        fields = line.split(":")
        if len(fields) == 7 and fields[6]:
            refs.append(Ref(rel(passwd), fields[6], EDITIONS, f"shell de {fields[0]}"))
    users = AIROOTFS / "root/scripts/users.sh"
    text = read(users).replace("\\\n", " ")
    for match in re.finditer(r"^\s*useradd\b(.*)$", text, re.M):
        shell = re.search(r"(?:-s|--shell)\s+(\S+)", match.group(1))
        if shell:
            refs.append(Ref(rel(users), shell.group(1), EDITIONS, "useradd --shell"))
    return refs


# --------------------------------------------------------------------- Rust

HELPER_DEF = re.compile(r"fn\s+(\w+)\s*(?:<[^>]*>)?\(\s*(\w+)\s*:\s*&\[&str\]")


def without_tests(text: str) -> str:
    """Quita los `#[cfg(test)] mod x { ... }` (conserva los saltos de línea)."""
    while match := re.search(r"#\[cfg\(test\)\]\s*mod\s+\w+\s*\{", text):
        end = block_end(text, match.end() - 1)
        text = text[:match.start()] + "\n" * text[match.start():end].count("\n") + text[end:]
    return text


def block_end(text: str, start: int) -> int:
    """Posición tras la llave que cierra la que abre en `start` (sin mirar cadenas)."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    return len(text)


@lru_cache(maxsize=None)
def rust_sources() -> dict[Path, str]:
    return {path: without_tests(read(path)) for path in sorted(ROOT.glob("rust/*/src/**/*.rs"))
            if path.name != "tests.rs"}


@lru_cache(maxsize=None)
def rust_helpers() -> frozenset[str]:
    """Funciones `fn x(args: &[&str])` que acaban en Command::new(args[0]), directa o indirectamente."""
    helpers, changed = set(), True
    while changed:
        changed = False
        for text in rust_sources().values():
            for match in HELPER_DEF.finditer(text):
                name, param = match.groups()
                if name in helpers:
                    continue
                start = text.find("{", match.end())
                body = text[start:block_end(text, start)]
                direct = re.search(rf"Command::new\(\s*&?\s*{param}\[0\]\s*\)", body)
                nested = any(re.search(rf"\b{helper}\(\s*&?{param}\b", body) for helper in helpers)
                if direct or nested:
                    helpers.add(name)
                    changed = True
    return frozenset(helpers)


def rust_commands() -> dict[tuple[str, str], list[str]]:
    """{(crate, programa): ['fichero:línea', ...]} de los literales que Rust ejecuta."""
    helpers = "|".join(sorted(rust_helpers()))
    patterns = [re.compile(r'Command::new\(\s*"([^"]+)"\s*\)')]
    if helpers:
        patterns.append(re.compile(rf'(?<![\w.])(?:\w+::)*(?:{helpers})\(\s*&\[\s*"([^"]+)"'))
    found = {}
    for path, text in rust_sources().items():
        crate = path.relative_to(ROOT / "rust").parts[0]
        for pattern in patterns:
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                found.setdefault((crate, match.group(1)), []).append(f"{rel(path)}:{line}")
    return found


def rust_refs() -> list[Ref]:
    refs = []
    for (crate, command), places in sorted(rust_commands().items()):
        desktop = RUST_DESKTOP_ONLY.get(Path(command).name, "niri")
        if desktop is None:
            continue
        editions = tuple(testlib.editions_with_desktop(desktop))
        refs.append(Ref(f"rust/{crate}", command, editions, ", ".join(places[:3])))
    return refs


# ----------------------------------------------------------------- conjunto

@lru_cache(maxsize=None)
def all_refs(yaml) -> tuple[Ref, ...]:
    groups = (niri_refs, desktop_refs, session_file_refs, xfconf_refs, labwc_refs, waybar_refs,
              wlogout_refs, noctalia_refs, fuzzel_refs, greetd_refs, systemd_refs, hook_refs,
              login_shell_refs, rust_refs, lambda: calamares_refs(yaml))
    return tuple(ref for group in groups for ref in group())


def unit_resolution(unit: str, item) -> bool | None:
    """¿Existe la unidad en la edición? None si no se sabe de qué paquete sale."""
    for directory in ("etc/systemd/system", "usr/lib/systemd/system", "etc/systemd/user"):
        if (AIROOTFS / directory / unit).exists():
            return True
    package = testlib.providers()["units"].get(unit)
    if package is None:
        base = unit.rsplit(".", 1)[0]
        known = {name for edition in EDITIONS for name in testlib.packages(edition)}
        package = base if base in known else None
    if package is None:
        return None
    return package in testlib.installed(item)


def crate_name(command: str) -> str | None:
    name = command[len("/usr/bin/"):] if command.startswith("/usr/bin/") else command
    return name if name in testlib.deploy_crate_names() else None


def crate_main(name: str) -> Path:
    for crate in testlib.crates():
        if crate.name == name:
            return crate.directory / "src/main.rs"
    raise KeyError(name)


class ReferenceTests(unittest.TestCase):
    """Cada programa que lanza la configuración existe donde se lanza."""

    @classmethod
    def setUpClass(cls):
        if tomllib is None:
            raise unittest.SkipTest("tomllib necesita Python >= 3.11")

    def refs(self) -> tuple[Ref, ...]:
        return all_refs(testlib.require_module(self, "yaml"))

    def test_every_source_yields_references(self):
        # Una fuente que de repente no aporta nada es un parser roto (o un
        # formato que cambió), no una configuración perfecta.
        counts = {}
        for ref in self.refs():
            counts[ref.source.split(":")[0]] = counts.get(ref.source.split(":")[0], 0) + 1
        expected = [f"archiso/airootfs/{name}" for name in NIRI_CONFIGS]
        # Solo los .desktop que ejecutan algo: un Type=Link (URL=) o uno con solo
        # DBusActivatable no aporta referencias y es válido.
        expected += [rel(path) for path in sorted((AIROOTFS / "usr/share/applications").glob("*.desktop"))
                     if re.search(r"^(?:Try)?Exec\s*=\s*\S", read(path), re.M)]
        expected += [rel(path) for path in sorted((AIROOTFS / "etc/pacman.d/hooks").glob("*.hook"))]
        expected += ["archiso/airootfs/etc/xdg/labwc/rc.xml", "archiso/airootfs/etc/greetd/regreet.toml",
                     rel(BUILD_SH), rel(EDITION_SESSION), "archiso/airootfs/usr/bin/churros-niri-session",
                     "archiso/airootfs/usr/bin/churros-xfce-session", "archiso/airootfs/usr/bin/churros-pi-session",
                     "installer/calamares/modules/shellprocess-cleanup.conf", "rust/services", "rust/preferences"]
        empty = [name for name in expected if not counts.get(name)]
        self.assertEqual(empty, [], "estas fuentes no aportan ninguna referencia: ¿el parser dejó de entenderlas?")

    def test_every_reference_resolves(self):
        findings, optional = {}, {}
        for ref in self.refs():
            if ref.optional:
                if ref.kind == "command":
                    optional.setdefault((ref.source, ref.command), [ref.where, set()])[1].update(ref.editions)
                continue
            for item in ref.editions:
                if ref.kind == "unit":
                    if unit_resolution(ref.command, item) is False:
                        findings[f"ref:{item.id}:{ref.source}:{ref.command}"] = (
                            f"{item.id}: {ref.source} ({ref.where}) arranca {ref.command}, cuyo paquete no está en {item.package_list}")
                    continue
                result = testlib.resolve_command(ref.command, item)
                if not result.ok:
                    findings[f"ref:{item.id}:{ref.source}:{ref.command}"] = (
                        f"{item.id}: {ref.source} ({ref.where}) ejecuta '{ref.command}': {result.how}")
        # Lo opcional puede faltar en una edición, pero no en todas: eso es una errata.
        for (source, command), (where, editions) in optional.items():
            if editions and not any(resolves(command, item) for item in editions):
                findings[f"ref:any:{source}:{command}"] = (
                    f"{source} ({where}) ejecuta '{command}', que no existe en ninguna edición "
                    f"({', '.join(sorted(item.id for item in editions))}): ¿errata?")
        testlib.assert_findings(self, "ref", findings)

    def test_referenced_paths_are_executable(self):
        # mkarchiso copia el airootfs con `cp -af --no-preserve=ownership,mode`
        # y solo file_permissions de profiledef.sh da el bit de ejecución.
        findings = {}
        for ref in self.refs():
            if ref.kind != "command":
                continue
            path = ref.command
            if not path.startswith("/"):
                path = next((f"/{d}/{path}" for d in ("usr/bin", "usr/local/bin") if (AIROOTFS / d / path).exists()), "")
                path = path or (f"/usr/bin/{ref.command}" if crate_name(ref.command) else "")
            in_tree = path and (testlib.airootfs(path).is_file() and not testlib.airootfs(path).is_symlink())
            if not (in_tree or path in testlib.generated_paths()):
                continue
            for arch in sorted({item.arch for item in ref.editions}):
                spec = testlib.profile(arch)["file_permissions"].get(path)
                if spec is None or not testlib.mode_is_executable(spec):
                    findings[f"ref-not-executable:{path}"] = (
                        f"{ref.source} ({ref.where}) ejecuta {path}, que no tiene modo ejecutable en "
                        f"file_permissions de archiso/profiledef.sh ({arch}): llega a la ISO como 0644")
        testlib.assert_findings(self, "ref-not-executable", findings)

    def test_rust_binaries_accept_their_arguments(self):
        # gtk::Application::run() pasa std::env::args() a GApplication: una
        # opción desconocida sale con "Unknown option" y un argumento suelto
        # con "This application can not open files" (exit 1). Solo
        # run_with_args deja los argumentos a la propia app.
        findings = {}
        popups = re.search(r"const POPUPS:[^=]*=\s*\[(.*?)\]", read(crate_main("churros-popup")), re.S)
        popup_names = set(re.findall(r'"([^"]+)"', popups.group(1))) if popups else set()
        for ref in self.refs():
            name = crate_name(ref.command)
            if not name or not ref.args:
                continue
            main = without_tests(read(crate_main(name)))
            if re.search(r"\.run\(\s*\)", main) and "run_with_args" not in main:
                findings[f"ref-args:{ref.source}:{name}"] = (
                    f"{ref.source} ({ref.where}) lanza '{name} {' '.join(ref.args)}', pero {rel(crate_main(name))} "
                    f"usa app.run(): GApplication rechaza esos argumentos y sale con 1")
            if name == "churros-popup" and ref.args[0] not in popup_names:
                findings[f"ref-args:{ref.source}:{name} {ref.args[0]}"] = (
                    f"{ref.source} ({ref.where}) abre el popup '{ref.args[0]}', que no está en POPUPS de "
                    f"{rel(crate_main(name))}: churros-popup sale con 64")
        testlib.assert_findings(self, "ref-args", findings)


class ParserTests(unittest.TestCase):
    """Los parsers entienden lo que entienden los programas de verdad."""

    def test_kdl_comments_slashdash_and_raw_strings(self):
        text = '''
        // spawn "comentado"
        /* spawn "bloque" /* anidado */ spawn "sigue-comentado" */
        /-spawn-at-startup "desactivado"
        binds {
            Mod+T hotkey-overlay-title="T" { spawn "foot" "-e" "btop"; }
            Mod+X /-{ spawn "hijos-desactivados"; }
            Mod+Y { spawn-sh r#"echo "a" && wpctl"#; }
            Mod+Z { spawn #"uno"#; spawn "\\u{66}uzzel"; }
        }
        spawn-at-startup \\
            "noctalia"
        '''
        spawns = [(node.name, node.args) for node in kdl_walk(kdl_parse(text)) if node.name.startswith("spawn")]
        self.assertEqual(spawns, [
            ("spawn", ["foot", "-e", "btop"]),
            ("spawn-sh", ['echo "a" && wpctl']),
            ("spawn", ["uno"]),
            ("spawn", ["fuzzel"]),
            ("spawn-at-startup", ["noctalia"]),
        ])

    def test_shell_words(self):
        cases = {
            "/usr/local/bin/x create || echo aviso >&2": [["/usr/local/bin/x", "create"], ["echo", "aviso"]],
            "pgrep -x wf >/dev/null 2>&1 && echo ok": [["pgrep", "-x", "wf"], ["echo", "ok"]],
            "env A=1 B=2 cage -s -- regreet": [["env", "A=1", "B=2", "cage", "-s", "--", "regreet"],
                                               ["cage", "-s", "--", "regreet"], ["regreet"]],
            "command -v startx >/dev/null || exec startxfce4": [["startxfce4"]],
            "[ -f ~/.x ] && churros-tour": [["[", "-f", "~/.x", "]"], ["churros-tour"]],
            "rm -- $(grep -Frl 'a b' /h/)": [["rm", "--", "$"], ["grep", "-Frl", "a b", "/h/"]],
            "$TERMINAL -e x; ./local": [],
        }
        for line, expected in cases.items():
            self.assertEqual(command_words(line), expected, line)

    def test_desktop_exec(self):
        self.assertEqual(desktop_exec_argv('churros-apply-wallpaper %f'), ["churros-apply-wallpaper"])
        self.assertEqual(desktop_exec_argv('"/opt/my app/run" --x=%% %U'), ["/opt/my app/run", "--x=%"])
        self.assertEqual(desktop_exec_argv(r'sh -c "echo \"hi\"\sthere"'), ["sh", "-c", 'echo "hi" there'])

    def test_autostart_respects_show_in(self):
        self.assertEqual(autostart_editions({"OnlyShowIn": "XFCE;"}), XFCE)
        self.assertEqual(autostart_editions({"NotShowIn": "XFCE;"}), ())
        self.assertEqual(autostart_editions({"OnlyShowIn": "niri;"}), ())
        self.assertEqual(autostart_editions({}), XFCE)
        self.assertEqual(autostart_editions({"Hidden": "true"}), ())


if __name__ == "__main__":
    unittest.main()
