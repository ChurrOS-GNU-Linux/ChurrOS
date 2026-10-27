# Roadmap

Hoja de ruta de ChurrOS: qué está hecho y qué falta. Puede cambiar conforme evolucione la distribución; los objetivos grandes nuevos se añaden después de aprobarse según [Cómo se decide](principios.md#cómo-se-decide).

---

## Estado actual

La última versión publicada es la **1.4** (25 de octubre de 2026): ISOs x86_64 de las ediciones Niri y XFCE en [download.churroslinux.org](https://download.churroslinux.org/). En el repositorio también se construyen la edición Servidor (x86_64) y la edición Niri para aarch64, y de forma experimental la edición Raspberry Pi Lite (aarch64) y un port i686 sin sesión gráfica ni instalador. Detalle en el [README](../README.md#ediciones).

ChurrOS sigue en etapa temprana. El objetivo principal es consolidar esa base (identidad de arranque, repositorio propio firmado y documentación de usuario) antes de ampliar el alcance, como piden los [principios](principios.md).

---

## Fase 1 — Fundación

Construir la infraestructura principal del proyecto.

- [x] Crear el repositorio.
- [x] Configurar ArchISO.
- [x] Construir la primera ISO.
- [x] Crear la CLI de ChurrOS.
- [x] Sistema de branding.
- [x] Documentación oficial.
- [x] Integración con QEMU.
- [x] CI con `./churros check` (GitHub Actions).
- [x] Versión Alpha pública.

---

## Fase 2 — Identidad

Dar personalidad propia a la distribución.

- [x] Logo oficial.
- [ ] Mascota oficial (en diseño, ver [branding/mascot.md](../branding/mascot.md)).
- [x] Wallpapers oficiales.
- [x] Fastfetch personalizado.
- [ ] Plymouth gráfico. Hoy el sistema instalado lleva el hook y un tema `churros` en modo texto; `churros.script` existe pero no se usa, y en el Live Plymouth está enmascarado.
- [x] Tema de ReGreet (pantalla de inicio de sesión de greetd), ver [Login Greeter](login-greeter.md).
- [x] Iconos de las apps de ChurrOS (el tema de iconos es Papirus-Dark).
- [ ] Cursor propio (hoy Adwaita).
- [x] Tema de GRUB (sistema instalado, vía Calamares).

---

## Fase 3 — Escritorio

Construir una experiencia de escritorio moderna.

- [x] Niri configurado.
- [x] Noctalia (barra, notificaciones, OSD, dock, lanzador y centro de control).
- [x] foot.
- [x] Menú de sesión con wlogout (`Mod+Shift+E`).
- [x] Waybar, Fuzzel y Mako, instalados como alternativa; no arrancan por defecto en Niri (Fuzzel queda en `Mod+Shift+Space`).
- [x] Tema oficial.

---

## Fase 4 — Instalador

Instalador gráfico de ChurrOS, basado en Calamares.

- [x] Interfaz gráfica (Calamares con branding ChurrOS).
- [x] Particionado automático.
- [x] Particionado manual.
- [x] Selección de idioma.
- [x] Selección de zona horaria.
- [x] Creación de usuario.
- [x] Instalación del bootloader (GRUB en UEFI y en BIOS; Syslinux solo arranca la ISO Live en BIOS).
- [x] Configuración inicial.

---

## Fase 5 — Ecosistema

Herramientas propias y paquetes.

- [ ] Repositorio pacman `[churros]` firmado, en lugar de paquetes sueltos y del bundle de utilidades (#141).
- [ ] Firma obligatoria de las actualizaciones de utilidades (#139).
- [ ] Paquetes propios publicados. Hoy Calamares, Bazaar, yay, wlogout y python-pywal se compilan en local durante el build y no hay repositorio remoto.
- [x] ChurrOS CLI.
- [x] Actualizador (pacman, Flatpak y utilidades de ChurrOS).
- [x] Rollback con snapshots btrfs (`churros-snapshot` + hook de pacman).
- [x] Aplicación de bienvenida (`churros-welcome`, Rust).
- [x] Herramienta de configuración (`churros-settings`, Rust).
- [x] Centro de control (`churros-control-center`, Rust). En Niri lo sustituye el centro de control de Noctalia (#134).
- [x] Popups integrados (`churros-popup`: audio, bluetooth, battery, brightness, network, power). En Niri no tienen atajo: los cubre Noctalia.
- [x] Tour de bienvenida (`churros-tour`, Rust), que se limpia al instalar.

---

## Fase 6 — Publicación y comunidad

Publicar versiones de forma periódica y abrir el proyecto a más gente.

- [x] Versiones públicas periódicas (la actual está en [`VERSION`](../VERSION)).
- [ ] Primera versión estable. Falta definir qué criterios la marcan.
- [x] Sitio web: [churroslinux.org](https://www.churroslinux.org/). Falta actualizar sus enlaces al repositorio de la organización ChurrOS-GNU-Linux.
- [x] Descargas en download.churroslinux.org. GitHub Releases solo tiene las ISO de v0.1.1 y v0.6 y el bundle de utilidades de v1.0.
- [ ] Sumas SHA-256 (y firma) publicadas junto a cada ISO.
- [ ] Mirrors para las ISO y para el repositorio de paquetes.
- [ ] Documentación de usuario: instalar, primer inicio, actualizar y recuperar el sistema.
- [ ] Wiki oficial. La wiki de GitHub solo tiene un esbozo de julio de 2026.
- [x] Servidor de Discord.
- [ ] Foro público para preguntas y ayuda de usuarios.

---

## Objetivos a largo plazo

- Una distribución estable y fácil de mantener.
- Identidad visual completa (mascota, Plymouth gráfico, cursor).
- Una comunidad activa, con foro público.
- Documentación para usuarios, no solo para quien desarrolla.
- Publicaciones periódicas con sumas de verificación, firma y mirrors.

Un instalador propio que sustituya a Calamares, o cualquier otra app o herramienta propia nueva, pasa por la [regla para programas nuevos](principios.md#regla-para-programas-nuevos).

---

## Seguimiento

Quien termina una tarea de esta lista la marca en el mismo PR que la cierra. Si un PR cambia algo que aquí aparece como hecho o pendiente, actualiza la casilla.
