#!/usr/bin/env bash
# Install or remove the aarch64 mkinitcpio preset and hook list.
#
# mkarchiso copies airootfs before pacstrap. The x86 linux.preset would make
# mkinitcpio look for /boot/vmlinuz-linux, so apply moves it aside. The ARM
# preset is NOT written to /etc/mkinitcpio.d/: linux-aarch64 owns that path
# and pacstrap aborts with "exists in filesystem". It is staged under
# /usr/share/churros, and customize_airootfs.sh installs it after pacstrap.
# etc/mkinitcpio.conf.d/archiso.conf is not owned by any ALARM package, so
# replacing it here is safe and the package hook sees the ARM hooks.
# restore puts the tree back so an x86 build is unchanged.
#
#   apply-aarch64-mkinitcpio.sh apply
#   apply-aarch64-mkinitcpio.sh restore

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
AIROOTFS="$ROOT/archiso/airootfs"
SRC="$ROOT/archiso/mkinitcpio/aarch64"
PRESET_DIR="$AIROOTFS/etc/mkinitcpio.d"
CONF_DIR="$AIROOTFS/etc/mkinitcpio.conf.d"
SHARE_DIR="$AIROOTFS/usr/share/churros/mkinitcpio/aarch64"
PRESET_STASH="$PRESET_DIR/linux.preset.x86-stash"
CONF_STASH="$CONF_DIR/archiso.conf.x86-stash"

apply_aarch64() {
    if [ ! -f "$SRC/linux-aarch64.preset" ] || [ ! -f "$SRC/archiso.conf" ]; then
        printf 'apply-aarch64-mkinitcpio: missing %s\n' "$SRC" >&2
        exit 1
    fi

    mkdir -p "$PRESET_DIR" "$CONF_DIR" "$SHARE_DIR"
    # Stash once. A second apply must not treat the ARM files as the x86 originals.
    if [ ! -f "$PRESET_STASH" ] && [ -f "$PRESET_DIR/linux.preset" ]; then
        mv "$PRESET_DIR/linux.preset" "$PRESET_STASH"
    fi
    if [ ! -f "$CONF_STASH" ] && [ -f "$CONF_DIR/archiso.conf" ]; then
        cp -a "$CONF_DIR/archiso.conf" "$CONF_STASH"
    fi

    cp -a "$SRC/linux-aarch64.preset" "$SHARE_DIR/linux-aarch64.preset"
    cp -a "$SRC/archiso.conf" "$SHARE_DIR/archiso.conf"
    # archiso.conf is not shipped by mkinitcpio or mkinitcpio-archiso.
    cp -a "$SRC/archiso.conf" "$CONF_DIR/archiso.conf"
    rm -f "$PRESET_DIR/linux.preset" "$PRESET_DIR/linux-aarch64.preset"
}

restore_x86() {
    if [ -f "$PRESET_STASH" ]; then
        mv -f "$PRESET_STASH" "$PRESET_DIR/linux.preset"
    fi
    if [ -f "$CONF_STASH" ]; then
        mv -f "$CONF_STASH" "$CONF_DIR/archiso.conf"
    fi
    rm -f "$PRESET_DIR/linux-aarch64.preset"
    rm -rf --one-file-system "$AIROOTFS/usr/share/churros/mkinitcpio"
}

case "${1:-}" in
    apply) apply_aarch64 ;;
    restore) restore_x86 ;;
    *)
        printf 'usage: %s apply|restore\n' "$0" >&2
        exit 1
        ;;
esac
