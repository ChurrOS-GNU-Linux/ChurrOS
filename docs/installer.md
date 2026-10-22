# Instalador

Cómo instala ChurrOS cada edición, qué parte del instalador es del proyecto y qué limitaciones tiene.

---

## Qué es el instalador ahora

El instalador de ChurrOS es **Calamares con branding propio más una cola de pasos propios**. No es una aplicación propia. La Fase 4 del [roadmap](roadmap.md) (instalador gráfico basado en Calamares) está cerrada, y un instalador propio que sustituya a Calamares tendría que cumplir la [regla para programas nuevos](principios.md#regla-para-programas-nuevos).

```
scripts/build-calamares.sh      →  compila Calamares desde AUR con los parches de installer/patches/
installer/apply-calamares.sh    →  despliega la config y la regla polkit en el airootfs
installer/calamares/            →  settings.conf, módulos y branding (slideshow propio)
branding/customize_airootfs.sh  →  instala el paquete de Calamares en la ISO durante el build
```

La instalación es offline: `unpackfs` copia al disco el sistema del Live (squashfs y kernel). `netinstall` y `packages` no están en la secuencia; sus ficheros (`netinstall.conf`, `netinstall.yaml`, `packages.conf`) siguen en `installer/calamares/modules/` sin usarse. El repo `[churros]` (`Server = file:///root/packages`) no lo registra ningún paso: viene declarado en `archiso/pacman.<arch>.conf` y `post-install` lo retira del sistema instalado.

La parte propia son dos cosas.

**1. La configuración.** [`installer/calamares/settings.conf`](../installer/calamares/settings.conf) ordena la secuencia (es la fuente de verdad del orden) y añade cinco instancias de `shellprocess`:

| Instancia (`id`) | Fichero en `modules/` | Cuándo y qué hace |
|---|---|---|
| `boot-nocow` | `shellprocess-boot-nocow.conf` | Tras `mount` y antes de `unpackfs`: `chattr +C` y `compression none` en `/boot` del destino, para que GRUB pueda leer el kernel en btrfs |
| `pacman-init` | `shellprocess-pacman.conf` | Inicializa y puebla el keyring de pacman en el destino. Va antes de `fix-boot` |
| `fix-boot` | `shellprocess-fixboot.conf` | Cambia el preset de mkinitcpio de archiso por el normal y añade módulos de vídeo |
| `grub-theme` | `shellprocess-grub-theme.conf` | Tras `bootloader`: copia el tema de GRUB, regenera `grub.cfg` y deja `/boot` legible para GRUB en btrfs+zstd |
| `post-install` | `shellprocess-cleanup.conf` | Último paso antes de `umount` (ver el punto 2) |

**2. La post-instalación**, que es lo que hace que una instalación de ChurrOS no sea la de Arch. `post-install` quita el sudoers NOPASSWD, Calamares y sus reglas polkit, la config SSH y las claves de host del Live, el usuario `churros` y los artefactos de `/root`; retira el repo `[churros]`, activa `[multilib]`, instala un tema Plymouth de texto, restablece las unidades `wait-online` y lanza cuatro scripts de `/usr/share/churros/scripts/`:

| Script | Qué hace |
|---|---|
| `configure-greetd-session` | Escribe `/etc/greetd/config.toml` y `/etc/greetd/environments` con la sesión de la edición |
| `configure-server` | Si la edición es `server`, convierte la instalación en un servidor sin escritorio |
| `verify-install` | Comprueba que la instalación quedó bien y lo registra |
| `configure-greeter-locale` | Adapta el saludo y el formato del reloj de ReGreet al idioma instalado |

---

## Arquitecturas

`apply-calamares.sh` copia los módulos comunes y, encima, los de `installer/calamares/modules/<arch>/` (la arquitectura sale de `CHURROS_ARCH`, que pasa `build.sh`).

| Arquitectura | Qué cambia |
|---|---|
| x86_64 | Nada: usa los módulos comunes |
| aarch64 | `unpackfs` (kernel `vmlinuz-linux-aarch64`), `shellprocess-fixboot` (preset `linux-aarch64.preset`, módulos virtio y `publish-aarch64-kernel --require`), `shellprocess-pacman` (keyring `archlinuxarm`) y `grubcfg` (consola serie `ttyAMA0`) |
| i686 | Hay variantes (`unpackfs`, `shellprocess-fixboot` y `shellprocess-pacman` con el keyring `archlinux32`), pero la ISO i686 no lleva Calamares: Arch Linux 32 no empaqueta `polkit-qt6` y `build.sh` lo omite |

---

## Cómo resuelve la edición

Calamares no sabe qué edición se está instalando, así que el proyecto no le pide que lo sepa:

| Pieza | Dónde | Cómo resuelve la edición |
|---|---|---|
| `/etc/churros-edition` | Lo escribe `build.sh` | El valor viaja al sistema instalado con el resto del sistema de ficheros |
| `edition-session.sh` | `/usr/share/churros/scripts/` | Tabla edición → comando de sesión. La cargan `configure-greetd-session` y `churros-write-root-config` |
| `churros-xsession` | `/usr/local/bin/` | Es el ejecutable que declara `displaymanager.conf`: lee `/etc/churros-edition` y lanza la sesión que toque. Calamares lo escribe en la config de greetd, pero `configure-greetd-session` lo sustituye después por el comando directo de la edición |
| `configure-greetd-session` | Post-instalación | Escribe `config.toml` y `/etc/greetd/environments` con la sesión de la edición |
| `configure-server` | Post-instalación | Si la edición es `server`, quita el escritorio y deja `multi-user.target` |

| Edición | Sesión | Display manager en el instalado |
|---|---|---|
| niri | `churros-niri-session` | greetd |
| xfce | `churros-xfce-session` (env X11 y VT de Xorg) | greetd |
| pi (solo aarch64) | `churros-pi-session` (labwc + waybar) | greetd |
| server | ninguna | desactivado |

La ISO de la edición server sí lleva un XFCE mínimo, porque Calamares es gráfico y necesita una sesión donde dibujar. No es parte del producto final: `configure-server` lo quita al terminar.

---

## Verificación

`verify-install` se ejecuta al final de la instalación y **no falla la instalación, avisa**. Escribe en `/var/log/churros-install-verify.log`.

Comprobaciones comunes a todas las ediciones:

- `/etc/churros-edition` legible.
- El sudoers NOPASSWD del Live ya no está.
- El usuario `churros` del Live fue eliminado.
- El repo `[churros]` ya no está en `/etc/pacman.conf`.
- Los artefactos de `/root` y las claves SSH del Live se borraron.

Red, en todas las ediciones:

- NetworkManager y systemd-resolved habilitados, NetworkManager configurado con `dns=systemd-resolved` y `/etc/resolv.conf` enlazado al stub de resolved.
- `iwd`, `systemd-networkd` y los servicios de invitado de máquinas virtuales (Hyper-V, VirtualBox, VMware) deshabilitados.
- `NetworkManager-wait-online` habilitado y sin máscara; `systemd-networkd-wait-online` sin máscara pero deshabilitado; `systemd-time-wait-sync` sin máscara.
- No queda la configuración heredada de systemd-networkd ni su alias D-Bus.

En las ediciones de escritorio:

- Hay sesión declarada en `/etc/greetd/environments` y el lanzador existe en disco.
- `greetd` está habilitado.
- No hay sección `[initial_session]` en `config.toml`. Si el usuario marcó el inicio automático en Calamares, `configure-greetd-session` conserva ese usuario y escribe `[initial_session]`, y `verify-install` lo registra igualmente como aviso: es un falso positivo.

Solo en XFCE:

- La sesión usa el wrapper `churros-xfce-session` y `xfce.desktop` lo lanza.
- La sesión `xfce-wayland` está desactivada.
- Están el hook `92-churros-xfce-x11-session.hook` y el script `fix-xfce-sessions`, que mantienen la sesión X11 tras las actualizaciones.

En la edición server, en lugar de lo de escritorio:

- `greetd` está desactivado y el target por defecto es `multi-user.target`.
- `sshd` y `chronyd` están habilitados.
- No queda `startxfce4` en disco.

---

## Controles en el repositorio

`./churros check` valida, para cada lista `archiso/packages*.x86_64`, que su edición esté cableada en `scripts/cli/build.sh` (el comando de sesión), `branding/stamp-os-release.sh` y `edition-session.sh`. Aparte comprueba que `configure-greetd-session` y `churros-write-root-config` carguen `edition-session.sh` y que `displaymanager.conf` use `churros-xsession`. Añadir una edición a medias es un fallo de CI, no una sorpresa en el arranque de un usuario.

```
✓ edicion server cableada en el instalador
✓ edicion niri cableada en el instalador
✓ edicion xfce cableada en el instalador
✓ configure-greetd-session y churros-write-root-config comparten edition-session.sh
✓ el instalador resuelve la edicion en runtime (churros-xsession)
```

La edición pi no entra en este control, porque su lista es `packages.pi.aarch64` y el check solo recorre las `*.x86_64`. Tampoco se comprueba, edición por edición, el `case` de `churros-xsession`.

---

## Limitaciones conocidas

1. **El instalador no es propio.** Es Calamares con parches, branding y post-instalación. Sustituirlo implica escribir particionado, subvolúmenes de btrfs, bootloader, usuarios y recuperación de errores, y tendría que cumplir la regla para programas nuevos (ver arriba).
2. **La edición server no se puede instalar por consola**, porque el instalador es gráfico.
3. **Añadir una edición toca varios sitios**: `build.sh`, `branding/stamp-os-release.sh`, `edition-session.sh` y `churros-xsession`. `./churros check` cubre los tres primeros (ver arriba).
4. **Ninguna CI ejecuta una instalación.** `ci.yml` pasa los chequeos estáticos, `rust.yml` compila las apps, `polkit.yml` prueba la regla polkit con un polkitd real e `iso-arm64.yml` construye la ISO aarch64 (a mano o en los PR que tocan ese perfil) sin instalarla. La secuencia real de instalación solo se verifica a mano, con `./churros build` y `./churros run`.

---

## Referencia

| Documento | Contenido |
|---|---|
| [`installer/README.md`](../installer/README.md) | Secuencia de instalación paso a paso, regla polkit de Calamares y vista previa en el host |
| [`docs/build-system.md`](build-system.md) | La construcción de la ISO, incluido `apply-calamares.sh` |
| [`docs/server.md`](server.md) | La edición server en detalle |
| [`docs/privileged-execution.md`](privileged-execution.md) | Qué comandos pueden obtener privilegio y con qué reglas |
| [`docs/rollback.md`](rollback.md) | Snapshots btrfs que crea el hook de pacman en el sistema instalado (el instalador no crea un snapshot inicial) |
