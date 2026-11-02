# QA visual

Flujo para ver, en una pull request, si el diff cambia la interfaz de
ChurrOS. El clasificador decide. Si el diff es visual, se construyen la ISO
del PR y la de `main`, y se capturan las mismas pantallas de las dos. El
informe de comparación se documenta aquí cuando existe.

El clasificador no sustituye a `./churros test`. Un diff que no es visual
sigue solo con la CI habitual.

## Clasificador

`.github/workflows/visual-qa-classify.yml` corre en cada `pull_request`. El
job `classify` escribe la salida `visual=true` o `visual=false` (también
`decider`, `model` y `probability`) y pone o quita la etiqueta `visual-qa`.

`scripts/qa/visual/classify.py` decide en este orden:

1. **Reglas de ruta.** El diff es visual si algún fichero cae en `branding/`,
   `archiso/airootfs/etc/skel/.config/{noctalia,waybar,wlogout,niri}`,
   `usr/share/churros/{styles,defaults,pi}`, `usr/share/plymouth`,
   `usr/share/color-schemes`, un directorio `icons`,
   `installer/calamares/branding`, `grub-theme` o `churros-theme`.
   Documentación, pruebas, `.github/` y `scripts/{cli,lib,qa}` no lo son.
   Cualquier otra ruta es ambigua.
2. **Jev (TypeSafe).** Solo el diff ambiguo. Una pregunta Choice con las
   opciones `visual` y `not_visual`, `POST https://api.typesafe.ai/v1/systemone`,
   modelo por defecto `jev-latest`. La clave es el secret `TYPESAFE_API_KEY`
   y viaja en `Authorization: Bearer`. Si la probabilidad más alta de las dos
   opciones llega al umbral, esa opción es la decisión.
3. **Claude Haiku.** Si la probabilidad máxima de Jev queda por debajo del
   umbral, o Jev responde con error, Haiku contesta sí o no. La clave es el
   secret `ANTHROPIC_API_KEY` (`x-api-key`). El modelo por defecto es
   `claude-haiku-4-5`.

El log dice qué modelo decidió y la probabilidad. Las claves no se imprimen,
ni el cuerpo de error de la API.

| Variable | Secret o variable | Defecto |
|---|---|---|
| `TYPESAFE_API_KEY` | secret | — |
| `ANTHROPIC_API_KEY` | secret | — |
| `VISUAL_QA_JEV_MODEL` | variable | `jev-latest` |
| `VISUAL_QA_JEV_THRESHOLD` | variable | `0.8` |
| `VISUAL_QA_MODEL` | variable | `claude-haiku-4-5` |

El umbral compara la probabilidad más alta de `probabilities`, no
`confidence`. `confidence` se anota en el log y no decide. En el empate
exacto con el umbral (0.8) se acepta a Jev: solo un valor menor escala.

Si no hay clave (una pull request desde un fork no recibe los secrets) o
Jev y Haiku fallan, un diff ambiguo sale `visual=true` con
`decider=unresolved-default-visual` y `model=none` (no una cadena vacía).
Así no se salta la QA. Una ruta que las reglas ya descartan sigue en
`visual=false`. El script sale con 0. Una invocación mal formada sale con 2.

El job lleva `continue-on-error: true`. No publica un commit status propio
y no debe añadirse a los checks requeridos de `main`: un fallo de la API o
del etiquetado no impide fusionar. En una pull request desde un fork el
token no puede crear la etiqueta; las reglas de ruta siguen aplicando y
un diff ambiguo queda visual por ese defecto.

La forma de la llamada a Jev está en `ask_jev`, alineada con la primitiva
Choice de [docs.typesafe.ai](https://docs.typesafe.ai/primitives/choice) y
con [el endpoint system-one](https://docs.typesafe.ai/api/system-one).

## ISO del PR y de main

`.github/workflows/visual-qa-iso.yml` corre en cada pull request y también
a mano (`workflow_dispatch`, edición `niri`, `xfce` o `server`). El job
`gate` vuelve a ejecutar el clasificador. El job `iso` solo arranca si
`visual=true`. Un dispatch manual construye siempre.

Construye dos imágenes con `scripts/qa/visual/build-local.sh --container`,
la misma receta que `iso.yml` (`./churros build --container`), edición
`niri` por defecto:

- la del commit del PR, artefacto `visual-qa-pr-<sha>-<edición>`;
- la del padre de ese commit (en un dispatch, `origin/main`), artefacto
  `visual-qa-main-<sha>-<edición>`.

Cada artefacto lleva la ISO y `SHA256SUMS`. La de main se conserva 7 días
y el script la reutiliza por SHA: primero
`${XDG_CACHE_HOME:-~/.cache}/churros/visual-iso/<sha>/<edición>/` y, si hay
`gh` con `GH_TOKEN` y `GITHUB_REPOSITORY`, el artefacto del mismo nombre.
`./churros build` borra `out/` al empezar; el script aparta las ISO fuera
de ese directorio y las publica en `out/qa-visual/{pr,main}/` al terminar.

Los dos jobs llevan `continue-on-error`. No son checks requeridos.

Un runner gratuito puede quedarse sin disco o sin los 240 minutos del job
(son dos construcciones seguidas, cada una del orden de la ISO nocturna).
En ese caso el mismo script vale en una máquina propia:

```bash
# Arch, con las herramientas de ./churros doctor
scripts/qa/visual/build-local.sh --edition niri

# Sin pacman en el host (el caso del runner de GitHub)
scripts/qa/visual/build-local.sh --container --edition niri
```

`--role pr`, `--role main` o `--role both` (el defecto). `--base <sha>` fija
el commit de main. `--dry-run` escribe el plan en JSON y no construye nada.

## Capturas

`.github/workflows/visual-qa-capture.yml` corre en cada pull request. Si
`visual=true`, espera los artefactos de la ISO (por defecto 90 minutos,
`VISUAL_QA_WAIT_SECONDS`) y arranca cada una con
`scripts/qa/visual/capture.sh`.

- `out/before` es la ISO de main. `out/after` es la del PR.
- El plan sale de `scripts/qa/visual/screens.py`: las rutas eligen, en un
  orden fijo, `grub`, `plymouth`, `desktop`, `bar`, `launcher`,
  `session-menu` e `installer`. Un diff visual que no casa con ninguna
  pide el escritorio.
- KVM si `/dev/kvm` se puede abrir; si no, TCG. La sesión gráfica es
  virgl en un Xvfb: `virtio-vga-gl` a 1920×1080 (EDID) y SDL con GL. VNC
  no se combina con ese contexto GL (QEMU muere al crear el socket). QMP
  sigue abierto; si el proceso no sigue vivo un segundo después, se
  reintenta sin GL. Sin 3D niri no pinta y el manifiesto queda
  `capture-failed`.
- GRUB y Plymouth no usan una espera fija. Se muestrean fotogramas hasta
  ver el menú (el timeout del menú en la ISO es 15 s) y, si aparece, un
  splash. Si la línea de órdenes del kernel no lleva `splash` ni
  `plymouth`, o el fotograma siguiente ya es texto del kernel, Plymouth
  queda `not-in-boot` en vez de una toma tardía.
- OpenCode no arranca hasta que un fotograma posterior al texto del
  kernel es gráfico (`bootframes.py wait-desktop`). En TCG el escritorio
  tarda unos 4-6 min; el plazo es `VISUAL_QA_DESKTOP_TIMEOUT` (por defecto
  600 s). Cada PNG se clasifica: si es texto, negro o no mide 1920×1080,
  esa pantalla queda fallida y el agente no pasa a `ok`.
- La captura GL usa `xwd` sobre la ventana de QEMU (`-name` o `-id`), no
  sobre la raíz del Xvfb, y recorta el borde negro. El Xvfb es 2560×1600
  para que la ventana de 1920×1080 quepa entera.
- El prompt usa `scripts/qa/visual/vmctl.py`. La tecla Mod es el qcode
  `meta_l`. La clave no entra en el prompt; si el log la repite, el script
  la tapa.
- `manifest.json` lista el plan, el acelerador, VNC y cada toma. Si la ISO
  no llegó, el estado es `iso-missing` y no se arranca QEMU.

Los artefactos son `visual-qa-before-<sha>` y `visual-qa-after-<sha>`. El
job lleva `continue-on-error` y no es un check requerido.

niri 26.04 no pinta sin 3D. Con `VISUAL_QA_GPU=auto` (el defecto) se usa
virgl si hay un nodo DRM o Xvfb; si no, la VGA es plana y el escritorio
puede salir negro. Las pantallas de arranque siguen saliendo por QMP.

```bash
python3 scripts/qa/visual/screens.py --paths-file changed.txt --out plan.json
scripts/qa/visual/capture.sh --dry-run --plan plan.json --out out/before --role before
scripts/qa/visual/capture.sh --iso out/qa-visual/main/*.iso --plan plan.json --out out/before --role before
scripts/qa/visual/capture.sh --iso out/qa-visual/pr/*.iso --plan plan.json --out out/after --role after
```
