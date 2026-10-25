#!/usr/bin/env bash

set -e

# shellcheck source=scripts/lib/host.sh
source "$(dirname "$0")/../lib/host.sh"
# shellcheck source=scripts/lib/local-repo.sh
source "$(dirname "$0")/../lib/local-repo.sh"

HOST_REPO_SYMLINK=0
EDITION="niri"
# Sin --arch se usa la arquitectura del equipo (uname -m).
TARGET_ARCH=""
USE_CONTAINER=0
USE_CLUSTER=0
# Argumentos que se reenvían al build dentro del contenedor (sin --container).
BUILD_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        --container)
            USE_CONTAINER=1
            shift
            continue
            ;;
        --cluster|-c)
            USE_CLUSTER=1
            shift
            continue
            ;;
    esac
    BUILD_ARGS+=("$1")
    case "$1" in
        --edition|-e)
            BUILD_ARGS+=("${2-}")
            EDITION="$2"
            shift 2
            ;;
        --edition=*)
            EDITION="${1#*=}"
            shift
            ;;
        --arch|-a)
            BUILD_ARGS+=("${2-}")
            TARGET_ARCH="$2"
            shift 2
            ;;
        --arch=*)
            TARGET_ARCH="${1#*=}"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

[ -n "$TARGET_ARCH" ] || TARGET_ARCH="$(uname -m)"
case "$TARGET_ARCH" in
    arm64) TARGET_ARCH="aarch64" ;;
    i386|i486|i586|i686) TARGET_ARCH="i686" ;;
    x86_64|aarch64) ;;
    *)
        echo "Error: unsupported architecture '$TARGET_ARCH' (use --arch x86_64, --arch arm64 or --arch i686)." >&2
        exit 1
        ;;
esac

PACKAGE_LIST="archiso/packages.${TARGET_ARCH}"

# Los paquetes locales ([churros]: calamares, bazaar, yay, wlogout, pywal) los
# compila makepkg para la arquitectura del host. Construir aquí una ISO de otra
# arquitectura deja paquetes incompatibles en el repo y pacstrap falla con
# "wrong architecture"; usa un host de esa arquitectura.
HOST_ARCH="$(uname -m)"
case "$HOST_ARCH" in
    arm64) HOST_ARCH="aarch64" ;;
    i386|i486|i586|i686) HOST_ARCH="i686" ;;
esac
if [ "$TARGET_ARCH" != "$HOST_ARCH" ]; then
    echo "WARNING: construyendo la ISO $TARGET_ARCH en un host $HOST_ARCH." >&2
    echo "         Los paquetes locales del repo [churros] deben estar compilados" >&2
    echo "         para $TARGET_ARCH o pacstrap rechazará los del host." >&2
fi

EDITION=$(echo "$EDITION" | tr '[:upper:]' '[:lower:]')
if [ "$EDITION" != "niri" ] && [ "$EDITION" != "xfce" ] && [ "$EDITION" != "server" ] && [ "$EDITION" != "pi" ]; then
    echo "Error: unsupported edition '$EDITION' (supported: niri, xfce, server, pi)" >&2
    exit 1
fi

# Solo niri y pi tienen lista aarch64. El resto seguiría copiando
# packages.<edicion>.x86_64 o fallaría a medias.
if [ "$TARGET_ARCH" = aarch64 ] && [ "$EDITION" != niri ] && [ "$EDITION" != pi ]; then
    echo "Error: la ISO aarch64 solo tiene la edición niri o pi (no hay packages.${EDITION}.aarch64)." >&2
    exit 1
fi

# En un host que no es aarch64, pacstrap y makepkg tienen que ser nativos
# de Arch Linux ARM. Sin --container se estarían usando las herramientas
# x86_64 del host.
if [ "$TARGET_ARCH" = aarch64 ] && [ "$(uname -m)" != aarch64 ] && ! churros_in_container && [ "$USE_CONTAINER" -ne 1 ]; then
    echo "Error: este host es $(uname -m). La ISO aarch64 se construye entera dentro de" >&2
    echo "un contenedor Arch Linux ARM (qemu-user en x86_64, nativo en aarch64):" >&2
    echo "  ./churros build --container --arch arm64" >&2
    echo "Comprueba binfmt con:" >&2
    echo "  ./churros doctor --arch arm64" >&2
    exit 1
fi

# --container: el build completo (makepkg de AUR, Rust, mkarchiso) corre en el
# contenedor Arch del Containerfile. El repo se monta dentro, así que la ISO
# queda en out/ igual que en un build normal. --privileged porque pacstrap
# monta proc, sys y dev en el chroot de la ISO.
# aarch64 usa Containerfile.aarch64 (--platform linux/arm64): el mismo
# contenedor es nativo en un host ARM y emulado con qemu-user en x86_64.
if [ "$USE_CONTAINER" -eq 1 ] && ! churros_in_container; then
    # shellcheck source=scripts/lib/container.sh
    source "$(dirname "$0")/../lib/container.sh"

    if [ "$TARGET_ARCH" = aarch64 ]; then
        container_use_arch aarch64
        if churros_need_aarch64_emulation && ! churros_aarch64_emulation_ready; then
            if churros_aarch64_binfmt_entry >/dev/null 2>&1 && ! churros_aarch64_binfmt_has_credentials; then
                echo "Error: qemu-aarch64 binfmt está registrado sin la bandera C (credentials)." >&2
                echo "sudo dentro de makepkg falla con 'effective uid is not 0'." >&2
                churros_print_aarch64_binfmt_help >&2
            else
            echo "Error: falta qemu-user aarch64 (binfmt) para construir la ISO ARM en este host." >&2
            echo "  Debian/Ubuntu: sudo apt install qemu-user-static binfmt-support" >&2
            echo "  Fedora:        sudo dnf install qemu-user-static" >&2
            echo "  Arch:          sudo pacman -S qemu-user-static qemu-user-static-binfmt" >&2
            echo "  o:             ./install-deps.sh --arch arm64" >&2
            fi
            echo "Comprueba con: ./churros doctor --arch arm64" >&2
            exit 1
        fi
        echo "[container] Build de la edición $EDITION ($TARGET_ARCH) en el contenedor Arch Linux ARM."
    else
        echo "[container] Build de la edición $EDITION ($TARGET_ARCH) en el contenedor Arch."
    fi
    container_engine_init
    container_ensure_image
    # La arquitectura ya resuelta en el host manda: dentro de un contenedor
    # emulado, uname -m daría la de la imagen.
    container_run --privileged --upgrade -- \
        bash scripts/cli/build.sh ${BUILD_ARGS[@]+"${BUILD_ARGS[@]}"} --arch "$TARGET_ARCH"
    exit 0
fi

# x86_64 sigue en archiso/packages/. aarch64 tiene su propio directorio para
# que un paquete -x86_64 no entre en el repo que pacstrap de la ISO ARM.
if [ "$TARGET_ARCH" = aarch64 ]; then
    LOCAL_REPO="archiso/packages/aarch64"
else
    LOCAL_REPO="archiso/packages"
fi
mkdir -p "$LOCAL_REPO"
export CHURROS_PKG_DIR="$PWD/$LOCAL_REPO"

PACKAGES_BACKED_UP=0
unmount_work_submounts() {
    local target_dir="${1:-work}"
    if [ -d "$target_dir" ]; then
        local abs_target
        abs_target=$(cd "$target_dir" 2>/dev/null && pwd)
        if [ -n "$abs_target" ]; then
            local mounts
            if command -v findmnt >/dev/null 2>&1; then
                mounts=$(findmnt -lno TARGET 2>/dev/null | grep "^$abs_target/" | sort -r || true)
            else
                mounts=$(awk -v p="$abs_target" '$2 ~ "^"p"/" {print $2}' /proc/mounts 2>/dev/null | sort -r || true)
            fi
            if [ -n "$mounts" ]; then
                echo "  [cleanup] Desmontando sistemas de archivos residuales en $target_dir..."
                while IFS= read -r mnt; do
                    if [ -n "$mnt" ]; then
                        sudo umount -l "$mnt" 2>/dev/null || true
                    fi
                done <<< "$mounts"
            fi
        fi
    fi
}

cleanup_temp() {
    echo "[cleanup] Removing temporary build files..."
    unmount_work_submounts work
    if [ "$HOST_REPO_SYMLINK" -eq 1 ]; then
        echo "[cleanup] Removing host /root/packages symlink..."
        sudo rm -f /root/packages 2>/dev/null || true
    fi
    if [ "$PACKAGES_BACKED_UP" -eq 1 ] && [ -f "$PACKAGE_LIST.orig" ]; then
        mv "$PACKAGE_LIST.orig" "$PACKAGE_LIST"
    fi
    if [ -f archiso/airootfs/etc/greetd/config.toml.bak ]; then
        mv archiso/airootfs/etc/greetd/config.toml.bak archiso/airootfs/etc/greetd/config.toml
    fi
    rm -f archiso/airootfs/etc/churros-edition 2>/dev/null || true
    rm -f archiso/airootfs/root/customize_airootfs.sh 2>/dev/null || true
    rm -rf --one-file-system archiso/airootfs/root/branding 2>/dev/null || true
    rm -rf --one-file-system archiso/airootfs/root/packages 2>/dev/null || true
    rm -rf --one-file-system archiso/airootfs/etc/calamares 2>/dev/null || true
    rm -f archiso/airootfs/etc/polkit-1/rules.d/49-calamares.rules 2>/dev/null || true
    # Binarios Rust desplegados por build-rust.sh (no se versionan en git)
    rm -f archiso/airootfs/usr/bin/churros-welcome 2>/dev/null || true
    rm -f archiso/airootfs/usr/bin/churros-settings 2>/dev/null || true
    rm -f archiso/airootfs/usr/bin/churros-popup 2>/dev/null || true
    rm -f archiso/airootfs/usr/bin/churros-control-center 2>/dev/null || true
    rm -f archiso/airootfs/usr/bin/churros-tour 2>/dev/null || true
    # GRUB theme copiado al airootfs para que esté disponible en el sistema instalado
    rm -rf --one-file-system archiso/airootfs/usr/share/churros/grub-theme 2>/dev/null || true
    # Preset y hooks de mkinitcpio que apply-aarch64-mkinitcpio.sh mete solo
    # en el build ARM. En x86 restore no encuentra el stash y no toca nada.
    bash scripts/apply-aarch64-mkinitcpio.sh restore
}

trap cleanup_temp EXIT

echo "======================================"
echo "      ChurrOS Build System"
echo "      Edition: ${EDITION^^}"
echo "      Arch: ${TARGET_ARCH}"
echo "======================================"
echo

# Pre-flight: validar dependencias esenciales del host antes de compilar
missing_deps=()
for tool in mkarchiso mksquashfs xorriso; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        missing_deps+=("$tool")
    fi
done

if ! command -v grub-mkstandalone >/dev/null 2>&1; then
    missing_deps+=("grub (comando grub-mkstandalone requerido para uefi.grub)")
fi

if ! command -v mkfs.fat >/dev/null 2>&1; then
    missing_deps+=("dosfstools (comando mkfs.fat)")
fi

if ! command -v mcopy >/dev/null 2>&1 || ! command -v mmd >/dev/null 2>&1; then
    missing_deps+=("mtools (comandos mcopy y mmd)")
fi

if [ "${#missing_deps[@]}" -gt 0 ]; then
    echo "Error: Faltan dependencias en el host para compilar la ISO con mkarchiso:" >&2
    for dep in "${missing_deps[@]}"; do
        echo "  - $dep" >&2
    done
    echo >&2
    if churros_in_container; then
        if [ "$TARGET_ARCH" = aarch64 ]; then
            echo "La imagen del contenedor no trae estas herramientas: revisa Containerfile.aarch64" >&2
        else
            echo "La imagen del contenedor no trae estas herramientas: revisa Containerfile" >&2
        fi
        echo "y reconstruye la imagen con CHURROS_CONTAINER_REBUILD=1." >&2
        exit 1
    elif churros_host_is_arch; then
        echo "Instálalas con:" >&2
        echo "  sudo pacman -S --needed archiso grub dosfstools mtools squashfs-tools libisoburn" >&2
        echo >&2
        echo "O construye en el contenedor Arch del proyecto:" >&2
    else
        # mkarchiso, pacstrap y makepkg solo existen en Arch: instalar herramientas
        # sueltas en otra distro no basta.
        echo "Este host es $(churros_host_name), no Arch Linux: mkarchiso y makepkg no están" >&2
        echo "disponibles aquí. Construye la ISO en el contenedor Arch del proyecto" >&2
        echo "(necesita podman o docker):" >&2
    fi
    echo "  ./churros build --container${BUILD_ARGS[*]:+ ${BUILD_ARGS[*]}}" >&2
    exit 1
fi

# 0. Configurar paquetes según la edición
if [ "$EDITION" != "niri" ]; then
    PKG_LIST="archiso/packages.${EDITION}.${TARGET_ARCH}"
    echo "[0/5] Selecting ${EDITION} packages..."
    if [ -f "$PKG_LIST" ]; then
        cp "$PACKAGE_LIST" "$PACKAGE_LIST.orig"
        PACKAGES_BACKED_UP=1
        cp "$PKG_LIST" "$PACKAGE_LIST"
    else
        echo "Error: $PKG_LIST not found!" >&2
        exit 1
    fi
fi

# Guardar la edición activa en el airootfs
mkdir -p archiso/airootfs/etc
echo "$EDITION" > archiso/airootfs/etc/churros-edition

# Configurar greetd autologin para la sesión Live.
# SESSION_CMD es el punto de entrada al escritorio de cada edición.
mkdir -p archiso/airootfs/etc/greetd

# La edición server arranca en XFCE porque su único escritorio está en la ISO
# para poder ejecutar el instalador gráfico; el sistema instalado lo quita
# después configure-server.
# Cada edición tiene su brazo explícito: si mañana se añade una y se olvida
# este case, el build se para aquí en vez de generar una ISO que instala mal.
case "$EDITION" in
    niri)                SESSION_CMD="niri" ;;
    xfce|server)         SESSION_CMD="/usr/bin/churros-xfce-session" ;;
    pi)                SESSION_CMD="/usr/bin/churros-pi-session" ;;
    *)
        echo "Error: sin comando de sesión definido para la edición '$EDITION'" >&2
        exit 1
        ;;
esac

if [ -f archiso/airootfs/etc/greetd/config.toml ] && [ ! -f archiso/airootfs/etc/greetd/config.toml.bak ]; then
    cp archiso/airootfs/etc/greetd/config.toml archiso/airootfs/etc/greetd/config.toml.bak
fi

cat > archiso/airootfs/etc/greetd/config.toml << EOF
[terminal]
vt = 7

[default_session]
command = "env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24 cage -s -- regreet"
user = "greeter"

[initial_session]
command = "$SESSION_CMD"
user = "churros"
EOF

echo "[1/5] Preparing branding..."

bash scripts/build-grub-theme.sh

mkdir -p archiso/airootfs/root

cp branding/customize_airootfs.sh \
    archiso/airootfs/root/customize_airootfs.sh

mkdir -p archiso/airootfs/root/branding

cp -r branding/files \
    archiso/airootfs/root/branding/

cp VERSION archiso/airootfs/root/branding/VERSION
cp branding/stamp-os-release.sh archiso/airootfs/root/branding/stamp-os-release.sh
chmod +x archiso/airootfs/root/branding/stamp-os-release.sh
CHURROS_VERSION=$(tr -d '[:space:]' < VERSION)
bash branding/stamp-os-release.sh \
    archiso/airootfs/root/branding/files/os-release \
    "$CHURROS_VERSION" \
    "$EDITION"

if [ -d branding/grub-theme ]; then
    cp -r branding/grub-theme \
        archiso/airootfs/root/branding/grub-theme

    mkdir -p archiso/airootfs/usr/share/churros
    cp -r branding/grub-theme \
        archiso/airootfs/usr/share/churros/grub-theme
fi

echo "[2/5] Checking packages..."

# Noctalia v4 (noctalia-qs + noctalia-shell) se compilaba desde AUR; la ISO
# instala ahora `noctalia` de [extra]. Los paquetes que dejó un build anterior
# se copiarían a /root/packages y seguirían en el índice churros.db.
for obsolete_pkg in noctalia-qs noctalia-qs-debug noctalia-shell; do
    if compgen -G "${LOCAL_REPO}/${obsolete_pkg}-*.pkg.tar.*" >/dev/null; then
        echo "  Removing obsolete local package: $obsolete_pkg"
        churros_remove_pkgs "$LOCAL_REPO" "${obsolete_pkg}-*"
    fi
    if [ -f "$LOCAL_REPO/churros.db.tar.gz" ] &&
        tar -tzf "$LOCAL_REPO/churros.db.tar.gz" 2>/dev/null | grep -qE "^${obsolete_pkg}-[^-/]+-[^-/]+/desc$"; then
        repo-remove -q "$LOCAL_REPO/churros.db.tar.gz" "$obsolete_pkg"
    fi
done

# El repo local es compartido entre arquitecturas: un calamares/yay/wlogout de
# un build x86_64 quedaría aquí y pacstrap lo rechazaría al construir i686
# (o aarch64). Se descartan los paquetes cuyo arch (.PKGINFO) no coincide.
# bsdtar lo expone; si no está disponible (no debería en un host de build Arch),
# se deja como está y el warning de arriba avisa.
if command -v bsdtar >/dev/null 2>&1; then
    for pkg in archiso/packages/*.pkg.tar.zst; do
        [ -f "$pkg" ] || continue
        pkg_arch=$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null | sed -n 's/^arch = //p' | head -n1)
        if [ -n "$pkg_arch" ] && [ "$pkg_arch" != "any" ] && [ "$pkg_arch" != "$TARGET_ARCH" ]; then
            echo "  Removing local package for wrong architecture ($pkg_arch): $(basename "$pkg")"
            rm -f "$pkg"
        fi
    done
    if ls archiso/packages/*.pkg.tar.zst >/dev/null 2>&1; then
        repo-add -q archiso/packages/churros.db.tar.gz archiso/packages/*.pkg.tar.zst 2>/dev/null || true
    fi
fi

# Always invoke: rebuilds if the package is missing or linked against a
# different libpython than the ISO's `python` package (pacstrap).
# Always invoke Calamares on supported architectures: it rebuilds if missing or linked against a different libpython than the ISO. Arch Linux 32 lacks polkit-qt6, required by the PKGBUILD.
if [ "$TARGET_ARCH" = "i686" ]; then
    echo "  [i686] Calamares omitido: archlinux32 no empaqueta polkit-qt6."
else
    bash scripts/build-calamares.sh
fi

if [ "$TARGET_ARCH" = "x86_64" ] && { grep -q '^linux-churrosvyper' "$PACKAGE_LIST" 2>/dev/null || [ "$USE_CLUSTER" -eq 1 ]; }; then
    kernel_build_opts=()
    [ "$USE_CLUSTER" -eq 1 ] && kernel_build_opts+=("--cluster")
    bash scripts/build-kernel-vyper.sh ${kernel_build_opts[@]+"${kernel_build_opts[@]}"}
fi
CALAMARES_PKG="$(churros_first_pkg "$LOCAL_REPO" 'calamares-[0-9]*' || true)"
PYWAL_PKG="$(churros_first_pkg "$LOCAL_REPO" 'python-pywal-*' || true)"
YAY_PKG="$(churros_first_pkg "$LOCAL_REPO" 'yay-*' || true)"
WLOGOUT_PKG="$(churros_first_pkg "$LOCAL_REPO" 'wlogout-*' || true)"

# En i686 no existen para la arquitectura (vistos arriba) y además pueden
# quedar en archiso/packages/ los de un build x86_64 previo: integrarlos haría
# que pacstrap los rechace por arquitectura. Fuerzan el camino "sin instalador".
if [ "$TARGET_ARCH" = "i686" ]; then
    CALAMARES_PKG=""
    BAZAAR_PKG=""
fi

if [ -z "$PYWAL_PKG" ] || [ -z "$YAY_PKG" ] || [ -z "$WLOGOUT_PKG" ]; then
    echo "  AUR extras not found — building..."
    bash scripts/build-aur.sh
fi

if [ "$TARGET_ARCH" = "i686" ]; then
    echo "  [i686] Bazaar omitido: archlinux32 no empaqueta webkitgtk-6.0 ni glycin."
else
    # Siempre: el script reutiliza el paquete si ya depende de libdex>=1.2.
    echo "  Bazaar (libdex >= 1.2)..."
    bash scripts/build-bazaar.sh
fi

if [ -n "$CALAMARES_PKG" ]; then
    echo "  Integrating Calamares installer..."

    CHURROS_ARCH="$TARGET_ARCH" bash installer/apply-calamares.sh

    # El slideshow del instalador se despliega con un marcador @EDITION@: el
    # texto que ve la persona depende de la edición que esta instalando.
    case "$EDITION" in
        xfce)   EDITION_NAME="XFCE" ;;
        server) EDITION_NAME="Servidor" ;;
    pi)   EDITION_NAME="Raspberry Pi Lite" ;;
        *)      EDITION_NAME="Niri" ;;
    esac

    SHOW_QML="archiso/airootfs/etc/calamares/branding/churros/show.qml"
    if [ -f "$SHOW_QML" ]; then
        sed -i "s/@EDITION@/$EDITION_NAME/g" "$SHOW_QML"
        echo "  Installer slideshow edition: $EDITION_NAME"
    fi

    mkdir -p archiso/airootfs/root/packages
    churros_copy_pkgs "$LOCAL_REPO" archiso/airootfs/root/packages
    cp "$LOCAL_REPO"/churros.db* archiso/airootfs/root/packages/ 2>/dev/null || true
    cp "$LOCAL_REPO"/churros.files* archiso/airootfs/root/packages/ 2>/dev/null || true
else
    echo "  Calamares not available — building without installer."
fi

echo "[3/5] Building Rust apps...";

bash scripts/build-rust.sh;

echo "[4/5] Cleaning previous build...";

unmount_work_submounts work
if mountpoint -q work 2>/dev/null; then
    echo "  work is mounted (tmpfs) — cleaning contents..."
    sudo find work -mindepth 1 -delete 2>/dev/null || sudo rm -rf work/* 2>/dev/null || true
else
    sudo rm -rf --one-file-system work
fi
sudo rm -rf --one-file-system out
mkdir -p out

echo "[5/5] Building ISO...";

# El repo local [churros] usa Server = file:///root/packages. Durante pacstrap
# file:// se resuelve contra el root del HOST (no el chroot), así que exponemos
# el repo local en /root/packages del host para que el build lo encuentre.
LOCAL_REPO_LINK="$(cd "$LOCAL_REPO" && pwd)"
if sudo test -L /root/packages && [ "$(sudo readlink /root/packages)" = "$LOCAL_REPO_LINK" ]; then
    echo "  /root/packages symlink already in place."
    HOST_REPO_SYMLINK=1
elif sudo test -e /root/packages || sudo test -L /root/packages; then
    echo "  WARNING: /root/packages exists but is not our symlink — leaving as is."
else
    echo "  Exposing local repo at host /root/packages..."
    sudo ln -sfn "$LOCAL_REPO_LINK" /root/packages
    HOST_REPO_SYMLINK=1
fi

# profiledef.sh elige arch, bootmodes, compresión y pacman.<arch>.conf a partir
# de CHURROS_ARCH. sudo limpia el entorno: la variable se pasa con env.
# En aarch64 el preset x86 (vmlinuz-linux) y los hooks memdisk/pxe no sirven.
# Hay que cambiarlos antes de que mkarchiso copie airootfs y pacstrap lance
# mkinitcpio. El trap los devuelve al terminar.
# archiso además lista módulos GRUB que ALARM no tiene en arm64-efi. El
# parche deja solo los .mod que existen; si el array desaparece, falla.
if [ "$TARGET_ARCH" = aarch64 ]; then
    bash scripts/apply-aarch64-mkinitcpio.sh apply
    sudo bash scripts/patch-mkarchiso-grubmodules.sh /usr/bin/mkarchiso
fi
sudo env CHURROS_ARCH="$TARGET_ARCH" mkarchiso -v \
    -w work \
    -o out \
    archiso

sudo chown -R "$USER:$USER" work out 2>/dev/null || true

echo "[6/6] Cleaning build artifacts..."

unmount_work_submounts work
if mountpoint -q work 2>/dev/null; then
    sudo find work -mindepth 1 -delete 2>/dev/null || sudo rm -rf work/* 2>/dev/null || true
else
    sudo rm -rf --one-file-system work 2>/dev/null || true
fi

echo
echo "======================================"
echo " Build completed!"
echo "======================================"

find out -name "*.iso"
