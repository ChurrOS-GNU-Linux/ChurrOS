# Containerfile — entorno de build de ChurrOS.
#
# Es el mismo entorno que un Arch Linux con las dependencias del proyecto:
# mkarchiso, makepkg (AUR), las apps GTK en Rust y los tests de Node/Python.
# Sirve para construir desde cualquier distro y es el que usa el CI.
#
# No hace falta construirla a mano: la construyen y la usan
#   ./churros build --container   (ISO; el contenedor corre con --privileged)
#   ./churros rust                (compila y prueba rust/, igual que el CI)
# y se reconstruye sola cuando cambia este archivo o tiene más de 7 días.
#
# La imagen no copia nada del repo: el repo se monta en /churros al ejecutar
# y scripts/container-entrypoint.sh crea ahí un usuario con el UID del host.

# Imagen oficial, solo x86_64. En un host ARM, exporta CHURROS_CONTAINER_BASE
# con una imagen de Arch Linux ARM (el CI usa docker.io/menci/archlinuxarm).
ARG BASE_IMAGE=docker.io/library/archlinux:latest
FROM ${BASE_IMAGE}

# pacman no puede aplicar su sandbox de Landlock dentro del contenedor y no
# sincroniza ni descarga nada. La imagen oficial de Arch ya trae
# DisableSandboxFilesystem; la de Arch Linux ARM no.
RUN grep -q '^DisableSandboxFilesystem' /etc/pacman.conf \
    || sed -i '/^\[options\]/a DisableSandboxFilesystem' /etc/pacman.conf

# Primero el keyring (archlinux-keyring, o el de ARM): con una imagen base
# vieja, -Syu falla por firmas de empaquetadores nuevos.
#
# Arch Linux ARM no empaqueta archiso: sobre esa base la imagen sirve para
# ./churros rust, pero no para ./churros build. La ISO aarch64 usa
# Containerfile.aarch64 (archiso instalado desde extra de Arch, arch=any).
RUN pacman-key --init \
    && pacman-key --populate \
    && pacman -Sy --noconfirm --needed $(pacman -Qq | grep -- '-keyring$') \
    && pacman -Su --noconfirm \
    && if pacman -Si archiso >/dev/null 2>&1; then pacman -S --noconfirm --needed archiso; fi \
    && pacman -S --noconfirm --needed \
        base-devel \
        git \
        grub \
        gtk4 \
        libadwaita \
        rust \
        lld \
        nodejs \
        python \
    && pacman -Scc --noconfirm

# makepkg no corre como root y build.sh llama a sudo (mkarchiso, pacman):
# el usuario del build necesita sudo sin contraseña. Es un contenedor
# desechable, no un sistema.
RUN printf '%s\n' 'ALL ALL=(ALL:ALL) NOPASSWD: ALL' > /etc/sudoers.d/churros-builder \
    && chmod 0440 /etc/sudoers.d/churros-builder

WORKDIR /churros
