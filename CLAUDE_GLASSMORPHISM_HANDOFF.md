# Diagnóstico independiente: glassmorphism GTK4 + Niri en ChurrOS

Actúa como especialista en GTK4/GDK Wayland, gtk4-rs, CSS GTK, libadwaita y Niri. Investiga el repositorio actual para encontrar la causa raíz del fondo opaco y proponer una solución reproducible. El problema sigue presente después de reconstruir y reinstalar el sistema.

## Síntoma observado

En el escritorio Niri de ChurrOS, `churros-settings` (crate `rust/preferences`) sí presenta fondo translúcido con blur del wallpaper. `churros-control-center`, popups, welcome y tour aparecen con fondo marrón/naranja opaco, sin blur visible. El usuario confirma que reconstruyó/reinstaló después de una ronda anterior de cambios, y que también fallan welcome, tour y popups.

Mediciones comunicadas por el usuario sobre una captura:

- Wallpaper bajo la ventana: crema `#FFF7D8` (`rgb(255,247,216)`).
- El borde de 2 px `#DE8636` es la regla de foco/borde de Niri, y no el fondo de la ventana.
- Color uniforme medido en Control Center: `#9E632E` (`rgb(158,99,46)`).
- La regla Niri aplicada usa `opacity 0.9`; usando composición alfa simple, eso sugiere un color de buffer aproximado `#93531B` (`rgb(147,83,27)`) con alfa 1. Esta inferencia puede ser errónea si intervienen color management, otro fondo, alpha premultiplicado, muestreo, opacidad duplicada o una regla distinta. No la trates como una observación directa del buffer.
- Configuración reportada para Control Center: `open-floating true`, `opacity 0.9`, `background-effect { blur true }`, `geometry-corner-radius 22`, `clip-to-geometry true`.

## Contraste útil

- `rust/preferences/` usa `gtk::ApplicationWindow`, libadwaita (`adw::HeaderBar`), clase CSS `preferences`, y su propio CSS. FUNCIONA. No editar ningún archivo de `rust/preferences/`.
- `rust/control-center/` usa GTK4 puro, `gtk::ApplicationWindow`, sin decoración, no redimensionable, clase `control-center`, con un `ScrolledWindow` que contiene el contenido. Falla.
- También fallan las apps/popup crates `rust/popups/`, `rust/churros-welcome/` y `rust/churros-tour/`.
- Las apps afectadas instalan proveedores CSS en prioridades que pueden diferir de Preferences. Sigue en el código el orden real y determina qué selector/color gana, incluyendo CSS del usuario, stylesheet global GTK, tema/accent, CSS compartido y CSS local.
- Identificadores Niri: Control Center `org.churros.controlcenter`; welcome `org.churros.welcome`; tour `org.churros.tour`; popups `org.churros.popup.*`. Comprueba las reglas reales en el repositorio en vez de asumir que coinciden con la configuración descrita.

## Cambios ya probados y resultado

La rama actual contiene cambios no confirmados del intento anterior. Inspecciónalos como parte de la investigación. Incluyen la clase `churros-glass`, reglas de fondo semitransparente y transparencia de scrollers en CSS compartido/local, y ajustes al resolver de assets del Control Center. El usuario confirmó que reconstruyó/reinstaló y el problema persistió en todas las apps indicadas. No des por sentado que esos cambios están bien ni propongas repetirlos sin demostrar por qué deberían funcionar.

El workspace está en la rama `fix/niri-glassmorphism-gtk4`. No descartes ni sobrescribas los cambios locales existentes.

## Restricciones del proyecto

- No modificar `rust/preferences/`; solo usarlo como referencia comparativa.
- El usuario quiere que el efecto funcione en Control Center y las demás apps afectadas.
- Sigue `AGENTS.md`: cualquier implementación debe hacerse en rama distinta de `main`; esta rama ya satisface esa regla.
- Los assets runtime se copian/despliegan desde `rust/<crate>/assets/` por `scripts/build-rust.sh` a `/usr/share/churros/...`; distingue esos archivos fuente de posibles CSS legacy generados o rutas antiguas.
- No asumir que `set_decorated(false)` elimina el canal alfa ni que `ScrolledWindow` crea una superficie Wayland opaca. Verifica el comportamiento por código y documentación/API disponible.
- No asumir que libadwaita habilita globalmente el alpha de Wayland: explica qué puede y qué no puede configurar.

## Trabajo solicitado

1. Traza cada app afectada desde inicialización GTK hasta `present()`: inicialización del tema/acento, creación de `ApplicationWindow`, clase CSS, configuración del hijo, proveedores CSS/prioridades/rutas y carga de assets. Compara con Preferences sin editarla.
2. Encuentra la fuente exacta más probable del color sólido. Busca `window_bg_color`, `view_bg_color`, `@define-color`, `background-color`, `background`, `opaque`, `set_opaque_region`, opacidad de ventana, providers y overrides del usuario. Identifica el widget concreto que lo pinta y la regla efectiva, citando rutas y líneas.
3. Revisa especialmente el CSS global desplegado y cualquier regla GTK por defecto/tema que pinte `window`, `.background`, `scrolledwindow`, `viewport` o el widget raíz. Considera si los estilos globales de ChurrOS se cargan efectivamente en todas las apps y a qué prioridad.
4. Determina si la hipótesis de que el buffer Wayland sale alfa opaco está probada o solo inferida. Si no puede demostrarse desde este repo, indica qué inspección runtime mínima resolvería la duda (por ejemplo, identificar widget CSS ganador, inspección GTK Inspector, capturar surface con herramienta apropiada, logs/versiones/ruta CSS). No inventes telemetría ni afirmes haber ejecutado el escritorio ChurrOS.
5. Entrega un diagnóstico priorizado, con evidencia concreta y una corrección exacta propuesta en Rust/CSS que no toque Preferences. Considera una corrección compartida para todas las apps si la causa es común, así como requisitos de transparencia en widgets hijos y colores GTK del tema. Explica por qué Niri solo puede ver el wallpaper/blur donde la superficie deja pasar alpha.
6. Propón una verificación mínima que demuestre el resultado: cómo distinguir entre regla CSS opaca persistente, ruta/versión de asset equivocada, y opacidad del compositor. Indica archivos y comandos útiles, sin lanzar build ni modificar archivos.

## Formato de respuesta

- Resumen de causa raíz más probable y nivel de certeza.
- Evidencia: rutas, líneas y flujo de inicialización; compara con Preferences.
- Qué hipótesis se descartan y por qué; qué datos siguen faltando.
- Parche recomendado con snippets concretos de Rust/CSS, pero NO apliques cambios.
- Pasos de verificación runtime y riesgos/versiones GTK/Niri.

No hagas cambios en el árbol de trabajo. No ejecutes builds, tests ni instalaciones. Limítate a leer e inspeccionar. Si no puedes confirmar una causa raíz, dilo y da el siguiente experimento decisivo en vez de afirmar certeza.
