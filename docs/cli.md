# ChurrOS CLI

La CLI de ChurrOS es la herramienta oficial utilizada para desarrollar, construir y probar la distribución.

Su objetivo es simplificar el flujo de trabajo del desarrollador y evitar ejecutar múltiples comandos manualmente.

Toda tarea repetitiva debe integrarse en esta herramienta.

---

# Filosofía

La CLI busca que desarrollar ChurrOS sea tan sencillo como ejecutar un único comando.

En lugar de recordar comandos largos de ArchISO o QEMU, todo se centraliza en:

```bash
./churros
```

---

# Uso

```bash
./churros <comando> [opciones]
```

Ejemplo:

```bash
./churros build
./churros run --fresh
```

Los argumentos posteriores al subcomando se reenvían al script `scripts/cli/<comando>.sh`. Un archivo `.sh` en ese directorio no es un comando público hasta que se añade a la lista explícita del dispatcher `churros`.

---

# Comandos disponibles

## build

Construye una nueva imagen ISO de ChurrOS.

```bash
./churros build
./churros build --edition xfce
./churros build --edition kde
./churros build --edition server
./churros build --edition niri
```

Opciones:
- `--arch <x86_64|arm64>` (o `-a`): arquitectura de la ISO. Por defecto, la del equipo (`uname -m`); en un host x86_64 la ISO ARM se pide con `--arch arm64`. En aarch64 solo existe la edición niri. Un host que no es aarch64 no puede construir esa ISO fuera del contenedor.
- `--container`: construye dentro del contenedor Arch (podman, o docker si no hay podman; con `sudo` y `--privileged`). Sirve en cualquier distro y la ISO queda igualmente en `out/`. x86_64 usa `Containerfile`. `--arch arm64` usa `Containerfile.aarch64` (`--platform linux/arm64`): en x86_64 hace falta qemu-user-static con binfmt y la bandera `C`; en aarch64 el contenedor es nativo. Detalle en `docs/getting-started.md` y `docs/vm.md`.
- `--edition <niri|xfce|kde|server>` (o `-e`): Selecciona la edición de la ISO (por defecto: `niri`). La edición `server` instala un sistema sin escritorio, accesible por SSH.
  - `niri`: Compositor Wayland con tiling dinámico horizontal (Noctalia Shell, foot, Fuzzel, Mako).
  - `xfce`: Entorno de escritorio clásico X11 (XFCE 4, panel ChurrOS, xfwm4, xfce4-terminal).

Este comando realiza automáticamente:

- Comprobación pre-flight de dependencias críticas del host (grub, dosfstools, mtools, mkarchiso) antes de compilar para evitar fallos tardíos.
- Configuración de paquetes y dotfiles según la edición seleccionada.
- Copia de branding y tema GRUB al airootfs.
- Construcción de paquetes AUR locales si faltan (Calamares, python-pywal, yay, wlogout).
- Compilación de las apps Rust (`scripts/build-rust.sh`) y despliegue en `usr/bin/`.
- Limpieza del directorio temporal.
- Ejecución de ArchISO.
- Construcción de la imagen ISO en `out/`.

---

## run

Construye la ISO (si es necesario) y la inicia en una máquina virtual utilizando QEMU.

```bash
./churros run
./churros run --nokvm
./churros run --fresh
./churros run --clean
```

Este comando permite probar rápidamente los cambios realizados sin necesidad de crear una máquina virtual manualmente.

Flags opcionales (detalle en `docs/vm.md`):

- `--arch <x86_64|arm64>` — arquitectura de la ISO y de QEMU. Por defecto, la del equipo, igual que `build`. ARM usa `qemu-system-aarch64`, máquina `virt`, CD virtio-scsi (virt no tiene IDE) y consola `ttyAMA0`. Si no hay ISO de esa arquitectura y el host no es aarch64, el build automático lleva `--container`.
- `--nokvm` — emulación por software, sin KVM.
- `--fresh` — resetea `vm/OVMF_VARS.fd` para arrancar desde el CD-ROM.
- `--clean` — borra el disco de la VM y las variables EFI antes de arrancar.

Comportamiento de aceleración:
- Si `/dev/kvm` está disponible, usa `-machine q35,accel=kvm` y 4 cores.
- Si KVM no está disponible o la virtualización está desactivada en la BIOS, emite una advertencia explicativa con instrucciones de solución y utiliza fallback por software con `-cpu max` y 2 cores.

---

## clean

Elimina todos los archivos temporales generados durante la compilación.

```bash
./churros clean
```

Directorios y archivos eliminados:

```text
work/
out/
archiso/airootfs/ (artefactos temporales de build)
```

No elimina ningún archivo del código fuente.

---

## check

Ejecuta las comprobaciones estáticas del repositorio.

```bash
./churros check
```

Revisa:

- Sintaxis de los scripts Bash y ShellCheck a nivel de error.
- Sintaxis de todos los archivos Python.
- Paquetes duplicados en `archiso/packages.x86_64`.
- Que los comandos del autostart de Niri existan como binario, crate Rust desplegable o paquete de la ISO.
- Que `Exec=` / `TryExec=` de los `.desktop` resuelvan, y que las rutas absolutas existan en airootfs.
- Orden crítico de Calamares y que cada instancia `shellprocess` tenga su `.conf`.
- Que el branding de Calamares cargue (`componentName`, slideshow API 2, imágenes existentes).
- Que los paquetes de `scripts/build-aur.sh` figuren en `netinstall.yaml`.
- Que los archivos de traducción `po/*.po` compilen.

Termina con código 0 si todo pasa y 1 si algo falla. Los avisos de higiene del repositorio se informan pero no bloquean. No necesita construir la ISO ni permisos de root, y tarda unos segundos.

Es el mismo comando que ejecuta el CI en cada Pull Request (ver `.github/workflows/ci.yml`).

---

## rust

Compila y prueba las apps Rust (`rust/`) con los mismos pasos que el CI: `cargo build --workspace --all-targets`, `cargo test --workspace` y `cargo clippy` (sus avisos no fallan).

```bash
./churros rust                       # en el contenedor Arch (cualquier distro)
./churros rust -p churros-services   # solo un crate
./churros rust --host                # en este equipo (Arch al día)
```

Por defecto corre en el contenedor porque gtk4-rs y libadwaita-rs piden versiones que Debian, Ubuntu o Fedora no tienen. El CI (`.github/workflows/rust.yml`) ejecuta exactamente este comando.

---

## doctor

Comprueba que las herramientas del entorno de desarrollo estén instaladas (`mkarchiso`, `qemu-system-x86_64`, `xorriso`, `grub`, `dosfstools`, `mtools`, etc.) y verifica la aceleración por hardware KVM.

```bash
./churros doctor
./churros doctor --install    # o -i / -y: instala automáticamente dependencias faltantes
```

Características:
- Identifica el nombre del paquete exacto que provee cada comando faltante.
- Detecta la distro: propone `sudo pacman -S --needed ...`, `sudo apt-get install ...` o `sudo dnf install ...` con los nombres de paquete de cada una, y pregunta si instalarlos (`[S/n]`).
- Fuera de Arch no busca `mkarchiso` ni `makepkg`: recomienda `./churros build --container` y comprueba que haya podman o docker.
- Avisa si `rustc` es anterior a 1.85 (edition 2024).
- Diagnostica si el usuario carece de permisos sobre `/dev/kvm` o si la virtualización (`Intel VT-x` o `AMD SVM`) está deshabilitada en la BIOS/UEFI.


---

## apps

Abre las apps propias de ChurrOS en el host, sin construir la ISO ni QEMU.

```bash
./churros apps
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

Muestra información del proyecto y del entorno (versión, rama, arquitectura y directorios).

```bash
./churros info
```

---

## version

Muestra la versión actual de la CLI.

```bash
./churros version
```

---

## logo

Muestra el logotipo oficial de ChurrOS en la terminal.

```bash
./churros logo
```

---

# Flujo recomendado

Durante el desarrollo se recomienda utilizar la siguiente secuencia:

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

Realizar commit

↓

Push

---

# Diseño

La CLI está diseñada para crecer junto con el proyecto.

Cada nueva funcionalidad de desarrollo debe añadirse como un nuevo comando: un script `scripts/cli/<comando>.sh` y una entrada en la lista explícita de comandos públicos del dispatcher `churros`. Un `.sh` extra en ese directorio no queda expuesto solo por existir.

Esto evita depender de múltiples scripts independientes.

---

# Comandos planificados

Las siguientes funciones están previstas para futuras versiones.

## release

```bash
./churros release
```

Permitirá generar una versión oficial de ChurrOS.

Automáticamente:

- Construirá la ISO.
- Generará checksums.
- Creará la versión.
- Preparará el Release.

---

## package

```bash
./churros package
```

Permitirá construir paquetes propios de ChurrOS.

---

## update

```bash
./churros update
```

Actualizará las dependencias del proyecto.

---

## docs

```bash
./churros docs
```

Abrirá la documentación oficial.

---

# Futuro

La CLI evolucionará hasta convertirse en la herramienta central del desarrollo de ChurrOS.

El objetivo es que prácticamente todas las tareas relacionadas con la distribución puedan ejecutarse desde un único comando.

Con el tiempo se añadirán nuevas funciones para automatizar procesos de compilación, pruebas, publicación y mantenimiento del proyecto.