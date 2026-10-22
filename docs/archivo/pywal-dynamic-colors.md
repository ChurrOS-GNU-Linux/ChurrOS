# Guía de Desarrollo — Rama `fix/pywal-dynamic-colors`

Este documento está dirigido al desarrollador que continúe el trabajo en esta rama. Explica el contexto de la rama, la arquitectura implementada, qué se ha hecho hasta el momento, los puntos críticos a tener en cuenta y las tareas pendientes antes de abrir el Pull Request a `main`.

---

## 1. Contexto y Objetivos de la Rama

El objetivo principal de `fix/pywal-dynamic-colors` es completar la integración de **Colores Dinámicos (Pywal)** en todo ChurrOS. 

### ¿Qué hace esta funcionalidad?
Cuando el usuario selecciona un fondo de pantalla (o activa "Colores dinámicos" en *Preferencias → Apariencia*):
1. `PywalService` ejecuta `wal` sobre la imagen del wallpaper.
2. Se genera la paleta de colores y se extrae el color de acento dominante (junto con variantes de brillo y contraste).
3. Se escribe atómicamente `~/.config/churros/accent.css`.
4. Todas las aplicaciones GTK4/Libadwaita (`churros-settings`, `churros-welcome`, `churros-control-center`, `churros-popup`) adoptan el nuevo acento en tiempo real sin reiniciarse.
5. Se actualiza el archivo de colores de Waybar (`colors-waybar.css`), recargándose automáticamente vía inotify.
6. Los iconos vectoriales (SVG) adaptan su color dinámicamente gracias al uso de `currentColor`.

---

## 2. Historial de Cambios y Commits Realizados

A continuación se detalla cada commit existente en la rama y la razón de cada cambio:

| Commit | Mensaje | Descripción y Razón |
|---|---|---|
| `8e5dba1` | `fix(preferences): isolate wal pty writes and use singleton CssProvider for accent` | Crea un singleton `ACCENT_PROVIDER` para evitar fugas de memoria y acumulación de providers CSS. Añade `-s -t` a `wal` para aislar TTY. |
| `dd6bc36` | `fix(build): increase RUST_MIN_STACK to prevent LLVM stack overflow when compiling gtk4` | Sube `RUST_MIN_STACK` a 64MB para evitar `SIGSEGV` en LLVM durante `cargo build --release` de crates GTK4. |
| `135fe60` | `fix(wallpaper,theme): eliminate grey screen drop and fix GTK4 crashes on theme change` | Transición de wallpaper sin pantalla gris (mata el proceso viejo solo tras confirmar el nuevo). Elimina escrituras a `settings.ini` de GTK4 en caliente para evitar crashes. Usa `adw::StyleManager` para dark/light. |
| `2f387a9` | `fix(preferences): migrate to adw::Application, isolate stdio and ignore SIGPIPE` | Migra a `adw::Application` / `adw::ApplicationWindow`. Ignora `SIGPIPE` y redirige stdio a `/tmp/churros/` mediante `libc::dup2`. |
| `5479742` | `cli: stub awww and wallpaper daemons in apps dev sandbox` | Agrega `awww`, `swaybg`, `waypaper` y `churros-apply-wallpaper` a los stubs de `./churros apps` para no mutar el host durante pruebas locales. |
| `5c8d36b` | `fix(preferences): embed header bar in main box for AdwApplicationWindow` | Integra `AdwHeaderBar` dentro del box principal vertical de la ventana para layout nativo y estable. |
| `428c377` | `fix a medias` *(Pull general de colores dinámicos y estilos)* | Hace asíncrono el cambio de wallpaper/pywal (evita freeze de UI). Habilita carga de `accent.css` en Welcome, Popups y Control Center. Convierte iconos SVG a `currentColor`. Estabiliza Waybar sin `SIGUSR2`. Refina Liquid Glass. |

---

## 3. Arquitectura y Archivos Clave

```text
rust/
├── preferences/ (churros-settings)
│   ├── src/pages/wallpaper.rs       # Selección asíncrona de fondo (std::thread::spawn)
│   ├── src/pages/appearance.rs      # Toggle de Modo Oscuro y Colores Dinámicos
│   ├── src/services/pywal.rs        # Invocación de wal, lectura de caché y aplicación de acento
│   ├── src/services/accent.rs       # Generación y escritura atómica de accent.css + Provider singleton
│   ├── src/services/wallpaper.rs    # Backend swaybg/awww desacoplado con setsid
│   ├── src/services/theme.rs        # Gestión limpia de Adwaita y variables de entorno Wayland
│   └── src/services/waybar.rs       # Escritura de colors-waybar.css para Waybar
├── churros-welcome/src/main.rs      # Carga accent.css y estilos compartidos
├── control-center/src/main.rs       # Carga accent.css y estilos compartidos
└── popups/src/popup.rs              # Carga accent.css y estilos compartidos en los 6 popups

archiso/airootfs/
├── usr/bin/churros-apply-wallpaper  # Script de sesión para aplicar fondo sin parpadeo
├── usr/share/churros/styles/        # churros.css (tokens base Liquid Glass)
└── etc/skel/.config/gtk-4.0/gtk.css # Configuración GTK4 base del usuario
```

---

## 4. Reglas Críticas para Desarrollar en esta Rama

> [!CAUTION]
> ### 1. NO escribir en `~/.config/gtk-4.0/settings.ini` en tiempo de ejecución
> GTK4 tiene un watcher inotify en ese archivo. Si cualquier proceso escribe en `settings.ini` mientras una ventana GTK4 está abierta, GTK4 recarga todas las hojas de estilo y **cierra abruptamente la aplicación**.
> * El modo oscuro/claro se gestiona exclusivamente con `adw::StyleManager::default().set_color_scheme()`.
> * La limpieza de claves incompatibles se realiza en `ThemeService::migrate_before_gtk()` **antes** de inicializar GTK.

> [!IMPORTANT]
> ### 2. Operaciones de fondo y procesos externos SIEMPRE en hilos secundarios
> Comandos como `wal`, `swaybg` o `makoctl` tardan varios milisegundos en responder. Si se ejecutan en el hilo principal de GTK, la interfaz se congela.
> * Ejecuta la lógica pesada dentro de `std::thread::spawn(move || { ... })`.
> * Para modificar la interfaz o reemplazar estilos CSS tras el cálculo, despacha la acción con `glib::idle_add_once` o `glib::idle_add_local_once`.

> [!TIP]
> ### 3. Escritura atómica de CSS (`write_file_atomic`)
> Nunca escribas directamente en `accent.css` con `fs::write` si otras apps están leyéndolo en ese milisegundo. Escribe en un `.tmp` y haz rename atómico.

> [!NOTE]
> ### 4. Iconos SVG y colores
> En los SVGs de interfaz, **no uses colores hexadecimales fijos** (como `#F97316`) en trazos o rellenos principales. Usa `stroke="currentColor"` o `fill="currentColor"` para que hereden el acento dinámico de la clase CSS o botón contenedor.

---

## 5. Dónde Vamos y Tareas Pendientes (Roadmap)

### Estado Actual:
- [x] Extracción de paleta Pywal (`wal -i`) al cambiar wallpaper.
- [x] Generación de `accent.css` en `~/.config/churros/accent.css`.
- [x] Inyección de `accent.css` en tiempo de ejecución en:
  - [x] `churros-settings`
  - [x] `churros-welcome`
  - [x] `churros-control-center`
  - [x] `churros-popup` (Audio, Batería, Bluetooth, Brillo, Red, Energía)
- [x] Sincronización de colores en Waybar (`colors-waybar.css`).
- [x] Transición de fondo fluida sin pantalla gris (`swaybg` / `awww`).
- [x] Glassmorphism en GTK4/Libadwaita (`@define-color window_bg_color transparent`) en todas las apps.
- [x] Regla de opacidad `opacity 0.9` en window-rules de Niri para popup, controlcenter, preferences y welcome.
- [x] Blur `dual_kawase` en Picom para la edición XFCE.
- [x] Soporte en modo desarrollo (`./churros apps`) con sandboxing de daemons.
- [x] Pasan todos los checks estáticos (`./churros check`) y compilación Rust (`cargo check`).

---

### Tareas Pendientes para Completar la Rama:

1. **Pruebas en vivo en máquina virtual QEMU:**
   - Ejecutar `./churros run` (o `./churros run --fresh`).
   - Abrir *Preferencias* (`Mod+P`), cambiar entre distintos wallpapers (claros, oscuros, de diferentes tonos).
   - Verificar que Waybar, los popups (`Mod+Shift+A/N/B...`) y el centro de control (`Mod+C`) adopten el color del fondo.
   - Probar el switch "Colores dinámicos" (activar / desactivar) y confirmar que vuelve al acento predeterminado cuando está apagado.

2. **Integración con Notificaciones (Mako) [Opcional / Recomendado]:**
   - Verificar si `MakoConfigService` o el script de colores debe actualizar los colores de Mako (`makoctl reload` o `~/.config/mako/config`) para que las alertas adopten el color del acento de Pywal.

3. **Integración con Terminal (Foot) y Fuzzel [Opcional]:**
   - Foot ya cambia entre claro/oscuro con señales `USR1`/`USR2`. Comprobar si se desea enlazar el archivo `~/.cache/wal/colors-foot.ini` en la configuración de foot.

4. **Limpieza de Git antes del PR:**
   - Una vez comprobado todo en QEMU, renombrar o hacer *squash/reword* del commit `428c377 fix a medias` a un mensaje formal:
     ```bash
     git commit --amend -m "feat(theme): propagate pywal dynamic colors and liquid glass styling across all apps"
     ```
   - Ejecutar `./churros check` final.
   - Abrir el PR hacia `main`.

---

## 6. Comandos Rápidos de Verificación

```bash
# 1. Comprobar sintaxis y políticas de la distro
./churros check

# 2. Comprobar compilación de todos los crates Rust
cargo check --manifest-path rust/Cargo.toml

# 3. Probar la app de ajustes en el host (sandbox seguro)
./churros apps preferences

# 4. Probar en máquina virtual completa
./churros run
```
