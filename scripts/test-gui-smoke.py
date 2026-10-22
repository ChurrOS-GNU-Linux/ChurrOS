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

Cada arranque se hace dos veces, porque en la ISO los programas externos
(nmcli, wpctl, bluetoothctl, upower, brightnessctl, niri, noctalia...)
pueden faltar o fallar (wpctl antes de que arranque PipeWire, un portátil sin
batería, una sesión sin niri):
  - tal cual: en el contenedor casi todos faltan y la app ve un error al
    lanzarlos;
  - "[herramientas fallan]": cada programa que lanzan las apps (el escaneo de
    Command::new de tests/static/test_references.py) existe en el PATH, no
    escribe nada en stdout y sale con 1 tras un mensaje de error. Así se
    ejecuta el código que mira su salida y su código de salida, que con el
    programa ausente nunca corre.
Una app que entra en pánico en cualquiera de los dos casos tiene un fallo de
verdad, no un fallo de la prueba.

churros-popup y los logs de settings y control-center escriben en
/tmp/churros, una ruta fija: la prueba nunca usa la del equipo. Con
bubblewrap (bwrap) cada app corre con /tmp, /run y /sys propios o de solo
lectura y sin red; sin él solo corre dentro del contenedor de build
(scripts/lib/container.sh), cuyo /tmp es desechable.

Uso: python3 scripts/test-gui-smoke.py [-k filtro] [-v]
En local (en el contenedor, con la prueba del tour): ./churros test --gui
CI: rust.yml, en el contenedor (container_run), tras la prueba del tour.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
import os
from pathlib import Path
import re
import shlex
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
# Sufijo de la etiqueta de la segunda pasada (programas externos que fallan).
FAILING_TOOLS = "[herramientas fallan]"
# Programas que están en cualquier sistema y no fallan: un stub que falla
# probaría un caso imposible.
ALWAYS_PRESENT = frozenset({"sh", "bash", "id", "date", "getent"})
STUB = """#!/bin/sh
printf '%s\\n' "${{0##*/}} $*" >> {log}
echo "${{0##*/}}: Could not connect to service (stub de test-gui-smoke)" >&2
exit 1
"""


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


def external_tools() -> list[str]:
    """Programas que lanzan las apps Rust: Command::new("x") y los helpers que
    lo envuelven, con el mismo escaneo que comprueba que existen en la ISO."""
    from tests.static import test_references
    names = {command for _, command in test_references.rust_commands() if "/" not in command}
    names -= ALWAYS_PRESENT
    if not names:
        die("el escaneo de tests/static/test_references.py no encuentra ningún programa que "
            "lancen las apps Rust: actualiza esta prueba")
    return sorted(names)


def make_stubs(directory: Path, log: Path) -> int:
    """Un programa que falla por cada herramienta externa; devuelve cuántos."""
    directory.mkdir()
    tools = external_tools()
    for name in tools:
        stub = directory / name
        stub.write_text(STUB.format(log=shlex.quote(str(log))), encoding="utf-8")
        stub.chmod(0o755)
    return len(tools)


def build(binaries: set[str], destination: Path) -> None:
    """cargo build del workspace como scripts/build-rust.sh (release, mismas
    flags) y copia de los binarios a `destination`.

    En las copias de tests/mutations el target es ajeno al árbol y lo
    comparten varias copias: testlib.workspace_build toma su cerrojo y olvida
    lo compilado del workspace antes y después, para no reutilizar el binario
    de otra copia mutada. El cerrojo cubre compilar y copiar.
    """
    env = os.environ.copy()
    env.setdefault("RUST_MIN_STACK", "268435456")
    if shutil.which("ld.lld"):
        env["RUSTFLAGS"] = env.get("RUSTFLAGS", "") + " -C link-arg=-fuse-ld=lld"
    target = testlib.cargo_target(ROOT)
    destination.mkdir()
    with testlib.workspace_build(target, ROOT) as foreign:
        if foreign:
            print(f"== {target} no es de este árbol: se recompilan los crates del workspace", flush=True)
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
        "el popup abierto). Instala bubblewrap o ejecútala en el contenedor: ./churros test --gui")


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


def read_from(path: Path, offset: int) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(offset)
        return handle.read().decode("utf-8", "replace")


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
            prefix: list[str], churros_tmp: Path, dbus: str | None, stubs: Path | None,
            calls_log: Path, verbose: bool) -> list[str]:
    """Arranca una app; devuelve sus fallos (vacío = arrancó y siguió viva).
    Con `stubs`, ese directorio va delante en el PATH."""
    base = root / "apps" / re.sub(r"[^\w.-]+", "-", label).strip("-")
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
    if stubs is not None:
        env["PATH"] = f"{stubs}{os.pathsep}{env.get('PATH', os.defpath)}"
    command = prefix + ([dbus, "--"] if dbus else []) + [str(binary)] + args
    output_path = base / "output.txt"
    before = snapshot(churros_tmp)
    calls_before = calls_log.stat().st_size if calls_log.is_file() else 0
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
        calls = list(dict.fromkeys(read_from(calls_log, calls_before).splitlines()))
        if stubs is not None and calls:
            print(f"  programas externos (stubs que fallan) a los que llamó ({len(calls)} distintos):")
            print("\n".join("    " + line for line in calls[:30]))
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


def on_terminate(signum, _frame) -> NoReturn:
    # tests/mutations termina con SIGTERM la prueba que agota su plazo: así
    # corren los finally (cerrar las apps, que viven en su propia sesión, y
    # gtk4-broadwayd; soltar el cerrojo del target de cargo).
    raise SystemExit(128 + signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-k", dest="filter", default="", help="solo los arranques cuyo nombre contenga esto")
    parser.add_argument("-v", dest="verbose", action="store_true", help="muestra la salida de cada app")
    options = parser.parse_args()
    signal.signal(signal.SIGTERM, on_terminate)

    for command in ("cargo", "gtk4-broadwayd"):
        if not shutil.which(command):
            die(f"falta '{command}': esta prueba no se puede saltar (ejecútala en el contenedor de build)")
    dbus = shutil.which("dbus-run-session")
    if not dbus:
        if testlib.STRICT:
            die("falta dbus-run-session (modo estricto)")
        print("aviso: sin dbus-run-session, las apps arrancan sin bus de sesión")

    # Cada arranque, primero tal cual y luego con los programas externos fallando.
    selected = [(f"{label} {FAILING_TOOLS}" if failing else label, binary, args, failing)
                for label, binary, args in launches() for failing in (False, True)]
    selected = [item for item in selected if options.filter in item[0]]
    if not selected:
        die(f"ningún arranque casa con -k {options.filter!r}")

    failures: dict[str, list[str]] = {}
    with tempfile.TemporaryDirectory(prefix="churros-gui-smoke-") as tmp:
        root = Path(tmp)
        prefix, churros_tmp = sandbox(root)
        calls_log = root / "stub-calls.log"
        stubs = root / "fake-bin"
        count = make_stubs(stubs, calls_log)
        release = root / "bin"
        build({binary for _, binary, _, _ in selected}, release)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700)
        where = ("bwrap: /tmp y /run propios, /sys de solo lectura, sin red" if prefix
                 else f"contenedor de build, {CHURROS_TMP} desechable")
        # Sin bwrap, todas las ejecuciones del contenedor comparten /tmp/churros:
        # el popup de una mataría el de otra (pidfile) y leerían sus logs.
        shared = nullcontext() if prefix else testlib.file_lock(CHURROS_TMP.parent / "churros-gui-smoke.lock")
        with shared:
            if not prefix:
                # El pidfile de un popup que sobrevivió a una ejecución abortada
                # (SIGKILL): el popup del mismo nombre lo apagaría (toggle) y
                # saldría con 0 en vez de abrirse.
                for name in ("popup.pid", "popup.name"):
                    (CHURROS_TMP / name).unlink(missing_ok=True)
            print(f"== {len(selected)} arranques en Broadway {BROADWAY_DISPLAY} ({where}), "
                  f"{STARTUP_SECONDS:.0f} s cada uno; {FAILING_TOOLS}: {count} programas externos "
                  f"que fallan en {stubs}", flush=True)
            server = start_broadway(runtime, root / "broadway.log")
            try:
                for label, binary, args, failing in selected:
                    if server.poll() is not None:
                        die("gtk4-broadwayd murió durante la prueba:\n"
                            + (root / "broadway.log").read_text(errors="replace"))
                    problems = run_one(label, release / binary, args, root, runtime, prefix, churros_tmp,
                                       dbus, stubs if failing else None, calls_log, options.verbose)
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
