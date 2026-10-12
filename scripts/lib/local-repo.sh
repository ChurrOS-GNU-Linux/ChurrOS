# shellcheck shell=bash
#
# Directorio del repositorio local [churros]. Se carga con `source`.
#
# x86_64 sigue en archiso/packages/. aarch64 escribe en
# archiso/packages/aarch64/ para no mezclar paquetes de las dos
# arquitecturas en el mismo churros.db.

# Imprime la ruta absoluta del repo local de esta arquitectura.
churros_local_repo_dir() {
    if [ -n "${CHURROS_PKG_DIR:-}" ]; then
        printf '%s\n' "$CHURROS_PKG_DIR"
        return
    fi
    local root
    root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
    if [ "$(uname -m)" = aarch64 ]; then
        printf '%s\n' "$root/archiso/packages/aarch64"
    else
        printf '%s\n' "$root/archiso/packages"
    fi
}

# makepkg rechaza el paquete si CARCH no está en arch=(). Varios PKGBUILD
# de AUR y de Arch declaran solo x86_64 aunque el código compila en aarch64
# (wlogout, calamares, bazaar). En aarch64 se añade la arquitectura; en
# x86_64 el PKGBUILD no se toca. arch=('any') tampoco.
churros_pkgbuild_allow_arch() {
    local pkgbuild="$1"
    local arch
    arch="$(uname -m)"
    [ "$arch" = aarch64 ] || return 0
    python3 - "$pkgbuild" "$arch" <<'PY'
import re
import sys

path, arch = sys.argv[1], sys.argv[2]
text = open(path, encoding="utf-8").read()

def add(match):
    body = match.group(1)
    tokens = re.findall(r"[A-Za-z0-9_]+", body)
    if arch in tokens or "any" in tokens:
        return match.group(0)
    body = body.rstrip()
    if body.endswith(","):
        body = body + f" '{arch}'"
    else:
        body = body + f" '{arch}'"
    return "arch=(" + body + ")"

new, count = re.subn(r"^arch=\(([^)]*)\)", add, text, count=1, flags=re.M)
if count != 1:
    raise SystemExit(f"PKGBUILD: no arch=() line in {path}")
if new != text:
    open(path, "w", encoding="utf-8").write(new)
    print(f"    arch+=({arch})")
PY
}

# Paquetes de makepkg. Arch usa .pkg.tar.zst; Arch Linux ARM trae
# PKGEXT='.pkg.tar.xz'. El build acepta cualquiera de los dos (y gz) para
# que un paquete ya compilado no se vuelva a construir ni falle el cp.
# Las firmas y los paquetes -debug- no entran en el repo local.
churros_pkg_archives() {
    local dir="$1"
    local name_glob="${2:-*}"
    local f base
    local restore_nullglob=0
    shopt -q nullglob || restore_nullglob=1
    shopt -s nullglob
    # El glob del nombre es a propósito; no va entre comillas.
    # shellcheck disable=SC2086
    for f in "$dir"/${name_glob}.pkg.tar.*; do
        base="$(basename "$f")"
        case "$base" in
            *.sig|*-debug-*.pkg.tar.*) continue ;;
        esac
        printf '%s\n' "$f"
    done
    if [ "$restore_nullglob" -eq 1 ]; then
        shopt -u nullglob
    fi
}

# Primer paquete que casa, o retorno 1 si no hay ninguno.
churros_first_pkg() {
    local f
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        printf '%s\n' "$f"
        return 0
    done < <(churros_pkg_archives "$@")
    return 1
}

# Copia los paquetes (sin debug ni firmas) de src a dest. Falla si no hay.
churros_copy_pkgs() {
    local src="$1"
    local dest="$2"
    local name_glob="${3:-*}"
    local f copied=0
    mkdir -p "$dest"
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        cp -f "$f" "$dest/"
        copied=1
    done < <(churros_pkg_archives "$src" "$name_glob")
    [ "$copied" -eq 1 ]
}

# Borra paquetes, debug y firmas que casen. No falla si no hay ninguno.
churros_remove_pkgs() {
    local dir="$1"
    local name_glob="$2"
    local f
    local restore_nullglob=0
    shopt -q nullglob || restore_nullglob=1
    shopt -s nullglob
    # shellcheck disable=SC2086
    for f in "$dir"/${name_glob}.pkg.tar.*; do
        rm -f "$f"
    done
    if [ "$restore_nullglob" -eq 1 ]; then
        shopt -u nullglob
    fi
}

# Regenera churros.db con los paquetes reales del directorio.
churros_repo_add() {
    local dir="$1"
    local f
    local -a pkgs=()
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        pkgs+=("$(basename "$f")")
    done < <(churros_pkg_archives "$dir")
    if [ "${#pkgs[@]}" -eq 0 ]; then
        echo "repo-add: no packages in $dir" >&2
        return 1
    fi
    (
        cd "$dir"
        repo-add churros.db.tar.gz "${pkgs[@]}"
    )
}
