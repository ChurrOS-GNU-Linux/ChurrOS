#!/usr/bin/env bash
#
# build-kernel-vyper.sh — Compila y empaqueta el kernel ChurrOSvyper
# Produce linux-churrosvyper y linux-churrosvyper-headers en archiso/packages/.
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# shellcheck source=scripts/lib/local-repo.sh
source "$SCRIPT_DIR/lib/local-repo.sh"
PACKAGE_DIR="$(churros_local_repo_dir)"
PKGBUILD_DIR="$PROJECT_DIR/pkgs/linux-churrosvyper"

FORCE=0
for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=1 ;;
    esac
done

# Verificar si ya existen los paquetes compilados en el repositorio local
existing_kernel="$(churros_first_pkg "$PACKAGE_DIR" 'linux-churrosvyper-[0-9]*' || true)"
existing_headers="$(churros_first_pkg "$PACKAGE_DIR" 'linux-churrosvyper-headers-[0-9]*' || true)"
if [ -n "$existing_kernel" ] && [ -n "$existing_headers" ] && [ "$FORCE" -eq 0 ]; then
    echo "[skip] linux-churrosvyper ya compilado ($(basename "$existing_kernel"))"
    echo "       (usa --force para forzar la recompilación)"
    exit 0
fi

echo "=============================================="
echo "  Compilando Kernel ChurrOSvyper (CachyOS BORE)"
echo "=============================================="

if [ ! -d "$PKGBUILD_DIR" ] || [ ! -f "$PKGBUILD_DIR/PKGBUILD" ]; then
    echo "Error: no se encontró la receta en $PKGBUILD_DIR" >&2
    exit 1
fi

choose_work_dir() {
    WORK_DIR="$PROJECT_DIR/work-kernel"
    mkdir -p "$WORK_DIR"
}

choose_work_dir
mkdir -p "$PACKAGE_DIR" "$WORK_DIR"
rm -rf "$WORK_DIR"/*

echo "[1/3] Preparando entorno de compilación en $WORK_DIR..."
cp -r "$PKGBUILD_DIR"/* "$WORK_DIR/"

echo "[2/3] Compilando kernel con makepkg (BORE + Clang ThinLTO + O3)..."
echo "      Esto tomará varios minutos dependiendo de tu CPU."
(
    cd "$WORK_DIR"
    churros_pkgbuild_allow_arch PKGBUILD
    export MAKEFLAGS="-j$(nproc)"
    makepkg -sf --noconfirm --skipinteg
)

echo "[3/3] Publicando paquetes en el repositorio local [churros]..."
churros_copy_pkgs "$WORK_DIR" "$PACKAGE_DIR" "linux-churrosvyper-*"
churros_remove_pkgs "$PACKAGE_DIR" "linux-churrosvyper-debug-*"
churros_repo_add "$PACKAGE_DIR"

echo "✓ Kernel ChurrOSvyper compilado y publicado con éxito en $PACKAGE_DIR"
