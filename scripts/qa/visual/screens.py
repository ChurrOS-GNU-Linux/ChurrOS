#!/usr/bin/env python3
"""Elige las pantallas que hay que capturar a partir de las rutas del diff.

El orden es fijo para que las tomas de main y del PR se llamen igual.
Si ninguna regla casa (un diff ambiguo que Jev marcó como visual), se
pide el escritorio: es el ancla para comparar.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ORDER = ("grub", "plymouth", "desktop", "bar", "launcher", "session-menu", "installer")

RULES = {
    "grub": ("grub-theme/",),
    "plymouth": ("plymouth/",),
    "bar": ("waybar/", "noctalia/"),
    "launcher": ("fuzzel/",),
    "session-menu": ("wlogout/",),
    "installer": ("installer/calamares/branding/",),
    "desktop": (
        "niri/",
        "branding/",
        "churros-theme",
        "color-schemes/",
        "usr/share/churros/styles/",
        "usr/share/churros/defaults/",
        "usr/share/churros/pi/",
        "wallpapers/",
        "/icons/",
    ),
}


def normalize(path: str) -> str:
    text = path.replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text


def screens_for_paths(paths: list[str]) -> list[str]:
    texts = [normalize(path) for path in paths if normalize(path)]
    chosen = []
    for screen in ORDER:
        markers = RULES[screen]
        if any(marker in path for path in texts for marker in markers):
            chosen.append(screen)
    return chosen or ["desktop"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan de pantallas de la QA visual.")
    parser.add_argument("--paths-file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    paths = list(args.paths)
    if args.paths_file:
        paths.extend(args.paths_file.read_text(encoding="utf-8").splitlines())
    plan = {"screens": screens_for_paths(paths), "paths": [normalize(p) for p in paths if normalize(p)]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
