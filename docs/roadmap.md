# Roadmap

Este documento describe la hoja de ruta oficial de ChurrOS.

Su propósito es definir los objetivos del proyecto y servir como referencia durante el desarrollo.

La hoja de ruta puede cambiar conforme evolucione la distribución.

---

# Estado actual

La versión publicada es **v1.2**. ChurrOS sigue en etapa temprana: hay ISO, tres ediciones de escritorio (Niri, XFCE y KDE Plasma), instalador, apps oficiales, actualizador y rollback.

El objetivo principal es consolidar esa base (identidad de arranque y repositorio propio) antes de ampliar el alcance.

---

# Fase 1 — Fundación

Construir la infraestructura principal del proyecto.

## Objetivos

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

# Fase 2 — Identidad

Dar personalidad propia a la distribución.

## Objetivos

- [x] Logo oficial.
- [x] Mascota oficial.
- [x] Wallpapers oficiales.
- [x] Fastfetch personalizado.
- [ ] Plymouth.
- [ ] Tema / branding de greetd.
- [x] Iconos oficiales.
- [x] Cursor oficial.
- [x] Tema de GRUB (sistema instalado, vía Calamares).

---

# Fase 3 — Escritorio

Construir una experiencia de escritorio moderna.

## Objetivos

- [x] Niri configurado.
- [x] Noctalia (barra, notificaciones, OSD, dock y launcher; Waybar/Mako/Fuzzel como alternativa).
- [x] Waybar.
- [x] foot.
- [x] Fuzzel.
- [x] Wlogout.
- [x] Notificaciones (mako).
- [x] Centro de control (churros-control-center).
- [x] Tema oficial.

---

# Fase 4 — Instalador

Desarrollar el instalador gráfico de ChurrOS.

## Objetivos

- [x] Interfaz gráfica (Calamares con branding ChurrOS).
- [x] Particionado automático.
- [x] Particionado manual.
- [x] Selección de idioma.
- [x] Selección de zona horaria.
- [x] Creación de usuario.
- [x] Instalación del bootloader (GRUB UEFI + Syslinux BIOS).
- [x] Configuración inicial.

---

# Fase 5 — Ecosistema

Crear herramientas propias.

## Objetivos

- [ ] Repositorio oficial.
- [ ] Paquetes propios (en desarrollo — Calamares, yay, wlogout y python-pywal se construyen en local).
- [x] ChurrOS CLI.
- [x] Actualizador (pacman, Flatpak y utilidades de ChurrOS).
- [x] Rollback con snapshots btrfs (`churros-snapshot` + hook de pacman).
- [x] Aplicación de bienvenida (`churros-welcome`, Rust).
- [x] Herramienta de configuración (`churros-settings`, Rust).
- [x] Centro de control (`churros-control-center`, Rust).
- [x] Popups integrados (`churros-popup`: audio, bluetooth, battery, brightness, network, power).
- [x] Tour de bienvenida (`churros-tour`, Rust), que se limpia al instalar.

---

# Fase 6 — Publicación

Publicar la primera versión estable.

## Objetivos

- [x] Versión 1.2.
- [ ] Sitio web.
- [x] GitHub Releases (v0.6). La ISO actual (**v1.2**) se publica en download.churroslinux.org.
- [ ] Wiki oficial.
- [ ] Manual de usuario.
- [ ] Comunidad.

---

# Objetivos a largo plazo

Después de la versión 1.2, ChurrOS buscará convertirse en una distribución Linux completa con identidad propia.

Algunos objetivos futuros incluyen:

- Instalador completamente desarrollado por el proyecto.
- Herramientas propias.
- Aplicaciones propias.
- Identidad visual completa.
- Comunidad activa.
- Documentación extensa.
- Publicaciones periódicas.

---

# Filosofía

El desarrollo de ChurrOS prioriza:

- Calidad.
- Estabilidad.
- Organización.
- Simplicidad.
- Automatización.

No se añadirán características únicamente por cantidad.

Cada nueva función debe aportar valor al proyecto y mantener una experiencia consistente.

---

# Seguimiento

La hoja de ruta será actualizada conforme avance el desarrollo.

Las tareas completadas deberán marcarse como finalizadas y las nuevas funcionalidades se añadirán a la fase correspondiente.