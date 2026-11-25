# Mutaciones nuevas

Cada PR añade aquí **su propio fichero** (`<tema>.toml`, por ejemplo
`snapshots-manuales.toml`) con sus `[[mutation]]`, en el mismo formato que
`../mutations.toml` (está explicado al principio de `../run_mutations.py`).

`../mutations.toml` ya no crece: cuando todas las mutaciones se añadían al final
de ese fichero, cada PR que se fusionaba dejaba en conflicto a los demás.
`run_mutations.py` lee `mutations.toml` y luego estos ficheros por orden de
nombre; un nombre de mutación repetido, aunque esté en otro fichero, es un
error.
