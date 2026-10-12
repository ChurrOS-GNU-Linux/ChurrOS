#!/usr/bin/env bash
set -euo pipefail

# ChurrOS - Development dependency installer
#
# Arch Linux y derivadas: todo, incluido archiso para ./churros build.
# Debian/Ubuntu (apt) y Fedora (dnf): lo que usan ./churros check, ./churros run
# y los tests (qemu, OVMF, Rust, Python, Node), más podman para construir la
# ISO con ./churros build --container: mkarchiso y makepkg solo existen en Arch.
#
# Uso: ./install-deps.sh [-y|--yes]   (-y no pide confirmación al gestor)

cd "$(dirname "$0")"

# shellcheck source=scripts/lib/host.sh
source scripts/lib/host.sh

ASSUME_YES=0
WANT_ARM64=0
args=("$@")
i=0
while [ "$i" -lt "${#args[@]}" ]; do
    arg="${args[$i]}"
    case "$arg" in
        -y|--yes) ASSUME_YES=1 ;;
        --arch=arm64|--arch=aarch64) WANT_ARM64=1 ;;
        --arch)
            i=$((i + 1))
            case "${args[$i]:-}" in
                arm64|aarch64) WANT_ARM64=1 ;;
                *)
                    echo "Uso: ./install-deps.sh [-y|--yes] [--arch arm64]" >&2
                    exit 1
                    ;;
            esac
            ;;
        *)
            echo "Uso: ./install-deps.sh [-y|--yes] [--arch arm64]" >&2
            exit 1
            ;;
    esac
    i=$((i + 1))
done

if [[ "${EUID}" -eq 0 ]]; then
    echo "No ejecutes este script como root."
    echo "El script usará sudo cuando sea necesario."
    exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
    echo "ERROR: sudo no está instalado."
    exit 1
fi

FAMILY="$(churros_host_family)"

# rustc/cargo >= 1.85: el workspace usa edition 2024.
RUST_MIN="1.85"

version_ge() {
    [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]
}

rustc_version() {
    rustc --version 2>/dev/null | awk '{print $2}'
}

rust_is_recent() {
    command -v cargo >/dev/null 2>&1 && version_ge "$(rustc_version)" "$RUST_MIN"
}

echo "========================================"
echo "       ChurrOS - Install Dependencies"
echo "========================================"
echo
echo "Host: $(churros_host_name) (familia: $FAMILY)"
echo

REQUIRED=()
OPTIONAL=()
SETUP_RUSTUP=0

case "$FAMILY" in
    arch)
        REQUIRED=(
            archiso
            grub
            git
            qemu-full
            edk2-ovmf
            edk2-aarch64
            rust
            gtk4
            libadwaita
            python
            nodejs
            shellcheck
            gettext
            zstd
        )
        OPTIONAL=(
            virt-manager
            swtpm
        )
        PM_REFRESH=(sudo pacman -Sy)
        PM_INSTALL=(sudo pacman -S --needed)
        if [ "$ASSUME_YES" -eq 1 ]; then PM_INSTALL+=(--noconfirm); fi
        ;;
    debian)
        REQUIRED=(
            git
            qemu-system-x86
            qemu-system-arm
            qemu-utils
            ovmf
            qemu-efi-aarch64
            python3
            nodejs
            shellcheck
            gettext
            zstd
        )
        OPTIONAL=(
            virt-manager
            swtpm
        )
        PM_REFRESH=(sudo apt-get update)
        # dpkg pregunta por los archivos de configuración ya modificados (p. ej.
        # /etc/fuse.conf) aunque se pase -y: se conserva la versión local, o la
        # predeterminada del paquete si no se modificó. La confirmación de apt
        # sigue siendo interactiva sin -y.
        PM_INSTALL=(apt-get install
            -o Dpkg::Options::=--force-confdef
            -o Dpkg::Options::=--force-confold)
        if [ "$ASSUME_YES" -eq 1 ]; then
            # sudo descarta DEBIAN_FRONTEND del entorno: se pasa con env.
            PM_INSTALL=(sudo env DEBIAN_FRONTEND=noninteractive "${PM_INSTALL[@]}" -y)
        else
            PM_INSTALL=(sudo "${PM_INSTALL[@]}")
        fi
        ;;
    fedora)
        REQUIRED=(
            git
            qemu-system-x86
            qemu-system-aarch64
            qemu-img
            edk2-ovmf
            edk2-aarch64
            rust
            cargo
            python3
            nodejs
            ShellCheck
            gettext
            zstd
        )
        OPTIONAL=(
            virt-manager
            swtpm
        )
        PM_REFRESH=(true)
        PM_INSTALL=(sudo dnf install)
        if [ "$ASSUME_YES" -eq 1 ]; then PM_INSTALL+=(-y); fi
        ;;
    *)
        echo "ERROR: $(churros_host_name) no está soportada por este instalador."
        echo
        echo "Instala a mano: git, qemu (x86_64 y aarch64), qemu-img, OVMF/AAVMF,"
        echo "rust >= $RUST_MIN (rustup), python3, node, shellcheck, gettext, zstd"
        echo "y podman o docker. La ISO se construye con ./churros build --container."
        exit 1
        ;;
esac

# Fuera de Arch la ISO se construye en el contenedor: hace falta un motor.
if [ "$FAMILY" != arch ] && ! command -v podman >/dev/null 2>&1 && ! command -v docker >/dev/null 2>&1; then
    REQUIRED+=(podman)
fi

# En un host que no es aarch64, --arch arm64 registra qemu-user para que
# el contenedor Arch Linux ARM arranque. En un host aarch64 no hace falta.
if [ "$WANT_ARM64" -eq 1 ] && [ "$(uname -m)" != aarch64 ]; then
    case "$FAMILY" in
        debian) REQUIRED+=(qemu-user-static binfmt-support) ;;
        fedora) REQUIRED+=(qemu-user-static) ;;
        arch)   REQUIRED+=(qemu-user-static qemu-user-static-binfmt) ;;
        *)
            echo "ERROR: --arch arm64 en $(churros_host_name) necesita qemu-user-static y binfmt a mano." >&2
            exit 1
            ;;
    esac
fi

echo "[1/4] Actualizando la base de datos de paquetes..."
"${PM_REFRESH[@]}"

# El rustc de apt puede ser anterior a edition 2024 (Ubuntu 24.04 trae 1.75).
# En ese caso se instala rustup, que choca con los paquetes rustc/cargo.
if [ "$FAMILY" = debian ] && ! rust_is_recent; then
    candidate="$(apt-cache policy rustc 2>/dev/null | awk '/Candidate:/ {print $2}')"
    rustup_candidate="$(apt-cache policy rustup 2>/dev/null | awk '/Candidate:/ {print $2}')"
    if [ -n "$candidate" ] && [ "$candidate" != "(none)" ] &&
        dpkg --compare-versions "$candidate" ge "$RUST_MIN"; then
        REQUIRED+=(rustc cargo)
    elif [ -n "$rustup_candidate" ] && [ "$rustup_candidate" != "(none)" ]; then
        echo "  rustc de apt (${candidate:-ninguno}) es anterior a $RUST_MIN: se instala rustup."
        REQUIRED+=(rustup)
        SETUP_RUSTUP=1
    else
        # Debian 12 no empaqueta rustup. No se descarga un instalador por
        # nuestra cuenta: la verificación final lo marca como pendiente.
        echo "  Aviso: rustc de apt (${candidate:-ninguno}) es anterior a $RUST_MIN y esta versión"
        echo "  no empaqueta rustup. Instálalo desde https://rustup.rs y vuelve a ejecutar."
    fi
fi

echo
echo "[2/4] Instalando dependencias requeridas..."
"${PM_INSTALL[@]}" "${REQUIRED[@]}"

if [ "$SETUP_RUSTUP" -eq 1 ]; then
    echo "  rustup default stable"
    rustup default stable
fi

echo
echo "[3/4] Instalando dependencias opcionales..."
"${PM_INSTALL[@]}" "${OPTIONAL[@]}" || {
    echo
    echo "Aviso: algunas dependencias opcionales no pudieron instalarse."
    echo "La instalación principal continuará."
}

echo
echo "[4/4] Verificando herramientas..."

# rustup deja cargo en ~/.cargo/bin, que puede no estar aún en el PATH.
if [ -d "$HOME/.cargo/bin" ]; then
    PATH="$HOME/.cargo/bin:$PATH"
fi

FAILED=0

check_command() {
    local name="$1"

    if command -v "$name" >/dev/null 2>&1; then
        printf '  [OK] %s\n' "$name"
    else
        printf '  [FAIL] %s\n' "$name"
        FAILED=1
    fi
}

check_command git
check_command qemu-system-x86_64
check_command qemu-system-aarch64
check_command qemu-img
check_command cargo
check_command rustc
check_command python3
check_command node
check_command shellcheck
check_command msgfmt

if command -v rustc >/dev/null 2>&1 && ! version_ge "$(rustc_version)" "$RUST_MIN"; then
    printf '  [FAIL] rustc %s (hace falta >= %s para edition 2024)\n' "$(rustc_version)" "$RUST_MIN"
    FAILED=1
fi

if [ "$FAMILY" = arch ]; then
    check_command mkarchiso
elif command -v podman >/dev/null 2>&1; then
    check_command podman
else
    check_command docker
fi

if [ "$WANT_ARM64" -eq 1 ] && [ "$(uname -m)" != aarch64 ]; then
    if churros_aarch64_emulation_ready; then
        echo "  [OK] qemu-user aarch64 (binfmt, flag C)"
    elif churros_aarch64_binfmt_entry >/dev/null 2>&1 && ! churros_aarch64_binfmt_has_credentials; then
        echo "  [FAIL] qemu-user aarch64 (binfmt sin bandera C; sudo en makepkg falla)"
        churros_print_aarch64_binfmt_help | sed 's/^/  /'
        FAILED=1
    else
        echo "  [FAIL] qemu-user aarch64 (binfmt no quedó registrado)"
        FAILED=1
    fi
fi

echo

if [[ "$FAILED" -ne 0 ]]; then
    echo "Algunas herramientas requeridas no fueron encontradas."
    exit 1
fi

echo "========================================"
echo " Dependencias de ChurrOS instaladas."
echo " Ya puedes ejecutar:"
echo
if [ "$FAMILY" = arch ]; then
    echo "   ./churros build"
else
    echo "   ./churros check"
    echo "   ./churros build --container   (la ISO se construye en el contenedor Arch)"
    echo "   ./churros rust                (apps GTK en el contenedor, como el CI)"
fi
echo "   ./churros run"
echo "========================================"
