# Project Structure

Este documento describe la organización del repositorio de ChurrOS y el propósito de cada directorio.

Mantener una estructura clara facilita el mantenimiento, el desarrollo y la incorporación de nuevos colaboradores.

---

# Estructura general

```text
ChurrOS
├── archiso/
├── branding/
├── docs/
├── installer/
├── po/
├── rust/
├── scripts/
├── out/
├── vm/
├── work/
├── churros
├── VERSION
├── LICENSE
└── README.md
```

`out/`, `vm/` y `work/` no forman parte del código fuente: se generan al construir o probar.

---

# Directorios

## archiso/

Perfil de ArchISO usado para construir la ISO Live.

Incluye:

- `packages.x86_64`, `packages.xfce.x86_64`, `packages.kde.x86_64`, `packages.server.x86_64` — una lista de paquetes por edición
- `profiledef.sh` — metadatos, arquitectura (`CHURROS_ARCH`), bootmodes (`bios.syslinux` + `uefi.grub` en x86_64) y permisos
- `pacman.x86_64.conf` y `pacman.aarch64.conf` — repositorios del bootstrap de cada arquitectura
- `airootfs/` — overlay del sistema Live (skel, servicios, assets)
- `grub/` y `syslinux/` — cargadores de la ISO
- `packages/` — repo pacman local (Calamares y extras AUR construidos en el host)

Es el corazón de la distribución.

---

## rust/

Workspace Cargo de las apps oficiales (gtk4-rs + libadwaita):

| Crate | Binario | `deploy` |
|-------|---------|----------|
| `churros-welcome` | `churros-welcome` | sí |
| `preferences` | `churros-settings` | sí |
| `control-center` | `churros-control-center` | sí |
| `popups` | `churros-popup` | sí |
| `churros-tour` | `churros-tour` | sí |
| `services` | librería `churros_services` | no (la usan las demás) |

`scripts/build-rust.sh` (lo invoca `./churros build`) compila en release y copia los binarios con `deploy = true` a `archiso/airootfs/usr/bin/`. Esos binarios no se versionan. Los assets de runtime viven en `archiso/airootfs/usr/share/churros/<app>/`.

---

## branding/

Identidad de la distribución y script que se aplica al arrancar el Live.

```text
branding
├── customize_airootfs.sh
├── files/          # os-release, issue, motd
├── grub-theme/     # tema del GRUB instalado
├── colors.md
├── typography.md
├── logo-guidelines.md
├── mascot.md
└── ui-guidelines.md
```

`customize_airootfs.sh` se copia al airootfs en cada build; editar la copia en `archiso/airootfs/root/` no tiene efecto.

Los wallpapers y el resto de assets de escritorio viven en `archiso/airootfs/usr/share/churros/`, no en carpetas `branding/wallpapers/` o `branding/logos/`.

---

## docs/

Documentación oficial del proyecto. Toda funcionalidad importante debe estar documentada.

---

## installer/

Configuración de Calamares (no un instalador propio todavía):

```text
installer
├── apply-calamares.sh
└── calamares/
    ├── settings.conf
    ├── branding/churros/
    ├── preview/            # solo ./churros apps calamares; no va a la ISO
    └── modules/
```

`apply-calamares.sh` despliega la config y la regla polkit al airootfs durante el build. `preview/` no se copia.

---

## po/

Traducciones gettext (`*.po`). `./churros check` las valida con `msgfmt --check`.

---

## scripts/

Scripts de desarrollo. No forman parte del sistema instalado.

- `scripts/cli/` — subcomandos de `./churros` (`build`, `run`, `check`, `apps`, `doctor`, …)
- `scripts/build-rust.sh`, `build-calamares.sh`, `build-aur.sh`, `build-grub-theme.sh`

---

## out/

ISO generada (`ChurrOS-*.iso`). Se puede borrar sin afectar el proyecto.

---

## work/

Directorio temporal de ArchISO. No forma parte del repositorio.

---

## vm/

Disco QEMU (`ChurrOS.qcow2`) y variables UEFI (`OVMF_VARS.fd`). Gitignorados; cada desarrollador los genera con `./churros run`.

---

# Archivos principales

## churros

CLI oficial de desarrollo. Despacha a `scripts/cli/<comando>.sh`.

```bash
./churros build
./churros run
./churros check
./churros clean
```

## VERSION

Número de versión del proyecto. Lo leen `./churros version` y `./churros info`.

## README.md

Página principal del proyecto.

## LICENSE

GNU General Public License v3.0 (GPL-3.0).

---

# Flujo del proyecto

```text
Modificar código
        ↓
./churros check
        ↓
./churros build
        ↓
./churros run
        ↓
Commit en una rama
        ↓
Pull request hacia main
```

No se trabaja directo en `main`.

---

# Organización del repositorio

Cada carpeta tiene una única responsabilidad.

❌ Incorrecto

```
branding/
    wallpaper.png
    build.sh
```

✅ Correcto

```
branding/
    files/os-release

scripts/
    build-rust.sh

archiso/airootfs/usr/share/churros/wallpapers/
    fondo.png
```

---

# Convenciones

- Mantener una estructura simple.
- Utilizar nombres descriptivos.
- Evitar duplicar archivos.
- Separar código, documentación y recursos gráficos.
- Documentar cualquier cambio importante.

---

# Objetivo

La estructura del proyecto debe permanecer organizada incluso cuando ChurrOS crezca. Una buena organización facilita el mantenimiento, reduce errores y mejora la colaboración.
