# Memoria y zram

ChurrOS usa `zram-generator` para tener swap comprimido en RAM. Da margen cuando la memoria se llena, pero por sí solo no reduce la memoria residente del escritorio. Todas las ediciones incluyen el paquete `zram-generator` junto a la configuración común `archiso/airootfs/etc/systemd/zram-generator.conf`.

## Ajustes para equipos de 2 GiB

2 GiB es el mínimo que ChurrOS promete. La CI arranca cada edición con esa memoria (ver más abajo). Estos ajustes van en todas las ediciones:

- **systemd-oomd** (`services.sh` lo habilita). Si la sesión del usuario pasa más del 50 % del tiempo esperando memoria durante 20 s, systemd-oomd cierra el cgroup que más presiona (`user@.service.d/10-churros-oomd.conf`). Si el swap (zram) supera el 90 %, cierra el que más swap usa (`-.slice.d/10-churros-oomd.conf`). Sin esto, una app que agota la memoria congela el equipo entero. Son los valores por defecto de Fedora.
- **MGLRU `min_ttl_ms=1000`** (`tmpfiles.d/churros-mglru.conf`). El kernel no expulsa páginas usadas en el último segundo, así que el escritorio no se queda atascado paginando el código en uso (thrashing).
- **Preset `10-churros.preset`**. La Live arranca con la machine-id vacía y systemd aplica los presets de Arch, que habilitan `systemd-networkd` y `systemd-homed`. ChurrOS usa NetworkManager y no tiene usuarios de homed, así que el preset los deja desactivados.
- **Niri sin Xwayland en reposo**. `churros-portal-start` ejecuta `xdg-mime` sin `DISPLAY`. Como xdg-utils no conoce `XDG_CURRENT_DESKTOP=niri`, lanzaba `xprop -root` para adivinar el escritorio, y ese cliente X bastaba para que niri arrancara Xwayland, que se quedaba vivo toda la sesión (unos 37 MiB).
- **Sin applet de cola de impresión en XFCE** (`skel/.config/autostart/print-applet.desktop`, `Hidden=true`). La herramienta de impresoras sigue en el menú.
- **Disco del sistema instalado**. Calamares se instala con bsdtar, fuera de pacman. `shellprocess-cleanup.conf` quita sus bibliotecas Qt/KDE con `pacman -Rnsu` (en XFCE, unos 260 MiB). Se conserva lo que otro paquete necesita, además de `os-prober`, `zenity` y `udisks2`.

## Revisar una sesión Live o una instalación

Después de iniciar sesión, ejecuta:

```sh
free -h
swapon --show
zramctl
ps -eo pid,comm,rss --sort=-rss | head -20
systemd-cgtop --batch --iterations=1 --depth=3
```

`MemAvailable` es más útil que sumar la memoria libre y las cachés. RSS es la memoria residente de cada proceso y puede contar más de una vez las páginas compartidas, así que su suma no es el uso físico exclusivo. Las columnas `DATA`, `COMPR` y `TOTAL` de `zramctl` ayudan a distinguir los datos comprimidos de la memoria física que ocupan.

## Perfil repetible en QEMU

`tests/vm/boot_smoke.py` arranca la ISO con 4096 MiB por defecto, espera al sistema y a la sesión Live y guarda en `report.json` `/proc/meminfo`, el swap activo, las estadísticas de zram y los 20 procesos con más RSS. El informe incluye la edición y la memoria de la VM. La prueba de humo también comprueba que `/dev/zram0` está activo.

El informe guarda dos fotos. `memory_profile` se toma tras el inicio de sesión, con la bienvenida abierta. `memory_profile_idle` se toma al final, después de cerrar las ventanas de ChurrOS (bienvenida, Ajustes, centro de control, recorrido): es el escritorio en reposo. Cada foto trae, además del RSS, `top_pss_processes`: el PSS de los 40 procesos más grandes con su línea de comandos. PSS reparte las páginas compartidas entre quienes las usan, así que su suma se acerca a la memoria física y dice cuánto se libera al cerrar un proceso. `x11_clients` lista los procesos conectados al socket de X; en una sesión niri en reposo debería estar vacío.

`.github/workflows/iso.yml` arranca cada edición también con 2048 MiB (`boot-uefi-2g`), el mínimo que se promete. Esa ejecución tiene que llegar al escritorio igual que la de 4096 MiB.

Para probar otra capacidad, pasa `--memory MIB`, por ejemplo `--memory 2048`. Compara Niri y XFCE con la misma arquitectura, la misma ISO o base, la misma memoria de la VM, el mismo firmware, la misma aceleración de QEMU y el mismo estado tras el inicio de sesión. Mantén aparte el perfil `server`, que no tiene escritorio. Los workflows de ISO suben los informes de arranque como artefactos; las pruebas estáticas por sí solas no producen mediciones.

Los perfiles de QEMU sirven para comparar dentro del mismo entorno virtual; no predicen el uso exacto en hardware físico ni justifican quitar servicios. No desactives el compositor, el portal, Polkit, el gestor de sesión, la red ni las apps de inicio por su nombre: toma datos de antes y después y prueba primero las funciones relacionadas. El issue #288 recoge las posibles optimizaciones del escritorio que necesitan una comparación real.

## Referencia inicial

Primera medición en la CI (2026-11-01, commit `608670d`), con KVM/virgl y 4096 MiB, arranques UEFI y BIOS de Niri y XFCE. En UEFI, Niri dio unos 3122 MiB de `MemAvailable` y 218 MiB de `AnonPages`; XFCE, unos 2989 MiB y 335 MiB. En las dos, `/dev/zram0` estaba activo y sin swap usado, y BIOS dio cifras parecidas. Las dos se tomaron en el mismo punto, tras el inicio de sesión de la prueba de humo (en Niri, con la ventana de bienvenida abierta).

Son fotos orientativas, no un benchmark controlado: las ISO se construyen con repositorios rolling y QEMU no predice el hardware físico. `AnonPages` es una categoría de memoria de todo el sistema, no la suma del RSS de los procesos. Con una sola comparación no se quitó ningún servicio ni función.
