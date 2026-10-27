# Documentación de ChurrOS

Índice de toda la documentación del repositorio, ordenado según lo que vengas a hacer. Si buscas descargar la ISO, empieza por el [README principal](../README.md).

`./churros check` (y `./churros test`, que lo incluye) comprueba que cada documento de `docs/` aparece en este índice y que los enlaces relativos de los `.md` apuntan a ficheros que existen.

## Usar ChurrOS

Todavía no hay un manual de usuario completo (está en el [roadmap](roadmap.md)). Mientras tanto, estas páginas cubren lo que más se pregunta:

| Documento | Para qué sirve |
|-----------|----------------|
| [Rollback](rollback.md) | Recuperar el sistema con los snapshots Btrfs cuando una actualización falla. |
| [Server](server.md) | Qué instala y qué activa la edición servidor, y qué tienes que configurar tú. |
| [Login Greeter](login-greeter.md) | Pantalla de inicio de sesión (greetd + ReGreet): qué sesión arranca cada edición y dónde se configura. |

Para preguntas y ayuda: [issues de GitHub](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues).

## Contribuir

| Documento | Para qué sirve |
|-----------|----------------|
| [Contributing](contributing.md) | Cómo contribuir, con o sin programar: flujo de trabajo, pruebas según el tipo de cambio, licencia de las contribuciones y uso de IA. |
| [Principios](principios.md) | Los principios del proyecto y cómo se decide; todo PR se revisa contra ellos. |
| [Pruebas](testing.md) | Capas de pruebas (`./churros test` y sus opciones), CI, problemas conocidos y autoprueba por mutaciones. |
| [Getting Started](getting-started.md) | Preparar el entorno de desarrollo en Arch u otra distro (con contenedor). |
| [CLI](cli.md) | Referencia de `./churros` (build, run, check, test, rust, apps, doctor, cluster, clean). |
| [VM](vm.md) | Probar la ISO en QEMU/KVM. |

## Referencia técnica

| Documento | Tema |
|-----------|------|
| [Arquitectura](../ARCHITECTURE.md) | Visión general: cómo encajan build, Live, instalación y apps. |
| [Project Structure](project-structure.md) | Mapa de carpetas y ficheros del repositorio. |
| [Build System](build-system.md) | Cómo se construye la ISO: ediciones, arquitecturas, contenedor y paquetes locales. |
| [Boot](boot.md) | Arranque de la ISO (GRUB UEFI y Syslinux BIOS). |
| [Installer](installer.md) | Calamares: configuración, secuencia y pasos propios de post-instalación. |
| [Privileged Execution](privileged-execution.md) | Reglas polkit, `churros-pkexec` y los helpers que se ejecutan como root. |
| [Live Services](live-services.md) | Servicios systemd, usuario y scripts del entorno Live. |
| [Desktop Config](desktop-config.md) | Configuración del escritorio por edición (Niri, Noctalia, XFCE). |
| [Apps](apps.md) | Índice de las apps propias en Rust (gtk4-rs + libadwaita). |
| [Preferences](preferences.md) | App de ajustes `churros-settings`. |
| [Popups](popups.md) | Binario `churros-popup` y sus popups. |
| [Services](services.md) | Crate `churros-services`, la capa común sobre las herramientas del sistema. |
| [ChurrOS Tour](churros-tour.md) | Recorrido guiado de primer inicio y su catálogo de apps. |
| [Branding](branding.md) | Dónde vive cada elemento de identidad visual y cómo llega a la ISO. |

## Proyecto

| Documento | Contenido |
|-----------|-----------|
| [Vision](vision.md) | Qué es ChurrOS y a quién va dirigido. |
| [Principios](principios.md) | Principios ordenados, regla para programas nuevos y proceso de decisión. |
| [Roadmap](roadmap.md) | Estado actual y objetivos pendientes. |
| [Release](release.md) | Cómo se publica una versión y dónde se distribuye. |
| [Licencias](licencias.md) | Licencia del código, componentes de terceros e inventario de arte. |
| [Devlog](devlog.md) | Registro cronológico del desarrollo. |
| [Código de conducta](../CODE_OF_CONDUCT.md) | Normas de convivencia y cómo reportar un incidente. |
| [Seguridad](../SECURITY.md) | Cómo reportar una vulnerabilidad en privado. |
| [MAINTAINERS](../MAINTAINERS) | Quién responde por cada parte del repositorio. |

## Archivo

Documentos que ya no describen el estado actual y se conservan como referencia histórica.

| Documento | Contenido |
|-----------|-----------|
| [Pywal dynamic colors](archivo/pywal-dynamic-colors.md) | Nota de traspaso de la rama `fix/pywal-dynamic-colors` (entró en `main` con la PR #72). |
| [ChurrOS.pptx](ChurrOS.pptx) | Presentación de una charla sobre el proyecto; puede contener datos desactualizados. |

## Cómo mantener esta documentación

- Si un cambio modifica el comportamiento, el mismo PR actualiza el documento que lo describe.
- Un documento nuevo se añade a este índice en la sección que corresponda.
- Lo que deja de ser cierto se corrige o se mueve a `docs/archivo/` con una nota al principio; no se deja desactualizado.
