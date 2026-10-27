# Sistema de compilación

La ISO de ChurrOS se construye con ArchISO (`mkarchiso`) y un solo comando, `./churros build`, que ejecuta `scripts/cli/build.sh`. El resultado depende de la fecha y del estado de los repositorios de Arch en el momento del build: dos builds del mismo commit no dan la misma ISO bit a bit (`SOURCE_DATE_EPOCH` toma la hora actual y no se fija ninguna instantánea de los repositorios).

```text
./churros build
   ├─ edición y lista de paquetes
   ├─ branding (os-release, tema GRUB)
   ├─ paquetes locales [churros] (Calamares, Bazaar, extras AUR)
   ├─ apps Rust (build-rust.sh)
   └─ sudo mkarchiso  ->  out/ChurrOS-<fecha>-<arch>.iso
```

## Uso

```bash
./churros build [--edition niri|xfce|server|pi] [--arch x86_64|arm64|i686] [--container]
```

| Opción | Por defecto | Efecto |
|--------|-------------|--------|
| `--edition`, `-e` | `niri` | Lista de paquetes y sesión del Live (tabla siguiente). |
| `--arch`, `-a` | la del equipo (`uname -m`) | Arquitectura de la ISO. `arm64` equivale a `aarch64`. |
| `--container` | no | Ejecuta el build completo dentro del contenedor Arch del proyecto (ver [Contenedor](#contenedor)). |

### Ediciones y arquitecturas

| Edición | Arquitecturas | Lista de paquetes | Sesión del Live (autologin de greetd) |
|---------|---------------|-------------------|----------------------------------------|
| `niri` | x86_64, aarch64, i686 | `archiso/packages.<arch>` | `niri` |
| `xfce` | x86_64 | `archiso/packages.xfce.x86_64` | `churros-xfce-session` |
| `server` | x86_64 | `archiso/packages.server.x86_64` | `churros-xfce-session`: el XFCE solo está en el Live para el instalador y `configure-server` lo quita del sistema instalado |
| `pi` | aarch64 | `archiso/packages.pi.aarch64` | `churros-pi-session` (labwc + Waybar) |

Limitaciones por arquitectura:

- **aarch64** en un host que no es aarch64 solo se construye con `--container` (ver [ISO aarch64](#iso-aarch64)).
- **i686** usa los repositorios de Arch Linux 32, que no empaquetan niri, noctalia, `polkit-qt6`, webkitgtk-6.0 ni glycin. La ISO arranca sin escritorio, sin instalador (Calamares) y sin Bazaar. Los extras locales (`yay`, `wlogout`, `python-pywal`) tienen que estar compilados para i686.
- Si la arquitectura de la ISO no es la del equipo, el build avisa: makepkg compila los paquetes locales para la arquitectura del host y pacstrap rechaza los de otra.

## Requisitos del host

En Arch Linux el build corre directamente. Antes de empezar comprueba que existen `mkarchiso`, `mksquashfs`, `xorriso`, `grub-mkstandalone`, `mkfs.fat`, `mcopy` y `mmd`; si falta alguno, propone:

```bash
sudo pacman -S --needed archiso grub dosfstools mtools squashfs-tools libisoburn
```

En cualquier otra distro, `mkarchiso`, `pacstrap` y `makepkg` no existen: usa `./churros build --container` (podman o docker). `./churros doctor` revisa las herramientas del host.

El build necesita `sudo`: lo usan `mkarchiso`, la limpieza de `work/` y `out/`, y el enlace `/root/packages` (paso 5).

## Pasos del build

La salida de `build.sh` usa la misma numeración (`[0/5]` a `[5/5]` y, al final, `[6/6]`).

### 0. Edición

- Si la edición no es `niri`, copia `archiso/packages.<edición>.<arch>` sobre `archiso/packages.<arch>` (guarda el original como `.orig`).
- Escribe la edición en `archiso/airootfs/etc/churros-edition` (en todas las ediciones, también `niri`).
- Reescribe `archiso/airootfs/etc/greetd/config.toml` (guarda el original como `.bak`): greeter `cage` + `regreet` y autologin del usuario `churros` en la sesión de la edición.

### 1. Branding

- `scripts/build-grub-theme.sh` genera las fuentes `.pf2` del tema GRUB si faltan (necesita `grub-mkfont`).
- Copia `branding/customize_airootfs.sh`, `branding/files/` (issue, motd, os-release), `VERSION` y `branding/stamp-os-release.sh` a `archiso/airootfs/root/`, y estampa la versión y la edición en ese `os-release`.
- Copia `branding/grub-theme/` a `archiso/airootfs/usr/share/churros/grub-theme/`, de donde Calamares lo instala en el disco.

Hostname, logos y fondos no salen de este paso: están versionados en `archiso/airootfs/`.

### 2. Paquetes locales

El repositorio local `[churros]` vive en `archiso/packages/` (x86_64 e i686) o en `archiso/packages/aarch64/`. `pacman.<arch>.conf` lo declara antes que `core` y `extra` con `Server = file:///root/packages`, así que sus paquetes tienen prioridad.

1. Borra los paquetes de Noctalia v4 que hubiera dejado un build anterior (`noctalia-qs`, `noctalia-shell`) y, en `archiso/packages/`, los `.pkg.tar.zst` de otra arquitectura.
2. `scripts/build-calamares.sh` (salvo en i686): clona el PKGBUILD de Calamares del AUR, aplica `installer/patches/calamares-*.patch` y lo compila. Lo reutiliza si coinciden la versión de Python del host y el hash de los parches.
3. `scripts/build-aur.sh`, solo si falta alguno de `python-pywal`, `yay` o `wlogout`.
4. `scripts/build-bazaar.sh` (salvo en i686): compila Bazaar con el PKGBUILD de Arch y la dependencia `libdex>=1.2.0`. Lo reutiliza si el paquete ya depende de esa versión. En Arch Linux ARM, que trae libdex 1.1.0, compila también libdex 1.2 y lo publica en el repositorio local.
5. Si hay paquete de Calamares, `installer/apply-calamares.sh` copia la configuración del instalador y la regla polkit `49-calamares.rules`; después el build pone el nombre de la edición en el slideshow y copia el repositorio local a `archiso/airootfs/root/packages/`. Sin Calamares (i686) la ISO sale sin instalador.

Los paquetes ya compilados se reconocen tanto en `.pkg.tar.zst` como en `.pkg.tar.xz`.

### 3. Apps Rust

`scripts/build-rust.sh` compila en release todo el workspace `rust/` (en el contenedor, en `CARGO_TARGET_DIR`). Copia a `archiso/airootfs/usr/bin/` los binarios de los crates con `deploy = true` y su carpeta `assets/` a `archiso/airootfs/usr/share/churros/<binario>/assets/`. El binario se llama como el `name` del crate (el crate `preferences` produce `churros-settings`).

### 4. Limpieza del build anterior

`sudo rm -rf work out`. Cada build vacía `out/`: mueve la ISO anterior si quieres conservarla.

### 5. ISO

```bash
sudo env CHURROS_ARCH=<arch> mkarchiso -v -w work -o out archiso
```

Antes, el build crea el enlace `/root/packages` -> repositorio local, porque durante pacstrap `file:///root/packages` se resuelve contra la raíz del equipo y no contra el chroot. Sin `--container`, ese enlace queda en el `/root` del host mientras dura el build. En aarch64 aplica además `scripts/apply-aarch64-mkinitcpio.sh` y parchea `/usr/bin/mkarchiso` con `scripts/patch-mkarchiso-grubmodules.sh` (deja solo los módulos GRUB que Arch Linux ARM publica para `arm64-efi`). Por ambos motivos conviene `--container`.

`profiledef.sh` elige con `CHURROS_ARCH` el `pacman.<arch>.conf`, la compresión y los modos de arranque:

| Arquitectura | Arranque de la ISO | squashfs |
|--------------|--------------------|----------|
| x86_64 | Syslinux (BIOS) + GRUB (UEFI) | zstd |
| i686 | Syslinux (BIOS) + GRUB (UEFI IA32) | zstd |
| aarch64 | GRUB (UEFI) | xz |

mkarchiso copia `airootfs/`, instala encima los paquetes con pacstrap, ejecuta `customize_airootfs.sh` dentro del chroot (crea el usuario Live, activa servicios, instala Calamares desde `/root/packages`), genera initramfs y squashfs y escribe la ISO.

### 6. Resultado

Se borra `work/` y `out/` vuelve a ser del usuario. La ISO se llama `out/ChurrOS-<AAAA.MM.DD>-<arch>.iso`, por ejemplo `out/ChurrOS-2026.10.22-x86_64.iso`: lleva fecha y arquitectura, pero no edición ni versión. Para publicarla hay que renombrarla (ver [Release](release.md)). Para probarla en QEMU: `./churros run` (ver [VM](vm.md)).

### Limpieza al salir

Un `trap` en `EXIT` deshace los cambios temporales aunque el build falle: desmonta lo que quede montado en `work/`, quita el enlace `/root/packages` si lo creó el build, restaura `packages.<arch>` y `greetd/config.toml`, borra de `archiso/airootfs/` `etc/churros-edition`, `root/customize_airootfs.sh`, `root/branding/`, `root/packages/`, `etc/calamares/`, `49-calamares.rules`, los binarios Rust y `usr/share/churros/grub-theme/`, y devuelve el preset de mkinitcpio de x86 (`apply-aarch64-mkinitcpio.sh restore`). Esas rutas se regeneran en cada build: editarlas a mano no sirve. Los assets que copia `build-rust.sh` se quedan. Git ignora los de welcome, settings, popup y control-center; los de `usr/share/churros/churros-tour/` están versionados y cada build los sobrescribe desde `rust/churros-tour/assets/`.

## Contenedor

`--container` ejecuta el mismo `build.sh` dentro de una imagen Arch. Lo gestiona `scripts/lib/container.sh`:

- Imagen `localhost/churros-builder`, construida desde `Containerfile` (archiso, base-devel, grub, gtk4, libadwaita, rust, lld, nodejs, python). Se reconstruye si cambia el `Containerfile`, si tiene más de 7 días o con `CHURROS_CONTAINER_REBUILD=1`.
- Motor: podman o, si no hay, docker (`CHURROS_CONTAINER_ENGINE` lo fuerza). Corre como root real (`sudo podman` o el demonio de docker) y con `--privileged`, porque pacstrap monta `proc` y `dev` en el chroot; docker rootless no sirve.
- El repo se monta en `/churros`. `scripts/container-entrypoint.sh` crea el usuario `builder` con el UID/GID del host (makepkg no corre como root), así que `out/` y `archiso/packages/` quedan a nombre del usuario.
- Cargo compila en `rust/target/container`. Los volúmenes `churros-builder-home` y `churros-pacman-cache` guardan la caché de cargo y la de pacman entre ejecuciones.
- El enlace `/root/packages` y los cambios en `mkarchiso` se hacen dentro del contenedor, no en el host.

### ISO aarch64

```bash
./churros doctor --arch arm64            # comprueba qemu-user y binfmt
./churros build --container --arch arm64
```

- Imagen `localhost/churros-builder-aarch64` desde `Containerfile.aarch64`, con `--platform linux/arm64` y base `docker.io/menci/archlinuxarm:latest`. Instala el `archiso` de extra de Arch (es `arch=any`); Arch Linux ARM no lo empaqueta.
- En un host aarch64 el contenedor es nativo. En x86_64 corre con qemu-user, que tiene que estar registrado en binfmt con la bandera `C` (credentials). Sin ella, `sudo` dentro de makepkg falla con `effective uid is not 0`. La entrada que instala Debian (`flags: POF` en `/proc/sys/fs/binfmt_misc/qemu-aarch64`) no vale.
- La imagen fija `PKGEXT='.pkg.tar.zst'` en `/etc/makepkg.conf.d/churros.conf`, porque Arch Linux ARM usa `.pkg.tar.xz` por defecto.
- Cargo compila en `rust/target/container-aarch64` y los paquetes locales van a `archiso/packages/aarch64/`.

Para volver a registrar qemu-aarch64 con las banderas `F` y `C` (como root; `echo` deja las secuencias `\x` para que las decodifique el kernel, `printf '%b'` no sirve):

```bash
echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-aarch64
echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:FPOC' | sudo tee /proc/sys/fs/binfmt_misc/register
```

Con `update-binfmts` (si existe `/usr/share/binfmts/qemu-aarch64`) o con systemd-binfmt (`/etc/binfmt.d/qemu-aarch64.conf`) el cambio es el mismo: las flags tienen que incluir `F` y `C`. `./churros doctor --arch arm64` muestra los comandos. `./install-deps.sh --arch arm64` instala qemu-user-static, pero no cambia las flags que haya dejado la distro.

## Otros scripts de `scripts/`

| Script | Cuándo se usa |
|--------|---------------|
| `build-churros-release.sh [x86_64\|aarch64\|i686]` | A mano, al publicar. Genera en `release/<arch>/` el bundle OTA `churros-utils-<versión>-<arch>.tar.zst`, sus copias por edición y `updates.json`. Compila para la arquitectura del equipo. Ver [Release](release.md). |
| `build-i18n.sh` | A mano; `./churros build` no lo ejecuta. Regenera los `.mo` versionados en `archiso/airootfs/usr/share/locale/` a partir de `po/*.po`. Hoy ningún componente carga ese catálogo. |

## Limpiar

```bash
./churros clean
```

Borra `work/` y `out/` (incluidas las ISO) y los artefactos generados en `archiso/airootfs/`. No borra `vm/` ni el repositorio local `archiso/packages/`.

## Errores comunes

### Faltan herramientas de ArchISO

Ejecuta `./churros doctor`. En Arch: `sudo pacman -S --needed archiso grub dosfstools mtools squashfs-tools libisoburn`. En otra distro: `./churros build --container`.

### Permisos en `work/` u `out/`

Quedan de un build interrumpido con `sudo`. `./churros clean` los borra.

### Falla la compilación Rust

```bash
./churros rust                 # contenedor Arch, igual que la CI
./churros rust --host          # en este equipo (Arch al día)
./churros rust -p <crate>      # solo un crate
```

### `wrong architecture` en pacstrap

Hay paquetes locales compilados para otra arquitectura. Construye en un host (o contenedor) de la arquitectura de la ISO.

### Otros fallos de `mkarchiso`

Revisa su salida: suele ser un paquete que ya no existe en los repositorios, una ruta mal escrita o un fichero de configuración inválido.

## CI

| Workflow | Dónde corre | Cuándo | Qué hace |
|----------|-------------|--------|----------|
| `ci.yml` | `ubuntu-latest` | push a `main` y PR | `./churros check`, `node scripts/test-polkit-rules.js`, `python3 scripts/test-privileged-helpers.py` y `cargo test -p churros-services` (sin GTK) |
| `polkit.yml` | `ubuntu-latest`, contenedor `archlinux:latest` | push a `main` y PR | `scripts/test-polkit-pkexec.sh` contra polkitd y pkexec reales |
| `rust.yml` | imagen del `Containerfile` en `ubuntu-latest` (`archlinux:latest`) y en `ubuntu-24.04-arm` (`menci/archlinuxarm`) | push a `main`, PR, cada lunes y a mano | Construye la imagen, comprueba que trae las herramientas del build de la ISO (solo x86_64) y ejecuta `./churros rust`: build, tests y clippy (los avisos de clippy no hacen fallar el job) |
| `iso-arm64.yml` | `ubuntu-24.04-arm`, `Containerfile.aarch64` | a mano y en PR que tocan el perfil arm64 | `./churros build --container --arch arm64` y sube la ISO como artefacto (7 días). No es un check obligatorio |

Las apps GTK no se compilan directamente en `ubuntu-latest`: activan la feature `v4_18` de gtk4-rs, que exige GTK ≥ 4.18, y Ubuntu 24.04 trae GTK 4.14. Por eso `rust.yml` usa la imagen Arch, el mismo entorno en el que se construye la ISO x86_64.

La compilación ARM64 corre en un runner arm64 nativo y no con `cargo check --target aarch64-unknown-linux-gnu` desde x86_64, porque glib-sys y gtk4-sys buscan con pkg-config las bibliotecas de aarch64.
