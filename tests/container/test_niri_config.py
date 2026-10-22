"""Configs de niri, Noctalia y .desktop validados por sus propios programas.

Corre en el contenedor de build (Containerfile, Arch Linux) con
`./churros test --container`, como test_arch_repos. Fuera de él el módulo se
salta, también en modo estricto. Instala con pacman (el contenedor es
desechable) niri, noctalia, desktop-file-utils y python-yaml, y comprueba:

  - `niri validate` sobre cada niri/config.kdl del airootfs (el del skel y la
    copia de /usr/share/churros/defaults) y sobre el config que deja el
    instalador: los comandos de los shellprocess de Calamares que tocan
    .config/niri/config.kdl, sacados de sus .conf (con el overlay de cada
    arquitectura) y aplicados en el orden de exec de settings.conf a una
    copia. niri rechaza nodos desconocidos y binds sin acción, cosas que un
    parser de KDL da por buenas, y el niri de Arch cambia de sintaxis sin que
    cambie el repo.
  - `noctalia config validate` sobre cada config de Noctalia del airootfs y
    sobre el del Live: el del skel más los .toml que root/scripts/*.sh
    escriben en ~/.config/noctalia (live.toml de desktop.sh). Cuentan los
    errores y los avisos de sección, ajuste o valor desconocidos (Noctalia
    los ignora al cargar); un tipo equivocado no lo detecta noctalia.
  - `desktop-file-validate` (errores, no avisos ni pistas) sobre cada
    .desktop del repo: una clave mal escrita o un booleano inválido hacen
    que GLib/garcon ignoren la entrada.

Lo que escribe churros-settings (rust/preferences: niri_config.rs,
window_rules_service.rs, keyboard.rs) no se valida aquí: compilar
preferences necesita GTK y es trabajo de ./churros rust.
"""
from __future__ import annotations

from functools import lru_cache
import importlib
import os
from pathlib import Path
import re
import shlex
import shutil
import tempfile
import unittest

from tests import testlib

SUDO = [] if os.geteuid() == 0 else ["sudo", "-n"]
PACKAGES = ("niri", "noctalia", "desktop-file-utils", "python-yaml")
NIRI_CONFIG = re.compile(r"(?<!\S)\S*/\.config/niri/config\.kdl(?!\S)")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
WORK: Path | None = None


def setUpModule():
    global WORK
    if not Path("/etc/arch-release").exists():
        raise unittest.SkipTest("solo corre en el contenedor Arch de build (no hay /etc/arch-release)")
    if os.environ.get("CHURROS_IN_CONTAINER") != "1":
        raise unittest.SkipTest("solo corre dentro del contenedor de build (./churros test --container; CHURROS_IN_CONTAINER != 1)")
    WORK = Path(tempfile.mkdtemp(prefix="churros-configs-"))


def tearDownModule():
    if WORK is not None:
        shutil.rmtree(WORK, ignore_errors=True)


@lru_cache(maxsize=None)
def install_error() -> str | None:
    """Instala PACKAGES; devuelve el error o None.

    Si la base de datos de la imagen es vieja y el mirror ya no tiene esa
    versión, -S falla: entonces -Syu (el contenedor es desechable).
    """
    result = None
    for operation in ("-S", "-Syu"):
        result = testlib.run([*SUDO, "pacman", operation, "--needed", "--noconfirm", *PACKAGES], timeout=1800)
        if result.returncode == 0:
            importlib.invalidate_caches()  # python-yaml recién instalado
            return None
    return f"pacman no pudo instalar {' '.join(PACKAGES)}:\n{result.stdout}"


def require_packages(testcase: unittest.TestCase) -> None:
    error = install_error()
    if error:
        testcase.fail(error)


def scratch(name: str) -> Path:
    path = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=WORK))
    for sub in ("home", "config", "state", "cache", "runtime"):
        (path / sub).mkdir(mode=0o700)
    return path


def tool_env(base: Path) -> dict[str, str]:
    """HOME y XDG_* propios: nada del usuario que corre la prueba se cuela."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("XDG_") and key not in {"NIRI_CONFIG", "WAYLAND_DISPLAY", "DISPLAY"}}
    env.update(HOME=str(base / "home"), XDG_CONFIG_HOME=str(base / "config"), XDG_STATE_HOME=str(base / "state"),
               XDG_CACHE_HOME=str(base / "cache"), XDG_RUNTIME_DIR=str(base / "runtime"), NO_COLOR="1")
    return env


def niri_validate(path: Path) -> str | None:
    """Salida de niri validate si rechaza el fichero, o None."""
    result = testlib.run(["niri", "validate", "-c", str(path)], env=tool_env(scratch("niri")))
    return None if result.returncode == 0 else ANSI.sub("", result.stdout).strip()


def airootfs_files(pattern: str) -> list[Path]:
    return [path for path in testlib.repo_files() if path.is_relative_to(testlib.AIROOTFS) and path.match(pattern)]


# ------------------------------------------------------------- instalador

def calamares_conf(arch: str, name: str) -> Path:
    """El .conf que apply-calamares.sh deja en la ISO: el de <arch>/ si existe."""
    modules = testlib.ROOT / "installer/calamares/modules"
    return modules / arch / name if (modules / arch / name).exists() else modules / name


def installer_niri_commands(arch: str) -> list[tuple[str, str]]:
    """(fichero, comando) de los shellprocess que tocan el config de niri, en orden de exec."""
    import yaml
    settings = yaml.safe_load(testlib.read_text(testlib.ROOT / "installer/calamares/settings.conf"))
    configs = {f"{item['module']}@{item['id']}": item.get("config", f"{item['module']}.conf")
               for item in settings.get("instances", [])}
    steps = [step for block in settings.get("sequence", []) for step in block.get("exec", [])]
    found = []
    for step in steps:
        if step.split("@", 1)[0] != "shellprocess":
            continue
        path = calamares_conf(arch, configs.get(step, "shellprocess.conf"))
        script = (yaml.safe_load(testlib.read_text(path)) or {}).get("script", [])
        for entry in [script] if isinstance(script, str) else script:
            command = entry.get("command") if isinstance(entry, dict) else entry
            if isinstance(command, str) and NIRI_CONFIG.search(command):
                found.append((testlib.rel(path), command))
    return found


def apply_installer_commands(commands: list[tuple[str, str]], target: Path) -> list[str]:
    """Ejecuta los comandos sobre `target`; devuelve los fallos.

    La primera ruta .config/niri/config.kdl del comando pasa a ser `target` y
    las demás se quitan: el skel y /home/<usuario> son el mismo fichero en ese
    momento (el módulo users copia /etc/skel antes de shellprocess@post-install).
    El '-' inicial solo hace que Calamares ignore el fallo; aquí un fallo
    significa que la transformación no se aplicó y se informa.
    """
    errors = []
    for source, command in commands:
        seen = []

        def substitute(match: re.Match) -> str:
            seen.append(match.group(0))
            return shlex.quote(str(target)) if len(seen) == 1 else ""

        shell = NIRI_CONFIG.sub(substitute, command.lstrip("-"))
        result = testlib.run(["sh", "-c", shell], cwd=target.parent)
        if result.returncode != 0:
            errors.append(f"{source}: `{command}` falló sobre una copia del config:\n{result.stdout.strip()}")
    return errors


# ------------------------------------------------------------- noctalia

def live_noctalia_files() -> dict[str, str]:
    """{nombre: contenido} de los .toml que los scripts del Live escriben en
    ~/.config/noctalia con un heredoc (desktop.sh: live.toml)."""
    found = {}
    pattern = re.compile(r"cat\s+>\s*\S*/\.config/noctalia/([\w.-]+\.toml)\s*<<-?\s*'?(\w+)'?\n(.*?)\n\s*\2\s*$",
                         re.DOTALL | re.MULTILINE)
    for path in sorted((testlib.AIROOTFS / "root/scripts").glob("*.sh")):
        for name, _, body in pattern.findall(testlib.read_text(path)):
            found[name] = body + "\n"
    return found


def noctalia_validate(base: Path, target: Path | None = None) -> str | None:
    """Salida de noctalia config validate si hay errores o ajustes desconocidos.

    noctalia solo sale con 1 por errores de sintaxis. Una sección, un ajuste o
    un valor de enum desconocidos son avisos ("WARN <fichero>:<l>:<c>: <clave>:
    unknown ...") y Noctalia los ignora al cargar: el ajuste no se aplica (un
    allow_empty_password mal escrito deja el Live sin poder desbloquear).
    """
    cmd = ["noctalia", "config", "validate"] + ([str(target)] if target else [])
    result = testlib.run(cmd, env=tool_env(base))
    output = ANSI.sub("", result.stdout).strip()
    unknown = [line for line in output.splitlines() if re.match(r"WARN\s", line) and ": unknown " in line]
    return output if result.returncode != 0 or unknown else None


# ------------------------------------------------------------------ pruebas

class NiriConfigTest(unittest.TestCase):
    def test_niri_validate_shipped_configs(self):
        require_packages(self)
        configs = airootfs_files("*/niri/config.kdl")
        self.assertIn(testlib.AIROOTFS / "etc/skel/.config/niri/config.kdl", configs, "no se encontró el config de niri del skel")
        findings = {}
        for path in configs:
            error = niri_validate(path)
            if error:
                findings[f"niri-validate:{testlib.rel(path)}"] = f"niri validate rechaza {testlib.rel(path)}:\n{error}"
        testlib.assert_findings(self, "niri-validate", findings)

    def test_niri_validate_installed_config(self):
        """El config.kdl que queda tras shellprocess@post-install sigue siendo válido."""
        require_packages(self)
        testlib.require_module(self, "yaml")
        skel = testlib.AIROOTFS / "etc/skel/.config/niri/config.kdl"
        arches = sorted({item.arch for item in testlib.EDITIONS if item.desktop == "niri" and item.installer})
        findings = {}
        for arch in arches:
            commands = installer_niri_commands(arch)
            if not commands:
                continue
            target = scratch(f"installed-{arch}") / "config.kdl"
            shutil.copyfile(skel, target)
            errors = apply_installer_commands(commands, target)
            error = niri_validate(target)
            if error:
                errors.append(f"niri validate rechaza el config.kdl instalado:\n{error}")
            if errors:
                applied = "\n".join(f"    {source}: {command}" for source, command in commands)
                findings[f"niri-installed:{arch}"] = (
                    f"config de niri del sistema instalado ({arch}), skel más:\n{applied}\n" + "\n".join(errors)
                )
        testlib.assert_findings(self, "niri-installed", findings)


class NoctaliaConfigTest(unittest.TestCase):
    def test_noctalia_config_validate(self):
        require_packages(self)
        directories = sorted({path.parent for path in airootfs_files("*/noctalia/config.toml")})
        skel = testlib.AIROOTFS / "etc/skel/.config/noctalia"
        self.assertIn(skel, directories, "no se encontró el config de Noctalia del skel")
        findings = {}
        for directory in directories:
            error = noctalia_validate(scratch("noctalia"), directory)
            if error:
                findings[f"noctalia-validate:{testlib.rel(directory)}"] = f"noctalia config validate da errores o ajustes desconocidos en {testlib.rel(directory)}:\n{error}"
        # Sesión Live: desktop.sh copia el skel a /home/churros/.config y añade
        # sus .toml. Sin ruta, noctalia valida la unión como al arrancar.
        extra = live_noctalia_files()
        if extra:
            base = scratch("noctalia-live")
            shutil.copytree(skel, base / "config/noctalia")
            for name, body in extra.items():
                (base / "config/noctalia" / name).write_text(body)
            error = noctalia_validate(base)
            if error:
                findings["noctalia-validate:live"] = (
                    f"noctalia config validate da errores o ajustes desconocidos en el config del Live (skel + {', '.join(sorted(extra))} de root/scripts):\n{error}"
                )
        testlib.assert_findings(self, "noctalia-validate", findings)


class DesktopFilesTest(unittest.TestCase):
    def test_desktop_file_validate(self):
        require_packages(self)
        files = [path for path in testlib.repo_files() if path.suffix == ".desktop" and not path.is_symlink()]
        self.assertTrue(files, "no se encontró ningún .desktop")
        findings = {}
        for path in files:
            result = testlib.run(["desktop-file-validate", str(path)])
            if result.returncode != 0:
                errors = [line.split(": ", 1)[-1] for line in result.stdout.splitlines() if ": error: " in line]
                findings[f"desktop-file:{testlib.rel(path)}"] = (
                    f"desktop-file-validate rechaza {testlib.rel(path)}:\n    " + "\n    ".join(errors or [result.stdout.strip()])
                )
        testlib.assert_findings(self, "desktop-file", findings)


if __name__ == "__main__":
    unittest.main()
