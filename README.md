<div align="center">
  <img src="archiso/airootfs/usr/share/pixmaps/churros-logo.svg" width="96" alt="ChurrOS">
  <h1>ChurrOS</h1>
  <p><strong>Distribución Linux basada en Arch Linux</strong>, construida con archiso, con escritorio Niri y herramientas propias en Rust.</p>
  <p>
    <a href="actions/workflows/ci.yml"><img alt="CI" src="https://github.com/Hoyuse/ChurrOS/actions/workflows/ci.yml/badge.svg"></a>
    <a href="blob/main/LICENSE"><img alt="Licencia" src="https://img.shields.io/badge/licencia-GPL--3.0-blue.svg"></a>
    <img alt="Base" src="https://img.shields.io/badge/base-Arch%20Linux-1793D1.svg">
    <img alt="Build" src="https://img.shields.io/badge/build-archiso-1793D1.svg">
    <img alt="Apps" src="https://img.shields.io/badge/apps-Rust-orange.svg">
    <img alt="Escritorios" src="https://img.shields.io/badge/escritorios-Niri%20%2F%20XFCE%20%2F%20Plasma%20%2F%20Server-FFBC00.svg">
  </p>
</div>

---

## Qué es ChurrOS

ChurrOS es una distribución Linux basada en Arch Linux y construida mediante [archiso](https://archlinux.org/archiso/). El repositorio contiene el perfil de la ISO, el overlay del sistema Live, la configuración del instalador, las utilidades de administración y el código de las aplicaciones propias.

El proyecto combina:

- Una base Arch Linux.
- Un sistema de construcción automatizado.
- Una identidad visual propia.
- Escritorios configurados por edición.
- Aplicaciones oficiales desarrolladas en Rust.
- Integración con Calamares.
- Herramientas propias de desarrollo y administración.
- Documentación orientada al mantenimiento del proyecto.

ChurrOS utiliza Arch Linux como base actualmente, mientras desarrolla progresivamente su propio ecosistema.

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
| Edición KDE Plasma | ✅ |
| Edición Servidor (sin escritorio, por SSH) | ✅ |
| Aplicaciones oficiales en Rust | ✅ |
| Calamares con branding propio | ✅ |
| Tema GRUB | ✅ |
| Actualizador de ChurrOS | ✅ |
| Rollback mediante snapshots Btrfs | ✅ |
| Repositorio oficial de paquetes | 🚧 |
| Instalador completamente propio | 🚧 |
| Wiki oficial | 🚧 |
| Manual de usuario | 🚧 |

---

## Ediciones

### Niri

La edición predeterminada. Utiliza:

- Niri (Wayland con tiling dinámico)
- Noctalia (paquete `noctalia` de [extra])
- Waybar / Fuzzel / Mako (alternativa, mantenidos)
- foot
- Aplicaciones oficiales de ChurrOS

```bash
./churros build
```

### XFCE

Edición basada en XFCE, orientada a una experiencia de escritorio tradicional y ligera. Usa una lista de paquetes propia (`archiso/packages.xfce.x86_64`, 214 paquetes frente a los 206 de la edición Niri).

```bash
./churros build --edition xfce
```

### KDE Plasma

Edición basada en KDE Plasma 6, completa y orientada a un escritorio tradicional con muchas opciones. Usa su propia lista de paquetes (`archiso/packages.kde.x86_64`, 209 paquetes) y arranca en la sesión Wayland de Plasma (`startplasma-wayland`).

```bash
./churros build --edition kde
./churros build --edition server
```

Es la edición más pesada: el cierre de dependencias ronda los **3340 MiB instalados**, frente a unos 3140 (niri) y 3100 (xfce).

### Servidor

Edición sin escritorio gráfico en el sistema instalado, accesible por SSH. La ISO lleva un XFCE mínimo porque el instalador (Calamares) es gráfico; `configure-server` lo quita al terminar la instalación y deja el arranque en `multi-user`.

```bash
./churros build --edition server
```

Es la más ligera: **1843 MiB instalados**, un 41 % menos que la edición Niri. Incluye `sshd`, `chronyd` y `fail2ban` habilitados. Los detalles y las limitaciones están en [`docs/server.md`](docs/server.md).

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

`./churros build` ejecuta cinco pasos:

1. **Preparing branding** — copia `branding/` al airootfs y genera el tema de GRUB.
2. **Checking packages** — compila Calamares y los extras locales (`yay`, `wlogout`, `python-pywal`, `bazaar`) si faltan, despliega la configuración del instalador y copia los paquetes al repositorio local.
3. **Building Rust apps** — compila las apps en release y despliega los binarios en `usr/bin/`.
4. **Cleaning previous build** — borra `work/` y `out/`.
5. **Building ISO** — ejecuta `mkarchiso` y deja la imagen en `out/`.

Los pasos que pasan por `sudo` son los que archiso necesita con privilegios. La ISO generada queda en `out/`.

---

## Inicio rápido

### Requisitos

ChurrOS está diseñado para desarrollarse desde Arch Linux o una distribución basada en Arch. `mkarchiso` construye la imagen dentro de la propia ISO, así que la máquina de build debe ser `x86_64`.

```bash
sudo pacman -S archiso git qemu-full edk2-ovmf rust cargo shellcheck gettext
```

`doctor` comprueba además `xorriso`, `squashfs-tools`, `mtools`, `dosfstools`, `grub`, `mkinitcpio`, `pkgconf` y el acceso a `/dev/kvm`.

Herramientas opcionales para algunos flujos de trabajo: `virt-manager`, `swtpm`.

```bash
./churros doctor
```

El comando detecta las dependencias que faltan y, cuando corresponde, ofrece instalarlas mediante `pacman`.

> `./churros build` compila Calamares desde AUR, lo que requiere además un entorno AUR funcional (`base-devel`, `git`) y las dependencias de compilación que declara su PKGBUILD (cmake, ninja, Qt 6). `doctor` todavía no las comprueba.

### Clonar

```bash
git clone https://github.com/Hoyuse/ChurrOS.git
cd ChurrOS
```

Se recomienda trabajar mediante ramas y pull requests en lugar de realizar cambios directamente sobre `main`.

### Construir

```bash
./churros build              # edición Niri
./churros build --edition xfce
./churros build --edition kde
```
./churros build --arch x86_64     # por defecto / anfitriona
./churros build --arch arm64      # ARM de 64 bits (edición pi / Raspberry Pi)
./churros build --arch i686       # i686 / Arch Linux 32
```
### Probar en QEMU

```bash
./churros run
```

Si no existe una ISO, `./churros run` solicitará al desarrollador que la construya. La máquina virtual usa un disco QCOW2 de desarrollo de 64 GiB en `vm/`.

| Opción | Qué hace |
|---|---|
| `./churros run --nokvm` | Ejecuta QEMU sin aceleración KVM |
| `./churros run --fresh` | Regenera las variables UEFI de la máquina virtual |
| `./churros run --clean` | Elimina el disco virtual y las variables UEFI antes de iniciar |

### Limpiar

```bash
./churros clean
```

Elimina los artefactos generados (`work/` y `out/`). No toca el código fuente.

---

## CLI de ChurrOS

```text
./churros <comando> [opciones]
```

| Comando | Qué hace |
|---|---|
| `build` | Construye la ISO (`--edition niri\|xfce\|kde\|server`) |
| `run` | Construye si hace falta y lanza QEMU (`--nokvm`, `--fresh`, `--clean`) |
| `clean` | Elimina los artefactos de construcción |
| `check` | Ejecuta las comprobaciones estáticas del repositorio |
| `doctor` | Diagnostica el entorno de desarrollo |
| `apps` | Abre las apps del repo en el host, sin ISO |
| `info` | Muestra información del proyecto |
| `version` | Muestra la versión de la CLI |
| `logo` | Imprime el logo en ASCII |

```bash
./churros --help
```

---

## Aplicaciones oficiales

Las aplicaciones oficiales de ChurrOS están desarrolladas en Rust, utilizando GTK 4, libadwaita y gtk4-rs.

| Aplicación | Binario | Función |
|---|---|---|
| Welcome | `churros-welcome` | Pantalla de bienvenida |
| Settings | `churros-settings` | Configuración del sistema |
| Control Center | `churros-control-center` | Centro de control |
| Popups | `churros-popup` | Controles rápidos |
| Tour | `churros-tour` | Recorrido guiado del escritorio |
| Services | `churros_services` | Biblioteca de servicios compartidos |

Los crates con `deploy = true` se compilan durante la construcción y se despliegan en `/usr/bin`. `churros_services` es una biblioteca: la usan las demás apps y no se despliega por separado.

### churros-welcome

Pantalla de bienvenida. Muestra CPU, RAM, kernel, sistema operativo, arquitectura y hostname, y ofrece accesos rápidos al instalador, a GitHub y a la comunidad.

### churros-settings

Aplicación principal de configuración, con GTK4 y libadwaita. En Niri se abre con `Mod+P`.

### churros-control-center

Centraliza red, Bluetooth, brillo, batería y audio. En Niri se abre con `Mod+C`.

### churros-popup

Controles rápidos para red, audio, volumen, Bluetooth, batería, brillo y energía.

```bash
churros-popup audio
```

### churros-tour

Recorrido guiado que se abre en el primer arranque para enseñar las esquinas del escritorio. Se limpia al terminar la instalación, así que no aparece en el sistema instalado.

---

## Paquetes y ecosistema

ChurrOS utiliza un repositorio local de paquetes durante la construcción (`archiso/packages/`). El build puede compilar e integrar componentes adicionales:

- Calamares
- yay
- wlogout
- python-pywal
- bazaar (parcheado para resolver un conflicto de `libdex`)

El objetivo a largo plazo es disponer de un repositorio oficial de paquetes de ChurrOS.

Cada edición de escritorio tiene además su propio perfil en `archiso/`: `packages.x86_64` (206 entradas), `packages.xfce.x86_64` (214), `packages.kde.x86_64` (209) y `packages.server.x86_64` (185).

---

## Instalador

ChurrOS utiliza actualmente Calamares como instalador gráfico, con branding propio y configuración específica del proyecto.

Soporta, entre otras funciones:

- Particionado automático.
- Particionado manual.
- Selección de idioma.
- Selección de zona horaria.
- Creación de usuarios.
- Instalación del bootloader (GRUB en UEFI, Syslinux en BIOS).
- Configuración posterior a la instalación.

La secuencia de instalación está definida en `installer/calamares/settings.conf` e incluye pasos de shell propios (keyring de pacman, configuración de mkinitcpio, repositorio local temporal, tema de GRUB y limpieza de rastros del Live).

El proyecto contempla desarrollar un instalador propio en el futuro, pero Calamares es el instalador utilizado actualmente.

---

## Identidad visual

ChurrOS mantiene sus recursos visuales dentro de una estructura organizada. Incluye:

- Logo oficial.
- Mascota.
- Wallpapers.
- Fastfetch personalizado.
- Iconos.
- Cursor.
- Tema GRUB.
- Configuración visual de las aplicaciones.
- Branding del sistema Live.

Las guías están en [`docs/branding.md`](docs/branding.md) y en `branding/`.

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

- Sintaxis Bash y ShellCheck.
- Sintaxis Python.
- Listas de paquetes de la ISO.
- Comandos referenciados por la configuración de Niri.
- `Exec` y `TryExec` de las desktop entries.
- Orden de ejecución y configuración de los módulos de Calamares.
- Branding de Calamares.
- Snapshots Btrfs.
- Traducciones (`po/*.po`).
- Versionado.
- Higiene del repositorio.

Termina con código de salida distinto de cero cuando encuentra fallos. Es lo que ejecuta la CI.

---

## Diagnóstico del entorno

```bash
./churros doctor
```

Comprueba las herramientas necesarias para archiso, QEMU, Rust, la construcción de la ISO, GRUB, SquashFS, FAT, mtools, gettext, shellcheck, pkg-config y la virtualización KVM, incluyendo si `/dev/kvm` está disponible.

---

## Integración continua

ChurrOS utiliza GitHub Actions con dos trabajos:

```text
GitHub Actions
      │
      ├── Static checks
      │      └── ./churros check
      │
      └── Rust tests
             └── cargo test -p churros-services
```

Los workflows se ejecutan para cambios en `main` y para pull requests. La CI **no** construye la ISO completa, y los tests de Rust cubren hoy únicamente el crate `churros-services`.

---

## Estructura del proyecto

```text
ChurrOS/
├── archiso/       Perfil archiso: paquetes, overlay del Live, cargadores
├── branding/      Identidad visual y customize_airootfs.sh
├── docs/          Documentación oficial
├── installer/     Configuración de Calamares y despliegue
├── po/            Traducciones gettext
├── rust/          Aplicaciones oficiales en Rust
├── scripts/       CLI de desarrollo y scripts de build
├── vm/            Máquina virtual generada (no versionada)
├── out/           ISO generada (no versionada)
├── work/          Temporal de archiso (no versionada)
├── churros        CLI principal
├── VERSION        Versión del proyecto
└── LICENSE        Licencia
```

`out/`, `work/` y `vm/` contienen artefactos generados y no forman parte del código fuente. El detalle está en [`docs/project-structure.md`](docs/project-structure.md) y [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Documentación

| Documento | Contenido |
|---|---|
| [Getting Started](docs/getting-started.md) | Preparar el entorno y generar la primera ISO |
| [Build System](docs/build-system.md) | La construcción de la ISO, paso a paso |
| [Project Structure](docs/project-structure.md) | Qué contiene cada carpeta |
| [CLI](docs/cli.md) | Referencia de `./churros` |
| [Development](docs/development.md) | Flujo de trabajo y convenciones |
| [Live Services](docs/live-services.md) | Servicios systemd, hooks de pacman y scripts del Live |
| [Login Greeter](docs/login-greeter.md) | greetd y ReGreet |
| [Desktop Config](docs/desktop-config.md) | Usuario del Live y configuración del escritorio |
| [Apps](docs/apps.md) | Las aplicaciones en Rust |
| [Preferences](docs/preferences.md) | `churros-settings` |
| [Popups](docs/popups.md) | `churros-popup` |
| [Services](docs/services.md) | Capa de servicios compartida |
| [Rollback](docs/rollback.md) | Snapshots de Btrfs |
| [Server](docs/server.md) | Edición para servidores, sin escritorio |
| [Installer](docs/installer.md) | Cómo instala ChurrOS, edition por edition |
| [Privileged Execution](docs/privileged-execution.md) | Cómo se obtiene privilegio y con qué reglas |
| [Branding](docs/branding.md) | Identidad visual |
| [Boot](docs/boot.md) | Arranque de la ISO |
| [VM](docs/vm.md) | Entorno de pruebas con QEMU |
| [Release](docs/release.md) | Proceso de publicación |
| [Contributing](docs/contributing.md) | Cómo contribuir |
| [Roadmap](docs/roadmap.md) | Hoja de ruta por fases |
| [Vision](docs/vision.md) | Objetivos de largo plazo |
| [Devlog](docs/devlog.md) | Registro de cambios |

---

## Roadmap

| Fase | Pendiente |
|---|---|
| 1 — Fundación | — |
| 2 — Identidad | Plymouth, branding de greetd |
| 3 — Escritorio | Wlogout |
| 4 — Instalador | — (Calamares) |
| 5 — Ecosistema | Repositorio oficial de paquetes |
| 6 — Publicación | Sitio web, wiki, manual de usuario, comunidad |

El detalle completo está en [`docs/roadmap.md`](docs/roadmap.md).

---

## Estado actual

Versión del proyecto: **1.2** ( [`VERSION`](VERSION) ).

ChurrOS cuenta con ISO personalizada, tres ediciones de escritorio (Niri, XFCE y KDE Plasma), construcción basada en archiso, CLI de desarrollo, instalador Calamares, aplicaciones oficiales en Rust, centro de control, herramientas de configuración, popups del sistema, actualizador, rollback Btrfs, branding propio, tema GRUB, CI y sistema de comprobaciones.

El proyecto está en desarrollo activo y en etapa temprana: no hay soporte fuera de GitHub, el instalador es Calamares con parches propios y los paquetes que no están en Arch se compilan en el host durante cada build.

La ISO de la versión actual se distribuye desde [download.churroslinux.org](https://download.churroslinux.org/). Las releases de GitHub contienen assets parciales: `v0.6` incluye la ISO en `.7z` con su `SHA256SUMS` y `v1.0` el paquete de utilidades. Verifica siempre el hash antes de instalar:

```bash
sha256sum -c SHA256SUMS
```

---

## Contribuir

Las contribuciones son bienvenidas. Antes de comenzar:

```bash
./churros doctor
```

Después de realizar cambios:

```bash
./churros check
```

Y, cuando corresponda:

```bash
./churros build
./churros run
```

Flujo recomendado:

```text
Crear rama
    ↓
Modificar código
    ↓
./churros check
    ↓
./churros build
    ↓
./churros run
    ↓
Verificar
    ↓
Commit
    ↓
Pull Request
```

Consulta [`docs/contributing.md`](docs/contributing.md) para conocer las convenciones del proyecto y [`AGENTS.md`](AGENTS.md) para el resumen de convenciones dirigido a herramientas y agentes.

---

## Filosofía

ChurrOS prioriza la calidad sobre la cantidad, la estabilidad, la organización, la automatización y el mantenimiento a largo plazo.

El objetivo no es modificar Arch Linux visualmente, sino construir progresivamente una distribución con identidad, herramientas, aplicaciones, documentación e infraestructura propias.

---

## Seguridad

No abras issues públicos para reportar un fallo de seguridad. La política y los canales privados están en [`SECURITY.md`](SECURITY.md). Para el modelo de ejecución privilegiada del sistema, ver [`docs/privileged-execution.md`](docs/privileged-execution.md).

---

## Licencia

ChurrOS se distribuye bajo la [GNU General Public License v3.0](LICENSE) (GPL-3.0). Los paquetes de terceros incluidos en la ISO conservan sus propias licencias.

---

<div align="center">
Una distribución construida con software libre.
</div>