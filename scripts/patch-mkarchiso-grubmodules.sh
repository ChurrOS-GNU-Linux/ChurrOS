#!/usr/bin/env bash
# Filter mkarchiso's hardcoded GRUB module list at runtime.
#
# archiso assigns grubmodules=(...) and passes every name to grub-mkstandalone.
# Arch Linux ARM does not ship all of those modules under
# /usr/lib/grub/arm64-efi/ (at_keyboard, keylayouts, usb, usbserial_*). The
# inserted loop keeps a module only when that .mod file exists for $grub_target.
#
# The script is idempotent. It exits 1 when grubmodules=( is missing, so a
# newer archiso cannot skip the filter silently.
#
# uefi_arch[aarch64]=AA64 (BOOTAA64.EFI), grub_target=arm64-efi, the ucode
# check and the i386 mixed-mode binary are already gated in mkarchiso.
# profiledef.sh selects only uefi.grub on aarch64, so systemd-boot and the
# deprecated uefi-x64 modes are not patched here.
#
#   patch-mkarchiso-grubmodules.sh [/usr/bin/mkarchiso]

set -euo pipefail

MARKER='churros: keep only GRUB modules that exist for this platform.'

file=${1:-/usr/bin/mkarchiso}

if [[ ! -f "$file" ]]; then
    printf 'patch-mkarchiso-grubmodules: %s does not exist\n' "$file" >&2
    exit 1
fi

if grep -qF "$MARKER" "$file"; then
    exit 0
fi

start=$(grep -nE '^[[:space:]]*grubmodules=\(' "$file" | head -n 1 | cut -d: -f1 || true)
if [[ -z "$start" ]]; then
    printf 'patch-mkarchiso-grubmodules: grubmodules=( not found in %s; archiso changed and the GRUB module filter was not applied\n' "$file" >&2
    exit 1
fi

end=0
line_no=0
while IFS= read -r line || [[ -n "$line" ]]; do
    line_no=$((line_no + 1))
    if (( line_no < start )); then
        continue
    fi
    # Backslash-continued array. The closing line has no trailing '\'.
    if [[ "$line" == *'\' ]]; then
        continue
    fi
    if (( line_no == start )) || [[ "$line" == *')'* ]]; then
        end=$line_no
        break
    fi
    printf 'patch-mkarchiso-grubmodules: grubmodules=( at line %s does not continue as an array in %s\n' "$start" "$file" >&2
    exit 1
done < "$file"

if (( end == 0 )); then
    printf 'patch-mkarchiso-grubmodules: grubmodules=( array at line %s is not closed in %s\n' "$start" "$file" >&2
    exit 1
fi

if ! sed -n "${start},${end}p" "$file" | grep -q ')'; then
    printf 'patch-mkarchiso-grubmodules: grubmodules=( array at line %s has no closing paren in %s\n' "$start" "$file" >&2
    exit 1
fi

tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
chmod --reference="$file" "$tmp"
{
    sed -n "1,${end}p" "$file"
    cat <<'EOF'
    # churros: keep only GRUB modules that exist for this platform.
    _churros_grub_keep=()
    for _churros_grub_mod in "${grubmodules[@]}"; do
        if [[ -f "${CHURROS_GRUB_LIB:-/usr/lib/grub}/${grub_target}/${_churros_grub_mod}.mod" ]]; then
            _churros_grub_keep+=("$_churros_grub_mod")
        else
            _msg_warning "GRUB module '${_churros_grub_mod}' is not in ${CHURROS_GRUB_LIB:-/usr/lib/grub}/${grub_target}; skipping it"
        fi
    done
    if (( ${#_churros_grub_keep[@]} == 0 )); then
        _msg_error "No GRUB modules found in ${CHURROS_GRUB_LIB:-/usr/lib/grub}/${grub_target}" 1
    fi
    grubmodules=("${_churros_grub_keep[@]}")
    unset -v _churros_grub_keep _churros_grub_mod
EOF
    total=$(wc -l < "$file")
    if (( end < total )); then
        sed -n "$((end + 1)),\$p" "$file"
    fi
} > "$tmp"

mv -f "$tmp" "$file"
trap - EXIT
