# ArchISO Profile — ChurrOS

Este directorio contiene la definición completa del perfil de **ArchISO** utilizado para construir la imagen ISO Live de ChurrOS mediante `mkarchiso`.

---

## 📁 Estructura del Directorio

```text
archiso/
├── profiledef.sh              # Metadatos de la ISO, arquitectura, modos de arranque y mapa de permisos
├── packages.x86_64            # Paquetes de la ISO x86_64 (edición Niri; las demás ediciones tienen packages.<edición>.x86_64)
├── packages.aarch64           # Paquetes de la ISO ARM64
├── packages.i686              # Paquetes de la ISO i686 (Arch Linux 32)
├── pacman.x86_64.conf         # Repositorios pacman del bootstrap x86_64 (Arch Linux)
├── pacman.aarch64.conf        # Repositorios pacman del bootstrap ARM64 (Arch Linux ARM)
├── pacman.i686.conf           # Repositorios pacman del bootstrap i686 (Arch Linux 32)
├── pacman-build.conf          # Configuración extendida para incluir repositorios locales
├── packages/                  # Repositorio pacman local [churros] con paquetes AUR precompilados
├── efiboot/                   # Configuración del cargador UEFI
├── grub/                      # Menú de arranque GRUB para UEFI
├── syslinux/                  # Menú de arranque Syslinux para BIOS
└── airootfs/                  # Overlay del sistema de archivos raíz (SquashFS)
    ├── etc/                   # Configuraciones globales, systemd, skel del usuario
    ├── root/                  # Scripts de inicialización del Live
    └── usr/                   # Binarios de ChurrOS, scripts del sistema, assets y temas
```

---

## 📋 Archivos Clave

### `profiledef.sh`
Define los metadatos de la distribución:
- Nombre de la imagen (`iso_name="ChurrOS"`).
- Arquitectura (`CHURROS_ARCH`, que pasa `build.sh`; por defecto la del equipo), con su `pacman.<arch>.conf` y su compresión del squashfs.
- Modos de arranque: `bios.syslinux` y `uefi.grub` en x86_64 e i686; solo `uefi.grub` en ARM64.
- Mapa explícito de permisos y propietarios de archivos (`file_permissions`), asegurando que scripts y binarios en `/usr/bin/` y `/usr/local/bin/` tengan permisos de ejecución `0755`.

### `packages.x86_64`, `packages.aarch64` y `packages.i686`
Lista declarativa de todos los paquetes instalados en la imagen squashfs (un paquete por línea). Se valida automáticamente mediante `./churros check` para evitar duplicados. La lista i686 se apoya en el proyecto Arch Linux 32.

### `packages/` (Repositorio local `[churros]`)
Almacena paquetes generados en local durante el proceso de compilación (`calamares`, `yay`, `wlogout`, `python-pywal`). `scripts/cli/build.sh` ejecuta `repo-add` sobre este directorio para que `mkarchiso` pueda resolver dependencias offline.

### `airootfs/`
Contiene la estructura de archivos que se fusiona con el sistema raíz de la ISO:
- **`etc/skel/.config/`**: Configuraciones de inicio del usuario para **Niri**, **Waybar**, **foot**, **Fuzzel** y **Mako**.
- **`root/scripts/`**: Scripts de aprovisionamiento del Live (`users.sh`, `services.sh`, `desktop.sh`, `cleanup.sh`, `greetd-config.sh`).
- **`usr/share/churros/`**: Assets gráficos, estilos CSS y fondos de pantalla oficiales.

---

## 🔨 Compilación

Para construir la imagen ISO utilizando este perfil:

```bash
./churros build
```

---

## 📖 Documentación Relacionada

- [Documentación del Sistema de Compilación](../docs/build-system.md)
- [Configuración del Escritorio](../docs/desktop-config.md)
- [Servicios del Live](../docs/live-services.md)
- [Sistema de Arranque](../docs/boot.md)
