#!/usr/bin/env python3
"""Distingue menú de arranque, splash y consola de texto en una captura.

El Live no imprime Plymouth por la serie (en BIOS ni siquiera va
console=ttyS0, y el initramfs no lleva el hook). Hay que mirar los
fotogramas: el menú tiene color, el kernel es texto sobre negro y un
splash plano no es ni lo uno ni lo otro. Si tras el menú llega el texto
del kernel sin splash, Plymouth no está en ese arranque.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
import time


def _ratios(width: int, height: int, rgb: bytes) -> tuple[float, float, float]:
    total = width * height
    if total == 0:
        return 1.0, 0.0, 0.0
    step = 1 if total <= 64 * 64 else 4
    seen = near_black = light = saturated = 0
    for y in range(0, height, step):
        row = y * width * 3
        for x in range(0, width, step):
            index = row + x * 3
            red, green, blue = rgb[index], rgb[index + 1], rgb[index + 2]
            seen += 1
            level = red if red > green else green
            if blue > level:
                level = blue
            floor = red if red < green else green
            if blue < floor:
                floor = blue
            if level < 20:
                near_black += 1
            elif level > 180:
                light += 1
            if level - floor > 40 and level > 40:
                saturated += 1
    if seen == 0:
        return 1.0, 0.0, 0.0
    return near_black / seen, light / seen, saturated / seen


def classify_frame(width: int, height: int, rgb: bytes) -> str:
    """blank, text, splash o menu. menu cubre el tema gráfico del arranque."""
    black, light, saturated = _ratios(width, height, rgb)
    if black > 0.92 and saturated < 0.01:
        return "text" if light >= 0.005 else "blank"
    if saturated < 0.02 and black > 0.7 and light < 0.15:
        return "text"
    if saturated > 0.4 and black < 0.2:
        return "splash"
    if saturated >= 0.02:
        return "menu"
    if black < 0.5:
        return "splash"
    return "text"


GRAPHICAL_KINDS = {"menu", "splash"}


def is_graphical(kind: str) -> bool:
    """Un fotograma que ya no es consola de texto ni negro."""
    return kind in GRAPHICAL_KINDS


class DesktopWait:
    """No acepta el menú de arranque: primero tiene que verse texto del kernel."""

    def __init__(self) -> None:
        self.seen_text = False
        self.ready = False

    def feed(self, kind: str) -> bool:
        if kind in {"text", "blank"}:
            self.seen_text = True
        elif self.seen_text and is_graphical(kind):
            self.ready = True
        return self.ready


def assess_image(width: int, height: int, rgb: bytes, expect_w: int, expect_h: int) -> tuple[bool, str]:
    kind = classify_frame(width, height, rgb)
    if kind in {"text", "blank"}:
        return False, f"not-graphical:{kind}"
    if (width, height) != (expect_w, expect_h):
        return False, f"wrong-resolution:{width}x{height}"
    return True, "graphical"


def splash_on_cmdline(serial: str) -> bool | None:
    """True/False si la serie ya mostró la línea de órdenes del kernel.

    None si todavía no aparece (el arranque BIOS de syslinux no lleva
    console=ttyS0, así que puede no aparecer nunca).
    """
    chosen = ""
    for line in serial.splitlines():
        if "Kernel command line:" in line or "archisobasedir=" in line:
            chosen = line
    if not chosen:
        return None
    words = chosen.split()
    return "splash" in words or "plymouth" in words


class BootWatch:
    """Estado del arranque a partir de la clase de cada fotograma."""

    def __init__(self, want_grub: bool, want_plymouth: bool) -> None:
        self.want_grub = want_grub
        self.want_plymouth = want_plymouth
        self.menu_seen = False
        self.grub: str | None = None
        self.plymouth: str | None = None
        self.phase = "menu"

    def feed(self, kind: str, splash_flag: bool | None = None) -> None:
        if self.phase == "done":
            return
        if not self.menu_seen:
            if kind == "menu":
                self.menu_seen = True
                if self.want_grub:
                    self.grub = "ok"
                self.phase = "splash"
            return
        if splash_flag is False and self.plymouth is None:
            self.plymouth = "absent"
            self.phase = "done"
            return
        if kind == "splash":
            if self.want_plymouth:
                self.plymouth = "ok"
            self.phase = "done"
        elif kind == "text":
            if self.plymouth is None:
                self.plymouth = "absent"
            self.phase = "done"

    def finish(self) -> None:
        if self.want_grub and self.grub is None:
            self.grub = "missed"
        if self.want_plymouth and self.plymouth is None:
            self.plymouth = "absent"
        self.phase = "done"


def watch(socket: Path, serial: Path, out: Path, timeout: float, want_grub: bool, want_plymouth: bool, interval: float = 0.4) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from imageutil import read_png  # noqa: E402
    from vmctl import QmpError, screendump  # noqa: E402

    state = BootWatch(want_grub, want_plymouth)
    frame = out / "_frame.png"
    saved_grub = False
    saved_plymouth = False
    failures = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and state.phase != "done":
        try:
            screendump(socket, frame)
            failures = 0
        except (OSError, QmpError, ValueError):
            failures += 1
            if failures >= 3:
                break
            time.sleep(interval)
            continue
        width, height, rgb = read_png(frame)
        kind = classify_frame(width, height, rgb)
        serial_text = serial.read_text(encoding="utf-8", errors="replace") if serial.is_file() else ""
        splash_flag = splash_on_cmdline(serial_text)
        grub_before = state.grub
        plymouth_before = state.plymouth
        state.feed(kind, splash_flag)
        if state.grub == "ok" and grub_before != "ok" and not saved_grub:
            shutil.copyfile(frame, out / "grub.png")
            saved_grub = True
        if state.plymouth == "ok" and plymouth_before != "ok" and not saved_plymouth:
            shutil.copyfile(frame, out / "plymouth.png")
            saved_plymouth = True
        time.sleep(interval)
    state.finish()
    frame.unlink(missing_ok=True)
    result = {"grub": state.grub, "plymouth": state.plymouth}
    (out / "boot-watch.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def wait_desktop(socket: Path, timeout: float, interval: float = 2.0) -> bool:
    """Espera un fotograma gráfico posterior al texto del kernel."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from imageutil import read_png  # noqa: E402
    from vmctl import QmpError, screendump  # noqa: E402

    state = DesktopWait()
    frame = socket.parent / "_desktop-frame.png"
    failures = 0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            screendump(socket, frame)
            failures = 0
        except (OSError, QmpError, ValueError):
            failures += 1
            if failures >= 5:
                break
            time.sleep(interval)
            continue
        width, height, rgb = read_png(frame)
        if state.feed(classify_frame(width, height, rgb)):
            frame.unlink(missing_ok=True)
            return True
        time.sleep(interval)
    frame.unlink(missing_ok=True)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vigila el menú de arranque y Plymouth.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    watch_cmd = sub.add_parser("watch")
    watch_cmd.add_argument("--socket", type=Path, required=True)
    watch_cmd.add_argument("--serial", type=Path, required=True)
    watch_cmd.add_argument("--out", type=Path, required=True)
    watch_cmd.add_argument("--timeout", type=float, default=20.0)
    watch_cmd.add_argument("--grub", type=int, default=0)
    watch_cmd.add_argument("--plymouth", type=int, default=0)
    desktop_cmd = sub.add_parser("wait-desktop")
    desktop_cmd.add_argument("--socket", type=Path, required=True)
    desktop_cmd.add_argument("--timeout", type=float, default=600.0)
    assess_cmd = sub.add_parser("assess")
    assess_cmd.add_argument("--png", type=Path, required=True)
    assess_cmd.add_argument("--width", type=int, default=1920)
    assess_cmd.add_argument("--height", type=int, default=1080)
    args = parser.parse_args(argv)
    if args.cmd == "watch":
        watch(
            args.socket, args.serial, args.out, args.timeout,
            bool(args.grub), bool(args.plymouth),
        )
        return 0
    if args.cmd == "wait-desktop":
        ready = wait_desktop(args.socket, args.timeout)
        print("ready" if ready else "timeout")
        return 0 if ready else 1
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from imageutil import read_png  # noqa: E402
    width, height, rgb = read_png(args.png)
    ok, reason = assess_image(width, height, rgb, args.width, args.height)
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
