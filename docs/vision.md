# Visión

ChurrOS nació con una idea simple:

> Construir una distribución Linux moderna, elegante y con identidad propia.

No buscamos hacer otra personalización de Arch Linux, sino una distribución que ofrezca una experiencia coherente desde que se arranca la ISO hasta el primer inicio de sesión en el sistema instalado.

ChurrOS también es un proyecto para aprender: entender cómo se construye una distribución Linux y compartir lo aprendido con quien quiera hacer lo mismo.

---

## A quién va dirigida

- Usuarios nuevos que quieren Arch Linux sin configurarlo desde cero.
- Desarrolladores.
- Personas que quieren un escritorio cuidado desde el primer inicio.

La edición por defecto usa Niri, un compositor Wayland de mosaico con desplazamiento, que necesita aceleración 3D para ir fluido. La edición XFCE ofrece un escritorio tradicional. Todas las ediciones y arquitecturas, y cuáles tienen ISO publicada, están en el [README](../README.md#ediciones).

---

## Qué ofrece hoy

- Instalador gráfico Calamares, con branding y parches de ChurrOS (el port i686 no lo lleva).
- En la edición Niri, Noctalia hace de barra, lanzador, notificaciones, OSD y centro de control, y foot es la terminal. Waybar, Fuzzel y Mako siguen instalados como alternativa.
- Apps propias en Rust: `churros-welcome`, `churros-settings`, `churros-tour`, `churros-control-center` y `churros-popup`. En Niri, el centro de control de Noctalia cubre lo que hacen las dos últimas. Detalle en [Apps](apps.md).
- greetd con ReGreet como pantalla de inicio de sesión, con autologin en el Live.
- Actualizador y rollback con snapshots Btrfs ([Rollback](rollback.md)).
- GPU AMD e Intel con Mesa desde la ISO. Los controladores propietarios de NVIDIA no vienen en la ISO ni los instala Calamares.

---

## Identidad propia

ChurrOS usa Arch Linux como base y quiere ser reconocible por sí misma. Hoy tiene logo, wallpapers, configuración de Fastfetch, tema de GRUB y branding propio en Calamares y en ReGreet. Faltan la mascota, un Plymouth gráfico y un cursor propio: el estado de cada pieza está en el [roadmap](roadmap.md) y dónde vive cada una, en [Branding](branding.md).

---

## Principios

Las decisiones del proyecto se toman según los [principios de ChurrOS](principios.md): cinco principios ordenados, cada uno con una pregunta para revisar cambios, la regla para añadir programas nuevos y el proceso para decidir cambios grandes.

---

## Software libre y comunidad

El código de ChurrOS se publica bajo GPL-3.0 ([LICENSE](../LICENSE)). Las licencias del arte y de los componentes de terceros están en [Licencias](licencias.md).

Cualquiera puede contribuir, programando o no: la guía está en [Contribuir](contributing.md), y la convivencia se rige por el [código de conducta](../CODE_OF_CONDUCT.md). El foro público (GitHub Discussions) todavía no está activado; mientras tanto, las preguntas llegan por los [issues](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues).

---

## Objetivos a largo plazo

- Una distribución estable y fácil de mantener.
- Una identidad visual completa.
- Documentación para usuarios, no solo para quien desarrolla.
- Una comunidad activa, con un foro público.
- Publicaciones periódicas, con sumas de verificación y réplicas (mirrors) para descargar.

El instalador es Calamares. Sustituirlo por uno propio, o añadir otras herramientas propias, pasa por la [regla para programas nuevos](principios.md#regla-para-programas-nuevos). Hoy no hay ninguna propuesta abierta para un instalador propio.
