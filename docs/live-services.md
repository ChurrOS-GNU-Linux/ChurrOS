# Servicios del Live

Este documento describe qué configura el entorno Live de ChurrOS: el script que prepara la imagen durante el build, el usuario live, las unidades systemd, los hooks de pacman, el orden de arranque y las utilidades `churros-*`.

Las unidades y hooks se incluyen mediante `archiso/airootfs/etc/systemd/system/` y `archiso/airootfs/etc/pacman.d/hooks/`. Calamares instala el airootfs en el sistema destino, así que las unidades pueden heredarse; `services-systemd.conf` y `shellprocess-cleanup.conf` deshabilitan los servicios exclusivos del Live y corrigen las máscaras que no deben quedar en la instalación.

---

## Vista general

```text
archiso/airootfs/etc/
├── NetworkManager/
│   └── conf.d/
│       └── 20-churros-dns.conf
├── resolv.conf -> /run/systemd/resolve/stub-resolv.conf
├── systemd/
│   ├── journald.conf.d/
│   │   └── volatile-storage.conf
│   ├── logind.conf.d/
│   │   └── do-not-suspend.conf
│   ├── resolved.conf.d/
│   │   └── archiso.conf
│   ├── system-generators/
│   │   └── systemd-gpt-auto-generator -> /dev/null
│   └── system/
│       ├── pacman-init.service
│       ├── etc-pacman.d-gnupg.mount
│       ├── choose-mirror.service
│       ├── livecd-alsa-unmuter.service
│       ├── livecd-talk.service
│       ├── churros-update.service
│       ├── churros-update.timer
│       ├── dbus-org.freedesktop.{ModemManager1,resolve1,timesync1}.service   (alias D-Bus)
│       ├── greetd.service.d/
│       │   └── plymouth.conf
│       ├── multi-user.target.wants/   (pacman-init, choose-mirror, livecd-talk,
│       │                               ModemManager, systemd-resolved)
│       ├── sysinit.target.wants/      (systemd-timesyncd, systemd-time-wait-sync)
│       ├── sound.target.wants/        (livecd-alsa-unmuter)
│       └── sockets.target.wants/      (pcscd.socket)
└── pacman.d/
    └── hooks/
        ├── 50-churros-snapshot.hook
        ├── 91-churros-boot-grub-readable.hook
        ├── 92-churros-xfce-x11-session.hook
        ├── uncomment-mirrors.hook
        └── zzzz99-remove-custom-hooks-from-airootfs.hook
```

Además, el script `customize_airootfs.sh` (en `branding/`, copiado a `airootfs/root/` durante el build) crea el usuario, habilita servicios y configura el escritorio.

---

## customize_airootfs.sh

**Fuente:** `branding/customize_airootfs.sh` (se copia a `archiso/airootfs/root/customize_airootfs.sh` en cada build; editar la copia no sirve).

Lo ejecuta mkarchiso dentro del chroot de la imagen, justo después de pacstrap y antes de copiar el kernel al arranque de la ISO y crear el squashfs. Se ejecuta **una vez, durante el build**: no se ejecuta al arrancar el Live. Lo que hace queda dentro del squashfs. Aviso: el mkarchiso de upstream lo marca como obsoleto ("customize_airootfs.sh is deprecated! Support for it will be removed in a future archiso version").

Pasos, en orden:

1. Copia `os-release` (a `/etc` y `/usr/lib`), `issue` y `motd` desde `/root/branding/files/`, y estampa la versión y la edición con `stamp-os-release.sh`.
2. Despliega el tema de GRUB del sistema instalado en `/usr/share/churros/grub-theme/` ([boot.md](boot.md)).
3. Crea el usuario live (`users.sh`, ver [Usuario live](#usuario-live)).
4. Habilita y enmascara servicios (`services.sh`, ver [services.sh](#servicessh)).
5. Activa `[multilib]` en `/etc/pacman.conf`.
6. Configura el escritorio (`desktop.sh`): copia `/etc/skel/.config` a `/home/churros/`, escribe las variables de sesión de la edición y, fuera de xfce y server, el `live.toml` de Noctalia (ver [desktop-config.md](desktop-config.md)).
7. Instala Calamares desde `/root/packages` con `bsdtar`, crea `calamares.desktop` y parchea el módulo DMgreetd para que use `cage` + `regreet` ([login-greeter.md](login-greeter.md)).
8. Solo en aarch64: instala el preset de mkinitcpio, regenera el initramfs y publica los nombres del kernel (`publish-aarch64-kernel`).
9. Limpia la caché de pacman (`cleanup.sh`).

---

## Usuario live

**Script:** `archiso/airootfs/root/scripts/users.sh`

```bash
groupadd -f autologin

useradd -m \
    -G wheel,audio,video,input,storage,network,autologin \
    -s /bin/zsh \
    churros

passwd -d churros

echo "churros ALL=(ALL:ALL) NOPASSWD: ALL" > /etc/sudoers.d/churros
echo 'Defaults:churros env_keep += "WAYLAND_DISPLAY XDG_RUNTIME_DIR ..."' >> /etc/sudoers.d/churros
chmod 440 /etc/sudoers.d/churros

usermod -a -G video,input,render,tty greeter   # si existe el usuario greeter
```

El usuario `churros`:

- Pertenece a `wheel`, `audio`, `video`, `input`, `storage`, `network` y `autologin`.
- Shell: zsh.
- Sin contraseña (`passwd -d` la vacía).
- `sudo` sin contraseña, conservando las variables de la sesión gráfica (`env_keep`) para que las apps lanzadas con sudo encuentren Wayland, X11 y D-Bus.
- Home: `/home/churros/`.

El Live corre en RAM: cualquier cambio se pierde al apagar. En el sistema instalado el usuario lo crea Calamares (módulo `users`) y el paso post-install borra `/etc/sudoers.d/churros` y ejecuta `userdel -r churros`.

---

## services.sh

**Script:** `archiso/airootfs/root/scripts/services.sh` (lo llama `customize_airootfs.sh` durante el build).

- **Enmascara** `getty@tty1.service` (el inicio de sesión lo hace greetd en VT7), `plymouth-start`, `plymouth-quit`, `plymouth-quit-wait`, `systemd-time-wait-sync` y `NetworkManager-wait-online`, para que el Live arranque rápido.
- **Habilita** `NetworkManager.service`, `greetd.service` y `ufw.service`, si la unidad existe.

El post-install de Calamares deshace en el sistema instalado las máscaras de espera de red y de hora (ver [Red y DNS](#red-y-dns)). `getty@tty1` sigue enmascarado también en el sistema instalado.

---

## Servicios

### pacman-init.service

**Path:** `archiso/airootfs/etc/systemd/system/pacman-init.service`

Inicializa el keyring de pacman al arrancar el Live.

```ini
[Unit]
Description=Initializes Pacman keyring
Requires=etc-pacman.d-gnupg.mount
After=etc-pacman.d-gnupg.mount time-sync.target
BindsTo=etc-pacman.d-gnupg.mount
Before=archlinux-keyring-wkd-sync.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/pacman-key --init
ExecStart=/usr/bin/pacman-key --populate

[Install]
WantedBy=multi-user.target
```

- `pacman-key --init` genera las claves locales.
- `pacman-key --populate` importa las claves oficiales de Arch Linux.
- Es necesario para usar pacman dentro del Live. El sistema instalado no lo usa (Calamares lo enmascara): inicializa su keyring con el paso `shellprocess@pacman-init` del instalador.

### etc-pacman.d-gnupg.mount

**Path:** `archiso/airootfs/etc/systemd/system/etc-pacman.d-gnupg.mount`

```ini
[Unit]
Description=Temporary /etc/pacman.d/gnupg directory

[Mount]
What=tmpfs
Where=/etc/pacman.d/gnupg
Type=tmpfs
Options=mode=0755,noswap
```

Monta `/etc/pacman.d/gnupg` como tmpfs. Esto evita que se generen claves persistentes dentro de la ISO: cada arranque genera claves nuevas, y al apagar se pierde todo (el sistema corre en RAM).

`pacman-init.service` requiere este mount y se bindea a él.

### choose-mirror.service

**Path:** `archiso/airootfs/etc/systemd/system/choose-mirror.service`

Permite seleccionar un mirror de pacman desde la línea de comandos del kernel (al arrancar la ISO).

```ini
[Unit]
Description=Choose mirror from the kernel command line
ConditionKernelCommandLine=mirror

[Service]
Type=oneshot
ExecStart=/usr/local/bin/choose-mirror

[Install]
WantedBy=multi-user.target
```

Solo se activa si la línea del kernel incluye `mirror=...`. El script `choose-mirror` lee el parámetro y regenera `/etc/pacman.d/mirrorlist`. Con `mirror=auto` usa el servidor de `archiso_http_srv` (arranque PXE por HTTP).

Uso típico:

```bash
# Al arrancar la ISO desde GRUB, edita la entrada y añade:
mirror=https://mirror.example.com/archlinux
```

El mirrorlist que escribe usa la estructura `$repo/os/$arch` de los mirrors de Arch Linux; los de Arch Linux ARM y Arch Linux 32 usan otra.

### livecd-alsa-unmuter.service

**Path:** `archiso/airootfs/etc/systemd/system/livecd-alsa-unmuter.service`

Quita el silencio de las tarjetas de sonido al iniciar, solo si `accessibility=on`.

```ini
[Unit]
Description=Unmute All Sound Card Controls For Use With The Live Arch Environment
Wants=systemd-udev-settle.service
After=systemd-udev-settle.service sound.target
ConditionKernelCommandLine=accessibility=on

[Service]
Type=oneshot
ExecStart=/usr/local/bin/livecd-sound -u

[Install]
WantedBy=sound.target
```

`livecd-sound -u` recorre todas las tarjetas de sonido y quita el silencio de sus controles. Sin esto, el lector de pantalla no tendría audio.

### livecd-talk.service

**Path:** `archiso/airootfs/etc/systemd/system/livecd-talk.service`

Activa el lector de pantalla espeakup, solo si `accessibility=on`.

```ini
[Unit]
Description=Screen reader service
After=livecd-alsa-unmuter.service
Before=getty@tty1.service
ConditionKernelCommandLine=accessibility=on

[Service]
Type=oneshot
TTYPath=/dev/tty13
ExecStartPre=/usr/bin/chvt 13
ExecStart=/usr/local/bin/livecd-sound -p
ExecStartPost=/usr/bin/chvt 1
ExecStartPost=systemctl start espeakup.service
StandardInput=tty
TTYVHangup=yes
TTYVTDisallocate=yes
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
```

Pasos:

1. Cambia a tty13 (consola virtual auxiliar).
2. `livecd-sound -p` permite al usuario elegir tarjeta de sonido con feedback auditivo.
3. Vuelve a tty1.
4. Inicia `espeakup.service`.

El paquete `espeakup` solo está en `archiso/packages.aarch64`. En las demás listas (x86_64, xfce, server, i686) el último paso falla y el modo accesible no lee nada.

### churros-update.service y churros-update.timer

**Path:** `archiso/airootfs/etc/systemd/system/churros-update.{service,timer}`

Timer de sistema que ejecuta `churros-update-auto` como root cada día a las 04:00 (ver [churros-update-auto](#churros-update-auto)). No está habilitado en el Live ni en las ediciones de escritorio; solo lo habilita `configure-server` en la edición server ([server.md](server.md)).

### getty@tty1

No hay autologin en tty1. `services.sh` enmascara `getty@tty1.service` y el inicio de sesión lo hace greetd en VT7 con `[initial_session]` ([login-greeter.md](login-greeter.md)).

---

## Drop-ins de systemd

### do-not-suspend.conf

**Path:** `archiso/airootfs/etc/systemd/logind.conf.d/do-not-suspend.conf`

Impide que el sistema se suspenda automáticamente en el Live. El usuario debe apagar manualmente cuando termine.

### volatile-storage.conf

**Path:** `archiso/airootfs/etc/systemd/journald.conf.d/volatile-storage.conf`

Configura journald para almacenar logs en RAM (tmpfs). Como el sistema es Live, no tiene sentido escribir logs al disco.

### greetd.service.d/plymouth.conf

**Path:** `archiso/airootfs/etc/systemd/system/greetd.service.d/plymouth.conf`

Hace que greetd arranque después de Plymouth y le pida salir (`plymouth quit`) antes de mostrar la sesión.

### Red y DNS

NetworkManager es el único gestor de interfaces en el Live y en la instalación. El perfil usa `wpa_supplicant` para Wi-Fi; no habilita `iwd` ni `systemd-networkd`, y no incluye perfiles DHCP `20-*.network` que compitan por las mismas interfaces.

`systemd-resolved` se mantiene habilitado como resolvedor DNS: `/etc/resolv.conf` apunta a `/run/systemd/resolve/stub-resolv.conf` y `NetworkManager/conf.d/20-churros-dns.conf` configura `dns=systemd-resolved` para que NetworkManager publique ahí los DNS recibidos.

Durante la instalación, `services-systemd.conf` deshabilita `iwd`, `systemd-networkd`, su socket de activación, su unidad wait-online y los servicios específicos de hipervisores. El perfil Live tampoco conserva el alias D-Bus `dbus-org.freedesktop.network1.service`. El paso post-install elimina perfiles y alias heredados de networkd, deshace las máscaras de Live para los servicios wait-online y de sincronización de hora, y habilita `NetworkManager-wait-online.service`. Así, `network-online.target` espera a NetworkManager en el sistema instalado, sin arrancar un segundo gestor de interfaces.

Los servicios de integración de Hyper-V, VirtualBox y VMware también quedan deshabilitados en la instalación para no arrastrar una activación específica del Live a todas las máquinas. En una VM, funciones como portapapeles, carpetas compartidas o ajustes de pantalla pueden requerir habilitar manualmente el servicio del hipervisor correspondiente; los paquetes disponibles no se eliminan.

---

## Hooks de pacman

### uncomment-mirrors.hook

**Path:** `archiso/airootfs/etc/pacman.d/hooks/uncomment-mirrors.hook`

```ini
[Trigger]
Operation = Install
Operation = Upgrade
Type = Package
Target = pacman-mirrorlist

[Action]
Description = Uncommenting HTTPS mirrors in /etc/pacman.d/mirrorlist...
When = PostTransaction
Depends = pacman-mirrorlist
Depends = sed
Exec = /usr/bin/sed -E -i 's/#(Server = https:)/\1/g' /etc/pacman.d/mirrorlist
```

Tras instalar o actualizar `pacman-mirrorlist`, descomenta automáticamente las líneas `Server = https://...`. Sin esto, el mirrorlist queda con todos los servidores comentados y pacman no puede descargar nada.

### zzzz99-remove-custom-hooks-from-airootfs.hook

**Path:** `archiso/airootfs/etc/pacman.d/hooks/zzzz99-remove-custom-hooks-from-airootfs.hook`

```ini
[Trigger]
Operation = Install
Operation = Upgrade
Operation = Remove
Type = Package
Target = *

[Action]
Description = Work around FS#49347 by removing custom pacman hooks that are only required during ISO build...
When = PostTransaction
Depends = sh
Depends = coreutils
Depends = grep
Exec = /bin/sh -c "rm -- $(grep -Frl 'remove from airootfs' /etc/pacman.d/hooks/)"
```

Workaround para el bug FS#49347: los hooks que contienen el comentario `# remove from airootfs!` se eliminan automáticamente al instalar o actualizar cualquier paquete. Esto evita que los hooks específicos del build se ejecuten en el Live cuando el usuario instale software.

El prefijo `zzzz99` en el nombre asegura que este hook se ejecute al final, después de los demás.

### 50-churros-snapshot.hook

Antes de cada transacción de pacman (instalar, actualizar o quitar) ejecuta `churros-snapshot create pacman-pre`. Si la raíz no es btrfs, solo avisa y la transacción sigue. Detalle en [rollback.md](rollback.md).

### 91-churros-boot-grub-readable.hook

Tras instalar o actualizar el kernel, el initramfs, el microcódigo, el tema de GRUB o el paquete `grub`, ejecuta `make-boot-grub-readable` para reescribir esas imágenes de `/boot` sin compresión btrfs, de modo que GRUB pueda leerlas ([boot.md](boot.md)).

### 92-churros-xfce-x11-session.hook

Cuando una actualización de `xfce4-session` vuelve a instalar `xfce-wayland.desktop` o `xfce.desktop`, ejecuta `fix-xfce-sessions`: borra la sesión Wayland de XFCE (exige labwc) y hace que `xfce.desktop` lance `churros-xfce-session` ([login-greeter.md](login-greeter.md)).

---

## Scripts heredados de archiso

### livecd-sound

**Path:** `archiso/airootfs/usr/local/bin/livecd-sound`

Script de gestión de audio. Opciones:

- `-u` / `--unmute` — quita el silencio de todas las tarjetas
- `-p` / `--pick` — permite elegir tarjeta con feedback auditivo
- `-h` / `--help` — ayuda

Usa `amixer` para controlar ALSA y genera `/etc/asound.conf` a partir de `/usr/local/share/livecd-sound/asound.conf.in`.

### choose-mirror

**Path:** `archiso/airootfs/usr/local/bin/choose-mirror`

Lee `mirror=` de la línea del kernel y regenera `/etc/pacman.d/mirrorlist`. El archivo original se guarda como `mirrorlist.orig`.

### Installation_guide

**Path:** `archiso/airootfs/usr/local/bin/Installation_guide`

```sh
exec xdg-open 'https://wiki.archlinux.org/title/Installation_guide'
```

Abre en el navegador la guía de instalación manual de Arch Linux. ChurrOS se instala con Calamares; esta guía solo sirve para una instalación manual de Arch.

---

## Utilidades de ChurrOS

ChurrOS incluye utilidades auxiliares en `/usr/bin/` y `/usr/local/bin/` para fondos, permisos, actualizaciones y temas.

### churros-apply-wallpaper

**Path:** `/usr/bin/churros-apply-wallpaper`

Aplica el fondo de pantalla según la sesión:

1. En XFCE, con `xfconf-query` (canal `xfce4-desktop`).
2. Si Noctalia está en marcha, con `noctalia msg wallpaper-set` (reintenta y, si falla, no arranca `swaybg`: los dos fondos se pisarían).
3. Sin Noctalia, con `swaybg` y, si falla, con `awww`.

Detecta los sockets `WAYLAND_DISPLAY` y `XDG_RUNTIME_DIR` aunque no se le pasen. Sin argumentos, lee la ruta guardada en `~/.config/churros/settings.json` o recurre a `/usr/share/churros/wallpapers/default.png`.

### churros-pick-image

**Path:** `/usr/bin/churros-pick-image`

Selector de imagen (fondos de pantalla, avatares). Prueba `zenity`, después `yad` y por último `Gtk.FileDialog` vía Python. Filtra JPG, JPEG, PNG, WEBP y GIF y devuelve la ruta elegida por stdout.

### churros-pkexec

**Path:** `/usr/bin/churros-pkexec`

Wrapper para ejecutar comandos con permisos de administrador utilizando Polkit sin requerir terminal interactiva. Permite a las aplicaciones de usuario ejecutar utilidades privilegiadas (como `timedatectl`, `churros-update-utils` o `churros-snapshot`) respetando las políticas de `/etc/polkit-1/rules.d/`. Si ya se ejecuta como root, lanza el comando directamente.

Hace `exec pkexec`: así el sujeto de polkit es la app que llama y la contraseña que piden las acciones `auth_admin_keep` se recuerda unos minutos entre llamadas. Los llamadores pasan la ruta absoluta del programa, porque la regla autoriza por ruta y argv exactos. Tabla de decisiones en [privileged-execution.md](privileged-execution.md#tabla-de-decisiones).

### churros-portal-start

**Path:** `/usr/bin/churros-portal-start`

Lo lanza Niri al arrancar la sesión. Exporta el entorno de la sesión (`WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS`, etc.) a systemd y a D-Bus, escribe `~/.config/xdg-desktop-portal/portals.conf` con `gtk` como backend y arranca `xdg-desktop-portal` y `xdg-desktop-portal-gtk` si no están en marcha. También fija Thunar como gestor de archivos por defecto.

### churros-update-utils

**Path:** `/usr/bin/churros-update-utils`

Comprueba y descarga actualizaciones del bundle de utilidades oficiales de ChurrOS desde el servidor de distribución (`https://download.churroslinux.org/churros/updates.json`).

El origen está **fijado en el binario** y el comando no acepta argumentos: una URL configurable por el usuario convertía esto en ejecución de root. Antes de extraer se valida:

- la versión y el nombre del fichero del manifiesto, contra expresiones regulares;
- el SHA-256 del paquete frente al anunciado en el manifiesto;
- la lista de miembros del tarball: solo ficheros regulares y directorios (sin enlaces simbólicos o duros, dispositivos ni FIFOs), sin rutas absolutas ni `..`, y solo en las rutas autorizadas: `usr/bin/churros-*`, `usr/local/bin/churros-*`, `usr/share/churros/`, `etc/churros-version`, `etc/churros-edition` y el hook `etc/pacman.d/hooks/50-churros-snapshot.hook`.

La extracción se hace en un directorio de stage y después se instala fichero a fichero: modo 0755 o 0644, temporal en el directorio de destino y `rename` atómico. Los directorios existentes no se tocan; antes, `cp -a` copiaba el modo 0700 del stage sobre `/` (#130).

El manifiesto se descarga antes de verificar su firma (#139). Si existe `/usr/share/churros/churros-release.pubkey`, el manifiesto debe venir firmado por minisign y la actualización se aborta si la firma no valida o si falta `minisign`. Sin clave publicada solo se avisa; que la firma sea obligatoria está pendiente (#139, #141).

### churros-theme

**Path:** `/usr/local/bin/churros-theme`

Escribe en `~/.cache/churros-theme/` ficheros de color con la paleta fija de ChurrOS para Waybar, foot, fuzzel y mako, y enlaza los de Waybar y foot en `~/.cache/wal/`. El argumento (la ruta de un fondo) solo aparece en el mensaje final: los colores no se calculan a partir de la imagen. No cambia entre tema claro y oscuro; eso lo hace `churros-settings` con `noctalia msg theme-mode-set`.

### churros-update-auto

**Path:** `/usr/local/bin/churros-update-auto`

Actualiza el sistema **sin preguntar**. Ejecuta, a través de `churros-pkexec`:

1. `pacman -Syu --noconfirm`
2. `flatpak update -y`
3. `churros-update-utils`

Escribe la salida en `/tmp/churros-update.log` y al terminar envía una notificación de escritorio con el resultado.

Lo lanzan dos timers con el mismo horario (cada día a las 04:00, con hasta 30 minutos de retraso aleatorio y `Persistent=true`):

- **Timer de usuario** (`/etc/skel/.config/systemd/user/churros-update.timer`), habilitado por defecto en el skel, así que lo tienen el usuario live y los usuarios del sistema instalado. Corre con los permisos del usuario: la regla polkit pide la contraseña de administrador para los tres pasos (`auth_admin_keep`), y sin un agente de polkit que la pida fallan (#142).
- **Timer de sistema** (`/etc/systemd/system/churros-update.timer`), solo en la edición server. Corre como root, así que actualiza sin intervención ([server.md](server.md)).

### churros-snapshot

**Path:** `/usr/local/bin/churros-snapshot`

Herramienta de administración para crear, listar, limpiar y restaurar snapshots Btrfs del sistema raíz (`@`) y de usuario (`@home`). La usan el hook de pacman (`50-churros-snapshot.hook`) y la interfaz gráfica de `churros-settings`. Detalles en [rollback.md](rollback.md).

---

## Orden de arranque

Resumen de cómo arranca la sesión. Lo que hace `customize_airootfs.sh` ya quedó dentro de la imagen al construirla y no corre aquí:

1. systemd monta `/etc/pacman.d/gnupg` (tmpfs).
2. `pacman-init.service` inicializa el keyring.
3. `choose-mirror.service` (si `mirror=` está en la línea del kernel) regenera el mirrorlist.
4. NetworkManager, `systemd-resolved` y `ufw` arrancan.
5. `livecd-alsa-unmuter.service` (si `accessibility=on`) quita el silencio del audio.
6. `livecd-talk.service` (si `accessibility=on`) intenta activar espeakup.
7. greetd arranca en VT7 y hace el autologin de `churros` con `[initial_session]`, que lanza la sesión de la edición: `niri`, `churros-xfce-session` (xfce y server) o `churros-pi-session` (pi). Ver [login-greeter.md](login-greeter.md).
8. En niri, Niri ejecuta su autostart (portales, agente polkit, Noctalia, `churros-welcome` y, si existe su `.desktop`, `churros-tour`). El fondo lo pinta Noctalia, no swaybg. El autostart de cada edición está en [desktop-config.md](desktop-config.md).

`/root/.automated_script.sh`, que ejecuta el parámetro `script=` del kernel, solo actúa cuando root inicia sesión en tty1 (lo llama `/root/.zlogin`). Con `getty@tty1` enmascarado eso no pasa en un arranque normal, así que `script=` no tiene efecto.

---

## Trabajo pendiente

- Mover la lógica de `services.sh` (que habilita NetworkManager, greetd y ufw) a unidades nativas de systemd.
- Documentar el orden de dependencias entre servicios (hoy está implícito en los `After=` y `Before=`).
- Internacionalizar los mensajes de los hooks.
