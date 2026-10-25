# Escritorio por edición

Este documento describe el escritorio de cada edición de ChurrOS: Niri + Noctalia (edición por defecto), XFCE y Raspberry Pi (labwc). El inicio de sesión y el autologin están en [login-greeter.md](login-greeter.md); el usuario live y el orden de arranque, en [live-services.md](live-services.md).

La configuración de usuario vive en `archiso/airootfs/etc/skel/.config/`. Durante el build de la ISO, `desktop.sh` (lo ejecuta `customize_airootfs.sh` en el chroot de mkarchiso) la copia a `/home/churros/`, así que el usuario live ya la lleva dentro del squashfs. En el sistema instalado, cada usuario nuevo la recibe del skel.

---

## Resumen

| Edición | Sesión | Compositor / gestor de ventanas | Barra | Notificaciones | Lanzador |
|---|---|---|---|---|---|
| niri | `niri` en el Live, `churros-niri-session` instalado | Niri (Wayland) | Noctalia | Noctalia | Noctalia (`Mod+Space`); Fuzzel como alternativa (`Mod+Shift+Space`) |
| xfce | `churros-xfce-session` (X11) | xfwm4 (el autostart lanza también picom) | Panel de XFCE (abajo) | `xfce4-notifyd` | Whisker Menu |
| pi | `churros-pi-session` | labwc (Wayland) | Waybar (config propia de Pi) | `mako` está instalado; la sesión no lo lanza (ver [Raspberry Pi](#raspberry-pi-labwc)) | Fuzzel (`Super+D` o el botón de Waybar) |
| server | XFCE solo en la ISO, para el instalador | — | — | — | — |

La ISO i686 se construye como edición niri, pero Arch Linux 32 no empaqueta `niri` ni `noctalia` (ver la cabecera de `archiso/packages.i686`), así que no tiene sesión gráfica Niri. La edición server no arranca ningún escritorio en el sistema instalado ([server.md](server.md)).

---

## Niri

**Path:** `archiso/airootfs/etc/skel/.config/niri/config.kdl` (copia idéntica en `archiso/airootfs/usr/share/churros/defaults/niri/config.kdl`, que usa "restaurar valores por defecto").

Niri es el compositor Wayland de la edición por defecto. Es un compositor de mosaico desplazable (scrollable-tiling) escrito en Rust. Toda la configuración vive en un solo archivo `config.kdl` en formato KDL. XFCE y la edición Pi no usan este archivo.

### Entorno y decoraciones

```kdl
environment {
    QT_QPA_PLATFORM "wayland"
    GDK_BACKEND "wayland"
    MOZ_ENABLE_WAYLAND "1"
}

cursor {
    xcursor-size 24
}

prefer-no-csd
```

Fuerza a las apps Qt y GTK a usar Wayland en lugar de XWayland cuando es posible. Firefox usa Wayland nativo gracias a `MOZ_ENABLE_WAYLAND`. `prefer-no-csd` pide a las ventanas que no dibujen sus propias decoraciones (ver [Transparencia y blur en Niri](#transparencia-y-blur-en-niri)). El bloque global `blur { ... }` ajusta la intensidad del desenfoque.

### Teclado

```kdl
input {
    keyboard {
        xkb {
            layout "us"
        }
    }
}
```

Layout de teclado US.

### Layout

```kdl
layout {
    gaps 8
    focus-ring {
        off
    }
    border {
        on
        width 2
        active-color "#DE8636"
        inactive-color "#766561"
    }
}
```

- Gaps: 8px entre ventanas y bordes.
- Sin anillo de foco; borde de 2px en tono cobre `#DE8636` en la ventana activa y `#766561` en las inactivas.

### Atajos

| Atajo | Acción |
|-------|--------|
| `SUPER + Return` | Abre foot (terminal) |
| `SUPER + Q` | Cierra la ventana activa |
| `SUPER + SHIFT + M` | Sale de Niri |
| `SUPER + F` | Maximiza la columna |
| `SUPER + SHIFT + F` | Pantalla completa |
| `SUPER + SPACE` | Abre el lanzador de Noctalia |
| `SUPER + SHIFT + SPACE` | Lanzador alternativo (Fuzzel) |
| `SUPER + C` | Abre el centro de control de Noctalia |
| `SUPER + P` | Abre los ajustes (churros-settings) |
| `SUPER + W` | Abre churros-welcome |
| `SUPER + S` | Abre Bazaar (tienda Flatpak) |
| `SUPER + E` | Abre Thunar (archivos) |
| `SUPER + SHIFT + E` | Menú de sesión (wlogout) |
| `SUPER + Escape` | Activa o desactiva el bloqueo de atajos (cuando una app los captura) |
| `SUPER + V` | Alterna la ventana entre flotante y mosaico |
| `SUPER + SHIFT + V` | Cambia el foco entre flotantes y mosaico |
| `SUPER + O` | Vista general (overview) |
| `SUPER + R` | Cambia el ancho de la columna entre los preajustes |
| `SUPER + SHIFT + /` | Muestra los atajos |
| `Print` | Captura interactiva |
| `Ctrl + Print` | Captura de toda la pantalla |
| `Alt + Print` | Captura de la ventana |
| `SUPER + 1-9` | Cambia al workspace N (1-9) |
| `SUPER + SHIFT + 1-9` | Mueve la ventana activa al workspace N |
| `SUPER + ←/→` | Mueve el foco entre columnas |
| `SUPER + ↑/↓` | Mueve el foco entre ventanas |
| `SUPER + SHIFT + ←/→` | Mueve la columna |
| `SUPER + SHIFT + ↑/↓` | Mueve la ventana |
| `XF86AudioRaise/Lower/Mute` | Volumen (con `allow-when-locked`) |
| `XF86AudioPlay/Next/Prev` | Control multimedia (con `allow-when-locked`) |
| `XF86MonBrightnessUp/Down` | Brillo (con `allow-when-locked`) |

### Autostart

```kdl
spawn-at-startup "churros-portal-start"
spawn-at-startup "/usr/lib/polkit-gnome/polkit-gnome-authentication-agent-1"
spawn-at-startup "noctalia"
spawn-at-startup "churros-welcome"
spawn-sh-at-startup "[ -f ~/.config/autostart/churros-tour.desktop ] && churros-tour"
```

- `churros-portal-start` arranca los portales (`xdg-desktop-portal` con el backend GTK; ver [live-services.md](live-services.md#churros-portal-start)).
- `polkit-gnome` es el agente de polkit: muestra el diálogo de contraseña cuando una app pide permisos de administrador.
- Noctalia arranca la barra, las notificaciones, el OSD, el lanzador y el centro de control. También pinta el fondo (`[wallpaper.default]` en `config.toml`, `default.png`). `swaybg` sigue instalado, pero no arranca con la sesión: si lo hiciera, se vería encima o debajo del fondo de Noctalia.
- `churros-welcome` muestra la pantalla de bienvenida.
- `churros-tour` (el recorrido guiado) solo arranca mientras exista `~/.config/autostart/churros-tour.desktop` ([churros-tour.md](churros-tour.md)).

Waybar, Fuzzel y Mako siguen instalados como alternativa; Fuzzel queda en `Mod+Shift+Space`.

---

## Transparencia y blur en Niri

Las apps de ChurrOS (`churros-popup`, `churros-control-center`, `churros-settings`, `churros-welcome` y `churros-tour`) tienen un aspecto de cristal: la transparencia sale del alfa del fondo en su CSS (GTK no soporta `backdrop-filter`) y el desenfoque real lo hace Niri. Cada una tiene una `window-rule` en `config.kdl`:

```kdl
window-rule {
    match app-id="org.churros.controlcenter"
    open-floating true
    opacity 0.9
    draw-border-with-background false
    background-effect {
        blur true
    }
    geometry-corner-radius 22
    clip-to-geometry true
}
```

`draw-border-with-background false` es imprescindible. En las ventanas que dibujan sus propias decoraciones (CSD), Niri pinta el borde como un rectángulo sólido detrás de toda la ventana, con el color del borde (`#DE8636` en la activa, `#766561` en las inactivas). `prefer-no-csd` solo evita ese fondo en las apps que negocian decoraciones del servidor con el protocolo xdg-decoration, y las apps GTK de ChurrOS no lo hacen. En una ventana translúcida ese rectángulo se ve a través del cristal y tapa el desenfoque: la ventana parece opaca y naranja o marrón. Con `draw-border-with-background false`, Niri solo dibuja el contorno del borde y el desenfoque se ve. Si añades una regla para otra ventana translúcida, ponle también esa línea (la regla de `foot` ya la lleva).

Las reglas de las apps de ChurrOS están entre los comentarios `// [CHURROS-GLASS-START]` y `// [CHURROS-GLASS-END]`. `churros-settings` usa esos marcadores para el modo rendimiento: cambia `blur true` por `blur false` (y al revés) solo dentro de ese bloque (`rust/preferences/src/services/niri_config.rs`). No borres ni muevas los marcadores. `./churros check` no comprueba que las reglas lleven `draw-border-with-background false`.

---

## Noctalia

**Binario:** `noctalia` (paquete `noctalia` de `[extra]`, también en Arch Linux ARM). Es Noctalia v5, escrita en C++ sin Qt ni Quickshell. Se controla con `noctalia msg <comando>` y escribe su log en `~/.cache/noctalia/noctalia.log`.

**Config:** `~/.config/noctalia/config.toml`. Noctalia fusiona en orden alfabético todos los `*.toml` de esa carpeta; el `settings.json` de la v4 ya no se lee. ChurrOS despliega una base en `archiso/airootfs/etc/skel/.config/noctalia/config.toml` y otra idéntica en `usr/share/churros/defaults/noctalia/` para que "restaurar valores por defecto" sea coherente. `noctalia config validate` comprueba el archivo.

- Terminal: Noctalia usa `$TERMINAL` o el primer terminal que encuentra (`foot` en ChurrOS).
- Historial de portapapeles propio de Noctalia (sin `cliphist`), sin pegado automático.
- Wallpapers desde `/usr/share/churros/wallpapers` (por defecto `default.png`, recorte `crop`), relleno `#111827`.
- Paleta propia `palettes/ChurrOS.json` (naranja `#F97316`, midnight `#111827`, grafito `#1F2937`, texto `#F8FAFC`), con variante clara y oscura. `shell_mode = "follow"`: Ajustes → Apariencia → Modo oscuro llama a `noctalia msg theme-mode-set` y el shell cambia con las apps.
- Fuente `Inter` (paquete `inter-font`), densidad cómoda (`ui_scale = 1.0`, lanzador no compacto), esquinas `corner_radius_scale = 1.2`, barra al 0.85 y paneles en modo `soft` (el modo `glass` deja el fondo al 55 % y, en oscuro sobre un wallpaper claro, el texto se vuelve ilegible).
- Sin asistente de primer arranque, sin telemetría, sin clima ni geolocalización y sin sonidos de interfaz.
- Idle/lock gestionado por Noctalia (pantalla 600 s, bloqueo 660 s, suspensión 28800 s); dock flotante que se oculta solo.
- El agente de polkit sigue siendo `polkit-gnome` (`polkit_agent = false`).
- En el Live, `desktop.sh` añade `~/.config/noctalia/live.toml` con `allow_empty_password = true`, porque el usuario `churros` no tiene contraseña. "Restaurar valores por defecto" lo conserva.

Los cambios hechos desde la UI de Noctalia se guardan en `~/.local/state/noctalia/settings.toml` y tienen prioridad sobre el `config.toml`; "Restaurar valores por defecto" vacía ese archivo y repone `config.toml` sin borrar la carpeta, para que Noctalia lo aplique en caliente. `churros-apply-wallpaper` le pasa a Noctalia el fondo elegido en `churros-settings` (`noctalia msg wallpaper-set`).

### Widgets y atajos

Distribución de la barra (`[bar.default]` en `config.toml`):

| Zona | Widgets |
|------|---------|
| Izquierda (`start`) | `launcher`, `clock`, `cpu`, `temp`, `ram`, `active_window`, `media` |
| Centro (`center`) | `workspaces` |
| Derecha (`end`) | `tray`, `notifications`, `battery`, `volume`, `brightness`, `control-center` |

Los atajos de Niri que abren el shell (`Mod+Space`, `Mod+Shift+Space`, `Mod+C`, `Mod+Shift+E` y `Mod+Shift+/`) están en la tabla de [Atajos](#atajos). `Mod+Space` y `Mod+C` llaman a `noctalia msg panel-toggle launcher` y `noctalia msg panel-toggle control-center`.

El centro de control de Noctalia ya tiene pestañas de audio, red, bluetooth, brillo (`monitor`) y batería (`power`). Por eso Niri no ata `churros-popup` ni `churros-control-center`. Esos binarios siguen en la ISO y se pueden abrir desde el lanzador (o desde Waybar, si la lanzas a mano).

---

## Waybar (alternativa)

**Path:** `archiso/airootfs/etc/skel/.config/waybar/`

Waybar sigue instalada, pero no arranca con la sesión Niri: la barra es la de Noctalia. Esta configuración del skel solo se usa si lanzas Waybar a mano. La edición Pi usa otra configuración ([Raspberry Pi](#raspberry-pi-labwc)).

### Config

`config.jsonc` empieza así:

```jsonc
{
  "reload_style_on_change": true,
  "layer": "top",
  "position": "top",
  "spacing": 0,
  "height": 30,
  ...
}
```

| Posición | Módulos |
|----------|---------|
| Izquierda | `custom/launcher`, `custom/sep`, `niri/workspaces`, `custom/sep`, `mpris` |
| Centro | (vacío) |
| Derecha | `group/tray-expander`, `custom/sep`, `memory`, `disk`, `cpu`, `battery`, `backlight`, `custom/sep`, `custom/screenrecording-indicator`, `idle_inhibitor`, `custom/dnd`, `custom/sep`, `bluetooth`, `network`, `pulseaudio`, `custom/sep`, `custom/control-center`, `custom/settings`, `custom/sep`, `clock`, `custom/power` |

| Módulo | Acción |
|--------|--------|
| `custom/launcher` | Clic → fuzzel. Clic derecho → foot. |
| `custom/control-center` | Clic → `churros-control-center`. |
| `custom/settings` | Clic → `churros-settings`. |
| `custom/power` | Clic → `wlogout`. |
| `network` | Clic → popup de red. |
| `bluetooth` | Clic → popup de bluetooth. |
| `pulseaudio` | Clic → popup de audio. Clic derecho → silencia. Rueda → ±5 %. |
| `backlight` | Clic → popup de brillo. Rueda → ±10 %. |
| `battery` | Clic → popup de batería. |
| `cpu` | Clic → `foot btop`. Clic derecho → foot. |
| `clock` | Tooltip con calendario. |
| `custom/dnd` | Clic → alterna el modo "No molestar" de mako. Solo funciona si mako está en marcha, y con Noctalia no lo está. |
| `idle_inhibitor` | Inhibe la inactividad. |
| `custom/screenrecording-indicator` | Indicador de `wf-recorder`, que no está en ninguna lista de paquetes. |
| `mpris` | Playerctl: clic → anterior, clic central → reproducir o pausar, clic derecho → siguiente. |

Los popups son `churros-popup` ([popups.md](popups.md)). Los iconos vienen de `Symbols Nerd Font Mono`.

### Estilo

`style.css` importa `colors-waybar.css` (`@background`, `@foreground`, `@color1`, `@color4`) y pinta la barra con `alpha(@background, 0.9)`, sin bordes ni esquinas redondeadas, con `JetBrains Mono` y `Symbols Nerd Font Mono` a 14px. Para cambiar los colores, cambia `colors-waybar.css`; `churros-theme` puede generar uno con la paleta de ChurrOS en `~/.cache/churros-theme/` ([live-services.md](live-services.md#churros-theme)).

---

## XFCE (X11)

**Path:** `archiso/airootfs/etc/skel/.config/xfce4/`
**Comando de sesión:** `/usr/bin/churros-xfce-session`, en el Live y en el sistema instalado. Es un wrapper que arranca Xorg con `startx` si hace falta y lanza `startxfce4`; nunca la sesión Wayland de XFCE ([login-greeter.md](login-greeter.md)).

La edición XFCE ofrece un escritorio clásico con ventanas flotantes gestionadas por `xfwm4`. `xfwm4.xml` deja activado el compositor de xfwm4 (`use_compositing`) y el autostart lanza además `picom -b`. La ISO de la edición server usa este mismo escritorio solo para el instalador.

### Estructura de configuración (xfconf y GTK)

```text
.config/
├── gtk-3.0/
│   ├── gtk.css           # Tema oscuro con acento naranja (#F97316), panel y Whisker Menu
│   └── settings.ini      # Adwaita-dark, Papirus-Dark, cursor Adwaita, fuente Inter 11
├── gtk-4.0/
│   ├── gtk.css           # Tokens de color y acento ChurrOS para apps GTK 4
│   └── settings.ini      # Igual que el de GTK 3
├── xfce4/
│   ├── panel/
│   │   ├── whiskermenu-1.rc  # Menú de inicio (icono ChurrOS, favoritos)
│   │   └── launcher-10..14/  # Lanzadores del panel
│   ├── terminal/
│   │   └── terminalrc        # Paleta de colores ChurrOS, fuente JetBrains Mono y transparencia
│   └── xfconf/xfce-perchannel-xml/
│       ├── xfce4-desktop.xml             # Wallpaper (/usr/share/churros/wallpapers/default.png)
│       ├── xfce4-keyboard-shortcuts.xml  # Atajos de teclado
│       ├── xfce4-notifyd.xml             # Notificaciones
│       ├── xfce4-panel.xml               # Panel: Whisker Menu, lanzadores, tareas, bandeja, volumen, energía, reloj, acciones
│       ├── xfwm4.xml                     # Gestor de ventanas: composición con sombras y botones |HMC
│       └── xsettings.xml                 # Tema GTK (Adwaita-dark), iconos (Papirus-Dark), cursor (Adwaita) y fuente (DejaVu Sans 10)
└── picom.conf
```

En XFCE la fuente de GTK la fija `xsettings.xml` (`DejaVu Sans 10`; monoespaciada, `JetBrains Mono 10`), así que no se usa la `Inter 11` de `settings.ini`. Tampoco está instalada: `inter-font` no está en la lista de la edición XFCE.

### Panel

Un único panel de 38px en la parte inferior, a todo el ancho, con fondo oscuro translúcido (`rgba(16, 16, 18, 0.94)`) y una línea naranja tenue en el borde superior. De izquierda a derecha:

1. **Whisker Menu** con el logo de ChurrOS (`churros-logo`).
2. Separador.
3. **Lanzadores**: Firefox, Thunar, terminal (`xfce4-terminal`), Bazaar y Configuración (`churros-settings`).
4. Separador.
5. **Lista de tareas**: botones planos; la ventana activa se marca en naranja ChurrOS (`#F97316`).
6. Separador expandible.
7. **Bandeja del sistema** (systray), donde aparece `nm-applet` para la red.
8. **Volumen** (plugin de PulseAudio).
9. **Energía y batería** (`power-manager-plugin`).
10. **Reloj** digital, formato `%I:%M %p`.
11. **Acciones de sesión** (plugin `actions`, pide confirmación).

### Autostart en XFCE

En `archiso/airootfs/etc/skel/.config/autostart/`:

- `churros-welcome.desktop`: lanza `churros-welcome --live-only` (`OnlyShowIn=XFCE;`). Niri lo arranca desde su propio `config.kdl`.
- `picom.desktop`: compositor de XFCE (`picom -b`, `OnlyShowIn=XFCE;`).
- `churros-tour.desktop`: el recorrido guiado, sin `OnlyShowIn`. XFCE lo lanza como autostart XDG; Niri comprueba que el archivo exista antes de lanzar `churros-tour`.

### Integración con utilidades de ChurrOS

- **Fondo de pantalla:** `churros-apply-wallpaper` detecta XFCE y aplica el fondo con `xfconf-query -c xfce4-desktop ...`.
- **Ajustes:** `churros-settings` lee la edición en `/etc/churros-edition` y, en XFCE, adapta las páginas de entrada, pantalla, teclado y apariencia: en lugar de las opciones de Niri ofrece las herramientas de XFCE (por ejemplo, Entrada abre `xfce4-mouse-settings`). `churros-welcome` no tiene lógica propia para XFCE.

---

## Raspberry Pi (labwc)

**Lista de paquetes:** `archiso/packages.pi.aarch64` (solo aarch64).
**Comando de sesión:** `/usr/bin/churros-pi-session`.

`churros-pi-session` exporta las variables de una sesión Wayland, arranca Waybar con la configuración de Pi (`/usr/share/churros/pi/waybar/config.jsonc` y `style.css`) y ejecuta `labwc`.

- **labwc:** configuración de sistema en `archiso/airootfs/etc/xdg/labwc/rc.xml` y `menu.xml`. Atajos: `Super+Return` abre foot, `Super+D` abre Fuzzel y `Escape` (sin modificador) ejecuta `labwc --exit`. El menú tiene Terminal (foot), File Manager (`pcmanfm`) y Logout.
- **Waybar de Pi:** barra superior de 24px con el lanzador (clic → Fuzzel, clic derecho → foot) a la izquierda y red, brillo, volumen y reloj a la derecha.

Problemas conocidos en el código actual:

- `foot` no está en `packages.pi.aarch64` (solo `foot-terminfo`), así que el atajo y la entrada de menú del terminal no abren nada.
- `Escape` sin modificador cierra la sesión.
- Ni `churros-pi-session` ni labwc lanzan `mako`. El paquete trae un servicio D-Bus que lo arranca con la primera notificación; que esa activación funcione en esta sesión no está comprobado.

---

## Personalización

Estas recetas son para tu propio `$HOME` o para un fork. En este repositorio, AGENTS.md pide no modificar `archiso/airootfs/etc/skel/.config/`, y el fondo por defecto es identidad de marca.

### Cambiar el layout de teclado (Niri)

En `~/.config/niri/config.kdl`:

```kdl
input {
    keyboard {
        xkb {
            layout "es"    # o "us,es" para alternar
        }
    }
}
```

### Cambiar los gaps (Niri)

En `~/.config/niri/config.kdl`:

```kdl
layout {
    gaps 8   // valor único (todos los lados)
}
```

### Cambiar el wallpaper

Desde Ajustes (`churros-settings`), que llama a `churros-apply-wallpaper`. En un fork, el fondo por defecto es `archiso/airootfs/usr/share/churros/wallpapers/default.png`; Noctalia lo carga al inicio (`[wallpaper.default]` en `~/.config/noctalia/config.toml`).

### Cambiar los widgets de la barra (Noctalia)

Desde la UI de Noctalia, o editando `[bar.default]` (`start`, `center`, `end`) en `~/.config/noctalia/config.toml`. Los cambios de la UI se guardan en `~/.local/state/noctalia/settings.toml` y tienen prioridad.

---

## Trabajo pendiente

- Soporte multi-monitor: configuración de outputs pendiente.
- Perfiles de energía: cambiar decoraciones automáticamente según si el equipo está en batería. Ajustes ya tiene páginas de perfil de energía y de batería.
- Traducciones: las apps Rust llevan sus cadenas en el código; las traducciones gettext de `po/` no las cubren.
