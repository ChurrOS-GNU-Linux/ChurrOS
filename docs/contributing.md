# Contribuir a ChurrOS

Esta guía explica cómo proponer cambios, qué pruebas pide cada tipo de cambio y cómo ayudar sin escribir código.

Antes de empezar:

- Lee los [principios del proyecto](principios.md). Todo PR se revisa contra ellos. Los cambios grandes (un programa, una edición o una arquitectura nuevos, o retirar una funcionalidad) se proponen primero en un issue y no se empiezan hasta que se aprueben, como explica [Cómo se decide](principios.md#cómo-se-decide).
- Al participar aceptas el [código de conducta](../CODE_OF_CONDUCT.md).
- Las vulnerabilidades no se reportan en issues públicos: sigue [SECURITY.md](../SECURITY.md).
- Para preparar el entorno de desarrollo, ve a [Getting Started](getting-started.md). La referencia de `./churros` está en [CLI](cli.md) y la organización del repositorio, en [Estructura del proyecto](project-structure.md).

---

## Flujo de trabajo

1. Si no tienes permiso de escritura en el repositorio, haz un fork.
2. Crea una rama desde `origin/main` actualizado. No reutilices ramas ya fusionadas.
3. Haz el cambio en commits pequeños, uno por cambio lógico.
4. Ejecuta las pruebas que pide tu tipo de cambio (tabla de abajo).
5. Actualiza la documentación que describe lo que has cambiado.
6. Abre un pull request hacia `main` y rellena la plantilla.

No se trabaja directamente sobre `main`: cada cambio entra por pull request.

### Ramas

Nombre con el tipo de cambio delante: `fix/…`, `feat/…`, `docs/…`, `perf/…`, `chore/…`. Por ejemplo, `fix/xfce-login-loop`, `feat/port-i686` o `chore/update-org-urls`.

### Commits

Se sigue la forma de Conventional Commits, `tipo(ámbito): descripción`, con el ámbito opcional. Los tipos habituales son `feat`, `fix`, `docs`, `perf`, `build`, `ci`, `chore`, `style`, `test` y `refactor`. El prefijo suele ir en inglés; la descripción, en español o en inglés (el historial usa los dos). Ejemplos reales:

```text
fix(container): sin límite de procesos en el build privilegiado
build(aur): retry makepkg on transient download failures
docs: modelo nuevo de ejecución privilegiada
```

La descripción puede ir en español o en inglés; el historial usa los dos. No mezcles cambios sin relación en un mismo commit y evita mensajes como `update`, `changes` o `fix` a secas.

---

## Pruebas según el tipo de cambio

La guía de capas, qué cubre cada una y las reglas para no debilitarlas están en [Pruebas](testing.md).

Ejecuta siempre `./churros test` (es lo mismo que `./churros check`: `scripts/cli/check.sh` y `tests/static`). Tarda alrededor de un minuto y no construye la ISO. Revisa scripts (sintaxis de Bash y Python, ShellCheck), permisos de lo que se ejecuta en la ISO, que cada comando que lanza el sistema exista en su edición, Calamares, unidades systemd, sintaxis de configuraciones, el contrato de las apps Rust, un build en seco, las listas de paquetes, Niri y Noctalia, las entradas `.desktop`, el perfil de cada arquitectura, las reglas polkit y los helpers privilegiados, que los `.po` compilen y que los enlaces de la documentación funcionen. Con `CHURROS_STRICT=1` (o `CI=true`, que es como corre la CI) una herramienta que falta o una prueba saltada es un fallo; en local solo avisa.

| Si tu cambio toca | Ejecuta además |
|---|---|
| Solo documentación (`*.md`) | Nada más: con `./churros test` basta. Si editas desde la web de GitHub, la CI lo ejecuta en el PR. |
| Apps Rust (`rust/`) | `./churros rust` (build, `#[test]` y clippy) y `./churros test --gui`. Corre en el contenedor de build; `./churros rust --host` lo ejecuta en tu equipo. Para ver una app sin construir la ISO: `./churros apps welcome`, `settings`, `control-center`, `tour` o `popup <nombre>`. Para iterar un binario sin el contenedor: `cargo build --release --manifest-path rust/Cargo.toml` (queda en `rust/target/release/<nombre>`). |
| Listas de paquetes (`archiso/packages.*`) o la configuración de niri (también lo que Ajustes escribe) | `./churros test --container`. |
| Build, paquetes, escritorio, arranque, sistema Live o instalador (`archiso/`, `branding/`, `scripts/`, `installer/`, `Containerfile*`) | `./churros build`, `./churros test --iso --boot`, y comprueba a mano en QEMU lo que has cambiado (ver [VM](vm.md)). |
| Reglas polkit o helpers privilegiados | Lee antes [Ejecución privilegiada](privileged-execution.md). `./churros check` ya ejecuta `scripts/test-polkit-rules.js` y `scripts/test-privileged-helpers.py`. |

Si un cambio en una app Rust afecta a cómo se comporta en el sistema Live, pruébala también en QEMU.

En cada pull request la CI ejecuta `./churros test` y `./churros test --mutations` (`ci.yml`, con modo estricto), `./churros rust`, `./churros test --gui` y `./churros test --container` en x86_64 y en arm64 (`rust.yml`), y las reglas polkit contra `pkexec` y polkitd reales en un contenedor Arch (`polkit.yml`). Si el PR toca lo que entra en la ISO, `iso.yml` la construye y la arranca (`--iso` y `--boot`) en las ediciones x86_64 afectadas. Si toca el perfil arm64, `iso-arm64.yml` construye esa ISO y audita su contenido. Un fallo real que no se arregla en el mismo cambio se anota en `tests/known_issues.toml` (la lista solo se acorta). Cada arreglo lleva la prueba que lo habría detectado y una mutación en `tests/mutations/mutations.toml`. No se borra, se salta ni se suaviza una prueba para que el CI pase.

---

## Qué documentación actualizar

Si un cambio modifica el comportamiento, el mismo PR actualiza el documento que lo describe.

| Cambio | Documento |
|---|---|
| Comando u opción de `./churros` | [cli.md](cli.md) |
| Proceso de build, ediciones, arquitecturas, paquetes locales | [build-system.md](build-system.md) |
| App propia | [apps.md](apps.md) y su documento, si lo tiene |
| Instalador (Calamares) | [installer.md](installer.md) |
| Reglas polkit y helpers que se ejecutan como root | [privileged-execution.md](privileged-execution.md) |
| Configuración del escritorio por edición | [desktop-config.md](desktop-config.md) |
| Servicios y scripts del sistema Live | [live-services.md](live-services.md) |
| Identidad visual | [branding.md](branding.md) |
| Arte o componentes de terceros | [licencias.md](licencias.md) |
| Comandos de build, pruebas o convenciones | [AGENTS.md](../AGENTS.md) y [testing.md](testing.md) |

Un documento nuevo se añade al [índice de la documentación](README.md).

---

## Contribuir sin programar

- **Probar ISOs.** Prueba la ISO publicada (enlace en el [README](../README.md)) o una que construyas tú, en QEMU ([VM](vm.md)) o en un equipo real. Después abre un [informe de hardware o de prueba de ISO](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/new?template=hardware.yml). Un informe en el que todo funciona también sirve.
- **Reportar errores.** Usa el [formulario de error](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/new?template=bug.yml). Busca antes si ya está reportado. Abre un issue por problema, con los pasos para reproducirlo, la edición y la arquitectura, y los registros: `vm_serial.log` si pruebas con `./churros run`, o la salida de `journalctl -b` en el equipo.
- **Mejorar la documentación.** Corrige erratas, pasos que ya no funcionan o datos desactualizados. El [índice](README.md) lista todos los documentos. Un cambio solo de documentación no necesita construir la ISO.
- **Responder preguntas.** Las dudas de uso llegan como issues; responderlas ayuda a quien pregunta y a quien busque lo mismo después.
- **Diseño y arte.** Propón el wallpaper, icono o recurso en un issue antes de abrir un PR. Solo se acepta con autor, licencia y fuente declarados (ver [Licencia de las contribuciones](#licencia-de-las-contribuciones)).
- **Triage.** Intenta reproducir los errores abiertos, pide los datos que falten y señala los duplicados en un comentario. Un issue con `good first issue` o `help wanted` es una buena tarea para empezar.

Traducir los ficheros de `po/` hoy no sirve: las apps Rust escriben sus textos en el código y no usan gettext. Las traducciones esperan a que se resuelva el issue [#148](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/148).

---

## Licencia de las contribuciones

Al abrir un pull request aceptas que tu aportación se publique con estas condiciones:

- **Código y scripts:** GPL-3.0-only ([LICENSE](../LICENSE)). Los ficheros que vienen de otros proyectos conservan su licencia y su aviso de copyright; no los quites.
- **Recursos que no son código** (wallpapers, iconos, logos, sonidos, fuentes): el PR indica el autor, la licencia y la fuente de cada uno, y si se generó con IA. Se añaden al inventario de [licencias.md](licencias.md). Si la licencia no permite redistribuirlo dentro de la ISO, no entra.
- **Personajes y marcas de terceros** (personajes de anime, series o videojuegos, logos de empresas o de otros proyectos): solo entran si su titular permite redistribuirlos, con ese permiso o esa licencia anotados en [licencias.md](licencias.md). Un fan art sin ese permiso no entra.

---

## Contribuciones asistidas por IA

Se aceptan cambios hechos con ayuda de herramientas de IA, con estas condiciones:

1. Se declara. Cada commit asistido lleva un trailer `Co-Authored-By:` o `Assisted-by:` con la herramienta, y el PR lo indica.
2. Una persona es la autora y responde del cambio: lo ha leído, lo entiende, lo ha probado y puede explicarlo en la revisión.
3. No se commitean prompts, notas de traspaso entre agentes ni transcripciones o resúmenes de sesión. Lo que merezca conservarse va al documento que corresponda.
4. Los cambios en código privilegiado (reglas polkit, `churros-pkexec`, `churros-write-root-config`, `churros-update-utils`), en el instalador y en los scripts de build necesitan la aprobación de una persona distinta de la autora.
5. La descripción del PR la escribe o la revisa la persona autora.

---

## Revisión y etiquetas

El fichero [MAINTAINERS](../MAINTAINERS) indica quién responde por cada área del repositorio. Sirve para saber a quién preguntar o pedir revisión. Las asignaciones se dedujeron del historial de commits y de los permisos de escritura del repositorio; si algo está mal, se corrige en un pull request.

Las etiquetas que existen son `bug`, `documentation`, `duplicate`, `enhancement`, `good first issue`, `help wanted`, `invalid`, `question` y `wontfix`. Solo las puede poner quien tiene permiso de triage o de escritura en el repositorio; los formularios de issue ponen algunas automáticamente.
