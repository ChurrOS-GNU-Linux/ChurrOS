# Boot

Este documento describe el sistema de arranque de la ISO Live de ChurrOS.

ChurrOS utiliza ArchISO, que genera automáticamente cargadores de arranque para BIOS y UEFI. Los cargadores soportados son **GRUB** (UEFI) y **Syslinux** (BIOS legacy).

Todas las entradas de menú de los cargadores están renombradas de "Arch Linux" a "ChurrOS Live" para mantener la identidad de la distribución.

---

# Overview

El sistema de arranque se distribuye en tres carpetas bajo `archiso/`:

```text
archiso/
├── grub/
│   ├── grub.cfg
│   └── loopback.cfg
├── efiboot/
│   └── loader/
│       ├── loader.conf
│       └── entries/
│           ├── 01-archiso-linux.conf
│           ├── 02-archiso-speech-linux.conf
│           └── 03-archiso-memtest86+x64.conf
└── syslinux/
    ├── syslinux.cfg
    ├── archiso_head.cfg
    ├── archiso_sys.cfg
    ├── archiso_sys-linux.cfg
    ├── archiso_pxe.cfg
    ├── archiso_pxe-linux.cfg
    ├── archiso_tail.cfg
    └── splash.png
```

El modo de arranque se define en `archiso/profiledef.sh` según la arquitectura de la ISO:

```bash
bootmodes=('bios.syslinux' 'uefi.grub')   # x86_64
bootmodes=('uefi.grub')                   # aarch64
```

Eso significa que en BIOS se usa Syslinux y en UEFI se usa GRUB. El bootmode `uefi.grub` hace que ArchISO genere el binario GRUB EFI (con `grub-mkstandalone`) y cree la imagen FAT de arranque El Torito. El archivo `grub/loopback.cfg` se usa para arrancar desde ISO por loopback.

En aarch64 el perfil no activa `uefi.systemd-boot`: ese modo y `uefi.grub` escriben los dos `EFI/BOOT/BOOTAA64.EFI`. Syslinux no existe en ARM. archiso pide un conjunto fijo de módulos GRUB; ALARM no publica todos bajo `arm64-efi`, así que el build deja solo los que existen como `/usr/lib/grub/arm64-efi/<mod>.mod`. El menú no carga `usbserial_*` cuando `grub_cpu` es `arm64`.

El kernel de Arch Linux ARM (`linux-aarch64`) instala `/boot/Image`, no `vmlinuz-linux`, y posee `/etc/mkinitcpio.d/linux-aarch64.preset`. Ese fichero no se copia antes de pacstrap. Tras instalar el paquete, `customize_airootfs.sh` pone el preset de archiso (`ALL_kver=/boot/Image`, imagen `initramfs-linux.img`) y vuelve a correr mkinitcpio. Los hooks `memdisk` y `archiso_pxe_*` no entran en ese initramfs: en ALARM no están syslinux ni `ipconfig` de pxe. `publish-aarch64-kernel` copia `Image` a `vmlinuz-linux-aarch64` e `initramfs-linux.img` a `initramfs-linux-aarch64.img` antes de que mkarchiso arme el arranque de la ISO, y otra vez en el sistema instalado (Calamares deja el preset en `initramfs-linux-aarch64.img` y un hook de pacman vuelve a publicar tras una actualización del kernel). El menú GRUB de la ISO elige esos nombres cuando `grub_cpu` es `arm64`, y la consola serie pasa a `ttyAMA0` (PL011 de la máquina `virt`). En x86_64 el menú y el preset siguen usando `vmlinuz-linux`, `initramfs-linux.img` y `ttyS0`, con los hooks pxe y memdisk.

---

# GRUB

**Archivos:** `archiso/grub/grub.cfg`, `archiso/grub/loopback.cfg`

El menú de GRUB ofrece las siguientes entradas:

| Entrada | Hotkey | Descripción |
|---------|--------|-------------|
| ChurrOS Live | — | Arranque normal |
| ChurrOS Live Accessibility | `s` | Arranque con `accessibility=on` (activa espeakup) |
| Run Memtest86+ (RAM test) | — | Test de memoria |
| UEFI Shell | — | Solo en UEFI |
| UEFI Firmware Settings | — | Solo en UEFI (vuelve a la BIOS) |
| System shutdown | — | Apaga el equipo desde GRUB |
| System restart | — | Reinicia el equipo desde GRUB |

La entrada principal está etiquetada como `id 'archlinux'` (mantiene el id interno de ArchISO para compatibilidad con scripts) pero el texto visible dice "ChurrOS Live".

El parámetro `archisobasedir=%INSTALL_DIR%` se sustituye en tiempo de compilación por `churros` (definido en `profiledef.sh` como `install_dir="churros"`).

La entrada de accesibilidad añade `accessibility=on` a la línea del kernel, lo que activa los servicios `livecd-alsa-unmuter.service` y `livecd-talk.service` descritos en `docs/live-services.md`.

GRUB también carga módulos para soportar distintos sistemas de archivos y modos de consola (serial, USB-serial).

---

# Tema GRUB del sistema instalado

**Archivos:** `branding/grub-theme/`

El GRUB del sistema **instalado** (vía Calamares) usa un tema propio con menú centrado:

- **Fondo**: `background.png` (copia de `ChurrOSDarkMinimal.png`, 1920×1080).
- **Menú**: centrado en pantalla, texto claro `#F8FAFC` sobre fondo oscuro `#111827`, selección con caja naranja redondeada `#F97316` (pixmap `select.png`).
- **Fuentes**: DejaVu Sans (`.pf2`) generadas con `grub-mkfont` (`scripts/build-grub-theme.sh`).

**Cómo llega al sistema instalado:**

1. `./churros build` regenera las fuentes si faltan (`build-grub-theme.sh`) y copia `branding/grub-theme` al airootfs.
2. En el arranque live, `customize_airootfs.sh` lo despliega en `/usr/share/churros/grub-theme/`.
3. Calamares (instancia `shellprocess@grub-theme`, tras el módulo `bootloader`) lo copia a `/boot/grub/themes/churros/`, añade `GRUB_THEME` a `/etc/default/grub`, regenera `/boot/grub/grub.cfg` con `grub-mkconfig` y reescribe las imágenes de `/boot` sin compresión Btrfs para que GRUB pueda leer el kernel.

`grubcfg.conf` usa `GRUB_TERMINAL_OUTPUT: "gfxterm"` para que el tema se renderice con gráficos.

El tema no usa `title-align` ni otras claves globales que `theme_set_string` de GRUB no reconoce (eso aborta la carga del tema). El título centrado es un `+ label` con `align = "center"`.

Con Btrfs + `compress=zstd`, GRUB suele fallar al leer `/@/boot/vmlinuz-linux` (`premature end of file`). Antes de unpackfs, `shellprocess@boot-nocow` marca `/boot` con `chattr +C` y `compression=none`. Tras el bootloader, `make-boot-grub-readable` reescribe vmlinuz/initramfs en un inodo nuevo sin CoW (copia completa; `cp -a` en Btrfs hace reflink y deja el archivo comprimido). Un hook de pacman (`91-churros-boot-grub-readable.hook`) lo vuelve a correr tras actualizar el kernel.

---

# systemd-boot

> **Nota:** systemd-boot ya no se usa en la ISO. Desde que se habilitó el bootmode `uefi.grub`, el arranque UEFI lo gestiona GRUB (mismo binario que también cubre el sistema instalado vía Calamares). Los archivos de `archiso/efiboot/` quedan obsoletos; no se incluyen en la ISO con el bootmode actual.

systemd-boot era el cargador usado en sistemas UEFI modernos (más rápido y sencillo que GRUB).

---

# Syslinux

**Archivos:** `archiso/syslinux/syslinux.cfg` + varios `archiso_*.cfg`

Syslinux se usa como cargador de BIOS legacy. La estructura está dividida en varios archivos:

| Archivo | Función |
|---------|---------|
| `syslinux.cfg` | Punto de entrada; redirige según el modo de arranque |
| `archiso_head.cfg` | Cabecera común (UI, splash) |
| `archiso_sys.cfg` | Menú para arranque desde disco/ISO local |
| `archiso_sys-linux.cfg` | Entradas de kernel para arranque local |
| `archiso_pxe.cfg` | Menú para arranque por red (PXE) |
| `archiso_pxe-linux.cfg` | Entradas de kernel para arranque PXE |
| `archiso_tail.cfg` | Pie común (submenu, utilidades) |
| `splash.png` | Imagen de fondo del menú |

El punto de entrada decide entre arranque PXE o local mediante `whichsys.c32`:

```text
DEFAULT select

LABEL select
COM32 whichsys.c32
APPEND -pxe- pxe -sys- sys -iso- sys

LABEL pxe
CONFIG archiso_pxe.cfg

LABEL sys
CONFIG archiso_sys.cfg
```

Si el medio es arrancable por red (PXE), se carga `archiso_pxe.cfg`. En cualquier otro caso (disco o ISO local), se carga `archiso_sys.cfg`.

---

# Boot Process

El proceso de arranque es el siguiente:

1. La BIOS/UEFI carga el cargador correspondiente (GRUB en UEFI, Syslinux en BIOS).
2. El cargador lee `archisobasedir` y `archisosearchuuid` para localizar la partición Live.
3. Carga el kernel (`vmlinuz-linux`) y el initramfs (`initramfs-linux.img`).
4. El initramfs monta el sistema squashfs raíz.
5. systemd arranca y los servicios live (ver `docs/live-services.md`) se inicializan.
6. Si `accessibility=on` está presente, se activan los servicios de accesibilidad.
7. greetd arranca, autologin como `churros` y se carga Niri.

---

# Building

No necesitas editar manualmente los archivos de los cargadores para regenerar la ISO: ArchISO los usa tal cual desde `archiso/`. Si modificas `grub.cfg`, por ejemplo, simplemente ejecuta:

```bash
./churros build
```

La nueva ISO incluirá los cambios.

---

# Customization

## Cambiar el nombre del menú

Edita los archivos correspondientes:

- GRUB: `archiso/grub/grub.cfg` (cadenas dentro de `menuentry`)
- Syslinux: `archiso/syslinux/archiso_sys-linux.cfg` (campo `LABEL` y `MENU LABEL`)

## Cambiar el splash

Para Syslinux/GRUB, reemplaza `archiso/syslinux/splash.png` con tu imagen (recomendado 640×480 o 800×600, formato PNG).

## Cambiar el timeout

- GRUB: `archiso/grub/grub.cfg` → `timeout=15`

---

# Troubleshooting

## La ISO no arranca en UEFI

Comprueba que tu firmware tenga activado el modo UEFI (no Legacy/CSM). Si el firmware solo soporta Legacy, la ISO arrancará con Syslinux.

## No aparece la entrada de accesibilidad

La entrada solo se activa si el paquete `espeakup` está en `archiso/packages.x86_64`. Ya está incluido por defecto.

## GRUB muestra "Arch Linux" en vez de "ChurrOS"

Verifica que `archiso/grub/grub.cfg` tenga las cadenas actualizadas. El id interno (`archlinux`) debe permanecer por compatibilidad, pero el texto visible debe decir "ChurrOS Live".

## Cambios en grub.cfg no aparecen

Recuerda que `archiso/airootfs/` es la fuente para `mkarchiso`. Si modificas archivos fuera de `archiso/`, no se incluirán.
