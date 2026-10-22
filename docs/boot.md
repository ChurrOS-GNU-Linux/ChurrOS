# Arranque

Este documento describe el sistema de arranque de la ISO Live de ChurrOS y el tema de GRUB del sistema instalado.

ChurrOS utiliza ArchISO, que genera los cargadores de arranque a partir del perfil `archiso/`. En x86_64 e i686 la ISO arranca con **Syslinux** en BIOS y con **GRUB** en UEFI; en aarch64 solo con GRUB (UEFI).

Las entradas de arranque de GRUB y de Syslinux, también las de PXE, muestran "ChurrOS Live", y los textos de ayuda de Syslinux hablan de ChurrOS. En `grub/loopback.cfg` quedan dos diferencias: la entrada principal dice "ChurrOS live" y la de accesibilidad, "ChurrOS Live Accesibility".

---

## Archivos

El arranque de la ISO sale de estas carpetas de `archiso/`:

```text
archiso/
├── grub/
│   ├── grub.cfg
│   └── loopback.cfg
├── syslinux/
│   ├── syslinux.cfg
│   ├── archiso_head.cfg
│   ├── archiso_sys.cfg
│   ├── archiso_sys-linux.cfg
│   ├── archiso_pxe.cfg
│   ├── archiso_pxe-linux.cfg
│   ├── archiso_tail.cfg
│   └── splash.png
└── mkinitcpio/
    └── aarch64/
        ├── archiso.conf
        └── linux-aarch64.preset
```

`archiso/efiboot/` (entradas de systemd-boot) sigue en el repositorio, pero ningún bootmode del perfil lo usa: mkarchiso solo lo lee con los bootmodes `uefi.systemd-boot`.

El modo de arranque se define en `archiso/profiledef.sh` según la arquitectura de la ISO:

```bash
bootmodes=('bios.syslinux' 'uefi.grub')   # x86_64
bootmodes=('uefi.grub')                   # aarch64
bootmodes=('bios.syslinux' 'uefi.grub')   # i686 (UEFI de 32 bits, IA32)
```

En BIOS se usa Syslinux y en UEFI se usa GRUB. El bootmode `uefi.grub` hace que ArchISO genere el binario GRUB EFI (con `grub-mkstandalone`) y cree la imagen FAT de arranque El Torito. El archivo `grub/loopback.cfg` se usa para arrancar desde la ISO por loopback.

---

## Particularidades por arquitectura

### aarch64

El perfil no activa `uefi.systemd-boot`: ese modo y `uefi.grub` escriben los dos `EFI/BOOT/BOOTAA64.EFI`. Syslinux no existe en ARM. archiso pide un conjunto fijo de módulos GRUB; ALARM no publica todos bajo `arm64-efi`, así que el build deja solo los que existen como `/usr/lib/grub/arm64-efi/<mod>.mod`. El menú no carga `usbserial_*` cuando `grub_cpu` es `arm64`.

El kernel de Arch Linux ARM (`linux-aarch64`) instala `/boot/Image`, no `vmlinuz-linux`, y posee `/etc/mkinitcpio.d/linux-aarch64.preset`. Ese fichero no se copia antes de pacstrap. Tras instalar el paquete, `customize_airootfs.sh` pone el preset de archiso (`archiso/mkinitcpio/aarch64/`: `ALL_kver=/boot/Image`, imagen `initramfs-linux.img`) y vuelve a correr mkinitcpio. Los hooks `memdisk` y `archiso_pxe_*` no entran en ese initramfs: en ALARM no están syslinux ni `ipconfig` de pxe.

`publish-aarch64-kernel` copia `Image` a `vmlinuz-linux-aarch64` e `initramfs-linux.img` a `initramfs-linux-aarch64.img` antes de que mkarchiso arme el arranque de la ISO, y otra vez en el sistema instalado (Calamares deja el preset en `initramfs-linux-aarch64.img` y un hook de pacman vuelve a publicar tras una actualización del kernel). El menú GRUB de la ISO elige esos nombres cuando `grub_cpu` es `arm64`, y la consola serie pasa a `ttyAMA0` (PL011 de la máquina `virt`). En x86_64 el menú y el preset siguen usando `vmlinuz-linux`, `initramfs-linux.img` y `ttyS0`, con los hooks pxe y memdisk.

### i686

i686 conserva Syslinux para BIOS. El arranque UEFI es de 32 bits (GRUB `i386-efi`) y lo aporta el mkarchiso de Arch Linux 32. GRUB usa los mismos nombres de kernel que x86_64 (`vmlinuz-linux`, `initramfs-linux.img`). La ISO i686 no integra Calamares y no tiene paquete `niri` (ver la cabecera de `archiso/packages.i686`).

---

## GRUB

**Archivos:** `archiso/grub/grub.cfg`, `archiso/grub/loopback.cfg`

El menú de GRUB ofrece estas entradas:

| Entrada | Hotkey | Cuándo aparece |
|---------|--------|----------------|
| ChurrOS Live | — | Siempre. Arranque normal |
| ChurrOS Live Accessibility | `s` | Siempre. Añade `accessibility=on` (ver abajo) |
| Run Memtest86+ (RAM test) | — | Solo en UEFI x86_64 y si la ISO lleva `memtest86+-efi` (listas `x86_64` y `xfce`) |
| UEFI Shell | — | Solo en UEFI y si la lista incluye `edk2-shell` (no está en las listas aarch64) |
| UEFI Firmware Settings | — | Solo en UEFI (abre la configuración del firmware) |
| System shutdown | — | Siempre. Apaga el equipo desde GRUB |
| System restart | — | Siempre. Reinicia el equipo desde GRUB |

La entrada principal está etiquetada como `id 'archlinux'` (mantiene el id interno de ArchISO) pero el texto visible dice "ChurrOS Live".

El parámetro `archisobasedir=%INSTALL_DIR%` se sustituye en tiempo de compilación por `churros` (definido en `profiledef.sh` como `install_dir="churros"`).

Las entradas de arranque local de GRUB y de Syslinux pasan `copytoram=n cow_spacesize=2G` (las de PXE, solo `cow_spacesize=2G`). El overlay de 256 MB por defecto no alcanza para la reserva de 500 MB de OSTree que hace Flatpak, y sin ese margen Bazaar no puede sincronizar Flathub.

La entrada de accesibilidad añade `accessibility=on` a la línea del kernel, lo que activa `livecd-alsa-unmuter.service` y `livecd-talk.service` (ver [live-services.md](live-services.md)). El lector de pantalla necesita el paquete `espeakup`, que hoy solo está en `archiso/packages.aarch64`: en las demás listas la entrada aparece, pero `livecd-talk` no consigue arrancar `espeakup.service`.

GRUB también carga módulos para distintos sistemas de archivos y para la consola serie (y USB-serie fuera de arm64).

---

## Tema GRUB del sistema instalado

**Archivos:** `branding/grub-theme/`

El GRUB del sistema **instalado** (vía Calamares) usa un tema propio con menú centrado. El GRUB de la ISO no lo usa.

- **Fondo**: `background.png` (copia de `ChurrOSDarkMinimal.png`, 1920×1080), sobre color `#111827`.
- **Menú**: centrado en pantalla, texto claro `#F8FAFC` y la entrada seleccionada en naranja `#F97316` y negrita. No hay caja de selección: `theme.txt` no usa `selected_item_pixmap_style` porque el pixmap se dibujaba en la entrada equivocada.
- **Fuentes**: DejaVu Sans (`.pf2`) generadas con `grub-mkfont` (`scripts/build-grub-theme.sh`).

**Cómo llega al sistema instalado:**

1. `./churros build` regenera las fuentes si faltan (`build-grub-theme.sh`) y copia `branding/grub-theme` al airootfs, en `/usr/share/churros/grub-theme/` (y en `/root/branding/`, desde donde `customize_airootfs.sh` lo vuelve a copiar dentro del chroot de mkarchiso). Todo ocurre durante el build: la ISO ya lo lleva.
2. Calamares (instancia `shellprocess@grub-theme`, tras el módulo `bootloader`) lo copia a `/boot/grub/themes/churros/`, añade `GRUB_THEME` a `/etc/default/grub`, regenera `/boot/grub/grub.cfg` con `grub-mkconfig` y reescribe las imágenes de `/boot` sin compresión Btrfs para que GRUB pueda leer el kernel.

`grubcfg.conf` usa `GRUB_TERMINAL_OUTPUT: "gfxterm"` para que el tema se renderice con gráficos.

El tema no usa `title-align` ni otras claves globales que `theme_set_string` de GRUB no reconoce (eso aborta la carga del tema). El título centrado es un `+ label` con `align = "center"`.

Con Btrfs + `compress=zstd`, GRUB suele fallar al leer `/@/boot/vmlinuz-linux` (`premature end of file`). Antes de unpackfs, `shellprocess@boot-nocow` marca `/boot` con `chattr +C` y `compression=none`. Tras el bootloader, `make-boot-grub-readable` reescribe vmlinuz/initramfs en un inodo nuevo sin CoW (copia completa; `cp -a` en Btrfs hace reflink y deja el archivo comprimido). Un hook de pacman (`91-churros-boot-grub-readable.hook`) lo vuelve a correr tras actualizar el kernel.

GRUB también es el cargador del sistema instalado, pero no es el mismo binario que el de la ISO: el de la ISO lo genera mkarchiso con `grub-mkstandalone` y el del sistema instalado lo instala Calamares con `grub-install`.

---

## Syslinux

**Archivos:** `archiso/syslinux/syslinux.cfg` + varios `archiso_*.cfg`

Syslinux se usa como cargador de BIOS legacy en x86_64 e i686. La estructura está dividida en varios archivos:

| Archivo | Función |
|---------|---------|
| `syslinux.cfg` | Punto de entrada; redirige según el modo de arranque |
| `archiso_head.cfg` | Cabecera común (UI, splash) |
| `archiso_sys.cfg` | Menú para arranque desde disco/ISO local |
| `archiso_sys-linux.cfg` | Entradas de kernel para arranque local |
| `archiso_pxe.cfg` | Menú para arranque por red (PXE) |
| `archiso_pxe-linux.cfg` | Entradas de kernel para arranque PXE |
| `archiso_tail.cfg` | Pie común (otro sistema, Memtest86+, HDT, reinicio, apagado) |
| `splash.png` | Imagen de fondo del menú (640×480) |

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

## Proceso de arranque

1. La BIOS/UEFI carga el cargador correspondiente (GRUB en UEFI, Syslinux en BIOS).
2. El cargador lee `archisobasedir` y `archisosearchuuid` para localizar la partición Live.
3. Carga el kernel (`vmlinuz-linux`) y el initramfs (`initramfs-linux.img`); en aarch64, `vmlinuz-linux-aarch64` e `initramfs-linux-aarch64.img`.
4. El initramfs monta el sistema squashfs raíz.
5. systemd arranca y los servicios live (ver [live-services.md](live-services.md)) se inicializan.
6. Si `accessibility=on` está presente, se activan los servicios de accesibilidad.
7. greetd (VT7) hace el autologin de `churros` y lanza la sesión de la edición (ver [login-greeter.md](login-greeter.md)).

---

## Construir

No necesitas editar manualmente los archivos de los cargadores para regenerar la ISO: ArchISO los usa tal cual desde `archiso/`. Si modificas `grub.cfg`, por ejemplo, ejecuta:

```bash
./churros build
```

La nueva ISO incluirá los cambios.

---

## Personalización

Estas recetas son para forks o pruebas locales. Los gráficos de arranque y el splash son identidad de marca y AGENTS.md los incluye en lo que no se modifica en este repositorio.

### Cambiar el nombre del menú

Edita los archivos correspondientes:

- GRUB: `archiso/grub/grub.cfg` y `archiso/grub/loopback.cfg` (cadenas dentro de `menuentry`)
- Syslinux: `archiso/syslinux/archiso_sys-linux.cfg` y `archiso/syslinux/archiso_pxe-linux.cfg` (`MENU LABEL` y `TEXT HELP`)

### Cambiar el splash

Solo Syslinux usa imagen de fondo: `archiso/syslinux/splash.png` (640×480, PNG). El GRUB de la ISO no tiene fondo.

### Cambiar el timeout

- GRUB: `archiso/grub/grub.cfg` y `archiso/grub/loopback.cfg` → `timeout=15` (segundos)
- Syslinux: `archiso/syslinux/archiso_sys.cfg` → `TIMEOUT 150` (décimas de segundo)

---

## Problemas frecuentes

### La ISO no arranca en UEFI

Comprueba que tu firmware tenga activado el modo UEFI (no Legacy/CSM). En x86_64 e i686, si el firmware solo soporta Legacy, la ISO arrancará con Syslinux. La ISO aarch64 solo arranca en UEFI.

### La entrada de accesibilidad no lee nada

La entrada aparece siempre. El lector de pantalla necesita `espeakup`, que hoy solo está en `archiso/packages.aarch64`; para usarlo en x86_64 hay que añadirlo a `archiso/packages.x86_64` y a las listas de edición.

### GRUB muestra "Arch Linux" en vez de "ChurrOS"

Verifica que `archiso/grub/grub.cfg` (y `loopback.cfg`) tengan las cadenas actualizadas. El id interno (`archlinux`) debe permanecer, pero el texto visible debe decir "ChurrOS Live".

### Los cambios en grub.cfg no aparecen

Comprueba que editaste `archiso/grub/grub.cfg` (o `loopback.cfg`) y no el `/boot/grub/grub.cfg` de un sistema instalado, que regenera `grub-mkconfig`. Reconstruye con `./churros build` y arranca con `./churros run --fresh` para que OVMF arranque desde el CD-ROM y no desde el disco de la VM.
