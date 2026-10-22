#!/usr/bin/env bash
# Sustituye en la copia de prueba a scripts/build-calamares.sh,
# scripts/build-aur.sh y scripts/build-bazaar.sh (los reales clonan de AUR y
# compilan con makepkg). Deja en el repo local, con los mismos nombres y la
# misma lógica de "ya existe, no se rehace", los paquetes que dejarían ellos.
# Cada paquete falso es solo su .PKGINFO: el bsdtar de la prueba lo lee.
#
# DRYRUN_PKG_ARCH: arquitectura de los paquetes (la del host donde makepkg
# compilaría; la prueba usa la de la ISO, como recomienda build.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/lib/local-repo.sh
source "$SCRIPT_DIR/lib/local-repo.sh"
PACKAGE_DIR="$(churros_local_repo_dir)"
arch="${DRYRUN_PKG_ARCH:?}"
name="$(basename "$0")"

mkdir -p "$PACKAGE_DIR"
printf '%s %s\n' "$name" "$PACKAGE_DIR" >> "${DRYRUN_LOG:?}/builders.log"

fake_pkg() {
    local pkgname="$1" pkgver="$2" pkgarch="$3"
    shift 3
    if churros_first_pkg "$PACKAGE_DIR" "$pkgname-[0-9]*" >/dev/null; then
        return
    fi
    {
        printf 'pkgname = %s\npkgver = %s\narch = %s\n' "$pkgname" "$pkgver" "$pkgarch"
        printf '%s\n' "$@"
    } > "$PACKAGE_DIR/$pkgname-$pkgver-$pkgarch.pkg.tar.zst"
}

case "$name" in
    build-calamares.sh) fake_pkg calamares 3.4.0-1 "$arch" ;;
    build-aur.sh)
        fake_pkg python-pywal 3.3.0-6 any
        fake_pkg yay 12.4.2-1 "$arch"
        fake_pkg wlogout 1.2.2-1 "$arch"
        ;;
    build-bazaar.sh) fake_pkg bazaar 0.9.7-1 "$arch" 'depend = libdex>=1.2.0' ;;
    *)
        echo "fake-builder: nombre desconocido: $name" >&2
        exit 1
        ;;
esac

churros_repo_add "$PACKAGE_DIR" >/dev/null
