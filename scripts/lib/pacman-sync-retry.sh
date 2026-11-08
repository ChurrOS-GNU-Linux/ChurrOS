# shellcheck shell=bash
# Reintenta las operaciones de sincronización del contenedor de build.
# Uso: pacman_sync_with_retry pacman -Sy ...
pacman_sync_with_retry() {
    local attempts="${CHURROS_PACMAN_SYNC_ATTEMPTS:-3}"
    local delay="${CHURROS_PACMAN_SYNC_RETRY_DELAY:-5}"
    local attempt=1 status

    if [[ ! "$attempts" =~ ^([1-9]|10)$ ]]; then
        printf 'Error: CHURROS_PACMAN_SYNC_ATTEMPTS debe ser un entero entre 1 y 10 (recibido: %s).\n' \
            "$attempts" >&2
        return 2
    fi
    if [[ ! "$delay" =~ ^[0-9]+([.][0-9]+)?$ ]]; then
        printf 'Error: CHURROS_PACMAN_SYNC_RETRY_DELAY debe ser un número no negativo (recibido: %s).\n' \
            "$delay" >&2
        return 2
    fi

    while :; do
        if "$@"; then
            return 0
        else
            status=$?
        fi

        if (( attempt >= attempts )); then
            printf 'Error: la sincronización de pacman falló tras %s intento(s). Revisa la conexión y la resolución DNS del host y del contenedor. Si tu red requiere un DNS específico, pásalo al contenedor con CHURROS_CONTAINER_ARGS="--dns DIRECCION_DNS".\n' \
                "$attempts" >&2
            return "$status"
        fi

        attempt=$((attempt + 1))
        printf '[container] Falló la sincronización de pacman; reintento %s/%s en %s s...\n' \
            "$attempt" "$attempts" "$delay" >&2
        sleep "$delay"
    done
}
