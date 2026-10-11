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
| KDE Plasma | Autostart XDG mediante el mismo `.desktop`, heredado de `/etc/skel`. | Atajos de KDE; Konsole. |
| Server | Sin Tour después de `configure-server`: retira el binario, el autostart y el escritorio del destino. La ISO lleva XFCE para ejecutar Calamares. | No hay recorrido gráfico en el servidor instalado. |

`main.rs` bloquea el Tour cuando existe `/run/archiso`. La excepción
`CHURROS_TOUR_PREVIEW` permite la vista previa de `./churros apps tour` en el host.
Con esa variable, también se bloquean las instalaciones y escrituras del
inicio automático: recorrer todas las páginas no modifica el sistema anfitrión.

Calamares conserva el `.desktop` y ahora conserva también el lanzador de Niri.
Anteriormente `shellprocess-cleanup.conf` borraba la línea del Tour en Niri,
aunque dejaba el `.desktop`: el primer inicio quedaba desconectado en esa edición.

## Personalizado y catálogo

El catálogo único está en `src/catalog.rs`: las mismas 37 apps y nombres del
catálogo anterior, agrupados en navegadores, ofimática/productividad, gaming,
desarrollo, multimedia y herramientas del sistema. `Personalizado` es una opción
explícita y predeterminada; muestra todos los grupos desplegados y cada app tiene
su propia casilla.

El historial explica dos etapas:

- `d6b9dab`: cuatro perfiles con grupos completos (Ofimática, Gaming,
  Programación y Multimedia).
- `a6743a0`: catálogo ampliado a 37 apps y selección individual.

Los cuatro perfiles originales se ofrecen como selecciones iniciales. Elegir
uno reemplaza las casillas por los paquetes de ese perfil. Elegir Personalizado
conserva la selección actual; editar una casilla de un perfil cambia a
Personalizado sin borrar las otras apps. Las casillas actualizan una sola
selección ordenada, sin duplicados, y la instalación recibe una copia exacta de
esa selección. Volver atrás conserva las casillas durante ese recorrido; un
nuevo proceso empieza sin apps marcadas.

Se retiró la adición automática de drivers por `lspci`: detectaba fabricantes en
cualquier dispositivo PCI y añadía paquetes sin mostrarlos al usuario. El Tour
solo añade las aplicaciones elegidas y sus dependencias. Las actualizaciones
de paquetes existentes se describen antes de la operación.

## Instalación, cierre y errores

La operación ejecuta `yay -Syu --needed -- <paquetes>` en una terminal interactiva.
Actualiza el sistema antes de instalar y deja al usuario revisar/confirmar las
operaciones, incluyendo AUR. No usa `--noconfirm`. La selección vacía termina el
recorrido sin abrir una terminal ni actualizar el sistema.

Se evita `-Sy` porque Arch no soporta actualizaciones parciales:
[System maintenance](https://wiki.archlinux.org/title/System_maintenance#Partial_upgrades_are_unsupported).
Konsole usa `--separate --nofork` y XFCE usa `--disable-server` para que el proceso
lanzado permanezca vinculado a la operación, incluso si ya había otra terminal:
[Konsole](https://docs.kde.org/trunk_kf6/en/konsole/konsole/command-line-options.html),
[XFCE](https://docs.xfce.org/apps/xfce4-terminal/command-line).

El shell conserva el código de salida de yay y escribe un informe en un
directorio temporal privado (0700). Solo se anuncia éxito si tanto el proceso
como el informe indican éxito. Un informe ausente, una terminal que no inicia,
un código de error o una interrupción deja la página en error y conserva el
inicio automático. El informe temporal se elimina al terminar.

Mientras la instalación está en curso se bloquean Atrás, Finalizar y el cierre
de la ventana. Para cancelar, se interrumpe la operación en la terminal. Al
fallar, Atrás permite corregir la selección y reintentar; Cerrar conserva el
Tour para el siguiente inicio. No se borra el autostart tras un fracaso.

Tras el éxito, Finalizar guarda la opción «Abrir al iniciar» (desmarcada por
defecto) y cierra. Si no se marca, elimina únicamente el `.desktop` del usuario;
si se marca, lo conserva. Cerrar la ventana antes de Finalizar conserva el inicio
automático. Los errores al guardar esa preferencia se muestran y permiten
reintentar. Se usa `~/.config/autostart`, el mismo lugar que comprueba Niri.

## Validación reproducible y límites

Desde la raíz del repositorio:

```bash
cargo check --offline --locked --manifest-path rust/Cargo.toml -p churros-tour
cargo test --offline --locked --manifest-path rust/Cargo.toml -p churros-tour
cargo clippy --offline --locked --manifest-path rust/Cargo.toml -p churros-tour --all-targets --no-deps -- -D warnings
python3 scripts/test-tour.py
./churros check
git diff --check
```

Las cinco pruebas de biblioteca no necesitan pantalla. La prueba GTK adicional
se omite en `cargo test` ordinario. `scripts/test-tour.py` la ejecuta en Broadway
con sockets Unix privados, HOME/config/cache temporales, y terminal/yay
simulados. No instala software ni se conecta a la sesión del escritorio.
Verifica todas las casillas, los cuatro perfiles, el paso a Personalizado, la
selección vacía inicial de otro recorrido, la seguridad de la vista previa,
los códigos 0/1/42/130, una terminal que sale con 0 sin ejecutar yay, un error de
arranque de terminal y la conservación del autostart tras el fracaso.

Estas pruebas verifican selección y manejo de resultados; no prueban descargas,
resolución de dependencias o instalación real de los 37 paquetes. No se construyó
una ISO ni se probó el primer login en VM. Sigue pendiente comprobar Niri, XFCE y
KDE en una ISO nueva con éxito, cancelación y reintento reales, y confirmar la
limpieza de server. El arranque y las terminales por edición se auditaron en el
código; no se declara validación del escritorio instalado.
