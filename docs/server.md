# Server Edition

Edición de ChurrOS para servidores: sin escritorio gráfico en el sistema instalado, accesible por SSH.

```bash
./churros build --edition server
```

---

# Qué es y qué no es

Esta edición tiene una restricción propia que conviene entender antes de usarla: **el instalador de ChurrOS es Calamares, que es gráfico**, así que la ISO necesita una sesión gráfica para mostrar la ventana del instalador.

| | |
|---|---|
| La **ISO** | Lleva un XFCE mínimo. Es lo que ves al arrancar y lo que hospeda el instalador. |
| El **sistema instalado** | Sin escritorio. `configure-server` lo quita al terminar la instalación. |
| El **arranque** | `multi-user.target`: consola de texto, sin display manager. |

Es decir: el escritorio de la ISO es una herramienta de instalación, no parte del producto final.

---

# Peso

Cierre de dependencias medido contra las bases de pacman de Arch:

| Edición | Lista | Cierre | Instalado |
|---|---|---|---|
| server | 185 | 279 | **1843 MiB** |
| xfce | 214 | 318 | 3097 MiB |
| niri | 206 | 309 | 3142 MiB |
| kde | 209 | 308 | 3343 MiB |

Un **41 % menos** que la edición Niri.

---

# Qué incluye

## Base

- Arch Linux `x86_64` con btrfs, GRUB (UEFI) y Syslinux (BIOS).
- NetworkManager con `iwd` para Wi-Fi.
- PipeWire **no** se incluye: es una edición sin audio.
- Calamares, las apps propias de ChurrOS y el tema de GRUB, igual que en las otras ediciones.

## Servicios de servidor

| Servicio | Estado |
|---|---|
| `sshd` | Habilitado por `configure-server`. **No** en las ediciones de escritorio |
| `chronyd` | Habilitado. `systemd-timesyncd` no viene en la ISO, y sin reloj fiable falla el TLS de `pacman` |
| `NetworkManager` | Habilitado |
| `ufw` | Habilitado, como en el resto de ediciones |
| `fail2ban` | Incluido y habilitado por defecto, bloquea intentos de fuerza bruta contra SSH |
| `greetd` | **Deshabilitado**. El módulo `services-systemd` de Calamares lo habilita con `mandatory: true`; `configure-server` lo revierte |

## Herramientas

`htop`, `tmux`, `lsof`, `jq`, `strace`, `git`, `procps-ng` (pgrep/pkill/top), `pciutils` (lspci), más las que ya traía la base: `btrfs-progs`, `lvm2`, `mdadm`, `cryptsetup`, `nvme-cli`, `smartmontools`, `rsync`, `curl`, `tcpdump`, `vim`, `nano` y las páginas de manual.

---

# Qué quita al instalar

`configure-server` borra los 22 paquetes de escritorio (XFCE, `cage`, `greetd`, `thunar`, `gvfs`…) con `pacman -Rns`, y además:

- Los binarios de las apps propias, que son ficheros en `/usr/bin` y no paquetes: `churros-welcome`, `churros-settings`, `churros-control-center`, `churros-popup`, `churros-tour`, `churros-apply-wallpaper`, `churros-pick-image`.
- Los lanzadores del panel de XFCE, que apuntan a esos binarios.
- `/etc/skel/.config/xfce4` y los autostart del skel, para que un usuario nuevo no herede un escritorio que ya no está.
- Las líneas de arranque de `churros-welcome` y `churros-tour` en el `config.kdl` de Niri.

Todo va registrado en `/var/log/churros-server.log`. Cada paso es tolerante a fallos: si algo falla, la instalación termina igual y queda en el log.

---

# Conectarse tras instalar

```bash
# en el servidor
ip a            # o hostname -I
systemctl status sshd
```

`sshd` escucha en el puerto 22. El usuario es el que creaste en el instalador; la contraseña es la misma que en las otras ediciones (`doReusePassword` activa la de root).

Primera conexión:

```bash
ssh usuario@IP_DEL_SERVIDOR
```

---

# Limitaciones conocidas

1. **El instalador sigue siendo gráfico.** No hay instalación por consola. Para desplegar en servidores sin KVM hay que hacerlo por otros medios (instalación manual, `mkarchiso` con una imagen propia, o provisionado).
2. **La ISO es más grande de lo que sugiere el resultado.** Lleva el escritorio solo para el instalador; el sistema instalado es el que pesa 1843 MiB.
3. **Sin remoto gráfico.** No hay VNC ni RDP configurados. Para acceso gráfico hay que añadir `tigervnc`/`xrdp` a la lista y documentar su endurecimiento.
4. **No se prueba en CI.** La CI no construye la ISO: `rust.yml` compila las apps y `ci.yml` pasa los chequeos estáticos. El arranque real de esta edición está sin verificar.
5. **SSH con contraseña.** Es lo que deja Calamares. Endurecerlo (solo claves, `PasswordAuthentication no`) es una decisión que no se ha tomado todavía.

---

# Ficheros que la edición toca

| Fichero | Cambio |
|---|---|
| `archiso/packages.server.x86_64` | Lista de paquetes (185 entradas) |
| `scripts/cli/build.sh` | Edición admitida y comando de sesión (`startxfce4`, por el instalador) |
| `archiso/airootfs/usr/share/churros/scripts/configure-server` | Conversión a sin escritorio |
| `archiso/airootfs/usr/share/churros/scripts/configure-greetd-session` | Sale con 0 en la edición server |
| `archiso/airootfs/root/scripts/desktop.sh` | La sesión Live usa las variables de XFCE |
| `branding/stamp-os-release.sh` | `VARIANT=Server Edition`, `VARIANT_ID=server` |
| `installer/calamares/modules/shellprocess-cleanup.conf` | Ejecuta `configure-server` |

---

# Verificación hecha

- Cada nombre de paquete comprobado contra las bases de pacman de Arch; los 22 del purge existen en la lista de la edición, así que `pacman -Rns` no se encuentra con nombres fantasma.
- Los seis paquetes añadidos (`chrony`, `fail2ban`, `htop`, `tmux`, `lsof`, `jq`, `strace`, `git`, `procps-ng`, `pciutils`) existen en los repos.
- `bash -n` en los scripts tocados, YAML del módulo de Calamares válido y `./churros check` en verde.

**Lo que no está verificado: el build y el arranque.** En el entorno donde se escribió esto no hay `mkarchiso`. Antes de dar la edición por buena hay que construir la ISO y arrancar un servidor instalado desde ella.