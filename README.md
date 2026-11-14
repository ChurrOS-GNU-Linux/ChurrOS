<div align="center">
  <img src="archiso/airootfs/usr/share/pixmaps/churros-logo.svg" width="96" alt="ChurrOS">
  <h1>ChurrOS</h1>
  <p><strong>Distribución Linux basada en Arch Linux</strong>, construida con archiso, con escritorio Niri y herramientas propias en Rust.</p>
  <p>
    <a href="https://github.com/ChurrOS-GNU-Linux/ChurrOS/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/ChurrOS-GNU-Linux/ChurrOS/actions/workflows/ci.yml/badge.svg"></a>
    <a href="LICENSE"><img alt="Licencia" src="https://img.shields.io/badge/licencia-GPL--3.0-blue.svg"></a>
    <img alt="Base" src="https://img.shields.io/badge/base-Arch%20Linux-1793D1.svg">
    <img alt="Build" src="https://img.shields.io/badge/build-archiso-1793D1.svg">
    <img alt="Apps" src="https://img.shields.io/badge/apps-Rust-orange.svg">
    <img alt="Escritorios" src="https://img.shields.io/badge/escritorios-Niri%20%2F%20XFCE%20%2F%20Server-FFBC00.svg">
  </p>
</div>

---

## Qué es ChurrOS

ChurrOS es una distribución Linux basada en Arch Linux y construida mediante [archiso](https://archlinux.org/archiso/). Ofrece ediciones con escritorio Niri o XFCE y una edición para servidores, un instalador gráfico (Calamares), aplicaciones propias escritas en Rust, un actualizador y rollback con snapshots Btrfs.

Este repositorio contiene el perfil de la ISO, el overlay del sistema Live, la configuración del instalador, las utilidades de administración y el código de las aplicaciones propias.

---

## Características

| Característica | Estado |
|---|---|
| Base Arch Linux | ✅ |
| Perfil archiso personalizado | ✅ |
| CLI `./churros` | ✅ |
| Construcción automatizada de la ISO | ✅ |
| QEMU para pruebas | ✅ |
| Edición Niri | ✅ |
| Edición XFCE | ✅ |
| Edición Servidor (sin escritorio en instalado) | ✅ |
| Aplicaciones oficiales en Rust | ✅ |
| Calamares con branding propio | ✅ |
| Tema GRUB | ✅ |
| Actualizador de ChurrOS | ✅ |
| Rollback mediante snapshots Btrfs | ✅ |
| Repositorio de paquetes remoto y firmado | Pendiente; `[churros]` solo se usa durante el build |
| Wiki oficial | Pendiente |
| Guía de usuario | Guía inicial disponible ([guía de uso](docs/user-guide.md)); wiki y manual completo pendientes |

---

## Ediciones

| Edición | Arquitectura | Escritorio | Estado |
|---|---|---|---|
| Niri (por defecto) | x86_64 | Niri + Noctalia | ISO publicada (1.5) |
| XFCE | x86_64 | XFCE | ISO publicada (1.5) |
| Servidor | x86_64 | Ninguno en el sistema instalado | Se construye y prueba en nightly; no hay ISO publicada |
| Niri | aarch64 (UEFI) | Niri + Noctalia | CI diaria construye y audita; no publica ISO estable |
| Raspberry Pi Lite (`pi`) | aarch64 | labwc + Waybar | Experimental: sin build nightly ni ISO publicada |
| Port de 32 bits | i686 | Ninguno (Niri y Noctalia no existen en Arch Linux 32) | Experimental: sin sesión gráfica ni instalador gráfico |

### Niri

La edición predeterminada. Utiliza:

- Niri (Wayland con tiling scrollable)
- Noctalia (paquete `noctalia` de [extra]) como barra, lanzador, notificaciones y OSD
- wlogout como menú de sesión (`Mod+Shift+E`)
- Waybar, Fuzzel y Mako, instalados como alternativa
- foot
- Aplicaciones oficiales de ChurrOS

```bash
./churros build
```

### XFCE

Edición basada en XFCE, orientada a una experiencia de escritorio tradicional y ligera. Usa su propia lista de paquetes (`archiso/packages.xfce.x86_64`).

```bash
./churros build --edition xfce
```

### Servidor

Edición sin escritorio gráfico en el sistema instalado, accesible por SSH. La ISO lleva un XFCE mínimo porque el instalador (Calamares) es gráfico; `configure-server` lo quita al terminar la instalación y deja el arranque en `multi-user`.

```bash
./churros build --edition server
```

Es la más ligera de las ediciones x86_64. Habilita `sshd`, `chronyd`, NetworkManager y la actualización automática diaria de ChurrOS. El cortafuegos (`ufw`) y `fail2ban` vienen instalados, pero no filtran nada hasta que los configures. Las cifras medidas, cómo activarlos y las limitaciones están en [`docs/server.md`](docs/server.md).

### Otras arquitecturas

- **aarch64 (UEFI):** la edición Niri para ARM de 64 bits, con la lista `archiso/packages.aarch64`. Se construye dentro de un contenedor Arch Linux ARM (`./churros build --container --arch arm64`) o de forma nativa en un host aarch64. La CI diaria la construye y audita en runner ARM nativo; no prueba arranque ni instalación.
- **Raspberry Pi Lite (experimental):** edición `pi`, solo aarch64, con sesión labwc y Waybar (`archiso/packages.pi.aarch64`). Se construye con `./churros build --container --arch arm64 --edition pi`.
- **i686 (experimental):** port de 32 bits sobre [Arch Linux 32](https://archlinux32.org). Niri y Noctalia no existen allí, así que la ISO no tiene sesión gráfica, y no lleva Calamares porque falta `polkit-qt6`. Los paquetes locales (yay, wlogout, python-pywal) tienen que estar compilados para i686.

---

## Descarga

Las ISO publicadas se descargan de [download.churroslinux.org](https://download.churroslinux.org/). La última versión publicada es la **1.5** (9 de noviembre de 2026), para x86_64 en ediciones Niri y XFCE. El [directorio de descargas](https://download.churroslinux.org/) lista ambas ISO y `SHA256SUMS`. La [GitHub Release v1.5](https://github.com/ChurrOS-GNU-Linux/ChurrOS/releases/tag/v1.5) también adjunta el manifiesto, pero no las ISO. Las versiones 0.6, 0.7 y 1.0 también están en [SourceForge](https://sourceforge.net/projects/churr-os/files/).

El servidor publica SHA-256 para ambas ISO 1.5 en [`SHA256SUMS`](https://download.churroslinux.org/SHA256SUMS), y GitHub adjunta el mismo manifiesto a la [release v1.5](https://github.com/ChurrOS-GNU-Linux/ChurrOS/releases/tag/v1.5). Las sumas no están firmadas: sirven para detectar corrupción, no para autenticar el origen. Puedes comprobar los archivos así:

```bash
sha256sum -c SHA256SUMS
```

---

## Sistema de construcción

ChurrOS utiliza una cadena de construcción basada en archiso.

```text
                      Código fuente
                           │
                           ▼
                    ./churros build
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
       Branding      Paquetes         Apps Rust
    (tema GRUB,     (Calamares,      (gtk4-rs +
     scripts)        AUR, Bazaar)     libadwaita)
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                       mkarchiso
                           │
                           ▼
                     ISO de ChurrOS
```

`./churros build`:

1. **Comprueba las herramientas** — `mkarchiso`, `mksquashfs`, `xorriso`, `grub-mkstandalone`, `mkfs.fat` y mtools. Si faltan, dice cómo instalarlas o propone `--container`.
2. **Aplica la edición** — elige la lista de paquetes, escribe `/etc/churros-edition` y la sesión Live de greetd.
3. **Branding** — genera el tema de GRUB, copia `branding/` al airootfs y escribe la versión y la edición en `os-release`.
4. **Paquetes locales** — prepara los paquetes locales (Calamares, Bazaar, yay, wlogout, python-pywal) y, si hay Calamares, despliega la configuración del instalador y copia los paquetes a la ISO.
5. **Apps Rust** — compila las apps en release y despliega los binarios en `usr/bin/`.
6. **Limpieza** — borra `work/` y `out/`.
7. **ISO** — ejecuta `mkarchiso` y deja la imagen en `out/`.

Usa `sudo` para `mkarchiso`, para borrar `work/` y `out/` y para exponer temporalmente el repositorio local en `/root/packages` del host; `makepkg` lo usa también para instalar dependencias de compilación. El detalle está en [`docs/build-system.md`](docs/build-system.md).

---

## Inicio rápido

### Requisitos

En Arch Linux la ISO se construye en el host. En cualquier otra distro se construye dentro del contenedor Arch del proyecto con `./churros build --container` (podman o docker). La ISO aarch64 se construye en contenedor (`--container --arch arm64`), salvo en un host aarch64.

```bash
./install-deps.sh     # dependencias en Arch, Debian/Ubuntu o Fedora
./churros doctor      # comprueba el entorno y ofrece instalar lo que falte
```

`doctor` propone el comando de instalación con el gestor de la distro (pacman, apt-get o dnf). En Arch, el build en el host necesita además `base-devel`, porque `makepkg` compila Calamares y los extras de AUR; `install-deps.sh` no lo instala y `doctor` no lo comprueba. La tabla por distro y los detalles del contenedor están en [`docs/getting-started.md`](docs/getting-started.md).

### Clonar

```bash
git clone https://github.com/ChurrOS-GNU-Linux/ChurrOS.git
cd ChurrOS
```

Se trabaja mediante ramas y pull requests, no directamente sobre `main`.

### Construir

```bash
./churros build                                         # Niri, arquitectura del equipo
./churros build --edition xfce
./churros build --edition server
./churros build --container                             # en cualquier distro
./churros build --container --arch arm64                # Niri para aarch64 (UEFI)
./churros build --container --arch arm64 --edition pi   # Raspberry Pi Lite (experimental)
./churros build --arch i686                             # 32 bits (experimental)
```

### Probar en QEMU

```bash
./churros run
```

Si no existe una ISO de esa arquitectura, `./churros run` pregunta si construirla. La máquina virtual usa un disco QCOW2 de desarrollo de 64 GiB en `vm/`.

| Opción | Qué hace |
|---|---|
| `./churros run --nokvm` | Ejecuta QEMU sin aceleración KVM |
| `./churros run --fresh` | Regenera las variables UEFI de la máquina virtual |
| `./churros run --clean` | Elimina el disco virtual y las variables UEFI antes de iniciar |
| `./churros run --arch arm64\|i686` | Arranca la ISO de esa arquitectura |

### Limpiar

```bash
./churros clean
```

Elimina `work/`, `out/` y casi todo lo que el build genera en `archiso/airootfs/` (la lista exacta está en [`docs/cli.md`](docs/cli.md#clean)). No toca el código fuente.

---

## CLI de ChurrOS

```text
./churros <comando> [opciones]
```

| Comando | Qué hace |
|---|---|
| `build` | Construye la ISO (`--edition niri\|xfce\|server\|pi`, `--arch x86_64\|arm64\|i686`, `--container`) |
| `run` | Arranca la ISO en QEMU y ofrece construirla si no existe (`--nokvm`, `--fresh`, `--clean`, `--arch`) |
| `clean` | Elimina los artefactos de construcción |
| `check` | Ejecuta las comprobaciones estáticas del repositorio |
| `rust` | Compila, prueba y pasa clippy a `rust/` en el contenedor Arch (`--host` para hacerlo en local) |
| `doctor` | Diagnostica el entorno de desarrollo |
| `apps` | Abre las apps del repo en el host, sin ISO |
| `info` | Muestra información del proyecto |
| `version` | Muestra la versión de ChurrOS (fichero `VERSION`) |
| `logo` | Imprime el logo en ASCII |

```bash
./churros --help
```

La referencia completa está en [`docs/cli.md`](docs/cli.md).

---

## Aplicaciones oficiales

Las aplicaciones oficiales de ChurrOS están desarrolladas en Rust, utilizando GTK 4, libadwaita y gtk4-rs.

| Aplicación | Binario | Función |
|---|---|---|
| Welcome | `churros-welcome` | Pantalla de bienvenida |
| Settings | `churros-settings` | Configuración del sistema |
| Control Center | `churros-control-center` | Centro de control |
| Popups | `churros-popup` | Controles rápidos |
| Tour | `churros-tour` | Asistente de primer inicio |
| Services | `churros_services` | Biblioteca de servicios compartidos |

Los crates con `deploy = true` se compilan durante la construcción y se despliegan en `/usr/bin`. `churros_services` es una biblioteca: la usan las demás apps y no se despliega por separado.

### churros-welcome

Pantalla de bienvenida. Muestra CPU, RAM, kernel, sistema operativo, arquitectura y hostname, y ofrece accesos rápidos al instalador (solo en el Live), al repositorio de GitHub y a la comunidad de Discord.

### churros-settings

Aplicación principal de configuración, con GTK4 y libadwaita. En Niri se abre con `Mod+P`.

### churros-control-center

Centraliza red, Bluetooth, brillo, batería y audio. En Niri no tiene atajo (`Mod+C` abre el centro de control de Noctalia) y se abre desde el lanzador; en XFCE, con `Super+C`.

### churros-popup

Controles rápidos para red, audio, volumen, Bluetooth, batería, brillo y energía.

```bash
churros-popup audio
```

### churros-tour

Asistente del primer inicio del sistema instalado (Niri y XFCE): permite elegir aplicaciones e instalarlas con `yay`. No se ejecuta en el Live y la edición servidor no lo incluye. Ver [`docs/churros-tour.md`](docs/churros-tour.md).

---

## Paquetes y ecosistema

Durante la construcción, ChurrOS usa un repositorio local de paquetes, `[churros]` (`archiso/packages/`; `archiso/packages/aarch64/` para la ISO ARM). Contiene lo que se compila en local:

- Calamares (de AUR, con parches propios)
- yay, wlogout y python-pywal (de AUR)
- Bazaar (desde el PKGBUILD de Arch, para que enlace libdex ≥ 1.2)

El objetivo a largo plazo es disponer de un repositorio oficial de paquetes de ChurrOS.

Cada edición tiene su lista de paquetes en `archiso/`: `packages.x86_64` (Niri), `packages.xfce.x86_64`, `packages.server.x86_64`, `packages.aarch64` (Niri en ARM), `packages.pi.aarch64` y `packages.i686`. Hay un único perfil archiso: `./churros build` pone la lista de la edición en lugar de la de Niri. La lista i686 se limita a lo que empaqueta Arch Linux 32: faltan Niri, Noctalia, Bazaar (y webkitgtk-6.0/glycin) y `polkit-qt6` (necesario para Calamares). XFCE y servidor no tienen lista para i686.

---

## Instalador

ChurrOS utiliza Calamares como instalador gráfico, con branding propio y configuración específica del proyecto.

Soporta, entre otras funciones:

- Particionado automático.
- Particionado manual.
- Selección de idioma.
- Selección de zona horaria.
- Creación de usuarios.
- Instalación del bootloader (GRUB, tanto en UEFI como en BIOS).
- Configuración posterior a la instalación.

La secuencia de instalación está definida en `installer/calamares/settings.conf` e incluye pasos de shell propios: `/boot` sin copy-on-write en Btrfs, keyring de pacman, preset de mkinitcpio, tema de GRUB y limpieza del Live (incluida la retirada del repositorio `[churros]`). El detalle está en [`docs/installer.md`](docs/installer.md).

Sustituir Calamares por un instalador propio pasaría por la [regla para programas nuevos](docs/principios.md#regla-para-programas-nuevos); hoy no hay ninguna propuesta abierta.

---

## Identidad visual

ChurrOS mantiene sus recursos visuales dentro de una estructura organizada. Incluye:

- Logo oficial.
- Wallpapers.
- Fastfetch personalizado.
- Iconos de las apps propias (el tema de iconos es Papirus y el cursor, Adwaita).
- Tema GRUB.
- Configuración visual de las aplicaciones.
- Branding del instalador y del sistema Live.

La mascota está en diseño ([`branding/mascot.md`](branding/mascot.md)). Las guías están en [`docs/branding.md`](docs/branding.md) y en `branding/`; la autoría y la licencia de cada recurso, en [`docs/licencias.md`](docs/licencias.md).

---

## Actualizaciones y rollback

ChurrOS incluye herramientas para:

- Actualizaciones mediante pacman.
- Actualizaciones de Flatpak.
- Actualización de las utilidades propias de ChurrOS.
- Snapshots Btrfs y rollback mediante `churros-snapshot`.

`churros-snapshot` toma snapshots de los subvolúmenes `@` y `@home` antes de cada transacción de pacman (mediante un hook `PreTransaction`), y permite restaurarlos desde la ISO Live. Ver [`docs/rollback.md`](docs/rollback.md).

---

## Comprobaciones

```bash
./churros check
```

Valida, entre otras cosas:

- Sintaxis Bash, ShellCheck y sintaxis Python.
- Listas de paquetes y perfil archiso de cada arquitectura.
- Comandos que lanza Niri, su integración con Noctalia y los `Exec`/`TryExec` de las desktop entries.
- Orden de ejecución, configuración, branding y vista previa de Calamares.
- Arranque, Live y snapshots Btrfs.
- Ejecución privilegiada: regla polkit y helpers que corren como root.
- Que `po/*.po` compile (catálogo heredado; las apps Rust no usan gettext).
- Versión de la distribución.
- Enlaces de la documentación e índice de `docs/`.
- Higiene del repositorio.

Termina con código de salida distinto de cero cuando encuentra fallos. El detalle está en [`docs/cli.md`](docs/cli.md#check).

---

## Diagnóstico del entorno

```bash
./churros doctor
```

Comprueba git, QEMU (x86_64, i386 y aarch64), Python, Node, ShellCheck, gettext, zstd, Rust (y que `rustc` sea 1.85 o posterior) y el acceso a `/dev/kvm`. En Arch comprueba también las herramientas del build en el host (`mkarchiso`, xorriso, SquashFS, mtools, FAT, GRUB, `mkinitcpio`); fuera de Arch, que haya podman o docker para `--container`. Con `--arch arm64`, en un host que no es aarch64, exige además qemu-user aarch64 registrado con la bandera `C`.

---

## Integración continua

ChurrOS utiliza GitHub Actions con seis workflows:

| Workflow | Cuándo se ejecuta | Qué hace |
|---|---|---|
| `ci.yml` | Push a `main` y pull requests | `./churros test` y `./churros test --mutations` (checks estáticos, reglas polkit, helpers y contratos del repositorio) |
| `rust.yml` | Push a `main`, pull requests, semanal y manual | Build, tests, clippy, pruebas GTK en Broadway y validación de configuración en x86_64 y ARM64; mutaciones del contenedor fuera de PR |
| `polkit.yml` | Push a `main` y pull requests | Prueba la regla con `pkexec` y `polkitd` reales en un contenedor Arch |
| `iso.yml` | Diario en `main` y manual | Construye, audita y arranca ediciones x86_64 en QEMU; sube ISO, sumas e informes como artefactos temporales |
| `iso-arm64.yml` | Diario en `main` y manual | Construye y audita ISO aarch64 en runner ARM; no prueba instalación ni arranque |
| `visual-qa-classify.yml` | Pull requests | Clasifica cambios de interfaz; no es una prueba visual y no bloquea la fusión |

Los workflows de ISO no corren en cada PR ni sus artefactos temporales son releases firmadas. El job de instalación completa de Calamares sigue pendiente (#297). Revisa el workflow y los checks requeridos del repositorio antes de asumir que todos bloquean la fusión.

---

## Estructura del proyecto

```text
ChurrOS/
├── .github/               Workflows de CI y plantillas de issues y PR
├── archiso/               Perfil archiso: paquetes, overlay del Live, cargadores
├── branding/              Identidad visual; incluye customize_airootfs.sh, aún usado y pendiente de migrar
├── docs/                  Documentación
├── installer/             Configuración de Calamares y despliegue
├── po/                    Catálogo gettext heredado (las apps Rust no lo usan)
├── rust/                  Aplicaciones oficiales en Rust
├── scripts/               CLI de desarrollo y scripts de build
├── vm/                    Máquina virtual generada (no versionada)
├── out/                   ISO generada (no versionada)
├── work/                  Temporal de archiso (no versionada)
├── churros                CLI principal
├── Containerfile          Contenedor de build (x86_64)
├── Containerfile.aarch64  Contenedor de build de la ISO ARM
├── install-deps.sh        Instalador de dependencias de desarrollo
├── VERSION                Versión del proyecto
├── AGENTS.md              Resumen de convenciones para herramientas y agentes
├── ARCHITECTURE.md        Visión general de la arquitectura
├── CODE_OF_CONDUCT.md     Código de conducta
├── SECURITY.md            Política de seguridad
├── MAINTAINERS            Responsables por área
├── LICENSE                Licencia
└── LICENSES/              Textos de licencia de componentes de terceros
```

`out/`, `work/` y `vm/` contienen artefactos generados y no forman parte del código fuente. El detalle está en [`docs/project-structure.md`](docs/project-structure.md) y [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Documentación

El índice completo, ordenado según lo que vengas a hacer, está en [`docs/README.md`](docs/README.md). Para empezar:

- [Getting Started](docs/getting-started.md): preparar el entorno y generar la primera ISO.
- [CLI](docs/cli.md): referencia de `./churros`.
- [Contributing](docs/contributing.md): cómo contribuir, con o sin programar.
- [Guía de uso](docs/user-guide.md): probar, instalar, actualizar y recuperar el sistema.
- [Rollback](docs/rollback.md) y [Server](docs/server.md): detalle de recuperación y de la edición servidor.

---

## Roadmap

| Área | Estado |
|---|---|
| Instalación automatizada y primer arranque en QEMU | Pendiente ([#297](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/297)); la guía no sustituye esta prueba |
| Firma obligatoria del actualizador y repo remoto firmado | Pendientes ([#139](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/139), [#141](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/141)) |
| Criterios para la primera versión estable | Propuesta en discusión ([#298](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/298)); ninguna versión está declarada estable |
| Migración desde `customize_airootfs.sh` | Pendiente ([#299](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/299)) |
| Guía de uso inicial | Disponible en [`docs/user-guide.md`](docs/user-guide.md); wiki y manual completo pendientes |
| Publicación | Mirrors y política de release estable pendientes |

El detalle completo está en [`docs/roadmap.md`](docs/roadmap.md). La guía inicial de uso está disponible en [`docs/user-guide.md`](docs/user-guide.md); la instalación automatizada y la migración del hook siguen pendientes. La guía inicial de uso ya está disponible en [`docs/user-guide.md`](docs/user-guide.md); la prueba de instalación y la migración del hook de ArchISO siguen pendientes. La [guía inicial para usuarios](docs/user-guide.md) está disponible, pero no sustituye una política de firma ni una prueba automatizada de instalación. La [guía inicial para usuarios](docs/user-guide.md) está disponible; no sustituye una política de firma ni una prueba automatizada de instalación. La [guía inicial para usuarios](docs/user-guide.md) está disponible; no sustituye una política de firma ni una prueba automatizada de instalación.

---

## Estado actual

Versión del proyecto: **1.5.3** ( [`VERSION`](VERSION) ), una actualización de utilidades sobre la 1.5; la última ISO publicada es la 1.5 (9 de noviembre de 2026).

ChurrOS cuenta con ISO personalizada, ediciones Niri, XFCE y servidor, construcción basada en archiso, CLI de desarrollo, Calamares, aplicaciones Rust, actualizador, rollback Btrfs, branding propio, tema GRUB y CI. La guía inicial está en [`docs/user-guide.md`](docs/user-guide.md); todavía faltan la prueba automatizada de instalación en disco, la firma obligatoria de actualizaciones y el repositorio remoto firmado.

El proyecto está en desarrollo activo y en etapa temprana. El instalador es Calamares con parches propios. Calamares, Bazaar, yay, wlogout y python-pywal se compilan en local la primera vez que se construye la ISO y se reutilizan en los builds siguientes; Calamares se recompila si cambian libpython o sus parches.

---

## Comunidad y soporte

Las preguntas, los errores y las propuestas van a los [issues de GitHub](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues).

---

## Contribuir

Las contribuciones son bienvenidas, también sin programar: probar ISOs, reportar errores, mejorar la documentación o responder preguntas. La guía está en [`docs/contributing.md`](docs/contributing.md), con una sección para [contribuir sin programar](docs/contributing.md#contribuir-sin-programar) y las pruebas que pide cada tipo de cambio.

Antes de empezar a programar:

```bash
./churros doctor
```

Después de realizar cambios:

```bash
./churros check
```

Al participar aceptas el [código de conducta](CODE_OF_CONDUCT.md). [`AGENTS.md`](AGENTS.md) resume las convenciones para herramientas y agentes.

---

## Principios

Los principios del proyecto y cómo se toman las decisiones están en [`docs/principios.md`](docs/principios.md).

---

## Seguridad

No abras issues públicos para reportar un fallo de seguridad. Cómo reportarlo está en [`SECURITY.md`](SECURITY.md). Para el modelo de ejecución privilegiada del sistema, ver [`docs/privileged-execution.md`](docs/privileged-execution.md).

---

## Licencia

El código de ChurrOS se distribuye bajo la [GNU General Public License v3.0](LICENSE), en su variante GPL-3.0-only (declarada en `rust/Cargo.toml`). Los ficheros heredados de archiso conservan su licencia original, GPL-3.0-or-later. Los paquetes de terceros incluidos en la ISO conservan sus propias licencias. La licencia de los recursos gráficos y de los componentes de terceros está en [`docs/licencias.md`](docs/licencias.md).

---

<div align="center">
Una distribución construida con software libre.
</div>
