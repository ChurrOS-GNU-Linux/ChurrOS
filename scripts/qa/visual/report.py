#!/usr/bin/env python3
"""Empareja las capturas de main y del PR y escribe el informe.

HTML y Markdown con la pareja, el diff de píxeles y una imagen lado a
lado por pantalla. Los píxeles se comparan con la paleta de
scripts/qa/visual/design-tokens.json: si el naranja o un fondo de marca
no aparecen, la lista lo marca. Una pareja también se marca si falta un
lado, si el tamaño no coincide o si la fracción de píxeles distintos
supera el umbral (por defecto 0.01). Los conflictos entre guías se listan
aparte: ya estaban en la documentación.

Sale 0 aunque haya desviaciones. El comentario del PR es el resumen, no
un check que impida fusionar.
"""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from imageutil import read_png, write_png  # noqa: E402

MARKER = "<!-- visual-qa-report -->"
DEFAULT_THRESHOLD = 0.01
PALETTE_DISTANCE = 72
ARCH_BLUE = (23, 147, 209)  # #1793D1, el azul del logo de Arch Linux
PALETTE_ROLES = {
    "primary", "background", "text", "secondary", "hover", "panel",
    "installer-background", "success", "warning", "error",
}
BRANDED_SCREENS = {"desktop", "bar", "launcher", "session-menu", "installer", "grub", "plymouth"}


def read_threshold(value: str | None) -> float:
    if value is None or not str(value).strip():
        return DEFAULT_THRESHOLD
    number = float(str(value).strip())
    if not 0.0 <= number <= 1.0:
        raise ValueError("el umbral del diff tiene que estar entre 0 y 1")
    return number


def png_names(directory: Path) -> set[str]:
    if not directory.is_dir():
        return set()
    return {path.name for path in directory.glob("*.png")}


def compare_pair(before: Path | None, after: Path | None, diff_path: Path, threshold: float) -> dict:
    if before is None or not before.is_file() or after is None or not after.is_file():
        missing = "before" if before is None or not (before and before.is_file()) else "after"
        return {"ratio": None, "deviation": True, "reason": f"missing-{missing}"}
    try:
        width_a, height_a, rgb_a = read_png(before)
        width_b, height_b, rgb_b = read_png(after)
    except (OSError, ValueError) as exc:
        return {"ratio": None, "deviation": True, "reason": f"unsupported:{exc}"}
    if (width_a, height_a) != (width_b, height_b):
        return {
            "ratio": None,
            "deviation": True,
            "reason": "size",
            "before_size": [width_a, height_a],
            "after_size": [width_b, height_b],
        }
    changed = 0
    diff = bytearray(len(rgb_a))
    total = width_a * height_a or 1
    for index in range(0, len(rgb_a), 3):
        if rgb_a[index:index + 3] != rgb_b[index:index + 3]:
            changed += 1
            diff[index:index + 3] = b"\xff\x00\x00"
        else:
            diff[index] = rgb_a[index] // 3
            diff[index + 1] = rgb_a[index + 1] // 3
            diff[index + 2] = rgb_a[index + 2] // 3
    ratio = changed / total
    diff_path.parent.mkdir(parents=True, exist_ok=True)
    write_png(diff_path, width_a, height_a, bytes(diff))
    return {
        "ratio": ratio,
        "changed_pixels": changed,
        "deviation": ratio > threshold,
        "reason": "pixels" if ratio > threshold else "ok",
    }


def parse_hex(value: str) -> tuple[int, int, int]:
    text = value.removeprefix("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def palette_entries(tokens: dict) -> list[dict]:
    found = []
    seen = set()
    for color in tokens.get("colors", []):
        if color.get("role") not in PALETTE_ROLES:
            continue
        key = (str(color.get("hex", "")).upper(), color.get("role"))
        if key in seen or len(key[0]) != 7:
            continue
        seen.add(key)
        found.append(color)
    return found


def sample_pixels(rgb: bytes, width: int, height: int) -> list[tuple[int, int, int]]:
    total = width * height
    step = 1 if total <= 4096 else max(1, int((total / 4000) ** 0.5))
    pixels = []
    for y in range(0, height, step):
        row = y * width * 3
        for x in range(0, width, step):
            index = row + x * 3
            pixels.append((rgb[index], rgb[index + 1], rgb[index + 2]))
    return pixels


def color_distance(left: tuple[int, int, int], right: tuple[int, int, int]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2 + (left[2] - right[2]) ** 2) ** 0.5


def nearest_distance(pixels: list[tuple[int, int, int]], target: tuple[int, int, int]) -> float:
    if not pixels:
        return 999.0
    return min(color_distance(pixel, target) for pixel in pixels)


def palette_findings(name: str, images: list[tuple[str, bytes, int, int]], tokens: dict, limit: float = PALETTE_DISTANCE) -> list[dict]:
    """Compara píxeles muestreados con la paleta. Vacío si no hay captura."""
    screen = Path(name).stem
    if screen not in BRANDED_SCREENS:
        return []
    palette = palette_entries(tokens)
    primaries = [parse_hex(item["hex"]) for item in palette if item["role"] == "primary"]
    backgrounds = [parse_hex(item["hex"]) for item in palette if item["role"] in {"background", "installer-background"}]
    findings = []
    for label, rgb, width, height in images:
        pixels = sample_pixels(rgb, width, height)
        if primaries and screen in {"desktop", "bar", "launcher", "session-menu", "installer"}:
            distance = min(nearest_distance(pixels, color) for color in primaries)
            if distance > limit:
                findings.append({
                    "status": "deviation",
                    "text": f"{name} ({label}): el naranja de marca no aparece (distancia {distance:.0f}).",
                })
        if backgrounds:
            distance = min(nearest_distance(pixels, color) for color in backgrounds)
            if distance > limit:
                findings.append({
                    "status": "deviation",
                    "text": f"{name} ({label}): ningún fondo de la paleta está cerca (distancia {distance:.0f}).",
                })
        if screen == "grub" and arch_logo_pixels(pixels, palette):
            findings.append({
                "status": "deviation",
                "text": f"{name} ({label}): se ve el logo de Arch (#1793D1), no solo el fondo.",
            })
    return findings


def arch_logo_pixels(pixels: list[tuple[int, int, int]], palette: list[dict], near: float = 48, far: float = 60) -> bool:
    """Azul de Arch que no encaja en la paleta de ChurrOS."""
    known = [parse_hex(item["hex"]) for item in palette]
    for pixel in pixels:
        if color_distance(pixel, ARCH_BLUE) > near:
            continue
        if not known or min(color_distance(pixel, color) for color in known) > far:
            return True
    return False


def load_manifest(directory: Path) -> dict:
    path = directory / "manifest.json"
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def shot_reason(manifest: dict, stem: str) -> str:
    """Causa si esa pantalla quedó ok:false. Un PNG en disco no la absuelve."""
    status = str(manifest.get("status") or "")
    found = None
    for shot in manifest.get("shots") or []:
        if not isinstance(shot, dict):
            continue
        shot_id = str(shot.get("id") or "")
        shot_file = Path(str(shot.get("file") or "")).stem
        if shot_id == stem or shot_file == stem:
            found = shot
            break
    if found is None:
        screens = {str(screen).removesuffix(".png") for screen in manifest.get("screens") or []}
        if stem in screens and status and status not in {"captured", "dry-run"}:
            return status
        return ""
    if found.get("ok") is not False:
        return ""
    method = str(found.get("method") or "failed")
    if status and status not in {"captured", "dry-run"}:
        return f"{status}:{method}"
    return method


def planned_names(*manifests: dict, files: set[str]) -> list[str]:
    names = set(files)
    for manifest in manifests:
        for screen in manifest.get("screens") or []:
            text = str(screen)
            names.add(text if text.endswith(".png") else f"{text}.png")
        for shot in manifest.get("shots") or []:
            if not isinstance(shot, dict):
                continue
            if shot.get("file"):
                names.add(str(shot["file"]))
            elif shot.get("id"):
                names.add(f"{shot['id']}.png")
    return sorted(names)


def _unify_boot_absence(before_detail: str, after_detail: str) -> tuple[str, str]:
    """Plymouth ausente es una sola causa aunque el estado del job no coincida."""
    def bare(detail: str) -> str:
        if detail == "not-in-boot" or detail.endswith(":not-in-boot"):
            return "not-in-boot"
        return detail

    if bare(before_detail) == "not-in-boot" and bare(after_detail) == "not-in-boot":
        return "not-in-boot", "not-in-boot"
    return before_detail, after_detail


def pair_reason(before_missing: bool, after_missing: bool, before_detail: str, after_detail: str) -> str | None:
    before_detail, after_detail = _unify_boot_absence(before_detail, after_detail)
    if not before_missing and not after_missing:
        if not before_detail and not after_detail:
            return None
        if before_detail and before_detail == after_detail:
            return f"failed:{before_detail}"
        return f"failed:{before_detail or 'ok'}|{after_detail or 'ok'}"
    if before_missing and after_missing:
        if before_detail and before_detail == after_detail:
            return f"missing:{before_detail}"
        if before_detail or after_detail:
            return f"missing:{before_detail or 'missing'}|{after_detail or 'missing'}"
        return "missing"
    if before_missing:
        reason = f"missing-before:{before_detail}" if before_detail else "missing-before"
        if after_detail:
            reason = f"{reason};after:{after_detail}"
        return reason
    reason = f"missing-after:{after_detail}" if after_detail else "missing-after"
    if before_detail:
        reason = f"{reason};before:{before_detail}"
    return reason


def side_by_side(panels: list[tuple[int, int, bytes]], gap: int = 4) -> tuple[int, int, bytes]:
    """Antes, después y diff en una sola imagen, separados por una franja negra."""
    if not panels:
        return 1, 1, b"\x00\x00\x00"
    height = max(panel_h for _panel_w, panel_h, _rgb in panels)
    width = sum(panel_w for panel_w, _panel_h, _rgb in panels) + gap * (len(panels) - 1)
    canvas = bytearray(width * height * 3)
    origin = 0
    for panel_w, panel_h, rgb in panels:
        for y in range(panel_h):
            src = y * panel_w * 3
            dest = (y * width + origin) * 3
            canvas[dest:dest + panel_w * 3] = rgb[src:src + panel_w * 3]
        origin += panel_w + gap
    return width, height, bytes(canvas)


def load_panel(path: Path | None, fallback_w: int, fallback_h: int) -> tuple[int, int, bytes]:
    if path is not None and path.is_file():
        try:
            return read_png(path)
        except (OSError, ValueError):
            pass
    width = fallback_w or 1
    height = fallback_h or 1
    return width, height, bytes(width * height * 3)


def checklist(tokens: dict, palette_items: list[dict] | None = None) -> list[dict]:
    items = list(palette_items or [])
    for color in tokens.get("colors", []):
        items.append({
            "status": "info",
            "text": f"{color['name']} {color['hex']} ({color['role']}, {color['source']})",
        })
    for font in tokens.get("fonts", []):
        items.append({
            "status": "info",
            "text": f"{font['family']} ({font['role']}, {font['source']})",
        })
    metrics = tokens.get("metrics") or {}
    if metrics.get("logo_min_symbol_px") or metrics.get("logo_min_full_px"):
        items.append({
            "status": "review",
            "text": (
                f"Símbolo como mínimo {metrics.get('logo_min_symbol_px')} px; "
                f"logotipo completo como mínimo {metrics.get('logo_min_full_px')} px."
            ),
        })
    for conflict in tokens.get("conflicts", []):
        items.append({"status": "known-conflict", "text": conflict})
    return items


def rel(path: Path | None, start: Path) -> str | None:
    if path is None or not path.is_file():
        return None
    return Path(os.path.relpath(path, start)).as_posix()


def render_markdown(report: dict) -> str:
    lines = [
        "# Comparación visual",
        "",
        f"Pares: {report['pairs_total']}. Desviaciones: {report['deviations']}. "
        f"Umbral de píxeles: {report['threshold']}.",
        "",
        "| Pantalla | Píxeles distintos | Estado |",
        "|---|---:|---|",
    ]
    for pair in report["pairs"]:
        ratio = "—" if pair["ratio"] is None else f"{pair['ratio'] * 100:.2f}%"
        lines.append(f"| {pair['name']} | {ratio} | {pair['reason']} |")
    lines.extend(["", "## Lista de las guías", ""])
    for item in report["checklist"]:
        lines.append(f"- `{item['status']}` {item['text']}")
    lines.append("")
    return "\n".join(lines)


def render_html(report: dict) -> str:
    rows = []
    for pair in report["pairs"]:
        def cell(src: str | None) -> str:
            if not src:
                return "<td>no está</td>"
            return f"<td><img src=\"{html.escape(src)}\" alt=\"\"></td>"
        ratio = "—" if pair["ratio"] is None else f"{pair['ratio'] * 100:.2f}%"
        mark = "desviación" if pair["deviation"] else "igual"
        rows.append(
            "<tr>"
            f"<th>{html.escape(pair['name'])}</th>"
            f"{cell(pair.get('side_src'))}"
            f"{cell(pair.get('before_src'))}{cell(pair.get('after_src'))}{cell(pair.get('diff_src'))}"
            f"<td>{ratio}</td><td>{html.escape(mark)} ({html.escape(pair['reason'])})</td>"
            "</tr>"
        )
    checks = "\n".join(
        f"<li><code>{html.escape(item['status'])}</code> {html.escape(item['text'])}</li>"
        for item in report["checklist"]
    )
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<title>Comparación visual</title>
<style>
body {{ font: 16px/1.4 sans-serif; margin: 2rem; background: #111827; color: #F8FAFC; }}
img {{ max-width: 320px; background: #1F2937; }}
table {{ border-collapse: collapse; }}
th, td {{ border: 1px solid #1F2937; padding: 0.4rem 0.6rem; vertical-align: top; }}
code {{ color: #F97316; }}
</style>
</head>
<body>
<h1>Comparación visual</h1>
<p>{report['pairs_total']} pares, {report['deviations']} desviaciones.
Umbral {report['threshold']}.</p>
<table>
<thead><tr><th>Pantalla</th><th>Lado a lado</th><th>Antes</th><th>Después</th><th>Diff</th><th>Píxeles</th><th>Estado</th></tr></thead>
<tbody>
{''.join(rows)}
</tbody>
</table>
<h2>Lista de las guías</h2>
<ul>
{checks}
</ul>
</body>
</html>
"""


def render_summary(report: dict) -> str:
    if report["pairs_total"] == 0:
        body = "No hay capturas para comparar."
    else:
        bits = [f"{report['pairs_total']} pares, {report['deviations']} desviaciones"]
        named = [pair["name"] for pair in report["pairs"] if pair["deviation"]]
        if named:
            bits.append("(" + ", ".join(named) + ")")
        body = " ".join(bits) + "."
    conflicts = sum(1 for item in report["checklist"] if item["status"] == "known-conflict")
    if conflicts == 1:
        body += " Las guías dejan 1 conflicto conocido, aparte de las capturas."
    elif conflicts:
        body += f" Las guías dejan {conflicts} conflictos conocidos, aparte de las capturas."
    palette = sum(1 for item in report["checklist"] if item["status"] == "deviation")
    if palette == 1:
        body += " La paleta marca 1 desvío de color."
    elif palette:
        body += f" La paleta marca {palette} desvíos de color."
    body += " El HTML está en el artefacto visual-qa-report."
    return MARKER + "\n" + body + "\n"


def build_report(before: Path, after: Path, out: Path, tokens: dict, threshold: float) -> dict:
    before_manifest = load_manifest(before)
    after_manifest = load_manifest(after)
    names = planned_names(before_manifest, after_manifest, files=png_names(before) | png_names(after))
    pairs = []
    for name in names:
        stem = Path(name).stem
        before_path = before / name if (before / name).is_file() else None
        after_path = after / name if (after / name).is_file() else None
        diff_path = out / "diff" / name
        explained = pair_reason(
            before_path is None, after_path is None,
            shot_reason(before_manifest, stem), shot_reason(after_manifest, stem),
        )
        if explained is not None:
            result = {"ratio": None, "deviation": True, "reason": explained, "palette": []}
        else:
            result = compare_pair(before_path, after_path, diff_path, threshold)
        before_panel = load_panel(before_path, 1, 1)
        after_panel = load_panel(after_path, before_panel[0], before_panel[1])
        diff_panel = load_panel(diff_path if diff_path.is_file() else None, before_panel[0], before_panel[1])
        side_path = out / "side-by-side" / name
        side_path.parent.mkdir(parents=True, exist_ok=True)
        write_png(side_path, *side_by_side([before_panel, after_panel, diff_panel]))
        result.update({
            "name": name,
            "before_src": rel(before_path, out),
            "after_src": rel(after_path, out),
            "diff_src": rel(diff_path, out) if diff_path.is_file() else None,
            "side_src": rel(side_path, out),
        })
        shots = []
        if before_path is not None and before_path.is_file():
            try:
                width, height, rgb = read_png(before_path)
                shots.append(("antes", rgb, width, height))
            except (OSError, ValueError):
                pass
        if after_path is not None and after_path.is_file():
            try:
                width, height, rgb = read_png(after_path)
                shots.append(("después", rgb, width, height))
            except (OSError, ValueError):
                pass
        if "palette" not in result:
            result["palette"] = palette_findings(name, shots, tokens)
        pairs.append(result)
    palette_items = [item for pair in pairs for item in pair.get("palette", [])]
    payload = {
        "threshold": threshold,
        "pairs_total": len(pairs),
        "deviations": sum(1 for pair in pairs if pair["deviation"]),
        "pairs": pairs,
        "checklist": checklist(tokens, palette_items),
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(render_markdown(payload), encoding="utf-8")
    (out / "report.html").write_text(render_html(payload), encoding="utf-8")
    (out / "summary.md").write_text(render_summary(payload), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Informe de comparación visual.")
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--tokens", type=Path, default=Path(__file__).resolve().parent / "design-tokens.json")
    parser.add_argument("--threshold", default=None)
    args = parser.parse_args(argv)
    try:
        threshold = read_threshold(args.threshold if args.threshold is not None else os.environ.get("VISUAL_QA_DIFF_RATIO"))
    except ValueError as exc:
        print(f"visual-qa: {exc}", file=sys.stderr)
        return 2
    tokens = json.loads(args.tokens.read_text(encoding="utf-8"))
    report = build_report(args.before, args.after, args.out, tokens, threshold)
    print(
        f"visual-qa: {report['pairs_total']} pares, {report['deviations']} desviaciones "
        f"en {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
