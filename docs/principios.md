# Principios de ChurrOS

> Estos principios rigen desde que el equipo aprueba el pull request que los introduce. Para cambiarlos, ver [Cómo se decide](#cómo-se-decide).

**De dónde sale.** Este documento sustituye a las listas de principios que había en `vision.md`, `goals.md` y `development.md` (estos dos ya retirados), `roadmap.md`, `README.md` y `contributing.md`, que no coincidían entre sí. Recoge lo que tenían en común (calidad antes que cantidad, estabilidad, sencillez, facilidad de mantenimiento, experiencia coherente y software libre), lo ordena y pone a cada principio una pregunta para poder aplicarlo. Deja fuera los objetivos de un instalador y un ecosistema de herramientas propios que aparecían en esas listas: ahora pasan por la [regla para programas nuevos](#regla-para-programas-nuevos).

Unos principios solo sirven si las decisiones los citan. Por eso cada uno trae una pregunta, las plantillas de PR y de propuesta piden indicar cuál aplica, y quien revisa puede aceptar o rechazar un cambio citando su número.

## Los principios, en orden

Cuando dos principios chocan, gana el que está más arriba. Si la respuesta a la pregunta de un principio es «no», el cambio no entra hasta que se resuelva, o el PR explica por qué ese principio no aplica.

### 1. Libre y redistribuible

Lo que crea el proyecto se publica con licencia libre, y todo lo que va en la ISO tiene una licencia conocida que permite redistribuirlo.

- **Pregunta:** ¿cada fichero nuevo que no viene de un paquete de Arch tiene autor, fuente y licencia declarados, y esa licencia permite distribuirlo en la ISO?
- **Ejemplo:** varios iconos de Ajustes (`rust/preferences/assets/icons/`, commit a691eec, agosto de 2026) son copias de Feather (MIT) y Lucide (ISC). Entraron sin el aviso de copyright que exigen esas licencias, y los wallpapers de la ISO siguen sin autor ni licencia declarados ([licencias.md](licencias.md)). Con esta pregunta se habrían anotado al entrar.

### 2. Estabilidad antes que novedades

El sistema tiene que arrancar, instalarse y actualizarse sin romperse, en el Live y en el sistema instalado. Eso va antes que cualquier función nueva.

- **Pregunta:** ¿se ha probado el cambio donde puede romper algo, con las pruebas que pide su tipo de cambio en [contributing.md](contributing.md#pruebas-según-el-tipo-de-cambio), incluido el sistema instalado si lo afecta?
- **Ejemplo:** en la edición XFCE instalada, iniciar sesión devolvía al greeter en bucle porque el arreglo de la sesión solo se aplicaba en el Live. La corrección (3ae0651, PR #175, octubre de 2026) se fusionó probada solo con `./churros check`: su propio commit indica que falta instalar la ISO y entrar desde ReGreet.

### 3. Mantener antes que crear

Calidad antes que cantidad: solo entra lo que alguien puede mantener, con su documentación y una prueba automática. Arreglar lo que ya existe va antes que añadir.

- **Pregunta:** ¿hay una persona con nombre que se compromete a mantener esto, y el cambio trae documentación y una prueba o un check de CI?
- **Ejemplo:** la edición KDE Plasma se creó con un agente de IA (commit 107cfd6, autor `opencode`), entró en `main` el 1 de octubre de 2026 (PR #102) y se retiró el 14 de octubre (a5d8edb): 55 ficheros y unas mil líneas borradas.

### 4. Usar antes que construir

Sencillez: si un paquete de Arch o un componente que ChurrOS ya trae resuelve el problema, se configura ese en lugar de escribir uno propio. Las mejoras se envían al proyecto original cuando se puede.

- **Pregunta:** ¿está comprobado, y escrito en el issue o en el PR, que ningún paquete de Arch ni componente que ya trae ChurrOS cubre esto?
- **Ejemplo:** el instalador es Calamares con el branding de ChurrOS y dos parches (`installer/patches/`), no un instalador escrito desde cero. En sentido contrario, `churros-popup` y `churros-control-center` repiten lo que hace el centro de control de Noctalia; desde el commit ecdf0df (octubre de 2026) la sesión Niri ya no les asigna atajo (comentario en `config.kdl`, issue #134).

### 5. Experiencia coherente

La identidad propia de ChurrOS consiste en que todo se vea y funcione igual desde que arranca la ISO hasta el sistema instalado, en cada edición. Se consigue sobre todo con configuración y branding.

- **Pregunta:** ¿el cambio se ve y se comporta igual en el Live y en el sistema instalado, y en cada edición a la que afecta?
- **Ejemplo:** el tema de GRUB no se queda en la ISO: el paso `shellprocess@grub-theme` de Calamares lo copia al sistema instalado justo después de instalar el cargador de arranque.

## Regla para programas nuevos

Cuenta como programa nuevo una app, un crate, un binario o un script nuevos, una edición nueva o un port a otra arquitectura. Un cambio dentro de algo que ya existe no lo es.

Un programa nuevo solo entra si cumple las cuatro condiciones:

1. Un issue aprobado según [Cómo se decide](#cómo-se-decide) muestra que ningún paquete de Arch ni componente que ya trae ChurrOS lo cubre.
2. Una persona (no una herramienta) se compromete a mantenerlo y figura para esa ruta en [MAINTAINERS](../MAINTAINERS).
3. Tiene tests o un check en `./churros check` o en la CI.
4. Su documentación llega en el mismo PR.

Si el problema se puede resolver en el proyecto original (upstream), se prefiere eso a mantener un programa o un parche propios.

Dejar de mantener algo es un resultado válido. Si nadie se hace cargo de un programa o de una edición, se abre un issue para retirarlo y se decide como un cambio grande.

## Uso de IA

Se pueden usar herramientas de IA para escribir código, documentación o descripciones de PR. Una persona es la autora del cambio y responde de él: lo ha leído, lo entiende y lo ha probado. Que una herramienta pueda generar un programa en una tarde no cambia nada de lo anterior, porque el coste está en mantenerlo: la regla para programas nuevos se aplica igual. Las condiciones concretas (cómo se declara en los commits, qué no se commitea y qué áreas necesitan la revisión de otra persona) están en [Contribuciones asistidas por IA](contributing.md#contribuciones-asistidas-por-ia).

## Cómo se decide

Mantenedor es una persona que figura en [MAINTAINERS](../MAINTAINERS).

- **Cambios pequeños** (arreglos, documentación, ajustes dentro de lo que ya existe): revisión normal del PR. La CI tiene que pasar.
- **Cambios grandes** (una edición, un port o un programa nuevos, o retirar una funcionalidad o una edición): hace falta un issue o una discusión abierta durante al menos 7 días y la aprobación de dos mantenedores distintos de quien lo propone, escrita en ese issue. El PR enlaza el issue.
- **Cambiar este documento:** lo mismo que un cambio grande y, además, que ningún mantenedor se oponga durante ese plazo.

La [plantilla de PR](../.github/PULL_REQUEST_TEMPLATE.md) y el formulario de propuesta de mejora preguntan qué principio aplica y qué se deja de mantener a cambio.
