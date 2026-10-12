# Apps

Este documento describe las aplicaciones oficiales de ChurrOS.

Desde **v0.5 / v0.6** todas las apps oficiales están escritas en **Rust** con **gtk4-rs** y **libadwaita**. El código Python de `/usr/share/churros/` se eliminó del repositorio; en runtime solo quedan assets (CSS, SVG) y los binarios que despliega `scripts/build-rust.sh`.

```text
rust/
├── Cargo.toml              # workspace
├── churros-welcome/        # binario churros-welcome
├── preferences/            # binario churros-settings
├── control-center/         # binario churros-control-center
├── popups/                 # binario churros-popup
└── services/               # crate churros_services (no se despliega)
```

Cada crate con `deploy = true` en `Cargo.toml` se copia a `archiso/airootfs/usr/bin/<nombre>` al construir la ISO. Los binarios no se versionan.

En desarrollo, los crates resuelven assets a `rust/<crate>/assets/` si no existe `/usr/share/churros/<app>/`.

---

# churros-welcome

**Path:** `rust/churros-welcome/`
**Binario:** `/usr/bin/churros-welcome`
**Autostart:** `archiso/airootfs/etc/skel/.config/niri/config.kdl` (Niri) y `.config/autostart/churros-welcome.desktop` (XFCE)
**Assets:** `archiso/airootfs/usr/share/churros/churros-welcome/assets/`

Pantalla de bienvenida al iniciar la sesión Live.

## Purpose

- Dar la bienvenida al usuario.
- Mostrar resumen de información del sistema: CPU, RAM (usada de total con porcentaje), espacio de `/`, uptime, Kernel, SO, Arquitectura y Hostname.
- Ofrecer accesos rápidos a instalación con Calamares, GitHub y comunidad.

El footer muestra `Linux • <Entorno> • ChurrOS <Versión>` detectado dinámicamente con `churros_services::version::desktop_name()` y `churros_services::version::distro()`.

## Traducciones

La interfaz de las apps Rust va en castellano, escrita directamente en el código. El catálogo de gettext en `po/` sigue apuntando a la interfaz en Python anterior (`preferences/pages/*.py`, `popups/*/widgets/*.py`), que ya no está en el repositorio: es decir, **las traducciones no se aplican a nada de lo que el usuario ve hoy**.

`./churros check` valida la sintaxis de los `.po`, no que sirvan para la interfaz actual, y lo dice en pantalla. Conectar gettext (o `i18n-embed`) a las apps Rust es trabajo pendiente, no una función que esté activa a medio hacer.

## Valores por defecto

`/usr/share/churros/defaults/` es una copia de `etc/skel/.config/` y "Restaurar valores por defecto" la copia sobre `~/.config/`. Las dos tienen que estar sincronizadas: si divergen, restaurar da una configuración distinta de la de una instalación nueva. `./churros check` lo verifica fichero a fichero.

## Stack

- GTK 4 + Libadwaita (gtk4-rs / libadwaita-rs)
- Sin psutil: CPU, RAM, kernel y hostname salen de `/proc` y `/etc/os-release`

## Window

- Tamaño predeterminado: 900×680 (redimensionable, tamaño mínimo 480×400)
- `AdwToolbarView` como contenedor: la `AdwHeaderBar` va arriba y la toolbar view gestiona los controles de ventana
- El contenido va dentro de un `AdwClamp` (máximo 840 px) sobre un `ScrolledWindow`, para que en pantallas anchas las cards queden centradas y no se repartan de lado a lado
- Layout vertical responsivo con desplazamiento automático
- En Niri se maximiza automáticamente; en XFCE se abre en ventana centrada con decoraciones completas
- El título son dos labels (`.title-plain` y `.title-accent`), no markup Pango: el color de acento sale de `--accent` (`~/.config/churros/accent.css`, pywal o churros-settings) y no de un valor fijo en el código
- CSS: `/usr/share/churros/styles/churros.css` + `assets/style.css`

## Structure

```text
rust/churros-welcome/
├── Cargo.toml
├── assets/
└── src/
    ├── main.rs
    ├── header.rs
    ├── cards.rs            # FlowBox responsivo (SystemCard + 3 ActionCards)
    ├── footer.rs
    ├── action_card.rs
    ├── system_card.rs      # Información de CPU, RAM, Kernel, SO, Arch, Hostname
    ├── system_info.rs
    ├── actions.rs          # URLs + calamares.desktop
    └── assets.rs
```

## Cards en FlowBox

| Tarjeta / Icono | Título | Descripción / Acción |
|-----------------|--------|----------------------|
| `computer-symbolic` | Información | CPU, RAM (usada de total con porcentaje), espacio libre de `/`, uptime, Kernel, SO, Arquitectura y Hostname |
| `install.svg` | Install ChurrOS | Lanza el instalador `calamares.desktop` |
| `github.svg` | GitHub | Abre el repositorio oficial |
| `community.svg` | Comunidad | Abre el enlace a la comunidad de ChurrOS |

Son cuatro tarjetas. Con el `AdwClamp` de 840 px entran dos por fila (cada tarjeta pide 280 px más separación), así que el reparto real es 2×2 en ventana grande y una columna al estrecharse. `max_children_per_line` es 4 para que pueda aprovechar más espacio si el clamp cambia.

La tarjeta de información no es un botón: es un `GtkBox`, y por eso no se eleva al pasar el ratón (el hover solo se aplica a `.action-card`).

## Tests

`system_info.rs` separa el acceso a `/proc` de la lógica: los parsers son funciones puras (`parse_cpu`, `parse_memory`, `parse_uptime`, `parse_os_release`, `format_uptime`, `format_filesystem`) y hay tests para cada una, incluidos los casos en los que el kernel no publica `MemAvailable` y la variante de CPU sin `model name` de aarch64.

```bash
cargo test -p churros-welcome
```

## Desktop Entry

`archiso/airootfs/usr/share/applications/churros-welcome.desktop` — `Exec=churros-welcome`.

---

# churros-control-center

**Path:** `rust/control-center/`
**Binario:** `/usr/bin/churros-control-center`
**Desktop entry:** `archiso/airootfs/usr/share/applications/churros-control-center.desktop`
**Atajo:** ninguno en Niri. `Mod+C` abre el centro de control de Noctalia. Este binario se abre desde el lanzador o desde Waybar.

Centro de control con tarjetas que abren el popup correspondiente (`churros-popup <nombre>`).

## Window

- 430×650, redimensionable con scroll para resoluciones bajas
- Header: logo, título, botón de settings (`churros-settings`), botón de power y botón de cierre
- Grid 2×2 (red, bluetooth, brillo, batería) + tarjeta de audio a ancho completo
- Refresh asíncrono cada 2 s (`churros_services` en un hilo)

## Cards

| Posición | Tarjeta | Popup |
|----------|---------|-------|
| 0,0 | Network | `churros-popup network` |
| 0,1 | Bluetooth | `churros-popup bluetooth` |
| 1,0 | Brightness | `churros-popup brightness` |
| 1,1 | Battery | `churros-popup battery` |
| debajo | Audio | (controles in-place + popup de audio) |

## Services

Usa el crate `churros_services` (`rust/services/`): wifi, ethernet, bluetooth, brightness, battery, audio. Detalle en `docs/services.md`.

Logs de arranque: `/tmp/churros/churros-control-center.log`.

---

# churros-settings

**Path:** `rust/preferences/`
**Binario:** `/usr/bin/churros-settings`
**Atajo:** `Mod + P` (niri)

App de configuración principal, estilo System Settings con colores ChurrOS. Documentación dedicada en `docs/preferences.md`.

Logs: `/tmp/churros/churros-settings.log`.

---

# churros-popup

**Path:** `rust/popups/`
**Binario:** `/usr/bin/churros-popup`

Un solo binario con los seis popups y toggle nativo (pidfiles en `/tmp/churros/`). Documentación en `docs/popups.md`.

---

# fuzzel (launcher)

**Path:** paquete del sistema (`archiso/packages.x86_64`).
**Atajo:** `Mod + Shift + Space` (el lanzador de Noctalia ocupa `Mod + Space`)
**Waybar:** `custom/launcher` → `fuzzel`

No es una app ChurrOS. Config: `archiso/airootfs/etc/skel/.config/fuzzel/fuzzel.ini`.

---

# churros-ui (planificado)

**Estado:** no implementado.

Hoy cada app tiene su propio CSS. A largo plazo convendría un crate o stylesheet compartido más allá de `/usr/share/churros/styles/churros.css`.

---

# Packaging

| Qué | Dónde |
|-----|--------|
| Código | `rust/<crate>/` |
| Binario en la ISO | `archiso/airootfs/usr/bin/<app>` (generado, no versionado) |
| Assets | `archiso/airootfs/usr/share/churros/<app>/` |
| Desktop entries | `archiso/airootfs/usr/share/applications/` |

---

# Development

1. Edita el crate en `rust/<app>/`.
2. Ábrelo en el host (sin ISO):

```bash
./churros apps doctor
./churros apps welcome
./churros apps settings
./churros apps control-center
./churros apps popup audio
```

Compila desde `rust/`. Los crates resuelven assets a `rust/<crate>/assets/` si no existe `/usr/share/churros/`. Hace falta sesión gráfica. Por defecto el modo preview no escribe configs del host ni ejecuta apagar/red/audio/gsettings; `--live-host` sí lo haría.

El instalador se previsualiza igual:

```bash
./churros apps calamares
```

Usa un overlay temporal: no toca `/etc/calamares`, no particiona, no pide Polkit y no reinicia el host. `./churros check` no abre ventanas; valida que el branding de Calamares cargue (YAML, imágenes, API del slideshow) y que el preview no cargue el módulo de particiones.

3. Para verlo en el Live:

```bash
./churros build
./churros run
```

---

# Future Work

- Empaquetar las apps como paquetes pacman propios.
- Completar i18n (los `.po` existen; las apps Rust aún no cargan gettext).
- churros-ui: widgets y CSS compartidos.
- Tests automatizados de las apps GTK.
