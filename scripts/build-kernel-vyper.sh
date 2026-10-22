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
USE_CLUSTER=0
for arg in "$@"; do
    case "$arg" in
        --force|-f) FORCE=1 ;;
        --cluster|-c) USE_CLUSTER=1 ;;
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
(
    cd "$WORK_DIR"
    churros_pkgbuild_allow_arch PKGBUILD

    if [ "$USE_CLUSTER" -eq 1 ]; then
        # shellcheck source=scripts/lib/cluster.sh
        source "$PROJECT_DIR/scripts/lib/cluster.sh"
        if churros_cluster_is_configured; then
            churros_cluster_load_config
            if ! command -v distcc >/dev/null 2>&1; then
                echo "Aviso: distcc no está instalado en el host local. Instálalo con: sudo pacman -S distcc"
                echo "       Compilando localmente..."
                export MAKEFLAGS="-j$(nproc)"
            else
                export DISTCC_HOSTS
                DISTCC_HOSTS="$(churros_cluster_distcc_hosts)"
                export DISTCC_FALLBACK=1
                export NUMJOBS
                NUMJOBS="$(churros_cluster_total_threads)"
                export MAKEFLAGS="-j$NUMJOBS"
                export _kernel_cc="distcc clang"
                if [ -d "/usr/lib/distcc/bin" ]; then
                    export PATH="/usr/lib/distcc/bin:$PATH"
                fi
                echo "      [cluster] Compilación distribuida distcc ACTIVADA"
                echo "      [cluster] Potencia: $NUMJOBS hilos paralelos"
                echo "      [cluster] Nodos: $DISTCC_HOSTS"
            fi
        else
            echo "Aviso: cluster.conf no configurado. Compilando localmente..."
            export MAKEFLAGS="-j$(nproc)"
        fi
    else
        export MAKEFLAGS="-j$(nproc)"
    fi

    makepkg -sf --noconfirm --skipinteg
)

echo "[3/3] Publicando paquetes en el repositorio local [churros]..."
churros_copy_pkgs "$WORK_DIR" "$PACKAGE_DIR" "linux-churrosvyper-*"
churros_remove_pkgs "$PACKAGE_DIR" "linux-churrosvyper-debug-*"
churros_repo_add "$PACKAGE_DIR"

echo "✓ Kernel ChurrOSvyper compilado y publicado con éxito en $PACKAGE_DIR"
