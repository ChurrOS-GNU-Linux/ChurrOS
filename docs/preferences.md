# Preferences

`churros-settings` es la app de configuración principal de ChurrOS. Está escrita en **Rust** (gtk4-rs, con libadwaita solo para la barra de título) con un estilo visual inspirado en System Settings de macOS y los colores naranja de ChurrOS.

---

## Resumen

**Path:** `rust/preferences/`
**Binario:** `/usr/bin/churros-settings` (desplegado por `build-rust.sh`; app id `org.churros.preferences`)
**Atajo:** `Mod+P` (Niri); `Super+I` / `Super+S` (XFCE)
**Assets:** `/usr/share/churros/churros-settings/assets/` en la ISO; `rust/preferences/assets/` en desarrollo
**Log:** `/tmp/churros/settings.log` (stdout y stderr del proceso se redirigen ahí)

- **Ventana:** 900×680 por defecto, redimensionable. Por debajo de 760 px de ancho el sidebar se colapsa.
- **Barra de título:** `adw::HeaderBar` con los botones de ventana (cerrar, maximizar, minimizar) y un botón de menú que aparece en modo estrecho para mostrar u ocultar el sidebar.
- **XFCE:** si la edición (ver el punto siguiente) contiene `xfce`, la ventana se crea sin decoración del servidor (`set_decorated(false)`) para que XFWM no ponga su barra de título encima de la de la app y se vean dos.
- **Multi-edición:** lee la edición (`/etc/churros-edition`, `VARIANT_ID` de `/etc/os-release` o el escritorio de la sesión). Si la edición no es Niri (XFCE, server, Pi), no registra las páginas Niri, Foot, Fuzzel, Luz nocturna, Pantalla de bloqueo, Reglas de ventana, Logs de Niri, Waybar ni Mako. En Niri, Waybar y Mako solo aparecen si la sesión los ejecuta; con Noctalia (por defecto) no.
- **Sidebar + stack de páginas:** navegación por catálogo con búsqueda (`Ctrl+F`).
- **Carga diferida:** al abrir solo se construye la página visible (`system` o la última visitada). Las demás se construyen la primera vez que se visitan y quedan en memoria.
- **Consultas rápidas del sistema:** el número de paquetes instalados se cuenta en `/var/lib/pacman/local` en lugar de con `pacman -Q`, y los datos estáticos de hardware (CPU, memoria, GPU con `lspci`, kernel, hostname) se guardan en caché de proceso con `OnceLock`.

---

## Estructura

```text
rust/preferences/
├── Cargo.toml                 # name = "churros-settings", deploy = true
├── assets/
└── src/
    ├── main.rs                # gtk::Application + carga de CSS
    ├── window.rs              # PreferencesWindow (sidebar + stack + registro de páginas)
    ├── logging.rs
    ├── assets.rs
    ├── widgets/               # Page, Sidebar, Row, Group, ComboRow, …
    ├── services/              # Settings, tema, acento, pywal, niri, mako, …
    └── pages/                 # Una página por archivo
```

Los servicios de display aún entienden un backend Hyprland (`hyprctl`) además de Niri, pero ninguna edición instala Hyprland.

---

## Persistencia de ajustes

`SettingsService` (`services/settings.rs`):

- Ruta: `~/.config/churros/settings.json`
- JSON anidado, acceso con dot keys (`theme.dark`, `accent.color`).
- Defaults en código; crea el archivo la primera vez.

También se espeja en gsettings:

| Clave local | gsettings |
|-------------|-----------|
| `theme.dark` | `org.gnome.desktop.interface color-scheme` |
| `cursor.theme` / `cursor.size` | `cursor-theme` / `cursor-size` |
| `fonts.family` / `fonts.scale` | `font-name`, `document-font-name`, `monospace-font-name`, `text-scaling-factor` |
| `icons.theme` | `icon-theme` |

---

## Tema (claro/oscuro)

`ThemeService` (`services/theme.rs`):

1. Orden de lectura: el modo de Noctalia (si es el shell de la sesión) → `~/.cache/churros-theme/dark-flag` → `theme.dark` de `settings.json` → oscuro.
2. `apply(dark)` guarda el JSON y el flag, escribe `color-scheme` `prefer-dark` / `prefer-light`, llama a `noctalia msg theme-mode-set` si Noctalia está instalado, a `xfconf-query` en XFCE, actualiza `~/.config/gtk-3.0/settings.ini` y señala a foot (`USR1` oscuro, `USR2` claro).
3. En la propia app: la ventana añade o quita la clase `.light` y cambia `gtk-application-prefer-dark-theme`. El CSS usa variables (`--bg-window`, `--text-primary`, …) definidas en `window` (oscuro) y `window.light`.

Las otras apps (welcome, control center, popups) leen el tema con `churros_services::theme::is_dark()` y siguen los cambios de `color-scheme`.

---

## Color de acento

`AccentService` — 8 colores (Blue, Purple, Pink, Red, Orange, Yellow, Green, Teal).

`set(color)` escribe `~/.config/churros/accent.css` con `--accent` y variantes. El CSS usa `window { … }` y las clases de cada app (GTK4 no soporta `:root`). En churros-settings el acento se aplica al momento: un `CssProvider` único a prioridad USER que se sustituye en cada cambio. welcome, control center y popups leen `accent.css` al arrancar, así que toman el nuevo acento la próxima vez que se abren.

Si los colores dinámicos están activos y se elige un color con nombre, la paleta de pywal lo vuelve a sustituir.

### Colores dinámicos (pywal)

`theme.dynamic_colors` (apagado por defecto), interruptor «Colores dinámicos» en Apariencia. `PywalService` (`services/pywal.rs`):

1. Ejecuta `wal -i <fondo> -q -n -e -s -t` sobre el fondo actual (o `/usr/share/churros/wallpapers/default.png`) y lee `~/.cache/wal/colors.json`.
2. Usa `color1` (o `color4`, o el `foreground`) como acento: `AccentService::set_hex` reescribe `accent.css` sin tocar `accent.color`.
3. Aplica la paleta a foot y fuzzel; a Waybar (`colors-waybar.css`) y Mako solo si la sesión los ejecuta, que con Noctalia no es el caso.

Cambiar el fondo con el interruptor activo regenera la paleta. Al apagarlo vuelve el color guardado en `accent.color`. Calamares también ejecuta `wal` sobre el fondo por defecto al instalar, si está instalado, pero lo hace como root en el sistema destino, no con la cuenta del usuario.

### Reglas al tocar tema, acento y colores dinámicos

- **No cambiar `gtk-theme` ni escribir `~/.config/gtk-4.0/settings.ini` con la app abierta.** Según `theme.rs`, GTK4 recarga las hojas de estilo y la ventana se cierra. Las claves obsoletas se limpian en `ThemeService::migrate_before_gtk()`, antes de iniciar GTK.
- **Escritura atómica.** `accent.css` se escribe en un `.tmp` y se renombra (`write_file_atomic`), porque otras apps lo leen al arrancar. Los configs de niri y fuzzel siguen el mismo patrón.
- **Comandos lentos fuera del hilo de GTK.** `wal`, `swaybg` o `makoctl` tardan; en el hilo principal congelan la interfaz. La página de fondos llama a `WallpaperService::set` con `gio::spawn_blocking`, y los cambios de CSS vuelven al hilo de GTK con `glib::idle_add_once`.
- **Iconos SVG con `currentColor`.** Casi todos los iconos de churros-settings y del control center (no el logo) usan `currentColor` para heredar el color del widget (y con él el acento). Los de welcome y tour aún llevan colores fijos.

---

## Fuentes, cursor, iconos, fondo

- **FontService** — `fc-list` para listar; aplica con gsettings (`font-name`, `document-font-name`, `monospace-font-name`, `text-scaling-factor`) y cambia `gtk-xft-dpi` en `gtk::Settings` para que la escala se vea al momento en la propia app.
- **CursorService** — busca temas en `/usr/share/icons` y `~/.icons`; aplica `cursor-theme` / `cursor-size` y escribe `gtk-cursor-theme-*` en los `settings.ini` de GTK 3 y GTK 4.
- **IconsService** — `icon-theme` en gsettings, `gtk-icon-theme-name` en los `settings.ini` de GTK 3 y GTK 4, y `/Net/IconThemeName` con `xfconf-query`.
- **WallpaperService** — con Noctalia en marcha, `churros-apply-wallpaper` (que usa el IPC de Noctalia) o, si no está, `noctalia msg wallpaper-set`; nunca arranca `swaybg` encima del shell. Sin Noctalia, `churros-apply-wallpaper` y, si falla, `swaybg`. Después regenera pywal si está activo.

---

## Pantalla

En XFCE la página no usa `DisplayService`: ofrece un botón que abre `xfce4-display-settings`.

En el resto de ediciones, `DisplayService` lista monitores y modos. Elige el backend por la variable de escritorio (`XDG_CURRENT_DESKTOP`, o si falta `XDG_SESSION_DESKTOP` o `DESKTOP_SESSION`):

- Si contiene `niri`: lee con `niri msg outputs` y cambia modo, escala, rotación y VRR con `niri msg output <nombre> …`.
- Si no: backend Hyprland (`hyprctl monitors -j`), sin VRR ni cambio de resolución (la página omite esos controles). Ninguna edición instala Hyprland, así que en el Live de server (sesión XFCE con edición `server`) y en la Pi (labwc) la página no encuentra monitores.

---

## Navegación

- `gtk::Stack` con una entrada por página o subpágina; `window.rs` guarda además un historial de páginas visitadas.
- `Ctrl+F` enfoca la búsqueda: filtra por título las páginas del sidebar y muestra un desplegable con las subpáginas que coinciden (por título o descripción); elegir un resultado abre esa subpágina.
- El botón «Atrás» de una subpágina vuelve a su página padre.
- En modo estrecho (menos de 760 px) el sidebar se oculta (`Revealer`) y aparece el botón de menú. `Ctrl+B` lo muestra u oculta en modo estrecho; `Ctrl+Shift+N`, siempre.
- El item del sidebar sigue al padre si estás en una subpágina.

---

## Árbol de páginas

Páginas principales del sidebar, en orden: Sistema, Actualizaciones, Fecha y hora, Apariencia, Pantalla, Entrada, Audio, Conectividad, Energía, Usuarios, Privacidad, Aplicaciones, Teclado y Acerca de. Las subpáginas se abren desde su página padre y desde la búsqueda. La lista sale de `register_pages()` en `window.rs`.

| Archivo | Padre | Condición | Función |
|---------|-------|-----------|---------|
| `system.rs` | (principal) | | Versión, edición, sesión, kernel, hardware y accesos rápidos |
| ↳ `backup.rs` | `system` | | Exportar, importar o restablecer la configuración |
| ↳ `logs.rs` | `system` | Niri | Logs de Niri y validación del config |
| `update.rs` | (principal) | | Actualizaciones (pacman, Flatpak, utilidades ChurrOS) y rollback Btrfs |
| `datetime.rs` | (principal) | | Hora, zona horaria y NTP |
| `appearance.rs` | (principal) | | Tema, colores dinámicos, fondo, modo rendimiento y accesos a subpáginas |
| ↳ `accent.rs` | `appearance` | | 8 colores de acento |
| ↳ `icons.rs` | `appearance` | | Tema de iconos |
| ↳ `cursor.rs` | `appearance` | | Tema y tamaño de cursor |
| ↳ `fonts.rs` | `appearance` | | Familia, escala, vista previa |
| ↳ `wallpaper.rs` | `appearance` | | Selector e importación de fondos |
| ↳ `niri.rs` | `appearance` | Niri | Disposición, bordes, blur, animaciones |
| ↳ `window_rules.rs` | `appearance` | Niri | Bloques `window-rule {}` |
| ↳ `foot.rs` | `appearance` | Niri | `foot.ini` |
| ↳ `fuzzel.rs` | `appearance` | Niri | `fuzzel.ini` |
| ↳ `night_light.rs` | `appearance` | Niri | `wlsunset` |
| ↳ `lock_screen.rs` | `appearance` | Niri | `swaylock` / `swayidle` (con Noctalia, el bloqueo lo gestiona Noctalia) |
| ↳ `waybar.rs` | `appearance` | Niri y sesión con Waybar | Posición, módulos, colores |
| ↳ `mako.rs` | `appearance` | Niri y sesión con Mako | Tipografía, colores, bordes, DND |
| `display.rs` | (principal) | | Resolución, escala, rotación, VRR y brillo (en XFCE, botón a `xfce4-display-settings`) |
| ↳ `display_timeout.rs` | `display` | | Apagado de pantalla |
| `input.rs` | (principal) | | Teclado y ratón (en XFCE, botón a `xfce4-mouse-settings`) |
| `audio.rs` | (principal) | | Dispositivo y volumen de salida y micrófono |
| `connectivity.rs` | (principal) | | Wi-Fi y Bluetooth |
| `power.rs` | (principal) | | Resumen de energía |
| ↳ `power_profile.rs` | `power` | | `powerprofilesctl` |
| ↳ `battery.rs` | `power` | | Estado y nivel de la batería |
| ↳ `sleep.rs` | `power` | | Suspensión y tapa |
| `users.rs` | (principal) | | Cuenta y pantalla de inicio de sesión |
| `privacy.rs` | (principal) | | Permisos, firewall (`ufw`), diagnóstico |
| `applications.rs` | (principal) | | Apps instaladas, tienda y actualizaciones |
| `keyboard.rs` | (principal) | | Atajos de Niri (en XFCE, botón a `xfce4-keyboard-settings`) |
| `about.rs` | (principal) | | Versión, edición, software, licencia |

---

## Servicios extra

- **LockScreenService** — `swaylock` + `swayidle` (timeout, bloqueo al suspender). Con Noctalia activo el bloqueo lo gestiona Noctalia.
- **NightLightService** — `wlsunset` (temperatura, gamma, automático).
- **MakoConfig** (`mako_config.rs`) — escribe `~/.config/mako/config` y ejecuta `makoctl reload`; la página muestra y cambia el modo DND. Solo aparece si la sesión ejecuta Mako.
- **NiriConfig** — parser KDL y `reload()` con `niri msg action load-config-file`. Nunca `pkill -HUP niri`: SIGHUP reinicia la sesión entera del compositor y cierra todas las apps.
- **WaybarService** — `config.jsonc` + `style.css`; recarga relanzando Waybar o con `SIGUSR2`. `colors-waybar.css` (pywal) lo recoge Waybar por inotify, sin señal.
- **DatetimeService** — `timedatectl` vía `churros-pkexec`.
- **BackupService** — exporta e importa `churros-backup-*.tar.zst` (`settings.json` + dotfiles de niri, foot, fuzzel, mako, waybar, noctalia, fastfetch y el estado de Noctalia en `~/.local/state/noctalia`) y restablece desde `/usr/share/churros/defaults`.
- **UpdateService** — comprobación/actualización asíncrona de paquetes (pacman, flatpak, utilidades ChurrOS), temporizadores systemd y gestión de snapshots Btrfs vía `churros-snapshot`.

### Valores por defecto

`/usr/share/churros/defaults/` guarda una copia de los configs de `etc/skel/.config/` que la app sabe restablecer (niri, noctalia, foot, fuzzel, mako, waybar, fastfetch). «Restablecer a valores de fábrica» los copia sobre `~/.config/`. Las dos copias tienen que estar sincronizadas: si divergen, restablecer da una configuración distinta de la de una instalación nueva. `./churros check` lo verifica fichero a fichero.

---

## Robustez

- `logging.rs` escribe en `/tmp/churros/settings.log`, redirige ahí stdout/stderr, ignora `SIGPIPE` y captura panics.
- Recargas sin reiniciar la app: Niri (`niri msg action load-config-file`), Mako (`makoctl reload`), Waybar (relanzar o `SIGUSR2`), foot (`SIGUSR1`/`SIGUSR2`), tema y acento (CSS en caliente).
- `ComboRow` es un `gtk::Box` (no hereda de `Button`, para no comerse los clics del dropdown).

---

## Atajos

| Atajo | Acción |
|-------|--------|
| `Ctrl+F` | Búsqueda |
| `Ctrl+B` | Mostrar u ocultar el sidebar (modo estrecho) |
| `Ctrl+Shift+N` | Mostrar u ocultar el sidebar |
| `Mod+P` (Niri) / `Super+I`, `Super+S` (XFCE) | Abrir la app |

---

## Limitaciones conocidas

- El cambio de fuente se aplica al momento en esta app; otras GTK ya abiertas pueden necesitar reinicio.
- i18n: los `.po` existen, pero el binario Rust aún no carga gettext.
- Display asume un monitor principal; multi-monitor incompleto.
- Pantalla: en el Live de server y en la Pi no lista monitores (cae en el backend Hyprland, ver [Pantalla](#pantalla)).
- El interruptor «Colores dinámicos» y elegir un color con pywal activo ejecutan `wal` en el hilo de GTK; la ventana no responde mientras termina.
- `CursorService` e `IconsService` escriben en `~/.config/gtk-4.0/settings.ini` al cambiar el cursor o los iconos, justo lo que `ThemeService` evita con la app abierta.
- En el Live de la edición server, que también arranca XFCE, `edition()` devuelve `server` y la ventana conserva la decoración del servidor.
- Sin tests automatizados GTK. Verificación: `./churros rust` + probar en Niri / `./churros run`.

---

## Trabajo futuro

- Multi-monitor en Display.
- Gestos de trackpad y scrolling natural.
- Aplicar fuente/cursor a apps Qt.
