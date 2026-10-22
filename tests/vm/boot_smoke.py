#!/usr/bin/env python3
"""Prueba de arranque de la ISO en QEMU: ¿llega la sesión Live al escritorio?

Arranca la ISO sin pantalla por el camino real (UEFI -> GRUB -> entrada por
defecto, o BIOS -> syslinux con --firmware bios), espera a qemu-guest-agent
y comprueba desde dentro lo que una persona vería al arrancar:

- systemd termina el arranque y no hay unidades fallidas;
- greetd, NetworkManager y pacman-init funcionan;
- greetd abre la sesión del usuario churros (autologin) y está activa;
- los procesos del escritorio siguen vivos (niri + noctalia + bienvenida,
  o xfce4-session + xfwm4 + panel...) y, en niri, la ventana de la
  bienvenida existe (niri msg windows);
- no hay core dumps, ni 'Permission denied' al ejecutar scripts de
  ChurrOS, ni errores de configuración de niri, ni opciones desconocidas
  en los lanzadores;
- la pantalla no está negra ni en una consola de texto.

Deja en el directorio de artefactos serial.log, journal.txt, screen.png,
report.json y la línea de QEMU. Los fallos ya conocidos de una edición se
apuntan en tests/known_issues.toml con la categoría boot-<edición>.

Uso:
  python3 tests/vm/boot_smoke.py out/ChurrOS-....iso [--firmware uefi|bios]
      [--timeout SEG] [--artifacts DIR] [--edition niri]
Con KVM tarda 2-4 minutos; sin KVM (TCG) puede pasar de 20.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import struct
import sys
import time
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import testlib  # noqa: E402
from tests.vm.qemu import VM, VMError, kvm_available  # noqa: E402

# Lo que tiene que estar vivo en la sesión de cada escritorio (pgrep -x,
# nombre de proceso de 15 caracteres como mucho).
DESKTOPS = {
    "niri": {
        "processes": ["niri", "noctalia", "churros-welcome"],
        "windows": ["org.churros.welcome"],
    },
    "xfce": {
        "processes": ["xfce4-session", "xfwm4", "xfce4-panel", "churros-welcome"],
        "windows": [],
    },
    "labwc": {
        "processes": ["labwc"],
        "windows": [],
    },
}

# Unidades que la ISO Live tiene que tener activas.
ACTIVE_UNITS = ["greetd.service", "NetworkManager.service", "qemu-guest-agent.service"]
# Unidades oneshot que tienen que haber terminado bien.
SUCCEEDED_UNITS = ["pacman-init.service"]

# Mensajes de la consola serie que significan que el arranque ya ha muerto.
FATAL_SERIAL = (
    "Kernel panic",
    "You are now being dropped into an emergency shell",
    "Entering emergency mode",
    "ERROR: '/dev/disk/by-uuid/",
    "Failed to mount live image",
)


class Report:
    def __init__(self):
        self.checks: list[dict] = []
        self.findings: dict[str, str] = {}
        self.facts: dict = {}

    def check(self, name: str, ok: bool, detail: str = "") -> bool:
        self.checks.append({"name": name, "ok": ok, "detail": detail})
        mark = "✓" if ok else "✗"
        print(f"  {mark} {name}" + (f": {detail}" if detail and not ok else ""), flush=True)
        return ok

    def finding(self, key: str, message: str) -> None:
        self.findings[key] = message


def guest_sh(agent, script: str, timeout: float = 60) -> tuple[int, str]:
    code, out, err = agent.sh(script, timeout=timeout)
    return code, (out + err).strip()


def poll(agent, script: str, accept, timeout: float, interval: float = 5):
    """Repite script hasta que accept(salida) sea cierto o se acabe el tiempo."""
    deadline = time.monotonic() + timeout
    output = ""
    while True:
        _, output = guest_sh(agent, script)
        if accept(output):
            return True, output
        if time.monotonic() > deadline:
            return False, output
        time.sleep(interval)


# ---------------------------------------------------------------- pantalla

def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    # Cabecera P6: "P6\n<ancho> <alto>\n<max>\n" seguida de RGB.
    tokens, index = [], 0
    while len(tokens) < 4:
        while data[index:index + 1].isspace():
            index += 1
        if data[index:index + 1] == b"#":
            index = data.index(b"\n", index) + 1
            continue
        start = index
        while not data[index:index + 1].isspace():
            index += 1
        tokens.append(data[start:index])
    width, height = int(tokens[1]), int(tokens[2])
    return width, height, data[index + 1:index + 1 + width * height * 3]


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
    stride = width * 3
    raw = b"".join(b"\x00" + rgb[row * stride:(row + 1) * stride] for row in range(height))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def screen_stats(rgb: bytes) -> tuple[float, int]:
    """(fracción de píxeles no oscuros, colores distintos) sobre una muestra."""
    pixels = len(rgb) // 3
    step = max(1, pixels // 20000)
    bright, colours, total = 0, set(), 0
    for index in range(0, pixels, step):
        r, g, b = rgb[index * 3:index * 3 + 3]
        total += 1
        if r + g + b > 60:
            bright += 1
        colours.add((r >> 3, g >> 3, b >> 3))
    return bright / max(total, 1), len(colours)


def capture(vm: VM, artifacts: Path, name: str) -> tuple[float, int] | None:
    shot = vm.screenshot(artifacts / name)
    if shot is None or shot.suffix != ".ppm":
        return None
    width, height, rgb = read_ppm(shot)
    write_png(shot.with_suffix(".png"), width, height, rgb)
    shot.unlink()
    return screen_stats(rgb)


# ------------------------------------------------------------- comprobaciones

def check_system(agent, report: Report, timeout: float) -> None:
    code, state = guest_sh(agent, f"timeout {int(timeout)} systemctl is-system-running --wait", timeout=timeout + 30)
    report.facts["system_state"] = state
    report.check("systemd terminó el arranque", state in ("running", "degraded"), state)

    _, failed = guest_sh(agent, "systemctl list-units --state=failed --plain --no-legend --no-pager | awk '{print $1}'")
    failed_units = [unit for unit in failed.split() if unit]
    report.facts["failed_units"] = failed_units
    for unit in failed_units:
        _, status = guest_sh(agent, f"systemctl status --no-pager -l -n 20 {unit}")
        report.finding(f"failed-unit:{unit}", f"unidad fallida {unit}:\n{status}")
    report.check("sin unidades fallidas", not failed_units, ", ".join(failed_units))

    for unit in ACTIVE_UNITS:
        _, state = guest_sh(agent, f"systemctl is-active {unit}")
        report.check(f"{unit} activo", state == "active", state)
    for unit in SUCCEEDED_UNITS:
        _, result = guest_sh(agent, f"systemctl show -p Result --value {unit}")
        report.check(f"{unit} terminó bien", result == "success", result)


def check_session(agent, report: Report, desktop: str, timeout: float) -> str | None:
    expected = DESKTOPS[desktop]
    script = (
        "for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do "
        "loginctl show-session \"$s\" -p Name -p Type -p Class -p Active -p State --value | paste -sd' '; done"
    )
    # logind guarda el Type que hay en el entorno PAM al abrir la sesión, y
    # greetd no exporta XDG_SESSION_TYPE: sus sesiones salen como 'tty'
    # aunque lancen niri o XFCE. Lo gráfico se comprueba después por los
    # procesos, el IPC del compositor y la pantalla.
    ok, sessions = poll(
        agent, script,
        lambda out: any(line.split()[:1] == ["churros"] and line.split()[2:5] == ["user", "yes", "active"]
                        for line in out.splitlines() if len(line.split()) >= 5),
        timeout,
    )
    report.facts["sessions"] = sessions.splitlines()
    report.check("sesión activa de churros (autologin de greetd)", ok, sessions or "sin sesiones")

    uid_code, uid = guest_sh(agent, "id -u churros")
    uid = uid if uid_code == 0 else "1000"
    missing = []
    for process in expected["processes"]:
        alive, _ = poll(agent, f"pgrep -u churros -x {process} >/dev/null && echo yes",
                        lambda out: out == "yes", timeout=120 if not missing else 10)
        if not alive:
            missing.append(process)
            report.finding(f"process:{process}", f"el proceso {process} no está vivo en la sesión de churros")
    report.check("procesos del escritorio vivos", not missing, ", ".join(missing))
    return uid


def check_niri(agent, report: Report, uid: str, timeout: float) -> None:
    env = f"XDG_RUNTIME_DIR=/run/user/{uid}"
    sock = f"$(ls /run/user/{uid}/niri.*.sock 2>/dev/null | head -n1)"
    cmd = f"runuser -u churros -- env {env} NIRI_SOCKET={sock} niri msg -j"
    code, outputs = guest_sh(agent, f"{cmd} outputs")
    try:
        output_count = len(json.loads(outputs)) if code == 0 else 0
    except json.JSONDecodeError:
        output_count = 0
    detail = outputs[:300]
    if output_count == 0:
        # niri 26.04 rechaza los renderizadores EGL por software ("software EGL
        # renderers are skipped"): sin virgl no abre ninguna salida.
        detail += " (niri sin salidas: ¿la VM tiene 3D? mira /dev/vcs7 en la VM o usa --gpu virgl)"
    report.check("niri responde por IPC y tiene una salida", output_count > 0, detail)

    def has_windows(out: str) -> bool:
        try:
            ids = {window.get("app_id") for window in json.loads(out)}
        except (json.JSONDecodeError, AttributeError, TypeError):
            return False
        return all(app in ids for app in DESKTOPS["niri"]["windows"])

    ok, windows = poll(agent, f"{cmd} windows", has_windows, timeout)
    try:
        report.facts["windows"] = [w.get("app_id") for w in json.loads(windows)]
    except (json.JSONDecodeError, AttributeError, TypeError):
        report.facts["windows"] = windows[:500]
    report.check("ventanas esperadas abiertas (" + ", ".join(DESKTOPS["niri"]["windows"]) + ")", ok,
                 str(report.facts["windows"]))
    for app in DESKTOPS["niri"]["windows"]:
        if not ok:
            report.finding(f"window:{app}", f"no hay ventana {app} en niri")


def check_journal(agent, report: Report, artifacts: Path) -> None:
    _, journal = guest_sh(agent, "journalctl -b --no-pager -o short-monotonic", timeout=120)
    (artifacts / "journal.txt").write_text(journal + "\n")
    patterns = [
        (re.compile(r"(/usr/(?:local/)?bin/\S+|/usr/share/churros/\S+).*Permission denied|Permission denied.*(/usr/(?:local/)?bin/\S+|/usr/share/churros/\S+)"), "permission"),
        (re.compile(r"niri.*(?:error loading config|failed to parse config|error parsing)", re.I), "niri-config"),
        (re.compile(r"Unknown option (\S+)"), "unknown-option"),
        (re.compile(r"Failed to execute .*: (?:No such file|Permission denied)|Failed at step EXEC"), "exec"),
    ]
    hits = 0
    for line in journal.splitlines():
        for pattern, kind in patterns:
            match = pattern.search(line)
            if match:
                detail = next((g for g in match.groups() if g), "") if match.groups() else ""
                report.finding(f"journal:{kind}:{detail}".rstrip(":"), line.strip())
                hits += 1
    report.check("diario sin errores de ejecución, permisos ni configuración", hits == 0, f"{hits} líneas")

    code, dumps = guest_sh(agent, "coredumpctl list --no-legend --no-pager 2>/dev/null | awk '{print $NF}'")
    crashed = sorted({Path(line).name for line in dumps.split() if line.startswith("/")})
    for exe in crashed:
        report.finding(f"coredump:{exe}", f"core dump de {exe}")
    report.check("sin core dumps", not crashed, ", ".join(crashed))


def check_screen(vm: VM, report: Report, artifacts: Path) -> None:
    stats = capture(vm, artifacts, "screen")
    if stats is None:
        report.check("captura de pantalla", False, "QMP screendump no devolvió imagen")
        return
    bright, colours = stats
    report.facts["screen"] = {"bright_fraction": round(bright, 3), "colours": colours}
    # Una consola de texto o una pantalla negra tienen casi todo negro y
    # pocos colores; un escritorio con fondo, muchos.
    report.check("la pantalla muestra un escritorio (no negro ni consola)", bright > 0.2 and colours > 64,
                 f"{bright:.0%} píxeles claros, {colours} colores")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("iso", type=Path)
    parser.add_argument("--firmware", choices=("uefi", "bios"), default="uefi")
    parser.add_argument("--timeout", type=float, default=None, help="segundos para cada espera larga")
    parser.add_argument("--artifacts", type=Path, default=None)
    parser.add_argument("--edition", default=None, help="por defecto, /etc/churros-edition de la ISO")
    parser.add_argument("--memory", type=int, default=4096)
    parser.add_argument("--gpu", choices=("auto", "virgl", "plain"), default="auto",
                        help="virgl da 3D al invitado (niri lo necesita); plain, virtio-vga sin 3D")
    parser.add_argument("--keep", action="store_true", help="no apagar la VM al terminar")
    args = parser.parse_args()

    iso = args.iso.resolve()
    match = re.search(r"-(x86_64|aarch64|i686)(?:-|\.iso)", iso.name)
    arch = match.group(1) if match else "x86_64"
    timeout = args.timeout or (420 if kvm_available() else 2400)
    artifacts = (args.artifacts or testlib.ROOT / "out" / f"boot-{iso.stem}-{args.firmware}").resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    report = Report()
    print(f"== Arranque de {iso.name} ({arch}, {args.firmware}, {'KVM' if kvm_available() else 'TCG'}, espera {timeout:.0f} s)")
    print(f"   artefactos: {artifacts}")

    vm = VM(iso=iso, arch=arch, firmware=args.firmware, memory=args.memory, artifacts=artifacts, gpu=args.gpu)
    report.facts["gpu"] = vm.gpu
    started = time.monotonic()
    edition_name = args.edition
    try:
        vm.start()
        agent = vm.wait_for_agent(timeout, abort_patterns=FATAL_SERIAL)
        report.facts["agent_seconds"] = round(time.monotonic() - started)
        report.check("qemu-guest-agent responde", True)
        if not edition_name:
            _, edition_name = guest_sh(agent, "cat /etc/churros-edition")
        report.facts["edition"] = edition_name
        try:
            item = testlib.edition(edition_name, arch)
        except KeyError:
            report.check("edición conocida", False, f"{edition_name}/{arch} no está en testlib.EDITIONS")
            item = None
        check_system(agent, report, timeout)
        if item and item.desktop:
            uid = check_session(agent, report, item.desktop, timeout)
            if item.desktop == "niri":
                check_niri(agent, report, uid, timeout=min(timeout, 300))
        check_journal(agent, report, artifacts)
        if item and item.desktop:
            check_screen(vm, report, artifacts)
        agent.close()
    except VMError as exc:
        report.check("la VM arrancó", False, str(exc))
        capture(vm, artifacts, "screen")
    finally:
        report.facts["seconds"] = round(time.monotonic() - started)
        if not args.keep:
            vm.stop()

    category = f"boot-{edition_name or 'unknown'}"
    findings = {f"{category}:{key}": msg for key, msg in report.findings.items()}
    known = {k: v for k, v in testlib.known_issues().items() if k.startswith(category + ":")}
    new = {k: v for k, v in findings.items() if k not in known}
    fixed = sorted(k for k in known if k not in findings)
    failed_checks = [c for c in report.checks if not c["ok"]]
    # Un check que falla solo por hallazgos ya apuntados no cuenta.
    explained = {"sin unidades fallidas", "procesos del escritorio vivos", "sin core dumps",
                 "diario sin errores de ejecución, permisos ni configuración"}
    real_failures = [c for c in failed_checks if not (c["name"] in explained and not new)]
    if any(c["name"].startswith("ventanas esperadas") for c in failed_checks) and not new:
        real_failures = [c for c in real_failures if not c["name"].startswith("ventanas esperadas")]

    (artifacts / "report.json").write_text(json.dumps(
        {"iso": iso.name, "firmware": args.firmware, "checks": report.checks, "findings": findings,
         "new_findings": sorted(new), "fixed_known_issues": fixed, "facts": report.facts},
        indent=2, ensure_ascii=False) + "\n")

    print()
    if new:
        print(f"{len(new)} problema(s) nuevo(s):")
        for key, message in sorted(new.items()):
            print(f"  - [{key}] {message.splitlines()[0]}")
    if fixed:
        print("Ya no fallan; borra su entrada de tests/known_issues.toml:")
        for key in fixed:
            print(f"  - {key}")
    status = 1 if (real_failures or new or fixed) else 0
    print(f"{'OK' if status == 0 else 'FALLO'}: {len(report.checks) - len(failed_checks)}/{len(report.checks)} "
          f"comprobaciones en {report.facts['seconds']} s")
    return status


if __name__ == "__main__":
    sys.exit(main())
