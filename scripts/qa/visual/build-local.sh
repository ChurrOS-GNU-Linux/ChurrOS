#!/usr/bin/env bash
# Construye la ISO del HEAD (pr) y la de la base (main) para la QA visual.
#
# La de main se reutiliza por SHA: primero el directorio de caché y, si hay
# gh autenticado y GITHUB_REPOSITORY, el artefacto visual-qa-main-<sha>-<edición>.
# Si falta, se construye en un worktree de ese commit y se guarda en el caché.
#
# ./churros build borra out/ al empezar. Los ISO se aparcan fuera de out/
# y solo se publican al terminar, así una segunda construcción no se los lleva.
#
# En un runner de GitHub el host no tiene pacman: hace falta --container.
# Si el runner se queda sin disco o sin tiempo, el mismo script en una máquina
# con Arch (o con podman/docker) es el camino de reserva.
#
# Uso:
#   scripts/qa/visual/build-local.sh [--edition niri] [--role pr|main|both]
#       [--base SHA] [--cache-dir DIR] [--out DIR] [--container] [--dry-run]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$ROOT"

# shellcheck source=artifact-names.sh
source "$SCRIPT_DIR/artifact-names.sh"

edition="niri"
role="both"
base="${VISUAL_QA_BASE:-}"
cache_dir="${VISUAL_QA_ISO_CACHE:-${XDG_CACHE_HOME:-$HOME/.cache}/churros/visual-iso}"
out_dir="out/qa-visual"
use_container=0
dry_run=0

usage() {
  sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --edition)
      edition="${2:?falta el valor de --edition}"
      shift 2
      ;;
    --role)
      role="${2:?falta el valor de --role}"
      shift 2
      ;;
    --base)
      base="${2:?falta el valor de --base}"
      shift 2
      ;;
    --cache-dir)
      cache_dir="${2:?falta el valor de --cache-dir}"
      shift 2
      ;;
    --out)
      out_dir="${2:?falta el valor de --out}"
      shift 2
      ;;
    --container)
      use_container=1
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "visual-qa: argumento desconocido: $1" >&2
      exit 2
      ;;
  esac
done

case "$edition" in
  niri|xfce|server|pi) ;;
  *)
    echo "visual-qa: edición no admitida: $edition" >&2
    exit 2
    ;;
esac
case "$role" in
  pr|main|both) ;;
  *)
    echo "visual-qa: role no admitido: $role" >&2
    exit 2
    ;;
esac

full_sha() {
  git rev-parse --verify "${1}^{commit}"
}

if [[ -n "$base" ]]; then
  main_sha="$(full_sha "$base")"
elif git rev-parse --verify --quiet origin/main >/dev/null; then
  main_sha="$(git merge-base HEAD origin/main)"
elif git rev-parse --verify --quiet 'HEAD^1' >/dev/null; then
  main_sha="$(git rev-parse 'HEAD^1')"
else
  echo "visual-qa: no se pudo resolver la base (origin/main, HEAD^1 o --base)" >&2
  exit 2
fi
pr_sha="$(full_sha HEAD)"

if [[ ! "$main_sha" =~ ^[0-9a-f]{40}$ || ! "$pr_sha" =~ ^[0-9a-f]{40}$ ]]; then
  echo "visual-qa: la base o HEAD no es un SHA completo" >&2
  exit 2
fi

if [[ "$dry_run" -eq 1 ]]; then
  python3 - "$pr_sha" "$main_sha" "$edition" "$role" "$out_dir" "$use_container" "$cache_dir" <<'PY'
import json
import sys
print(json.dumps({
    "pr_sha": sys.argv[1],
    "main_sha": sys.argv[2],
    "edition": sys.argv[3],
    "role": sys.argv[4],
    "out": sys.argv[5],
    "container": sys.argv[6] == "1",
    "cache_dir": sys.argv[7],
}, indent=2))
PY
  exit 0
fi

stage="$(mktemp -d "${TMPDIR:-/tmp}/churros-visual-qa.XXXXXX")"
wt=""
main_cached=0

cleanup() {
  if [[ -n "$wt" && -d "$wt" ]]; then
    git worktree remove --force "$wt" >/dev/null 2>&1 || rm -rf "$wt"
  fi
  rm -rf "$stage"
}
trap cleanup EXIT

run_build() {
  local args=(./churros build --edition "$edition")
  if [[ "$use_container" -eq 1 ]]; then
    args=(./churros build --container --edition "$edition")
  fi
  "${args[@]}"
}

take_isos() {
  local src="$1" dest="$2" iso found=0
  mkdir -p "$dest"
  for iso in "$src"/*.iso; do
    [[ -f "$iso" ]] || continue
    mv "$iso" "$dest/"
    found=1
  done
  if [[ "$found" -ne 1 ]]; then
    echo "visual-qa: la construcción no dejó una ISO en $src" >&2
    return 1
  fi
  (
    cd "$dest" || exit 1
    sha256sum -- *.iso > SHA256SUMS
  )
}

cache_dir_for_main() {
  printf '%s/%s/%s\n' "$cache_dir" "$main_sha" "$edition"
}

cache_ok() {
  local dir
  dir="$(cache_dir_for_main)"
  [[ -f "$dir/SHA256SUMS" ]] || return 1
  (cd "$dir" && sha256sum -c --quiet SHA256SUMS)
}

copy_tree() {
  local src="$1" dest="$2"
  mkdir -p "$dest"
  cp -a "$src"/. "$dest"/
}

fetch_main_artifact() {
  local name dir id sums parent
  name="$(visual_qa_main_iso_name "$main_sha" "$edition")"
  dir="$(cache_dir_for_main)"
  [[ -n "${GITHUB_REPOSITORY:-}" ]] || return 1
  if [[ -z "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]]; then
    return 1
  fi
  command -v gh >/dev/null 2>&1 || return 1
  export GH_TOKEN="${GH_TOKEN:-${GITHUB_TOKEN}}"
  id="$(gh api --paginate "repos/${GITHUB_REPOSITORY}/actions/artifacts?per_page=100" \
    --jq ".artifacts[] | select(.name==\"${name}\" and .expired==false) | .id" \
    | head -n 1 || true)"
  [[ -n "$id" ]] || return 1
  mkdir -p "$dir/unpack"
  gh api "repos/${GITHUB_REPOSITORY}/actions/artifacts/${id}/zip" > "$dir/artifact.zip"
  unzip -qo "$dir/artifact.zip" -d "$dir/unpack"
  rm -f "$dir/artifact.zip"
  sums="$(find "$dir/unpack" -type f -name SHA256SUMS -print -quit)"
  [[ -n "$sums" ]] || return 1
  parent="$(dirname "$sums")"
  copy_tree "$parent" "$dir"
  rm -rf "$dir/unpack"
  cache_ok
}

ensure_commit() {
  if git cat-file -e "${main_sha}^{commit}" 2>/dev/null; then
    return 0
  fi
  git fetch --depth=1 origin "$main_sha"
}

build_pr() {
  echo "visual-qa: construyendo ISO pr ${pr_sha} (${edition})" >&2
  run_build
  take_isos "$ROOT/out" "$stage/pr"
  rm -rf "$ROOT/work"
}

build_main() {
  local dir
  dir="$(cache_dir_for_main)"
  if cache_ok || fetch_main_artifact; then
    echo "visual-qa: ISO main ${main_sha} desde caché" >&2
    copy_tree "$dir" "$stage/main"
    main_cached=1
    return 0
  fi
  if [[ "$main_sha" == "$pr_sha" && -d "$stage/pr" ]]; then
    echo "visual-qa: la base es HEAD; se reutiliza la ISO pr" >&2
    copy_tree "$stage/pr" "$stage/main"
    copy_tree "$stage/main" "$dir"
    return 0
  fi
  ensure_commit
  wt="$ROOT/.visual-qa-main-${main_sha}"
  if [[ -d "$wt" ]]; then
    git worktree remove --force "$wt" >/dev/null 2>&1 || rm -rf "$wt"
  fi
  git worktree add --detach "$wt" "$main_sha"
  echo "visual-qa: construyendo ISO main ${main_sha} (${edition})" >&2
  (cd "$wt" && run_build)
  take_isos "$wt/out" "$stage/main"
  rm -rf "$wt/work" "$wt/out"
  git worktree remove --force "$wt"
  wt=""
  copy_tree "$stage/main" "$dir"
}

preserve_previous_pr() {
  if [[ "$role" == "main" && -d "$out_dir/pr" ]]; then
    copy_tree "$out_dir/pr" "$stage/pr"
  fi
}

publish() {
  mkdir -p "$out_dir"
  if [[ -d "$stage/pr" ]]; then
    copy_tree "$stage/pr" "$out_dir/pr"
  fi
  if [[ -d "$stage/main" ]]; then
    copy_tree "$stage/main" "$out_dir/main"
  fi
  python3 - "$out_dir/manifest.json" "$edition" "$pr_sha" "$main_sha" "$role" "$main_cached" <<'PY'
import json
import pathlib
import sys
path, edition, pr_sha, main_sha, role, cached = sys.argv[1:]
out = pathlib.Path(path)
data = {}
if out.is_file():
    data = json.loads(out.read_text(encoding="utf-8"))
data["edition"] = edition
if role in {"pr", "both"} or pathlib.Path(out.parent / "pr" / "SHA256SUMS").is_file():
    data["pr"] = {"sha": pr_sha, "sha256_file": "pr/SHA256SUMS", "cached": False}
if role in {"main", "both"}:
    data["main"] = {
        "sha": main_sha,
        "sha256_file": "main/SHA256SUMS",
        "cached": cached == "1",
    }
out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY
}

preserve_previous_pr
case "$role" in
  pr) build_pr ;;
  main) build_main ;;
  both)
    build_pr
    build_main
    ;;
esac
publish
echo "visual-qa: ISO en ${out_dir} (main_cached=${main_cached})" >&2
