# Devlog

## 2026-10-08 — Noctalia v5 desde [extra]

`noctalia-qs` 0.0.12 (AUR) ya no compila con Qt 6.12 y rompía `./churros build`. La edición Niri pasa al paquete `noctalia` 5.2.1 de `[extra]`, también disponible en Arch Linux ARM: Noctalia v5, escrita en C++ sin Qt ni Quickshell. La v5 no lee el `settings.json` de la v4.

**Shell**

- Niri arranca `noctalia` en lugar de `qs -c noctalia-shell` y abre flotante la ventana de ajustes de Noctalia (`dev.noctalia.Noctalia`). Los atajos no cambian.
- `~/.config/noctalia/config.toml` (skel y `usr/share/churros/defaults/noctalia/`) sustituye a `settings.json` con los mismos ajustes donde hay equivalente: barra, dock, menú de sesión sin hibernar, idle 600/660/28800 s, notificaciones y OSD arriba a la derecha, colores desde el wallpaper, sin clima, geolocalización, telemetría ni sonidos. `polkit-gnome` sigue siendo el agente de polkit.
- En el Live, `desktop.sh` permite desbloquear con la contraseña vacía (`live.toml`), porque el usuario `churros` no tiene contraseña y la v5 ignora ese Enter.
- `churros-apply-wallpaper` y el cambio de tema de `churros-settings` avisan a Noctalia (`noctalia msg wallpaper-set` / `theme-mode-set`), que pinta su fondo encima de swaybg y reescribe el `color-scheme` de GNOME al arrancar.
- "Restaurar valores por defecto" vacía `~/.local/state/noctalia/settings.toml` y repone `config.toml` en su sitio (conserva `live.toml`): la v5 no ve borrados ni carpetas recreadas.
- Instalaciones de desarrollo con la v4: `sudo pacman -S noctalia && sudo pacman -Rns noctalia-shell noctalia-qs`, y restaurar los valores por defecto o cambiar el autostart de Niri a mano.

**Construcción**

- `build-aur.sh` deja de compilar `noctalia-qs` y `noctalia-shell`; `build.sh` ya no los exige y retira los que hayan quedado en `archiso/packages/` y en `churros.db`.
- `packages.x86_64` cambia `noctalia-shell`, `noctalia-qs`, `qt6-multimedia` y `cliphist` por `noctalia`; `packages.aarch64` gana `noctalia`.
- `./churros check` ya no da por bueno el binario `qs`.

---

## 2026-10-06 — Polkit con las claves reales de pkexec; actualizador endurecido

**Seguridad**

- `50-churros-store.rules` lee los detalles que publica pkexec (`program` y `command_line`). La regla anterior leía `command`, que no existe, y no autorizaba nunca nada: todo pedía contraseña (#152).
- La allowlist pasa a ser de argv exacto por programa y se limita a los llamadores reales: sin contraseña solo `churros-snapshot list --json` / `create manual` y `timedatectl set-timezone` / `set-ntp`; con contraseña recordada (`auth_admin_keep`) las actualizaciones, `churros-snapshot delete` y `churros-write-root-config`. Salen `yay`, `paru`, `churros-theme` y el resto de operaciones de pacman y flatpak. Tabla en [`docs/privileged-execution.md`](privileged-execution.md#tabla-de-decisiones).
- `churros-pkexec` hace `exec pkexec` para que la contraseña recordada sirva entre pasos, y los llamadores pasan rutas absolutas.
- `churros-write-root-config` recibe operaciones acotadas (`greetd-autologin on|off`, `lightdm-autologin on|off`, `regreet-wallpaper`, `regreet-greeting`) en vez del fichero entero. El usuario sale de `PKEXEC_UID` y la sesión de la edición, con la tabla que comparte con la instalación (`edition-session.sh`); el autologin de Niri vuelve a pasar por `churros-niri-session`.
- `churros-update-utils` instala fichero a fichero y ya no deja `/` en 0700 (#130), verifica la firma después de descargar el manifiesto (#139) y solo acepta `churros-*` en `usr/bin` y `usr/local/bin`, `usr/share/churros/` y tres ficheros de `etc`.

**Ajustes**

- Buscar actualizaciones usa `checkupdates` (nuevo `pacman-contrib` + `fakeroot` en las cuatro ediciones) en vez de `pkexec pacman -Sy`, y la página distingue "no se pudo comprobar" de "0 actualizaciones" o "al día" (#137).

**CI**

- `scripts/test-polkit-rules.js` (Node) prueba todas las decisiones de la regla y que cada llamador sigue escrito así; `scripts/test-privileged-helpers.py` prueba los helpers sobre un root falso. Los dos corren en `./churros check` y en CI, y `./churros check` falla si la regla vuelve a leer `lookup("command")`.
- Nuevo workflow `polkit.yml`: sonda con polkitd y pkexec reales en un contenedor Arch.

---

## 2026-10-05 — Pulido de la config de Noctalia

- Esquema de color derivado de los wallpapers (`useWallpaperColors: true`, `tonal-spot`, dark mode) y fondos `solidColor`/`fillColor` en Midnight `#111827`, acorde a la paleta oficial.
- Idle/lock propio de Noctalia activado (`lockOnSuspend` ya estaba; `~/.config/noctalia/settings.json` ahora define timeouts 600/660/1800 s). swayidle no se autoarranca en Niri, así que no hay conflicto.
- Tarjeta de brillo habilitada en el control center y `launcherUseDistroLogo: true` en el dock.
- Copia idéntica en `etc/skel` y `usr/share/churros/defaults/noctalia/`.

## 2026-10-05 — Noctalia Shell como shell del escritorio Niri

**Shell**

- Noctalia Shell (Quickshell, Qt/QML) pasa a ser la capa de shell de la edición Niri: barra, notificaciones, OSD, dock y widgets. Waybar, Fuzzel, Mako, wlogout y swaybg se mantienen instalados como alternativa (convivencia); `Mod+Space` sigue abriendo Fuzzel.
- `archiso/airootfs/etc/skel/.config/niri/config.kdl` (y su copia en `usr/share/churros/defaults/niri/`) arrancan `qs -c noctalia-shell` en autostart en lugar de `waybar` + `mako`.
- Config base de Noctalia en `~/.config/noctalia/settings.json` (terminal `foot -e`, cliphist, wallpapers de ChurrOS, fuentes JetBrains Mono, opacidad de paneles), desplegada también en `usr/share/churros/defaults/noctalia/`.

**Construcción**

- `scripts/build-aur.sh` compila además `noctalia-qs` (Quickshell) y `noctalia-shell` desde AUR hacia `archiso/packages/`.
- `archiso/packages.x86_64` gana `noctalia-shell`, `noctalia-qs`, `qt6-multimedia`, `wlr-randr`, `imagemagick`, `cliphist` y `power-profiles-daemon`.

**CI**

- `./churros check` reconoce el binario `qs` (paquete `noctalia-qs`) en la resolución de comandos de Niri.

---

## 2026-10-01 — Tercera edición, auditoría de seguridad y apps

Trabajo integrado en `main`, todavía sin número de versión.

**Ediciones**

- **KDE Plasma**: tercera edición de escritorio, con su propia lista de paquetes (`archiso/packages.kde.x86_64`) y sesión Wayland nativa. Detalle en [`docs/desktop-config.md`](desktop-config.md).

**Seguridad**

- La regla de polkit pasa a ser una allowlist estricta: se autoriza por ruta absoluta exacta, nunca por basename ni comodín, y se rechazan las opciones que convierten una utilidad en vector de escalada (`--hookdir`, `--config`, `--dbpath`, `--root`).
- `churros-pkexec` deja de estar autorizado: reenvía argumentos libres a `pkexec` y anularía la allowlist entera.
- El actualizador fija la URL de descarga a `https://download.churroslinux.org/churros/` y solo admite otro espejo con `CHURROS_UPDATE_ALLOW_MIRROR=1` y base `https`. El JSON de actualizaciones se parsea sin `unwrap`.
- El instalador deja de arrastrar la configuración SSH del Live: `shellprocess@post-install` borra `/etc/ssh/sshd_config.d/10-archiso.conf` y las claves de host.
- `churros-welcome` lanza las acciones sin shell: pasa el `Exec` del `.desktop` como `argv` a `execvp` y solo si el binario está en su lista de permitidos.
- Nuevo documento [`docs/privileged-execution.md`](privileged-execution.md): modelo, allowlist y checklist para añadir helpers.

**Apps**

- `churros-welcome`: `AdwToolbarView` con `AdwClamp`, tarjeta de información del sistema y 17 tests sobre los parsers que leen `/proc` y `/etc/os-release`.
- `MAINTAINERS`: cada área del repositorio tiene una persona responsable.

**Construcción**

- `rust` y `cargo` salen de la ISO de niri y de XFCE: solo hacen falta en el host, durante la construcción.
- La fuente Nerd Font se sustituye por `JetBrains Mono` + `Symbols Nerd Font Mono`, que es lo que usan los iconos.

**Correcciones**

- `procps-ng` y `pciutils` en la ISO de niri y XFCE: los invocaba el código que faltaba.
- El tour se limpia al terminar la instalación y no aparece en el sistema instalado.

## 2026-10-12 — ChurrOS 1.3

Release pública **v1.3**. Estabilidad del sistema, resolución de dependencias para gaming/AUR y actualización integral de la suite oficial:

- **ChurrOS Tour mejorado**: Inclusión de `base-devel` para compilación de paquetes AUR (`google-chrome`, `brave-bin`, etc.) y soporte gráfico multilib (`lib32-mesa`, `vulkan-icd-loader`, `lib32-vulkan-icd-loader`) para compatibilidad completa con Steam.
- **Alineación de versión 1.3**: Sincronización de `VERSION`, crates de Rust a `1.3.0`, `/etc/churros-version`, Fastfetch branding, Calamares installer (`branding.desc`) y manifiestos de actualización OTA.
- **Kernel estable de Arch Linux**: Se mantiene el kernel oficial (`linux`) garantizando máxima fiabilidad y compatibilidad de hardware.

---

## 2026-09-23 — ChurrOS 1.2

Release pública **v1.2**. Optimizaciones de rendimiento, rediseño de UI y mejoras de conectividad y audio:

- **Control Center ultrarrápido**: Carga instantánea de estado de red, bluetooth y audio mediante lecturas paralelas en hilos en segundo plano (<20ms).
- **Wi-Fi en tiempo real**: Monitoreo dinámico de tasa de transferencia (tasa de enlace actual y velocidad de tráfico en Mbps / KB/s en vivo vía `/proc/net/dev`).
- **Control de volumen con respuesta inmediata**: Feedback visual a 0ms en sliders de volumen y supresión de sincronización retrasada de WirePlumber/PipeWire.
- **Popup de audio dedicado y módulo Waybar**: Nuevo popup de barra deslizante de volumen tipo Liquid Glass con iconos dinámicos y soporte para rueda de ratón en Waybar.
- **Estilo de tarjetas en panel de control**: Fondo sólido opaco (`#161a22`) en tarjetas y selectores para máxima legibilidad, manteniendo transparencia glassmorphism en los bordes y entre opciones.
- **Actualización de versión 1.2**: Alineadas versiones internas en Calamares (`branding.desc`), crates de Rust (`Cargo.toml` a 1.2.0) y `/etc/churros-version`.

---

## 2026-08-17 — ChurrOS 0.7

Release pública **v0.7**. ISO `ChurrOS-2026.08.17-x86_64-v0.7.iso` y torrent en download.churroslinux.org.

Incluye actualizador (pacman, Flatpak y utilidades de ChurrOS), tienda Bazaar, rediseño de popups y personalización de Waybar.

---

## 2026-08-13 — ChurrOS 0.6

Release pública **v0.6** (tag `v0.6`). Las apps oficiales corren como binarios Rust (`churros-welcome`, `churros-settings`, `churros-control-center`, `churros-popup`). El tema GRUB se despliega al airootfs para que Calamares lo aplique en el sistema instalado. `build-rust.sh` instala cargo/rust en el host si faltan.

La ISO supera el límite de 2 GiB de GitHub: se publica partida en dos `.7z` más `SHA256SUMS`.

`VERSION` y el resto de la documentación se alinean a esta versión en una tanda posterior (dejan de describir v0.4.0 / Python como el runtime actual).

---

## 2026-07-25 — Popups, Control Center, Welcome, Preferencias

### Resumen

Sesión grande: terminadas las fases de personalización faltantes (5c, 5d), arreglados los bugs que rompían el arranque del live ISO y los que impedían abrir los popups, el centro de control y aplicar las opciones de apariencia.

### Bug crítico: `niri validate` fallaba y rompía el arranque del live ISO

- `archiso/airootfs/etc/skel/.config/niri/config.kdl` tenía una cláusula `match app-id=r#"firefox$"# title="^Picture-in-Picture$"` que no es KDL válido (raw string literal). Cambiado a dos sentencias `match` separadas que actúan con AND semántico (cada `window-rule` aplica si todos sus `match` coinciden).
- Conflictos de atajos: `Mod+V` estaba asignado tanto a `churros-settings` como a `toggle-window-floating`. Reorganizados:

| Atajo | Acción |
|-------|--------|
| `Mod+Return` | Terminal (`foot`) |
| `Mod+Space` | Launcher (`fuzzel`) |
| `Mod+C` | Control Center |
| `Mod+P` | Preferencias |
| `Mod+W` | Welcome |
| `Mod+V` | Toggle ventana flotante |
| `Mod+Shift+N` | Popup network |
| `Mod+Shift+A` | Popup audio |
| `Mod+Shift+B` | Popup bluetooth |
| `Mod+Shift+L` | Popup brightness |
| `Mod+Shift+T` | Popup battery |
| `Mod+Shift+E` | Popup power |

### Config niri

- Terminal oficial: **foot** (`packages.x86_64`, welcome/waybar/niri `Mod+Return`). Las docs antiguas hablaban de Kitty; se corrigen para reflejar el stack real.
- Terminal atajo: `Mod+Return` → foot (sin cambios).

### Waybar nuevos módulos

`archiso/airootfs/etc/skel/.config/waybar/config.jsonc`:

- Añadido `custom/control-center` (icono `󰂗`) que lanza `churros-control-center`.
- Añadido `custom/settings` (icono `󰒋`) que lanza `churros-settings`.
- Ambos colocados en `modules-right`, justo antes del reloj, precedidos por un `custom/sep`.

### Bug crítico: popups y control-center no abrían

Síntoma: al hacer clic en un módulo de waybar o usar un atajo, no pasaba nada. El script `churros-popup` redirige stdout/stderr a `/dev/null`, así los errores quedaban ocultos.

Causa raíz:

- `control-center/window.py` y los `popups/*/widgets/*.py` importaban `from i18n import _`.
- El módulo `i18n` solo existía en `preferences/i18n.py`.
- `control-center/window.py` intentaba añadir `preferences/` al `sys.path` con `Path(__file__).resolve().parents[2] / "preferences"`, pero `parents[2]` desde `control-center/window.py` es `usr/share/`, no `churros/`. El path calculado era `/usr/share/preferences` (inexistente).
- Resultado: `ModuleNotFoundError: No module named 'i18n'` → la app moría antes de crear la ventana.

Fix aplicado:

- Copié `preferences/i18n.py` a `archiso/airootfs/usr/share/churros/i18n.py` — módulo central accesible desde todas las apps ChurrOS (popups, control-center, preferences) mediante una sola entrada en el `sys.path` (root `churros/`).
- Reescribí `control-center/main.py` para insertar paths en el orden correcto:
  1. `APP_DIR` (control-center/) primero, para que `from window import ...` resuelva al `window.py` propio y no al de preferences.
  2. `PREFS_DIR` (preferences/) segundo, por si todavía queda alguna referencia a `i18n` no centralizada.
  3. `CHURROS_ROOT` tercero, para el namespace package `services.*` (wifi, ethernet, bluetooth...).
- Quité el path-hack en `control-center/window.py` (ya lo hace `main.py`).

Verificación: los 6 popups (audio, battery, bluetooth, brightness, network, power) y `control-center` cargan sin error al ejecutar `python3 main.py` (en host sin Wayland solo reportan un Gtk-WARNING inofensivo de theme).

### SelectRow: clics muertos en accent/cursor/icons

Síntoma reportado: "se queda clavado en la opción que está y no deja poner otro".

Causa:

- `SelectRow` hereda de `Row` (`Gtk.Button`) y añade un `Gtk.CheckButton` como suffix.
- En GTK4 el `Gtk.Button` captura el clic y el `CheckButton` hijo nunca recibe el evento → el callback conectado al `clicked` del row solo se ejecutaba a veces (cuando el clic caía fuera del CheckButton).
- Además el callback solo se invocaba si `not self.check.get_active()` (ignoraba re-clicks).
- No había group entre CheckButtons, así que varios items podían quedar activos a la vez.

Fix reescribiendo `archiso/airootfs/usr/share/churros/preferences/widgets/select_row.py`:

- Uso de `Gtk.CheckButton.set_group()` con un group compartido (atributo de clase `SelectRow.group`) → selección single mutual.
- Callback conectado a `notify::active` del CheckButton (se emite SIEMPRE al togglear, no solo cuando pasa a True).
- `on_row_clicked`: si el check está inactivo, fuerzo `set_active(True)` para que el grupo se re sincronice y emita toggled en todos los afectados.
- Nuevo class method `SelectRow.reset_group()` para que cada página (Accent, Cursor, Icons) arranque con un grupo limpio y no compita con otra página que use SelectRow.

Aplicado `SelectRow.reset_group()` al inicio del `__init__` de:

- `pages/accent.py`
- `pages/cursor.py`
- `pages/icons.py`

### Accent no se aplicaba en runtime

Bug 1: el CSS autogenerado usaba `:root` (no soportado en GTK4 CSS):

```css
/* Antes */
:root {
    --churros-accent: #DE8636;
    ...
}
```

GtkCssProvider ignora `:root`. Fix en `services/accent.py._generate_accent_css`:

```css
/* Ahora */
window {
    --accent: #DE8636;
    --accent-strong: #B86A24;
    --accent-soft: #E6A56A;
    --accent-text: #ffffff;
    --accent-bg-hover: <color más claro>;
}
```

Bug 2: `AccentService.set()` escribía el archivo CSS en disco, pero GTK no lo recargaba hasta el próximo arranque de la app.

Fix en `pages/accent.py.SelectRow`: añadido `_reload_accent_css()` que crea un `Gtk.CssProvider` nuevo, lo carga desde `accent.css` y lo registra en la display con `Gtk.STYLE_PROVIDER_PRIORITY_USER + 1` (prioridad mayor que el provider principal para que las variables nuevas ganen).

Resultado: clic en "Green" → se escribe `~/.config/churros/accent.css` → se cargan las nuevas vars en la display → todos los `var(--accent)` reaccionan inmediatamente.

### Modo oscuro no se aplicaba visualmente

`appearance.py.on_dark_changed` ya llamaba `window.refresh_theme()` vía `GLib.idle_add`, y `window._apply_theme_class()` añade/quita la clase `.light` en el window. Eso estaba bien — pero solo afectaba al `window` root, no era inválido de por sí.

La causa real del "no aplica" era el CSS: antes tenía reglas hardcoded (`.row { color:white; }`) que ignoraban completamente el `.light` y siempre pintaban blanco sobre fondo claro → "mitad negra mitad blanca". El fix fue reescribir todo el CSS (ver sección CSS).

### Fonts no se aplicaban en runtime

`FontService.set()` solo escribía `gsettings set org.gnome.desktop.interface font-name ...`, pero GTK4 solo lee `font-name` al arranque. Lo mismo con `text-scaling-factor`.

Fix en `services/fonts.py`:

- `set()` además hace `Gtk.Settings.get_default().set_property("gtk-font-name", ...)` (afecta a la app actual inmediatamente).
- `set()` también resetea `gtk-fontconfig-timestamp` para que fontconfig reléa la configuración.
- `set_scale()` además hace `Gtk.Settings.get_default().set_property("gtk-xft-dpi", int(1024 * scale))` — escalar DPI en runtime.
- Aplica también `document-font-name` y `monospace-font-name` (no solo `font-name`).

### Wallpaper — explorar archivos y copiarlos a la carpeta de wallpapers

Nuevo en `services/wallpaper.py`:

- `USER_DIR = ~/.local/share/churros/wallpapers/` — carpeta personal de fondos del usuario (añadida también a `WALLPAPER_DIRS` para que aparezcan en el grid).
- `import_image(source_path)` — copia una imagen externa a `USER_DIR`. Si el nombre ya existe, añade sufijo `_1`, `_2`, etc. Devuelve ruta destino o None.
- Fallback en `set()`: si `awww` falla, mata `swaybg` existente y lo relanza con `-i path -m fill` (start_new_session=True para que no muera con la app).

Nuevo en `pages/wallpaper.py`:

- Botón "Importar desde archivos..." usando `Gtk.FileDialog` (GTK4 nativo, no el deprecated `FileChooserDialog`).
- Filtro de mime types: `image/jpeg`, `image/png`, `image/webp`, `image/gif`.
- Ruta inicial: `~` (home del usuario).
- Tras elegir archivo: copia → aplica → recarga todo el grid con `_rebuild_grid()` para mostrar el nuevo thumbnail.

### CSS Preferences reescrito — estilo macOS con colores churros

`archiso/airootfs/usr/share/churros/preferences/style.css` (576 líneas → ~460 líneas consolidadas):

Antes había 3 definiciones de `.sidebar` background, 2 de `.row-title`, hardcoded `color:white` en todos lados. Resultado: al activar `.light`, solo los 4 elementos con `var()` cambiaban → mitad negra mitad blanca.

Ahora **todo** el CSS usa variables CSS. Variables definidas en `window { ... }` (dark default) y sobrescritas en `window.light { ... }`:

- `--bg-window` (fondo principal)
- `--bg-sidebar` (sidebar translúcido)
- `--bg-group` (card de grupo)
- `--row-bg`, `--row-bg-hover`, `--row-bg-active`
- `--text-primary`, `--text-secondary`, `--text-tertiary`
- `--border-soft`, `--border-strong`
- `--accent`, `--accent-soft`, `--accent-strong`, `--accent-text`, `--accent-bg-hover`
- `--scroller-thumb`

Colores churros:

- Dark: `--accent: #DE8636` (naranja cálido)
- Light: `--accent: #C5651C` (más oscuro para contraste)

Estilo macOS aplicado:

- Sidebar translúcido (rgba con alpha < 1) + bordes redondeados (16px) + border subtle.
- Items de sidebar con border-radius 9px, hover en `--accent-bg-hover`, item activo con fondo `--accent` y texto `--accent-text`.
- Grupos tipo "card" con padding 4px, border radius 12px y border subtle.
- Rows con radius 8px, hover en `--row-bg-hover`.
- Switches estilo iOS/macOS: 42x24 con border-radius 14px, slider 18x18 que se desplaza 22px al activar (en lugar del switch nativo GTK).
- Sliders con trough 5px, slider 14px redondo con sombra.
- DropDowns con radius 8px y hover en accent.
- Popover list con radius 6px por item.
- Scrollbar fina (8px) con color `--scroller-thumb` y hover en accent.
- About card con border radius 16px.
- Wallpaper thumbnails con radius 10px y selected border 3px accent.
- Back button de subpáginas con radius 8px.

Sin reglas duplicadas, sin hardcodes blancos fuera de los tokens.

### Subpáginas con botón "Atrás"

`widgets/page.py` extendido:

- Nuevo kwarg `parent_page=None`. Si se pasa, añade un botón "Atrás" al inicio de la página usando el icono `go-previous-symbolic`.
- `on_back()` llama `self.navigator.show_page(self.parent_page)`.

Aplicado a:

- `pages/accent.py` → `parent_page="appearance"`
- `pages/icons.py` → `parent_page="appearance"`
- `pages/cursor.py` → `parent_page="appearance"`
- `pages/fonts.py` → `parent_page="appearance"`
- `pages/wallpaper.py` → `parent_page="appearance"`
- `pages/power_profile.py` → `parent_page="power"`
- `pages/battery.py` → `parent_page="power"`
- `pages/display_timeout.py` → `parent_page="power"`
- `pages/sleep.py` → `parent_page="power"`

### Página de entrada (input) válida

`pages/input.py` antes era un stub de 12 líneas con constructor roto (`__init__(self)` en vez de `__init__(self, navigator)` y llamada `super().__init__("Entrada")` con un solo arg). Reescrito:

- Group "Teclado" con `ComboRow` de layouts (`es`, `us`, `latam`, `fr`, `de`, `it`).
- Group "Ratón" con `SwitchRow` "Tocar para clic" (vía `gsettings org.gnome.desktop.peripherals.mouse tap-to-click`).
- Group "Velocidad" con `SliderRow` (-100..100) para `gsettings org.gnome.desktop.peripherals.mouse speed`.

Añadido al sidebar como "Entrada" (icon `input.svg`) entre Pantalla y Audio. Registrada en `window.py` como `"input"` page.

### PowerService completado

`services/power.py` añadido:

- `set_power_profile(profile)` — `powerprofilesctl set <profile>`.
- `set_screen_timeout(seconds)` — `gsettings set org.gnome.desktop.session idle-delay <n>`.
- `set_sleep_timeout(seconds)` — `gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout <n>`.
- `set_lid_close_action(action)` — `gsettings set org.gnome.settings-daemon.plugins.power lid-close-ac-action <action>`.

### Páginas de power sub-functions ahora funcionan

Antes `pages/power.py` referenciaba subpáginas `power-profile`, `battery`, `display-timeout`, `sleep` vía `NavigationRow`, pero NO existían como navigator pages registradas en `window.py`. Al pulsar no pasaba nada.

Creadas y registradas:

- `pages/battery.py` — estado real con upower (present/percentage/state/profile).
- `pages/power_profile.py` — combo performance/balanced/power-saver con labels traducidos y callback `on_profile_changed` (invoca `PowerService.set_power_profile`).
- `pages/display_timeout.py` — combo "1m/2m/5m/10m/15m/30m/Nunca".
- `pages/sleep.py` — combo timeout + combo acción al cerrar tapa.

Todas registradas en `window.py` con `add_page("power-profile", ...)`, etc.

### WallpaperPage reescrito con thumbnails reales

Antes mostraba cada wallpaper como un `Row` con título y subtítulo. Reescrito con:

- `Gtk.FlowBox` con `set_max_children_per_line(4)`, `set_min_children_per_line(2)`.
- Cada thumbnail es un `Gtk.Box` vertical con `Gtk.Image.new_from_paintable(Gdk.Texture.new_from_filename(path))` a 120px.
- Imagen actual destacada con clase `wallpaper-selected` (borde accent).
- Fallback a `image-missing` si no puede cargar.
- Label con el nombre del archivo, ellipsize END, tooltip.
- Preview del fondo actual a 160px en un Group separado arriba.

### i18n module

Antes `preferences/i18n.py` era el único que existía; los popups lo referenciaban pero no estaba en el path. Ahora:

- Copia:`archiso/airootfs/usr/share/churros/i18n.py` (idéntico a `preferences/i18n.py`).
- Las apps solo necesitan `churros/` en el `sys.path` para importar `i18n`.
- `preferences/i18n.py` se mantiene para no romper imports antiguos dentro de preferences (que tienen `.` en el path).

### profiledef.sh

- Quitada la referencia a `churros-welcome/churros-welcome.sh` (eliminado en sesión anterior, pero la línea en profiledef seguía).
- Permisos declarados para `/usr/bin/churros-popup` (0755), `/usr/bin/churros-control-center` (0755), `/usr/bin/churros-settings` (0755), `/usr/bin/churros-welcome` (0755).

---

## 2026-08-07 — Preferences Brain (release v0.4.0)

Sesión de 60 commits centrada en madurar el panel de preferencias, eliminar bugs latentes y ampliar la cobertura de la GUI.

### Selector de zona horaria integrado

- `services/datetime.py` nuevo: `DatetimeService` con `get_timezone()`, `get_ntp()`, `list_timezones()` (598 zonas), `set_timezone()`/`set_ntp()` vía `churros-pkexec`.
- `pages/datetime.py` reescrito: reloj vivo (segundo a segundo), switch NTP integrado, **selector de zona con `Gtk.SearchEntry` que filtra en vivo** y abre un `Popover` con `ListBox` de resultados (max 200 visibles). Al hacer clic, aplica via `churros-pkexec` (polkit).
- `50-churros-store.rules` añadida autorización para `timedatectl` junto a `pacman/flatpak/yay/paru`.
- Eliminado el flujo anterior con `fzf`+`foot`; ahora todo se hace dentro de la GUI.

### Nuevas páginas

- **Mako** (`pages/mako.py`) — Tipografía, colores, bordes, disposición, padding, comportamiento + reload + **toggle DND**.
- **Backup** (`pages/backup.py`) — Exportar/importar/resetear la config de `~/.config/churros/`.
- **Night Light** (`pages/night_light.py`) — `wlsunset` (temperatura, gamma, automático).
- **Lock Screen** (`pages/lock_screen.py`) — `swaylock` + `swayidle`.
- **Window Rules** (`pages/window_rules.py`) — Editor visual de `window-rule {}` blocks en KDL.
- **Logs** (`pages/logs.py`) — Ver logs del sistema.
- **Niri** (`pages/niri.py`) — Toggle animaciones + sliders de duración de `window-open` y `workspace-switch`.

### Bugs críticos resueltos

- `NiriConfig.reload()` añadido (`f19966e`). Antes 11 sitios llamaban `NiriConfig.reload()` que no existía → `AttributeError`. Ahora envía `pkill -HUP niri`.
- `DisplayService.set_vrr()` añadido (`f19966e`). Faltaba wrapper; backend base ya lo tenía.
- `ComboRow` reescrito como `Gtk.Box` directo (`e1c2477`). Antes heredaba de `Gtk.Button` → el button capturaba el click del dropdown. Bug manifiesto: pulsar la flecha no abría el menú.
- `Row.set_title()` / `Row.set_subtitle()` añadidos como API pública (`f19966e`).
- `ColorPickerRow` acepta `subtitle` kwarg (`e517f4f`). Bug rompía `do_activate()` al construir `LockScreenPage`.
- `display_timeout.py` — `parent_page` corregido de `"power"` a `"display"` (`18ac16a`).
- `pages/shortcuts.py` borrada (`0b9bcd5`) — duplicaba `keyboard.py` (la única página de atajos).
- `archiso/packages/` — 9 artefactos de pacman quitados del índice (`ed7ab08`).
- `churros-settings` sin permisos de ejecución (`65c5f95`).
- Screen negro al cambiar wallpaper + modo oscuro (`ecd4adc`).
- OVMF_VARS.fd copia independiente (`dea9249`).

### Robustez y logs

- `churros-settings` (launcher bash) blindado (`677789f`):
  - Output redirigido a `$XDG_RUNTIME_DIR/churros-settings.log` (fallback `/tmp/churros-settings.log`).
  - Autodetección de `WAYLAND_DISPLAY` si no exportado.
  - Si la app falla, no aborta la sesión del usuario.
- `main.py` blindado (`677789f`):
  - Cada bloque crítico envuelto en try/except.
  - Errores se loguean con stack trace completo.
  - `_build_wallpaper` ahora no muere si el wallpaper no existe.

### Apariencia reorganizada

`pages/appearance.py` reorganizada en 9 grupos temáticos (`053872d`):

1. Tema (claro/oscuro)
2. Color de acento
3. Tipos de letra
4. Cursor
5. Iconos
6. Fondo de pantalla
7. Esquinas / forma
8. Pywal (paleta dinámica)
9. Waybar

ThemeService y AccentService tienen **hooks pywal** — cuando pywal está activo, regenera paleta desde el wallpaper.

### Búsqueda mejorada

- Search global con subpáginas (`36d9b7e`) — buscar "modo oscuro" salta a `Apariencia → Tema` y resalta el row correspondiente.
- Layout responsive — sidebar narrow en pantallas estrechas.
- Color picker entry editable — pegar hex manualmente funciona.

### Atajos globales

`PreferencesWindow` registra (`2d7f7bf`):

| Atajo | Acción |
|-------|--------|
| `Ctrl+F` | Foco al search del sidebar |
| `Ctrl+B` | Toggle sidebar narrow |
| `Shift+Ctrl+N` | Toggle sidebar narrow (alias) |

### Pulido de páginas existentes

- **Power profile** — descripciones + advertencias sobre rendimiento (`6b1c8a6`).
- **Sleep** — estado batería integrado (`6b1c8a6`).
- **Fonts** — preview en vivo + debounce (`6b1c8a6`).

### CI

- `./churros check` corre en GitHub Actions (`.github/workflows/ci.yml`) en cada push a `main` y PR.
- Verifica: bash syntax, shellcheck error level, Python syntax, duplicate entries en `packages.x86_64`, Niri autostart commands resolvibles, `msgfmt --check` en `po/*.po`, repo hygiene (no generated files tracked).

---

## 2026-08-25 — Multi-edición XFCE, App HeaderBars & Responsividad

### Soporte Multi-Edición (`niri` + `xfce`)
- Añadida bandera `--edition <niri|xfce>` al comando `./churros build`.
- Creado `archiso/packages.xfce.x86_64` con la suite completa de XFCE 4, panel ChurrOS, xfwm4, xsettings y utilidades X11.
- Configuración de dotfiles en `archiso/airootfs/etc/skel/.config/xfce4/` para panel, gestor de ventanas y xsettings oscuros con Adwaita/Papirus.
- `greetd` configurado dinámicamente para autologin a `/usr/bin/startxfce4` (XFCE) o `/usr/bin/niri` (Niri).
- `churros-apply-wallpaper` adaptado para configurar el fondo tanto en `swaybg` como en `xfce4-desktop` vía `xfconf-query`.

### Apps Rust: HeaderBars y Responsividad
- **ChurrOS Welcome (`churros-welcome`)**:
  - Integrada barra de título `AdwHeaderBar` con botones estándar de ventana (cerrar, maximizar, minimizar).
  - Integrada la tarjeta de Información del Sistema (`system_card`) en el FlowBox principal, mostrando CPU, RAM, Kernel, SO, Arquitectura y Hostname directamente desde `/proc` y `/etc/os-release`.
  - Configurado `FlowBox` responsivo (hasta 4 columnas, colapsable a 2 o 1) con desplazamiento automático en `ScrolledWindow`.
  - Autostart compatible con XFCE (`.config/autostart/churros-welcome.desktop`).
- **Configuración (`churros-settings`)**:
  - Añadida barra de título `AdwHeaderBar` con controles de ventana.
  - Integrado el botón hamburguesa en la barra de título para colapsar y expandir el menú lateral en pantallas estrechas.
  - Filtrado condicional de páginas: en XFCE se ocultan automáticamente las subpáginas exclusivas de Niri/Waybar.
  - Ajuste de línea automático (`wrap(true)`) en títulos y descripciones de filas.
- **Control Center (`churros-control-center`)**:
  - Añadido botón de cierre en cabecera y contenedor con scroll para pantallas de baja resolución.

### ReGreet + Greetd: Pantalla de Login macOS, Autologin y Personalización
- **Greeter Gráfico ReGreet + Cage**:
  - Implementado `ReGreet` (Rust + GTK4) corriendo sobre el compositor kiosko `cage` con `WLR_NO_HARDWARE_CURSORS=1` para evitar bugs de orientación de cursor en virtual GPUs.
  - Creado tema CSS estilo macOS Liquid Glass (`archiso/airootfs/etc/greetd/regreet.css`) con campos píldora (`border-radius: 9999px`), avatar circular, desenfoque y resplandor de foco en color acento naranja ChurrOS (`#F97316`).
  - Terminal gráfica aislada en `VT7` para evitar la exposición de logs de arranque de la consola de systemd (`VT1`).
- **Autenticación e Idioma**:
  - Configurado `/etc/pam.d/greetd` con `system-local-login` para solicitar y validar la contraseña del usuario.
  - Script post-instalación `/usr/share/churros/scripts/configure-greeter-locale` para sincronizar automáticamente el saludo (`greeting_msg`) y formato de fecha según el idioma seleccionado en Calamares.
  - Integración completa con el checkbox de autologin de Calamares y compatibilidad con `churros-settings` (sección *Usuarios y Login*).

---

## 2026-09-22 — Pre-flight Checks de Build, Saneamiento de Rust Workspace y Diagnósticos KVM en CLI

### Pre-flight Checks Tempranos en Build y Doctor
- **`scripts/cli/build.sh`**:
  - Implementada comprobación pre-flight antes del paso 0 que valida la presencia de dependencias críticas en el host (`mkarchiso`, `mksquashfs`, `xorriso`, `grub-mkstandalone`, `mkfs.fat`, `mcopy`, `mmd`). Si falta alguna herramienta requerida para generar la imagen UEFI, el script aborta en menos de 1 segundo indicando el paquete faltante exacto y el comando de instalación, en lugar de pasar minutos compilando Rust para fallar al final.
- **`scripts/cli/doctor.sh`**:
  - Añadida verificación de herramientas de arranque UEFI (`grub`, `dosfstools`, `mtools`).
  - Mapeo de cada comando al nombre del paquete Arch correspondiente (`pkgconf`, `gettext`, `libisoburn`, `squashfs-tools`, etc.).
  - **Instalación automática/interactiva**: Cuando detecta herramientas faltantes, propone su instalación con `sudo pacman -S --needed ...` y permite confirmar interactivamente con `[S/n]` o automáticamente mediante la bandera `--install` / `-y`.

### Diagnósticos de Virtualización Hardware KVM
- **`scripts/cli/doctor.sh` y `scripts/cli/run.sh`**:
  - Comprobación del dispositivo `/dev/kvm`, permisos del usuario actual y detección de virtualización deshabilitada en la BIOS/UEFI (`Intel Virtualization Technology` / `SVM`).
  - `run.sh` emite advertencias claras si KVM no está habilitado y configura un fallback seguro por emulación de software (`-cpu max`, 2 hilos) para evitar que QEMU falle silenciosamente.

### Saneamiento del Workspace de Rust (0 warnings)
- Limpieza integral de 56 advertencias de compilación en `preferences`, `churros-welcome`, `control-center` y `popups`:
  - Eliminación de imports redundantes (`gtk::prelude::*`) en 17 archivos.
  - Corrección de variables mutables innecesarias y código muerto.
  - Reemplazo de métodos deprecados de GTK4 (`load_from_data` → `load_from_string`).

### Higiene del Repositorio y Limpieza
- Actualizado `.gitignore` y `scripts/cli/clean.sh` para gestionar y limpiar los archivos temporales de `archiso/airootfs/` en caso de compilaciones interrumpidas.
- Corregido aviso de ShellCheck en `scripts/cli/check.sh`.

### Optimización y Carga Perezosa en Panel de Configuración (`churros-settings`)
- **Arquitectura Lazy-Loading en `window.rs`**:
  - En lugar de construir vorazmente las 34 páginas y subpáginas durante el arranque, se registran contenedores `gtk::Box` ligeros y se almacena la fábrica constructora en un mapa `builders`.
  - Solo se construye en el arranque la página inicial activa (`system` o la última visitada). Todas las subpáginas y páginas secundarias se instancian bajo demanda la primera vez que se seleccionan y se conservan cacheadas en memoria.
  - Esto reduce el tiempo de apertura de la aplicación en aproximadamente un 90% (de más de 1 segundo a unos ~100 ms).
- **Aceleración de Consultas del Sistema y Caché**:
  - `applications.rs`: Conteo de paquetes optimizado leyendo directamente las carpetas de `/var/lib/pacman/local` en <1 ms en lugar de lanzar el subproceso `pacman -Q` (~130 ms).
  - `system.rs`: Caché en memoria de proceso vía `OnceLock` para `cpu`, `gpu` (evitando re-ejecutar `lspci`), `kernel` y `hostname`.
  - `theme.rs`: Evitada la ejecución repetitiva de `gsettings` y migración de temas en cada arranque mediante un flag en caché.
  - `style.css`: Corregida la sintaxis duplicada de offsets en `box-shadow` (`0 0 20px var(--accent-glow)`) que provocaba avisos de parseo CSS en GTK4.

### Solución a Crash de Sesión X11 (XFCE) en Greetd
- **`churros-xfce-session`**: Se ha creado un script contenedor en `/usr/bin/churros-xfce-session` que se encarga de lanzar de manera correcta el entorno XFCE desde el Display Manager (Regreet/Greetd). Este contenedor ejecuta `startx /usr/bin/startxfce4` de forma condicional si no se detecta el entorno de visualización, logrando que el servidor Xorg asigne apropiadamente el TTY mediante `systemd-logind` y se resuelva el crasheo que devolvía al usuario a la pantalla de login.
- Integración en `desktop.sh`: Se ha automatizado la inyección en `/usr/share/xsessions/xfce.desktop` para usar este wrapper en entornos X11.

### Autostart Condicional de ChurrOS Tour
- Para el entorno **Niri**, se ha incluido un `spawn-sh-at-startup` en `config.kdl` que invoca `churros-tour` condicionalmente solo si existe el archivo `~/.config/autostart/churros-tour.desktop`.
- Para el entorno **XFCE**, este mecanismo ya funciona de forma nativa a través de los directorios de autostart del estándar XDG. 
- Se ha expuesto `churros-tour` en `/usr/share/applications/churros-tour.desktop` para que sea visible en cualquier lanzador o menú, y se ha limpiado su binario de desarrollo compilado que había entrado en caché del repositorio.

### Corrección de Cursor de Ratón en Entorno XFCE (Hardware Real)
- **El problema:** Al acceder a XFCE desde una instalación física, el ratón no aparecía ni respondía. Esto se debe a que `xorg-server` requiere un módulo adaptador (`xf86-input-libinput`) para interpretar eventos de hardware de entrada provenientes de `libinput`, lo cual es vital al iniciar fuera de un gestor de pantalla compuesto como GDM.
- **La solución:** Se ha añadido el paquete `xf86-input-libinput` a la lista de paquetes requeridos (`packages.xfce.x86_64`), permitiendo que Xorg detecte correctamente los periféricos en hardware físico.

### Falsa detección de Wayland en XFCE (Error de labwc)
- **El problema:** En las últimas versiones, el script `startxfce4` comprueba la existencia de la variable `WAYLAND_DISPLAY`. Greetd/Regreet dejaban un residuo de esta variable en la sesión tras cerrar `cage` (su propio entorno Wayland). Como resultado, XFCE creía que debía arrancar una sesión nativa en Wayland y pedía a gritos el compositor `labwc`, abortando el arranque de Xorg.
- **La solución:** Se ha inyectado un `unset WAYLAND_DISPLAY` en `churros-xfce-session` para limpiar el entorno residual heredado del greeter y forzar siempre un entorno X11 robusto para XFCE. (Nota: los errores de `libseat` mostrados en log son inofensivos; simplemente indican el *fallback* seguro a `systemd-logind`).

### Solución a Crash de Xorg (Recursive xinit)
- **El problema:** Tras corregir el error del DRM con `sleep 1`, persistía una pantalla negra que devolvía a Greetd. Al ejecutar `unset DISPLAY` globalmente al inicio del wrapper, se borraba la variable `$DISPLAY` inyectada por Xorg en la sesión cliente. Como resultado, `startxfce4` creía que no había un servidor gráfico activo y lanzaba `xinit` por segunda vez dentro del propio `xinit`, colapsando inmediatamente.
- **La solución:** Se ha reubicado el `unset DISPLAY` y `unset WAYLAND_DISPLAY` para que solo afecten al proceso padre (Greetd) y no al proceso hijo (la sesión X11 iniciada con `--xinit`). De esta forma, `startxfce4` reconoce `$DISPLAY=:0` correctamente.

### Bucle de login en XFCE instalado (vuelve al greeter)
- **El problema:** En el sistema instalado de la edición XFCE, al iniciar sesión (sobre todo sin inicio automático, desde ReGreet) el escritorio parecía arrancar y volvía al greeter en bucle.
- **La causa:** El parche de `xfce.desktop` (`Exec=churros-xfce-session`) vivía solo en `desktop.sh`, que se ejecuta en el Live; el sistema instalado se copia del squashfs y conservaba el `Exec=startxfce4` del paquete, más `xfce-wayland.desktop` (que exige `labwc`). ReGreet lanza `xsessions/*.desktop` como `startx /usr/bin/env <Exec>`, sin el wrapper ni `vt`/`-keeptty`. Además el inicio automático escribía `/usr/bin/startxfce4` en `[initial_session]`, otra vez sin wrapper. Para greetd, un Xorg que se desconecta del TTY es una sesión terminada.
- **La solución:** `edition-session.sh` y `build.sh` usan `/usr/bin/churros-xfce-session` como sesión XFCE. `configure-greetd-session` ejecuta `fix-xfce-sessions` al instalar (quita la sesión Wayland y reescribe `Exec`), y el hook `92-churros-xfce-x11-session` lo reaplica tras cada `pacman -Syu`. El wrapper resuelve su ruta absoluta (startx descarta rutas relativas y cae a `xterm`), detecta si ya hay un X en marcha (caso ReGreet) y, si no, lanza `startx` con `vt$XDG_VTNR -keeptty`.
- **Sin verificar en arranque real:** solo `./churros check`; falta probarlo instalando la ISO en QEMU.

