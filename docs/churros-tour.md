# ChurrOS Tour: selección de apps, primer inicio y reintento

El Tour es una app GTK4 en `rust/churros-tour/`, desplegada por
`scripts/build-rust.sh` como `/usr/bin/churros-tour`. La entrada del menú está en
`archiso/airootfs/usr/share/applications/churros-tour.desktop`. No es un módulo
netinstall de Calamares: instala las aplicaciones después de entrar al sistema
instalado.

## Ediciones y primer inicio

| Edición | Inicio del Tour en el sistema instalado | Atajos y terminal |
| --- | --- | --- |
| Niri | El `spawn-sh-at-startup` de su configuración comprueba `~/.config/autostart/churros-tour.desktop` antes de lanzar el binario. | Atajos de Niri; foot. |
| XFCE | Autostart XDG mediante el mismo `.desktop`, heredado de `/etc/skel`. | Atajos de XFCE; xfce4-terminal. |
| Server | Sin Tour después de `configure-server`: retira el binario, el autostart y el escritorio del destino. La ISO lleva XFCE para ejecutar Calamares. | No hay recorrido gráfico en el servidor instalado. |

La edición Pi (labwc) no está en la tabla porque nada lanza el Tour en ella: el
repositorio no tiene un `autostart` de labwc (`/etc/xdg/labwc/` solo lleva
`rc.xml` y `menu.xml`) ni otro mecanismo que ejecute el `.desktop`. Si debe
tenerlo es una decisión pendiente.

`main.rs` bloquea el Tour cuando existe `/run/archiso`. La excepción
`CHURROS_TOUR_PREVIEW` permite la vista previa de `./churros apps tour` en el host.
Con esa variable, también se bloquean las instalaciones y escrituras del
inicio automático: recorrer todas las páginas no modifica el sistema anfitrión.

Al instalar, Calamares (`shellprocess-cleanup.conf`) conserva el `.desktop` y la
línea del Tour en el `config.kdl` de Niri.

## Personalizado y catálogo

El catálogo único está en `src/catalog.rs`: 37 apps agrupadas en navegadores,
ofimática/productividad, gaming, desarrollo, multimedia y herramientas del
sistema. `Personalizado` es una opción explícita y predeterminada; muestra todos
los grupos desplegados y cada app tiene su propia casilla.

Hay además cuatro perfiles (Ofimática, Gaming, Programación y Multimedia) que
sirven de selección inicial. Elegir uno reemplaza las casillas por los paquetes
de ese perfil. Elegir Personalizado conserva la selección actual; editar una
casilla de un perfil cambia a Personalizado sin borrar las otras apps. Las
casillas actualizan una sola selección ordenada, sin duplicados, y la
instalación recibe una copia exacta de esa selección. Volver atrás conserva las
casillas durante ese recorrido; un nuevo proceso empieza sin apps marcadas.

Se retiró la adición automática de drivers por `lspci`: detectaba fabricantes en
cualquier dispositivo PCI y añadía paquetes sin mostrarlos al usuario. El Tour
solo añade las aplicaciones elegidas y sus dependencias. Las actualizaciones
de paquetes existentes se describen antes de la operación.

## Instalación, cierre y errores

La instalación se realiza en segundo plano, sin abrir ventanas de terminal ni
requerir confirmación interactiva. La regla `/etc/sudoers.d/99-churros-pacman`
permite a los administradores del grupo `wheel` ejecutar `/usr/bin/pacman` sin
contraseña, lo que permite a `yay` operar de manera desatendida tanto para
paquetes de los repositorios oficiales como para compilaciones de AUR.

Las aplicaciones se instalan secuencialmente para ofrecer un seguimiento claro
y preciso: la interfaz de ChurrOS Tour actualiza en tiempo real el nombre de la
aplicación en curso (p. ej., «Instalando Google Chrome (1/3) en segundo plano...»)
y el avance en la barra de progreso.

Para evitar fallos con paquetes de AUR como `google-chrome` cuyas claves PGP
no están en el anillo oficial de Arch, se precargan las claves públicas conocidas
y se añaden los parámetros `--noconfirm --needed --mflags "--skippgpcheck" --answerclean None --answerdiff None` a `yay`.
La selección vacía termina el recorrido sin realizar operaciones en segundo plano.

El shell conserva el código de salida de yay y escribe un informe en un
directorio temporal privado (0700). Solo se anuncia éxito si tanto el proceso
como el informe indican éxito. Un informe ausente, un ejecutable que no inicia,
un código de error o una interrupción deja la página en error y conserva el
inicio automático. El informe temporal se elimina al terminar.

Mientras la instalación está en curso se bloquean Atrás, Finalizar y el cierre
de la ventana. Al fallar, se indica exactamente qué aplicación tuvo problemas,
Atrás permite corregir la selección y reintentar, y Cerrar conserva el Tour para
el siguiente inicio. No se borra el autostart tras un fracaso.

Tras el éxito, Finalizar guarda la opción «Abrir al iniciar» (desmarcada por
defecto) y cierra. Si no se marca, elimina únicamente el `.desktop` del usuario;
si se marca, lo conserva. Cerrar la ventana antes de Finalizar conserva el inicio
automático. Los errores al guardar esa preferencia se muestran y permiten
reintentar. Se usa `~/.config/autostart`, el mismo lugar que comprueba Niri.

## Pruebas y límites

Desde la raíz del repositorio:

```bash
cargo check --offline --locked --manifest-path rust/Cargo.toml -p churros-tour
cargo test --offline --locked --manifest-path rust/Cargo.toml -p churros-tour
cargo clippy --offline --locked --manifest-path rust/Cargo.toml -p churros-tour --all-targets --no-deps -- -D warnings
python3 scripts/test-tour.py
./churros check
```

Las cinco pruebas de biblioteca no necesitan pantalla. La prueba GTK adicional
se omite en `cargo test` ordinario. `scripts/test-tour.py` la ejecuta en Broadway
con sockets Unix privados, HOME/config/cache temporales, y terminal/yay
simulados. No instala software ni se conecta a la sesión del escritorio.
Verifica todas las casillas, los cuatro perfiles, el paso a Personalizado, la
selección vacía inicial de otro recorrido, la seguridad de la vista previa,
los códigos 0/1/42/130, un error de arranque de yay y la conservación del
autostart tras el fracaso.
`scripts/test-tour.py` necesita `gtk4-broadwayd` y no lo ejecutan ni
`./churros check` ni el CI: hay que lanzarlo a mano antes de tocar el Tour.

Estas pruebas verifican selección y manejo de resultados; no prueban descargas,
resolución de dependencias o instalación real de los 37 paquetes. Sigue pendiente
comprobar Niri y XFCE en una ISO nueva con éxito, cancelación y reintento reales,
y confirmar la limpieza de server.

La página de atajos de Niri (`src/pages/shortcuts.rs`) muestra `Super + T`
(terminal), `Super + D` (Fuzzel) y `Super + F` (pantalla completa), que no
coinciden con `config.kdl`: allí la terminal es `Mod+Return`, los lanzadores
`Mod+Space` (Noctalia) y `Mod+Shift+Space` (Fuzzel), y `Mod+F` maximiza la
columna.
