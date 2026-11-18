#!/usr/bin/env bash
# trusted-scripts.sh — copia el código de QA visual desde una rama de confianza.
#
# QUÉ PROBLEMA RESUELVE (auditoría R1)
# Los cuatro workflows de visual-qa se disparan con `pull_request` y pasan
# TYPESAFE_API_KEY y ANTHROPIC_API_KEY al entorno de un paso que ejecutaba
# `python3 scripts/qa/visual/classify.py` resuelto desde el checkout de la PR.
# GitHub no entrega secretos a las PRs de forks, pero sí a las ramas del
# propio repositorio: cualquiera con permiso de push podía añadir dos líneas
# al script, exfiltrar las claves, y el job terminaba en verde porque lleva
# `continue-on-error: true` y no es check requerido.
#
# QUÉ HACE
# Extrae `scripts/qa/visual/` de la rama indicada (main por defecto) en un
# directorio temporal, y el workflow ejecuta desde ahí el paso que recibe las
# claves. El diff de la PR se sigue leyendo del checkout de la PR: eso son
# datos, no código.
#
# Uso:
#   scripts/qa/visual/trusted-scripts.sh DESTINO [REF]
#
# Imprime la ruta del directorio que contiene `scripts/qa/visual/`.
# Sale con 1 si no puede resolver la ref.

set -euo pipefail

destino="${1:?uso: trusted-scripts.sh DESTINO [REF]}"
ref="${2:-main}"
repo="$(cd "$(dirname "$0")/../../.." && pwd)"

cd "$repo"

# La ref tiene que existir en el remoto. Si no está (repo sin fetch, clon
# superficial raro), se cae con un mensaje claro en vez de ejecutar algo
# arbitrario.
if ! git rev-parse --verify --quiet "origin/${ref}^{commit}" >/dev/null; then
    git fetch --quiet --depth=1 origin "$ref" 2>/dev/null || true
fi
if ! git rev-parse --verify --quiet "origin/${ref}^{commit}" >/dev/null; then
    printf 'trusted-scripts: no se pudo resolver origin/%s\n' "$ref" >&2
    exit 1
fi

commit="$(git rev-parse "origin/${ref}^{commit}")"
mkdir -p "$destino"

# Solo el subárbol de la QA visual: ni el resto del repo ni ficheros que el
# script pudiera cargar por ruta relativa.
git archive "$commit" scripts/qa/visual | tar -x -C "$destino"

if [ ! -f "$destino/scripts/qa/visual/classify.py" ]; then
    printf 'trusted-scripts: origin/%s no trae scripts/qa/visual/classify.py\n' "$ref" >&2
    exit 1
fi

printf '%s\n' "$destino"
