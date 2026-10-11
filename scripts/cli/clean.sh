#!/usr/bin/env bash

set -e

echo "Cleaning build directories..."

if [ -d work ]; then
    abs_work=$(cd work 2>/dev/null && pwd)
    if [ -n "$abs_work" ]; then
        if command -v findmnt >/dev/null 2>&1; then
            residual_mounts=$(findmnt -lno TARGET 2>/dev/null | grep "^$abs_work/" | sort -r || true)
        else
            residual_mounts=$(awk -v p="$abs_work" '$2 ~ "^"p"/" {print $2}' /proc/mounts 2>/dev/null | sort -r || true)
        fi
        if [ -n "$residual_mounts" ]; then
            echo "  Desmontando sistemas de archivos residuales en work/..."
            while IFS= read -r mnt; do
                if [ -n "$mnt" ]; then
                    sudo umount -l "$mnt" 2>/dev/null || true
                fi
            done <<< "$residual_mounts"
        fi
    fi
fi

if mountpoint -q work 2>/dev/null; then
    echo "  work is mounted (tmpfs) — cleaning contents..."
    sudo find work -mindepth 1 -delete 2>/dev/null || sudo rm -rf work/* 2>/dev/null || true
else
    sudo rm -rf --one-file-system work
fi
sudo rm -rf --one-file-system out
mkdir -p out

echo "Cleaning temporary airootfs artifacts..."
rm -f archiso/airootfs/etc/churros-edition 2>/dev/null || true
rm -f archiso/airootfs/root/customize_airootfs.sh 2>/dev/null || true
rm -rf --one-file-system archiso/airootfs/root/branding 2>/dev/null || true
rm -rf --one-file-system archiso/airootfs/root/packages 2>/dev/null || true
rm -rf --one-file-system archiso/airootfs/etc/calamares 2>/dev/null || true
rm -f archiso/airootfs/etc/polkit-1/rules.d/49-calamares.rules 2>/dev/null || true
rm -f archiso/airootfs/usr/bin/churros-welcome 2>/dev/null || true
rm -f archiso/airootfs/usr/bin/churros-settings 2>/dev/null || true
rm -f archiso/airootfs/usr/bin/churros-popup 2>/dev/null || true
rm -f archiso/airootfs/usr/bin/churros-control-center 2>/dev/null || true
rm -rf --one-file-system archiso/airootfs/usr/share/churros/grub-theme 2>/dev/null || true

echo "Done."
