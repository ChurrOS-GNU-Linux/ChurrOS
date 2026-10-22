#!/usr/bin/env bash
#
# Batería de pruebas de ChurrOS por capas (docs/testing.md).
#
#   ./churros test                  capa estática: ./churros check (incluye tests/static)
#   ./churros test --container      tests/container en el contenedor Arch (pacman, niri validate)
#   ./churros test --rust           ./churros rust (build, test y clippy del workspace)
#   ./churros test --iso [ISO]      auditoría del contenido de una ISO ya construida
#   ./churros test --boot [ISO]     arranque de la ISO en QEMU y comprobaciones en la sesión Live
#   ./churros test --mutations      autoprueba: cada regresión sembrada tiene que hacer fallar la batería
#                                   (con --container, las de tests/container dentro del contenedor)
#
# Sin ISO explícita, --iso y --boot usan la más reciente de out/. Las capas se
# pueden combinar (./churros test --iso --boot). CHURROS_STRICT=1 (o CI=true)
# convierte una herramienta que falta en un fallo en vez de un aviso.
set -euo pipefail

cd "$(dirname "$0")/../.."

# shellcheck source=scripts/lib/host.sh
source scripts/lib/host.sh

RUN_STATIC=1
RUN_CONTAINER=0
RUN_RUST=0
RUN_ISO=0
RUN_BOOT=0
RUN_MUTATIONS=0
ISO=""
BOOT_ARGS=()

show_help() {
    sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --container) RUN_CONTAINER=1; RUN_STATIC=0 ;;
        --rust) RUN_RUST=1; RUN_STATIC=0 ;;
        --iso|--boot)
            [ "$1" = --iso ] && RUN_ISO=1 || RUN_BOOT=1
            RUN_STATIC=0
            if [ -n "${2-}" ] && [[ "$2" != --* ]]; then
                ISO="$2"
                shift
            fi
            ;;
        --edition|--timeout|--artifacts|--firmware)
            [ -n "${2-}" ] || { echo "Error: $1 necesita un valor" >&2; exit 1; }
            BOOT_ARGS+=("$1" "$2")
            shift
            ;;
        --mutations) RUN_MUTATIONS=1; RUN_STATIC=0 ;;
        --static) RUN_STATIC=1 ;;
        -h|--help) show_help; exit 0 ;;
        *)
            echo "Error: opción desconocida '$1'" >&2
            show_help >&2
            exit 1
            ;;
    esac
    shift
done

latest_iso() {
    find out -maxdepth 1 -name '*.iso' -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -n1 | cut -d' ' -f2-
}

if [ "$RUN_ISO" -eq 1 ] || [ "$RUN_BOOT" -eq 1 ]; then
    [ -n "$ISO" ] || ISO="$(latest_iso)"
    if [ -z "$ISO" ] || [ ! -f "$ISO" ]; then
        echo "Error: no hay ISO. Construye una con ./churros build o pasa la ruta: ./churros test --iso out/X.iso" >&2
        exit 1
    fi
fi

status=0

if [ "$RUN_STATIC" -eq 1 ]; then
    bash scripts/cli/check.sh || status=1
fi

if [ "$RUN_CONTAINER" -eq 1 ]; then
    CONTAINER_CMD=(python3 -m unittest discover -s tests/container -t . -v)
    if [ "$RUN_MUTATIONS" -eq 1 ]; then
        CONTAINER_CMD=(python3 tests/mutations/run_mutations.py --container)
        RUN_MUTATIONS=0
    fi
    if churros_in_container; then
        "${CONTAINER_CMD[@]}" || status=1
    else
        # shellcheck source=scripts/lib/container.sh
        source scripts/lib/container.sh
        container_engine_init
        container_ensure_image
        container_run --upgrade -e "CHURROS_STRICT=${CHURROS_STRICT:-}" -- \
            "${CONTAINER_CMD[@]}" || status=1
    fi
fi

if [ "$RUN_RUST" -eq 1 ]; then
    bash scripts/cli/rust.sh || status=1
fi

if [ "$RUN_ISO" -eq 1 ]; then
    python3 tests/iso/check_iso.py "$ISO" || status=1
fi

if [ "$RUN_BOOT" -eq 1 ]; then
    python3 tests/vm/boot_smoke.py "$ISO" ${BOOT_ARGS[@]+"${BOOT_ARGS[@]}"} || status=1
fi

if [ "$RUN_MUTATIONS" -eq 1 ]; then
    python3 tests/mutations/run_mutations.py || status=1
fi

exit "$status"
