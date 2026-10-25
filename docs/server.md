# Edición servidor

Edición de ChurrOS para servidores: el sistema instalado arranca sin escritorio gráfico y se administra por SSH.

```bash
./churros build --edition server
```

Antes de usarla en una máquina expuesta a la red, lee [Qué activa y qué no](#qué-activa-y-qué-no) y [Endurecimiento opcional](#endurecimiento-opcional): el cortafuegos y fail2ban vienen instalados pero **no** están activos, y el sistema se actualiza solo cada noche.

---

## Qué es y qué no es

Esta edición tiene una restricción propia que conviene entender antes de usarla: **el instalador de ChurrOS es Calamares, que es gráfico**, así que la ISO necesita una sesión gráfica para mostrar la ventana del instalador.

| Pieza | Qué lleva |
|---|---|
| La **ISO** | Un XFCE mínimo. Es lo que ves al arrancar y lo que hospeda el instalador. |
| El **sistema instalado** | Arranca sin escritorio. `configure-server` deshabilita greetd al terminar la instalación e intenta quitar los paquetes del escritorio; hoy esa parte falla (ver [Qué quita al instalar](#qué-quita-al-instalar)). |
| El **arranque** | `multi-user.target`: consola de texto, sin display manager. |

Es decir: el escritorio de la ISO es una herramienta de instalación, no parte del producto final.

---

## Peso

Cifras del commit que creó la edición (`0d0410c`, septiembre de 2026): cierre de dependencias medido contra las bases de pacman de Arch. Las listas han cambiado desde entonces (hoy tienen 187 entradas la de server, 219 la de xfce y 221 la de niri) y el repositorio no tiene un script para repetir la medida, así que tómalas como orden de magnitud.

| Edición | Paquetes con dependencias | Instalado |
|---|---|---|
| server | 279 | **1843 MiB** |
| xfce | 318 | 3097 MiB |
| niri | 309 | 3142 MiB |

En esa medida, la edición server ocupaba un 41 % menos que la edición Niri.

---

## Qué incluye

### Base

- Arch Linux `x86_64`. El sistema instalado usa btrfs por defecto (ext4 es la otra opción del instalador) y GRUB, en BIOS y en UEFI. La ISO arranca con Syslinux en BIOS y GRUB en UEFI ([boot.md](boot.md)).
- NetworkManager. El Wi-Fi va con `wpa_supplicant`: `iwd` está instalado, pero Calamares deshabilita `iwd.service`.
- PipeWire **no** se incluye: es una edición sin audio.
- La ISO lleva Calamares y las apps propias de ChurrOS, como las demás ediciones. En el sistema instalado, `configure-server` retira las apps de escritorio (ver [Qué quita al instalar](#qué-quita-al-instalar)). El tema de GRUB se instala igual que en las otras ediciones.

### Herramientas

`htop`, `tmux`, `lsof`, `jq`, `strace`, `git`, `procps-ng` (pgrep/pkill/top), `pciutils` (lspci), más las que ya traía la base: `btrfs-progs`, `lvm2`, `mdadm`, `cryptsetup`, `nvme-cli`, `smartmontools`, `rsync`, `curl`, `tcpdump`, `vim`, `nano` y las páginas de manual.

---

## Qué activa y qué no

Estado de cada servicio en el sistema instalado. Lo decide `archiso/airootfs/usr/share/churros/scripts/configure-server`, que Calamares ejecuta en el paso `shellprocess@post-install`.

| Unidad | Estado |
|---|---|
| `sshd` | **Habilitado.** Escucha en el puerto 22 desde el primer arranque. Las ediciones de escritorio no lo habilitan. |
| `chronyd` | Habilitado. Mantiene la hora sincronizada; sin reloj fiable falla el TLS de `pacman`. |
| `NetworkManager` | Habilitado. |
| `ufw` | **El servicio está habilitado, pero el cortafuegos no filtra nada.** `ufw.service` solo carga reglas si `/etc/ufw/ufw.conf` dice `ENABLED=yes`, y el paquete trae `ENABLED=no`. Nadie ejecuta `ufw enable` ni añade reglas. |
| `fail2ban` | **Instalado, pero ni habilitado ni configurado.** No protege SSH hasta que lo actives. |
| `churros-update.timer` | **Habilitado: actualización desatendida diaria** (ver [Actualizaciones automáticas](#actualizaciones-automáticas)). |
| `greetd` | Deshabilitado. El módulo `services-systemd` de Calamares lo habilita con `mandatory: true`; `configure-server` lo revierte y fija `multi-user.target` como destino por defecto. |

### Actualizaciones automáticas

`configure-server` habilita el timer de sistema `churros-update.timer` (`archiso/airootfs/etc/systemd/system/`). Cada día a las 04:00, con un retraso aleatorio de hasta 30 minutos, lanza `churros-update.service`, que ejecuta como root `/usr/local/bin/churros-update-auto`. Ese script hace, sin pedir confirmación:

1. `pacman -Syu --noconfirm`
2. `flatpak update -y`
3. `churros-update-utils`, que descarga e instala el paquete de utilidades de ChurrOS si el manifiesto anuncia una versión distinta de la instalada ([privileged-execution.md](privileged-execution.md)).

Como el timer tiene `Persistent=true`, si el servidor estaba apagado a esa hora la actualización se lanza en el siguiente arranque. No reinicia el equipo: un kernel nuevo se usa a partir del próximo reinicio. Con btrfs, el hook `50-churros-snapshot` crea un snapshot antes de cada transacción de pacman, así que una actualización que rompa algo se puede deshacer ([rollback.md](rollback.md)). La salida va a `/tmp/churros-update.log`; `journalctl -u churros-update.service` muestra cuándo se ejecutó. El script intenta avisar con una notificación de escritorio, que en un servidor no llega a ninguna parte.

Si prefieres actualizar a mano:

```bash
sudo systemctl disable --now churros-update.timer
```

Además, el usuario que creas en el instalador hereda del skel un timer de usuario con el mismo script. Ese timer no actualiza nada en el servidor: sin agente de polkit, los pasos que necesitan root fallan.

---

## Qué quita al instalar

`configure-server` intenta borrar los 22 paquetes de escritorio de la ISO (XFCE, `cage`, `greetd`, `greetd-regreet`, `thunar`, `gvfs`…) con una sola orden `pacman -Rns`. Con la lista actual esa orden falla y no borra ninguno: paquetes de `packages.server.x86_64` que no están en el purge dependen de paquetes que sí lo están (`xfwm4` de `xfconf`, `gvfs-mtp` de `gvfs`, `thunar-archive-plugin` y `thunar-volman` de `thunar`), y pacman cancela la transacción entera. El error queda en `/var/log/churros-server.log`, y `verify-install`, que comprueba que no exista `/usr/bin/startxfce4`, deja un aviso en `/var/log/churros-install-verify.log`. Aun así, el escritorio no arranca: greetd queda deshabilitado y el destino por defecto es `multi-user.target`.

Lo que sí se borra, porque no depende de pacman:

- Los binarios de las apps propias, que son ficheros en `/usr/bin` y no paquetes: `churros-welcome`, `churros-settings`, `churros-control-center`, `churros-popup`, `churros-tour`, `churros-apply-wallpaper`, `churros-pick-image`.
- Los lanzadores del panel de XFCE, que apuntan a esos binarios.
- `/etc/skel/.config/xfce4`, los autostart del skel y los de `/home/*`, para que ningún usuario herede la configuración del escritorio.
- `/etc/greetd/environments`.
- En el `config.kdl` de Niri (skel y homes): todas las líneas `spawn-at-startup` y las que mencionan `churros-welcome` o `churros-tour`.

Otros paquetes gráficos de la lista no están en el purge y se quedarían instalados aunque funcionara, entre ellos `xfwm4`, `xorg-server`, `gtk4`, `libadwaita` y `bazaar` (la tienda Flatpak).

Todo va registrado en `/var/log/churros-server.log`. Cada paso es tolerante a fallos: si algo falla, la instalación termina igual y queda en el log.

---

## Conectarse tras instalar

```bash
# en el servidor
ip a            # o hostname -I
systemctl status sshd
```

- `sshd` escucha en el puerto 22 de todas las interfaces, con la configuración por defecto de Arch: los usuarios normales pueden entrar con contraseña y root no (`PermitRootLogin prohibit-password`, el valor por defecto de OpenSSH). El paso post-install borra `10-archiso.conf`, que en el Live permite entrar como root con contraseña.
- El usuario es el que creaste en el instalador. Root recibe la misma contraseña si dejas marcada la casilla de usar la misma contraseña para el administrador, que viene marcada (`doReusePassword: true`).
- El post-install borra las claves de host SSH del Live; se generan otras nuevas en el primer arranque, así que la huella no coincide con la del Live.
- En la consola local, tty1 no muestra el login: `getty@tty1` queda enmascarado, como en el Live. Cambia a otra consola con `Ctrl+Alt+F2`.

Primera conexión:

```bash
ssh usuario@IP_DEL_SERVIDOR
```

---

## Endurecimiento opcional

Ninguno de estos pasos lo hace la edición por ti. Son los mínimos para que el cortafuegos y fail2ban hagan algo.

### Activar el cortafuegos sin perder SSH

```bash
sudo ufw allow ssh      # primero: abre el puerto 22
sudo ufw enable         # escribe ENABLED=yes y carga las reglas
sudo ufw status verbose
```

La política por defecto de ufw descarta las conexiones entrantes (`DEFAULT_INPUT_POLICY="DROP"` en `/etc/default/ufw`). Si activas el cortafuegos por SSH sin la regla de `ssh`, pierdes el acceso. Como `ufw.service` ya está habilitado, las reglas se cargan en cada arranque a partir de ahí.

### Activar fail2ban para SSH

```bash
sudo tee /etc/fail2ban/jail.d/sshd.local >/dev/null <<'EOF'
[sshd]
enabled = true
EOF
sudo systemctl enable --now fail2ban
sudo fail2ban-client status sshd
```

El paquete de Arch ya lee los registros de `sshd` desde el journal (`sshd_backend = systemd` en `/etc/fail2ban/paths-arch.conf`), así que basta con activar el jail.

---

## Limitaciones conocidas

1. **El instalador sigue siendo gráfico.** No hay instalación por consola. En servidores sin pantalla ni teclado hay que instalar por otros medios (instalación manual, `mkarchiso` con una imagen propia o provisionado).
2. **La ISO es más grande de lo que sugiere el resultado.** Lleva el escritorio solo para el instalador.
3. **Sin remoto gráfico.** No hay VNC ni RDP configurados. Para acceso gráfico hay que añadir `tigervnc`/`xrdp` a la lista y documentar su endurecimiento.
4. **No se prueba en CI.** La CI solo construye la ISO aarch64 (`iso-arm64.yml`); `rust.yml` compila las apps y `ci.yml` pasa los chequeos estáticos. El build y el arranque de esta edición no se prueban automáticamente y en el repositorio no hay constancia de una instalación probada en QEMU o en hardware.
5. **SSH con contraseña.** Es lo que deja Calamares. Pasar a solo claves (`PasswordAuthentication no`) es una decisión que no se ha tomado todavía.
6. **Actualización desatendida.** El timer actualiza sin ventana de mantenimiento ni aviso (ver [Actualizaciones automáticas](#actualizaciones-automáticas)).
7. **El escritorio de la ISO se queda en el disco.** El `pacman -Rns` de `configure-server` falla por dependencias y no quita ningún paquete (ver [Qué quita al instalar](#qué-quita-al-instalar)).

---

## Ficheros que la edición toca

| Fichero | Cambio |
|---|---|
| `archiso/packages.server.x86_64` | Lista de paquetes |
| `scripts/cli/build.sh` | Edición admitida y comando de la sesión Live (`/usr/bin/churros-xfce-session`, para el instalador) |
| `archiso/airootfs/usr/share/churros/scripts/configure-server` | Conversión a sistema sin escritorio y servicios |
| `archiso/airootfs/usr/share/churros/scripts/configure-greetd-session` | Sale con 0 en la edición server |
| `archiso/airootfs/root/scripts/desktop.sh` | La sesión Live usa las variables de XFCE |
| `branding/stamp-os-release.sh` | `VARIANT="Server Edition"`, `VARIANT_ID="server"` |
| `installer/calamares/modules/shellprocess-cleanup.conf` | Ejecuta `configure-server` |
