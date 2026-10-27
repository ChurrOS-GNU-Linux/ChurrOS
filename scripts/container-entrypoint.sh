#!/usr/bin/env bash
#
# Punto de entrada del contenedor de build (Containerfile). Lo lanza
# scripts/lib/container.sh como root dentro del contenedor; no se ejecuta en
# el host.
#
# Crea el usuario builder con el UID/GID del host y ejecuta el comando como
# él: lo que escribe en /churros queda a nombre del usuario del host, y
# makepkg se niega a correr como root. build.sh sigue usando sudo para
# mkarchiso y pacman (sin contraseña dentro del contenedor).
set -euo pipefail

if [ "${CHURROS_IN_CONTAINER:-0}" != 1 ] || [ ! -d /churros ]; then
    echo "Error: este script solo se ejecuta dentro del contenedor de build." >&2
    echo "Usa ./churros build --container o ./churros rust." >&2
    exit 1
fi

if [ "$#" -eq 0 ]; then
    set -- bash
fi

uid="${CHURROS_HOST_UID:-1000}"
gid="${CHURROS_HOST_GID:-1000}"

if [ "${CHURROS_CONTAINER_UPGRADE:-0}" = 1 ]; then
    # La imagen puede tener días; makepkg -s instala dependencias y con una
    # base de datos vieja pediría versiones que los mirrors ya no tienen.
    echo "[container] Actualizando el contenedor (pacman -Syu)..."
    # shellcheck disable=SC2046
    pacman -Sy --noconfirm --needed $(pacman -Qq | grep -- '-keyring$')
    pacman -Su --noconfirm
fi

if [ "$uid" -eq 0 ]; then
    # Motor rootless (o build lanzado como root): root del contenedor es el
    # usuario del host.
    exec "$@"
fi

# -o: el UID/GID del host puede coincidir con un usuario de sistema de Arch.
getent group builder >/dev/null || groupadd -o -g "$gid" builder
id builder >/dev/null 2>&1 || useradd -o -u "$uid" -g "$gid" -d /home/builder -s /bin/bash builder

# /home/builder es un volumen persistente: si cambió el UID del host, se
# corrige el dueño de lo que dejó la ejecución anterior.
mkdir -p /home/builder
if [ "$(stat -c %u:%g /home/builder)" != "$uid:$gid" ]; then
    chown -R "$uid:$gid" /home/builder
fi

exec runuser -u builder -- "$@"
