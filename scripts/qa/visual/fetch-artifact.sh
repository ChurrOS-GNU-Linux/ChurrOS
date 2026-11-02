#!/usr/bin/env bash
# Descarga un artefacto de Actions por nombre. No imprime el token.
# Sale 0 si el zip quedó en el directorio destino, 2 si no está o no hay credenciales.
# Uso: fetch-artifact.sh NOMBRE DESTINO
set -euo pipefail

name="${1:?falta el nombre del artefacto}"
dest="${2:?falta el directorio destino}"

if [[ ! "$name" =~ ^visual-qa-[A-Za-z0-9._-]+$ ]]; then
  echo "visual-qa: nombre de artefacto no admitido" >&2
  exit 2
fi
if [[ -z "${GITHUB_REPOSITORY:-}" ]]; then
  echo "visual-qa: sin GITHUB_REPOSITORY; no se descarga el artefacto" >&2
  exit 2
fi
if [[ -z "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]]; then
  echo "visual-qa: sin token; no se descarga el artefacto" >&2
  exit 2
fi
if ! command -v gh >/dev/null 2>&1; then
  echo "visual-qa: gh no está instalado" >&2
  exit 2
fi
export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN}}"

id="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100" \
  --jq ".artifacts[] | select(.name==\"${name}\" and .expired==false) | .id" \
  | head -n 1 || true)"
if [[ -z "$id" ]]; then
  exit 2
fi
mkdir -p "$dest"
tmp="$(mktemp)"
gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${id}/zip" > "$tmp"
unzip -qo "$tmp" -d "$dest"
rm -f "$tmp"
