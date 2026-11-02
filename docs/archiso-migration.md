# Migración del hook de personalización de ArchISO

## Estado

El perfil actual depende de `branding/customize_airootfs.sh`. La versión upstream de `mkarchiso` consultada el 2 de noviembre de 2026 aún ejecuta `/root/customize_airootfs.sh`, pero emite explícitamente el aviso de obsolescencia y dice que se retirará en una futura versión. Por tanto, la ISO puede seguir construyéndose ahora, pero este mecanismo es una deuda de compatibilidad: el siguiente cambio de ArchISO podría eliminarlo.

No se migra el hook en este cambio porque su reemplazo debe probarse contra la versión real de ArchISO y contra el ciclo completo de `pacstrap`, configuración de rootfs y arranque de la ISO. Un reemplazo basado en intuición podría producir una ISO que compila pero no crea el usuario Live ni configura los servicios.

## Inventario del comportamiento actual

Durante la construcción del chroot de la ISO, `branding/customize_airootfs.sh` aplica branding y tema GRUB, invoca `users.sh`, `services.sh` y `desktop.sh`, activa multilib, instala Calamares desde el repo local, modifica la detección de greetd en Calamares y adapta mkinitcpio para kernels específicos. La documentación mantenida por separado está en [servicios del Live](live-services.md), [sistema de build](build-system.md), [instalador](installer.md) y [arranque](boot.md).

Antes de cambiar el mecanismo, mantener una tabla de cada efecto, su momento requerido (build o primer arranque), sus rutas de entrada/salida, arquitecturas afectadas y su prueba existente. En especial, no desplazar accidentalmente a primer arranque el branding, las cuentas, la configuración de greetd ni la regeneración del initramfs.

## Plan de migración

1. Identificar y fijar el commit/versión de ArchISO que se usa en cada Containerfile y CI. Registrar la versión actual y la primera versión que ya no acepta `customize_airootfs.sh`; no depender de `latest` para afirmar compatibilidad futura.
2. Leer la interfaz upstream soportada para personalizar el airootfs durante la construcción y confirmar en la fuente de esa versión cuándo se invoca, en qué namespace/chroot y con qué variables/montajes. Preferir una interfaz existente de ArchISO a mantener un fork.
3. Clasificar cada operación del script actual como: configuración de perfil previa a pacstrap; overlay de archivos declarativo; hook de personalización soportado por upstream; acción de primer arranque; o paso específico de arquitectura. Conservar el orden donde una etapa depende de otra.
4. Migrar una operación cada vez y añadir un test contractual que verifique que no se llama al hook obsoleto y que cada operación crítica sigue conectada. No quitar pruebas anteriores hasta tener reemplazo equivalente.
5. Construir las ISOs x86_64 Niri, XFCE y Server; auditar su contenido y arrancarlas en UEFI/BIOS según corresponda. Construir y auditar Niri/Pi aarch64 en el runner nativo, validando kernel, initramfs y consola serie. Comparar usuario Live, servicios, archivos de greetd, escritorio e instalador con informes antes/después.
6. Ejecutar la instalación completa y comprobar el primer arranque instalado antes de declarar cubiertas las operaciones de Calamares. Ver [pruebas de instalación](testing.md#instalación-completa-en-qemu).
7. Solo retirar la ruta antigua cuando todas las ediciones y arquitecturas cubiertas tengan evidencia de build y runtime, CI verde y documentación actualizada.

## Criterio de finalización

La migración termina cuando no queda ninguna referencia ejecutable al mecanismo obsoleto, la CI detecta su reintroducción, las ISOs soportadas superan build/auditoría/arranque, las instalaciones soportadas completan y el diff documenta la versión de ArchISO probada. Una advertencia eliminada o un `mkarchiso` exitoso por sí solos no son prueba suficiente.
