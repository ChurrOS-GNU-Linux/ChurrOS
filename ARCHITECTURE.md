# Arquitectura de ChurrOS

Visión general de cómo encajan las piezas de ChurrOS: el build de la ISO, el sistema Live, la instalación, las apps propias y las actualizaciones. Cada sección enlaza al documento con el detalle. Los principios con los que se decide qué entra en el proyecto están en [docs/principios.md](docs/principios.md); el mapa completo de carpetas, en [docs/project-structure.md](docs/project-structure.md).

## Repositorio

| Ruta | Contenido |
|------|-----------|
| `churros`, `scripts/` | CLI de desarrollo (`./churros`, subcomandos en `scripts/cli/`), scripts de build, utilidades compartidas (`scripts/lib/`) y pruebas. |
| `Containerfile`, `Containerfile.aarch64` | Entornos Arch para construir desde cualquier distro y para la CI. |
| `archiso/` | Perfil de ArchISO: listas de paquetes por edición y arquitectura, `pacman.<arch>.conf`, cargadores de la ISO y `airootfs/` (el sistema de archivos del Live). |
| `branding/` | `os-release`, issue, motd, tema GRUB, `customize_airootfs.sh` y las guías de identidad visual (colores, tipografía, logo, mascota, interfaz). |
| `installer/` | Configuración de Calamares y parches que se aplican al compilarlo. |
| `rust/` | Apps propias en Rust (gtk4-rs; `churros-settings` además usa libadwaita) y la librería `churros_services`. |
| `po/` | Catálogos gettext heredados de la antigua interfaz en Python; ningún componente los usa hoy. |
| `docs/` | Documentación ([índice](docs/README.md)). |

## Ediciones y arquitecturas

| Edición | Arquitecturas | Escritorio |
|---------|---------------|------------|
| `niri` (por defecto) | x86_64, aarch64, i686 | Niri + Noctalia. En i686 no hay escritorio: Arch Linux 32 no empaqueta niri ni noctalia. |
| `xfce` | x86_64 | XFCE |
| `server` | x86_64 | Ninguno en el sistema instalado. El Live lleva XFCE solo para ejecutar el instalador. |
| `pi` | aarch64 | labwc + Waybar |

Todas parten del mismo perfil de ArchISO; `./churros build --edition` cambia la lista de paquetes y la sesión del Live. Los repositorios base son Arch Linux (x86_64), Arch Linux ARM (aarch64) y Arch Linux 32 (i686). La ISO i686 tampoco lleva instalador ni Bazaar.

### Stack de la edición Niri

| Pieza | Implementación |
|-------|----------------|
| Compositor | Niri |
| Shell (barra, lanzador, notificaciones, OSD) | Noctalia v5 (paquete `noctalia` de [extra]) |
| Alternativas instaladas | Fuzzel (lanzador, `Mod+Shift+Space`), Waybar (panel), Mako (notificaciones) |
| Menú de sesión | wlogout (`Mod+Shift+E`) |
| Tienda | Bazaar (`Mod+S`) |
| Archivos | Thunar (`Mod+E`) |
| Display manager | greetd con ReGreet dentro de cage; autologin en el Live |
| Terminal | foot |
| Audio | PipeWire + WirePlumber |
| Instalador | Calamares (x86_64 y aarch64) |
| Arranque de la ISO | x86_64 e i686: Syslinux (BIOS) + GRUB (UEFI); aarch64: GRUB (UEFI) |

Detalle de cada edición: [docs/desktop-config.md](docs/desktop-config.md) y [docs/server.md](docs/server.md).

## Build

```text
./churros build [--edition] [--arch] [--container]
   ├─ paquetes locales: Calamares, Bazaar, yay, wlogout, python-pywal -> repositorio [churros]
   ├─ apps Rust (build-rust.sh) -> archiso/airootfs/usr/bin/
   └─ mkarchiso: pacstrap + airootfs + customize_airootfs.sh -> out/ChurrOS-<fecha>-<arch>.iso
```

Los paquetes que no están en los repositorios oficiales (o que se recompilan con parches) forman el repositorio local `[churros]`, en `archiso/packages/`. Cada `pacman.<arch>.conf` lo declara con prioridad sobre `core` y `extra`. En hosts que no son Arch, `--container` ejecuta el build completo en una imagen Arch. Detalle: [docs/build-system.md](docs/build-system.md).

## Sistema Live

mkarchiso ejecuta `customize_airootfs.sh` dentro del chroot durante el build: aplica `os-release`, crea el usuario `churros` (sudo sin contraseña), activa servicios, configura el escritorio e instala Calamares desde el repositorio local. Al arrancar la ISO, greetd entra directamente en la sesión de la edición. Detalle: [docs/live-services.md](docs/live-services.md) y [docs/boot.md](docs/boot.md).

## Instalación

Calamares copia el squashfs del Live al disco (Btrfs por defecto), configura el sistema e instala GRUB. Sus pasos propios (`shellprocess`) desactivan la compresión en `/boot` para GRUB, inicializan el keyring de pacman, adaptan mkinitcpio al sistema instalado, aplican el tema GRUB y, al final, quitan lo que solo sirve en el Live (el repositorio `[churros]`, el usuario `churros`, Calamares y sus reglas polkit). En el primer inicio del sistema instalado (ediciones Niri y XFCE), [ChurrOS Tour](docs/churros-tour.md) ofrece instalar aplicaciones por categorías. Detalle: [docs/installer.md](docs/installer.md).

## Apps propias

Cinco binarios en Rust: `churros-welcome`, `churros-settings`, `churros-control-center`, `churros-popup` y `churros-tour`. Los crates con `deploy = true` se instalan en `/usr/bin/` y sus recursos en `/usr/share/churros/<binario>/`. La librería `churros-services` reúne las llamadas a las herramientas del sistema (wpctl, nmcli, bluetoothctl, brightnessctl…). Detalle: [docs/apps.md](docs/apps.md).

## Actualizaciones y rollback

- Paquetes del sistema: pacman contra los repositorios de Arch.
- Apps y scripts de ChurrOS: `churros-update-utils` descarga un bundle (`churros-utils-<versión>-<arch>.tar.zst`) de download.churroslinux.org y solo instala ficheros en rutas permitidas. Hoy solo hay bundle x86_64 y el manifiesto no va firmado (ver [docs/release.md](docs/release.md)).
- Snapshots: el hook de pacman `50-churros-snapshot.hook` crea un snapshot Btrfs antes de cada transacción. Detalle: [docs/rollback.md](docs/rollback.md).

## Ejecución privilegiada

Las apps corren como el usuario. Lo que necesita root pasa por `churros-pkexec`, y la regla polkit `50-churros-store.rules` solo autoriza programas concretos, por ruta absoluta y con argumentos exactos. Detalle: [docs/privileged-execution.md](docs/privileged-execution.md).
