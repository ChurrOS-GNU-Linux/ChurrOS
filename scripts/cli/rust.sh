#!/usr/bin/env bash
#
# Compila y prueba las apps Rust (rust/) igual que el CI (.github/workflows/rust.yml):
# cargo build, cargo test y cargo clippy sobre el workspace.
#
# Por defecto corre en el contenedor Arch del Containerfile: gtk4-rs y
# libadwaita-rs piden versiones de GTK y libadwaita que Debian, Ubuntu o Fedora
# todavía no tienen. --host lo ejecuta en este equipo (Arch al día).
set -euo pipefail

cd "$(dirname "$0")/../.."

# shellcheck source=scripts/lib/host.sh
source scripts/lib/host.sh

USE_HOST=0
PACKAGES=()

show_help() {
    cat <<'EOF'
Usage:
  ./churros rust [--host] [-p <crate>]...

Compila (cargo build), prueba (cargo test) y pasa clippy al workspace rust/,
los mismos pasos que el CI.

  (sin opciones)  en el contenedor Arch (podman o docker, con sudo)
  --host          en este equipo; necesita GTK y libadwaita de Arch al día
  -p <crate>      solo ese crate (repetible), p. ej. -p churros-services
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            USE_HOST=1
            shift
            ;;
        -p|--package)
            [ -n "${2-}" ] || { echo "Error: $1 necesita un crate" >&2; exit 1; }
            PACKAGES+=(-p "$2")
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            echo "Error: opción desconocida '$1'" >&2
            show_help >&2
            exit 1
            ;;
    esac
done

if [ "$USE_HOST" -eq 0 ] && ! churros_in_container; then
    # shellcheck source=scripts/lib/container.sh
    source scripts/lib/container.sh
    container_engine_init
    container_ensure_image
    container_run -- bash scripts/cli/rust.sh ${PACKAGES[@]+"${PACKAGES[@]}"}
    exit 0
fi

if ! command -v cargo >/dev/null 2>&1; then
    echo "Error: cargo no está instalado. Usa ./churros rust (sin --host) para compilar en el contenedor." >&2
    exit 1
fi

if [ "${#PACKAGES[@]}" -eq 0 ]; then
    PACKAGES=(--workspace)
fi

MANIFEST=(--manifest-path rust/Cargo.toml)

step() {
    printf '\n== %s\n' "$*"
}

on_error() {
    if ! churros_in_container; then
        echo >&2
        echo "Si el error es de gtk4 o libadwaita (system-deps / pkg-config), la versión" >&2
        echo "del host es demasiado vieja: ./churros rust lo compila en el contenedor Arch." >&2
    fi
}
trap 'on_error' ERR

step "cargo build ${PACKAGES[*]} --all-targets --locked"
cargo build "${PACKAGES[@]}" --all-targets --locked "${MANIFEST[@]}"

step "cargo test ${PACKAGES[*]} --locked"
cargo test "${PACKAGES[@]}" --locked "${MANIFEST[@]}"

# Igual que en el CI, clippy informa pero sus avisos no fallan: el workspace
# arrastra avisos previos. Un error de compilación sí falla.
step "cargo clippy ${PACKAGES[*]} --all-targets --locked"
cargo clippy "${PACKAGES[@]}" --all-targets --locked "${MANIFEST[@]}"

trap - ERR
echo
echo "Rust OK (build, test, clippy)."
