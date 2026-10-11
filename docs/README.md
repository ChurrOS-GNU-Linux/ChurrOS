# Documentación de ChurrOS

Bienvenido a la documentación oficial de ChurrOS.

Esta documentación está dirigida tanto a desarrolladores como a futuros colaboradores del proyecto y describe el funcionamiento interno de la distribución, su sistema de construcción, herramientas y objetivos.

---

# Índice

## Introducción

- [Getting Started](getting-started.md)
- [Project Structure](project-structure.md)

## Desarrollo

- [Build System](build-system.md)
- [Branding](branding.md)
- [CLI](cli.md)
- [Development](development.md)
- [Apps](apps.md)
- [Popups](popups.md)
- [Preferences](preferences.md)
- [Services](services.md)
- [Login Greeter](login-greeter.md)
- [Desktop Config](desktop-config.md)
- [Live Services](live-services.md)
- [Server](server.md)
- [Installer](installer.md)
- [Privileged Execution](privileged-execution.md)
- [Boot](boot.md)
- [VM](vm.md)

## Publicación

- [Release](release.md)

## Mantenimiento y Recuperación

- [Rollback](rollback.md)

## Proyecto

- [Roadmap](roadmap.md)
- [Goals](goals.md)
- [Vision](vision.md)
- [Contributing](contributing.md)
- [Devlog](devlog.md)

---

# Objetivo de la documentación

La documentación tiene como propósito facilitar el desarrollo de ChurrOS.

Todo cambio importante realizado en el proyecto debe ir acompañado de su respectiva documentación para mantener el repositorio organizado y accesible.

---

# Organización

Cada documento aborda un aspecto específico del proyecto.

| Documento | Descripción |
|-----------|-------------|
| Getting Started | Configuración inicial del entorno de desarrollo. |
| Project Structure | Organización de carpetas y archivos. |
| Build System | Funcionamiento del sistema de compilación. |
| Branding | Personalización e identidad de ChurrOS. |
| CLI | Herramienta de desarrollo `./churros`. |
| Development | Flujo de trabajo recomendado para desarrollar ChurrOS. |
| Apps | Apps oficiales GTK4 en Rust (welcome, control-center, settings, popups). |
| Popups | Sistema de popups (audio, battery, bluetooth, brightness, network, power). |
| Preferences | App `churros-settings` — tema, accent, fuentes, cursor, wallpaper, power, etc. |
| Services | Wrappers de servicios del sistema (wpctl, upower, nmcli, brightnessctl, etc). |
| Login Greeter | Pantalla de inicio de sesión ReGreet (macOS style), greetd, cage y autologin. |
| Desktop Config | Configuración del escritorio live (Niri, Noctalia, greetd, usuario). |
| Live Services | Servicios systemd y hooks del Live ISO. |
| Boot | Sistema de arranque (GRUB UEFI + Syslinux BIOS). |
| VM | Máquina virtual de desarrollo con QEMU/KVM. |
| Release | Proceso para generar una versión oficial. |
| Rollback | Sistema de snapshots Btrfs y recuperación ante fallos. |
| Roadmap | Estado actual y objetivos futuros del proyecto. |
| Goals | Metas generales y alcance del proyecto. |
| Vision | Filosofía y metas de ChurrOS. |
| Contributing | Guía para contribuir al proyecto. |
| Devlog | Registro cronológico del desarrollo y hitos alcanzados. |

---

# Convenciones

Durante el desarrollo se siguen las siguientes convenciones:

- Utilizar nombres descriptivos para archivos y directorios.
- Documentar cualquier cambio importante.
- Mantener el código organizado y legible.
- Priorizar la simplicidad sobre soluciones complejas.
- Automatizar tareas repetitivas siempre que sea posible.

---

# Estado

La documentación evoluciona junto con el proyecto.

Es posible que algunos documentos describan funcionalidades que aún se encuentran en desarrollo o planificación.
