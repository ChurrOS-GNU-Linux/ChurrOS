# VM (máquina virtual)

`./churros run` (`scripts/cli/run.sh`) arranca la ISO en QEMU para probar ChurrOS sin instalarlo en hardware real. Usa KVM si `/dev/kvm` está disponible (si no, emulación por software) y firmware UEFI (OVMF en x86, AAVMF/QEMU_EFI en aarch64); la ISO i686 arranca por BIOS si no hay OVMF de 32 bits.

## Uso

```bash
./churros run
```

1. Toma de `out/` la ISO de la arquitectura pedida (`--arch`; por defecto la del equipo, igual que `./churros build`). Si hay varias, la de fecha más reciente.
2. Si no hay ninguna, pregunta si construirla (`./churros build --arch <arch>`, con `--container` para arm64 en un host que no es aarch64). Si respondes que no, termina.
3. Crea el disco persistente la primera vez.
4. Lanza QEMU.

| Flag | Descripción |
|------|-------------|
| `--nokvm` | Emulación por software aunque haya KVM. x86_64: q35 y 2 vCPU con el modelo de CPU por defecto de QEMU; i686: `qemu32` y 2 vCPU; aarch64: `cortex-a72` y 4 vCPU. |
| `--fresh` | Borra las variables UEFI de esa arquitectura antes de arrancar, para que el firmware arranque desde el CD en vez del disco. Útil después de instalar ChurrOS en la VM. |
| `--clean` | Borra el disco y las variables UEFI de esa arquitectura antes de arrancar. Conserva la ISO. |
| `--arch arm64` | ISO `*aarch64*.iso` con `qemu-system-aarch64`, máquina `virt`, CPU `cortex-a72` (o `host` con KVM si el equipo es aarch64), CD virtio-scsi y teclado USB. |
| `--arch i686` | ISO de 32 bits con `qemu-system-i386`, máquina `q35` y CPU `qemu32` (o `host` con KVM). Arranca por UEFI IA32 si hay OVMF de 32 bits y, si no, por BIOS (SeaBIOS). La ISO i686 no tiene sesión gráfica ni instalador (ver [Sistema de compilación](build-system.md#ediciones-y-arquitecturas)). |

Cada `./churros build` vacía `out/`. Para tener a la vez ISO de varias arquitecturas, cópialas de nuevo a `out/` después de construirlas.

> **Después de instalar en la VM:** el firmware guarda la entrada de arranque de ChurrOS en las variables UEFI, así que el siguiente arranque entra al sistema instalado. Ejecuta `./churros run --fresh` para volver a arrancar desde el CD.

## Ficheros de `vm/`

| Arquitectura | Disco (qcow2, 64 GiB) | Variables UEFI |
|--------------|-----------------------|----------------|
| x86_64 | `vm/ChurrOS.qcow2` | `vm/OVMF_VARS.fd` |
| aarch64 | `vm/ChurrOS-arm64.qcow2` | `vm/OVMF_VARS_arm64.fd` |
| i686 | `vm/ChurrOS-i686.qcow2` | `vm/OVMF_VARS_ia32.fd` |

En aarch64, si solo está instalado el `QEMU_EFI.fd` crudo, `run` crea además `vm/pflash-code.fd` y `vm/pflash-vars.fd` (copias rellenadas a 64 MiB).

`.gitignore` cubre `*.qcow2` y `vm/OVMF_VARS.fd`, pero no las variables de aarch64 e i686 ni los `pflash-*.fd`: no los añadas a un commit.

La salida serie de la VM va a `vm_serial.log`, en la raíz del repo.

## Parámetros de QEMU

En x86_64:

| Parámetro | Valor | Notas |
|-----------|-------|-------|
| `-machine` | `q35,accel=kvm` | Sin KVM: `q35`. |
| `-cpu` | `host` | Solo con KVM; sin KVM no se pasa `-cpu`. |
| `-smp` | `4` | 2 sin KVM. |
| `-m` | `4096` | 4 GiB de RAM. |
| `-device virtio-vga-gl` | `-display gtk,gl=on,show-cursor=on` | Niri necesita 3D (virgl). Sin `/dev/dri` en el host: `-device virtio-gpu` con `gl=off`, y Niri cae a llvmpipe. |
| `-device qemu-xhci -device usb-tablet` | — | Controlador USB y puntero absoluto. |
| `-device intel-hda -device hda-duplex` | — | Audio (x86_64 e i686). |
| `-device virtio-serial-pci` + `qemu-vdagent` | `clipboard=on` | Portapapeles compartido vía spice-vdagent. |
| `-drive if=pflash,readonly=on` | p. ej. `/usr/share/edk2/x64/OVMF_CODE.4m.fd` | Código del firmware UEFI. |
| `-drive if=pflash` | `vm/OVMF_VARS.fd` | Variables UEFI. |
| `-drive ...,format=qcow2,if=virtio` | `vm/ChurrOS.qcow2` | Disco persistente. |
| `-cdrom` | la ISO elegida en `out/` | CD Live. |
| `-boot` | `order=c` | Fijo. Con OVMF manda el orden guardado en las variables UEFI; por eso existe `--fresh`. |
| `-serial` | `file:vm_serial.log` | Consola serie. |

En aarch64, QEMU usa TCG en un host x86_64 (no hay KVM para aarch64). La máquina `virt` no tiene IDE ni teclado PS/2: el CD va por virtio-scsi, el disco por virtio-blk, el teclado por USB y la GPU es `virtio-gpu-gl-pci`. No hay audio. La consola serie es PL011 (`ttyAMA0` en el kernel) y sigue yendo a `vm_serial.log`.

## Firmware UEFI

`scripts/lib/ovmf.sh` busca un par de ficheros CODE + plantilla VARS en las rutas habituales de cada distro (`/usr/share/edk2/`, `/usr/share/OVMF/`, `/usr/share/AAVMF/`…):

- x86_64: el primer par que exista, por ejemplo `OVMF_CODE.4m.fd` + `OVMF_VARS.4m.fd`. CODE y VARS miden distinto, y es normal.
- aarch64: QEMU exige que las dos imágenes pflash midan lo mismo. `run` elige el primer par AAVMF/QEMU de igual tamaño o, si solo está el `QEMU_EFI.fd` crudo, rellena copias a 64 MiB.
- i686: OVMF de 32 bits si existe; si no, SeaBIOS.

En el primer arranque, las variables de `vm/` se copian de la plantilla VARS del firmware (no del CODE), y el firmware las modifica en cada arranque. Si su tamaño ya no coincide con la plantilla (por ejemplo, tras cambiar de firmware), `run` las regenera.

## Requisitos

`./install-deps.sh` instala lo necesario. `./churros doctor` comprueba QEMU y `/dev/kvm`, pero no el firmware UEFI:

| | Arch | Debian/Ubuntu | Fedora |
|---|------|---------------|--------|
| QEMU | `qemu-full` | `qemu-system-x86`, `qemu-system-arm`, `qemu-utils` | `qemu-system-x86`, `qemu-system-aarch64`, `qemu-img` |
| Firmware UEFI | `edk2-ovmf`, `edk2-aarch64` | `ovmf`, `qemu-efi-aarch64` | `edk2-ovmf`, `edk2-aarch64` |

KVM es opcional pero muy recomendable: sin él todo funciona, mucho más lento. Para usarlo, la virtualización tiene que estar activada en la BIOS/UEFI del equipo y tu usuario necesita leer y escribir `/dev/kvm` (grupo `kvm`).

## Problemas frecuentes

### `/dev/kvm` no existe o no tiene permisos

`./churros run` avisa `KVM acceleration: not available (using software emulation)` y sigue sin KVM. Para activarlo:

```bash
sudo modprobe kvm_intel   # o kvm_amd
ls -la /dev/kvm
sudo usermod -aG kvm $USER   # después, cierra sesión y vuelve a entrar
```

### "Virtualization (VT-x/AMD-V) is DISABLED in BIOS/UEFI"

Lo muestra `./churros doctor` cuando el procesador tiene la virtualización desactivada:

1. Reinicia y entra en la configuración de la BIOS/UEFI (normalmente con `F2`, `F12`, `Supr` o `Esc` al encender).
2. Busca la sección de CPU (`Advanced`, `CPU Configuration` o `System Configuration`).
3. Activa **Intel Virtualization Technology** (VT-x) en Intel o **SVM Mode** (AMD-V) en AMD.
4. Guarda (`F10`) y reinicia.

### "OVMF firmware not found"

Falta el firmware UEFI:

- Arch: `sudo pacman -S edk2-ovmf` (arm64: `edk2-aarch64`)
- Debian/Ubuntu: `sudo apt install ovmf` (arm64: `qemu-efi-aarch64`)
- Fedora: `sudo dnf install edk2-ovmf` (arm64: `edk2-aarch64`)

### "No ISO found"

No hay ISO de esa arquitectura en `out/`. Responde `y` para construirla, o ejecuta antes `./churros build` (con `--arch` si hace falta).

### La VM arranca pero la pantalla queda en negro

Prueba `./churros run --nokvm` (no usa `-cpu host`) y revisa `vm_serial.log`. Si el host no tiene `/dev/dri`, `run` ya usa `virtio-gpu` sin aceleración y Niri arranca con llvmpipe, más lento.

### Empezar de cero

`./churros run --clean` borra el disco y las variables UEFI y arranca con la ISO actual. Para empezar de cero también con la ISO:

```bash
./churros clean && rm -rf vm && ./churros build && ./churros run
```

## Alternativas

Para usar **virt-manager** con la misma ISO: crea una VM con 4 GiB de RAM y 4 núcleos, elige firmware UEFI (OVMF) y activa la aceleración 3D (vídeo Virtio con 3D y pantalla Spice con OpenGL), porque Niri la necesita.

## Mejoras posibles

- `./churros vm create` para crear la VM con parámetros propios.
- `./churros vm reset` para borrar solo la VM sin tocar `out/`.
- Snapshot automático del disco antes de cada cambio importante.
- Reenvío de puertos (por ejemplo SSH con `-nic user,hostfwd=tcp::2222-:22`) para probar la edición server. La red ya funciona: sin opciones de red, QEMU crea una NIC con backend `user` (NAT).
- Carpetas compartidas vía virtio-9p o virtiofs.

## Checklist ARM64 en QEMU

Después de construir la ISO aarch64, valida en este orden:

- [ ] El menú GRUB aparece con el tema y la entrada Live.
- [ ] El sistema Live termina el arranque sin errores críticos en `vm_serial.log`.
- [ ] `niri` inicia; `llvmpipe` es aceptable si virgl no está disponible.
- [ ] Noctalia (barra), el lanzador (`Mod+Space`), `foot`, Welcome y los popups abren.
- [ ] `lscpu | grep Architecture` muestra `aarch64`.
- [ ] Calamares completa una instalación GPT/btrfs.
- [ ] El log de instalación contiene `grub-install --target=arm64-efi` y `grub-mkconfig`.
- [ ] El sistema instalado arranca desde el disco de la VM (`vm/ChurrOS-arm64.qcow2`).

El build de la ISO aarch64 (contenedor, qemu-user y binfmt) está en [Sistema de compilación](build-system.md#iso-aarch64).
