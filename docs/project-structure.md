# Estructura del proyecto

Mapa de carpetas y ficheros del repositorio. Cómo encajan las piezas se explica en [Arquitectura](../ARCHITECTURE.md); varias carpetas tienen además su propio README con más detalle.

## Raíz

```text
ChurrOS/
├── .github/                 # CI (workflows/), plantillas de issues, discusiones y PR
├── archiso/                 # Perfil de ArchISO (ver archiso/README.md)
├── branding/                # Identidad visual y script de personalización del Live
├── docs/                    # Documentación (índice en docs/README.md)
├── installer/               # Configuración y parches de Calamares
├── po/                      # Catálogos gettext heredados
├── rust/                    # Workspace Cargo de las apps propias
├── scripts/                 # CLI, scripts de build y pruebas (ver scripts/README.md)
├── churros                  # Dispatcher de la CLI: ./churros <comando>
├── Containerfile            # Imagen Arch para ./churros build --container y ./churros rust
├── Containerfile.aarch64    # Imagen Arch Linux ARM para la ISO aarch64
├── install-deps.sh          # Instala dependencias de desarrollo (pacman, apt o dnf)
├── VERSION                  # Versión de la distro
├── LICENSE                  # GPL-3.0
├── LICENSES/                # Textos de las demás licencias (ver docs/licencias.md)
├── README.md
├── ARCHITECTURE.md
├── AGENTS.md                # Guía para agentes de IA (build, convenciones, rutas protegidas)
├── CODE_OF_CONDUCT.md
├── SECURITY.md
├── MAINTAINERS              # Quién responde por cada área
├── .gitignore
└── .clang-format, .clangd   # Configuración para C++; el repositorio no tiene código C/C++
```

Se generan y no se versionan: `out/` (ISO), `work/` (temporal de ArchISO), `vm/` (discos y variables UEFI de QEMU), `release/` (bundles OTA e ISO preparadas para publicar), `rust/target/`, los paquetes y bases de datos de `archiso/packages/` y `vm_serial.log`.

## archiso/

Perfil de ArchISO. Detalle en [archiso/README.md](../archiso/README.md).

```text
archiso/
├── profiledef.sh            # Metadatos, arquitectura (CHURROS_ARCH), modos de arranque, compresión y permisos
├── packages.x86_64          # Edición niri en x86_64
├── packages.aarch64         # Edición niri en aarch64
├── packages.i686            # Edición niri en i686 (Arch Linux 32)
├── packages.xfce.x86_64     # Edición xfce
├── packages.server.x86_64   # Edición server
├── packages.pi.aarch64      # Edición pi
├── pacman.x86_64.conf       # Repositorios del bootstrap (Arch Linux) + [churros]
├── pacman.aarch64.conf      # Arch Linux ARM + [churros]
├── pacman.i686.conf         # Arch Linux 32 + [churros]
├── pacman-build.conf        # Sin uso: ningún script lo lee
├── pacman-local.conf        # Sin uso: ningún script lo lee
├── bootstrap_packages       # Solo para el modo bootstrap de archiso; el perfil construye únicamente la ISO
├── grub/                    # Menú GRUB de la ISO (UEFI)
├── syslinux/                # Menú Syslinux de la ISO (BIOS; x86_64 e i686)
├── efiboot/                 # Entradas de systemd-boot del perfil releng; sin uso con uefi.grub
├── mkinitcpio/aarch64/      # Preset y hooks de mkinitcpio para el kernel de Arch Linux ARM
├── packages/                # Repositorio local [churros] (generado; aarch64/ para ARM)
└── airootfs/                # Sistema de archivos del Live
```

Arranque de la ISO según la arquitectura: Syslinux (BIOS) + GRUB (UEFI) en x86_64 e i686, solo GRUB (UEFI) en aarch64.

`packages/` lo llenan los scripts `build-*.sh` (en el host o en el contenedor) con calamares, bazaar, yay, wlogout y python-pywal, y en aarch64 también libdex.

## rust/

Workspace Cargo de las apps propias. Detalle en [rust/README.md](../rust/README.md) y [Apps](apps.md).

| Crate | Binario | `deploy` | GTK |
|-------|---------|----------|-----|
| `churros-welcome` | `churros-welcome` | sí | gtk4 |
| `preferences` | `churros-settings` | sí | gtk4 + libadwaita |
| `control-center` | `churros-control-center` | sí | gtk4 |
| `popups` | `churros-popup` | sí | gtk4 |
| `churros-tour` | `churros-tour` | sí | gtk4 |
| `services` | librería `churros_services` | no (la usan las demás) | — |

`scripts/build-rust.sh` copia los binarios con `deploy = true` a `archiso/airootfs/usr/bin/` durante el build; no se versionan. Los recursos de cada app se editan en `rust/<crate>/assets/` y el build los copia a `archiso/airootfs/usr/share/churros/<binario>/assets/`. La hoja de estilos común es `archiso/airootfs/usr/share/churros/styles/churros.css`.

Dos copias versionadas en `archiso/airootfs/usr/share/churros/` no son la fuente: `control-center/` es antigua y el código ya no la lee (busca `churros-control-center/`), y `churros-tour/` la sobrescribe el build desde `rust/churros-tour/assets/`.

## branding/

```text
branding/
├── customize_airootfs.sh    # mkarchiso lo ejecuta en el chroot durante el build
├── stamp-os-release.sh      # Escribe VERSION y la edición en os-release
├── files/                   # os-release, issue, motd
├── grub-theme/              # Tema GRUB (ISO y sistema instalado)
├── README.md
├── colors.md
├── typography.md
├── logo-guidelines.md
├── mascot.md
└── ui-guidelines.md
```

`customize_airootfs.sh` no se ejecuta al arrancar el Live: el build lo copia a `archiso/airootfs/root/` y mkarchiso lo ejecuta dentro del chroot, después de pacstrap. Editar esa copia no sirve. archiso marca esta forma de personalizar como obsoleta.

Los fondos y demás recursos del escritorio están en `archiso/airootfs/usr/share/churros/`, no en `branding/`. Detalle en [Branding](branding.md).

## installer/

Configuración de Calamares. Detalle en [installer/README.md](../installer/README.md) e [Installer](installer.md).

```text
installer/
├── apply-calamares.sh       # Copia la configuración y la regla polkit al airootfs durante el build
├── patches/                 # calamares-*.patch, aplicados por scripts/build-calamares.sh
└── calamares/
    ├── settings.conf        # Instancias y secuencia de módulos
    ├── modules/             # Un .conf por módulo; aarch64/ e i686/ sobrescriben algunos por arquitectura
    ├── branding/churros/    # Slideshow, QSS y logo
    └── preview/             # Solo para ./churros apps calamares; no va a la ISO
```

## po/

`churros.pot`, `en.po` y `es.po`: catálogos gettext de la antigua interfaz en Python. Ninguna app actual los carga (las apps Rust llevan sus textos en el código). `./churros check` los valida con `msgfmt --check` y `scripts/build-i18n.sh` regenera a mano los `.mo` versionados en `archiso/airootfs/usr/share/locale/`.

## scripts/

Scripts de desarrollo; no forman parte del sistema instalado. Detalle en [scripts/README.md](../scripts/README.md).

- `cli/`: un script por subcomando de `./churros` (`build`, `run`, `check`, `rust`, `apps`, `doctor`, `clean`, `info`, `version`, `logo`).
- `build-*.sh`: paquetes locales (Calamares, AUR, Bazaar), apps Rust, tema GRUB, catálogos `.mo` y bundle OTA.
- `lib/`: funciones compartidas (contenedor, detección del host, repositorio local, firmware OVMF).
- `container-entrypoint.sh`, `apply-aarch64-mkinitcpio.sh` y `patch-mkarchiso-grubmodules.sh`: apoyo al build en contenedor y en aarch64.
- `host/grub-mkstandalone`: envoltorio de un build ARM anterior hecho en el host (busca los módulos en `/opt/grub-aarch64`). Ningún script lo usa hoy.
- `test-*`: pruebas (reglas polkit, helpers privilegiados, pkexec real, tour, servicios de red, fondo de pantalla).

## docs/

Documentación del proyecto, en español. El índice es [docs/README.md](README.md); `docs/archivo/` guarda documentos que ya no describen el estado actual.

## Ficheros de la raíz

- `churros`: CLI de desarrollo. Despacha a `scripts/cli/<comando>.sh`.
- `VERSION`: versión de la distro. La leen `./churros version`, `./churros info`, el build (os-release), `build-churros-release.sh` y las apps Rust al compilar (`churros-services`). Al publicar hay que cambiarla también en otros ficheros (ver [Release](release.md)).
- `LICENSE`: GPL-3.0. Los crates declaran `GPL-3.0-only` en `rust/Cargo.toml`. Licencias de terceros y del arte: [Licencias](licencias.md).

## Flujo de trabajo

Cada cambio va en una rama y llega a `main` por pull request:

```text
cambio -> ./churros check -> ./churros build -> ./churros run -> commit en una rama -> pull request
```

Detalle en [Contributing](contributing.md).
