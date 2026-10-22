# Pruebas

ChurrOS se prueba en capas. Las de abajo tardan segundos y corren en cada pull
request; las de arriba construyen y arrancan la ISO de verdad. Cada capa
detecta fallos que la anterior no puede ver.

| Capa | Comando | Tarda | Qué ve | CI |
|------|---------|-------|--------|----|
| Estática | `./churros test` | ~1 min | el repo: cada referencia entre ficheros | `ci.yml`, cada PR |
| Autoprueba | `./churros test --mutations` | ~5 min | si las pruebas siguen detectando lo que dicen | `ci.yml`, cada PR |
| Rust | `./churros rust` | ~10 min | compila y prueba `rust/` (build, test, clippy) | `rust.yml` |
| Apps GTK | `./churros test --gui` | ~5 min | cada app y cada popup arrancan en release sin morir (`scripts/test-gui-smoke.py`); los tests de widgets del recorrido (`scripts/test-tour.py`) | `rust.yml` |
| Contenedor Arch | `./churros test --container` | ~5 min | los repos reales de Arch (`pacman`), `niri validate` (también de lo que escribe Ajustes) | `rust.yml` |
| ISO | `./churros test --iso [ISO]` | ~2 min | el producto final, sin arrancarlo | `iso.yml`, `iso-arm64.yml` |
| Arranque | `./churros test --boot [ISO]` | 3 min con KVM | la sesión Live en QEMU, desde dentro | `iso.yml` |
| Manual | `./churros run` | — | lo que todavía no se automatiza (ver abajo) | — |

`CHURROS_STRICT=1` (y `CI=true`, que GitHub exporta) hace que una herramienta
que falta, o una prueba saltada, sea un fallo. En local solo avisa, para no
obligar a instalarlo todo: `./install-deps.sh` instala lo necesario.

## Qué ejecutar antes de abrir un PR

- Siempre: `./churros test`.
- Si tocas `rust/`: `./churros rust` y `./churros test --gui`.
- Si tocas listas de paquetes (`archiso/packages.*`), la configuración de
  niri o lo que Ajustes escribe en ella (`rust/preferences/src/services/`):
  `./churros test --container`.
- Si tocas el escritorio, el instalador, el arranque o el build:
  `./churros build`, luego `./churros test --iso --boot`, y un vistazo en
  `./churros run`.

`iso.yml` repite la construcción y el arranque en los PR que tocan lo que entra
en la ISO: siempre la edición niri, más cada edición x86_64 cuyos ficheros toca
el PR (`tests/iso/pick_editions.py`: por la ruta, como la lista de XFCE o la
sesión X, o por el contenido, como un script común que decide según la
edición; `build.sh`, la bienvenida o `known_issues.toml` construyen todas). Arranca por UEFI; por BIOS (syslinux) solo si el PR toca
`archiso/syslinux`, `profiledef.sh` o `tests/vm`. Cada noche, las tres ediciones
x86_64 por UEFI y por BIOS.

## Capa estática: `tests/static`

`./churros check` ejecuta `scripts/cli/check.sh` y, dentro, todas las pruebas de
`tests/static` (`python3 -m unittest discover -s tests/static -t .`). Solo usan
la biblioteca estándar de Python (más PyYAML) y no construyen nada. Modelan el
sistema a partir del repo:

| Módulo | Garantiza |
|--------|-----------|
| `test_shell_scripts.py` | Todo script (por shebang, no por extensión) pasa `bash -n`/`zsh -n` y shellcheck. |
| `test_file_permissions.py` | Todo lo que se ejecuta en la ISO tiene modo ejecutable en `file_permissions` (mkarchiso no conserva el `+x` de git). |
| `test_references.py` | Cada comando que lanza niri, un `.desktop`, XFCE, labwc, waybar, greetd, systemd, un hook de pacman, Calamares o una app Rust existe en la edición que lo lanza. |
| `test_editions.py` | La matriz edición × arquitectura de `build.sh`, la higiene de las listas y los paquetes imprescindibles de cada edición. |
| `test_systemd_units.py` | Unidades, enlaces `*.wants`, `services.sh` y hooks de pacman apuntan a cosas que existen; los `OnCalendar=`/`On*Sec=` de los temporizadores los entiende `systemd-analyze`. |
| `test_calamares_config.py` | YAML estricto, orden de la secuencia, instancias `shellprocess`, comandos que parsean y scripts que existen; `post-install` quita la cuenta y el sudoers sin contraseña del Live (simulado). |
| `test_config_syntax.py` | JSON/JSONC, TOML, XML, `.desktop`, KDL, tema de GRUB y Plymouth parsean; cada entrada de arranque de la Live sabe encontrar el medio; la versión es la de `VERSION`. |
| `test_rust_contract.py` | Binarios desplegados, assets, nombres de popups, `app-id` de las reglas de niri y opciones de los lanzadores. |
| `test_build_dryrun.py` | `build.sh` completo con herramientas falsas para cada edición: lo que recibe mkarchiso y que el árbol queda limpio. |
| `test_release_bundle.py` | El bundle de actualización y su manifiesto. |
| `test_repo_wiring.py` | Que ninguna prueba quede desconectada, que el CI no se ablande, que cada entrada de `known_issues.toml` caiga en la categoría exacta de una prueba y que `AGENTS.md` diga la verdad. |
| `test_harness.py` | Las funciones puras de `tests/iso`, `tests/vm` y `tests/mutations` (que solo corren con una ISO, con QEMU o en el job de mutaciones). |

Una prueba concreta: `python3 -m unittest tests.static.test_references -v`.

Lo que todas comparten (ediciones, listas, `file_permissions`, crates, a qué
paquete pertenece un comando) está en `tests/testlib.py`. Si un comando nuevo
no se llama como su paquete, añádelo a `tests/command_providers.toml`; las
unidades de paquetes van en `tests/unit_providers.toml`. La capa de contenedor
comprueba esas tablas contra `pacman -F`.

## Problemas conocidos: `tests/known_issues.toml`

Cuando una prueba nueva encuentra un fallo real que no se arregla en el mismo
cambio, el fallo se apunta ahí con su id (la prueba lo imprime entre
corchetes) y una nota. La prueba deja de fallar por ese id, pero:

- si aparece un fallo distinto, falla;
- si el fallo apuntado se arregla, falla hasta que se borra la entrada.

La lista solo puede acortarse. No es un sitio para silenciar lo que rompe un
PR: CODEOWNERS pide revisión de quien mantiene el CI para cualquier cambio en
`tests/`.

## Autoprueba: `tests/mutations`

`tests/mutations/mutations.toml` es una lista de regresiones reales y
realistas (quitar `foot` de la lista x86_64, borrar el permiso de
`churros-niri-session`, mover `grub-theme` antes de `bootloader`, una
comilla sin cerrar en un script que solo corre al instalar...). `./churros
test --mutations` aplica cada una en una copia del repo y exige que la prueba
indicada falle con el mensaje esperado. Si una sobrevive, una prueba se ha
debilitado.

Cada vez que se arregla un fallo, la prueba que lo habría detectado lleva su
mutación.

`./churros test --container --mutations` ejecuta las de `requires =
"container"` dentro del contenedor (semanal en `rust.yml`). Las mutaciones de
`rust/` compilan en las copias: cada copia usa su propio `CARGO_TARGET_DIR`.
La base parte del compartido y compila en la línea base (con 30 min de plazo,
por si el target está frío o viejo); cada worker parte de lo que compiló la
base. Al sembrar un target se olvida lo compilado del workspace (sus binarios
llevan dentro las rutas de la copia que los compiló) y se quedan las
dependencias. Cargo identifica los crates del workspace por su ruta relativa
a la raíz y decide por fecha: con un target común, un worker ejecutaría el
binario que acaba de compilar otro, y el `build-rust.sh` del repo original
metería en la ISO un binario compilado desde una copia mutada. En el
contenedor van 2 workers por defecto. Una prueba que agota su plazo recibe
SIGTERM (para cerrar lo que abrió) y, 15 s después, SIGKILL a todo su grupo.

## Apps GTK en Broadway: `./churros test --gui`

`cargo test` no abre ninguna ventana. `./churros test --gui` ejecuta en el
contenedor Arch, cada una sobre su `gtk4-broadwayd` privado, dos pruebas (que
falle una no impide la otra; en `rust.yml` son dos pasos):

- `scripts/test-tour.py`: los tests `#[ignore]` del recorrido, que manejan por
  API sus páginas de personalización e instalación (con un `yay` y terminales
  falsos).
- `scripts/test-gui-smoke.py`: compila el workspace en release (el perfil de
  la ISO, con `panic = "abort"`) y arranca cada binario desplegado
  (`deploy = true`) y `churros-popup` con cada nombre de `POPUPS`, dentro de
  `dbus-run-session`, con HOME (copia del skel) y `/tmp/churros` propios.
  Cada arranque se hace dos veces: tal cual (en el contenedor faltan nmcli,
  wpctl, upower, niri...) y `[herramientas fallan]`, con cada programa que
  lanzan las apps (el escaneo de `test_references.py`) sustituido por uno que
  escribe un error y sale con 1, como `wpctl` antes de que arranque PipeWire.
  Falla si la app termina antes de 5 s (con cualquier código o señal) o si su
  salida o su log de `/tmp/churros` contiene `panicked at`; un `Gtk-CRITICAL`
  solo se avisa. `-k <texto>` arranca solo los que lo contienen
  (`python3 scripts/test-gui-smoke.py -k churros-settings`).

Ninguna de las dos usa la bienvenida, los ajustes, el centro de control o los
popups después de abrirlos; el arranque en QEMU abre además Ajustes y el centro
de control en la sesión niri real.

## Lo que Ajustes escribe en el config de niri

`churros-settings` reescribe `~/.config/niri/config.kdl` (`niri_config.rs`,
`keyboard.rs`, `window_rules_service.rs` y `cursor.rs` de
`rust/preferences/src/services`). niri rechaza el fichero entero por un escape
inválido en una regex, un entero donde espera un decimal o un atajo repetido, y
la sesión siguiente arranca sin la configuración de ChurrOS. El test de cargo
`services::niri_writers` aplica cada llamada que hacen las páginas, con los
extremos de sus controles, a una copia del config del skel: comprueba que
cambia lo que debe, que no borra nodos de primer nivel ajenos y que guardar sin
tocar nada deja el fichero byte a byte igual. `tests/container/test_niri_config.py`
lo ejecuta y pasa `niri validate` por cada resultado (id
`niri-writers:<llamada>`). Un servicio nuevo que escribe `config.kdl` entra
solo en la comprobación: cada llamada de una página a él necesita un caso en
`niri_writers.rs`, o declararse en `NOT_NIRI_WRITERS` si no escribe el config.

## Capas que necesitan la ISO

`tests/iso/check_iso.py` audita la ISO sin arrancarla: entradas El Torito,
`archisosearchuuid`, permisos reales dentro de `airootfs.sfs`, que las apps
Rust y Calamares (con sus módulos) son ELF de la arquitectura con todas sus
bibliotecas, la sesión de greetd, los usuarios, `pkglist`, los enlaces de
systemd y `/etc/calamares`.

`tests/vm/boot_smoke.py` arranca la ISO en QEMU por el camino real (UEFI y
GRUB, o BIOS y syslinux) y habla con `qemu-guest-agent`, que instalan todas las
ediciones salvo `pi` (fallo conocido `edition-pkg:pi/aarch64:qemu-guest-agent`).
Comprueba desde dentro que systemd termina sin unidades fallidas; que greetd
abre una sesión activa de `churros` (logind la registra como `tty`, así que lo
gráfico se comprueba por los procesos del escritorio, el IPC de niri y la
pantalla); que el gestor de usuario de `churros` no tiene unidades fallidas ni
mal escritas y que los temporizadores del skel están activos; que los procesos
del escritorio siguen vivos; que niri tiene abierta la bienvenida y que
Ajustes y el centro de control abren su ventana; que el diario no tiene errores
de permisos, de ejecución ni de configuración (un id por fallo); que no hay
core dumps y que la pantalla no está negra. Deja `serial.log`, `journal.txt`,
`screen.png` y `report.json` en `out/boot-<iso>-<firmware>/` (y como artefacto
del CI), también si el arnés falla a medias; si la prueba no llega al final,
no da por arreglado ningún fallo conocido.

```bash
./churros build
./churros test --iso --boot
python3 tests/vm/boot_smoke.py out/ChurrOS-*.iso --firmware bios --keep
```

La VM recibe una GPU con 3D (virgl): niri 26.04 descarta el renderizado EGL
por software, así que con una `virtio-vga` sin 3D arranca sin ninguna salida y
la pantalla queda negra (lo mismo le pasa a quien prueba ChurrOS en una VM sin
aceleración 3D). Si el equipo tiene GPU, QEMU usa su nodo DRM
(`egl-headless`); si no, como en los runners de GitHub, abre su ventana SDL en
un Xvfb privado y usa el GL de Mesa (`xvfb`, `x11-apps`, `qemu-system-gui`,
`libgl1-mesa-dri`). La captura de pantalla sale de esa ventana con `xwd`.
`--gpu plain` reproduce el caso sin 3D.

Con KVM tarda 2-4 minutos; sin KVM (emulación por software, con virgl) unos
8-10. La espera sale del acelerador que usa la VM: una ISO i686 o aarch64 en un
equipo x86_64 va por TCG aunque haya `/dev/kvm`.

## Reglas para cambios hechos con ayuda de IA

- No se borra, se salta ni se suaviza una prueba para que el CI pase. Si una
  prueba falla, o el cambio está mal o la prueba tiene un error que hay que
  explicar en el PR.
- Un fallo arreglado lleva la prueba que lo habría detectado y su mutación.
- Una entrada nueva en `known_issues.toml` explica qué falla y por qué no se
  arregla en ese PR.
- `AGENTS.md` describe el sistema tal como es: `test_repo_wiring.py` falla si
  afirma cosas que el repo contradice.

## Lo que todavía se prueba a mano

- La instalación con Calamares hasta el disco y el primer arranque del
  sistema instalado (con ReGreet, sin autologin).
- Las ediciones `pi` (aarch64) e i686 no se arrancan en CI.
- Hardware real: Wi-Fi, Bluetooth, audio, suspensión.
- Usar la bienvenida, los ajustes, el centro de control y los popups (pulsar,
  cambiar de página): `./churros test --gui` y el arranque solo comprueban que
  abren.
