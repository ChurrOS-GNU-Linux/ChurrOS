# shellcheck shell=bash
#
# Detección de la distro del host. Se carga con `source`; no ejecuta nada.
#
# Se lee /etc/os-release en vez de buscar pacman en el PATH: Debian empaqueta
# un juego llamado pacman (/usr/games/pacman) y pacman-package-manager.

# Imprime la familia del host: arch, debian, fedora u other.
# ID_LIKE cubre las derivadas (Manjaro, EndeavourOS, CachyOS, Arch Linux ARM;
# Ubuntu, Mint, Pop!_OS; Nobara, RHEL, Rocky).
churros_host_family() {
    local ids=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        ids=$(. /etc/os-release && printf '%s %s' "${ID:-}" "${ID_LIKE:-}")
    fi
    case " $ids " in
        *" arch "|*" archarm "*) echo arch ;;
        *" debian "|*" ubuntu "*) echo debian ;;
        *" fedora "|*" rhel "*) echo fedora ;;
        *) echo other ;;
    esac
}

churros_host_is_arch() {
    [ "$(churros_host_family)" = arch ]
}

# Nombre legible de la distro, para los mensajes.
churros_host_name() {
    local name=""
    if [ -r /etc/os-release ]; then
        # shellcheck disable=SC1091
        name=$(. /etc/os-release && printf '%s' "${PRETTY_NAME:-${NAME:-}}")
    fi
    printf '%s\n' "${name:-$(uname -s)}"
}

# Dentro del contenedor de build (scripts/container-entrypoint.sh).
churros_in_container() {
    [ "${CHURROS_IN_CONTAINER:-0}" = 1 ]
}

# Un host que no es aarch64 necesita qemu-user + binfmt para correr el
# contenedor de la ISO ARM. En un host aarch64 el mismo contenedor es nativo.
churros_need_aarch64_emulation() {
    [ "$(uname -m)" != aarch64 ]
}

# Directorio de binfmt. CHURROS_BINFMT_DIR solo lo usan las pruebas.
churros_binfmt_dir() {
    printf '%s\n' "${CHURROS_BINFMT_DIR:-/proc/sys/fs/binfmt_misc}"
}

# Ruta de la entrada qemu-aarch64, o retorno 1 si no está registrada.
churros_aarch64_binfmt_entry() {
    local dir entry
    dir="$(churros_binfmt_dir)"
    for entry in "$dir/qemu-aarch64" "$dir/qemu-aarch64-static"; do
        [ -r "$entry" ] || continue
        printf '%s\n' "$entry"
        return 0
    done
    return 1
}

churros_aarch64_binfmt_flags() {
    local entry flags
    entry="$(churros_aarch64_binfmt_entry)" || return 1
    flags="$(awk '/^flags: / { print $2; exit }' "$entry")"
    [ -n "$flags" ] || return 1
    printf '%s\n' "$flags"
}

# La bandera C hace que el kernel calcule las credenciales del binario
# emulado. Sin ella, el setuid de sudo se ignora y makepkg ve
# "effective uid is not 0".
churros_aarch64_binfmt_has_credentials() {
    local flags
    flags="$(churros_aarch64_binfmt_flags)" || return 1
    case "$flags" in
        *C*) return 0 ;;
        *) return 1 ;;
    esac
}

# Cierto si binfmt interpreta aarch64, el intérprete existe y la entrada
# tiene la bandera C. Acepta qemu-aarch64 y qemu-aarch64-static.
churros_aarch64_emulation_ready() {
    local entry interp
    entry="$(churros_aarch64_binfmt_entry)" || return 1
    grep -q '^enabled$' "$entry" || return 1
    interp="$(awk '/^interpreter / { print $2; exit }' "$entry")"
    [ -n "$interp" ] && [ -x "$interp" ] || return 1
    churros_aarch64_binfmt_has_credentials
}

# Cómo volver a registrar qemu-aarch64 con F (persiste en el contenedor) y C.
churros_print_aarch64_binfmt_help() {
    cat <<'EOF'
qemu-aarch64 está registrado sin la bandera C (credentials). sudo dentro de
makepkg falla con "effective uid is not 0": qemu-user conserva el euid de
quien llama y el bit setuid no pasa a root.

Hay que volver a registrar el intérprete con F y C. Como root. El kernel
decodifica las secuencias \x del texto; no hay que pasarlas por printf %b,
porque un NUL corta el magic y el registro pasa a casar con cualquier ELF:

  echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-aarch64
  echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:FPOC' | sudo tee /proc/sys/fs/binfmt_misc/register

Si existe /usr/share/binfmts/qemu-aarch64, las flags de esa plantilla tienen
que incluir C y F, y luego:

  sudo update-binfmts --unimport qemu-aarch64
  sudo update-binfmts --import qemu-aarch64

Con systemd-binfmt, copia /usr/lib/binfmt.d/qemu-aarch64.conf a
/etc/binfmt.d/qemu-aarch64.conf, cambia las flags a FPOC (tienen que incluir
F y C) y reinicia la unidad:

  sudo systemctl restart systemd-binfmt
EOF
}
