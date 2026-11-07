#!/usr/bin/env python3
"""Saca colores, familias y medidas de las guías de marca.

Las fuentes son branding/colors.md, typography.md, ui-guidelines.md,
logo-guidelines.md y docs/branding.md. Si dos guías no dicen lo mismo,
el conflicto queda en la lista para que el informe lo marque.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

SOURCES = (
    "branding/colors.md",
    "branding/typography.md",
    "branding/ui-guidelines.md",
    "branding/logo-guidelines.md",
    "docs/branding.md",
)

UI_ROLES = {
    "Naranja principal": "primary",
    "Hover": "hover",
    "Fondo": "background",
    "Paneles": "panel",
    "Texto": "text",
    "Texto secundario": "text-secondary",
}


def section(text: str, title: str) -> str:
    match = re.search(
        rf"(?ms)^#{{1,2}} {re.escape(title)}\s*\n(.*?)(?=^#{{1,2}} |\Z)",
        text,
    )
    return match.group(1) if match else ""


def parse_colors_md(text: str) -> list[dict]:
    items = []
    for chunk in re.split(r"(?m)^## ", text)[1:]:
        lines = [line.strip() for line in chunk.splitlines() if line.strip() and line.strip() != "---"]
        if not lines:
            continue
        heading = lines[0]
        role = heading.split()[0].lower()
        name = ""
        before_hex = []
        for line in lines[1:]:
            if re.search(r"#[0-9A-Fa-f]{6}\b", line):
                break
            before_hex.append(line)
        for line in before_hex:
            if line.upper() == "HEX" or line.startswith("#") or line in {"RGB", "Uso"} or line.startswith("-"):
                continue
            if re.fullmatch(r"[\d ]+", line):
                continue
            name = line
            break
        for digits in re.findall(r"#([0-9A-Fa-f]{6})\b", chunk):
            items.append({
                "hex": f"#{digits.upper()}",
                "name": name or heading,
                "role": role,
                "source": "branding/colors.md",
            })
    return items


def parse_ui_colors(text: str) -> list[dict]:
    items = []
    for match in re.finditer(r"^-\s+([^:\n`]+):\s+`#([0-9A-Fa-f]{6})`", text, re.M):
        label = match.group(1).strip()
        items.append({
            "hex": f"#{match.group(2).upper()}",
            "name": label,
            "role": UI_ROLES.get(label, "other"),
            "source": "branding/ui-guidelines.md",
        })
    return items


def parse_ui_fonts(text: str) -> list[dict]:
    block = section(text, "Tipografía")
    roles = {
        "JetBrains Mono": "text",
        "Symbols Nerd Font Mono": "icons",
        "Noto Sans": "fallback",
    }
    items = []
    for family in re.findall(r"`([^`]+)`", block):
        if family not in roles:
            continue
        items.append({
            "family": family,
            "role": roles[family],
            "source": "branding/ui-guidelines.md",
        })
    return items


def parse_typography(text: str) -> list[dict]:
    items = []
    for title, role in (("UI", "ui"), ("Terminal", "terminal")):
        block = section(text, title)
        for line in block.splitlines():
            name = line.strip()
            if name and name != "---" and not name.startswith("#"):
                items.append({
                    "family": name,
                    "role": role,
                    "source": "branding/typography.md",
                })
                break
    return items


def parse_branding_doc(text: str) -> list[dict]:
    items = []
    seen = set()
    for digits in re.findall(r"#([0-9A-Fa-f]{6})\b", text):
        hex_value = f"#{digits.upper()}"
        if hex_value in seen:
            continue
        seen.add(hex_value)
        if hex_value == "#0F0F10":
            name, role = "Rectangle del slideshow", "installer-background"
        else:
            name, role = "mencionado en la documentación", "mentioned"
        items.append({
            "hex": hex_value,
            "name": name,
            "role": role,
            "source": "docs/branding.md",
        })
    return items


def parse_metrics(ui_text: str, logo_text: str) -> dict:
    def numbers(block: str) -> list[int]:
        return [int(value) for value in re.findall(r"(\d+)", block)]

    borders = numbers(section(ui_text, "Bordes"))
    spacing = numbers(section(ui_text, "Espaciado"))
    animation = numbers(section(ui_text, "Animaciones"))
    opacity = [value / 100 for value in numbers(section(ui_text, "Transparencia"))]
    symbol = re.search(r"símbolo por debajo de (\d+) px", logo_text)
    full = re.search(r"logotipo completo por debajo de (\d+) px", logo_text)
    return {
        "radius_px": borders[0] if borders else None,
        "spacing_px": spacing,
        "animation_ms": animation,
        "opacity": opacity,
        "logo_min_symbol_px": int(symbol.group(1)) if symbol else None,
        "logo_min_full_px": int(full.group(1)) if full else None,
    }


def conflicts(colors: list[dict], fonts: list[dict]) -> list[str]:
    found = []
    backgrounds = [item for item in colors if item["role"] in {"background", "installer-background"}]
    unique = {(item["hex"], item["source"]) for item in backgrounds}
    if len({hex_value for hex_value, _source in unique}) > 1:
        detail = ", ".join(f"{hex_value} ({source})" for hex_value, source in sorted(unique))
        found.append(f"El fondo no coincide entre guías: {detail}.")
    by_source: dict[str, list[str]] = {}
    for font in fonts:
        by_source.setdefault(font["source"], [])
        if font["family"] not in by_source[font["source"]]:
            by_source[font["source"]].append(font["family"])
    typography = by_source.get("branding/typography.md", [])
    ui = by_source.get("branding/ui-guidelines.md", [])
    if typography and ui and set(typography) != set(ui):
        found.append(
            "Las familias no coinciden: typography.md cita "
            + ", ".join(typography)
            + "; ui-guidelines.md cita "
            + ", ".join(ui)
            + "."
        )
    return found


def extract(root: Path) -> dict:
    texts = {name: (root / name).read_text(encoding="utf-8") for name in SOURCES}
    colors = (
        parse_colors_md(texts["branding/colors.md"])
        + parse_ui_colors(texts["branding/ui-guidelines.md"])
        + parse_branding_doc(texts["docs/branding.md"])
    )
    fonts = parse_typography(texts["branding/typography.md"]) + parse_ui_fonts(texts["branding/ui-guidelines.md"])
    colors.sort(key=lambda item: (item["source"], item["role"], item["hex"], item["name"]))
    fonts.sort(key=lambda item: (item["source"], item["role"], item["family"]))
    return {
        "sources": list(SOURCES),
        "colors": colors,
        "fonts": fonts,
        "metrics": parse_metrics(texts["branding/ui-guidelines.md"], texts["branding/logo-guidelines.md"]),
        "conflicts": conflicts(colors, fonts),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extrae los tokens de las guías de marca.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    payload = extract(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
