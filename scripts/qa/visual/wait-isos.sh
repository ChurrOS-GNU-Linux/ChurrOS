#!/usr/bin/env bash
# Espera los artefactos de la ISO del PR y de main y escribe status.json.
# Sale 0 tanto si llegan como si se agota la espera: la captura sigue y
# deja constancia de lo que falta.
# Uso: wait-isos.sh --edition niri --pr-sha SHA --main-sha SHA --dest DIR
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=artifact-names.sh
source "$SCRIPT_DIR/artifact-names.sh"

edition="niri"
pr_sha=""
main_sha=""
dest=""
wait_seconds="${VISUAL_QA_WAIT_SECONDS:-}"
if [[ -z "$wait_seconds" ]]; then
  wait_seconds=5400
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --edition) edition="${2:?}"; shift 2 ;;
    --pr-sha) pr_sha="${2:?}"; shift 2 ;;
    --main-sha) main_sha="${2:?}"; shift 2 ;;
    --dest) dest="${2:?}"; shift 2 ;;
    *) echo "visual-qa: argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

case "$edition" in
  niri|xfce|server) ;;
  *) echo "visual-qa: edición no admitida: $edition" >&2; exit 2 ;;
esac
if [[ -z "$pr_sha" || -z "$main_sha" || -z "$dest" ]]; then
  echo "visual-qa: faltan --pr-sha, --main-sha o --dest" >&2
  exit 2
fi
if [[ ! "$wait_seconds" =~ ^[0-9]+$ ]]; then
  echo "visual-qa: VISUAL_QA_WAIT_SECONDS no es un entero" >&2
  exit 2
fi

pr_name="$(visual_qa_pr_iso_name "$pr_sha" "$edition")"
main_name="$(visual_qa_main_iso_name "$main_sha" "$edition")"
mkdir -p "$dest/pr" "$dest/main"

find_iso() {
  find "$1" -type f -name '*.iso' -print -quit
}

try_fetch() {
  local name="$1" dir="$2"
  if [[ -n "$(find_iso "$dir")" ]]; then
    return 0
  fi
  "$SCRIPT_DIR/fetch-artifact.sh" "$name" "$dir" >/dev/null 2>&1 || return 1
  [[ -n "$(find_iso "$dir")" ]]
}

deadline=$((SECONDS + wait_seconds))
while true; do
  try_fetch "$pr_name" "$dest/pr" || true
  try_fetch "$main_name" "$dest/main" || true
  if [[ -n "$(find_iso "$dest/pr")" && -n "$(find_iso "$dest/main")" ]]; then
    break
  fi
  if ((SECONDS >= deadline)); then
    break
  fi
  sleep 30
done

python3 - "$dest/status.json" "$pr_name" "$main_name" "$(find_iso "$dest/pr")" "$(find_iso "$dest/main")" <<'PY'
import json
import pathlib
import sys
path, pr_name, main_name, pr_iso, main_iso = sys.argv[1:]
pathlib.Path(path).write_text(json.dumps({
    "pr_name": pr_name,
    "main_name": main_name,
    "pr_iso": pr_iso,
    "main_iso": main_iso,
}, indent=2) + "\n", encoding="utf-8")
PY
echo "visual-qa: pr=${pr_name} main=${main_name}" >&2
