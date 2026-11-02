#!/usr/bin/env python3
"""Control mínimo de QEMU por QMP para la QA visual.

screendump, send-key, wait-serial, quit y free-display. No imprime
entornos ni claves. Si QMP no puede capturar (una salida GL responde
«no surface»), y VISUAL_QA_XWD_DISPLAY apunta a un Xvfb, intenta xwd.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import socket
import struct
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imageutil import ppm_to_png, write_png  # noqa: E402


class QmpError(RuntimeError):
    pass


class Qmp:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(path))
        self.buffer = b""
        self._recv()
        self.execute("qmp_capabilities")

    def execute(self, command: str, arguments: dict | None = None) -> dict:
        message = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        try:
            self.sock.sendall(json.dumps(message).encode() + b"\n")
        except OSError as exc:
            raise QmpError(str(exc)) from None
        while True:
            reply = self._recv()
            if "event" in reply:
                continue
            if "error" in reply:
                desc = reply["error"].get("desc", "error") if isinstance(reply["error"], dict) else "error"
                raise QmpError(desc)
            return reply.get("return", {})

    def _recv(self) -> dict:
        while b"\n" not in self.buffer:
            try:
                chunk = self.sock.recv(65536)
            except OSError as exc:
                raise QmpError(str(exc)) from None
            if not chunk:
                raise QmpError("socket cerrado")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        line = line.strip().lstrip(b"\xff")
        if not line:
            return self._recv()
        try:
            return json.loads(line)
        except json.JSONDecodeError as exc:
            raise QmpError("respuesta no es JSON") from exc

    def close(self) -> None:
        self.sock.close()


def xwd_to_rgb(data: bytes) -> tuple[int, int, bytes]:
    fields = struct.unpack(">25I", data[:100])
    header_size, _version, pixmap_format, depth, width, height = fields[:6]
    byte_order, bits_per_pixel, bytes_per_line = fields[7], fields[11], fields[12]
    red_mask, green_mask, blue_mask, ncolors = fields[14], fields[15], fields[16], fields[19]
    if pixmap_format != 2 or bits_per_pixel not in (24, 32) or depth < 24:
        raise QmpError("formato XWD no soportado")
    pixels = data[header_size + ncolors * 12:]
    step = bits_per_pixel // 8
    endian = "little" if byte_order == 0 else "big"
    shifts = [(mask, (mask & -mask).bit_length() - 1) for mask in (red_mask, green_mask, blue_mask)]
    out = bytearray(width * height * 3)
    index = 0
    for row in range(height):
        line = pixels[row * bytes_per_line:row * bytes_per_line + width * step]
        for column in range(0, width * step, step):
            value = int.from_bytes(line[column:column + step], endian)
            for mask, shift in shifts:
                out[index] = (value & mask) >> shift
                index += 1
    return width, height, bytes(out)


def screendump(socket_path: Path, dest: Path) -> str:
    dest.parent.mkdir(parents=True, exist_ok=True)
    ppm = dest.with_suffix(".ppm")
    try:
        qmp = Qmp(socket_path)
    except OSError as exc:
        raise QmpError(f"sin QMP: {exc}") from None
    try:
        qmp.execute("screendump", {"filename": str(ppm.resolve())})
    except QmpError:
        qmp.close()
        return _xwd(dest)
    else:
        qmp.close()
    if not ppm.is_file():
        return _xwd(dest)
    ppm_to_png(ppm, dest)
    ppm.unlink(missing_ok=True)
    return "qmp-screendump"


def crop_to_content(width: int, height: int, rgb: bytes) -> tuple[int, int, bytes]:
    """Recorta al rectángulo con píxeles no negros."""
    rows = [y for y in range(height) if any(rgb[y * width * 3:(y + 1) * width * 3])]
    if not rows:
        return 1, 1, b"\0\0\0"
    top, bottom = rows[0], rows[-1]
    left, right = width, -1
    for y in range(top, bottom + 1):
        line = rgb[y * width * 3:(y + 1) * width * 3]
        first = next((x for x in range(width) if any(line[x * 3:x * 3 + 3])), None)
        if first is None:
            continue
        last = next(x for x in range(width - 1, -1, -1) if any(line[x * 3:x * 3 + 3]))
        left, right = min(left, first), max(right, last)
    new_width = right - left + 1
    out = b"".join(rgb[(y * width + left) * 3:(y * width + right + 1) * 3] for y in range(top, bottom + 1))
    return new_width, bottom - top + 1, out


def guest_size() -> tuple[int, int]:
    width = int(os.environ.get("VISUAL_QA_GUEST_WIDTH", "1920"))
    height = int(os.environ.get("VISUAL_QA_GUEST_HEIGHT", "1080"))
    return width, height


def xwd_selectors(name: str) -> list[list[str]]:
    """Ventana de QEMU, nunca la raíz del Xvfb (queda desplazada y recortada)."""
    return [
        ["-name", f"QEMU ({name}-0)"],
        ["-name", f"QEMU ({name})"],
        ["-name", name],
    ]


def pin_qemu_window(display: str) -> None:
    """SDL recentra al cambiar de tamaño. xdotool la devuelve a 0,0 si está."""
    if not display or not shutil.which("xdotool"):
        return
    name = os.environ.get("VISUAL_QA_QEMU_NAME", "churros-visual-qa")
    env = dict(os.environ)
    env["DISPLAY"] = display
    for title in (f"QEMU ({name}-0)", f"QEMU ({name})", name):
        subprocess.run(
            ["xdotool", "search", "--name", title, "windowmove", "0", "0"],
            env=env, capture_output=True, timeout=10, check=False,
        )


def fit_guest(width: int, height: int, rgb: bytes) -> tuple[int, int, bytes]:
    """Se queda con la ventana si ya es la resolución del invitado; si no, recorta el negro."""
    expect_w, expect_h = guest_size()
    if (width, height) == (expect_w, expect_h):
        return width, height, rgb
    cropped_w, cropped_h, cropped = crop_to_content(width, height, rgb)
    if (cropped_w, cropped_h) == (expect_w, expect_h):
        return cropped_w, cropped_h, cropped
    if os.environ.get("VISUAL_QA_REQUIRE_SIZE") == "1":
        raise QmpError(f"wrong-resolution:{cropped_w}x{cropped_h}")
    return cropped_w, cropped_h, cropped


def _xwd_bytes(display: str) -> bytes:
    if not shutil.which("xwd"):
        raise QmpError("screendump no disponible")
    pin_qemu_window(display)
    name = os.environ.get("VISUAL_QA_QEMU_NAME", "churros-visual-qa")
    for selector in xwd_selectors(name):
        result = subprocess.run(
            ["xwd", "-silent", "-display", display, *selector],
            capture_output=True, timeout=60, check=False,
        )
        if result.returncode == 0 and len(result.stdout) > 100:
            return result.stdout
    raise QmpError("xwd no encontró la ventana de QEMU")


def _xwd(dest: Path) -> str:
    display = os.environ.get("VISUAL_QA_XWD_DISPLAY", "")
    if not display:
        raise QmpError("screendump no disponible")
    width, height, rgb = xwd_to_rgb(_xwd_bytes(display))
    width, height, rgb = fit_guest(width, height, rgb)
    write_png(dest, width, height, rgb)
    return "xwd-window"


def free_display() -> int:
    for display in range(64):
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 5900 + display))
        except OSError:
            continue
        else:
            return display
        finally:
            sock.close()
    raise QmpError("no hay un puerto VNC libre")


def wait_serial(path: Path, pattern: str, timeout: float) -> bool:
    compiled = re.compile(pattern)
    deadline = time.monotonic() + timeout
    while True:
        if path.is_file() and compiled.search(path.read_text(encoding="utf-8", errors="replace")):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Control QMP de la VM de QA visual.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    dump = sub.add_parser("screendump")
    dump.add_argument("--socket", type=Path, required=True)
    dump.add_argument("--out", type=Path, required=True)

    keys = sub.add_parser("send-key")
    keys.add_argument("--socket", type=Path, required=True)
    keys.add_argument("--key", action="append", required=True)

    serial = sub.add_parser("wait-serial")
    serial.add_argument("--log", type=Path, required=True)
    serial.add_argument("--pattern", required=True)
    serial.add_argument("--timeout", type=float, default=30.0)

    quit_cmd = sub.add_parser("quit")
    quit_cmd.add_argument("--socket", type=Path, required=True)

    sub.add_parser("free-display")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "free-display":
            print(free_display())
            return 0
        if args.cmd == "wait-serial":
            return 0 if wait_serial(args.log, args.pattern, args.timeout) else 1
        if args.cmd == "screendump":
            method = screendump(args.socket, args.out)
            print(method)
            return 0
        qmp = Qmp(args.socket)
        try:
            if args.cmd == "quit":
                qmp.execute("quit")
            else:
                qmp.execute("send-key", {"keys": [{"type": "qcode", "data": key} for key in args.key]})
        finally:
            qmp.close()
    except QmpError as exc:
        print(f"visual-qa: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
