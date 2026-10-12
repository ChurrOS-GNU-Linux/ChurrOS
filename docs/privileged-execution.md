# Privileged Execution

Este documento describe cómo obtienen privilegios los procesos de ChurrOS y
qué reglas se aplican para que esa escalada sea explícita y auditable.

La regla que resume todo lo demás: **se autoriza por ruta absoluta exacta y por
argv exacto, nunca por nombre de comando ni por comodín.**

---

# Por qué importa

`pkexec` resuelve rutas relativas (`./x`, `../x`) y busca en `$PATH` antes de
elevar. Una regla polkit que autorice por *basename* concede root sin contraseña
a cualquier fichero que el usuario pueda crear:

```bash
printf '#!/bin/sh\nid -u\n' > /tmp/churros-pwn && chmod +x /tmp/churros-pwn
pkexec /tmp/churros-pwn        # uid=0, sin contraseña
```

Por eso las reglas de ChurrOS comparan la ruta absoluta contra una lista
cerrada, todas bajo `/usr` o `/usr/local` (propiedad de root, no escribibles por
el usuario), y además el argv completo: una opción extra convierte una utilidad
inocua en otra cosa.

---

# Piezas

| Pieza | Ruta | Función |
|-------|------|---------|
| Regla polkit | `/etc/polkit-1/rules.d/50-churros-store.rules` | Decide, para `wheel`, qué argv exactos van sin contraseña y cuáles con contraseña recordada |
| Regla de Calamares | `/etc/polkit-1/rules.d/49-calamares.rules` | Solo durante la instalación: permite al usuario Live lanzar Calamares |
| Wrapper | `/usr/bin/churros-pkexec` | Hace `exec pkexec` (o ejecuta directamente si ya es root) |
| Helper de config | `/usr/local/bin/churros-write-root-config` | Aplica operaciones acotadas sobre greetd, ReGreet y LightDM |
| Tabla de sesiones | `/usr/share/churros/scripts/edition-session.sh` | Edición → comando de sesión; la comparten la instalación y el helper |
| Snapshots | `/usr/local/bin/churros-snapshot` | Snapshots btrfs de `@` y `@home` |
| Utilidades | `/usr/bin/churros-update-utils` | Descarga e instala el bundle de utilidades de ChurrOS |

---

# Qué recibe la regla

pkexec usa la acción `org.freedesktop.policykit.exec` y publica estos detalles
(comprobado con polkitd 124 y en el código de pkexec):

| Detalle | Contenido |
|---------|-----------|
| `program` | Ruta absoluta del ejecutable. Desde polkit 127 es su `realpath` |
| `command_line` | argv unido con espacios, sin comillas, empezando por la ruta con la que se llamó |
| `user` | Usuario destino: `root`, salvo con `pkexec --user` |

**No existe un detalle `command` ni `action.getDetails()`.** La regla anterior
leía `action.lookup("command")`, que siempre devolvía `undefined`, así que no
autorizaba nunca nada: todo pedía contraseña y lo que se lanzaba sin agente de
polkit fallaba (#152). Corregir solo la clave habría activado de golpe una
allowlist demasiado amplia, por eso el arreglo y la restricción van juntos.

La regla exige que `command_line` empiece exactamente por `program`. Si no
coinciden (un enlace simbólico que polkit 127 resuelve, una ruta con espacios),
los argumentos no se pueden separar con certeza y no se autoriza nada. Por eso
los llamadores pasan siempre la ruta absoluta canónica.

---

# Tabla de decisiones

| Programa | Argumentos exactos | Resultado |
|----------|--------------------|-----------|
| `/usr/local/bin/churros-snapshot` | `list --json` | `YES` |
| | `create manual` | `YES` (1) |
| | `delete AAAAMMDD-HHMMSS` | `AUTH_ADMIN_KEEP` |
| `/usr/bin/timedatectl` | `set-timezone <Zona/Ciudad>` (nombre de la base tz) | `YES` |
| | `set-ntp true` · `set-ntp false` | `YES` |
| `/usr/bin/pacman` | `-Syu --noconfirm` | `AUTH_ADMIN_KEEP` |
| `/usr/bin/flatpak` | `update -y` | `AUTH_ADMIN_KEEP` |
| `/usr/bin/churros-update-utils` | (sin argumentos) | `AUTH_ADMIN_KEEP` |
| `/usr/local/bin/churros-write-root-config` | `greetd-autologin on\|off` · `lightdm-autologin on\|off` · `regreet-wallpaper <ruta>` · `regreet-greeting <texto>` | `AUTH_ADMIN_KEEP` |
| Cualquier otra cosa | | `NOT_HANDLED` |

- **`YES`**: sin contraseña. Solo para lo inocuo.
- **`AUTH_ADMIN_KEEP`**: contraseña de administrador, que polkit recuerda unos
  minutos para el mismo proceso (ver más abajo).
- **`NOT_HANDLED`**: la regla no decide y se aplica la política por defecto de
  pkexec, `auth_admin`: contraseña cada vez.
- La regla solo actúa para sujetos locales del grupo `wheel` y con `root` como
  usuario destino.
- (1) `create` rota los snapshots: conserva los 5 más recientes y borra el
  resto. Si no se quiere que un proceso del usuario pueda descartar puntos de
  restauración sin contraseña, hay que pasarlo a `AUTH_ADMIN_KEEP`.

Ya no están en la lista `yay`, `paru`, `churros-theme` (escribe en
`$HOME/.cache`, no necesita root), las demás operaciones de pacman (`-S`, `-R`,
`-Sy`, `-Sc`...) ni ningún argumento libre de flatpak. Nadie los usaba por
pkexec.

**`churros-pkexec` no está autorizado.** Reenvía argumentos libres a `pkexec`, así
que permitirlo anularía la allowlist por completo.

## Llamadores

Son lo único que la regla permite. `scripts/test-polkit-rules.js` comprueba que
cada uno sigue escrito así en el código.

| Llamador | Comandos |
|----------|----------|
| `rust/preferences/src/services/update.rs` | `pacman -Syu --noconfirm`, `flatpak update -y`, `churros-update-utils`, `churros-snapshot list --json`, `churros-snapshot create manual`, `churros-snapshot delete <stamp>` |
| `archiso/airootfs/usr/local/bin/churros-update-auto` | `pacman -Syu --noconfirm`, `flatpak update -y`, `churros-update-utils` |
| `rust/preferences/src/services/datetime.rs` | `timedatectl set-timezone <tz>`, `timedatectl set-ntp true\|false` |
| `rust/preferences/src/services/users.rs` | `churros-write-root-config` con las cuatro operaciones |

Fuera de la tabla:

- Comprobar actualizaciones ya no necesita root: Ajustes usa `checkupdates`
  (pacman-contrib), que sincroniza una copia temporal de las bases, en vez de
  `pkexec pacman -Sy`, que dejaba el sistema expuesto a una actualización
  parcial (#137).
- `rust/preferences/src/services/privacy.rs` usa `pkexec systemctl …` y
  `pkexec ufw …` directamente: caen en la política por defecto.
- `churros-update-auto` corre desde un timer de usuario, sin agente de polkit:
  sus pasos piden contraseña y fallan. Que pase a comprobar y avisar en vez de
  instalar es #142.

## Contraseña recordada y `churros-pkexec`

polkit guarda las autorizaciones `*_KEEP` por **sujeto**, y para pkexec el
sujeto es su proceso padre. `churros-pkexec` hace `exec pkexec`, así que el
padre es la app que llama (Ajustes): "Actualizar ahora" pide la contraseña una
vez para pacman, flatpak y las utilidades. Si pkexec fuera hijo del script,
cada llamada sería un sujeto nuevo y pediría la contraseña cada vez.

El código de salida es el de pkexec: el del comando si se ejecutó, 126 si se
cerró el diálogo y 127 si no se autorizó o no hay agente. `churros-pkexec` ya no
reintenta con `sudo -n`: en el sistema instalado sudo pide contraseña y no
servía; solo se usa sudo si pkexec no está instalado.

---

# Escritura de configuración del sistema

Los ajustes que viven en `/etc` (autologin de greetd, fondo y saludo de ReGreet,
autologin de LightDM) se aplican con `churros-write-root-config`, que **no
acepta contenido**, solo operaciones:

```bash
churros-pkexec /usr/local/bin/churros-write-root-config greetd-autologin on
churros-pkexec /usr/local/bin/churros-write-root-config lightdm-autologin off
churros-pkexec /usr/local/bin/churros-write-root-config regreet-wallpaper /usr/share/churros/wallpapers/default.png
churros-pkexec /usr/local/bin/churros-write-root-config regreet-greeting "Bienvenido a ChurrOS"
```

Antes recibía el fichero entero por stdin. `/etc/greetd/config.toml` decide qué
usuario y qué comando arranca greetd al encender (`[initial_session]`), así que
quien pudiera escribirlo controlaba el arranque. Ahora:

- el usuario del inicio automático es siempre quien invocó pkexec
  (`PKEXEC_UID`, resuelto con `getent`), nunca un argumento; root no;
- el comando de sesión sale de `/etc/churros-edition` con la tabla de
  `edition-session.sh`, la misma que usa la instalación
  (`configure-greetd-session`): Niri → `/usr/bin/churros-niri-session`,
  XFCE → `/usr/bin/churros-xfce-session`, KDE → `/usr/bin/startplasma-wayland`, server →
  sin sesión;
- el fondo tiene que ser un fichero regular de `/usr/share/churros/wallpapers`,
  `/usr/share/backgrounds` o `/usr/share/wallpapers` (tras resolver enlaces) y
  legible por cualquier usuario, el greeter incluido. Un fondo del home no lo
  podría leer el greeter y su contenido lo controla el usuario;
- el saludo admite hasta 80 caracteres UTF-8 sin caracteres de control (un
  salto de línea abriría otra clave TOML). Fondo y saludo se escapan para TOML y
  solo se toca su clave: el resto de `regreet.toml` se conserva;
- cada escritura es atómica: temporal `mktemp` **dentro del directorio de
  destino** y `rename`.

---

# Actualización de las utilidades

`churros-update-utils` se ejecuta como root y escribe en el sistema, así que:

- el origen (`https://download.churroslinux.org/churros/`) está fijado en el
  binario y el comando **no acepta argumentos**;
- el manifiesto se descarga primero y, si existe
  `/usr/share/churros/churros-release.pubkey`, se verifica su firma minisign
  antes de leerlo. Antes se verificaba un fichero vacío, antes de la descarga
  (#139). Con la clave publicada, la falta de `minisign` aborta;
- versión, nombre de fichero y sha256 del manifiesto se validan con expresiones
  regulares, y el sha256 del bundle tiene que coincidir;
- el tarball solo puede traer ficheros regulares y directorios (ni enlaces, ni
  dispositivos, ni FIFOs), sin rutas absolutas ni `..`, y solo en estas rutas:
  - `usr/bin/churros-*` y `usr/local/bin/churros-*` (ficheros directos);
  - `usr/share/churros/` (cualquier profundidad);
  - `etc/churros-version`, `etc/churros-edition` y
    `etc/pacman.d/hooks/50-churros-snapshot.hook` (el hook de rollback que lleva
    el bundle; solo llama a `churros-snapshot`);
- se extrae en un stage y se instala **fichero a fichero**: modo 0755 si viene
  ejecutable y 0644 si no, temporal en el directorio de destino y `rename`
  atómico. Los directorios que faltan se crean con 0755 y los existentes no se
  tocan. Antes se hacía `cp -a "$STAGE"/. /`, que copiaba sobre `/` el modo 0700
  del stage de `mktemp -d` y dejaba el sistema inutilizable (#130).

Pendiente: que la firma sea obligatoria (no hay clave publicada ni firma en
`build-churros-release.sh`; #139, #141).

Detalle en [live-services.md](live-services.md#churros-update-utils).

---

# Pruebas

| Prueba | Qué cubre | Dónde corre |
|--------|-----------|-------------|
| `scripts/test-polkit-rules.js` | La regla con un `polkit` falso: cada llamador real (y que sigue escrito así en el código), intentos con `--opt=valor`, argumentos extra, rutas relativas o de otro directorio, `flatpak run`, `pacman -R`, `yay`, `pkexec --user`, el `realpath` de polkit 127, y que la regla no lea `command` ni use sintaxis que duktape no entienda | `./churros check` (si hay `node`) y CI |
| `scripts/test-privileged-helpers.py` | `churros-update-utils` sobre un root falso (`/`, `/usr` y `/etc` siguen en 755, rutas fuera de la lista, tarballs con enlaces o `..`, firma tras la descarga), el bundle real de `build-churros-release.sh`, `churros-write-root-config` y la tabla de sesiones | `./churros check` y CI |
| `scripts/test-polkit-pkexec.sh` | polkitd y pkexec reales: las claves que publica pkexec, que la regla carga en duktape y sus decisiones con programas falsos | CI (`polkit.yml`, contenedor Arch). Necesita root: no la lances en tu sistema |

`./churros check` además falla si la regla vuelve a leer `lookup("command")`.

---

# Entorno Live

En el Live, el usuario `churros` tiene `NOPASSWD: ALL` en
`/etc/sudoers.d/churros`, una contraseña vacía y el arranque de tty1 es un
autologin de root (herencia de archiso). Es intencional para un Live, y ese
fichero se elimina en `shellprocess@post-install` junto con los artefactos del
usuario Live.

En consecuencia, en el Live la frontera real no es el privilegio sino el acceso
físico a la máquina: quien la tiene ya tiene root. Lo que sí se protege es el
sistema instalado, donde el usuario normal es `wheel` y su `sudo` **sí** pide
contraseña.

---

# Checklist al añadir un helper privilegiado

1. ¿El llamador pasa la ruta absoluta y un argv fijo?
2. ¿Ese argv exacto está en `50-churros-store.rules`, con el resultado mínimo
   (`YES` solo si es inocuo) y en la tabla de `scripts/test-polkit-rules.js`?
3. ¿El helper valida sus argumentos por sí mismo, en vez de confiar en la regla?
4. ¿Recibe operaciones y no contenido libre? Si necesita datos, ¿los valida y
   escapa?
5. ¿La escritura es atómica y en el directorio de destino?
6. ¿Hay una prueba que demuestre que un usuario sin privilegios no puede
   convertirlo en ejecución arbitraria?
