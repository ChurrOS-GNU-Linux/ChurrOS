# QA visual

Flujo para ver, en una pull request, si el diff cambia la interfaz de
ChurrOS. Esta página cubre el clasificador. La construcción de las ISO, las
capturas y el informe de comparación entran en los cambios que siguen a este
y se documentan aquí cuando existen.

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
`decider=unresolved-default-visual`. Así no se salta la QA. Una ruta que
las reglas ya descartan sigue en `visual=false`. El script sale con 0.
Una invocación mal formada sale con 2.

El job lleva `continue-on-error: true`. No publica un commit status propio
y no debe añadirse a los checks requeridos de `main`: un fallo de la API o
del etiquetado no impide fusionar. En una pull request desde un fork el
token no puede crear la etiqueta; las reglas de ruta siguen aplicando y
un diff ambiguo queda visual por ese defecto.

La forma de la llamada a Jev está en `ask_jev`, alineada con la primitiva
Choice de [docs.typesafe.ai](https://docs.typesafe.ai/primitives/choice) y
con [el endpoint system-one](https://docs.typesafe.ai/api/system-one).
