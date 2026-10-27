# Apps

Aplicaciones propias de ChurrOS. Todas están escritas en **Rust** con **gtk4-rs**; `churros-settings` usa además **libadwaita** (solo para la barra de título, `adw::HeaderBar`). En runtime, `/usr/share/churros/` solo guarda assets (CSS, SVG); los binarios los despliega `scripts/build-rust.sh`.

```text
rust/
├── Cargo.toml              # workspace
├── churros-welcome/        # binario churros-welcome
├── churros-tour/           # binario churros-tour (recorrido del primer inicio)
├── preferences/            # binario churros-settings
├── control-center/         # binario churros-control-center
├── popups/                 # binario churros-popup
└── services/               # crate churros_services (librería, no se despliega)
```

`build-rust.sh` copia a `archiso/airootfs/usr/bin/` el binario de cada crate con `deploy = true` en su `Cargo.toml` (el nombre es el `name` del paquete, no el del directorio: `preferences/` produce `churros-settings`). También copia `rust/<crate>/assets/` a `archiso/airootfs/usr/share/churros/<binario>/assets/`. Los binarios no se versionan.

En desarrollo, si no existe `/usr/share/churros/<binario>/`, cada crate usa sus assets de `rust/<crate>/assets/`.

| App | Binario | Cómo se abre | Log | Documentación |
|-----|---------|--------------|-----|---------------|
| Bienvenida | `churros-welcome` | Autostart en el Live; `Mod+W` en Niri | — | [abajo](#churros-welcome) |
| Tour | `churros-tour` | Primer inicio del sistema instalado | — | [churros-tour.md](churros-tour.md) |
| Ajustes | `churros-settings` | `Mod+P` (Niri); `Super+I` / `Super+S` (XFCE) | `/tmp/churros/settings.log` | [preferences.md](preferences.md) |
| Centro de control | `churros-control-center` | Lanzador; `Super+A` / `Super+C` (XFCE) | `/tmp/churros/control-center.log` | [abajo](#churros-control-center) |
| Popups | `churros-popup <nombre>` | Centro de control, Waybar o a mano | — | [popups.md](popups.md) |

En la sesión Niri por defecto, según los comentarios de `config.kdl`, el centro de control de Noctalia (`Mod+C`) ya cubre red, audio, bluetooth, brillo y batería; `churros-control-center` y `churros-popup` siguen en la ISO y se abren desde el lanzador, sin atajo. `./churros check` falla si alguna línea no comentada de `config.kdl` los nombra.

---

## Traducciones

La interfaz de las apps Rust va en castellano, escrita directamente en el código. El catálogo de gettext en `po/` sigue apuntando a la interfaz en Python anterior (`preferences/pages/*.py`, `popups/*/widgets/*.py`), que ya no está en el repositorio: es decir, **las traducciones no se aplican a nada de lo que el usuario ve hoy**.

`./churros check` valida la sintaxis de los `.po`, no que sirvan para la interfaz actual, y lo dice en pantalla. Conectar gettext (o `i18n-embed`) a las apps Rust es trabajo pendiente, no una función que esté activa a medio hacer.

---

## churros-welcome

**Path:** `rust/churros-welcome/`
**Binario:** `/usr/bin/churros-welcome` (app id `org.churros.welcome`)
**Autostart:** `spawn-at-startup "churros-welcome"` en `niri/config.kdl` y `.config/autostart/churros-welcome.desktop` (XFCE, con `--live-only`: fuera del Live sale sin abrir ventana). Calamares borra los dos al instalar; como el `sed` de `shellprocess-cleanup.conf` elimina toda línea de `config.kdl` que contenga `churros-welcome`, también desaparece el atajo `Mod+W` del sistema instalado.
**Assets:** `archiso/airootfs/usr/share/churros/churros-welcome/assets/` (generado por `build-rust.sh`)

Pantalla de bienvenida al iniciar la sesión Live.

### Qué hace

- Da la bienvenida al usuario.
- Muestra un resumen del sistema: CPU, RAM (usada de total con porcentaje), espacio de `/`, uptime, Kernel, SO, Arquitectura y Hostname.
- Ofrece accesos rápidos a la instalación con Calamares, a GitHub y a la comunidad.

El footer muestra `Linux • <Entorno> • ChurrOS <Versión>`, con `churros_services::version::desktop_name()` y `churros_services::version::distro()`.

### Stack

- GTK 4 (gtk4-rs), sin libadwaita.
- Sin psutil: CPU, RAM, kernel y hostname salen de `/proc` y `/etc/os-release`.

### Ventana

- Tamaño predeterminado: 900×680 (redimensionable, tamaño mínimo 480×400).
- `gtk::HeaderBar` plana como barra de título (`set_titlebar`).
- El contenido es un `gtk::Box` centrado dentro de un `ScrolledWindow`.
- En Niri se abre con la regla de ventana de `org.churros.welcome` (opacidad 0.9, blur y esquinas de 18 px).
- El título son dos labels (`.title-plain` y `.title-accent`), no markup Pango: el color de acento sale de `--accent` (`~/.config/churros/accent.css`, pywal o churros-settings) y no de un valor fijo en el código. `accent.css` se lee una vez al arrancar.
- CSS: `/usr/share/churros/styles/churros.css` + `assets/style.css` + `accent.css`.

### Estructura

```text
rust/churros-welcome/
├── Cargo.toml
├── assets/
└── src/
    ├── main.rs
    ├── header.rs
    ├── cards.rs            # FlowBox responsivo (SystemCard + ActionCards)
    ├── footer.rs
    ├── action_card.rs
    ├── system_card.rs      # Información de CPU, RAM, Kernel, SO, Arch, Hostname
    ├── system_info.rs
    ├── actions.rs          # URLs + calamares.desktop
    └── assets.rs
```

### Tarjetas

| Tarjeta / Icono | Título | Descripción / Acción |
|-----------------|--------|----------------------|
| `computer-symbolic` | Información | CPU, RAM (usada de total con porcentaje), espacio libre de `/`, uptime, Kernel, SO, Arquitectura y Hostname |
| `install.svg` | Install ChurrOS | Lanza el instalador `calamares.desktop` |
| `github.svg` | GitHub | Abre el repositorio oficial |
| `community.svg` | Comunidad | Abre la invitación de Discord |

En el Live hay cuatro tarjetas. En el sistema instalado se omite «Install ChurrOS»: solo se añade si existe `/run/archiso` (o con `CHURROS_DEV`, en la vista previa). Si no encuentra `calamares.desktop` o no puede lanzarlo, muestra «Installer not available on this system.».

El `FlowBox` admite hasta cuatro tarjetas por fila (`max_children_per_line = 4`) y baja a una columna al estrechar la ventana.

La tarjeta de información no es un botón: es un `GtkBox`, y por eso no se eleva al pasar el ratón (el hover solo se aplica a `.action-card`).

### Tests

`system_info.rs` separa el acceso a `/proc` de la lógica: los parsers son funciones puras (`parse_cpu`, `parse_memory`, `parse_uptime`, `parse_os_release`, `format_uptime`, `format_filesystem`) y hay tests para cada una, incluidos los casos en los que el kernel no publica `MemAvailable` y la variante de CPU sin `model name` de aarch64.

```bash
cargo test -p churros-welcome
```

### Desktop entry

`archiso/airootfs/usr/share/applications/churros-welcome.desktop` — `Exec=churros-welcome`.

---

## churros-tour

**Path:** `rust/churros-tour/`
**Binario:** `/usr/bin/churros-tour` (app id `org.churros.tour`)
**Desktop entry:** `archiso/airootfs/usr/share/applications/churros-tour.desktop`

Recorrido del primer inicio en el sistema instalado: atajos de la edición y selección de apps que se instalan con `yay`. No se abre en el Live. Documentación en [churros-tour.md](churros-tour.md).

---

## churros-control-center

**Path:** `rust/control-center/`
**Binario:** `/usr/bin/churros-control-center` (app id `org.churros.controlcenter`)
**Desktop entry:** `archiso/airootfs/usr/share/applications/churros-control-center.desktop`
**Atajo:** ninguno en Niri (`Mod+C` abre el centro de control de Noctalia); `Super+A` / `Super+C` en XFCE. También desde el lanzador y, si se usa Waybar con la config del skel, desde `custom/control-center`.

Centro de control con tarjetas que abren el popup correspondiente (`churros-popup <nombre>`).

### Ventana

- 430×650, tamaño fijo y sin decoración; scroll vertical para resoluciones bajas. Escape cierra.
- Header: logo, título, botón de ajustes (`churros-settings`), botón de energía (abre `churros-popup power`) y botón de cierre.
- Grid 2×2 (red, bluetooth, brillo, batería) + tarjeta de audio a ancho completo.
- Refresco asíncrono cada 1 s (`churros_services` en un hilo).

### Tarjetas

| Posición | Tarjeta | Popup |
|----------|---------|-------|
| 0,0 | Network | `churros-popup network` |
| 0,1 | Bluetooth | `churros-popup bluetooth` |
| 1,0 | Brightness | `churros-popup brightness` |
| 1,1 | Battery | `churros-popup battery` |
| debajo | Audio | Slider y clic en el icono para silenciar; no abre popup |

Al abrir un popup, la ventana del centro de control se cierra.

### Servicios

Usa el crate `churros_services` (`rust/services/`): wifi, ethernet, bluetooth, brightness, battery, audio. Detalle en [services.md](services.md).

Logs de arranque: `/tmp/churros/control-center.log`.

---

## churros-settings

**Path:** `rust/preferences/`
**Binario:** `/usr/bin/churros-settings` (app id `org.churros.preferences`)
**Atajo:** `Mod+P` (Niri); `Super+I` / `Super+S` (XFCE)

App de configuración principal, estilo System Settings con colores ChurrOS. Documentación en [preferences.md](preferences.md).

Logs: `/tmp/churros/settings.log` (incluye stdout/stderr del proceso).

---

## churros-popup

**Path:** `rust/popups/`
**Binario:** `/usr/bin/churros-popup`

Un solo binario con los seis popups (`volume` es alias de `audio`) y toggle nativo (pidfiles en `/tmp/churros/`). Documentación en [popups.md](popups.md).

---

## fuzzel (lanzador alternativo)

**Path:** paquete del sistema (`archiso/packages.x86_64`).
**Atajo:** `Mod+Shift+Space` en Niri (el lanzador de Noctalia ocupa `Mod+Space`).
**Waybar:** `custom/launcher` → `fuzzel` (solo si se usa Waybar; la sesión Niri por defecto usa Noctalia).

No es una app ChurrOS. Config: `archiso/airootfs/etc/skel/.config/fuzzel/fuzzel.ini` (y su copia en `usr/share/churros/defaults/fuzzel/`).

`fuzzel.ini` lleva `launch-prefix=setsid -f` en `[main]`: cada app abierta desde Fuzzel arranca en su propia sesión, desligada del proceso que abrió Fuzzel. Se añadió porque, con Waybar como barra (Waybar lanza Fuzzel desde `custom/launcher`), reiniciar Waybar cerraba todas las apps abiertas desde el lanzador. La página Fuzzel de churros-settings edita las claves en su sitio y conserva esa línea.

---

## churros-ui (planificado)

**Estado:** no implementado.

Hoy cada app tiene su propio CSS. A largo plazo convendría un crate o stylesheet compartido más allá de `/usr/share/churros/styles/churros.css`.

---

## Empaquetado

| Qué | Dónde |
|-----|--------|
| Código | `rust/<crate>/` |
| Binario en la ISO | `archiso/airootfs/usr/bin/<binario>` (generado por `build-rust.sh`, no versionado) |
| Assets | `archiso/airootfs/usr/share/churros/<binario>/assets/` (copiados por `build-rust.sh` desde `rust/<crate>/assets/`) |
| Desktop entries | `archiso/airootfs/usr/share/applications/` |

---

## Desarrollo

1. Edita el crate en `rust/<crate>/`.
2. Compila, prueba y pasa clippy como el CI con `./churros rust` (en el contenedor; `--host` en este equipo).
3. Ábrelo en el host (sin ISO):

```bash
./churros apps doctor
./churros apps welcome
./churros apps settings
./churros apps control-center
./churros apps tour
./churros apps popup audio
```

Compila desde `rust/`. Los crates resuelven assets a `rust/<crate>/assets/` si no existe `/usr/share/churros/`. Hace falta sesión gráfica. Por defecto el modo preview usa un HOME temporal y stubs en `PATH`, no escribe configs del host ni ejecuta apagar/red/audio/gsettings; `--live-host` sí lo haría. Detalle en [cli.md](cli.md).

El instalador se previsualiza igual:

```bash
./churros apps calamares
```

Usa un overlay temporal: no toca `/etc/calamares`, no particiona, no pide Polkit y no reinicia el host. `./churros check` no abre ventanas; valida que el branding de Calamares cargue (YAML, imágenes, API del slideshow) y que el preview no cargue el módulo de particiones.

4. Para verlo en el Live:

```bash
./churros build
./churros run
```

---

## Trabajo futuro

- Empaquetar las apps como paquetes pacman propios.
- Completar i18n (los `.po` existen; las apps Rust aún no cargan gettext).
- churros-ui: widgets y CSS compartidos.
- Tests automatizados de las apps GTK.
