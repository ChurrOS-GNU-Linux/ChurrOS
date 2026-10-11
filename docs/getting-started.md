# Getting Started

Bienvenido al entorno de desarrollo de ChurrOS.

Esta guía explica cómo preparar el sistema, obtener el código fuente del proyecto y generar la primera imagen ISO.

---

# Requisitos

ChurrOS se desarrolla sobre Arch Linux, pero se puede trabajar desde cualquier distro: lo que solo existe en Arch (`mkarchiso`, `makepkg`, GTK y libadwaita recientes) corre en un contenedor Arch definido en `Containerfile`.

## Qué funciona en cada distro

| Tarea | Arch y derivadas | Debian / Ubuntu | Fedora | Otras |
|-------|------------------|-----------------|--------|-------|
| `./install-deps.sh` | ✅ pacman | ✅ apt | ✅ dnf | ❌ instalar a mano |
| `./churros check` y tests (Python, Node) | ✅ | ✅ | ✅ | ✅ con python3, node, shellcheck |
| `./churros run` (QEMU) | ✅ | ✅ | ✅ | ✅ con qemu + OVMF/AAVMF |
| `./churros build` (ISO en el host) | ✅ | ❌ | ❌ | ❌ |
| `./churros build --container` | ✅ | ✅ | ✅ | ✅ con podman o docker |
| `./churros rust` (apps GTK, en contenedor) | ✅ | ✅ | ✅ | ✅ con podman o docker |
| `./churros rust --host` / `./churros apps` | ✅ | ❌ GTK/libadwaita viejos | ⚠️ depende de la versión | ⚠️ |
| `cargo test -p churros-services` en el host | ✅ | ⚠️ necesita rustc ≥ 1.85 (rustup) | ✅ | ⚠️ |

Notas:

- `install-deps.sh` en Debian/Ubuntu instala `rustup` si el `rustc` de apt es anterior a 1.85 (Ubuntu 24.04 trae 1.75). Debian 12 no empaqueta rustup: instálalo desde https://rustup.rs.
- `scripts/test-kde-integration.py` salta (SKIP) la prueba del panel sin `kwriteconfig6` y la de autologin sin un `rustc` ≥ 1.85.
- Fuera de Arch, `./churros check` no compara la libpython del paquete de Calamares con el Python del host (no es el de la ISO): esa comprobación la hace el build en el contenedor.

## Contenedor de build

```bash
./churros build --container              # ISO, en cualquier distro
./churros build --container --edition kde
./churros rust                           # build + test + clippy de rust/, como el CI
```

- Usa podman y, si no hay, docker. Se ejecuta con root real (`sudo podman` o el demonio de docker) y `--privileged`, porque `mkarchiso` monta `proc`, `sys` y `dev` en el chroot de la ISO. Docker rootless no sirve para el build.
- El repo se monta en `/churros` y todo corre con tu UID: la ISO queda en `out/` a tu nombre. Rust de la ISO x86_64 compila en `rust/target/container`, separado de los builds del host.
- La imagen x86_64 (`localhost/churros-builder`, `Containerfile`) se construye sola la primera vez y se reconstruye si cambia `Containerfile` o tiene más de 7 días. `CHURROS_CONTAINER_REBUILD=1` fuerza la reconstrucción.
- La ISO aarch64 no usa esa imagen. `./churros build --container --arch arm64` construye `localhost/churros-builder-aarch64` desde `Containerfile.aarch64` (`--platform linux/arm64`, base `docker.io/menci/archlinuxarm`) y corre dentro paquetes locales, Rust y mkarchiso. En un host x86_64 hace falta qemu-user-static con binfmt y la bandera `C` (credentials). Debian y Ubuntu registran el intérprete como `POF`, sin `C`: `sudo` dentro de makepkg responde `effective uid is not 0` y el paquete no se construye. `./churros doctor --arch arm64` lee `/proc/sys/fs/binfmt_misc/qemu-aarch64` y, si falta `C`, explica cómo volver a registrarlo (`echo` del magic con las secuencias `\x` literales hacia `binfmt_misc/register` y flags `FPOC`; el kernel decodifica `\x`, `printf '%b'` no sirve porque un NUL trunca el magic). También vale `update-binfmts --import` si existe la plantilla, o `/etc/binfmt.d/qemu-aarch64.conf` con `F` y `C` más `systemctl restart systemd-binfmt`. Ese contenedor desactiva el sandbox de pacman (seccomp devuelve EINVAL bajo qemu-user), sustituye el mirrorlist de la imagen por RWTH antes del primer `pacman -Sy`, y fuerza `PKGEXT='.pkg.tar.zst'` en `/etc/makepkg.conf.d/` porque ALARM trae `.pkg.tar.xz`. Los scripts aceptan las dos extensiones al reutilizar un paquete ya compilado. En un host aarch64 el mismo contenedor es nativo. Rust de ese build va a `rust/target/container-aarch64` y los paquetes locales a `archiso/packages/aarch64/`.
- Volúmenes persistentes: `churros-pacman-cache` y `churros-builder-home` para x86_64; `churros-pacman-cache-aarch64` y `churros-builder-home-aarch64` para la ISO ARM. Se borran con `podman volume rm` (o `docker volume rm`).
- Variables: `CHURROS_CONTAINER_ENGINE=podman|docker`, `CHURROS_CONTAINER_ARGS` (argumentos extra para `run`, p. ej. un proxy) y `CHURROS_CONTAINER_BASE` (imagen base; la oficial `archlinux` solo existe para x86_64). `./churros rust` en un runner ARM sigue usando `Containerfile` con `docker.io/menci/archlinuxarm`: esa imagen no lleva archiso. La ISO ARM es `Containerfile.aarch64`, que instala el paquete `archiso` (`arch=any`) desde extra de Arch.
- El CI (`.github/workflows/rust.yml`) construye la imagen desde `Containerfile` en cada PR y una vez por semana, y ejecuta `./churros rust` en x86_64 y en un runner ARM64. `.github/workflows/iso-arm64.yml` construye la ISO aarch64 en `ubuntu-24.04-arm` (manual, y en PRs que tocan el perfil arm64) y la sube como artefacto.

## Paquetes necesarios (Arch)

En otras distros: `./install-deps.sh`.

```bash
sudo pacman -S \
    archiso \
    git \
    qemu-full \
    edk2-ovmf \
    rust \
    cargo \
    virt-manager \
    swtpm
```

`./churros build` puede instalar `rust`/`cargo` si faltan, pero conviene tenerlos de antemano.

| Paquete | Obligatorio |
|----------|-------------|
| archiso | ✅ |
| git | ✅ |
| qemu-full | ✅ |
| edk2-ovmf | ✅ |
| rust / cargo | ✅ (compila las apps oficiales) |
| virt-manager | Opcional |
| swtpm | Opcional |

Comprueba el entorno con:

```bash
./churros doctor
```

---

# Clonar el proyecto

```bash
git clone https://github.com/Hoyuse/ChurrOS.git

cd ChurrOS
```

No se trabaja directo en `main`. Crea una rama por cambio y abre un pull request.

---

# Estructura inicial

Después de clonar el proyecto encontrarás una estructura similar a la siguiente:

```text
ChurrOS
├── archiso/
├── branding/
├── docs/
├── installer/
├── po/
├── rust/
├── scripts/
├── churros
├── VERSION
└── README.md
```

`out/`, `work/` y `vm/` aparecen al construir o ejecutar la ISO.

---

# Compilar la ISO

```bash
./churros build
```

Este comando:

1. Copia branding y tema GRUB al airootfs.
2. Construye paquetes AUR locales si faltan.
3. Compila las apps Rust y las deja en `usr/bin/`.
4. Ejecuta ArchISO (`mkarchiso`).
5. Deja la ISO en `out/`.

Hace falta `sudo` para `mkarchiso`.

## Elegir edición

Sin opciones compila la edición **niri**. Las otras se piden explícitamente:

```bash
./churros build --edition xfce   # XFCE
./churros build --edition kde    # KDE Plasma
```

Cada edición tiene su lista de paquetes (`archiso/packages.<edición>.x86_64`) y su lanzador de sesión. La lista se elige al construir, no después: una ISO de niri no se convierte en una de XFCE. El detalle de cada escritorio está en [`docs/desktop-config.md`](desktop-config.md).

---

# Ejecutar la ISO

```bash
./churros run
```

Este comando:

- Construye la ISO si es necesario.
- Inicia una máquina virtual mediante QEMU.
- Arranca desde la última ISO generada.

No modifica el sistema anfitrión. Flags útiles: `--fresh` (UEFI limpia), `--nokvm`, `--clean`. Detalle en `docs/vm.md`.

---

# Limpiar archivos temporales

```bash
./churros clean
```

Elimina `work/` y `out/`.

---

# Flujo de trabajo recomendado

Modificar archivos

↓

```bash
./churros check
```

↓

```bash
./churros build
```

↓

```bash
./churros run
```

↓

Verificar cambios

↓

Commit en una rama y pull request

---

# Primeros cambios recomendados

Si acabas de comenzar a contribuir, puedes empezar por:

- Documentación
- CLI (`scripts/cli/`)
- Apps en `rust/`
- Configuración del escritorio (con cuidado: el skel temático no se toca salvo bugs)

Estos componentes permiten familiarizarse con la estructura sin tocar branding ni el instalador.

---

# Problemas frecuentes

## La ISO no se genera

Comprueba que `archiso` esté instalado.

```bash
pacman -Q archiso
```

## QEMU no inicia

```bash
qemu-system-x86_64 --version
```

## Falla la compilación Rust

```bash
pacman -Q rust cargo
cargo build --release --manifest-path rust/Cargo.toml
```

## No aparece la ISO

```bash
ls out/
```

Si está vacía, ejecuta de nuevo `./churros build`.

---

# Siguiente paso

Cuando puedas generar una ISO, continúa con **Project Structure** (`docs/project-structure.md`) y **Apps** (`docs/apps.md`).
