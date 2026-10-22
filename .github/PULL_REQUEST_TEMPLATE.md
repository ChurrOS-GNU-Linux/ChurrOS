## Resumen

-

## Qué ediciones y arquitecturas afecta

- [ ] niri x86_64
- [ ] xfce x86_64
- [ ] server x86_64
- [ ] niri aarch64 / pi aarch64
- [ ] i686
- [ ] Ninguna (CLI, docs, CI)

## Cómo se probó

- [ ] `./churros test` (capa estática: `check.sh` + `tests/static`) en verde
- [ ] `./churros rust` y `./churros test --gui` (si toca `rust/`)
- [ ] `./churros test --container` (si toca listas de paquetes o configuración de niri)
- [ ] `./churros build` + `./churros test --iso --boot` (si toca escritorio, instalador o build)
- [ ] Probado a mano en `./churros run` (qué se comprobó: …)

## Pruebas

- [ ] Este cambio arregla un fallo y añade la prueba que lo habría detectado (y su mutación en `tests/mutations/mutations.toml`)
- [ ] No se ha borrado, saltado ni suavizado ninguna prueba para que el CI pase
- [ ] Si añade una entrada a `tests/known_issues.toml`, la nota explica qué falla y por qué no se arregla aquí

## Asistencia de IA

- [ ] El cambio se hizo con ayuda de una IA y una persona leyó el diff completo

## Notas

-
