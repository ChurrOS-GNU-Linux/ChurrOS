# Instalador

Cómo instala ChurrOS hoy, edition por edition, y qué falta para que el instalador sea propio.

---

# Qué es el instalador ahora

El instalador de ChurrOS es **Calamares con branding propio más una cola de pasos propios**. No es una aplicación propia todavía; la fase 4 del roadmap ("instalador completamente propio") sigue abierta.

```
branding/customize_airootfs.sh  →  instala Calamares en la ISO desde archiso/packages
installer/apply-calamares.sh    →  despliega la config y la regla polkit en la ISO
installer/calamares/            →  settings.conf, módulos y branding (slideshow propio)
scripts/build-calamares.sh      →  compila Calamares desde AUR con parches locales
```

La parte propia son dos cosas:

1. **La configuración**: `settings.conf` ordena la secuencia y añade cinco instancias de `shellprocess` (keyring de pacman, configuración de mkinitcpio, repositorio local temporal, tema de GRUB, limpieza).
2. **Los scripts de post-instalación**, que son los que hacen que una instalación de ChurrOS no sea la de Arch:

| Script | Qué hace |
|---|---|
| `shellprocess-pacman` | Inicializa el keyring en el destino |
| `shellprocess-fixboot` | Reescribe el preset de mkinitcpio y sus módulos |
| `shellprocess-repo` | Registra el repo `[churros]` temporal (lo quita `shellprocess-cleanup`) |
| `shellprocess-grub-theme` | Aplica el tema de GRUB y deja `/boot` legible en btrfs+zstd |
| `shellprocess-cleanup` | Quita sudoers NOPASSWD, reglas polkit, config SSH del Live, usuario y artefactos del Live, y lanza los tres scripts siguientes |
| `configure-greetd-session` | Escribe la sesión del sistema instalado según la edición |
| `configure-server` | Convierte la instalación en un servidor sin escritorio |
| `verify-install` | Comprueba que la instalación quedó bien y lo registra |

---

# Cómo resuelve la edición

Calamares no sabe qué edición se está instalando, así que el proyecto no le pide que lo sepa:

| Pieza | Dónde | Cómo resuelve la edición |
|---|---|---|
| `/etc/churros-edition` | Lo escribe `build.sh` | El valor viaja al sistema instalado con el resto del sistema de ficheros |
| `churros-xsession` | `/usr/local/bin/` | Dispatcher que lee `/etc/churros-edition` y lanza la sesión que toque. Es lo que declara `displaymanager.conf` |
| `configure-greetd-session` | Post-instalación | Escribe `config.toml` y `/etc/greetd/environments` con la sesión de la edición |
| `configure-server` | Post-instalación | Si la edición es `server`, quita el escritorio y deja `multi-user.target` |

| Edición | Sesión | Display manager en el instalado |
|---|---|---|
| niri | `churros-niri-session` | greetd |
| xfce | `churros-xfce-session` (env X11 y VT de Xorg) | greetd |
| kde | `startplasma-wayland` | greetd |
| server | ninguna | desactivado |

La ISO de la edición server sí lleva un XFCE mínimo, porque Calamares es gráfico y necesita una sesión donde dibujar. No es parte del producto final: `configure-server` lo quita al terminar.

---

# Verificación

`verify-install` se ejecuta al final de la instalación y **no falla la instalación, avisa**. Escribe en `/var/log/churros-install-verify.log`.

Comprobaciones comunes a todas las ediciones:

- `/etc/churros-edition` legible.
- El sudoers NOPASSWD del Live ya no está.
- El usuario `churros` del Live fue eliminado.
- El repo `[churros` ya no está en `pacman.conf`.
- Los artefactos de `/root` y las claves SSH del Live se borraron.

Por edición, en las de escritorio:

- Hay sesión declarada en `/etc/greetd/environments` y el lanzador existe en disco.
- `greetd` está habilitado.
- No queda sección `[initial_session]` en `config.toml` (el autologin es solo del Live).

En la edición server, en su lugar:

- `greetd` está desactivado y el target por defecto es `multi-user.target`.
- `sshd` y `chronyd` están habilitados.
- No queda `startxfce4` en disco.

---

# Controles en el repositorio

`./churros check` valida, para cada lista `archiso/packages.*.x86_64`, que su edición esté cableada en los cuatro sitios que lo necesitan. Añadir una edición a medias es un fallo de CI, no una sorpresa en el arranque de un usuario.

```
✓ edicion niri cableada en el instalador
✓ edicion xfce cableada en el instalador
✓ edicion kde cableada en el instalador
✓ edicion server cableada en el instalador
✓ el instalador resuelve la edicion en runtime (churros-xsession)
```

Los checks se probaron con fallos simulados: quitar un brazo de sesión, renombrar una variante de `os-release`, descomentar una edición en `configure-greetd-session` y volver a dejar `displaymanager.conf` con un ejecutable de una sola edición. Los cuatro se detectan.

---

# Limitaciones conocidas

1. **El instalador no es propio.** Es Calamares con parches, branding y post-instalación. Sustituirlo implica escribir particionado, subvolúmenes de btrfs, bootloader, usuarios y recuperación de errores: es la fase 4 del roadmap, no un fichero.
2. **La edición server no se puede instalar por consola**, porque el instalador es gráfico.
3. **`displaymanager.conf` declara un único ejecutable.** Hoy es `churros-xsession`, que resuelve en runtime. Si ese script se pierde, Calamares no tiene alternativa: es un punto único de fallo deliberado a cambio de no repetir el hardcodeo de una edición.
4. **Nada de esto se prueba en CI.** La CI no construye la ISO: `ci.yml` pasa los chequeos estáticos y `rust.yml` compila las apps. La secuencia real de instalación solo se verifica `./churros build` más `run`, a mano.

---

# Referencia

| Documento | Contenido |
|---|---|
| `installer/README.md` | Secuencia de instalación paso a paso |
| `docs/build-system.md` | La construcción de la ISO, incluido `apply-calamares.sh` |
| `docs/server.md` | La edición server en detalle |
| `docs/privileged-execution.md` | Qué comandos pueden obtener privilegio y con qué reglas |
| `docs/rollback.md` | Snapshots de btrfs, que también son la red de seguridad del instalador |