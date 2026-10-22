# Services

Este documento describe la capa de servicios que usan las apps oficiales.

`churros_services` es un crate Rust (`rust/services/`, paquete `churros-services`, `deploy = false`) que envuelve comandos del sistema y expone funciones sencillas. Lo usan todas las apps:

- `churros-popup` y `churros-control-center`: hardware y sesión (audio, batería, bluetooth, brillo, red, energía).
- `churros-settings`: `jsonc`, `waybar_style`, `noctalia`, `version` y los helpers `run`, `which`, `home_dir`. El resto de sus servicios (tema, acento, niri, mako, fondo, …) vive en `rust/preferences/src/services/`; ver [preferences.md](preferences.md).
- `churros-welcome` y `churros-tour`: `version`, `theme` y `home_dir` (el Tour, también `which`).

La referencia de la API (tipos y firmas) se genera desde el código, así que no se copia aquí:

```bash
cargo doc --manifest-path rust/Cargo.toml -p churros-services --no-deps --open
```

---

## Módulos

```text
rust/services/src/
├── lib.rs          # run / spawn / which / home_dir
├── audio.rs        # wpctl: volumen y mute de salida y entrada, sinks/sources, sink por defecto
├── battery.rs      # upower: porcentaje, estado, tiempos e icono (Nerd Font)
├── bluetooth.rs    # bluetoothctl / rfkill: adaptador, escaneo, dispositivos, conectar/emparejar
├── brightness.rs   # brightnessctl + /sys/class/backlight
├── dev.rs          # Modo dry-run de CHURROS_DEV=1 para ./churros apps
├── ethernet.rs     # nmcli: dispositivo, conexión, velocidad e IP; conectar/desconectar
├── jsonc.rs        # JSON con comentarios // y comas finales -> Result<Value, JsoncError>
├── noctalia.rs     # ¿Noctalia es el shell? ¿La sesión ejecuta Waybar/Mako? Modo y fondo de Noctalia
├── power.rs        # Bloquear, cerrar sesión, suspender, hibernar, reiniciar, apagar
├── theme.rs        # is_dark() compartido: dark-flag -> gsettings color-scheme -> oscuro
├── version.rs      # distro() (VERSION), from_os_release(), edition(), desktop_name()
├── waybar_style.rs # Utilidades CSS para Waybar: colores, selectores, @define-color, parches de style.css
└── wifi.rs         # nmcli: redes, conexión activa, conectar/olvidar, tráfico de la interfaz
```

Patrón:

- Funciones libres (no hay clases estáticas).
- `get()` / `available()` leen el sistema en el momento.
- Sin estado interno: cada llamada refleja el hardware actual.

---

## Helpers comunes

```rust
pub type RunOut = (i32, String, String);

pub fn run(cmd: &[&str], timeout_ms: u64) -> Option<RunOut>;
pub fn spawn(cmd: &[&str]);
pub fn which(bin: &str) -> bool;
pub fn home_dir() -> String;
```

- `run` captura stdout/stderr y devuelve `None` si falla el spawn o vence el timeout. La salida que no es UTF-8 se pierde sin error.
- `spawn` lanza el comando sin esperar (fire-and-forget).
- `home_dir` devuelve `HOME`; si no está, el directorio de `getent passwd $USER`, y si eso falla, `/root`.

---

## Detalles que conviene saber

### power

| Función | Comando |
|---------|---------|
| `lock()` | `xflock4` en XFCE; si no, `loginctl lock-session` |
| `logout()` | Según el escritorio: `niri msg action quit`, `xfce4-session-logout --logout --fast`, `hyprctl dispatch exit`, `swaymsg exit` o, como último recurso, `loginctl terminate-user` |
| `suspend()` | `systemctl suspend` |
| `hibernate()` | `systemctl hibernate`. No comprueba nada: el popup de energía oculta la opción si `can_hibernate()` (hay swap) es falso |
| `restart()` | `systemctl reboot` |
| `shutdown()` | `systemctl poweroff` |

### theme

`theme::is_dark()` lee `~/.cache/churros-theme/dark-flag` (lo escribe churros-settings); si no existe, consulta `gsettings get org.gnome.desktop.interface color-scheme`; por defecto, oscuro. No consulta Noctalia: eso lo hace `ThemeService` de churros-settings.

### version

- `distro()`: contenido de `VERSION` (raíz del repo), embebido al compilar.
- `from_os_release()`: `VERSION_ID` de `/etc/os-release`, con `distro()` como respaldo.
- `edition()`: `/etc/churros-edition`, luego `VARIANT_ID`, luego el escritorio de la sesión (`xfce` o `niri`). churros-settings la usa para decidir qué páginas registra.
- `desktop_name()`: nombre del escritorio para la interfaz (el footer de welcome). Devuelve `Niri` para cualquier edición que no sea XFCE, server, Hyprland o Sway, incluida la Pi (labwc).

### jsonc

`parse(raw)` quita los comentarios `//` que están fuera de strings (una URL dentro de una cadena no se toca) y las comas finales, y devuelve `Result<Value, JsoncError>`; nunca un `{}` silencioso. Lo usa `WaybarService` para `config.jsonc`.

### dev

Modo de seguridad para desarrollo (`CHURROS_DEV=1`, lo pone `./churros apps`):

- Las lecturas (volumen, redes, batería…) se ejecutan normalmente.
- `run` no ejecuta los comandos que cambian el sistema (`wpctl set-*`, `nmcli … up/down/connect`, `bluetoothctl connect`, `systemctl reboot/poweroff`, `pkill`, …): devuelve éxito simulado `Some((0, "", ""))` y lo registra en stderr como `[churros-dev] blocked: <comando>`. La lista está en `dev::is_mutation`.
- `spawn` no lanza ningún comando en este modo; solo lo registra.

---

## Buenas prácticas

- No guardar estado: cada llamada lee el sistema.
- Comprobar `available` antes de pintar widgets.
- Timeouts cortos (`run`) y llamadas fuera del hilo de UI: el control center refresca en un hilo aparte y los popups usan `run_bg`.
- Presentación (iconos, porcentajes) en el widget, no en el servicio, salvo iconos que el servicio ya calcula (batería).

---

## Trabajo futuro

- Audio: elegir sink desde el control center con la lista que ya expone `list_sinks`.
- Notificaciones: una API para que las apps manden avisos. En la sesión Niri por defecto Mako no se ejecuta (`noctalia.rs` lo da por sustituido por Noctalia).
- Tema dinámico ante batería baja o red perdida.
