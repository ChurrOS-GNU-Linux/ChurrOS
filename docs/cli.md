# ChurrOS CLI

`./churros` es la herramienta de desarrollo de ChurrOS: construye la ISO, la arranca en QEMU, ejecuta las comprobaciones y abre las apps en el host.

---

## Uso

```bash
./churros <comando> [opciones]
./churros --help        # también -h, help o sin argumentos
```

Ejemplo:

```bash
./churros build
./churros run --fresh
```

El dispatcher `churros` se sitúa en la raíz del repositorio y reenvía los argumentos posteriores al subcomando a `scripts/cli/<comando>.sh`. Solo son comandos los de su lista explícita (`build`, `run`, `clean`, `check`, `test`, `rust`, `doctor`, `info`, `version`, `logo`, `apps` y `cluster`): un `.sh` más en ese directorio no queda expuesto por existir. Un comando desconocido muestra la ayuda y termina con código 1.

---

## Comandos disponibles

## build

Construye una imagen ISO de ChurrOS.

```bash
./churros build
./churros build --edition niri
./churros build --edition xfce
./churros build --edition server
./churros build --edition pi --arch arm64
./churros build --container
./churros build --container --arch arm64
./churros build --container --arch arm64 --edition pi
./churros build --arch i686
```

Opciones:

- `--edition <niri|xfce|server|pi>` (o `-e`, o `--edition=<valor>`; no distingue mayúsculas): edición de la ISO. Por defecto, `niri`.
  - `niri`: Wayland con tiling scrollable. Noctalia hace de barra, lanzador, notificaciones y OSD; terminal foot y wlogout como menú de sesión. Waybar, Fuzzel y Mako siguen instalados como alternativa.
  - `xfce`: escritorio clásico X11 (XFCE 4, panel ChurrOS, xfwm4, xfce4-terminal).
  - `server`: el sistema instalado no tiene escritorio y se administra por SSH. El Live arranca en XFCE para poder ejecutar el instalador gráfico; `configure-server` retira el escritorio al terminar la instalación.
  - `pi`: Raspberry Pi Lite, solo aarch64. Sesión labwc con Waybar. Experimental: no se publica ni se construye en la CI.
- `--arch <x86_64|arm64|i686>` (o `-a`, o `--arch=<valor>`; también acepta `aarch64` e `i386`…`i686`): arquitectura de la ISO. Por defecto, la del equipo (`uname -m`).
  - `arm64`: existen las ediciones `niri` y `pi`; cualquier otra termina con error. En un host que no es aarch64 hay que añadir `--container`; sin él, el build termina con error y muestra el comando correcto.
  - `i686`: repositorios de Arch Linux 32. Experimental: niri y noctalia no existen allí, así que la ISO no tiene sesión gráfica, y se omiten Calamares (falta `polkit-qt6`) y Bazaar. Los paquetes locales yay, wlogout y python-pywal tienen que estar compilados para i686. Construir para una arquitectura distinta de la del host solo muestra un aviso.
- `--container`: construye dentro del contenedor Arch (podman, o docker si no hay podman; con root real y `--privileged`). Sirve en cualquier distro y la ISO queda igualmente en `out/`. x86_64 usa `Containerfile`. `--arch arm64` usa `Containerfile.aarch64` (`--platform linux/arm64`): en x86_64 hace falta qemu-user-static con binfmt y la bandera `C`; en aarch64 el contenedor es nativo. Detalle en [Sistema de compilación](build-system.md#contenedor).

Pasos:

1. Comprueba que estén `mkarchiso`, `mksquashfs`, `xorriso`, `grub-mkstandalone`, `mkfs.fat`, `mcopy` y `mmd`. Si falta alguno, termina con error: en Arch muestra el `pacman -S` que lo instala y, fuera del contenedor, propone el mismo build con `--container`.
2. `[0/5]` Aplica la edición: si no es `niri`, sustituye `archiso/packages.<arch>` por `archiso/packages.<edición>.<arch>`. Escribe `/etc/churros-edition` en el airootfs y genera `etc/greetd/config.toml` con la sesión Live de la edición.
3. `[1/5]` Branding: genera el tema de GRUB, copia `customize_airootfs.sh` y `branding/files` al airootfs y escribe la versión (`VERSION`) y la edición en `os-release`.
4. `[2/5]` Paquetes locales: `scripts/build-calamares.sh` (recompila Calamares si falta o si cambian libpython o `installer/patches/`), `scripts/build-aur.sh` si falta python-pywal, yay o wlogout, y `scripts/build-bazaar.sh` (reutiliza el paquete si ya enlaza libdex ≥ 1.2). En i686 se omiten Calamares y Bazaar. Si hay Calamares, `installer/apply-calamares.sh` despliega su configuración y los paquetes se copian a `airootfs/root/packages/`.
5. `[3/5]` Compila las apps Rust (`scripts/build-rust.sh`) y despliega los binarios en `archiso/airootfs/usr/bin/`.
6. `[4/5]` Borra `work/` y `out/`.
7. `[5/5]` Expone el repositorio local en `/root/packages` del host y ejecuta `mkarchiso`. En aarch64 antes adapta el preset de mkinitcpio y la lista de módulos GRUB de `mkarchiso`. La ISO queda en `out/`.
8. `[6/6]` Borra `work/`. Al salir, haya ido bien o mal, restaura la lista de paquetes y la config de greetd, borra los ficheros generados en el airootfs y retira el enlace `/root/packages`.

El repositorio local está en `archiso/packages/` (x86_64 e i686) y en `archiso/packages/aarch64/` (ISO ARM).

---

## run

Arranca la ISO en una máquina virtual con QEMU.

```bash
./churros run
./churros run --nokvm
./churros run --fresh
./churros run --clean
./churros run --arch arm64
```

Busca en `out/` la ISO más reciente cuyo nombre lleva la arquitectura pedida. Si no hay ninguna, pregunta `Do you want to build ChurrOS? [y/N]`; con la respuesta por defecto no construye y termina. Si aceptas, ejecuta `./churros build --arch <arch>` (con `--container` para la ISO aarch64 en un host que no es aarch64).

Flags opcionales (detalle en [VM](vm.md)):

- `--arch <x86_64|arm64|i686>` (o `--arch=<valor>`) — arquitectura de la ISO y de QEMU. Por defecto, la del equipo, igual que `build`. ARM usa `qemu-system-aarch64`, máquina `virt`, CD virtio-scsi (virt no tiene IDE) y consola `ttyAMA0`. i686 usa `qemu-system-i386` y arranca por BIOS (SeaBIOS) o por UEFI IA32 si hay OVMF de 32 bits.
- `--nokvm` — emulación por software, sin KVM.
- `--fresh` — borra las variables EFI de la VM (`vm/OVMF_VARS.fd` en x86_64) para arrancar desde el CD-ROM.
- `--clean` — borra el disco de la VM y las variables EFI antes de arrancar.

Disco y firmware: `vm/ChurrOS.qcow2` (x86_64), `vm/ChurrOS-arm64.qcow2` y `vm/ChurrOS-i686.qcow2`, de 64 GiB, creados en el primer arranque. Las variables EFI de cada arquitectura se copian del firmware a `vm/OVMF_VARS.fd`, `vm/OVMF_VARS_arm64.fd` y `vm/OVMF_VARS_ia32.fd`. La salida serie va a `vm_serial.log`.

Aceleración:

- x86_64 e i686 con `/dev/kvm` legible y escribible: `-machine q35,accel=kvm`, `-cpu host` y 4 cores.
- x86_64 sin KVM o con `--nokvm`: emulación TCG con `-machine q35`, el modelo de CPU por defecto de QEMU y 2 cores. i686 en ese caso usa `-cpu qemu32`.
- aarch64: KVM solo si el host también es aarch64; si no, TCG con `-cpu cortex-a72`. En los dos casos, 4 cores.

Sin KVM, `run` indica que usa emulación por software pero no busca la causa. El diagnóstico (permisos de `/dev/kvm`, virtualización desactivada en la BIOS) lo hace `./churros doctor`.

---

## clean

Elimina los artefactos de la compilación.

```bash
./churros clean
```

Borra, con `sudo` cuando hace falta:

```text
work/                         (desmonta antes lo que haya quedado montado)
out/                          (se vuelve a crear vacío)
archiso/airootfs/etc/churros-edition
archiso/airootfs/root/customize_airootfs.sh
archiso/airootfs/root/branding/
archiso/airootfs/root/packages/
archiso/airootfs/etc/calamares/
archiso/airootfs/etc/polkit-1/rules.d/49-calamares.rules
archiso/airootfs/usr/bin/churros-welcome
archiso/airootfs/usr/bin/churros-settings
archiso/airootfs/usr/bin/churros-popup
archiso/airootfs/usr/bin/churros-control-center
archiso/airootfs/usr/share/churros/grub-theme/
```

No borra `archiso/airootfs/usr/bin/churros-tour`, que el build sí retira al terminar. No toca el código fuente, `vm/` ni los paquetes de `archiso/packages/`.

---

## check

Ejecuta las comprobaciones estáticas del repositorio.

```bash
./churros check
```

Revisa, por temas:

- Scripts: sintaxis de Bash, ShellCheck a nivel de error (los avisos de estilo solo se cuentan) y sintaxis de Python.
- Paquetes y ediciones: duplicados en `archiso/packages*.x86_64`, `archiso/packages.i686` y `archiso/packages.aarch64` (no revisa `packages.pi.aarch64`), el perfil archiso de cada arquitectura, que cada edición x86_64 esté cableada en `build.sh`, `stamp-os-release.sh` y `edition-session.sh`, y que `usr/share/churros/defaults/` coincida con el skel.
- Escritorio: los comandos que lanza Niri, su integración con Noctalia (atajos, fondo), Xwayland en Niri, los `Exec=`/`TryExec=` de los `.desktop` y la sesión X11 de XFCE. En esta sección de `check.sh` los comandos de Niri se resuelven contra `archiso/packages.aarch64` salvo que se pase otra arquitectura en `TARGET_ARCH` (por ejemplo, `TARGET_ARCH=x86_64 ./churros check`).
- Instalador: orden crítico de Calamares, configuración de cada `shellprocess`, branding (`componentName`, slideshow API 2, imágenes), la vista previa de `./churros apps calamares`, `finished.conf` y la libpython del paquete de Calamares.
- Arranque y Live: módulos GRUB de aarch64, firmware pflash de QEMU y login del Live, `initial_session` de greetd y el tamaño del overlay del Live (`cow_spacesize`).
- Sistema: snapshots Btrfs (rollback), extensión de los paquetes y binfmt de aarch64, versión de la distro (`VERSION`, `os-release` por edición).
- Ejecución privilegiada: la regla polkit, `scripts/test-polkit-rules.js`, `scripts/test-privileged-helpers.py` y `scripts/test-network-services.py`. Sin `node` o sin `zstd`, esas pruebas se omiten.
- `po/*.po`: que compilen con `msgfmt --check`. Es un catálogo heredado de la interfaz en Python; las apps Rust no usan gettext.
- Documentación: que los enlaces relativos de los `.md` versionados existan y que cada documento de `docs/` esté en [el índice](README.md).
- `tests/static` (ver [Pruebas](testing.md)): scripts por shebang, `file_permissions`, comandos de cada edición (no solo la de `TARGET_ARCH`), Calamares, unidades systemd, sintaxis de configuraciones, contrato de las apps Rust, un build en seco y que esta documentación no se desvíe del código.
- Higiene del repositorio: avisa si hay ficheros generados en git.

La lista completa está en `scripts/cli/check.sh`. Termina con código 0 si todo pasa y 1 si algo falla. Los avisos (`!`) se informan pero no bloquean. Con `CHURROS_STRICT=1` (o `CI=true`) una herramienta que falta o una prueba saltada cuentan como fallo. No construye la ISO ni necesita root, y tarda alrededor de un minuto. En cada pull request `ci.yml` lo ejecuta dentro de `./churros test`, y además `./churros test --mutations`.

---

## test

Ejecuta las capas de pruebas. Sin opciones es lo mismo que `./churros check`.

```bash
./churros test                  # capa estática (check.sh + tests/static)
./churros test --container      # tests/container en el contenedor Arch
./churros test --rust           # ./churros rust
./churros test --gui            # apps GTK en Broadway, en el contenedor (test-tour.py y test-gui-smoke.py)
./churros test --iso [ISO]      # auditoría del contenido de la ISO (por defecto, la última de out/)
./churros test --boot [ISO]     # arranque en QEMU y comprobaciones dentro de la sesión Live
./churros test --mutations      # autoprueba de la batería
```

Las capas se pueden combinar (`./churros test --iso --boot`). Detalle de cada una en [Pruebas](testing.md).

`--gui` es lo que `./churros rust` no ve: `cargo test` no abre ninguna ventana. Arranca cada app desplegada y cada popup compilados en release, como en la ISO, y ejecuta los tests de widgets del recorrido, sobre un `gtk4-broadwayd` privado. Si tocas `rust/`, ejecuta las dos.

En cada pull request, `ci.yml` ejecuta `./churros test` y `./churros test --mutations`. `rust.yml` ejecuta `./churros rust`, `./churros test --gui` y `./churros test --container` (en x86_64 y en arm64). `iso.yml` construye la ISO y ejecuta `--iso` y `--boot` cuando el PR toca lo que entra en la ISO.

---

## rust

Compila y prueba las apps Rust (`rust/`) con los mismos pasos que la CI: `cargo build --all-targets`, `cargo test` y `cargo clippy --all-targets` sobre el workspace, con `--locked`. Los avisos de clippy no hacen fallar el comando; un error de compilación sí.

```bash
./churros rust                       # en el contenedor Arch (cualquier distro)
./churros rust -p churros-services   # solo un crate (repetible; también --package)
./churros rust --host                # en este equipo (Arch al día)
```

Por defecto corre en el contenedor porque gtk4-rs y libadwaita-rs piden versiones que Debian, Ubuntu o Fedora no tienen. La CI (`.github/workflows/rust.yml`) ejecuta este comando en x86_64 y en arm64.

---

## doctor

Comprueba las herramientas del entorno de desarrollo y la aceleración KVM.

```bash
./churros doctor
./churros doctor --install    # también -i, --yes o -y: instala lo que falte sin la pregunta [S/n]
./churros doctor --arch arm64 # además, exige qemu-user aarch64 listo para el build ARM
```

Comprueba:

- En cualquier distro: `git`, `qemu-system-x86_64`, `qemu-system-i386`, `qemu-system-aarch64`, `qemu-img`, `sudo`, `python3`, `node`, `shellcheck`, `msgfmt` (gettext), `zstd`, `rustc` y `cargo`. Cuenta como fallo un `rustc` anterior a 1.85 (edition 2024). En Arch también `pkg-config`.
- En Arch, lo que necesita el build en el host: `mkarchiso`, `xorriso`, `mksquashfs`, `mcopy` y `mmd` (mtools), `mkfs.fat` (dosfstools), `grub-mkstandalone` y `mkinitcpio`. Podman o docker aparecen como opcionales. No comprueba `makepkg` ni `base-devel`.
- Fuera de Arch: recomienda `./churros build --container` y comprueba que haya podman o docker.
- En un host que no es aarch64: si qemu-user aarch64 está registrado en binfmt con la bandera `C`. Sin `--arch arm64` es solo un aviso; con `--arch arm64` cuenta como fallo y explica cómo registrarlo.
- `/dev/kvm`: si existe y tienes permiso (si no, propone añadirte al grupo `kvm`); si no existe, busca en el log del kernel si la virtualización está desactivada en la BIOS/UEFI.

En Arch, Debian/Ubuntu y Fedora, cada fallo indica el paquete que lo resuelve. Al final muestra el comando para instalarlos todos (`sudo pacman -S --needed`, `sudo apt-get install` o `sudo dnf install`) y, en una terminal interactiva, pregunta si ejecutarlo (`[S/n]`). Termina con código 1 si falta algo.

---

## apps

Abre las apps propias de ChurrOS en el host, sin construir la ISO ni QEMU. No se puede ejecutar como root.

```bash
./churros apps                  # ayuda
./churros apps doctor
./churros apps welcome
./churros apps settings
./churros apps control-center
./churros apps tour
./churros apps popup audio
./churros apps calamares
```

Los targets GTK (`welcome`, `settings`, `control-center`, `tour`, `popup`) se compilan desde `rust/`. Hace falta sesión gráfica y gtk4/libadwaita. Por defecto corren en modo preview: `HOME` es un directorio temporal y los comandos que cambian el sistema (volumen, red, energía, gsettings, pkill) no se ejecutan. Aparecen como `[churros-dev] blocked:` en stderr. `--live-host` desactiva ese aislamiento.

`calamares` copia la config del repo a un directorio temporal y lanza el instalador con `-c` sobre ese overlay: no escribe `/etc/calamares`, no usa `sudo`, no pide contraseña, no abre la página de particiones (eso dispara Polkit/KPMCore contra discos reales) y no aplica teclado ni zona horaria a esta sesión. El paso de instalar es un `sleep` (para ver el slideshow) y la página final no ofrece reiniciar. El overlay incluye `qml/` del paquete extraído. `--live-host` está prohibido con este target.

No sustituye `./churros run`.

---

## info

Muestra información del proyecto y del entorno: versión, rama, arquitectura, kernel y directorios.

```bash
./churros info
```

---

## version

Muestra el contenido del fichero `VERSION`, que es la versión de la distribución. La CLI no tiene una versión propia.

```bash
./churros version
```

---

## logo

Muestra el logotipo de ChurrOS en ASCII.

```bash
./churros logo
```

## cluster

Gestiona el cluster de compilación distribuida (distcc por SSH) que acelera la
compilación del kernel ChurrOSvyper. La configuración local va en
`cluster.conf` (plantilla: `cluster.conf.example`; no se versiona).

```bash
./churros cluster init      # crea cluster.conf desde la plantilla
./churros cluster scan      # detecta los nodos de la red
./churros cluster auth      # copia las llaves SSH a cada nodo
./churros cluster probe     # comprueba SSH, hardware y software de cada nodo
./churros cluster start     # arranca distccd en los nodos (stop para pararlo)
./churros cluster status    # estado de los workers e hilos totales
./churros cluster build     # compila el kernel con el cluster
./churros cluster monitor   # monitor de la compilación (distccmon)
```

`./churros build --cluster` usa el cluster para compilar el kernel cuando no
puede descargar el paquete precompilado.

---

## Añadir un comando

Un comando nuevo necesita un script `scripts/cli/<comando>.sh` y una entrada en la lista `PUBLIC_COMMANDS` del dispatcher `churros`. Si aparece en la ayuda, se añade también a `show_help` en el mismo fichero.

Un script nuevo cuenta como programa nuevo: antes de escribirlo, revisa la [regla para programas nuevos](principios.md#regla-para-programas-nuevos).
