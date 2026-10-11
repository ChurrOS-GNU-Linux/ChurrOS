# shellcheck shell=bash
#
# Elige un par CODE/VARS de firmware pflash del mismo tamaño.
# Se carga con `source`; no ejecuta nada.
#
# QEMU aborta si las dos imágenes pflash miden distinto. En Debian el
# QEMU_EFI.fd de qemu-efi-aarch64 ocupa unos 3 MiB y AAVMF_VARS.fd ocupa
# 64 MiB: no se pueden mezclar. En aarch64 gana el primer par en el que
# ambos ficheros existen y miden igual (siguiendo symlinks); en x86 basta
# con que existan los dos del par. Si en aarch64 solo está el QEMU_EFI.fd crudo,
# se rellenan copias a 64 MiB (el tamaño del pflash de AAVMF).

# Imprime dos rutas (CODE y plantilla VARS) y devuelve 0.
# $1: aarch64 o x86_64
# $2: directorio donde escribir las copias rellenadas
# CHURROS_FIRMWARE_ROOT antepone un prefijo a /usr (tests).
churros_resolve_pflash() {
    local arch=$1
    local out_dir=$2
    local entry code vars code_path vars_path
    local -a pairs=()
    local root="${CHURROS_FIRMWARE_ROOT:-}"

    case "$arch" in
        aarch64)
            pairs=(
                "/usr/share/AAVMF/AAVMF_CODE.fd|/usr/share/AAVMF/AAVMF_VARS.fd"
                "/usr/share/edk2/aarch64/QEMU_CODE.fd|/usr/share/edk2/aarch64/QEMU_VARS.fd"
                "/usr/share/edk2/aarch64/QEMU_EFI.fd|/usr/share/edk2/aarch64/QEMU_VARS.fd"
                "/usr/share/edk2/aarch64/QEMU_EFI-pflash.raw|/usr/share/edk2/aarch64/QEMU_VARS.fd"
                "/usr/share/qemu-efi-aarch64/QEMU_EFI.fd|/usr/share/qemu-efi-aarch64/QEMU_VARS.fd"
            )
            ;;
        x86_64)
            pairs=(
                "/usr/share/edk2/x64/OVMF_CODE.4m.fd|/usr/share/edk2/x64/OVMF_VARS.4m.fd"
                "/usr/share/edk2-ovmf/x64/OVMF_CODE.4m.fd|/usr/share/edk2-ovmf/x64/OVMF_VARS.4m.fd"
                "/usr/share/ovmf/x64/OVMF_CODE.4m.fd|/usr/share/ovmf/x64/OVMF_VARS.4m.fd"
                "/usr/share/OVMF/OVMF_CODE_4M.fd|/usr/share/OVMF/OVMF_VARS_4M.fd"
                "/usr/share/OVMF/OVMF_CODE.4m.fd|/usr/share/OVMF/OVMF_VARS.4m.fd"
                "/usr/share/edk2/x64/OVMF_CODE.fd|/usr/share/edk2/x64/OVMF_VARS.fd"
                "/usr/share/edk2-ovmf/x64/OVMF_CODE.fd|/usr/share/edk2-ovmf/x64/OVMF_VARS.fd"
                "/usr/share/OVMF/OVMF_CODE.fd|/usr/share/OVMF/OVMF_VARS.fd"
                "/usr/share/ovmf/OVMF_CODE.fd|/usr/share/ovmf/OVMF_VARS.fd"
            )
            ;;
        *)
            printf 'churros_resolve_pflash: unsupported arch %s\n' "$arch" >&2
            return 1
            ;;
    esac

    for entry in "${pairs[@]}"; do
        code="${entry%%|*}"
        vars="${entry#*|}"
        code_path="${root}${code}"
        vars_path="${root}${vars}"
        [ -f "$code_path" ] && [ -f "$vars_path" ] || continue
        # Solo aarch64 exige mismo tamaño (pflash de 64 MiB). En x86 CODE y
        # VARS miden distinto legítimamente; se emparejan por nombre.
        if [ "$arch" != aarch64 ] \
            || [ "$(stat -L -c %s "$code_path")" -eq "$(stat -L -c %s "$vars_path")" ]; then
            printf '%s\n%s\n' "$code_path" "$vars_path"
            return 0
        fi
    done

    if [ "$arch" = aarch64 ]; then
        _churros_pflash_pad_aarch64 "$out_dir"
        return
    fi

    printf 'churros_resolve_pflash: no matching %s CODE/VARS pair\n' "$arch" >&2
    return 1
}

# Rellena el QEMU_EFI.fd crudo (y una plantilla VARS, si hay) hasta 64 MiB.
_churros_pflash_pad_aarch64() {
    local out_dir=$1
    local root="${CHURROS_FIRMWARE_ROOT:-}"
    local candidate code_src="" vars_src=""
    local -a codes=(
        /usr/share/qemu-efi-aarch64/QEMU_EFI.fd
        /usr/share/edk2/aarch64/QEMU_EFI.fd
        /usr/share/edk2/aarch64/QEMU_EFI-pflash.raw
    )
    # AAVMF_VARS antes que un QEMU_VARS pequeño: es la plantilla de 64 MiB.
    local -a vars_candidates=(
        /usr/share/AAVMF/AAVMF_VARS.fd
        /usr/share/qemu-efi-aarch64/QEMU_VARS.fd
        /usr/share/edk2/aarch64/QEMU_VARS.fd
    )
    local pad=$((64 * 1024 * 1024))
    local code_bytes vars_bytes=0
    local code_out vars_out

    for candidate in "${codes[@]}"; do
        if [ -f "${root}${candidate}" ]; then
            code_src="${root}${candidate}"
            break
        fi
    done
    if [ -z "$code_src" ]; then
        printf 'churros_resolve_pflash: no aarch64 UEFI code image found\n' >&2
        return 1
    fi
    for candidate in "${vars_candidates[@]}"; do
        if [ -f "${root}${candidate}" ]; then
            vars_src="${root}${candidate}"
            break
        fi
    done

    code_bytes=$(stat -L -c %s "$code_src")
    if [ -n "$vars_src" ]; then
        vars_bytes=$(stat -L -c %s "$vars_src")
    fi
    if (( code_bytes > pad )); then
        pad=$code_bytes
    fi
    if (( vars_bytes > pad )); then
        pad=$vars_bytes
    fi

    mkdir -p "$out_dir"
    code_out="$out_dir/pflash-code.fd"
    vars_out="$out_dir/pflash-vars.fd"
    _churros_pflash_pad_file "$code_src" "$code_out" "$pad"
    _churros_pflash_pad_file "$vars_src" "$vars_out" "$pad"
    printf '%s\n%s\n' "$code_out" "$vars_out"
}

# Copia src sobre un fichero de exactamente bytes. src vacío deja ceros.
_churros_pflash_pad_file() {
    local src=$1
    local dest=$2
    local bytes=$3

    rm -f "$dest"
    truncate -s "$bytes" "$dest"
    if [ -n "$src" ]; then
        dd if="$src" of="$dest" conv=notrunc status=none
    fi
}
