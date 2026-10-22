# ArchISO Profile — ChurrOS

Este directorio contiene la definición completa del perfil de **ArchISO** utilizado para construir la imagen ISO Live de ChurrOS mediante `mkarchiso`.

---

## Estructura del directorio

```text
archiso/
├── profiledef.sh              # Metadatos de la ISO, arquitectura, modos de arranque, compresión y mapa de permisos
├── packages.x86_64            # Paquetes de la ISO x86_64 (edición Niri)
├── packages.xfce.x86_64       # Edición XFCE (x86_64)
├── packages.server.x86_64     # Edición servidor (x86_64)
├── packages.aarch64           # Paquetes de la ISO ARM64 (edición Niri)
├── packages.pi.aarch64        # Edición Raspberry Pi (ARM64)
├── packages.i686              # Paquetes de la ISO i686 (Arch Linux 32)
├── pacman.x86_64.conf         # Repositorios pacman del bootstrap x86_64 (Arch Linux) + [churros]
├── pacman.aarch64.conf        # Repositorios pacman del bootstrap ARM64 (Arch Linux ARM) + [churros]
├── pacman.i686.conf           # Repositorios pacman del bootstrap i686 (Arch Linux 32) + [churros]
├── pacman-build.conf          # Sin uso: ningún script lo lee
├── pacman-local.conf          # Sin uso: ningún script lo lee
├── bootstrap_packages         # Solo para el modo bootstrap de archiso; el perfil construye únicamente la ISO
├── packages/                  # Repositorio pacman local [churros] (generado; packages/aarch64/ para ARM64)
├── efiboot/                   # Entradas de systemd-boot del perfil releng; sin uso con uefi.grub
├── grub/                      # Menú de arranque GRUB (UEFI)
├── syslinux/                  # Menú de arranque Syslinux (BIOS; x86_64 e i686)
├── mkinitcpio/aarch64/        # Preset y hooks de mkinitcpio para el kernel de Arch Linux ARM
└── airootfs/                  # Overlay del sistema de archivos raíz (SquashFS)
    ├── etc/                   # Configuración global, systemd, greetd, polkit y skel del usuario
    ├── root/                  # Scripts que ejecuta customize_airootfs.sh durante el build
    └── usr/                   # Scripts de ChurrOS, assets, fondos y temas
```

---

## Archivos clave

### `profiledef.sh`
Define los metadatos de la distribución:
- Nombre de la imagen (`iso_name="ChurrOS"`). mkarchiso nombra la ISO `ChurrOS-<AAAA.MM.DD>-<arch>.iso`.
- Arquitectura (`CHURROS_ARCH`, que pasa `build.sh`; por defecto la del equipo), con su `pacman.<arch>.conf` y su compresión del squashfs (zstd en x86_64 e i686, xz en ARM64).
- Modos de arranque: `bios.syslinux` y `uefi.grub` en x86_64 e i686; solo `uefi.grub` en ARM64.
- Mapa explícito de permisos y propietarios de archivos (`file_permissions`), asegurando que scripts y binarios en `/usr/bin/` y `/usr/local/bin/` tengan permisos de ejecución `0755`.

### `packages.<arch>` y `packages.<edición>.<arch>`
Lista declarativa de los paquetes instalados en la imagen squashfs (un paquete por línea). `packages.<arch>` es la edición Niri; para otra edición, `./churros build --edition` copia `packages.<edición>.<arch>` encima durante el build y luego la restaura. `./churros check` busca duplicados. La lista i686 se limita a lo que empaqueta Arch Linux 32.

### `packages/` (repositorio local `[churros]`)
Almacena los paquetes que se compilan en local: `calamares`, `bazaar`, `yay`, `wlogout`, `python-pywal` y, en ARM64, `libdex`. Lo llenan los scripts `scripts/build-*.sh`, que mantienen la base de datos con `repo-add`. Cada `pacman.<arch>.conf` lo declara con `Server = file:///root/packages`, antes que `core` y `extra`; durante el build, `build.sh` crea el enlace `/root/packages` para que pacstrap lo encuentre.

### `airootfs/`
Contiene la estructura de archivos que se fusiona con el sistema raíz de la ISO:
- **`etc/skel/.config/`**: configuración inicial del usuario: Niri, Noctalia, foot, Fuzzel, Waybar, Mako, wlogout, XFCE, picom, GTK, fastfetch, autostart y el timer de usuario `churros-update.timer`.
- **`root/scripts/`**: `users.sh`, `services.sh`, `desktop.sh` y `cleanup.sh`. Los ejecuta `customize_airootfs.sh` dentro del chroot durante el build, no al arrancar el Live.
- **`usr/share/churros/`**: estilos CSS, fondos de pantalla, configuraciones por defecto y scripts del sistema.

---

## Compilación

Para construir la imagen ISO utilizando este perfil:

```bash
./churros build
```

---

## Documentación relacionada

- [Sistema de compilación](../docs/build-system.md)
- [Configuración del escritorio](../docs/desktop-config.md)
- [Servicios del Live](../docs/live-services.md)
- [Sistema de arranque](../docs/boot.md)
