#!/usr/bin/env bash
# Publica o actualiza el comentario de la QA visual. No crea un check.
# El cuerpo es un fichero; el token lo lee gh y este script no lo imprime.
# Uso: pr-comment.sh summary.md
# Entorno: GITHUB_REPOSITORY, PR (número), GH_TOKEN o GITHUB_TOKEN.
set -euo pipefail

body_file="${1:?falta el fichero del comentario}"
repo="${GITHUB_REPOSITORY:-}"
pr="${PR:-}"
marker='<!-- visual-qa-report -->'

if [[ ! -f "$body_file" ]]; then
  echo "visual-qa: no existe el resumen" >&2
  exit 2
fi
if ! grep -q "$marker" "$body_file"; then
  echo "visual-qa: el resumen no lleva la marca del comentario" >&2
  exit 2
fi
if [[ -z "$repo" || -z "$pr" ]]; then
  echo "visual-qa: sin pull request; no se comenta" >&2
  exit 0
fi
if [[ -z "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]]; then
  echo "visual-qa: sin token; no se comenta" >&2
  exit 0
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "visual-qa: gh no está instalado; no se comenta" >&2
  exit 0
fi
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN}}"

existing="$(gh api --paginate "repos/${repo}/issues/${pr}/comments" \
  --jq '.[] | select(.body | startswith("<!-- visual-qa-report -->")) | .id' \
  | head -n 1 || true)"

payload="$(mktemp)"
python3 - "$body_file" "$payload" <<'PY'
import json, pathlib, sys
source, dest = sys.argv[1:]
pathlib.Path(dest).write_text(
    json.dumps({"body": pathlib.Path(source).read_text(encoding="utf-8")}),
    encoding="utf-8",
)
PY
if [[ -n "$existing" ]]; then
  gh api --method PATCH "repos/${repo}/issues/comments/${existing}" --input "$payload" >/dev/null
else
  gh api --method POST "repos/${repo}/issues/${pr}/comments" --input "$payload" >/dev/null
fi
rm -f "$payload"
echo "visual-qa: comentario actualizado en ${repo}#${pr}" >&2
