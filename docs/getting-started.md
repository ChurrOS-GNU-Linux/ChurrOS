# Getting Started

Esta guía explica cómo preparar el sistema, obtener el código fuente y generar la primera imagen ISO de ChurrOS.

---

## Requisitos

ChurrOS se desarrolla sobre Arch Linux, pero se puede trabajar desde cualquier distro: lo que solo existe en Arch (`mkarchiso`, `makepkg`, GTK y libadwaita recientes) corre en un contenedor Arch definido en `Containerfile`.

### Qué funciona en cada distro

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
- Fuera de Arch, `./churros check` no compara la libpython del paquete de Calamares con el Python del host (no es el de la ISO): esa comprobación la hace el build en el contenedor.

### Instalar las dependencias

```bash
./install-deps.sh                 # Arch, Debian/Ubuntu o Fedora; -y no pide confirmación
./install-deps.sh --arch arm64    # además, qemu-user-static para construir la ISO aarch64 en x86_64
./churros doctor                  # comprueba el resultado
```

En Arch instala `archiso`, `grub`, `git`, `qemu-full`, `edk2-ovmf`, `edk2-aarch64`, `rust`, `gtk4`, `libadwaita`, `python`, `nodejs`, `shellcheck`, `gettext` y `zstd`, e intenta instalar `virt-manager` y `swtpm` como opcionales. En Debian/Ubuntu y Fedora instala lo necesario para `check`, `run` y los tests, y podman si no hay ni podman ni docker.

Para construir la ISO en el host de Arch hace falta además `base-devel`, que `install-deps.sh` no instala: `makepkg` compila Calamares y los extras de AUR durante el build.

```bash
sudo pacman -S --needed base-devel
```

| Paquete (Arch) | Para qué |
|----------|-------------|
| archiso, grub | `mkarchiso` y el arranque UEFI de la ISO |
| base-devel | `makepkg`: Calamares y los extras de AUR |
| git | clonar y descargar PKGBUILD |
| qemu-full, edk2-ovmf, edk2-aarch64 | `./churros run` (x86_64, i686 y aarch64) |
| rust, gtk4, libadwaita | compilar las apps oficiales |
| python, nodejs, shellcheck, gettext, zstd | `./churros check` y sus tests |
| virt-manager, swtpm | opcionales |

Si falta `cargo`, `scripts/build-rust.sh` intenta instalarlo durante el build, pero conviene tenerlo de antemano.

### Contenedor de build

```bash
./churros build --container              # ISO, en cualquier distro
./churros rust                           # build + test + clippy de rust/, como la CI
```

- Usa podman y, si no hay, docker. Se ejecuta con root real (`sudo podman` o el demonio de docker) y `--privileged`, porque `mkarchiso` monta `proc`, `sys` y `dev` en el chroot de la ISO. Docker rootless no sirve para el build. Con `--privileged` se pasa también `--pids-limit=-1`: con el límite de procesos que podman aplica por defecto, el build llegó a fallar al verificar las firmas de los paquetes (`GPGME error`). Es la causa más probable, no una demostrada.
- El repo se monta en `/churros` y todo corre con tu UID: la ISO queda en `out/` a tu nombre. Rust de la ISO x86_64 compila en `rust/target/container`, separado de los builds del host.
- La imagen x86_64 (`localhost/churros-builder`, `Containerfile`) se construye sola la primera vez y se reconstruye si cambia `Containerfile` o tiene más de 7 días. `CHURROS_CONTAINER_REBUILD=1` fuerza la reconstrucción.
- La ISO aarch64 usa otra imagen: `./churros build --container --arch arm64` construye `localhost/churros-builder-aarch64` desde `Containerfile.aarch64` (`--platform linux/arm64`, base `docker.io/menci/archlinuxarm`) y corre dentro paquetes locales, Rust y mkarchiso. En un host aarch64 el contenedor es nativo. En x86_64 hace falta qemu-user-static registrado en binfmt con la bandera `C` (credentials); sin ella, `sudo` dentro de makepkg falla con `effective uid is not 0`. `./churros doctor --arch arm64` lo comprueba, y [Sistema de compilación](build-system.md#iso-aarch64) explica cómo volver a registrarlo. Rust de ese build va a `rust/target/container-aarch64` y los paquetes locales a `archiso/packages/aarch64/`.
- Volúmenes persistentes: `churros-pacman-cache` y `churros-builder-home` para x86_64; `churros-pacman-cache-aarch64` y `churros-builder-home-aarch64` para la ISO ARM. Se borran con `podman volume rm` (o `docker volume rm`).
- Variables: `CHURROS_CONTAINER_ENGINE=podman|docker`, `CHURROS_CONTAINER_ARGS` (argumentos extra para `run`, p. ej. un proxy) y `CHURROS_CONTAINER_BASE` (imagen base; la oficial `archlinux` solo existe para x86_64).
- La CI (`.github/workflows/rust.yml`) construye la imagen desde `Containerfile` en cada PR y una vez por semana, y ejecuta `./churros rust` en x86_64 y en un runner ARM64. `.github/workflows/iso-arm64.yml` construye la ISO aarch64 en `ubuntu-24.04-arm` (manual, y en PRs que tocan el perfil arm64) y la sube como artefacto.

---

## Clonar el proyecto

```bash
git clone https://github.com/ChurrOS-GNU-Linux/ChurrOS.git
cd ChurrOS
```

No se trabaja directo en `main`. Crea una rama por cambio y abre un pull request.

---

## Estructura inicial

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
├── Containerfile
├── Containerfile.aarch64
├── install-deps.sh
├── VERSION
└── README.md
```

`out/`, `work/` y `vm/` aparecen al construir o ejecutar la ISO. El detalle está en [Project Structure](project-structure.md).

---

## Compilar la ISO

```bash
./churros build               # en Arch
./churros build --container   # en cualquier distro
```

Este comando:

1. Comprueba que estén `mkarchiso`, `mksquashfs`, `xorriso`, `grub-mkstandalone`, `mkfs.fat` y mtools; si faltan, dice cómo instalarlos o propone `--container`.
2. Aplica la edición: lista de paquetes, `/etc/churros-edition` y la sesión Live de greetd.
3. Copia el branding y el tema de GRUB al airootfs y escribe la versión y la edición en `os-release`.
4. Prepara los paquetes locales: Calamares (se recompila si falta o si cambian libpython o los parches), Bazaar y, si faltan, yay, wlogout y python-pywal. Con Calamares disponible, despliega la configuración del instalador y copia los paquetes a `/root/packages` dentro de la ISO.
5. Compila las apps Rust y las deja en `archiso/airootfs/usr/bin/`.
6. Ejecuta `mkarchiso` y deja la ISO en `out/`.

Usa `sudo` para `mkarchiso`, para borrar `work/` y `out/` y para exponer el repositorio local en `/root/packages` del host mientras dura el build; `makepkg` lo usa también para instalar las dependencias de compilación. El detalle de cada paso está en [Build System](build-system.md).

### Elegir edición y arquitectura

Sin opciones compila la edición **niri** para la arquitectura del equipo. Las demás se piden explícitamente:

```bash
./churros build --edition xfce                           # XFCE
./churros build --edition server                         # servidor, sin escritorio
./churros build --container --arch arm64                 # Niri para aarch64 (UEFI)
./churros build --container --arch arm64 --edition pi    # Raspberry Pi Lite (experimental)
```

La edición niri usa `archiso/packages.<arch>`; las demás, `archiso/packages.<edición>.<arch>`. Hay listas para `xfce` y `server` en x86_64 y para `pi` en aarch64. La lista se elige al construir: una ISO de niri no se convierte en una de XFCE. La ISO de servidor arranca el Live en XFCE para poder ejecutar el instalador gráfico. El detalle de cada escritorio está en [Desktop Config](desktop-config.md).

`--arch i686` construye un port experimental de 32 bits sobre Arch Linux 32, sin sesión gráfica ni instalador gráfico. Necesita yay, wlogout y python-pywal compilados para i686.

---

## Ejecutar la ISO

```bash
./churros run
```

Este comando:

- Busca en `out/` la ISO más reciente de la arquitectura pedida. Si no hay ninguna, pregunta si quieres construirla.
- Crea un disco virtual de 64 GiB en `vm/` la primera vez.
- Arranca QEMU con firmware UEFI (la ISO i686 arranca por BIOS si no hay OVMF de 32 bits) y con KVM si `/dev/kvm` está disponible.

No modifica el sistema anfitrión. Flags útiles: `--fresh` (variables UEFI limpias, para arrancar del CD-ROM), `--nokvm`, `--clean` (borra disco y variables UEFI) y `--arch arm64|i686` (ISO de otra arquitectura). Detalle en [VM](vm.md).

---

## Limpiar archivos temporales

```bash
./churros clean
```

Elimina `work/`, `out/` y casi todos los ficheros que el build genera en `archiso/airootfs/` (la lista exacta está en [CLI](cli.md#clean)).

---

## Antes de abrir un pull request

Las pruebas dependen de lo que cambies: para documentación basta `./churros check`; para apps Rust, `./churros rust`; para build, escritorio o instalador, además `./churros build` y `./churros run`. La tabla completa está en [Pruebas según el tipo de cambio](contributing.md#pruebas-según-el-tipo-de-cambio).

---

## Primeros cambios recomendados

Si acabas de comenzar a contribuir, puedes empezar por:

- Documentación
- CLI (`scripts/cli/`)
- Apps en `rust/`
- Configuración del escritorio (con cuidado: el skel temático no se toca salvo bugs)

Estos componentes permiten familiarizarse con la estructura sin tocar branding ni el instalador.

---

## Problemas frecuentes

### La ISO no se genera

Ejecuta `./churros doctor`: indica qué herramienta falta y con qué paquete se instala. Fuera de Arch, construye con `./churros build --container`. Si las herramientas están, revisa la salida de `mkarchiso` en la terminal.

### QEMU no inicia

`./churros doctor` comprueba `qemu-system-x86_64`, `qemu-system-i386`, `qemu-system-aarch64`, `qemu-img` y el acceso a `/dev/kvm`. Si falta el firmware UEFI, instala OVMF (y AAVMF para aarch64). Más casos en [VM](vm.md).

### Falla la compilación Rust

```bash
./churros rust          # en el contenedor, igual que la CI
./churros rust --host   # en este equipo (Arch al día)
```

Si el error viene de gtk4 o libadwaita en el host, la versión de la distro es demasiado vieja: usa el contenedor.

### No aparece la ISO

```bash
ls out/
```

Si está vacía, ejecuta de nuevo `./churros build` y revisa el primer error de la salida.

---

## Siguiente paso

Cuando puedas generar una ISO, continúa con [Project Structure](project-structure.md) y [Apps](apps.md).
