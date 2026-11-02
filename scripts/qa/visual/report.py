#!/usr/bin/env python3
"""Empareja las capturas de main y del PR y escribe el informe.

HTML y Markdown con la pareja, el diff de píxeles y una lista sacada de
scripts/qa/visual/design-tokens.json. Una pareja se marca como desviación
si falta un lado, si el tamaño no coincide o si la fracción de píxeles
distintos supera el umbral (por defecto 0.01). Los conflictos entre guías
se listan aparte: ya estaban en la documentación y no son un fallo de esta
pull request.

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


def checklist(tokens: dict) -> list[dict]:
    items = []
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
<thead><tr><th>Pantalla</th><th>Antes</th><th>Después</th><th>Diff</th><th>Píxeles</th><th>Estado</th></tr></thead>
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
    body += " El HTML está en el artefacto visual-qa-report."
    return MARKER + "\n" + body + "\n"


def build_report(before: Path, after: Path, out: Path, tokens: dict, threshold: float) -> dict:
    names = sorted(png_names(before) | png_names(after))
    pairs = []
    for name in names:
        before_path = before / name if (before / name).is_file() else None
        after_path = after / name if (after / name).is_file() else None
        diff_path = out / "diff" / name
        result = compare_pair(before_path, after_path, diff_path, threshold)
        result.update({
            "name": name,
            "before_src": rel(before_path, out),
            "after_src": rel(after_path, out),
            "diff_src": rel(diff_path, out) if diff_path.is_file() else None,
        })
        pairs.append(result)
    payload = {
        "threshold": threshold,
        "pairs_total": len(pairs),
        "deviations": sum(1 for pair in pairs if pair["deviation"]),
        "pairs": pairs,
        "checklist": checklist(tokens),
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
