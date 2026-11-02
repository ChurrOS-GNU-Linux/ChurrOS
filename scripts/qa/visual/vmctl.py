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


def _xwd(dest: Path) -> str:
    display = os.environ.get("VISUAL_QA_XWD_DISPLAY", "")
    if not display or not shutil.which("xwd"):
        raise QmpError("screendump no disponible")
    result = subprocess.run(
        ["xwd", "-silent", "-display", display, "-root"],
        capture_output=True, timeout=60, check=False,
    )
    if result.returncode != 0 or len(result.stdout) < 100:
        raise QmpError("xwd no capturó la pantalla")
    width, height, rgb = xwd_to_rgb(result.stdout)
    write_png(dest, width, height, rgb)
    return "xwd"


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
