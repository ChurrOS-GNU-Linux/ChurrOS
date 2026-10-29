"""Modelo de la configuración de Calamares que va en la ISO.

Lee installer/calamares como lo lee Calamares 3.4.2 (el que compila
scripts/build-calamares.sh desde el AUR, con yaml-cpp) y comprueba lo que
hoy solo se vería instalando en QEMU. Cada familia es un método:

1. YAML estricto: cada fichero carga, sin claves duplicadas, y los .conf de
   módulo y branding.desc son un mapa (si no, Calamares descarta el fichero
   entero sin avisar en la interfaz).
2. Secuencia de settings.conf: claves, branding, las cinco instancias,
   módulos que existen en 3.4.2, el .conf de cada paso por arquitectura (con
   la capa modules/<arch> que copia apply-calamares.sh), el orden entre
   pasos y las vistas que tienen que mostrarse para que sus trabajos hagan
   algo.
3. shellprocess-*.conf: claves, `script` no vacío, sintaxis de cada comando,
   variables de Calamares, dontChroot por instancia, scripts absolutos que
   existen y son ejecutables en la ISO, y la regla del bloque [churros].
4. Simulación: los comandos reales de fix-boot sobre los presets de
   mkinitcpio de cada arquitectura y la limpieza de pacman.conf de
   post-install, en un root temporal.
5. Referencias cruzadas: unidades de services-systemd, gestor de sesiones,
   shell, grupos y sudo de users.conf, hooks de initcpiocfg y netinstall.

Las reglas salen del código de Calamares v3.4.2 (codeberg.org/Calamares/
calamares, src/libcalamares y src/modules); cada una cita el fichero.

Uso: python3 -m unittest tests.static.test_calamares_config -v
Necesita PyYAML (python3-yaml) y bash.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

from tests import testlib

CALAMARES = testlib.ROOT / "installer/calamares"
MODULES = CALAMARES / "modules"
SETTINGS = CALAMARES / "settings.conf"
# MemTotal de un equipo de 2 GB físicos con gráfica integrada (GiB).
MIN_SUPPORTED_RAM_GIB = 1.7
BRANDING = CALAMARES / "branding"

# Ediciones y arquitecturas que llevan el instalador (build.sh lo omite en i686).
INSTALLER_EDITIONS = tuple(item for item in testlib.EDITIONS if item.installer)
INSTALLER_ARCHES = tuple(sorted({item.arch for item in INSTALLER_EDITIONS}))

# ------------------------------------------------------- hechos de Calamares 3.4.2

# Módulos de src/modules (nombre -> tipo de module.desc o calamares_add_plugin).
CALAMARES_MODULES = {
    "bootloader": "job", "contextualprocess": "job", "displaymanager": "job",
    "dracut": "job", "dracutlukscfg": "job", "dummycpp": "job",
    "dummyprocess": "job", "dummypython": "job", "finished": "view",
    "finishedq": "view", "fsresizer": "job", "fstab": "job", "grubcfg": "job",
    "hostinfo": "job", "hwclock": "job", "initcpio": "job", "initcpiocfg": "job",
    "initramfs": "job", "initramfscfg": "job", "interactiveterminal": "view",
    "keyboard": "view", "keyboardq": "view", "license": "view", "locale": "view",
    "localecfg": "job", "localeq": "view", "luksbootkeyfile": "job",
    "luksopenswaphookcfg": "job", "machineid": "job", "mkinitfs": "job",
    "mount": "job", "netinstall": "view", "networkcfg": "job", "notesqml": "view",
    "oemid": "view", "openrcdmcryptcfg": "job", "packagechooser": "view",
    "packagechooserq": "view", "packages": "job", "partition": "view",
    "plasmalnf": "view", "plymouthcfg": "job", "preservefiles": "job",
    "rawfs": "job", "removeuser": "job", "services-openrc": "job",
    "services-systemd": "job", "shellprocess": "job", "summary": "view",
    "summaryq": "view", "tracking": "view", "umount": "job", "unpackfs": "job",
    "unpackfsc": "job", "users": "view", "usersq": "view", "welcome": "view",
    "welcomeq": "view", "zfs": "job", "zfshostid": "job",
}
# El PKGBUILD del AUR los quita con -DSKIP_MODULES: no están en la ISO y
# ModuleManager::loadModules falla con "not found in module search paths".
AUR_SKIPPED_MODULES = frozenset({
    "dracut", "dracutlukscfg", "dummycpp", "dummyprocess", "dummypython",
    "dummypythonqt", "initramfs", "initramfscfg", "interactiveterminal",
    "packagechooser", "packagechooserq", "services-openrc",
})
AVAILABLE_MODULES = frozenset(CALAMARES_MODULES) - AUR_SKIPPED_MODULES
# module.desc `noconfig: true` / NO_CONFIG: getConfigFileName() devuelve ""
# y Calamares nunca abre su .conf (ModuleManager.cpp).
NOCONFIG_MODULES = frozenset({
    "dracutlukscfg", "hostinfo", "hwclock", "initramfscfg", "localecfg",
    "networkcfg", "summary", "summaryq", "zfshostid",
})
# Sin .conf propio, Module::loadConfigurationFile cae en
# /usr/share/calamares/modules/<m>.conf (el AUR compila con INSTALL_CONFIG=ON).
# Solo se acepta donde ese valor por defecto es el que queremos.
UPSTREAM_DEFAULT_OK = {"umount": "emergency: true"}

# Settings::setConfiguration (src/libcalamares/Settings.cpp) lee estas claves.
SETTINGS_KEYS = frozenset({
    "modules-search", "instances", "sequence", "branding", "prompt-install",
    "dont-chroot", "oem-setup", "disable-cancel", "disable-cancel-during-exec",
    "hide-back-and-next-during-exec", "quit-at-end",
})
SETTINGS_BOOLS = SETTINGS_KEYS - {"modules-search", "instances", "sequence", "branding"}
# InstanceDescription::fromSettings.
INSTANCE_KEYS = frozenset({"id", "module", "config", "weight", "autoProceed"})
# ShellProcessJob::setConfigurationMap y CommandLine(QVariantMap).
SHELLPROCESS_KEYS = frozenset({"dontChroot", "timeout", "verbose", "script", "i18n"})
COMMAND_KEYS = frozenset({"command", "timeout", "verbose", "environment"})

# AGENTS.md, "Calamares Sequence": cinco instancias shellprocess, ni una más.
# dontChroot: boot-nocow corre antes de unpackfs, cuando el destino todavía
# no tiene /bin/sh (chroot imposible) y usa ${ROOT}; las demás escriben en
# rutas del sistema instalado (/etc, /boot) y tienen que correr dentro.
EXPECTED_DONT_CHROOT = {
    "boot-nocow": True,
    "pacman-init": False,
    "fix-boot": False,
    "grub-theme": False,
    "post-install": False,
}

# Pasos sin los que la instalación no arranca o queda a medias.
REQUIRED_EXEC = (
    "partition", "mount", "shellprocess@boot-nocow", "unpackfs",
    "shellprocess@pacman-init", "shellprocess@fix-boot", "initcpiocfg",
    "initcpio", "users", "services-systemd", "grubcfg", "bootloader",
    "shellprocess@grub-theme", "shellprocess@post-install", "umount",
)
# (antes, después, por qué)
ORDER = (
    ("partition", "mount", "mount monta lo que crea partition"),
    ("mount", "shellprocess@boot-nocow", "boot-nocow usa ${ROOT}/boot montado"),
    ("shellprocess@boot-nocow", "unpackfs",
     "chattr +C solo afecta a ficheros nuevos: /boot tiene que ser No_COW antes de copiar vmlinuz (GRUB 'premature end of file')"),
    ("shellprocess@pacman-init", "shellprocess@fix-boot", "AGENTS.md: el keyring va antes que fix-boot"),
    ("shellprocess@fix-boot", "initcpio",
     "mkinitcpio -P lee el preset: sin la reescritura de fix-boot genera el initramfs de archiso"),
    ("initcpiocfg", "initcpio", "initcpiocfg escribe los HOOKS que usa mkinitcpio"),
    ("grubcfg", "bootloader", "bootloader corre grub-mkconfig con el /etc/default/grub de grubcfg"),
    ("bootloader", "shellprocess@grub-theme",
     "grub-theme copia el tema en /boot/grub (lo crea grub-install) y vuelve a correr grub-mkconfig"),
)
# Pasos que escriben en el destino: unpackfs copia el squashfs encima.
TARGET_WRITERS = frozenset({
    "machineid", "fstab", "locale", "keyboard", "localecfg", "initcpiocfg",
    "initcpio", "users", "displaymanager", "networkcfg", "hwclock",
    "services-systemd", "grubcfg", "bootloader",
})
# Vistas cuyos trabajos dependen de lo que elige la persona. users:
# Config::createJobs devuelve una lista vacía si !isReady() (users/Config.cpp),
# o sea, sin usuario ni sudo y root con la contraseña vacía del squashfs.
# partition: sin elección no hay trabajos y mount falla. locale y keyboard
# aplicarían en silencio America/New_York y "us" de su .conf.
VIEWS_MUST_BE_SHOWN = ("partition", "locale", "keyboard", "users")

# Variables que CommandList (src/libcalamares/utils/CommandList.cpp) sabe
# expandir. Las demás ($f, $1, ${HOME}) son "Missing variables" y el trabajo
# falla antes de correr nada; `$$` es el escape.
CALAMARES_VARIABLES = frozenset({"ROOT", "USER", "LANG"})

# Programas que la simulación ejecuta de verdad (con todas las rutas
# absolutas reescritas al root temporal) y scripts del airootfs que aceptan
# CHURROS_ROOT para trabajar fuera de /.
SIMULATION_PROGRAMS = frozenset({
    "rm", "sed", "awk", "mv", "cp", "mkdir", "cat", "grep", "test", "[",
    "printf", "echo", "true", "false", "touch", "ln", "chmod",
})
SIMULATION_SCRIPTS = frozenset({"/usr/share/churros/scripts/publish-aarch64-kernel"})
REWRITTEN_ROOTS = re.compile(r"/(?:etc|tmp|var|usr|boot|root|home|run|opt|srv|mnt|lib|bin|sbin)(?:/|$)")

# Qué hay en /etc/mkinitcpio.d y /etc/mkinitcpio.conf.d del squashfs, que
# unpackfs copia al destino. aarch64: scripts/apply-aarch64-mkinitcpio.sh
# aparta el preset x86 y customize_airootfs.sh instala el de ALARM.
LIVE_MKINITCPIO = {
    "x86_64": {
        "etc/mkinitcpio.d/linux.preset": "archiso/airootfs/etc/mkinitcpio.d/linux.preset",
        "etc/mkinitcpio.conf.d/archiso.conf": "archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf",
    },
    "i686": {
        "etc/mkinitcpio.d/linux.preset": "archiso/airootfs/etc/mkinitcpio.d/linux.preset",
        "etc/mkinitcpio.conf.d/archiso.conf": "archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf",
    },
    "aarch64": {
        "etc/mkinitcpio.d/linux-aarch64.preset": "archiso/mkinitcpio/aarch64/linux-aarch64.preset",
        "etc/mkinitcpio.conf.d/archiso.conf": "archiso/mkinitcpio/aarch64/archiso.conf",
    },
}


def live_kernel_presets(arch: str) -> dict[str, str]:
    """{etc/mkinitcpio.d/<kernel>.preset: texto} que customize_airootfs.sh
    escribe en el Live (heredoc) para un kernel que alguna edición con
    instalador de `arch` instala: el preset del paquete linux-churrosvyper
    pasa a la forma archiso y Calamares lo encuentra en el destino."""
    text = testlib.read_text(testlib.ROOT / "branding/customize_airootfs.sh")
    listed = set().union(*(testlib.packages(item) for item in testlib.EDITIONS
                           if item.arch == arch and item.installer))
    found = {}
    for _end, name, body in re.findall(
            r"cat\s+<<-?\s*'?(\w+)'?\s*>\s*/etc/mkinitcpio\.d/([\w.+-]+\.preset)\n(.*?)\n\1\n", text, re.S):
        if name.removesuffix(".preset") in listed:
            found[f"etc/mkinitcpio.d/{name}"] = body + "\n"
    return found


# /etc/mkinitcpio.conf del paquete mkinitcpio (no está en el airootfs).
STOCK_MKINITCPIO_CONF = (
    "MODULES=()\nBINARIES=()\nFILES=()\n"
    "HOOKS=(base udev autodetect microcode modconf kms keyboard keymap consolefont block filesystems fsck)\n"
)

# systemctl <action> <unit> (services-systemd/main.py pasa la acción tal cual).
UNIT_ACTIONS = frozenset({"enable", "disable", "mask", "unmask", "reenable", "preset"})
UNIT_NAME = re.compile(
    r"[A-Za-z0-9:_.\\-]+(?:@[A-Za-z0-9:_.\\-]*)?"
    r"\.(?:service|socket|target|device|mount|automount|swap|timer|path|slice|scope)"
)
# displaymanager/main.py: clase DM<nombre> y su `executable` en /usr/bin.
DISPLAY_MANAGERS = {
    "greetd": "greetd", "sddm": "sddm", "lightdm": "lightdm", "gdm": "gdm",
    "lxdm": "lxdm", "slim": "slim", "mdm": "mdm", "plasmalogin": "plasmalogin",
    "sysconfig": None,
}
# Grupos que crean filesystem y systemd en cualquier Arch. Solo hacen falta
# para entradas `must_exist: true` (las demás las crea CreateUserJob).
ARCH_BASE_GROUPS = frozenset({
    "root", "bin", "daemon", "sys", "adm", "tty", "disk", "lp", "mem", "kmem",
    "wheel", "ftp", "mail", "uucp", "log", "utmp", "locate", "rfkill", "smmsp",
    "proc", "http", "games", "lock", "uuidd", "dbus", "network", "video",
    "audio", "optical", "floppy", "storage", "scanner", "input", "power",
    "nobody", "users", "systemd-journal", "kvm", "render", "sgx",
})
# Hooks de mkinitcpio -> paquete que instala /usr/lib/initcpio/install/<hook>.
# Un hook que no existe hace que mkinitcpio salga con 1 (functions,
# run_build_hook) y el trabajo initcpio falla.
INITCPIO_HOOKS = {
    **{hook: "mkinitcpio" for hook in (
        "base", "udev", "autodetect", "microcode", "modconf", "kms", "keyboard",
        "keymap", "consolefont", "block", "filesystems", "fsck", "resume",
        "systemd", "sd-vconsole",
    )},
    "plymouth": "plymouth", "lvm2": "lvm2", "encrypt": "cryptsetup", "mdadm_udev": "mdadm",
}


# ----------------------------------------------------------------------- YAML

@lru_cache(maxsize=None)
def strict_loader():
    """SafeLoader que rechaza claves duplicadas.

    yaml-cpp y PyYAML se quedan con una de las dos sin decir nada; en un
    fichero que se edita a mano una clave repetida siempre es un error.
    """
    import yaml

    class StrictLoader(yaml.SafeLoader):
        pass

    def construct_mapping(loader, node, deep=False):
        loader.flatten_mapping(node)
        seen = set()
        for key_node, _value in node.value:
            key = loader.construct_object(key_node, deep=True)
            try:
                duplicated = key in seen
            except TypeError:
                continue
            if duplicated:
                raise yaml.constructor.ConstructorError(
                    "al leer un mapa", node.start_mark, f"clave duplicada {key!r}", key_node.start_mark)
            seen.add(key)
        return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)

    StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping)
    return StrictLoader


@lru_cache(maxsize=None)
def compose(path: Path):
    """(nodo, error): el árbol YAML de `path`, o el error de sintaxis."""
    import yaml
    try:
        return yaml.compose(testlib.read_text(path), Loader=yaml.SafeLoader), None
    except yaml.YAMLError as error:
        return None, " ".join(str(error).split())


def duplicate_keys(node, prefix: str = "") -> list[str]:
    """Claves repetidas en cualquier mapa del árbol ('script[].timeout')."""
    import yaml
    found = []
    if isinstance(node, yaml.MappingNode):
        seen = set()
        for key_node, value in node.value:
            name = key_node.value if isinstance(key_node, yaml.ScalarNode) else "?"
            if name in seen:
                found.append(prefix + name)
            seen.add(name)
            found += duplicate_keys(value, f"{prefix}{name}.")
    elif isinstance(node, yaml.SequenceNode):
        for item in node.value:
            found += duplicate_keys(item, prefix.rstrip(".") + "[].")
    return found


TRUE_SCALAR = re.compile(r"(true|True|TRUE|on|On|ON)")
FALSE_SCALAR = re.compile(r"(false|False|FALSE|off|Off|OFF)")
INT_SCALAR = re.compile(r"[-+]?\d+")
FLOAT_SCALAR = re.compile(r"[-+]?\d*\.?\d+")


def to_calamares(node):
    """El nodo como lo ve Calamares (Calamares::YAML::toVariant, utils/Yaml.cpp).

    Un escalar es bool solo si es true/on (o false/off) en cualquier estilo,
    aunque vaya entre comillas; `yes`/`no` se quedan en texto. Con claves
    repetidas gana la última, como QVariantMap::insert.
    """
    import yaml
    if isinstance(node, yaml.MappingNode):
        return {key.value: to_calamares(value) for key, value in node.value}
    if isinstance(node, yaml.SequenceNode):
        return [to_calamares(item) for item in node.value]
    if node.tag == "tag:yaml.org,2002:null":
        return None
    text = node.value
    if TRUE_SCALAR.fullmatch(text):
        return True
    if FALSE_SCALAR.fullmatch(text):
        return False
    if INT_SCALAR.fullmatch(text):
        return int(text)
    if FLOAT_SCALAR.fullmatch(text):
        return float(text)
    return text


def raw_scalar(mapping_node, key: str) -> str | None:
    import yaml
    for key_node, value in getattr(mapping_node, "value", []):
        if key_node.value == key and isinstance(value, yaml.ScalarNode):
            return value.value
    return None


def yaml_cpp_bool(text: str) -> bool | None:
    """convert<bool>::decode de yaml-cpp (requireBool de Settings.cpp)."""
    if text not in (text.lower(), text.upper(), text.capitalize()):
        return None
    return {"y": True, "yes": True, "true": True, "on": True,
            "n": False, "no": False, "false": False, "off": False}.get(text.lower())


def calamares_yaml_files() -> list[Path]:
    files = [SETTINGS]
    files += sorted(MODULES.glob("*.conf")) + sorted(MODULES.glob("*.yaml"))
    files += sorted(MODULES.glob("*/*.conf"))
    files += sorted(BRANDING.glob("*/branding.desc"))
    files += sorted((CALAMARES / "preview").glob("*.conf"))
    return files


def module_files(arch: str) -> dict[str, Path]:
    """/etc/calamares/modules de la ISO de `arch`, como lo deja apply-calamares.sh."""
    files = {path.name: path for path in sorted(MODULES.glob("*.conf"))}
    files.update({path.name: path for path in sorted(MODULES.glob("*.yaml"))})
    overlay = MODULES / arch
    if overlay.is_dir():
        files.update({path.name: path for path in sorted(overlay.glob("*.conf"))})
    return files


def crel(path: Path) -> str:
    """Ruta relativa a installer/calamares ('modules/x.conf'), para ids y mensajes."""
    return str(path.relative_to(CALAMARES)) if path.is_relative_to(CALAMARES) else testlib.rel(path)


def split_key(key: str) -> tuple[str, str] | None:
    """InstanceKey::fromString: 'm' -> (m, m), 'm@id' -> (m, id)."""
    parts = key.split("@")
    if len(parts) > 2 or not all(parts):
        return None
    return parts[0], parts[-1]


# ------------------------------------------------------------------- comandos

def command_entries(script) -> list[tuple[str | None, object]]:
    """(comando, entrada) de un `script` de shellprocess (CommandList.cpp).

    Un texto es un comando; un mapa necesita `command` no vacío; lo demás
    ("Bad CommandList element") se descarta. comando=None marca la entrada
    que Calamares tira.
    """
    if isinstance(script, (str, dict)):
        script = [script]
    if not isinstance(script, list):
        return []
    entries = []
    for item in script:
        if isinstance(item, str):
            entries.append((item, item))
        elif isinstance(item, dict) and isinstance(item.get("command"), str) and item["command"]:
            entries.append((item["command"], item))
        else:
            entries.append((None, item))
    return entries


IDENTIFIER = re.compile(r"[A-Za-z0-9_]*")


def calamares_macros(command: str) -> list[str]:
    """Variables que Calamares intenta expandir en `command`.

    Port de KMacroExpanderBase::expandMacrosShellQuote (kcoreaddons,
    kmacroexpander_unix.cpp) con KWordMacroExpander('$'): `$NOMBRE` y
    `${...}` se expanden en cualquier sitio, también entre comillas simples
    (por eso awk '{print $1}' falla); `$$` es un `$` literal; `\\$` fuera de
    comillas simples no se toca; un `)` o `}` sin pareja corta el análisis.
    """
    names: list[str] = []
    text = command
    stack: list[tuple[str, bool]] = []
    saves: list[tuple[str, int]] = []
    state = ("noquote", False)
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char == "$" and pos + 1 < len(text):
            following = text[pos + 1]
            length = 0
            if following == "$":
                length = 2
            elif following == "{":
                end = text.find("}", pos + 2)
                if end > pos + 2:
                    names.append(text[pos + 2:end])
                    length = end - pos + 1
            else:
                name = IDENTIFIER.match(text, pos + 1).group(0)
                if name:
                    names.append(name)
                    length = len(name) + 1
            if length:
                pos += length
                continue
        current, dquote = state
        if current == "singlequote":
            if char == "'":
                state = stack.pop()
        elif char == "\\":
            pos += 2
            continue
        elif current == "dollarquote":
            if char == "'":
                state = stack.pop()
        elif char == "$":
            pos += 1
            following = text[pos] if pos < len(text) else ""
            if following == "(":
                stack.append(state)
                if text[pos + 1:pos + 2] == "(":
                    saves.append((text, pos + 2))
                    state = ("math", dquote)
                    pos += 2
                    continue
                state = ("paren", False)
            elif following == "{":
                stack.append(state)
                state = ("subst", dquote)
            elif not dquote and following == "'":
                stack.append(state)
                state = ("dollarquote", dquote)
            elif not dquote and following == '"':
                stack.append(state)
                state = ("doublequote", True)
        elif char == "`":
            end = pos + 1
            while end < len(text) and text[end] != "`":
                end += 2 if text[end] == "\\" else 1
            if end >= len(text):
                break
            text = text[:pos] + "$( " + text[pos + 1:end] + ")" + text[end + 1:]
            stack.append(state)
            state = ("paren", False)
            pos += 3
            continue
        elif current == "doublequote":
            if char == '"':
                state = stack.pop()
        elif char == "'":
            if not dquote:
                stack.append(state)
                state = ("singlequote", dquote)
        elif char == '"':
            if not dquote:
                stack.append(state)
                state = ("doublequote", True)
        elif current == "subst":
            if char == "}":
                state = stack.pop()
        elif char == ")":
            if current == "math":
                if text[pos + 1:pos + 2] == ")":
                    state = stack.pop()
                    pos += 2
                else:
                    text, pos = saves.pop()
                    stack.append(("paren", False))
                    state = ("paren", False)
                continue
            if current == "paren":
                state = stack.pop()
            else:
                break
        elif char == "}":
            if current == "group":
                state = stack.pop()
            else:
                break
        elif char == "(":
            stack.append(state)
            state = ("paren", dquote)
        elif char == "{":
            stack.append(state)
            state = ("group", dquote)
        pos += 1
    return list(dict.fromkeys(names))


def unknown_macros(command: str) -> list[str]:
    return [name for name in calamares_macros(command)
            if name not in CALAMARES_VARIABLES and not re.fullmatch(r"gs\[[^\]]+\]", name)]


def expand_for_shell(command: str, root: str) -> str:
    """El comando tras la expansión de Calamares (ROOT, USER, LANG, `$$`)."""
    values = {"ROOT": root, "USER": "usuario", "LANG": "es_ES.UTF-8"}

    def replace(match):
        if match.group(0) == "$$":
            return "\\$"
        name = match.group(1) or match.group(2)
        if name in values:
            return values[name]
        if name.startswith("gs["):
            return "valor"
        return match.group(0)

    return re.sub(r"\$\$|\$\{([^}]*)\}|\$([A-Za-z0-9_]+)", replace, command)


def strip_ignore(command: str) -> tuple[str, bool]:
    """CommandList::run: un '-' inicial ignora el código de salida."""
    return (command[1:], True) if command.startswith("-") else (command, False)


def shell_tokens(command: str, strict: bool = False) -> list[str]:
    """Palabras y operadores de `command`. Con comillas sin cerrar: split()
    (test_3 informa la sintaxis rota), o ValueError si `strict`."""
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError:
        if strict:
            raise
        return command.split()


SEPARATORS = frozenset({";", "&&", "||", "|", "&", "(", ")", ";;", "|&"})


def is_redirection(token: str) -> bool:
    return bool(token) and set(token) <= set("<>&") and token not in SEPARATORS and token != "&"


def simple_commands(command: str) -> list[list[str]]:
    """Palabras de cada comando simple (sin redirecciones ni VAR=x iniciales)."""
    result, words, skip_next = [], [], False
    for token in shell_tokens(command) + [";"]:
        if token in SEPARATORS:
            if words:
                result.append(words)
            words = []
            continue
        if skip_next:
            skip_next = False
            continue
        if is_redirection(token):
            skip_next = True
            continue
        if not words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", token):
            continue
        words.append(token)
    return result


def sed_parts(words: list[str]) -> tuple[list[str], list[str]]:
    """(scripts, ficheros) de una llamada a sed."""
    scripts, files, index = [], [], 1
    explicit = any(word in ("-e", "--expression") or word.startswith("--expression=")
                   or (word.startswith("-e") and len(word) > 2) for word in words[1:])
    while index < len(words):
        word = words[index]
        if word in ("-e", "--expression") and index + 1 < len(words):
            scripts.append(words[index + 1])
            index += 2
            continue
        if word.startswith("--expression="):
            scripts.append(word.split("=", 1)[1])
        elif word.startswith("-e") and len(word) > 2:
            scripts.append(word[2:])
        elif word.startswith("-") and word != "-":
            pass
        elif not explicit and not scripts:
            scripts.append(word)
        else:
            files.append(word)
        index += 1
    return scripts, files


SED_DELETE = re.compile(
    r"(?P<a1>/(?:\\.|[^/\\])*/)\s*(?:,\s*(?P<a2>/(?:\\.|[^/\\])*/|\$|\d+)\s*)?(?P<cmd>[dD])(?![A-Za-z])")


def unanchored_churros_removal(command: str) -> str | None:
    """Motivo si `command` quita [churros] de pacman.conf línea a línea.

    AGENTS.md: borrar las líneas que contienen 'churros' deja `SigLevel =
    Optional TrustAll` y `Server = file:///root/packages` en la sección de
    encima; hay que quitar el bloque desde la cabecera anclada ^\\[churros\\].
    """
    for words in simple_commands(command):
        program = Path(words[0]).name
        if program == "sed":
            scripts, files = sed_parts(words)
            if not any(Path(name).name == "pacman.conf" for name in files):
                continue
            for script in scripts:
                for match in SED_DELETE.finditer(script):
                    if "churros" not in match.group("a1"):
                        continue
                    anchored = match.group("a1").startswith(r"/^\[churros\]")
                    if not (anchored and match.group("a2")):
                        return f"sed '{script}' borra líneas sueltas, no el bloque [churros]"
        elif program == "grep" and any(word.startswith("-") and "v" in word.lstrip("-") for word in words[1:]):
            if any(Path(word).name == "pacman.conf" for word in words[1:]) and any("churros" in word for word in words[1:]):
                return "grep -v quita líneas sueltas, no el bloque [churros]"
    return None


def executed_scripts(command: str) -> list[str]:
    """Rutas absolutas que el comando ejecuta (también `sh /ruta`)."""
    paths = []
    for words in simple_commands(command):
        found = testlib.shell_commands(shlex.join(words))
        for program in found:
            if program.startswith("/"):
                paths.append(program)
            elif program in ("sh", "bash") and program in words:
                rest = [word for word in words[words.index(program) + 1:] if not word.startswith("-")]
                if rest and rest[0].startswith("/"):
                    paths.append(rest[0])
    return paths


class NotSimulable(Exception):
    pass


SAFE_WORD = re.compile(r"[A-Za-z0-9_./*?=:,@%+\-]+")


def sandbox_command(command: str, root: Path) -> str:
    """`command` con cada ruta absoluta dentro de `root`.

    Solo acepta programas de SIMULATION_PROGRAMS y SIMULATION_SCRIPTS: un
    comando desconocido podría tocar el sistema que corre la prueba.
    """
    if re.search(r"\d[<>]", command):
        raise NotSimulable("redirección con descriptor numérico")
    tokens = shell_tokens(command, strict=True)
    out, expect_program, redirect_target = [], True, False
    for token in tokens:
        if token in SEPARATORS:
            out.append(token)
            expect_program = True
            continue
        if is_redirection(token):
            out.append(token)
            redirect_target = True
            continue
        word = token
        if expect_program and not redirect_target:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", word):
                raise NotSimulable(f"asignación {word}")
            if word.startswith("/"):
                if word not in SIMULATION_SCRIPTS:
                    raise NotSimulable(f"script {word}")
            elif word not in SIMULATION_PROGRAMS:
                raise NotSimulable(f"programa {word}")
            expect_program = False
        redirect_target = False
        if REWRITTEN_ROOTS.match(word):
            word = str(root) + word
        out.append(word if SAFE_WORD.fullmatch(word) else shlex.quote(word))
    return " ".join(out)


def run_sandboxed(command: str, root: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C",
           "HOME": str(root), "CHURROS_ROOT": str(root)}
    return subprocess.run(["bash", "-c", command], cwd=root, env=env, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:8]


# ------------------------------------------------------------------- pruebas

class CalamaresConfigTest(unittest.TestCase):

    def setUp(self):
        testlib.require_module(self, "yaml")

    # --------------------------------------------------------- utilidades

    def load(self, path: Path):
        """Contenido de `path` como lo ve Calamares; falla si no se lee."""
        node, error = compose(path)
        if error is not None:
            self.fail(f"{testlib.rel(path)} no es YAML válido (ver test_1_strict_yaml): {error}")
        return {} if node is None else to_calamares(node)

    def settings(self) -> dict:
        data = self.load(SETTINGS)
        if not isinstance(data, dict):
            self.fail(f"{testlib.rel(SETTINGS)} no es un mapa")
        return data

    def instances(self) -> dict[str, dict]:
        found = {}
        for entry in self.settings().get("instances") or []:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                found[entry["id"]] = entry
        return found

    def phases(self) -> list[tuple[str, list[str]]]:
        result = []
        for item in self.settings().get("sequence") or []:
            if isinstance(item, dict) and len(item) == 1:
                action, roster = next(iter(item.items()))
                result.append((action, [str(entry) for entry in roster or []]))
        return result

    def exec_steps(self) -> list[str]:
        return [step for action, roster in self.phases() if action == "exec" for step in roster]

    def config_name(self, key: str) -> str | None:
        """Nombre del .conf que Calamares abre para el paso `key` (o None)."""
        parts = split_key(key)
        if parts is None:
            return None
        module, ident = parts
        if module in NOCONFIG_MODULES:
            return None
        instance = self.instances().get(ident) if module != ident else None
        if instance and instance.get("module") == module and isinstance(instance.get("config"), str) and instance["config"]:
            return instance["config"]
        return f"{module}.conf"

    def shellprocess_conf_instance(self) -> dict[str, str]:
        """{nombre del .conf: id de la instancia shellprocess}."""
        return {entry["config"]: ident for ident, entry in self.instances().items()
                if entry.get("module") == "shellprocess" and isinstance(entry.get("config"), str)}

    # ------------------------------------------------------- 1. YAML estricto

    def test_1_strict_yaml(self):
        """Todo YAML de Calamares carga sin claves duplicadas; los .conf son mapas."""
        import yaml
        category = "calamares-yaml"
        findings = {}
        files = calamares_yaml_files()
        self.assertIn(SETTINGS, files)
        for path in files:
            name = crel(path)
            with self.subTest(fichero=name):
                node, error = compose(path)
                if error is not None:
                    # yaml-cpp también lo rechaza: ModuleFactory devuelve
                    # nullptr y Calamares no arranca ("could not be loaded").
                    findings[f"{category}:{name}:syntax"] = f"{name}: YAML inválido: {error}"
                    continue
                for key in duplicate_keys(node):
                    findings[f"{category}:{name}:duplicate:{key}"] = f"{name}: clave '{key}' repetida"
                try:
                    yaml.load(testlib.read_text(path), Loader=strict_loader())
                except yaml.YAMLError as error:
                    if not duplicate_keys(node):
                        findings[f"{category}:{name}:syntax"] = f"{name}: {' '.join(str(error).split())}"
                # Module::loadConfigurationFile: un .conf que no es un mapa
                # ("Bad module configuration format") se descarta entero.
                if path.suffix in (".conf", ".desc") and not isinstance(node, yaml.MappingNode):
                    findings[f"{category}:{name}:not-a-map"] = f"{name}: la raíz no es un mapa; Calamares lo ignora"
        testlib.assert_findings(self, category, findings)

    # ----------------------------------------------------------- 2. secuencia

    def test_2_sequence(self):
        """settings.conf: instancias, módulos, .conf por arquitectura, orden y vistas."""
        category = "calamares-sequence"
        findings = {}
        settings = self.settings()
        node, _ = compose(SETTINGS)

        for key in settings:
            if key not in SETTINGS_KEYS:
                findings[f"{category}:settings-key:{key}"] = f"settings.conf: clave '{key}' desconocida; Settings.cpp no la lee"
        for key in sorted(SETTINGS_BOOLS):
            raw = raw_scalar(node, key)
            if raw is not None and yaml_cpp_bool(raw) is None:
                findings[f"{category}:bool:{key}"] = f"settings.conf: {key}: '{raw}' no es un booleano de yaml-cpp (Settings no carga)"
        # dont-chroot: true hace que todos los pasos "en el destino" corran en el Live.
        if yaml_cpp_bool(raw_scalar(node, "dont-chroot") or "false"):
            findings[f"{category}:dont-chroot"] = "settings.conf: dont-chroot: true ejecuta los pasos del destino en el sistema Live"

        branding = settings.get("branding")
        desc = BRANDING / str(branding) / "branding.desc"
        if not isinstance(branding, str) or not desc.is_file():
            findings[f"{category}:branding"] = f"settings.conf: branding '{branding}' no tiene {testlib.rel(desc)}"
        else:
            component = self.load(desc).get("componentName")
            if component != branding:
                findings[f"{category}:branding"] = f"{testlib.rel(desc)}: componentName '{component}' != branding '{branding}' de settings.conf"

        # Instancias: exactamente las cinco de AGENTS.md, cada una usada una vez.
        entries = settings.get("instances") or []
        ids = []
        for entry in entries:
            if not isinstance(entry, dict):
                findings[f"{category}:instance-entry"] = f"settings.conf: entrada de instances que no es un mapa: {entry!r}"
                continue
            ident = entry.get("id")
            ids.append(ident)
            for key in entry:
                if key not in INSTANCE_KEYS:
                    findings[f"{category}:instance-key:{ident}:{key}"] = (
                        f"instances[{ident}]: clave '{key}' desconocida (InstanceDescription::fromSettings la ignora)")
            if entry.get("module") != "shellprocess":
                findings[f"{category}:instance-module:{ident}"] = f"instances[{ident}]: module '{entry.get('module')}', se espera shellprocess"
            if not isinstance(entry.get("config"), str) or not entry["config"]:
                findings[f"{category}:instance-config:{ident}"] = (
                    f"instances[{ident}]: sin config; Calamares cae en shellprocess.conf, el ejemplo de upstream")
        for ident in sorted({i for i in ids if ids.count(i) > 1}, key=str):
            findings[f"{category}:instance-duplicate:{ident}"] = f"settings.conf: instancia '{ident}' declarada {ids.count(ident)} veces"
        if set(ids) != set(EXPECTED_DONT_CHROOT):
            findings[f"{category}:instances"] = (
                f"settings.conf: instancias {sorted(map(str, ids))}; AGENTS.md exige exactamente {sorted(EXPECTED_DONT_CHROOT)}")

        phases = []
        for item in settings.get("sequence") or []:
            if not (isinstance(item, dict) and len(item) == 1 and next(iter(item)) in ("show", "exec")):
                findings[f"{category}:phase:{short_hash(repr(item))}"] = f"sequence: '{item!r}' no es un único show: o exec: (Calamares lo salta)"
                continue
            action, roster = next(iter(item.items()))
            if not isinstance(roster, list) or not all(isinstance(entry, str) for entry in roster):
                findings[f"{category}:phase:{action}"] = f"sequence: {action}: la lista tiene entradas que no son texto"
                roster = [entry for entry in roster or [] if isinstance(entry, str)]
            phases.append((action, roster))
        steps = [step for action, roster in phases if action == "exec" for step in roster]
        shown_before = {}
        seen_views: set[str] = set()
        for action, roster in phases:
            if action == "show":
                seen_views.update(roster)
            else:
                for step in roster:
                    shown_before.setdefault(step, set(seen_views))

        declared = {ident: entry for ident, entry in self.instances().items()}
        for key in dict.fromkeys(step for _action, roster in phases for step in roster):
            parts = split_key(key)
            if parts is None:
                findings[f"{category}:bad-key:{key}"] = f"sequence: '{key}' no es módulo ni módulo@instancia"
                continue
            module, ident = parts
            if module not in AVAILABLE_MODULES:
                where = "lo quita el PKGBUILD del AUR" if module in CALAMARES_MODULES else "no existe en Calamares 3.4.2"
                findings[f"{category}:unknown-module:{module}"] = f"sequence: módulo '{module}' {where}; Calamares no arranca"
            if module != ident and (ident not in declared or declared[ident].get("module") != module):
                findings[f"{category}:undeclared:{key}"] = (
                    f"sequence: '{key}' no está en instances; Calamares usa {module}.conf (el de upstream)")
        for ident in EXPECTED_DONT_CHROOT:
            count = steps.count(f"shellprocess@{ident}")
            if ident in declared and count != 1:
                findings[f"{category}:instance-use:{ident}"] = f"exec usa shellprocess@{ident} {count} veces; tiene que ser 1"
        for key in REQUIRED_EXEC:
            if key not in steps:
                findings[f"{category}:missing-step:{key}"] = f"exec no tiene '{key}'"

        # .conf de cada paso, en cada arquitectura (capa modules/<arch>).
        for arch in testlib.ARCHES:
            files = module_files(arch)
            for key in dict.fromkeys(step for _action, roster in phases for step in roster):
                name = self.config_name(key)
                parts = split_key(key)
                if name is None or parts is None or parts[0] not in CALAMARES_MODULES:
                    continue
                if name not in files and name.removesuffix(".conf") not in UPSTREAM_DEFAULT_OK:
                    findings[f"{category}:missing-conf:{arch}:{name}"] = (
                        f"{arch}: '{key}' necesita modules/{name} y no está (Calamares usaría el de upstream o ninguno)")
        # .conf de módulos sin configuración: Calamares nunca los abre.
        for path in sorted(MODULES.glob("*.conf")) + sorted(MODULES.glob("*/*.conf")):
            module = path.stem
            if module in NOCONFIG_MODULES:
                rel = crel(path)
                findings[f"{category}:ignored-conf:{rel}"] = (
                    f"{rel}: el módulo {module} es noconfig en Calamares 3.4.2; este fichero no se lee nunca")
        # shellprocess-*.conf que ninguna instancia usa.
        used = set(self.shellprocess_conf_instance())
        for path in sorted(MODULES.glob("shellprocess-*.conf")) + sorted(MODULES.glob("*/shellprocess-*.conf")):
            if path.name not in used:
                rel = crel(path)
                findings[f"{category}:orphan-conf:{rel}"] = f"{rel}: ninguna instancia de settings.conf lo usa"

        # Orden.
        position = {}
        for index, step in enumerate(steps):
            position.setdefault(step, index)
        for before, after, reason in ORDER:
            if before in position and after in position and position[before] > position[after]:
                findings[f"{category}:order:{before}<{after}"] = f"exec: '{before}' tiene que ir antes que '{after}': {reason}"
        if "unpackfs" in position:
            writers = [step for step in position
                       if step in TARGET_WRITERS or (step.startswith("shellprocess@") and step != "shellprocess@boot-nocow")]
            for step in writers:
                if position[step] < position["unpackfs"]:
                    findings[f"{category}:order:unpackfs<{step}"] = (
                        f"exec: '{step}' escribe en el destino y va antes de unpackfs, que copia el squashfs encima")
        if steps and steps[-1] != "umount":
            findings[f"{category}:last:umount"] = f"exec: el último paso es '{steps[-1]}'; tiene que ser umount"
        if "umount" in steps and steps.index("umount") > 0 and steps[steps.index("umount") - 1] != "shellprocess@post-install":
            findings[f"{category}:before-umount"] = (
                f"exec: antes de umount va '{steps[steps.index('umount') - 1]}'; AGENTS.md exige shellprocess@post-install")

        # Vistas que tienen que mostrarse antes de ejecutar sus trabajos.
        for view in VIEWS_MUST_BE_SHOWN:
            if view in shown_before and view not in shown_before[view]:
                findings[f"{category}:not-shown:{view}"] = (
                    f"'{view}' está en exec pero no en un show anterior: sus trabajos salen vacíos o con valores por defecto")

        # initcpiocfg reescribe HOOKS/MODULES/FILES/BINARIES de
        # /etc/mkinitcpio.conf desde el del Live (initcpiocfg/main.py,
        # write_mkinitcpio_lines; MODULES siempre queda vacío): lo que un
        # shellprocess anterior cambie en esas líneas se pierde.
        if "initcpiocfg" in position:
            conf_instance = self.shellprocess_conf_instance()
            for path in sorted(MODULES.glob("shellprocess-*.conf")) + sorted(MODULES.glob("*/shellprocess-*.conf")):
                ident = conf_instance.get(path.name)
                step = f"shellprocess@{ident}"
                if ident is None or step not in position or position[step] > position["initcpiocfg"]:
                    continue
                data = self.load(path)
                for command, _entry in command_entries(data.get("script") if isinstance(data, dict) else None):
                    if command and re.search(r"(?<![\w.])/etc/mkinitcpio\.conf(?![\w.])", command) \
                            and re.search(r"\b(MODULES|HOOKS|FILES|BINARIES)=", command):
                        rel = crel(path)
                        findings[f"{category}:initcpiocfg-overwrites:{rel}"] = (
                            f"{rel}: '{command}' edita /etc/mkinitcpio.conf antes de initcpiocfg, que reescribe esa línea")
        testlib.assert_findings(self, category, findings)

    # ------------------------------------------------------- 3. shellprocess

    def test_3_shellprocess(self):
        """shellprocess-*.conf: claves, script, sintaxis, variables, dontChroot, rutas y [churros]."""
        testlib.require_tool(self, "bash")
        category = "calamares-shellprocess"
        findings = {}
        conf_instance = self.shellprocess_conf_instance()
        position = {}
        for index, step in enumerate(self.exec_steps()):
            position.setdefault(step, index)
        paths = sorted(MODULES.glob("shellprocess-*.conf")) + sorted(MODULES.glob("*/shellprocess-*.conf"))
        self.assertTrue(paths, "no hay installer/calamares/modules/shellprocess-*.conf")

        for path in paths:
            rel = crel(path)
            prefix = f"{category}:{rel}"
            with self.subTest(fichero=rel):
                data = self.load(path)
                if not isinstance(data, dict):
                    continue  # lo informa test_1_strict_yaml
                for key in data:
                    if key not in SHELLPROCESS_KEYS:
                        findings[f"{prefix}:unknown-key:{key}"] = f"{rel}: clave '{key}' desconocida; ShellProcessJob la ignora"
                # Sin `script`, ShellProcessJob avisa "No script given" en el
                # log y exec() devuelve ok(): el paso entero se salta en silencio.
                entries = command_entries(data.get("script"))
                if "script" not in data or not any(command for command, _ in entries):
                    findings[f"{prefix}:no-script"] = f"{rel}: sin 'script' con comandos; Calamares se salta la instancia sin error"
                timeout = data.get("timeout")
                if timeout is not None and not (isinstance(timeout, int) and not isinstance(timeout, bool) and timeout >= 1):
                    findings[f"{prefix}:timeout"] = f"{rel}: timeout '{timeout}' no es un entero >= 1 (Calamares usa 30)"
                for key in ("verbose", "dontChroot"):
                    if key in data and not isinstance(data[key], bool):
                        findings[f"{prefix}:{key}"] = f"{rel}: {key}: '{data[key]}' no es true/false para Calamares (getBool usa el valor por defecto)"

                ident = conf_instance.get(path.name)
                dont_chroot = data.get("dontChroot") is True
                if ident in EXPECTED_DONT_CHROOT and dont_chroot != EXPECTED_DONT_CHROOT[ident]:
                    findings[f"{prefix}:dontChroot"] = (
                        f"{rel}: dontChroot {str(dont_chroot).lower()}; la instancia {ident} necesita "
                        f"{str(EXPECTED_DONT_CHROOT[ident]).lower()}")
                step = f"shellprocess@{ident}"
                if not dont_chroot and step in position and "unpackfs" in position and position[step] < position["unpackfs"]:
                    findings[f"{prefix}:chroot-before-unpackfs"] = (
                        f"{rel}: corre en chroot antes de unpackfs, cuando el destino no tiene /bin/sh")

                for command, entry in entries:
                    if command is None:
                        findings[f"{prefix}:bad-entry:{short_hash(repr(entry))}"] = (
                            f"{rel}: entrada {entry!r} sin 'command' de texto; CommandList la descarta")
                        continue
                    if isinstance(entry, dict):
                        for key in entry:
                            if key not in COMMAND_KEYS:
                                findings[f"{prefix}:unknown-command-key:{key}"] = f"{rel}: '{key}' en el comando '{command}' no existe"
                        value = entry.get("timeout")
                        if value is not None and not (isinstance(value, int) and not isinstance(value, bool) and value >= 1):
                            findings[f"{prefix}:command-timeout:{short_hash(command)}"] = (
                                f"{rel}: timeout '{value}' de '{command}' no es un entero >= 1")
                    for name in unknown_macros(command):
                        findings[f"{prefix}:undefined-variable:{name}"] = (
                            f"{rel}: '{command}' usa ${name}; Calamares solo expande ROOT, USER, LANG y gs[...] "
                            f"y falla con 'Missing variables' (escribe $$ para un $ literal)")
                    body, _ignored = strip_ignore(command)
                    shell = expand_for_shell(body, "/tmp/calamares-root" if dont_chroot else "/")
                    # Calamares corre cada comando con /bin/sh -c (bash en Arch).
                    result = testlib.run(["bash", "-n", "-c", shell], timeout=10)
                    if result.returncode != 0:
                        findings[f"{prefix}:syntax:{short_hash(command)}"] = (
                            f"{rel}: sintaxis de shell rota en '{command}': {result.stdout.strip()}")
                        continue
                    reason = unanchored_churros_removal(body)
                    if reason:
                        findings[f"{prefix}:unanchored-churros"] = f"{rel}: {reason} (AGENTS.md: usa la eliminación anclada del bloque)"

        # Scripts absolutos: existen en el airootfs y tienen modo ejecutable en
        # file_permissions (mkarchiso copia el airootfs con --no-preserve=mode:
        # el bit de git no llega a la ISO). Por arquitectura con instalador.
        for arch in INSTALLER_ARCHES:
            permissions = testlib.profile(arch)["file_permissions"]
            files = module_files(arch)
            for conf_name in sorted(conf_instance):
                path = files.get(conf_name)
                if path is None:
                    continue
                rel = crel(path)
                data = self.load(path)
                for command, _entry in command_entries(data.get("script") if isinstance(data, dict) else None):
                    if command is None:
                        continue
                    for script in executed_scripts(strip_ignore(expand_for_shell(command, "/"))[0]):
                        if not (testlib.airootfs(script).exists() or script in testlib.generated_paths()):
                            findings[f"{category}:{rel}:missing:{script}"] = (
                                f"{rel}: '{script}' no existe en archiso/airootfs (el '-' esconde el error)"
                                if command.startswith("-") else f"{rel}: '{script}' no existe en archiso/airootfs")
                        elif not testlib.mode_is_executable(permissions.get(script, "")):
                            findings[f"{category}:{rel}:not-executable:{arch}:{script}"] = (
                                f"{rel}: '{script}' no tiene modo 7xx en file_permissions de profiledef.sh ({arch})")
        testlib.assert_findings(self, category, findings)

    # ------------------------------------------------------------ 4. simulación

    def test_4_simulation(self):
        """fix-boot sobre los presets reales y limpieza de [churros] en pacman.conf."""
        testlib.require_tool(self, "bash")
        for tool in ("sed", "awk", "rm", "mv"):
            testlib.require_tool(self, tool)
        category = "calamares-sim"
        findings = {}
        instances = self.instances()
        fixboot_conf = (instances.get("fix-boot") or {}).get("config")
        cleanup_conf = (instances.get("post-install") or {}).get("config")
        self.assertIsInstance(fixboot_conf, str, "settings.conf: la instancia fix-boot no tiene config")
        self.assertIsInstance(cleanup_conf, str, "settings.conf: la instancia post-install no tiene config")

        for arch in testlib.ARCHES:
            files = module_files(arch)
            with self.subTest(simulacion="fix-boot", arch=arch), tempfile.TemporaryDirectory() as tmp:
                findings.update(self.simulate_fixboot(arch, files, fixboot_conf, Path(tmp), category))
            with self.subTest(simulacion="pacman.conf", arch=arch), tempfile.TemporaryDirectory() as tmp:
                findings.update(self.simulate_pacman_cleanup(arch, files, cleanup_conf, Path(tmp), category))
            with self.subTest(simulacion="acceso del Live", arch=arch), tempfile.TemporaryDirectory() as tmp:
                findings.update(self.simulate_live_access_cleanup(arch, files, cleanup_conf, Path(tmp), category))
        testlib.assert_findings(self, category, findings)

    def simulate_live_access_cleanup(self, arch, files, conf_name, root, category):
        """post-install quita el acceso del Live: el sudoers de churros y la cuenta.

        users.sh deja a churros sin contraseña, en wheel y con NOPASSWD: ALL;
        unpackfs copia todo eso al disco y settings.conf no tiene removeuser.
        Si post-install pierde estos comandos, cada instalación trae root sin
        contraseña y la instalación termina "bien" (verify-install solo avisa).
        """
        findings = {}
        prefix = f"{category}:live-access:{arch}"
        users_sh = testlib.read_text(testlib.AIROOTFS / "root/scripts/users.sh")
        dropins = sorted(set(re.findall(r"/etc/sudoers\.d/[\w.-]+", users_sh)))
        self.assertTrue(dropins, "users.sh ya no escribe en /etc/sudoers.d: actualiza esta prueba")
        conf = files.get(conf_name)
        if conf is None:
            self.fail(f"{arch}: falta {conf_name}")
        rel = crel(conf)
        commands = [command for command, _ in command_entries(self.load(conf).get("script")) if command]
        words = [w for command in commands for w in simple_commands(strip_ignore(command)[0])]
        removes_user = any(w[:1] == ["userdel"] and "churros" in w[1:] and {"-r", "--remove"} & set(w[1:])
                           for w in words)
        if not removes_user:
            findings[f"{prefix}:userdel"] = (f"{arch}: {rel} ya no ejecuta 'userdel -r churros': el sistema "
                                             "instalado conserva la cuenta del Live, sin contraseña y en wheel")
        for dropin in dropins:
            target = root / dropin.lstrip("/")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("churros ALL=(ALL:ALL) NOPASSWD: ALL\n")
        touching = [command for command in commands if "/etc/sudoers.d" in command]
        for program, message in self.run_commands(touching, root, rel).items():
            findings[f"{prefix}:command-fails:{program}"] = f"{arch}: {rel}: {message}"
        for dropin in dropins:
            if (root / dropin.lstrip("/")).exists():
                findings[f"{prefix}:sudoers:{dropin}"] = (
                    f"{arch}: tras post-install sigue {dropin} (NOPASSWD: ALL del Live) en el sistema instalado")
        return findings

    def run_commands(self, commands: list[str], root: Path, label: str) -> dict[str, str]:
        """Ejecuta los comandos con la semántica de CommandList en `root`."""
        failures = {}
        for command in commands:
            body, ignored = strip_ignore(expand_for_shell(command, "/"))
            words = simple_commands(body)
            program = Path(words[0][0]).name if words else "?"
            try:
                sandboxed = sandbox_command(body, root)
            except NotSimulable as error:
                self.fail(f"{label}: la simulación no sabe ejecutar '{command}' ({error}); "
                          "añade el programa a SIMULATION_PROGRAMS si no toca nada fuera de las rutas reescritas")
            except ValueError as error:
                # /bin/sh tampoco lo entiende: el comando falla.
                if not ignored:
                    failures[program] = f"'{command}': sintaxis de shell rota ({error})"
                continue
            result = run_sandboxed(sandboxed, root)
            if result.returncode != 0 and not ignored:
                failures[program] = f"'{command}' sale con {result.returncode}: {result.stdout.strip()}"
        return failures

    def simulate_fixboot(self, arch, files, conf_name, root, category):
        findings = {}
        prefix = f"{category}:fix-boot:{arch}"
        conf = files.get(conf_name)
        unpack = files.get("unpackfs.conf")
        if conf is None or unpack is None:
            self.fail(f"{arch}: falta {conf_name} o unpackfs.conf en modules/")
        # Destino tras unpackfs: el squashfs (mkarchiso vacía /boot en
        # _cleanup_pacstrap_dir) más los ficheros sueltos de unpackfs.conf.
        for target, source in LIVE_MKINITCPIO[arch].items():
            (root / target).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(testlib.ROOT / source, root / target)
        for target, body in live_kernel_presets(arch).items():
            (root / target).parent.mkdir(parents=True, exist_ok=True)
            (root / target).write_text(body)
        (root / "etc/mkinitcpio.conf").write_text(STOCK_MKINITCPIO_CONF)
        (root / "boot").mkdir(parents=True, exist_ok=True)
        kernel_dest = initramfs_dest = None
        for entry in self.load(unpack).get("unpack") or []:
            if isinstance(entry, dict) and entry.get("sourcefs") == "file" and str(entry.get("destination", "")).startswith("/"):
                dest = entry["destination"]
                (root / dest.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
                (root / dest.lstrip("/")).write_text(f"copia de {entry.get('source')}\n")
                name = Path(dest).name
                if name.startswith("vmlinuz"):
                    kernel_dest = dest
                elif name.startswith("initramfs") and name.endswith(".img"):
                    initramfs_dest = dest
        self.assertIsNotNone(initramfs_dest, f"{arch}: unpackfs.conf no copia ningún initramfs-*.img a /boot")
        for script in SIMULATION_SCRIPTS:
            if testlib.airootfs(script).exists():
                (root / script.lstrip("/")).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(testlib.airootfs(script), root / script.lstrip("/"))
                (root / script.lstrip("/")).chmod(0o755)

        data = self.load(conf)
        commands = [command for command, _ in command_entries(data.get("script")) if command]
        rel = crel(conf)
        for program, message in self.run_commands(commands, root, rel).items():
            findings[f"{prefix}:command-fails:{program}"] = (
                f"{arch}: {rel}: {message}; el trabajo fix-boot falla y la instalación se aborta")

        # mkinitcpio -P (initcpio, después) procesa cada preset así
        # (mkinitcpio, process_preset).
        presets = sorted((root / "etc/mkinitcpio.d").glob("*.preset"))
        if not presets:
            findings[f"{prefix}:no-preset"] = f"{arch}: no queda ningún preset en /etc/mkinitcpio.d"
        evaluate = (
            '. "$1" || exit 1\n'
            'for p in "${PRESETS[@]}"; do\n'
            '  k="${p}_kver"; c="${p}_config"; i="${p}_image"\n'
            '  printf "%s\\t%s\\t%s\\t%s\\n" "$p" "${!k:-$ALL_kver}" "${!c:-$ALL_config}" "${!i}"\n'
            'done\n'
        )
        for preset in presets:
            name = preset.name
            result = testlib.run(["bash", "-c", evaluate, "preset", str(preset)], timeout=10)
            rows = [line.split("\t") for line in result.stdout.splitlines() if line.count("\t") == 3]
            if result.returncode != 0 or [row[0] for row in rows] != ["default"]:
                findings[f"{prefix}:presets:{name}"] = (
                    f"{arch}: tras fix-boot {name} tiene PRESETS={[row[0] for row in rows]}; se espera ('default'):\n"
                    f"{testlib.read_text(preset)}")
            live = [line for line in testlib.read_text(preset).splitlines()
                    if "archiso" in line and not line.lstrip().startswith("#")]
            if live:
                findings[f"{prefix}:archiso-left:{name}"] = f"{arch}: {name} sigue nombrando archiso tras fix-boot: {live}"
            for _p, kver, config, image in rows:
                if config and config != "/etc/mkinitcpio.conf":
                    findings[f"{prefix}:config:{name}"] = f"{arch}: {name}: config '{config}', se espera /etc/mkinitcpio.conf"
                if not kver:
                    findings[f"{prefix}:kver-missing:{name}"] = f"{arch}: {name} no define el kernel (ALL_kver/default_kver)"
                elif kver.startswith("/") and not (root / kver.lstrip("/")).exists():
                    findings[f"{prefix}:kver-missing:{name}"] = (
                        f"{arch}: {name}: el kernel '{kver}' no existe en el destino (unpackfs copia "
                        f"{kernel_dest} y mkarchiso vacía /boot del squashfs): mkinitcpio -P falla")
                if image != initramfs_dest:
                    findings[f"{prefix}:image:{name}"] = (
                        f"{arch}: {name}: default_image '{image}' != '{initramfs_dest}' de unpackfs.conf: "
                        "GRUB arrancaría el initramfs de archiso copiado del ISO")
        confd = root / "etc/mkinitcpio.conf.d"
        for drop_in in sorted(confd.glob("*.conf")) if confd.is_dir() else []:
            if "archiso" in testlib.read_text(drop_in):
                findings[f"{prefix}:confd-archiso:{drop_in.name}"] = (
                    f"{arch}: /etc/mkinitcpio.conf.d/{drop_in.name} sigue con los hooks de archiso tras fix-boot")
        return findings

    def simulate_pacman_cleanup(self, arch, files, conf_name, root, category):
        """post-install sobre pacman.<arch>.conf: fuera el bloque [churros] y nada más."""
        findings = {}
        prefix = f"{category}:pacman-conf:{arch}"
        source = testlib.ROOT / f"archiso/pacman.{arch}.conf"
        conf = files.get(conf_name)
        if conf is None or not source.exists():
            self.fail(f"{arch}: falta {conf_name} o {testlib.rel(source)}")
        (root / "etc").mkdir(parents=True)
        (root / "tmp").mkdir()
        original = testlib.read_text(source)
        (root / "etc/pacman.conf").write_text(original)
        data = self.load(conf)
        commands = [command for command, _ in command_entries(data.get("script")) if command
                    and any(Path(word).name == "pacman.conf" for words in simple_commands(strip_ignore(command)[0]) for word in words)]
        rel = crel(conf)
        for program, message in self.run_commands(commands, root, rel).items():
            findings[f"{prefix}:command-fails:{program}"] = f"{arch}: {rel}: {message}"
        result = testlib.read_text(root / "etc/pacman.conf")

        def sections(text):
            found, current = {}, None
            for line in text.splitlines():
                if re.fullmatch(r"\[[^\]]+\]", line.strip()):
                    current = line.strip()
                    found.setdefault(current, [])
                elif current is not None:
                    found[current].append(line)
            return found

        before, after = sections(original), sections(result)
        if "[churros]" not in before:
            return findings
        if "[churros]" in after:
            findings[f"{prefix}:churros-left"] = f"{arch}: la sección [churros] sigue en pacman.conf tras post-install"
        leaked = [line for line in result.splitlines() if "/root/packages" in line and not line.lstrip().startswith("#")]
        if leaked:
            findings[f"{prefix}:server-left"] = f"{arch}: tras post-install quedan líneas del repo local: {leaked}"
        if after.get("[options]") != before.get("[options]"):
            findings[f"{prefix}:options-changed"] = (
                f"{arch}: la limpieza cambió [options] (SigLevel global): {after.get('[options]')}")
        for section in before:
            if section != "[churros]" and section not in after:
                findings[f"{prefix}:section-lost:{section}"] = f"{arch}: la limpieza borró la sección {section}"
        return findings

    # -------------------------------------------------------- 5. referencias

    def test_6_welcome_requirements(self):
        """welcome.conf no puede rechazar un equipo de 2 GB.

        Con 2 GB físicos MemTotal ronda 1.7-1.9 GiB (memoria reservada por el
        firmware y la gráfica integrada). Si `ram` está en `required` o
        `requiredRam` pasa de ese valor, Calamares deja "Siguiente" desactivado.
        """
        category = "calamares-welcome"
        findings = {}
        requirements = self.load(MODULES / "welcome.conf").get("requirements") or {}
        required = requirements.get("required") or []
        if "ram" in required:
            findings[f"{category}:ram-required"] = (
                "welcome.conf: 'ram' en required bloquea la instalación cuando falta RAM; "
                "déjalo solo en check (aviso)")
        ram = requirements.get("requiredRam")
        if not isinstance(ram, (int, float)) or ram > MIN_SUPPORTED_RAM_GIB:
            findings[f"{category}:required-ram"] = (
                f"welcome.conf: requiredRam={ram!r} supera {MIN_SUPPORTED_RAM_GIB} GiB, "
                "lo que ve un equipo de 2 GB físicos")
        if "storage" not in required:
            findings[f"{category}:storage-not-required"] = (
                "welcome.conf: 'storage' tiene que seguir en required (sin disco no hay instalación)")
        testlib.assert_findings(self, category, findings)

    def test_5_cross_references(self):
        """services-systemd, displaymanager, users, initcpiocfg y netinstall contra las ediciones."""
        category = "calamares-xref"
        findings = {}
        providers = testlib.providers()["units"]
        unknown_units = []

        services = self.load(MODULES / "services-systemd.conf")
        for unit in services.get("units") or []:
            if isinstance(unit, str):
                unit = {"name": unit}
            if not isinstance(unit, dict) or not isinstance(unit.get("name"), str):
                findings[f"{category}:unit-entry:{short_hash(repr(unit))}"] = f"services-systemd.conf: entrada sin name: {unit!r}"
                continue
            name, action = unit["name"], unit.get("action", "enable")
            mandatory = unit.get("mandatory", False) is True
            if action not in UNIT_ACTIONS:
                findings[f"{category}:unit-action:{name}"] = f"services-systemd.conf: '{action} {name}': systemctl no tiene esa acción"
            if not UNIT_NAME.fullmatch(name):
                findings[f"{category}:unit-name:{name}"] = f"services-systemd.conf: '{name}' no es un nombre de unidad válido"
                continue
            # Una unidad obligatoria que no existe aborta la instalación
            # (services-systemd/main.py devuelve error si mandatory).
            if not (mandatory and action in ("enable", "reenable", "unmask")):
                continue
            template = re.sub(r"@[^.]*\.", "@.", name)
            if any((testlib.AIROOTFS / base / candidate).exists()
                   for base in ("etc/systemd/system", "usr/lib/systemd/system") for candidate in (name, template)):
                continue
            package = providers.get(name) or providers.get(template)
            if package is None:
                unknown_units.append(name)
                continue
            for item in INSTALLER_EDITIONS:
                if package not in testlib.installed(item):
                    findings[f"{category}:unit:{name}:{item.id}"] = (
                        f"{item.id}: services-systemd activa {name} (obligatoria) pero '{package}' no está en {item.package_list}")

        dm_conf = self.load(MODULES / "displaymanager.conf")
        managers = dm_conf.get("displaymanagers") or []
        for manager in managers:
            if manager not in DISPLAY_MANAGERS:
                findings[f"{category}:dm:{manager}"] = f"displaymanager.conf: '{manager}' no es un gestor que conozca el módulo"
                continue
            executable = DISPLAY_MANAGERS[manager]
            for item in INSTALLER_EDITIONS:
                if executable and not testlib.resolve_command(executable, item).ok:
                    # have_dm() falso: el módulo lo quita de la lista y termina
                    # "bien" sin configurar nada.
                    findings[f"{category}:dm-missing:{manager}:{item.id}"] = (
                        f"{item.id}: displaymanager.conf usa {manager} y no está instalado")
        desktop = dm_conf.get("defaultDesktopEnvironment") or {}
        if isinstance(desktop, dict) and desktop.get("executable"):
            for item in INSTALLER_EDITIONS:
                resolution = testlib.resolve_command(str(desktop["executable"]), item)
                if not resolution.ok:
                    findings[f"{category}:de-exec:{item.id}"] = (
                        f"{item.id}: defaultDesktopEnvironment.executable: {resolution.how}")

        users = self.load(MODULES / "users.conf")
        shell = (users.get("user") or {}).get("shell", "/bin/bash") if isinstance(users.get("user"), dict) else "/bin/bash"
        for item in INSTALLER_EDITIONS:
            if shell and not testlib.resolve_command(str(shell), item).ok:
                findings[f"{category}:users-shell:{item.id}"] = (
                    f"{item.id}: users.conf crea la cuenta con shell {shell}, que no está instalado: no puede iniciar sesión")
        groups = {}
        for group in users.get("defaultGroups") or []:
            if isinstance(group, str):
                groups[group] = {}
            elif isinstance(group, dict) and isinstance(group.get("name"), str):
                groups[group["name"]] = group
        for name, group in groups.items():
            if group.get("must_exist") is True and name not in ARCH_BASE_GROUPS:
                findings[f"{category}:group:{name}"] = (
                    f"users.conf: el grupo {name} es must_exist y Arch no lo trae: CreateUserJob falla")
        sudoers = users.get("sudoersGroup")
        if sudoers:
            if sudoers not in groups:
                findings[f"{category}:sudoers-group"] = f"users.conf: sudoersGroup '{sudoers}' no está en defaultGroups: el usuario no puede usar sudo"
            for item in INSTALLER_EDITIONS:
                if not testlib.resolve_command("sudo", item).ok:
                    findings[f"{category}:sudo:{item.id}"] = (
                        f"{item.id}: users.conf da sudo al grupo {sudoers} pero sudo no está en {item.package_list}")

        hooks = (self.load(MODULES / "initcpiocfg.conf").get("hooks") or {})
        for hook in [*(hooks.get("prepend") or []), *(hooks.get("append") or [])]:
            package = INITCPIO_HOOKS.get(hook)
            if package is None:
                findings[f"{category}:initcpio-hook-unknown:{hook}"] = (
                    f"initcpiocfg.conf: hook '{hook}' sin paquete conocido; añádelo a INITCPIO_HOOKS si existe")
                continue
            for item in INSTALLER_EDITIONS:
                if package not in testlib.installed(item):
                    findings[f"{category}:initcpio-hook:{hook}:{item.id}"] = (
                        f"{item.id}: initcpiocfg añade el hook {hook} y '{package}' no está en {item.package_list}: "
                        "mkinitcpio sale con error y el trabajo initcpio falla")

        # netinstall: solo cuenta si está en la secuencia (hoy no lo está).
        if any(split_key(step) and split_key(step)[0] == "netinstall" for _a, roster in self.phases() for step in roster):
            netinstall = self.load(MODULES / "netinstall.yaml")
            groups_list = netinstall.get("groups", []) if isinstance(netinstall, dict) else netinstall
            names = set()

            def walk(items):
                for group in items or []:
                    if isinstance(group, dict):
                        for package in group.get("packages") or []:
                            names.add(package.get("name") if isinstance(package, dict) else package)
                        walk(group.get("subgroups"))

            walk(groups_list)
            listed = set().union(*(testlib.packages(item) for item in INSTALLER_EDITIONS))
            for package in sorted(name for name in names if isinstance(name, str)):
                if package not in testlib.local_packages() and package not in listed:
                    findings[f"{category}:netinstall:{package}"] = (
                        f"netinstall.yaml: {package} no está en el repo local ni en ninguna lista de paquetes")
        testlib.assert_findings(self, category, findings)
        if unknown_units:
            with self.subTest("unidades obligatorias sin proveedor"):
                self.skipTest("sin entrada en tests/unit_providers.toml: " + ", ".join(sorted(unknown_units)))


if __name__ == "__main__":
    unittest.main()
