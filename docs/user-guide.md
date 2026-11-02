# Guía de uso de ChurrOS

Esta guía ayuda a probar, instalar, actualizar y recuperar ChurrOS. Las instrucciones de instalación corresponden al instalador Calamares de las ediciones de escritorio; la edición server tiene limitaciones descritas más abajo.

## Antes de instalar

- Descarga una ISO desde el sitio oficial enlazado en el [README](../README.md). Confirma que el nombre de la edición y la arquitectura coincidan con tu equipo.
- Haz una copia de seguridad de tus documentos. El particionado automático puede borrar el disco o las particiones que selecciones.
- Si vas a verificar la descarga, utiliza únicamente un archivo de sumas publicado junto a esa misma ISO. Genera el SHA-256 local con `sha256sum archivo.iso` en Linux o `Get-FileHash archivo.iso -Algorithm SHA256` en PowerShell y compara el valor completo. **Una suma que se descarga del mismo servidor que la ISO detecta daños accidentales, pero no autentica al publicador si no tiene firma digital verificable.** Consulta el estado de firmas en [Publicaciones](release.md).
- Graba la ISO en una memoria USB con una herramienta de escritura de imágenes. La operación borra el contenido de la memoria; confirma cuidadosamente el dispositivo de destino.

## Probar el sistema Live

1. Arranca el equipo desde la memoria USB. Puede ser necesario elegirla en el menú de arranque del firmware.
2. En el menú de ChurrOS, elige el arranque normal. La opción de accesibilidad está disponible si necesitas lector de pantalla.
3. La sesión Live inicia automáticamente. Los cambios realizados en esta sesión se pierden al apagar.
4. Comprueba que funcionan la pantalla, el teclado, la red, el audio y los dispositivos que necesites antes de instalar.
5. Abre **Install ChurrOS** para iniciar Calamares cuando estés listo.

La disponibilidad de Wi-Fi, Bluetooth, gráficos, suspensión y otros dispositivos depende del hardware; una prueba en una máquina virtual no confirma su funcionamiento en tu equipo.

## Instalar desde Calamares

1. Conecta la alimentación si es un portátil y respalda los archivos importantes.
2. Abre **Install ChurrOS**, selecciona idioma, ubicación y distribución del teclado.
3. Elige el dispositivo y el esquema de particiones con cuidado. Revisa la pantalla de resumen antes de confirmar: las operaciones seleccionadas pueden borrar datos.
4. Crea tu usuario y establece una contraseña segura. La cuenta automática sin contraseña del Live es temporal y se elimina durante la instalación.
5. Espera a que finalice la copia y la configuración. Si aparece un error, conserva el texto o una foto de la pantalla antes de reiniciar.
6. Reinicia cuando Calamares lo indique y retira la memoria USB cuando el equipo empiece a reiniciar.
7. En el sistema instalado inicia sesión con la cuenta creada. El primer inicio no usa el autologin de la sesión Live.

La edición server tiene un escritorio mínimo en el Live para ejecutar el instalador; el sistema instalado es de consola y no ofrece instalación por consola en esta versión. La edición i686 no incluye Calamares. Verifica las ediciones y arquitecturas disponibles en el [README](../README.md#ediciones) antes de descargar.

## Actualizar

- Instala las actualizaciones del sistema desde **Ajustes → Actualizaciones**, o usa `sudo pacman -Syu` en una terminal.
- Revisa la lista de cambios que presenta pacman y no apagues el equipo durante una actualización.
- Flatpak y las utilidades de ChurrOS se gestionan desde la misma pantalla cuando hay una publicación disponible.
- Reinicia si la actualización reemplazó el kernel o si el sistema lo solicita.

No ejecutes `pacman -Sy` de forma aislada: sincronizar las bases sin actualizar los paquetes puede dejar una actualización parcial. No interrumpas una transacción de pacman en curso.

**Seguridad de las actualizaciones:** hasta que ChurrOS publique una clave de confianza y exija validar la firma del manifiesto antes de instalar utilidades, el hash SHA-256 servido por el mismo servidor no protege contra la sustitución coordinada del manifiesto y del archivo. Consulta [Publicaciones](release.md); no interpretes este mecanismo como autenticación criptográfica completa.

## Recuperar el sistema con Btrfs

La instalación predeterminada usa Btrfs y crea snapshots antes de transacciones de pacman. Si una actualización deja el sistema inutilizable:

1. Arranca con una ISO Live de ChurrOS y abre una terminal.
2. Identifica la partición Btrfs con `lsblk -f`. Si el disco usa LUKS, abre primero el volumen cifrado con `cryptsetup` desde el Live.
3. Lista los snapshots desde el nivel superior del volumen:

   ```sh
   sudo mount -o subvolid=5 /dev/LA_PARTICION_BTRFS /mnt
   ls /mnt/@snapshots
   cat /mnt/@snapshots/FECHA-HORA/meta.txt
   sudo umount /mnt
   ```

4. Confirma la fecha y el motivo del snapshot. Restaurar devuelve tanto el sistema como `/home` a ese punto; los datos posteriores permanecen en el subvolumen resguardado `@home.broken-*`.
5. Restaura el snapshot elegido:

   ```sh
   sudo churros-snapshot restore -d /dev/LA_PARTICION_BTRFS FECHA-HORA
   ```

6. Reinicia y comprueba el inicio de sesión. No borres los subvolúmenes `*.broken-*` hasta copiar los archivos que quieras conservar.

Reemplaza los marcadores por la partición y el identificador reales. Si el sistema usa ext4, no hay snapshots Btrfs que restaurar. Los detalles y las opciones de limpieza están en [Rollback](rollback.md).

## Cuando algo falla

- **No arranca desde USB:** vuelve a descargar la ISO, compara su hash si existe uno oficial, recrea la memoria y prueba otro puerto. Revisa el modo UEFI/Legacy admitido por la imagen.
- **Pantalla negra o resolución incorrecta:** prueba la opción de compatibilidad gráfica disponible en el menú y anota GPU, firmware y modo de arranque.
- **Calamares falla:** no repitas una operación de particionado destructiva a ciegas. Guarda el error y la edición, arquitectura y modelo de almacenamiento.
- **No hay red o no funciona un dispositivo:** recoge marca/modelo y el resultado de `lspci -nn` y `lsusb` cuando estén disponibles.
- Busca primero en los [issues de ChurrOS](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues). Para un error nuevo, incluye la edición, arquitectura, pasos para reproducirlo y registros pertinentes. No publiques claves, contraseñas ni datos personales.

## Alcance de esta guía

ChurrOS está en desarrollo y sus ISO y paquetes pueden cambiar con los repositorios rolling de Arch. Las instrucciones describen el estado actual del repositorio; no constituyen una garantía de compatibilidad con todos los equipos ni de recuperación de datos. Antes de una instalación o restauración, mantén una copia externa de los archivos importantes.
