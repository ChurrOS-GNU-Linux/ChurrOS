# Build System

El sistema de compilación de ChurrOS está basado en **ArchISO** y automatizado mediante `./churros`.

El objetivo es generar imágenes ISO reproducibles, mantener un flujo sencillo y minimizar las tareas manuales.

---

# Arquitectura

```
               Código fuente
                     │
                     ▼
              ./churros build
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
    branding    paquetes AUR   apps Rust
        │            │            │
        └────────────┼────────────┘
                     ▼
              mkarchiso (sudo)
                     ▼
          out/ChurrOS-*.iso
```

---

# Componentes

- ArchISO (`mkarchiso`)
- CLI de ChurrOS (`scripts/cli/build.sh`)
- Perfil en `archiso/`
- Workspace Rust en `rust/`
- Paquetes locales en `archiso/packages/`
- Scripts de compilación auxiliares en `scripts/`:
  - `build-rust.sh`: Compila en release todos los crates de `rust/` con `deploy = true` y los instala en el airootfs.
  - `build-calamares.sh`: Compila el instalador Calamares desde AUR con parches locales y soporte de Python.
  - `build-aur.sh`: Compila paquetes AUR necesarios (`python-pywal`, `yay`, `wlogout`).
  - `build-bazaar.sh`: Compila la tienda de aplicaciones Bazaar contra `libdex>=1.2` (meson pide `libdex-1`). En Arch extra esa versión ya está; en Arch Linux ARM el repo trae 1.1.0, así que el script construye libdex 1.2, lo instala en el contenedor y lo publica en el repo local.
  - `build-grub-theme.sh`: Genera fuentes `.pf2` y recursos gráficos para el tema de GRUB.
  - `build-i18n.sh`: Compila catálogos gettext de `po/*.po` a `.mo` en `archiso/airootfs/usr/share/locale/`.
  - `build-churros-release.sh`: Genera el bundle OTA `churros-utils-<version>.tar.zst` y `updates.json` para el servidor de actualizaciones.

---

# Flujo de compilación

`./churros build [--edition <niri|xfce|kde|server>]` hace, en este orden:

## 0. Selección de edición y paquetes

- Si se especifica una edición que no sea `niri`: selecciona `archiso/packages.<edición>.x86_64`, configura `/etc/churros-edition` y ajusta el autologin de `greetd` al lanzador de sesión (`startxfce4` para xfce, `startplasma-wayland` para kde, `startxfce4` también para server, que usa el XFCE de la ISO solo para el instalador).
- Si se especifica `--edition niri` (por defecto): utiliza `archiso/packages.x86_64` (Niri, Noctalia, foot, Fuzzel, Mako) y el autologin a sesión Niri.

## 1. Branding y tema GRUB

Copia `branding/customize_airootfs.sh` y `branding/files/` al airootfs. Estampa `VERSION` y la edición activa en `os-release`. Regenera fuentes del tema GRUB si faltan y copia `branding/grub-theme` a `/usr/share/churros/grub-theme/`.

## 2. Paquetes locales

Si no están, construye Calamares y los extras AUR (`python-pywal`, `yay`, `wlogout`) en `archiso/packages/` (en aarch64, `archiso/packages/aarch64/`). Un paquete ya compilado se reconoce tanto si es `.pkg.tar.zst` como `.pkg.tar.xz`. Si hay paquete de Calamares, `installer/apply-calamares.sh` despliega la config y se copian los paquetes a `airootfs/root/packages/`.

## 3. Apps Rust

`scripts/build-rust.sh` compila el workspace en release y copia los crates con `deploy = true` a `archiso/airootfs/usr/bin/`. Esos binarios no se versionan; un trap al salir del build los limpia del airootfs (junto con branding y Calamares generados).

## 4. ArchISO

```bash
sudo rm -rf work out
sudo mkarchiso -v -w work -o out archiso
```

ArchISO instala paquetes, genera initramfs y squashfs, crea los cargadores (GRUB UEFI + Syslinux BIOS) y escribe la ISO.

## 5. Resultado

La ISO queda en `out/`. Ejemplo:

```text
out/ChurrOS-2026.08.17-x86_64-v0.7.iso
```

Al terminar se borra `work/` y se devuelve `out/` al usuario.

---

# Probar la distribución

```bash
./churros run
```

Busca la ISO más reciente, crea el disco QEMU si hace falta e inicia la VM. Detalle en `docs/vm.md`.

---

# Limpiar el proyecto

```bash
./churros clean
```

Elimina `work/` y `out/`. No toca el código fuente.

---

# Directorios utilizados

| Ruta | Uso |
|------|-----|
| `archiso/` | Perfil Live |
| `rust/` | Código de las apps oficiales |
| `branding/` | Identidad y script live |
| `installer/` | Config de Calamares |
| `work/` | Temporal de ArchISO |
| `out/` | ISO generada |

---

# Branding

Durante la compilación se integran:

- hostname, issue, motd, os-release
- logos y fondos
- tema GRUB
- configuraciones del Live

Editar la copia generada en `archiso/airootfs/root/customize_airootfs.sh` no sirve: se regenera en cada build.

---

# Errores comunes

## La ISO no aparece

```bash
ls out/
./churros build
```

## Error de permisos

```bash
./churros clean
./churros build
```

`mkarchiso` necesita `sudo`.

## ArchISO no encontrado

```bash
pacman -Q archiso
```

## Falla la compilación Rust

```bash
pacman -Q rust cargo
cargo build --release --manifest-path rust/Cargo.toml
```

## La compilación falla

Revisa el registro de `mkarchiso`. Suele deberse a paquetes inexistentes, rutas incorrectas, permisos o config inválida.

---

# Buenas prácticas

```
Modificar archivos
        ↓
./churros check
        ↓
./churros build
        ↓
./churros run
        ↓
Corregir
        ↓
Commit + pull request
```

Nunca modificar la ISO generada. Todos los cambios van en el código fuente.

---

# Futuro

Mejoras previstas:

- Compilaciones incrementales.
- Generación de checksums desde la CLI.
- Comando `./churros release`.

`./churros check` y el workflow de GitHub Actions ya cubren la verificación estática. El release v1.2 se publica a mano en download.churroslinux.org (ISO + torrent).

## CI

| Workflow | Dónde corre | Qué hace |
|----------|-------------|----------|
| `ci.yml` | `ubuntu-latest` | `./churros check` y `cargo test -p churros-services` (rápido, sin GTK) |
| `rust.yml` | imagen del `Containerfile`: `archlinux:latest` en `ubuntu-latest` y `menci/archlinuxarm` en `ubuntu-24.04-arm` | Compila el workspace completo (`--all-targets`), ejecuta sus tests y pasa clippy, en x86_64 y en ARM64 |
| `iso-arm64.yml` | `ubuntu-24.04-arm`, contenedor `Containerfile.aarch64` | `./churros build --container --arch arm64` y sube la ISO como artefacto. Manual (`workflow_dispatch`) y en PRs que tocan el perfil arm64. No es un check obligatorio |

Las apps GTK no se compilan en `ubuntu-latest`: gtk4-rs 0.11 exige GTK ≥ 4.22 y libadwaita-rs 0.9 exige libadwaita ≥ 1.9, versiones que Ubuntu no alcanza. `rust.yml` corre dentro de una imagen Arch, que es el mismo entorno donde se construye la ISO x86_64.

ARM64 de las apps se compila en un runner arm64 nativo con Arch Linux ARM, no con `cargo check --target aarch64-unknown-linux-gnu` desde x86_64: glib-sys y gtk4-sys buscan con pkg-config las bibliotecas de aarch64, que el runner x86_64 no tiene. Esa imagen de `rust.yml` no instala archiso (Arch Linux ARM no lo empaqueta). La ISO aarch64 es otro contenedor, `Containerfile.aarch64`: instala el `archiso` de extra de Arch (`arch=any`) y corre el build entero de forma nativa en `ubuntu-24.04-arm`. En un host x86_64 el mismo contenedor usa qemu-user.
