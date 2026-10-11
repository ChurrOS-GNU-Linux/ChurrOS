# Live Services

Este documento describe los servicios systemd y los hooks de pacman que configuran el entorno Live de ChurrOS durante el arranque.

Las unidades y hooks se incluyen mediante `archiso/airootfs/etc/systemd/system/` y `archiso/airootfs/etc/pacman.d/hooks/`. Calamares instala el airootfs en el sistema destino, así que las unidades pueden heredarse; `services-systemd.conf` y `shellprocess-cleanup.conf` deshabilitan los servicios exclusivos del Live y corrigen las máscaras que no deben quedar en la instalación.

---

# Overview

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
│   └── system/
│       ├── pacman-init.service
│       ├── etc-pacman.d-gnupg.mount
│       ├── choose-mirror.service
│       ├── livecd-alsa-unmuter.service
│       └── livecd-talk.service
└── pacman.d/
    └── hooks/
        ├── uncomment-mirrors.hook
        └── zzzz99-remove-custom-hooks-from-airootfs.hook
```

Adicionalmente, el script `customize_airootfs.sh` (en `branding/`, copiado a `airootfs/root/` durante el build) orquesta la creación del usuario, habilitación de servicios y configuración del escritorio.

---

# Customization Script

**Path:** `archiso/airootfs/root/customize_airootfs.sh` (copiado desde `branding/customize_airootfs.sh`)

Este script es ejecutado por ArchISO al final del build, dentro del chroot. No se ejecuta en cada arranque.

```bash
cp /root/branding/files/os-release /etc/os-release
cp /root/branding/files/issue /etc/issue
cp /root/branding/files/motd /etc/motd

chmod 644 /etc/os-release
chmod 644 /etc/issue
chmod 644 /etc/motd

bash /root/scripts/users.sh
bash /root/scripts/services.sh
bash /root/scripts/desktop.sh
bash /root/scripts/cleanup.sh
```

Pasos:

1. Aplica branding (issue, motd, os-release).
2. Crea el usuario `churros` (`users.sh`).
3. Habilita servicios (`services.sh`).
4. Configura el escritorio (`desktop.sh`).
5. Limpia la cache de pacman (`cleanup.sh`).

Ver `docs/desktop-config.md` para más detalle sobre el usuario y la configuración del escritorio.

---

# Services

## pacman-init.service

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
- Necesario para que `pacman -Sy` funcione dentro del Live (por ejemplo, antes de instalar con `archinstall`).

## etc-pacman.d-gnupg.mount

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

## choose-mirror.service

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

Solo se activa si el kernel cmdline incluye `mirror=...`. El script `choose-mirror` lee el parámetro y regenera `/etc/pacman.d/mirrorlist`.

Uso típico:

```bash
# Al arrancar la ISO desde GRUB, edita la entrada y añade:
mirror=https://mirror.example.com/archlinux
```

Útil para entornos de prueba, redes restringidas o mirrors corporativos.

## livecd-alsa-unmuter.service

**Path:** `archiso/airootfs/etc/systemd/system/livecd-alsa-unmuter.service`

Desilencia las tarjetas de sonido al iniciar, solo si `accessibility=on`.

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

`livecd-sound -u` itera sobre todas las tarjetas de sonido y desilencia los controles. Sin esto, los lectores de pantalla (espeakup) no tendrían audio.

## livecd-talk.service

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

## getty@tty1.service.d/autologin.conf

**Path:** `archiso/airootfs/etc/systemd/system/getty@tty1.service.d/autologin.conf`

```ini
[Service]
ExecStart=
ExecStart=-/usr/bin/agetty --noreset --noclear --autologin root - ${TERM}
```

Hace que el login en tty1 sea automático como `root`. La línea vacía `ExecStart=` es necesaria para sobrescribir el valor por defecto de Arch.

Al loguearse, root ejecuta `/root/.zlogin` (que a su vez ejecuta `/root/.automated_script.sh`).

---

# Systemd Drop-ins

## do-not-suspend.conf

**Path:** `archiso/airootfs/etc/systemd/logind.conf.d/do-not-suspend.conf`

Impide que el sistema se suspenda automáticamente en el Live. El usuario debe apagar manualmente cuando termine.

## volatile-storage.conf

**Path:** `archiso/airootfs/etc/systemd/journald.conf.d/volatile-storage.conf`

Configura journald para almacenar logs en RAM (tmpfs). Como el sistema es Live, no tiene sentido escribir logs al disco.

## Propietario de red y DNS

NetworkManager es el único gestor de interfaces en el Live y en la instalación. El perfil usa `wpa_supplicant` para Wi-Fi; no habilita `iwd` ni `systemd-networkd`, y no incluye perfiles DHCP `20-*.network` que compitan por las mismas interfaces.

`systemd-resolved` se mantiene habilitado como resolvedor DNS: `/etc/resolv.conf` apunta a `/run/systemd/resolve/stub-resolv.conf` y `NetworkManager/conf.d/20-churros-dns.conf` configura `dns=systemd-resolved` para que NetworkManager publique ahí los DNS recibidos.

Durante la instalación, `services-systemd.conf` deshabilita `iwd`, `systemd-networkd`, su socket de activación, su unidad wait-online y los servicios específicos de hipervisores. El perfil Live tampoco conserva el alias D-Bus `dbus-org.freedesktop.network1.service`. El paso post-install elimina perfiles y alias heredados de networkd, deshace las máscaras de Live para los servicios wait-online y de sincronización de hora, y habilita `NetworkManager-wait-online.service`. Así, `network-online.target` espera a NetworkManager en el sistema instalado, sin arrancar un segundo gestor de interfaces.

Los servicios de integración de Hyper-V, VirtualBox y VMware también quedan deshabilitados en la instalación para no arrastrar una activación específica del Live a todas las máquinas. En una VM, funciones como portapapeles, carpetas compartidas o ajustes de pantalla pueden requerir habilitar manualmente el servicio del hipervisor correspondiente; los paquetes disponibles no se eliminan.

---

# Pacman Hooks

## uncomment-mirrors.hook

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

## zzzz99-remove-custom-hooks-from-airootfs.hook

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

---

# Scripts

## livecd-sound

**Path:** `archiso/airootfs/usr/local/bin/livecd-sound`

Script de gestión de audio. Opciones:

- `-u` / `--unmute` — desilencia todas las tarjetas
- `-p` / `--pick` — permite elegir tarjeta con feedback auditivo
- `-h` / `--help` — ayuda

Usa `amixer` para controlar ALSA y genera `/etc/asound.conf` a partir de `/usr/local/share/livecd-sound/asound.conf.in`.

## choose-mirror

**Path:** `archiso/airootfs/usr/local/bin/choose-mirror`

Lee `mirror=` del kernel cmdline y regenera `/etc/pacman.d/mirrorlist`. El archivo original se guarda como `mirrorlist.orig`.

## Installation_guide

**Path:** `archiso/airootfs/usr/local/bin/Installation_guide`

```sh
exec xdg-open 'https://wiki.archlinux.org/title/Installation_guide'
```

Atajo para abrir la guía de instalación de Arch en el navegador. Disponible en el PATH para que se pueda invocar desde la terminal o desde menús.

---

# Scripts y Utilidades de ChurrOS

ChurrOS incluye un conjunto de utilidades auxiliares en `/usr/bin/` y `/usr/local/bin/` para gestionar el entorno, fondos, permisos, actualizaciones y temas:

## churros-apply-wallpaper

**Path:** `/usr/bin/churros-apply-wallpaper`

Aplica el fondo de pantalla en compositores Wayland (Niri / Hyprland / Sway).

- Detecta automáticamente sockets `WAYLAND_DISPLAY` y `XDG_RUNTIME_DIR` incluso en entornos live sin sesión explícita.
- Si Noctalia está en marcha, el fondo se lo pasa a `noctalia msg wallpaper-set` (reintenta y no arranca `swaybg`). Sin Noctalia usa `swaybg` y, si falla, `awww`.
- Si no recibe argumentos, lee la ruta guardada en `~/.config/churros/settings.json` o recurre a `/usr/share/churros/wallpapers/default.png`.

## churros-pick-image

**Path:** `/usr/bin/churros-pick-image`

Diálogo gráfico nativo en GTK para seleccionar imágenes (fondos de pantalla, avatares). Filtra formatos comunes (PNG, JPG, JPEG, WEBP) y devuelve la ruta seleccionada por stdout.

## churros-pkexec

**Path:** `/usr/bin/churros-pkexec`

Wrapper para ejecutar comandos con permisos de administrador utilizando Polkit sin requerir terminal interactiva. Permite a las aplicaciones de usuario ejecutar utilidades privilegiadas (como `timedatectl`, `churros-update-utils` o `churros-snapshot`) respetando las políticas de `/etc/polkit-1/rules.d/`.

Hace `exec pkexec`: así el sujeto de polkit es la app que llama y la contraseña que piden las acciones `auth_admin_keep` se recuerda unos minutos entre llamadas. Los llamadores pasan la ruta absoluta del programa, porque la regla autoriza por ruta y argv exactos. Tabla de decisiones en [privileged-execution.md](privileged-execution.md#tabla-de-decisiones).

## churros-portal-start

**Path:** `/usr/bin/churros-portal-start`

Inicializa ordenadamente los servicios de portales `xdg-desktop-portal` en Wayland (específicamente `xdg-desktop-portal-gnome` / `xdg-desktop-portal-gtk` / `xdg-desktop-portal-wlr`) tras el arranque de Niri para garantizar la selección de archivos, captura de pantalla e integración con Flatpak.

## churros-update-utils

**Path:** `/usr/bin/churros-update-utils`

Comprueba y descarga actualizaciones del bundle de utilidades oficiales de ChurrOS desde el servidor de distribución (`https://download.churroslinux.org/churros/updates.json`).

El origen está **fijado en el binario** y el comando no acepta argumentos: una URL configurable por el usuario convertía esto en ejecución de root. Antes de extraer se valida:

- la versión y el nombre del fichero del manifiesto, contra expresiones regulares;
- el SHA-256 del paquete frente al anunciado en el manifiesto;
- la lista de miembros del tarball: solo ficheros regulares y directorios (sin enlaces simbólicos o duros, dispositivos ni FIFOs), sin rutas absolutas ni `..`, y solo en las rutas autorizadas: `usr/bin/churros-*`, `usr/local/bin/churros-*`, `usr/share/churros/`, `etc/churros-version`, `etc/churros-edition` y el hook `etc/pacman.d/hooks/50-churros-snapshot.hook`.

La extracción se hace en un directorio de stage y después se instala fichero a fichero: modo 0755 o 0644, temporal en el directorio de destino y `rename` atómico. Los directorios existentes no se tocan; antes, `cp -a` copiaba el modo 0700 del stage sobre `/` (#130).

El manifiesto se descarga antes de verificar su firma (#139). Si existe `/usr/share/churros/churros-release.pubkey`, el manifiesto debe venir firmado por minisign y la actualización se aborta si la firma no valida o si falta `minisign`. Sin clave publicada solo se avisa; que la firma sea obligatoria está pendiente (#139, #141).

## churros-theme

**Path:** `/usr/local/bin/churros-theme`

Script CLI para alternar entre tema oscuro y claro (`dark` / `light`), sincronizando gsettings, archivos CSS de acento y notificando al compositor y barra.

## churros-update-auto

**Path:** `/usr/local/bin/churros-update-auto`

Servicio en segundo plano que comprueba periódicamente si existen actualizaciones de pacman, flatpak o utilidades ChurrOS y emite notificaciones de escritorio cuando hay paquetes listos para actualizar.

## churros-snapshot

**Path:** `/usr/local/bin/churros-snapshot`

Herramienta de administración para crear, listar, limpiar y restaurar snapshots Btrfs del sistema raíz (`@`) y de usuario (`@home`). Utilizada tanto por el hook de pacman (`50-churros-snapshot.hook`) como por la interfaz gráfica en `churros-settings`. (Detalles en `docs/rollback.md`).

---

# Init Order

Resumen del orden de arranque del Live:

1. systemd monta `/etc/pacman.d/gnupg` (tmpfs).
2. `pacman-init.service` inicializa el keyring.
3. `choose-mirror.service` (si `mirror=` está en cmdline) regenera el mirrorlist.
4. NetworkManager arranca.
5. `livecd-alsa-unmuter.service` (si `accessibility=on`) desilencia audio.
6. `livecd-talk.service` (si `accessibility=on`) activa espeakup.
7. `getty@tty1` está enmascarado en el Live; el autologin lo hace greetd como `churros`.
8. `.zlogin` ejecuta `.automated_script.sh`.
9. greetd arranca.
10. Autologin como `churros`, sesión Niri.
11. Niri carga autostart (noctalia, churros-welcome). El fondo lo pinta Noctalia, no swaybg.

---

# Future Work

- Mover la lógica de `services.sh` (que habilita NetworkManager y greetd) a unidades nativas de systemd.
- Eliminar la dependencia de root autologin: usar `systemd-user-sessions` o un PAM module.
- Documentar el orden de dependencias entre servicios (hoy está implícito en los `After=` y `Before=`).
- Internacionalizar los mensajes de los hooks.
