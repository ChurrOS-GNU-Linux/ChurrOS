# shellcheck shell=bash
#
# Contenedor de build de ChurrOS (Containerfile en la raíz del repo).
# Se carga con `source` desde scripts/cli/build.sh y scripts/cli/rust.sh.
#
#   container_engine_init                 elige podman o docker
#   container_ensure_image                construye la imagen si hace falta
#   container_run [opciones] -- cmd...    ejecuta cmd en /churros (el repo)
#
# Variables de entorno (todas opcionales):
#   CHURROS_CONTAINER_ENGINE   podman | docker. Por defecto podman, y docker
#                              si no hay podman.
#   CHURROS_CONTAINER_IMAGE    nombre de la imagen (localhost/churros-builder).
#   CHURROS_CONTAINER_BASE     imagen base. Por defecto la oficial de Arch,
#                              que solo existe para x86_64. En ARM, el CI de
#                              rust usa docker.io/menci/archlinuxarm. El build
#                              de la ISO aarch64 fija la suya en container_use_arch.
#   CHURROS_CONTAINER_REBUILD  1 = reconstruir la imagen aunque esté al día.
#   CHURROS_CONTAINER_ARGS     argumentos extra para `run` (proxy, montajes).
#
# container_use_arch aarch64 cambia imagen, Containerfile, plataforma y
# volúmenes. ./churros rust no la llama: el job ARM de rust.yml sigue con
# Containerfile y CHURROS_CONTAINER_BASE.

CHURROS_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [ -n "${CHURROS_CONTAINER_IMAGE:-}" ]; then
    CHURROS_CONTAINER_IMAGE_EXPLICIT=1
else
    CHURROS_CONTAINER_IMAGE_EXPLICIT=0
    CHURROS_CONTAINER_IMAGE=localhost/churros-builder
fi
CHURROS_CONTAINERFILE="${CHURROS_CONTAINERFILE:-$CHURROS_REPO_ROOT/Containerfile}"
CHURROS_CONTAINER_PLATFORM="${CHURROS_CONTAINER_PLATFORM:-}"
CHURROS_CONTAINER_HOME_VOL="${CHURROS_CONTAINER_HOME_VOL:-churros-builder-home}"
CHURROS_CONTAINER_CACHE_VOL="${CHURROS_CONTAINER_CACHE_VOL:-churros-pacman-cache}"
CHURROS_CONTAINER_CARGO_DIR="${CHURROS_CONTAINER_CARGO_DIR:-/churros/rust/target/container}"
# Arch es rolling: una imagen de más de una semana obliga a cada build a
# actualizar medio sistema con pacman -Syu antes de empezar.
CHURROS_CONTAINER_MAX_AGE=$((7 * 24 * 3600))

CONTAINER_ENGINE=()
CONTAINER_ROOTLESS=0

container_die() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

# container_use_arch aarch64
#
# Imagen nativa de Arch Linux ARM para el build completo de la ISO
# (paquetes locales, Rust y mkarchiso). --platform linux/arm64: en x86_64
# el motor usa qemu-user; en aarch64 es nativo. Los volúmenes y el target
# de cargo no se mezclan con los del build x86_64.
container_use_arch() {
    case "$1" in
        aarch64|arm64)
            if [ "$CHURROS_CONTAINER_IMAGE_EXPLICIT" -eq 0 ]; then
                CHURROS_CONTAINER_IMAGE=localhost/churros-builder-aarch64
            fi
            CHURROS_CONTAINER_BASE="${CHURROS_CONTAINER_BASE:-docker.io/menci/archlinuxarm:latest}"
            CHURROS_CONTAINERFILE="$CHURROS_REPO_ROOT/Containerfile.aarch64"
            CHURROS_CONTAINER_PLATFORM=linux/arm64
            CHURROS_CONTAINER_HOME_VOL=churros-builder-home-aarch64
            CHURROS_CONTAINER_CACHE_VOL=churros-pacman-cache-aarch64
            CHURROS_CONTAINER_CARGO_DIR=/churros/rust/target/container-aarch64
            ;;
        x86_64) ;;
        *) container_die "container_use_arch: arquitectura no soportada '$1'" ;;
    esac
}

# El contenedor corre con root de verdad: sudo podman, o el demonio de docker.
# mkarchiso (pacstrap) monta devtmpfs y proc dentro del chroot, y eso no se
# puede desde el user namespace de podman o docker rootless.
container_engine_init() {
    local engine="${CHURROS_CONTAINER_ENGINE:-}"

    if [ -z "$engine" ]; then
        if command -v podman >/dev/null 2>&1; then
            engine=podman
        elif command -v docker >/dev/null 2>&1; then
            engine=docker
        else
            container_die "no hay podman ni docker. Instala uno (recomendado: podman):
  Debian/Ubuntu: sudo apt install podman
  Fedora:        sudo dnf install podman
  Arch:          sudo pacman -S podman"
        fi
    fi

    case "$engine" in
        podman|docker) ;;
        *) container_die "CHURROS_CONTAINER_ENGINE='$engine' no es válido (usa podman o docker)" ;;
    esac
    command -v "$engine" >/dev/null 2>&1 || container_die "$engine no está instalado"

    CONTAINER_ENGINE=("$engine")
    if [ "$(id -u)" -ne 0 ]; then
        if [ "$engine" = podman ]; then
            CONTAINER_ENGINE=(sudo podman)
        elif ! docker info >/dev/null 2>&1; then
            # Sin permiso sobre el socket (el usuario no está en el grupo docker).
            CONTAINER_ENGINE=(sudo docker)
        fi
    fi

    if [ "$engine" = docker ] &&
        "${CONTAINER_ENGINE[@]}" info --format '{{.SecurityOptions}}' 2>/dev/null | grep -q rootless; then
        CONTAINER_ROOTLESS=1
    fi
}

# Huella del Containerfile y de la imagen base: si cambia, se reconstruye.
container_recipe() {
    {
        cat "$CHURROS_CONTAINERFILE"
        printf 'base=%s\nplatform=%s\n' "${CHURROS_CONTAINER_BASE:-}" "${CHURROS_CONTAINER_PLATFORM:-}"
    } | sha256sum | cut -c1-16
}

container_label() {
    "${CONTAINER_ENGINE[@]}" image inspect \
        --format "{{ index .Config.Labels \"$1\" }}" "$CHURROS_CONTAINER_IMAGE" 2>/dev/null || true
}

container_ensure_image() {
    local want have built now reason="" ctx
    local -a build_args

    want=$(container_recipe)
    have=$(container_label org.churros.recipe)
    built=$(container_label org.churros.built)
    now=$(date +%s)

    if [ -z "$have" ]; then
        reason="no existe"
    elif [ "$have" != "$want" ]; then
        reason="el Containerfile cambió"
    elif ! [[ "$built" =~ ^[0-9]+$ ]] || [ $((now - built)) -gt "$CHURROS_CONTAINER_MAX_AGE" ]; then
        reason="tiene más de 7 días"
    elif [ "${CHURROS_CONTAINER_REBUILD:-0}" = 1 ]; then
        reason="CHURROS_CONTAINER_REBUILD=1"
    fi

    if [ -z "$reason" ]; then
        echo "[container] Imagen $CHURROS_CONTAINER_IMAGE al día (${CONTAINER_ENGINE[*]})."
        return 0
    fi

    echo "[container] Construyendo $CHURROS_CONTAINER_IMAGE con ${CONTAINER_ENGINE[*]} ($reason)..."

    # Contexto vacío: el Containerfile no copia nada y así no se envían al
    # motor out/, vm/ ni rust/target.
    ctx=$(mktemp -d)
    cp "$CHURROS_CONTAINERFILE" "$ctx/Containerfile"

    # --no-cache: si no, una reconstrucción por antigüedad reutilizaría la capa
    # de pacman y la imagen seguiría igual de vieja.
    build_args=(build --no-cache
        --label "org.churros.recipe=$want"
        --label "org.churros.built=$now"
        -t "$CHURROS_CONTAINER_IMAGE"
        -f "$ctx/Containerfile")
    if [ -n "$CHURROS_CONTAINER_PLATFORM" ]; then
        build_args+=(--platform "$CHURROS_CONTAINER_PLATFORM")
    fi
    if [ -n "${CHURROS_CONTAINER_BASE:-}" ]; then
        build_args+=(--build-arg "BASE_IMAGE=$CHURROS_CONTAINER_BASE")
    fi

    if ! "${CONTAINER_ENGINE[@]}" "${build_args[@]}" "$ctx"; then
        rm -rf "$ctx"
        container_die "no se pudo construir la imagen desde Containerfile"
    fi
    rm -rf "$ctx"
}

# container_run [--privileged] [--upgrade] [-e VAR=valor]... -- comando...
#
# Monta el repo en /churros y ejecuta el comando con el UID/GID del host, así
# lo que escribe (out/, archiso/packages/, rust/target/) es del usuario.
#   --privileged  necesario para mkarchiso (monta el chroot de pacstrap).
#   --upgrade     pacman -Syu antes del comando (makepkg -s instala deps).
#
# Rust compila en rust/target/container, no en rust/target: los build scripts
# enlazados contra la glibc de Arch no arrancan en un host con una más vieja
# (Debian, Ubuntu) si cargo los diera por buenos.
#
# Volúmenes persistentes entre ejecuciones:
#   churros-builder-home   HOME del usuario (registro de cargo, caché de fuentes)
#   churros-pacman-cache   /var/cache/pacman/pkg (deps de makepkg y paquetes
#                          de la ISO, que pacstrap toma de aquí)
container_run() {
    local uid gid
    local -a run_args extra

    if [ "$CONTAINER_ROOTLESS" -eq 1 ]; then
        # El root del contenedor ya es el usuario del host.
        uid=0
        gid=0
    else
        uid=$(id -u)
        gid=$(id -g)
    fi

    run_args=(run --rm
        --security-opt label=disable
        -v "$CHURROS_REPO_ROOT:/churros"
        -w /churros
        -v "$CHURROS_CONTAINER_HOME_VOL:/home/builder"
        -v "$CHURROS_CONTAINER_CACHE_VOL:/var/cache/pacman/pkg"
        -e CHURROS_IN_CONTAINER=1
        -e "CARGO_TARGET_DIR=$CHURROS_CONTAINER_CARGO_DIR"
        -e "CHURROS_HOST_UID=$uid"
        -e "CHURROS_HOST_GID=$gid")
    if [ -n "$CHURROS_CONTAINER_PLATFORM" ]; then
        run_args+=(--platform "$CHURROS_CONTAINER_PLATFORM")
    fi

    while [ "$#" -gt 0 ]; do
        case "$1" in
            --privileged)
                if [ "$CONTAINER_ROOTLESS" -eq 1 ]; then
                    container_die "docker rootless no puede montar el chroot de mkarchiso.
Usa podman (se ejecuta con sudo) o el demonio de docker normal:
  CHURROS_CONTAINER_ENGINE=podman ./churros build --container"
                fi
                run_args+=(--privileged)
                shift
                ;;
            --upgrade)
                run_args+=(-e CHURROS_CONTAINER_UPGRADE=1)
                shift
                ;;
            -e)
                run_args+=(-e "$2")
                shift 2
                ;;
            --)
                shift
                break
                ;;
            *)
                container_die "container_run: opción desconocida '$1'"
                ;;
        esac
    done

    if [ -t 0 ] && [ -t 1 ]; then
        run_args+=(-it)
    fi

    if [ -n "${CHURROS_CONTAINER_ARGS:-}" ]; then
        read -r -a extra <<< "$CHURROS_CONTAINER_ARGS"
        run_args+=("${extra[@]}")
    fi

    "${CONTAINER_ENGINE[@]}" "${run_args[@]}" "$CHURROS_CONTAINER_IMAGE" \
        bash /churros/scripts/container-entrypoint.sh "$@"
}
