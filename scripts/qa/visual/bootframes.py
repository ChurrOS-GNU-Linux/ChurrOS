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
    """El primer fotograma gráfico no basta: puede ser solo el overlay de niri.

    Hace falta texto del kernel, una barra a lo ancho, y N fotogramas casi iguales.
    """

    def __init__(self, stable_needed: int = 3) -> None:
        self.seen_text = False
        self.stable_needed = stable_needed
        self.stable = 0
        self.last: tuple | None = None
        self.ready = False

    def feed(self, kind: str, signature: tuple | None = None, bar: bool = False) -> bool:
        if kind in {"text", "blank"}:
            self.seen_text = True
            self.stable = 0
            self.last = None
            return False
        if not (self.seen_text and is_graphical(kind) and bar):
            self.stable = 0
            self.last = signature
            return False
        if signature is not None and near_identical(self.last, signature):
            self.stable += 1
        else:
            self.stable = 1
        self.last = signature
        self.ready = self.stable >= self.stable_needed
        return self.ready


def frame_signature(rgb: bytes, width: int, height: int, cols: int = 16, rows: int = 9) -> tuple:
    samples = []
    for row in range(rows):
        y = min(height - 1, row * height // rows)
        for col in range(cols):
            x = min(width - 1, col * width // cols)
            index = (y * width + x) * 3
            samples.append(rgb[index:index + 3])
    return tuple(samples)


def near_identical(previous: tuple | None, current: tuple | None, tolerance: int = 12) -> bool:
    if previous is None or current is None or len(previous) != len(current) or not previous:
        return False
    total = 0
    for left, right in zip(previous, current):
        total += abs(left[0] - right[0]) + abs(left[1] - right[1]) + abs(left[2] - right[2])
    return total / len(previous) <= tolerance


# Distancia mínima entre la franja y el fondo dominante. Un gris plano
# (#404040 de niri, o cualquier gris uniforme) queda por debajo.
BAR_CONTRAST = 24
BAR_CONTRAST2 = BAR_CONTRAST * BAR_CONTRAST
BAR_EDGE = 0.05
BAR_EDGE2 = 30 * 30
# #404040 contra el panel #2A2A2A son ~38: no debe colar como color de barra.
BAR_NEAR2 = 28 * 28
BAR_ROLES = {"panel", "background", "primary", "secondary"}
FALLBACK_BAR_COLORS = (
    (0xF9, 0x73, 0x16),
    (0x2A, 0x2A, 0x2A),
    (0x1F, 0x29, 0x37),
    (0x11, 0x18, 0x27),
)
_BAR_COLORS: tuple[tuple[int, int, int], ...] | None = None


def _dist2(left: tuple[int, int, int], right: tuple[int, int, int]) -> int:
    return (left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2


def bar_palette() -> tuple[tuple[int, int, int], ...]:
    """Colores de barra: design-tokens.json si está junto al script; si no, la paleta fija."""
    global _BAR_COLORS
    if _BAR_COLORS is not None:
        return _BAR_COLORS
    found: list[tuple[int, int, int]] = []
    path = Path(__file__).resolve().parent / "design-tokens.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            data = {}
        if isinstance(data, dict):
            for item in data.get("colors") or []:
                if not isinstance(item, dict) or item.get("role") not in BAR_ROLES:
                    continue
                text = str(item.get("hex") or "")
                if len(text) != 7 or text[0] != "#":
                    continue
                try:
                    color = (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
                except ValueError:
                    continue
                if color not in found:
                    found.append(color)
    _BAR_COLORS = tuple(found) if found else FALLBACK_BAR_COLORS
    return _BAR_COLORS


def _near_bar_color(color: tuple[int, int, int]) -> bool:
    return any(_dist2(color, token) <= BAR_NEAR2 for token in bar_palette())


def _region_mean(rgb: bytes, width: int, y0: int, y1: int) -> tuple[int, int, int]:
    total = red = green = blue = 0
    span = max(1, y1 - y0)
    stride = 1 if width * span <= 4096 else 2
    for y in range(y0, y1, stride):
        row = y * width * 3
        for x in range(0, width, stride):
            index = row + x * 3
            red += rgb[index]
            green += rgb[index + 1]
            blue += rgb[index + 2]
            total += 1
    if total == 0:
        return (0, 0, 0)
    return (red // total, green // total, blue // total)


def _dominant_background(rgb: bytes, width: int, height: int, band: int) -> tuple[int, int, int]:
    y0, y1 = band, height - band
    if y1 <= y0:
        y0, y1 = 0, height
    buckets: dict[tuple[int, int, int], list[int]] = {}
    span = max(1, y1 - y0)
    stride = 1 if width * span <= 4096 else 4
    for y in range(y0, y1, stride):
        row = y * width * 3
        for x in range(0, width, stride):
            index = row + x * 3
            pixel = (rgb[index], rgb[index + 1], rgb[index + 2])
            key = (pixel[0] // 16, pixel[1] // 16, pixel[2] // 16)
            bucket = buckets.get(key)
            if bucket is None:
                buckets[key] = [1, pixel[0], pixel[1], pixel[2]]
            else:
                bucket[0] += 1
                bucket[1] += pixel[0]
                bucket[2] += pixel[1]
                bucket[3] += pixel[2]
    if not buckets:
        return (0, 0, 0)
    best = max(buckets.values(), key=lambda item: item[0])
    count = best[0]
    return (best[1] // count, best[2] // count, best[3] // count)


def _edge_density(rgb: bytes, width: int, height: int, y0: int, y1: int) -> float:
    edges = 0
    checks = 0
    span = max(1, y1 - y0)
    stride = 1 if width * span <= 4096 else 2
    outside = y1 if y0 == 0 else y0 - 1

    def consider(a: int, b: int) -> None:
        nonlocal edges, checks
        checks += 1
        left = (rgb[a], rgb[a + 1], rgb[a + 2])
        right = (rgb[b], rgb[b + 1], rgb[b + 2])
        if _dist2(left, right) >= BAR_EDGE2:
            edges += 1

    for y in range(y0, y1, stride):
        row = y * width * 3
        for x in range(0, width - stride, stride):
            consider(row + x * 3, row + (x + stride) * 3)
        below = y + stride
        if below < y1:
            other = below * width * 3
            for x in range(0, width, stride):
                consider(row + x * 3, other + x * 3)
    if 0 <= outside < height and not y0 <= outside < y1:
        edge_y = y0 if y0 == 0 else y1 - 1
        row = edge_y * width * 3
        other = outside * width * 3
        for x in range(0, width, stride):
            consider(row + x * 3, other + x * 3)
    if checks == 0:
        return 0.0
    return edges / checks


def _band_is_bar(mean: tuple[int, int, int], background: tuple[int, int, int], edge: float) -> bool:
    distance = _dist2(mean, background)
    if distance < BAR_CONTRAST2:
        return False
    return edge >= BAR_EDGE or _near_bar_color(mean)


def has_bar(width: int, height: int, rgb: bytes) -> bool:
    """Franja superior o inferior distinta del fondo. Un gris plano no cuenta.

    El fondo es el color dominante del centro. La franja tiene que contrastar
    con él y, además, tener borde o acercarse a un color de barra.
    """
    if width < 4 or height < 4 or len(rgb) < width * height * 3:
        return False
    band = max(1, min(height // 8, 48))
    background = _dominant_background(rgb, width, height, band)
    for y0, y1 in ((0, band), (height - band, height)):
        mean = _region_mean(rgb, width, y0, y1)
        if _band_is_bar(mean, background, _edge_density(rgb, width, height, y0, y1)):
            return True
    return False


def change_ratio(before: bytes, after: bytes) -> float:
    if not before or len(before) != len(after):
        return 1.0
    changed = 0
    pixels = len(before) // 3
    for index in range(0, len(before), 3):
        if before[index:index + 3] != after[index:index + 3]:
            changed += 1
    return changed / pixels if pixels else 1.0


# Botones de wlogout: fondo y borde de
# archiso/airootfs/etc/skel/.config/wlogout/style.css (colors-waybar.css).
WLOGOUT_BUTTON = (0x2A, 0x16, 0x12)
WLOGOUT_ACCENT = (0xDE, 0x86, 0x36)
WLOGOUT_BUTTON2 = 32 * 32
WLOGOUT_ACCENT2 = 36 * 36


def _cell(rgb: bytes, index: int) -> tuple[int, int, int]:
    return rgb[index], rgb[index + 1], rgb[index + 2]


def _wlogout_grid(before: bytes, after: bytes, width: int, height: int) -> bool:
    """Rejilla de botones centrada, distinta de la base. Un cambio suelto no basta."""
    x0, x1 = width // 6, width - width // 6
    y0, y1 = height // 5, height - height // 6
    if x1 - x0 < 8 or y1 - y0 < 8:
        return False
    stride = 1 if width * height <= 80 * 80 else 4
    xs = list(range(x0, x1, stride))
    ys = list(range(y0, y1, stride))
    if len(xs) < 4 or len(ys) < 4:
        return False
    mask = []
    accent = 0
    for y in ys:
        row = []
        for x in xs:
            index = (y * width + x) * 3
            now = _cell(after, index)
            was = _cell(before, index)
            moved = _dist2(now, was) >= 18 * 18
            row.append(_dist2(now, WLOGOUT_BUTTON) <= WLOGOUT_BUTTON2 and moved)
            if moved and _dist2(now, WLOGOUT_ACCENT) <= WLOGOUT_ACCENT2:
                accent += 1
        mask.append(row)
    seen = [[False] * len(xs) for _ in ys]
    columns = set()
    blobs = 0
    for y, row in enumerate(mask):
        for x, hit in enumerate(row):
            if not hit or seen[y][x]:
                continue
            stack = [(x, y)]
            seen[y][x] = True
            size = 0
            acc_x = 0
            while stack:
                cx, cy = stack.pop()
                size += 1
                acc_x += cx
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < len(xs) and 0 <= ny < len(ys) and mask[ny][nx] and not seen[ny][nx]:
                        seen[ny][nx] = True
                        stack.append((nx, ny))
            if size >= 4:
                blobs += 1
                columns.add(acc_x // size)
    return blobs >= 3 and len(columns) >= 2 and accent >= 3


def session_menu_visible(before: bytes, after: bytes, width: int, height: int) -> tuple[bool, str]:
    """wlogout es una rejilla de botones centrada. Cerrar el overlay no cuenta."""
    if len(before) != len(after) or width * height * 3 != len(after):
        return False, "menu-not-visible:size"
    if change_ratio(before, after) < 0.01:
        return False, "menu-not-visible:unchanged"
    kind = classify_frame(width, height, after)
    if kind in {"text", "blank"}:
        return False, f"menu-not-visible:{kind}"
    if _wlogout_grid(before, after, width, height):
        return True, "wlogout"
    return False, "menu-not-visible:not-wlogout"


def differs_from_desktop(before: bytes, after: bytes, width: int, height: int) -> tuple[bool, str]:
    """La pantalla del diff no puede ser el escritorio con otro nombre."""
    if len(before) != len(after) or width * height * 3 != len(after):
        return False, "same-as-desktop:size"
    if change_ratio(before, after) < 0.08:
        return False, "same-as-desktop"
    x0, x1 = width // 4, width - width // 4
    y0, y1 = height // 4, height - height // 4
    changed = 0
    total = 0
    for y in range(y0, y1):
        row = y * width * 3
        for x in range(x0, x1):
            index = row + x * 3
            total += 1
            if before[index:index + 3] != after[index:index + 3]:
                changed += 1
    if total == 0 or changed / total < 0.08:
        return False, "same-as-desktop:center"
    return True, "changed"


def assess_image(
    width: int, height: int, rgb: bytes, expect_w: int, expect_h: int, require_bar: bool = False,
) -> tuple[bool, str]:
    kind = classify_frame(width, height, rgb)
    if kind in {"text", "blank"}:
        return False, f"not-graphical:{kind}"
    if (width, height) != (expect_w, expect_h):
        return False, f"wrong-resolution:{width}x{height}"
    if require_bar and not has_bar(width, height, rgb):
        return False, "no-bar"
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
        kind = classify_frame(width, height, rgb)
        ready = state.feed(kind, frame_signature(rgb, width, height), has_bar(width, height, rgb))
        if ready:
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
    assess_cmd.add_argument("--require-bar", action="store_true")
    menu_cmd = sub.add_parser("menu-visible")
    menu_cmd.add_argument("--before", type=Path, required=True)
    menu_cmd.add_argument("--after", type=Path, required=True)
    differs_cmd = sub.add_parser("differs")
    differs_cmd.add_argument("--before", type=Path, required=True)
    differs_cmd.add_argument("--after", type=Path, required=True)
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
    if args.cmd == "menu-visible":
        before_w, before_h, before_rgb = read_png(args.before)
        after_w, after_h, after_rgb = read_png(args.after)
        if (before_w, before_h) != (after_w, after_h):
            print("menu-not-visible:size")
            return 1
        ok, reason = session_menu_visible(before_rgb, after_rgb, after_w, after_h)
        print(reason)
        return 0 if ok else 1
    if args.cmd == "differs":
        before_w, before_h, before_rgb = read_png(args.before)
        after_w, after_h, after_rgb = read_png(args.after)
        if (before_w, before_h) != (after_w, after_h):
            print("same-as-desktop:size")
            return 1
        ok, reason = differs_from_desktop(before_rgb, after_rgb, after_w, after_h)
        print(reason)
        return 0 if ok else 1
    width, height, rgb = read_png(args.png)
    ok, reason = assess_image(width, height, rgb, args.width, args.height, args.require_bar)
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
