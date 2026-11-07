#!/usr/bin/env python3
"""PPM y PNG de 8 bits sin dependencias, para las capturas de QEMU."""
from __future__ import annotations

from pathlib import Path
import struct
import zlib


def read_ppm(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if not data.startswith(b"P6"):
        raise ValueError("no es un PPM P6")
    tokens: list[bytes] = []
    index = 0
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
    rgb = data[index + 1:index + 1 + width * height * 3]
    if len(rgb) != width * height * 3:
        raise ValueError("PPM incompleto")
    return width, height, rgb


def write_png(path: Path, width: int, height: int, rgb: bytes) -> None:
    if len(rgb) != width * height * 3:
        raise ValueError("el buffer RGB no mide width*height*3")

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    stride = width * 3
    raw = b"".join(b"\x00" + rgb[row * stride:(row + 1) * stride] for row in range(height))
    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def read_png(path: Path) -> tuple[int, int, bytes]:
    """PNG no entrelazado, color 8 bits, filtro None. El que escribe write_png."""
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("no es un PNG")
    pos = 8
    width = height = None
    idat = b""
    while pos + 8 <= len(data):
        length = struct.unpack(">I", data[pos:pos + 4])[0]
        kind = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            width, height, bit, color, _comp, _filt, inter = struct.unpack(">IIBBBBB", body)
            if bit != 8 or color != 2 or inter != 0:
                raise ValueError("PNG no soportado (hace falta RGB de 8 bits, sin entrelazar)")
        elif kind == b"IDAT":
            idat += body
        elif kind == b"IEND":
            break
    if width is None or height is None:
        raise ValueError("PNG sin IHDR")
    raw = zlib.decompress(idat)
    stride = width * 3
    rows = []
    index = 0
    for _ in range(height):
        if index >= len(raw) or raw[index] != 0:
            raise ValueError("filtro PNG distinto de None")
        index += 1
        rows.append(raw[index:index + stride])
        index += stride
    return width, height, b"".join(rows)


def ppm_to_png(ppm: Path, png: Path) -> None:
    width, height, rgb = read_ppm(ppm)
    write_png(png, width, height, rgb)
