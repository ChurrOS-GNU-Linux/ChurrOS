#!/usr/bin/env bash
# Espera los artefactos visual-qa-before-<sha> y visual-qa-after-<sha>.
# Sale 0 aunque no lleguen: el informe se escribe igual.
# Uso: wait-shots.sh --sha SHA --dest DIR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=artifact-names.sh
source "$SCRIPT_DIR/artifact-names.sh"

sha=""
dest=""
wait_seconds="${VISUAL_QA_WAIT_SECONDS:-}"
if [[ -z "$wait_seconds" ]]; then
  wait_seconds=5400
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --sha) sha="${2:?}"; shift 2 ;;
    --dest) dest="${2:?}"; shift 2 ;;
    *) echo "visual-qa: argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

if [[ -z "$sha" || -z "$dest" ]]; then
  echo "visual-qa: faltan --sha o --dest" >&2
  exit 2
fi
if [[ ! "$wait_seconds" =~ ^[0-9]+$ ]]; then
  echo "visual-qa: VISUAL_QA_WAIT_SECONDS no es un entero" >&2
  exit 2
fi

before_name="$(visual_qa_before_name "$sha")"
after_name="$(visual_qa_after_name "$sha")"
mkdir -p "$dest/before" "$dest/after"

ready() {
  local root="$1" found
  [[ -f "$root/manifest.json" ]] && return 0
  found="$(find "$root" -type f -name '*.png' -print -quit)"
  [[ -n "$found" ]]
}

try_fetch() {
  local name="$1" dir="$2"
  if ready "$dir"; then
    return 0
  fi
  "$SCRIPT_DIR/fetch-artifact.sh" "$name" "$dir/unpack" >/dev/null 2>&1 || return 1
  local found
  found="$(find "$dir/unpack" -name manifest.json -print -quit || true)"
  if [[ -z "$found" ]]; then
    found="$(find "$dir/unpack" -type f -name '*.png' -print -quit || true)"
  fi
  if [[ -n "$found" ]]; then
    cp -a "$(dirname "$found")"/. "$dir/"
  fi
  ready "$dir"
}

deadline=$((SECONDS + wait_seconds))
while true; do
  try_fetch "$before_name" "$dest/before" || true
  try_fetch "$after_name" "$dest/after" || true
  if ready "$dest/before" && ready "$dest/after"; then
    break
  fi
  if ((SECONDS >= deadline)); then
    break
  fi
  sleep 30
done

python3 - "$dest/status.json" "$before_name" "$after_name" "$dest" <<'PY'
import json, pathlib, sys
path, before_name, after_name, dest = sys.argv[1:]
root = pathlib.Path(dest)
def has(side):
    folder = root / side
    return (folder / "manifest.json").is_file() or any(folder.glob("*.png"))
pathlib.Path(path).write_text(json.dumps({
    "before_name": before_name,
    "after_name": after_name,
    "before": has("before"),
    "after": has("after"),
}, indent=2) + "\n", encoding="utf-8")
PY
