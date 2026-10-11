# Popups

Este documento describe el sistema de popups de ChurrOS: ventanas pequeñas al interactuar con la barra (Noctalia o Waybar) o con atajos de teclado.

Los seis popups viven en **un solo binario Rust** (`churros-popup`) con toggle nativo. Reemplazan al wrapper bash y a los procesos Python por popup.

---

# Overview

```text
rust/popups/
├── Cargo.toml              # name = "churros-popup", deploy = true
├── assets/                 # CSS e iconos (copia de desarrollo)
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
churros-popup {network|audio|bluetooth|power|brightness|battery}
```

Otro nombre → exit 64.

---

# How It Works

## Architecture

1. Noctalia, Waybar o niri ejecuta `churros-popup <nombre>`.
2. El binario lee `/tmp/churros/popup.pid` y `/tmp/churros/popup.name`.
3. Si no hay popup → abre el solicitado (misma ventana GTK, `org.churros.popup.<nombre>`).
4. Si el activo es el mismo → lo mata (toggle off) y sale.
5. Si hay otro → lo mata y abre el nuevo.

El toggle ya no es un script bash: está en `rust/popups/src/main.rs`.

## Estado en disco

```text
/tmp/churros/popup.pid     # PID del popup actual
/tmp/churros/popup.name    # Nombre del popup activo
```

Si el PID murió, limpia los archivos antes de lanzar uno nuevo. Al cerrar la ventana también los borra. Escape cierra el popup.

---

# Available Popups

| Nombre | Descripción | Crate de servicios |
|--------|-------------|--------------------|
| `audio` | Volumen, mute, dispositivo de salida | `churros_services::audio` |
| `battery` | Porcentaje, estado, tiempo restante | `churros_services::battery` |
| `bluetooth` | Toggle y lista real vía `bluetoothctl` | `churros_services::bluetooth` |
| `brightness` | Slider de brillo | `churros_services::brightness` |
| `network` | Wi-Fi + Ethernet | `churros_services::wifi` + `ethernet` |
| `power` | Lock, logout, suspend, hibernate, restart, shutdown | `churros_services::power` |

---

# Base: PopupWindow

`popup.rs` define la ventana común:

- 320×400, no redimensionable, sin decoración
- Clase CSS `popup`
- Header con icono + título
- `add(widget)` para el cuerpo
- CSS: `churros.css` + `common.css` + el CSS del popup

---

# Integration with Waybar

Ejemplos de `archiso/airootfs/etc/skel/.config/waybar/config.jsonc`:

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

En la sesión Niri esos atajos ya no están: el centro de control de Noctalia cubre red, audio, bluetooth, brillo y batería (`noctalia msg panel-toggle control-center`, con pestaña `audio`, `network`, `bluetooth`, `monitor` o `power`). `churros-popup` sigue instalado para Waybar y para abrirlo a mano. `Mod+Shift+E` abre `wlogout`, no el popup de energía.

---

# Adding a New Popup

1. Añade un módulo en `rust/popups/src/` que construya un `PopupWindow`.
2. Regístralo en `build_window` y en el array `POPUPS` de `main.rs`.
3. Añade CSS/iconos en `assets/` (build-rust.sh lo despliega a `archiso/airootfs/usr/share/churros/churros-popup/assets/`).
4. Enlázalo desde Noctalia, Waybar o niri.

---

# Limitations

- Un solo popup a la vez (intencional).
- Estado en `/tmp`: al reiniciar se pierde.
- No se cierran solos al perder el foco; Escape o toggle.
- Sin tests automatizados GTK.

---

# Future Work

- Cierre al perder foco.
- Animaciones de entrada/salida.
- Varios popups a la vez (sidebar de widgets).
