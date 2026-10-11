# VM (Virtual Machine)

Este documento describe la máquina virtual de desarrollo usada para probar ChurrOS sin instalarlo en hardware real.

ChurrOS utiliza **QEMU** con KVM para ejecutar la ISO en una VM con UEFI. El objetivo es ofrecer un entorno de pruebas reproducible y rápido.

---

# Overview

El comando principal es:

```bash
./churros run
```

Sin `--arch`, `run` usa la arquitectura del equipo, igual que `./churros build`.
Para validar la ISO ARM64 en un host x86_64:

```bash
./churros doctor --arch arm64          # qemu-user-static + binfmt
./churros build --container --arch arm64
./churros run --arch arm64 --fresh
```

El build corre entero dentro de un contenedor Arch Linux ARM (`Containerfile.aarch64`, `--platform linux/arm64`). En x86_64 eso necesita qemu-user-static con binfmt registrado y la bandera `C` (credentials). Sin `C`, el kernel calcula las credenciales del intérprete y no las del binario emulado: `sudo` dentro de makepkg se queda con el euid del usuario `builder` y falla con `effective uid is not 0`. La entrada que instala Debian (`flags: POF` en `/proc/sys/fs/binfmt_misc/qemu-aarch64`) no vale. `./churros doctor --arch arm64` lo comprueba. Para registrarla de nuevo, como root:

```bash
echo -1 | sudo tee /proc/sys/fs/binfmt_misc/qemu-aarch64
echo ':qemu-aarch64:M::\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x02\x00\xb7\x00:\xff\xff\xff\xff\xff\xff\xff\x00\xff\xff\xff\xff\xff\xff\xff\xff\xfe\xff\xff\xff:/usr/bin/qemu-aarch64-static:FPOC' | sudo tee /proc/sys/fs/binfmt_misc/register
```

`echo` deja las secuencias `\x` como texto: es el kernel quien las decodifica. `printf '%b'` las convierte antes y mete NUL en el magic; el registro queda truncado y pasa a casar con cualquier ELF de 64 bits.

Si existe `/usr/share/binfmts/qemu-aarch64`, lo mismo se hace con `update-binfmts --unimport qemu-aarch64` y `--import` después de añadir `C` a las flags de la plantilla. Con systemd-binfmt, se copia `/usr/lib/binfmt.d/qemu-aarch64.conf` a `/etc/binfmt.d/qemu-aarch64.conf`, las flags pasan a `FPOC` (tienen que incluir `F` y `C`) y se reinicia `systemd-binfmt`. `./install-deps.sh --arch arm64` instala el paquete, pero no cambia unas flags que la distro haya dejado sin `C`. En un host aarch64 el mismo contenedor es nativo y no hace falta emulación.

La imagen aarch64 escribe `PKGEXT='.pkg.tar.zst'` en `/etc/makepkg.conf.d/churros.conf`. ALARM trae `.pkg.tar.xz`; con esa extensión el build no encontraba el paquete de Calamares y lo recompilaba cada vez. Los scripts buscan `*.pkg.tar.*`, así que un paquete `.xz` que ya esté en `archiso/packages/aarch64/` también se reutiliza.

QEMU del guest ARM usa TCG en un host x86_64 (no hay KVM para aarch64). La máquina es `virt`: no tiene IDE ni teclado PS/2, así que el CD va por virtio-scsi, el disco por virtio-blk y el teclado por USB. La consola serie es PL011 (`ttyAMA0` en el kernel; el log sigue en `vm_serial.log`). CODE y VARS del firmware pflash tienen que medir lo mismo. `run` usa el primer par en el que ambos ficheros existen y miden igual (`AAVMF_CODE.fd` con `AAVMF_VARS.fd`, `QEMU_CODE.fd` con `QEMU_VARS.fd`, y en x86 `OVMF_CODE.4m.fd` con `OVMF_VARS.4m.fd`). Si solo está el `QEMU_EFI.fd` crudo, rellena copias a 64 MiB. `run` elige la ISO cuyo nombre lleva la arquitectura, para no arrancar una ISO x86_64 que haya quedado en `out/`.

Este script vive en `scripts/cli/run.sh` y se encarga de:

1. Buscar la última ISO en `out/`.
2. Si no existe, ejecutar `./churros build` automáticamente.
3. Crear un disco persistente si es la primera vez.
4. Lanzar QEMU con la configuración adecuada.

Flags opcionales:

| Flag | Descripción |
|------|-------------|
| `--nokvm` | Desactiva KVM y emula por software (CPU de 2 hilos, q35 sin `accel`). |
| `--fresh` | Borra `vm/OVMF_VARS.fd` antes de arrancar para que OVMF parta limpio y arranque desde el CD-ROM en vez del disco. Útil tras instalar ChurrOS en la VM y necesitar probar de nuevo la ISO live. |
| `--clean` | Borra `vm/ChurrOS.qcow2` y `vm/OVMF_VARS.fd` antes de arrancar (disco + variables EFI). |
| `--arch arm64` | Ejecuta la ISO `*aarch64*.iso` con `qemu-system-aarch64`, máquina `virt`, CPU `cortex-a72` (o KVM si el host ya es aarch64), CD virtio-scsi y teclado USB. Usa `vm/ChurrOS-arm64.qcow2` y `vm/OVMF_VARS_arm64.fd`. |

> **Consejo:** Si acabas de instalar ChurrOS en la VM, OVMF guarda la entrada `Boot0009 "ChurrOS"` en `OVMF_VARS.fd`, así que el siguiente arranque dirá `BdsDxe: starting Boot0009 "ChurrOS"` y entrará al sistema instalado. Ejecuta `./churros run --fresh` para arrancar limpio del CD-ROM, o simplemente `rm vm/OVMF_VARS.fd`.

Los archivos de la VM se guardan en `vm/`:

```text
vm/
├── ChurrOS.qcow2    # Disco persistente (64 GB)
└── OVMF_VARS.fd     # Variables UEFI (no se commitea)
```

Estos archivos están listados en `.gitignore` (junto con `*.qcow2`) para evitar que se suban al repositorio. Cada desarrollador genera los suyos localmente.

---

# QEMU Configuration

El script `scripts/cli/run.sh` lanza QEMU con los siguientes parámetros:

| Parámetro | Valor | Significado |
|-----------|-------|-------------|
| `-machine` | `q35,accel=kvm` | Chipset moderno con virtualización |
| `-cpu` | `host` | Pasa todas las instrucciones del CPU al guest |
| `-smp` | `4` | 4 cores con KVM (2 cores sin KVM) |
| `-m` | `4096` | 4 GB de RAM |
| `-device virtio-vga-gl` | `-display gtk,gl=on,show-cursor=on` | Gráficos 3D acelerados por hardware con cursor visible |
| `-device usb-tablet` | — | Puntero absoluto para ratón sin captura rígida |
| `-device intel-hda -device hda-duplex` | — | Audio PipeWire en el guest conectado al host |
| `-device virtio-serial-pci ...` | `qemu-vdagent,clipboard=on` | Canal de portapapeles y ratón bidireccional vía spice-vdagent |
| `-drive if=pflash,...readonly=on,file=...` | `/usr/share/edk2/x64/OVMF_CODE.4m.fd` | Firmware UEFI (código) |
| `-drive if=pflash,file=...` | `vm/OVMF_VARS.fd` | Variables UEFI (modificable) |
| `-drive file=...format=qcow2,if=virtio` | `vm/ChurrOS.qcow2` | Disco persistente (64 GB) |
| `-cdrom` | la última ISO en `out/` | CD Live |
| `-boot` | `order=c` | Arranca desde disco (o CD si fresh) |

## UEFI

Se usa OVMF (Open Virtual Machine Firmware) para que la VM arranque en modo UEFI, igual que la mayoría de PCs modernos. En UEFI la ISO usa GRUB (`uefi.grub`); en BIOS legacy usa Syslinux.

Los dos archivos de firmware:

- `OVMF_CODE.4m.fd` (de `/usr/share/edk2/x64/`) — código del firmware, solo lectura.
- `vm/OVMF_VARS.fd` — variables UEFI (boot order, secure boot, etc). Se copia del CODE en el primer arranque y se modifica por el firmware en runtime.

## Disk

El disco persistente es un `qcow2` de 64 GB. Se crea con `qemu-img create -f qcow2` la primera vez que se ejecuta `./churros run`. Permite:

- Instalar paquetes en la VM sin perderlos al apagar.
- Probar el instalador de ChurrOS.
- Guardar configuraciones de prueba.

Para resetear la VM, basta con borrar `vm/ChurrOS.qcow2` y `vm/OVMF_VARS.fd`. La próxima ejecución los regenerará.

## ISO Detection

```bash
ISO=$(find out -name "*.iso" | head -n1)
```

El script toma la primera ISO que encuentra en `out/` (orden alfabético). Si la ISO tiene fecha en el nombre (`ChurrOS-2026.07-x86_64.iso`), la última será la más reciente.

---

# Requirements

Para que `./churros run` funcione, el host necesita:

| Paquete | Obligatorio | Notas |
|---------|-------------|-------|
| `qemu-full` | ✅ | QEMU con todos los backends |
| `edk2-ovmf` | ✅ | Firmware UEFI (`/usr/share/edk2/x64/OVMF_CODE.4m.fd`) |
| KVM habilitado en el kernel | ✅ | `lsmod \| grep kvm` debe mostrar `kvm_intel` o `kvm_amd` |
| `/dev/kvm` accesible | ✅ | El usuario debe pertenecer al grupo `kvm` |

Ver `docs/getting-started.md` para las instrucciones de instalación.

---

# Troubleshooting

## "Could not access KVM kernel module"

KVM no está disponible. Soluciones:

```bash
# Cargar el módulo
sudo modprobe kvm_intel   # o kvm_amd para AMD

# Comprobar que el dispositivo existe
ls -la /dev/kvm

# Añadir tu usuario al grupo kvm si no tienes permisos de lectura/escritura
sudo usermod -aG kvm $USER
# Cierra sesión y vuelve a entrar
```

### "Virtualization (VT-x/AMD-V) is DISABLED in BIOS/UEFI"

Si `./churros doctor` o `./churros run` indican que la virtualización está desactivada:
1. Reinicia tu equipo y entra en la configuración de la BIOS/UEFI (normalmente pulsando `F2`, `F12`, `Del` o `Esc` al encender).
2. Busca la sección de configuración de CPU o Seguridad (`Advanced`, `CPU Configuration` o `System Configuration`).
3. Activa la opción de virtualización:
   - Para procesadores Intel: **Intel Virtualization Technology** (VT-x) o **Intel VMX**.
   - Para procesadores AMD: **SVM Mode** (Secure Virtual Machine) o **AMD-V**.
4. Guarda los cambios (`F10`) y reinicia. Al volver a entrar, `/dev/kvm` estará disponible.


## "OVMF_CODE.4m.fd not found"

El paquete `edk2-ovmf` no está instalado:

```bash
sudo pacman -S edk2-ovmf
```

## "No ISO found"

No hay ISOs en `out/`. Ejecuta primero:

```bash
./churros build
```

## La VM arranca pero no muestra nada

Si la pantalla queda en negro, prueba a quitar `-cpu host` y usar `-cpu kvm64` o un modelo genérico. Algunos CPUs exponen instrucciones que el firmware de OVMF no soporta bien.

También puedes añadir `-vga qxl` para forzar una VGA compatible.

## Quiero reiniciar la VM desde cero

```bash
./churros clean
rm -rf vm
./churros run
```

Esto borra la ISO, el workdir de ArchISO y el disco persistente. La próxima ejecución regenera todo.

---

# Alternatives

Si no puedes usar KVM, la VM funcionará pero mucho más lenta. En ese caso:

- Reduce `-smp` a 2 cores.
- Reduce `-m` a 2048 MB.
- Usa `-cpu kvm64` en vez de `-cpu host`.
- No actives `-enable-kvm`.

Para una alternativa con interfaz gráfica, puedes usar **virt-manager** con la misma ISO. Solo tienes que crear una VM nueva, asignar 4GB RAM, 4 cores, y montar la ISO como CD-ROM.

---

# Future Work

- Script `./churros vm create` para generar la VM desde cero con parámetros personalizados.
- Snapshot automático antes de cada cambio importante.
- Red NAT para que la VM tenga acceso a internet en configuraciones aisladas.
- Carpetas compartidas vía virtio-9p o virtiofs.

# ARM64 QEMU Checklist

Ejecuta la validación en este orden después de construir la ISO aarch64:

- [ ] El menú GRUB aparece con el tema y la entrada Live.
- [ ] El sistema Live termina el arranque sin errores críticos en `vm_serial.log`.
- [ ] `niri` inicia; `llvmpipe` es aceptable si virgl no está disponible.
- [ ] `waybar`, `fuzzel`, `foot`, Welcome y los popups abren correctamente.
- [ ] `lscpu | grep Architecture` muestra `aarch64`.
- [ ] Calamares completa una instalación GPT/btrfs.
- [ ] El log de instalación contiene `grub-install --target=arm64-efi` y `grub-mkconfig`.
- [ ] `./churros run --arch arm64 --fresh` arranca el sistema instalado desde el disco.
- Script `./churros vm reset` para borrar solo la VM sin tocar `out/`.
