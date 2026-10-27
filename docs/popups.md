# Popups

Este documento describe `churros-popup`: ventanas pequeñas de red, audio, bluetooth, brillo, batería y energía. Los seis popups viven en **un solo binario Rust** con toggle nativo.

Quién los abre:

- `churros-control-center`: sus tarjetas y el botón de energía lanzan `churros-popup <nombre>`.
- Waybar, si está en marcha. Solo la edición Pi la arranca (`churros-pi-session`), con `/usr/share/churros/pi/waybar/config.jsonc`, que cablea `churros-popup brightness` y `churros-popup audio`.
- El usuario, a mano o desde un atajo propio.

En la sesión Niri por defecto no se usan: según el comentario de `config.kdl`, el centro de control de Noctalia (`Mod+C`) ya cubre red, audio, bluetooth, brillo y batería, y `./churros check` falla si alguna línea no comentada de `config.kdl` nombra `churros-popup`. `Mod+Shift+E` abre `wlogout`, no el popup de energía.

---

## Estructura

```text
rust/popups/
├── Cargo.toml              # name = "churros-popup", deploy = true
├── assets/                 # CSS (copia de desarrollo)
└── src/
    ├── main.rs             # CLI + toggle/reemplazo
    ├── popup.rs            # PopupWindow + header + carga de CSS
    ├── audio.rs
    ├── battery.rs
    ├── bluetooth.rs
    ├── brightness.rs
    ├── network.rs
    └── power.rs
```

Assets de runtime: `/usr/share/churros/churros-popup/assets/` (desplegados por `build-rust.sh`; CSS compartido en `/usr/share/churros/styles/churros.css`).

Uso:

```bash
churros-popup {network|audio|volume|bluetooth|power|brightness|battery}   # volume = audio
```

Otro nombre → exit 64.

---

## Funcionamiento

1. Alguien ejecuta `churros-popup <nombre>`.
2. El binario lee `/tmp/churros/popup.pid` y `/tmp/churros/popup.name`.
3. Si no hay popup → abre el solicitado (app id `org.churros.popup.<nombre>`).
4. Si el activo es el mismo → lo mata (toggle off) y sale.
5. Si hay otro → lo mata y abre el nuevo.

Antes de matar un PID comprueba en `/proc/<pid>/cmdline` que es un `churros-popup`, para no señalar a otro proceso que haya reutilizado el PID. El toggle está en `rust/popups/src/main.rs`.

### Estado en disco

```text
/tmp/churros/popup.pid     # PID del popup actual
/tmp/churros/popup.name    # Nombre del popup activo
```

Si el PID murió, limpia los archivos antes de lanzar uno nuevo. Al cerrar la ventana también los borra. Escape cierra el popup.

---

## Popups disponibles

| Nombre | Descripción | Crate de servicios |
|--------|-------------|--------------------|
| `audio` (`volume`) | Volumen y mute de la salida por defecto | `churros_services::audio` |
| `battery` | Porcentaje, estado, tiempo restante | `churros_services::battery` |
| `bluetooth` | Toggle y lista real vía `bluetoothctl` | `churros_services::bluetooth` |
| `brightness` | Slider de brillo | `churros_services::brightness` |
| `network` | Wi-Fi + Ethernet | `churros_services::wifi` + `ethernet` |
| `power` | Lock, logout, suspend, hibernate (solo si hay swap), restart, shutdown | `churros_services::power` |

---

## Ventana base: PopupWindow

`popup.rs` define la ventana común:

- 320×400, no redimensionable, sin decoración
- Clases CSS `popup` y `churros-glass`
- Header con icono + título
- `add(widget)` para el cuerpo
- CSS: `churros.css` + `common.css` + el CSS del popup + `~/.config/churros/accent.css` (leído al abrir)
- `run_bg` ejecuta el trabajo pesado en un hilo y devuelve el resultado al hilo de GTK

---

## Integración con Waybar

La config de Waybar del skel (`archiso/airootfs/etc/skel/.config/waybar/config.jsonc`) abre los popups así, pero ninguna sesión la arranca: solo se usa si el usuario lanza Waybar a mano. La edición Pi usa su propia config (`/usr/share/churros/pi/waybar/config.jsonc`), con `backlight` → `churros-popup brightness` y `pulseaudio` → `churros-popup audio`.

```jsonc
"network":      { "on-click": "churros-popup network" }
"battery":      { "on-click": "churros-popup battery" }
"bluetooth":    { "on-click": "churros-popup bluetooth" }
"backlight":    { "on-click": "churros-popup brightness" }
"pulseaudio":   { "on-click": "churros-popup audio" }
```

Acciones secundarias de Waybar (no pasan por el popup):

- `pulseaudio` → click derecho silencia; scroll ajusta volumen
- `backlight` → scroll ajusta brillo con `brightnessctl`

---

## Añadir un popup

1. Añade un módulo en `rust/popups/src/` que construya un `PopupWindow`.
2. En `main.rs`, declara `mod <nombre>;`, añádelo a `build_window` y al array `POPUPS` (y actualiza su longitud, `[&str; N]`).
3. Añade el nombre a `POPUPS` en `scripts/cli/apps.sh`, para que `./churros apps popup <nombre>` lo acepte.
4. Añade CSS/iconos en `assets/` (`build-rust.sh` los despliega a `archiso/airootfs/usr/share/churros/churros-popup/assets/`).
5. Enlázalo desde el control center o Waybar. No desde `config.kdl`: `./churros check` lo rechaza.

---

## Limitaciones

- Un solo popup a la vez (intencional).
- Estado en `/tmp`: al reiniciar se pierde.
- No se cierran solos al perder el foco; Escape o toggle.
- Sin tests automatizados GTK.

---

## Trabajo futuro

- Cierre al perder foco.
- Animaciones de entrada/salida.
- Varios popups a la vez (sidebar de widgets).
