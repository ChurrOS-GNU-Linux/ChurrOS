#!/usr/bin/env bash
# shellcheck disable=SC2034

export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"

iso_name="ChurrOS"
iso_label="ChurrOS_$(date --date="@${SOURCE_DATE_EPOCH}" +%Y%m)"
iso_publisher="Hoyuse"
iso_application="ChurrOS Installer"
iso_version="$(date --date="@${SOURCE_DATE_EPOCH}" +%Y.%m.%d)"
install_dir="churros"
buildmodes=('iso')

# Arquitectura de la ISO. scripts/cli/build.sh la pasa con
# `sudo env CHURROS_ARCH=<arch> mkarchiso ...` (sudo limpia el entorno: un
# export no llega). Sin ella, la del equipo, como haría mkarchiso.
# mkarchiso lee packages.${arch} y nombra la ISO con ${arch}.
arch="${CHURROS_ARCH:-$(uname -m)}"
case "$arch" in
  x86_64)
    bootmodes=('bios.syslinux'
               'uefi.grub')
    # -Xbcj es solo de xz: mksquashfs falla si se combina con zstd.
    airootfs_image_tool_options=('-comp' 'zstd' '-b' '1M')
    ;;
  aarch64)
    # Sin BIOS en ARM: syslinux es solo x86. Tampoco uefi.systemd-boot:
    # los dos modos UEFI escriben EFI/BOOT/BOOTAA64.EFI y se pisan.
    bootmodes=('uefi.grub')
    # xz con filtro BCJ, como lo dejó el port ARM.
    airootfs_image_tool_options=('-comp' 'xz' '-Xbcj' 'arm' '-b' '1M' '-Xdict-size' '1M')
    ;;
  i686)
    # i686 es x86, así que conserva BIOS (syslinux). El arranque UEFI lo cubre
    # IA32 (grub i386-efi); lo aporta el mkarchiso de Arch Linux 32.
    bootmodes=('bios.syslinux'
               'uefi.grub')
    airootfs_image_tool_options=('-comp' 'zstd' '-b' '1M')
    ;;
  *)
    printf 'profiledef.sh: arquitectura no soportada: %s (x86_64, aarch64 o i686)\n' "$arch" >&2
    exit 1
    ;;
esac
# Repos de cada arquitectura: Arch Linux (mirrorlist del host), Arch Linux ARM
# o Arch Linux 32 (i686).
pacman_conf="pacman.${arch}.conf"
airootfs_image_type="squashfs"
bootstrap_tarball_compression=('zstd' '-c' '-T0' '--auto-threads=logical' '--long' '-19')
file_permissions=(
  ["/etc/shadow"]="0:0:400"
  ["/root"]="0:0:750"
  # .zlogin lo ejecuta. Sin 0755 zsh dice "permission denied".
  ["/root/.automated_script.sh"]="0:0:755"

  ["/usr/bin/churros-welcome"]="0:0:755"
  ["/usr/bin/churros-niri-session"]="0:0:755"
  ["/usr/bin/churros-xfce-session"]="0:0:755"
  ["/usr/bin/churros-tour"]="0:0:755"

  ["/usr/bin/churros-popup"]="0:0:755"

  ["/usr/local/bin/choose-mirror"]="0:0:755"
  ["/usr/local/bin/churros-theme"]="0:0:755"
  ["/usr/local/bin/calamares"]="0:0:755"
  ["/usr/local/bin/churros-xsession"]="0:0:755"
  ["/usr/local/bin/churros-update-auto"]="0:0:755"
  ["/usr/local/bin/churros-snapshot"]="0:0:755"
  ["/usr/local/bin/churros-write-root-config"]="0:0:755"
  ["/usr/local/bin/systemsettings"]="0:0:755"
  ["/usr/local/bin/discover"]="0:0:755"
  ["/usr/local/bin/plasma-discover"]="0:0:755"
  ["/usr/bin/churros-update-utils"]="0:0:755"
  ["/usr/bin/churros-settings"]="0:0:755"
  ["/usr/bin/churros-control-center"]="0:0:755"
  ["/usr/bin/churros-pick-image"]="0:0:755"
  ["/usr/bin/churros-pkexec"]="0:0:755"
  ["/usr/bin/churros-portal-start"]="0:0:755"
  ["/usr/bin/churros-apply-wallpaper"]="0:0:755"
  ["/usr/bin/churros-pi-session"]="0:0:755"
  ["/usr/share/churros/scripts/make-boot-grub-readable"]="0:0:755"
  ["/usr/share/churros/scripts/publish-aarch64-kernel"]="0:0:755"
  ["/usr/share/churros/scripts/configure-greeter-locale"]="0:0:755"
  ["/usr/share/churros/scripts/configure-greetd-session"]="0:0:755"
  ["/usr/share/churros/scripts/configure-server"]="0:0:755"
  ["/usr/share/churros/scripts/configure-kde-panel"]="0:0:755"
  ["/usr/share/churros/scripts/verify-install"]="0:0:755"
  ["/usr/share/churros/scripts/fix-xfce-sessions"]="0:0:755"
  ["/usr/share/icons/hicolor/scalable/apps/churros-welcome.svg"]="0:0:644"
  ["/usr/share/icons/hicolor/scalable/apps/churros-settings.svg"]="0:0:644"
  ["/usr/share/icons/hicolor/scalable/apps/churros-logo.svg"]="0:0:644"
  ["/usr/share/icons/hicolor/128x128/apps/churros-welcome.png"]="0:0:644"
  ["/usr/share/icons/hicolor/128x128/apps/churros-settings.png"]="0:0:644"
  ["/usr/share/icons/hicolor/128x128/apps/churros-logo.png"]="0:0:644"
  ["/usr/share/pixmaps/churros-logo.svg"]="0:0:644"
  ["/usr/share/pixmaps/churros-logo.png"]="0:0:644"
)
