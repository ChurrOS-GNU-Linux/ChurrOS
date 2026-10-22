#!/usr/bin/env python3
"""Arranque de las apps GTK en Broadway: ninguna puede morir al abrirse.

cargo test, clippy, la auditoría de la ISO y el arranque en QEMU (que solo
mira la ventana de bienvenida) no ejecutan nunca churros-settings,
churros-control-center ni los popups. Un cambio que compila pero entra en
pánico al construir la ventana (un RefCell prestado dos veces, un unwrap) pasa
todo eso, y en la ISO la app desaparece sin más: el perfil release lleva
panic = "abort".

Esta prueba compila el workspace con el perfil que se despliega (release, el
mismo `cargo build` que scripts/build-rust.sh) y arranca cada binario
desplegado (crates con deploy = true, tests/testlib.py) en un gtk4-broadwayd
privado, dentro de dbus-run-session, con HOME (copia de /etc/skel del
airootfs) y XDG_* temporales. churros-popup arranca una vez por cada nombre de
POPUPS (rust/popups/src/main.rs). Falla si el proceso termina antes de
STARTUP_SECONDS (con cualquier código o señal, SIGABRT incluido) o si su
salida o sus logs de /tmp/churros contienen "panicked at". Un Gtk-CRITICAL
solo se avisa.

nmcli, wpctl, bluetoothctl, upower, brightnessctl, niri o noctalia no existen
en el contenedor: una app que entra en pánico porque falta uno de ellos tiene
un fallo de verdad (en la ISO puede faltar el servicio, el hardware o la
sesión), no un fallo de la prueba.

churros-popup y los logs de settings y control-center escriben en
/tmp/churros, una ruta fija: la prueba nunca usa la del equipo. Con
bubblewrap (bwrap) cada app corre con /tmp, /run y /sys propios o de solo
lectura y sin red; sin él solo corre dentro del contenedor de build
(scripts/lib/container.sh), cuyo /tmp es desechable.

Uso: python3 scripts/test-gui-smoke.py [-k filtro] [-v]
CI: rust.yml, en el contenedor (container_run), tras la prueba del tour.
En local, igual que en el CI:
  source scripts/lib/container.sh; container_engine_init
  container_run -- python3 scripts/test-gui-smoke.py
"""
from __future__ import annotations

import argparse
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
import fcntl
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tests import testlib  # noqa: E402

# Lo que tiene que aguantar viva cada app. Las ventanas se construyen en
# activate(), en el primer segundo; el margen cubre una máquina de CI lenta.
STARTUP_SECONDS = 5.0
BROADWAY_DISPLAY = ":96"
POPUP_CRATE = "churros-popup"
SKEL = ROOT / "archiso/airootfs/etc/skel"
PANIC_MARK = "panicked at"
# Ruta fija en rust/popups/src/main.rs (PIDDIR) y en los logging.rs.
CHURROS_TMP = Path("/tmp/churros")
# Variables de la sesión de quien lo ejecuta que no pueden llegar a la app:
# abriría su ventana en el escritorio real o hablaría con su niri.
SESSION_VARS = ("DISPLAY", "WAYLAND_DISPLAY", "WAYLAND_SOCKET", "NIRI_SOCKET", "SWAYSOCK",
                "DBUS_SESSION_BUS_ADDRESS", "XDG_SESSION_ID", "XDG_SESSION_TYPE",
                "XDG_CURRENT_DESKTOP", "XDG_SEAT", "XDG_VTNR", "XAUTHORITY", "GDK_BACKEND",
                "GTK_THEME", "PULSE_SERVER", "PIPEWIRE_REMOTE")


def die(message: str) -> NoReturn:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def popup_names(crate: testlib.Crate) -> list[str]:
    source = crate.directory / "src/main.rs"
    match = re.search(r"\bconst\s+POPUPS\s*:[^=]*=\s*\[([^\]]*)\]", testlib.read_text(source))
    names = re.findall(r'"([^"\\]+)"', match.group(1)) if match else []
    if not names:
        die(f"no encuentro `const POPUPS` en {testlib.rel(source)}: actualiza esta prueba")
    return names


def launches() -> list[tuple[str, str, list[str]]]:
    """(etiqueta, binario, argumentos) de cada arranque."""
    found = []
    for crate in sorted(testlib.crates(), key=lambda c: c.name):
        if not crate.deploy:
            continue
        if crate.name == POPUP_CRATE:
            found += [(f"{crate.name} {name}", crate.name, [name]) for name in popup_names(crate)]
        else:
            found.append((crate.name, crate.name, []))
    if not found:
        die("ningún crate de rust/ tiene deploy = true: no hay nada que arrancar")
    return found


@contextmanager
def exclusive(lock_path: Path) -> Iterator[None]:
    """Cerrojo entre procesos (flock). tests/mutations ejecuta varias copias
    del repo a la vez con esta misma prueba."""
    with lock_path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def forget_workspace_build(target: Path) -> None:
    """Borra las huellas de cargo (release/.fingerprint) de los crates del
    workspace: el siguiente cargo build los recompila desde sus fuentes. Las
    dependencias de crates.io siguen en caché."""
    names = {crate.name for crate in testlib.crates()}
    fingerprints = target / "release/.fingerprint"
    if not fingerprints.is_dir():
        return
    for entry in fingerprints.iterdir():
        name, _, digest = entry.name.rpartition("-")
        if name in names and re.fullmatch(r"[0-9a-f]{16}", digest):
            shutil.rmtree(entry)


def build(binaries: set[str], destination: Path) -> None:
    """cargo build del workspace como scripts/build-rust.sh (release, mismas
    flags) y copia de los binarios a `destination`.

    tests/mutations ejecuta esta prueba en copias del repo con el
    CARGO_TARGET_DIR del repo original. Cargo da a los crates del workspace el
    mismo hash en cualquier ruta y decide por fecha de modificación: la copia
    (fechas viejas) reutilizaría el binario mutado de otra copia, y el
    build-rust.sh del repo original metería en la ISO un binario compilado
    desde una copia mutada. Con un target ajeno, la prueba olvida antes y
    después lo que compiló del workspace; el cerrojo cubre compilar y copiar.
    """
    env = os.environ.copy()
    env.setdefault("RUST_MIN_STACK", "268435456")
    if shutil.which("ld.lld"):
        env["RUSTFLAGS"] = env.get("RUSTFLAGS", "") + " -C link-arg=-fuse-ld=lld"
    target = Path(os.environ.get("CARGO_TARGET_DIR") or ROOT / "rust/target")
    target = target if target.is_absolute() else ROOT / target
    foreign = not target.resolve().is_relative_to(ROOT.resolve())
    target.mkdir(parents=True, exist_ok=True)
    destination.mkdir()
    with exclusive(target / "churros-gui-smoke.lock"):
        if foreign:
            print(f"== {target} no es de este árbol: se recompilan los crates del workspace", flush=True)
            forget_workspace_build(target)
        try:
            print("== cargo build --release (perfil de la ISO)", flush=True)
            result = subprocess.run(["cargo", "build", "--release", "--offline", "--locked",
                                     "--manifest-path", str(ROOT / "rust/Cargo.toml")],
                                    cwd=ROOT, env=env, timeout=3600)
            if result.returncode != 0:
                die(f"cargo build --release falló (código {result.returncode})")
            for name in sorted(binaries):
                built = target / "release" / name
                if not built.is_file():
                    die(f"cargo build no dejó {built}")
                shutil.copy2(built, destination / name)
        finally:
            if foreign:
                forget_workspace_build(target)


def bwrap_works() -> bool:
    if not shutil.which("bwrap"):
        return False
    probe = subprocess.run(["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "true"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return probe.returncode == 0


def in_build_container() -> bool:
    return (os.environ.get("CHURROS_IN_CONTAINER") == "1"
            and (Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()))


def sandbox(root: Path) -> tuple[list[str], Path]:
    """(prefijo del comando, directorio que la app ve como /tmp/churros)."""
    if bwrap_works():
        churros_tmp = root / "tmp-churros"
        churros_tmp.mkdir()
        return ["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "--tmpfs", "/run",
                "--ro-bind", "/sys", "/sys", "--unshare-net",
                "--bind", str(root), str(root), "--bind", str(churros_tmp), str(CHURROS_TMP),
                "--"], churros_tmp
    if in_build_container():
        return [], CHURROS_TMP
    die("sin bubblewrap (bwrap con user namespaces) no puedo darle a las apps un /tmp/churros "
        "propio, y fuera del contenedor de build churros-popup usaría el del equipo (y mataría "
        "el popup abierto). Instala bubblewrap o ejecútala en el contenedor:\n"
        "  source scripts/lib/container.sh; container_engine_init; "
        "container_run -- python3 scripts/test-gui-smoke.py")


def snapshot(directory: Path) -> dict[Path, int]:
    return {p: p.stat().st_size for p in directory.glob("*.log") if p.is_file()} if directory.is_dir() else {}


def new_log_text(directory: Path, before: dict[Path, int]) -> str:
    parts = []
    for path, size in sorted(snapshot(directory).items()):
        start = before.get(path, 0)
        if size > start:
            with path.open("rb") as handle:
                handle.seek(start)
                text = handle.read().decode("utf-8", "replace")
            parts.append(f"--- {CHURROS_TMP / path.name}\n{text}")
    return "\n".join(parts)


def describe_exit(code: int, wrapped: bool) -> str:
    if code < 0:
        return f"señal {signal.Signals(-code).name}"
    if wrapped and code > 128 and code - 128 in signal.valid_signals():
        return f"código {code} (señal {signal.Signals(code - 128).name})"
    return f"código {code}"


def stop(process: subprocess.Popen) -> None:
    """Termina el grupo entero: la app, dbus-run-session y su dbus-daemon."""
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def make_home(base: Path) -> Path:
    home = base / "home"
    shutil.copytree(SKEL, home, symlinks=True)
    for sub in (".config", ".cache", ".local/share", ".local/state"):
        (home / sub).mkdir(parents=True, exist_ok=True)
    return home


def run_one(label: str, binary: Path, args: list[str], root: Path, runtime: Path,
            prefix: list[str], churros_tmp: Path, dbus: str | None, verbose: bool) -> list[str]:
    """Arranca una app; devuelve sus fallos (vacío = arrancó y siguió viva)."""
    base = root / "apps" / label.replace(" ", "-")
    base.mkdir(parents=True)
    home = make_home(base)
    env = {key: value for key, value in os.environ.items() if key not in SESSION_VARS}
    env.update({
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
        "XDG_STATE_HOME": str(home / ".local/state"),
        "XDG_RUNTIME_DIR": str(runtime),
        "GDK_BACKEND": "broadway",
        "BROADWAY_DISPLAY": BROADWAY_DISPLAY,
        "GTK_A11Y": "none",
        "NO_AT_BRIDGE": "1",
        # dbus-run-session activaría xdg-desktop-portal, y su backend GTK no
        # abre Broadway: solo añade ruido y tiempo a cada arranque.
        "GDK_DEBUG": "no-portals",
        "RUST_BACKTRACE": "1",
    })
    command = prefix + ([dbus, "--"] if dbus else []) + [str(binary)] + args
    output_path = base / "output.txt"
    before = snapshot(churros_tmp)
    with output_path.open("w+b") as output:
        started = time.monotonic()
        process = subprocess.Popen(command, cwd=home, env=env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
        code = None
        try:
            while time.monotonic() - started < STARTUP_SECONDS:
                code = process.poll()
                if code is not None:
                    break
                time.sleep(0.1)
            elapsed = time.monotonic() - started
        finally:
            # También si ya terminó: lo que haya lanzado sigue en su grupo.
            stop(process)
    text = output_path.read_text(encoding="utf-8", errors="replace")
    logs = new_log_text(churros_tmp, before)

    problems = []
    if code is not None:
        problems.append(f"terminó a los {elapsed:.1f} s con {describe_exit(code, bool(prefix or dbus))}, "
                        f"antes de {STARTUP_SECONDS:.0f} s")
    if PANIC_MARK in text or PANIC_MARK in logs:
        problems.append(f"'{PANIC_MARK}' en su salida o en su log")
    # churros-settings redirige su stderr a su log: los avisos de GTK salen ahí.
    criticals = [line for line in (text + "\n" + logs).splitlines() if "-CRITICAL" in line]
    for line in criticals[:10]:
        print(f"  aviso {label}: {line.strip()}")
    if len(criticals) > 10:
        print(f"  aviso {label}: {len(criticals) - 10} CRITICAL más")
    if problems:
        print(f"FALLO {label}: " + "; ".join(problems))
    else:
        print(f"ok    {label} (viva a los {STARTUP_SECONDS:.0f} s)")
    if problems or verbose:
        print(f"  $ {' '.join(command[len(prefix):])}")
        print("  salida (últimas 40 líneas):")
        print("\n".join("    " + line for line in text.splitlines()[-40:]))
        if logs:
            print("  logs (últimas 40 líneas):")
            print("\n".join("    " + line for line in logs.splitlines()[-40:]))
    return problems


def start_broadway(runtime: Path, log_path: Path) -> subprocess.Popen:
    display = int(BROADWAY_DISPLAY.lstrip(":"))
    # gtk4-broadwayd :N escucha a las apps en $XDG_RUNTIME_DIR/broadway<N+1>.socket.
    sockets = [runtime / "http.socket", runtime / f"broadway{display + 1}.socket"]
    env = dict(os.environ, XDG_RUNTIME_DIR=str(runtime))
    with log_path.open("w") as log:
        server = subprocess.Popen(["gtk4-broadwayd", f"--unixsocket={sockets[0]}", BROADWAY_DISPLAY],
                                  env=env, stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 10
    while not all(s.exists() for s in sockets):
        if server.poll() is not None or time.monotonic() >= deadline:
            stop(server)
            die("gtk4-broadwayd no arrancó:\n" + log_path.read_text(errors="replace"))
        time.sleep(0.05)
    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-k", dest="filter", default="", help="solo los arranques cuyo nombre contenga esto")
    parser.add_argument("-v", dest="verbose", action="store_true", help="muestra la salida de cada app")
    options = parser.parse_args()

    for command in ("cargo", "gtk4-broadwayd"):
        if not shutil.which(command):
            die(f"falta '{command}': esta prueba no se puede saltar (ejecútala en el contenedor de build)")
    dbus = shutil.which("dbus-run-session")
    if not dbus:
        if testlib.STRICT:
            die("falta dbus-run-session (modo estricto)")
        print("aviso: sin dbus-run-session, las apps arrancan sin bus de sesión")

    selected = [item for item in launches() if options.filter in item[0]]
    if not selected:
        die(f"ningún arranque casa con -k {options.filter!r}")

    failures: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="churros-gui-smoke-") as tmp:
        root = Path(tmp)
        prefix, churros_tmp = sandbox(root)
        release = root / "bin"
        build({binary for _, binary, _ in selected}, release)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        where = ("bwrap: /tmp y /run propios, /sys de solo lectura, sin red" if prefix
                 else f"contenedor de build, {CHURROS_TMP} desechable")
        # Sin bwrap, todas las ejecuciones del contenedor comparten /tmp/churros:
        # el popup de una mataría el de otra (pidfile) y leerían sus logs.
        shared = nullcontext() if prefix else exclusive(CHURROS_TMP.parent / "churros-gui-smoke.lock")
        with shared:
            print(f"== {len(selected)} arranques en Broadway {BROADWAY_DISPLAY} ({where}), "
                  f"{STARTUP_SECONDS:.0f} s cada uno", flush=True)
            server = start_broadway(runtime, root / "broadway.log")
            try:
                for label, binary, args in selected:
                    if server.poll() is not None:
                        die("gtk4-broadwayd murió durante la prueba:\n"
                            + (root / "broadway.log").read_text(errors="replace"))
                    problems = run_one(label, release / binary, args, root, runtime, prefix, churros_tmp,
                                       dbus, options.verbose)
                    if problems:
                        failures[label] = problems
                    sys.stdout.flush()
            finally:
                stop(server)

    print()
    if failures:
        print(f"{len(failures)} de {len(selected)} arranques mueren o entran en pánico: " + ", ".join(failures))
        return 1
    print(f"Los {len(selected)} arranques siguen vivos a los {STARTUP_SECONDS:.0f} s, sin pánicos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
