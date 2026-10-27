# Rollback

ChurrOS incluye un sistema de rollback basado en **snapshots btrfs**: antes de
cada transacción de pacman se guarda una copia del sistema que permite volver
atrás si una actualización rompe algo.

## Cómo funciona

La instalación por defecto usa btrfs con subvolúmenes:

| Mount | Subvolumen |
|-------|------------|
| `/`     | `@`    |
| `/home` | `@home` |
| swap (si se eligió swap en fichero) | `@swap` (no entra en los snapshots) |

Los snapshots se guardan en un subvolumen contenedor `@snapshots` (creado en el
nivel superior, id=5) aislado de `@`, de modo que un snapshot nunca contiene
snapshots anidados.

- Un **hook de pacman** (`/etc/pacman.d/hooks/50-churros-snapshot.hook`,
  `PreTransaction`) crea un snapshot de `@` y `@home` **antes** de cualquier
  transacción de pacman que instale, actualice o quite paquetes (también las
  que lanza `yay`). Si el snapshot falla (p. ej. el sistema no es btrfs), la
  transacción continúa igual.
- Con el particionado por defecto (la ESP se monta en `/boot/efi`), `/boot`
  está dentro de `@`: restaurar también devuelve el kernel y el initramfs del
  snapshot. Esos ficheros siguen sin compresión (`/boot` tiene
  `+C`), así que GRUB los puede leer. No hay entradas de GRUB para arrancar un
  snapshot directamente: se restaura desde la ISO.
- Se conservan los **5** snapshots más recientes, **incluidos los manuales**:
  cada snapshot nuevo borra los que sobran, así que tras 5 transacciones un
  snapshot manual desaparece.

## Comandos

La herramienta `churros-snapshot` (root) gestiona todo:

```bash
sudo churros-snapshot create [RAZON]      # snapshot manual
sudo churros-snapshot list --plain        # lista (tabla)
sudo churros-snapshot list --json         # salida JSON (la usa Ajustes; sin opción, igual)
sudo churros-snapshot info <stamp>        # metadatos de un snapshot
sudo churros-snapshot delete <stamp>      # elimina un snapshot
sudo churros-snapshot cleanup [KEEP]      # borra los más antiguos hasta dejar KEEP
sudo churros-snapshot restore -d <partición> <stamp>   # restaura desde la ISO live
```

El `stamp` es la fecha y hora del snapshot (`20260824-163000`). `list`, `info`,
`delete` y `cleanup` solo funcionan en el sistema instalado (necesitan que `/`
sea btrfs); desde la ISO se usa el procedimiento de abajo.

## Restaurar

El subvolumen raíz está montado en uso, así que **no se puede restaurar desde
el sistema en marcha**. Para volver a un snapshot:

1. Arranca la ISO live de ChurrOS y abre una terminal.
2. Busca la **partición** btrfs del sistema instalado: es la que `lsblk -f`
   muestra con `FSTYPE` `btrfs`, por ejemplo `/dev/sda2` o `/dev/nvme0n1p2`.
   Tiene que ser la partición, no el disco entero (`/dev/sda`): con el disco
   el montaje falla. Si cifraste el disco al instalar, la partición aparece como
   `crypto_LUKS`; ábrela antes con `sudo cryptsetup open /dev/sdXN churros` y
   usa `/dev/mapper/churros` en los pasos siguientes.
3. Mira qué snapshots hay (en el Live `churros-snapshot list` no funciona):
   ```bash
   sudo mount -o subvolid=5 /dev/sdXN /mnt
   ls /mnt/@snapshots                        # cada carpeta es un stamp
   cat /mnt/@snapshots/<stamp>/meta.txt      # fecha y motivo de ese snapshot
   sudo umount /mnt
   ```
   Los snapshots con motivo `pacman-pre` son los del hook, tomados justo antes
   de una transacción.
4. Restaura:
   ```bash
   sudo churros-snapshot restore -d /dev/sdXN <stamp>
   ```
5. Reinicia: el sistema quedará en el estado del snapshot. El estado anterior
   queda resguardado como `@broken-<fecha>` (y `@home.broken-<fecha>`) por si
   hay que recuperar algo; se puede borrar después.

**Ojo:** restaurar también devuelve `/home` al momento del snapshot. Lo que
guardaste después no se pierde, pero ya no está en `/home`: sigue en
`@home.broken-<fecha>`. Cópialo antes de borrar ese subvolumen.

## Interfaz

`churros-settings` → **Actualizaciones** incluye la sección **Rollback
(snapshots btrfs)** que lista los snapshots, permite crearlos y eliminarlos, y
muestra un resumen de cómo restaurar.

## Consideraciones

- Solo aplica a instalaciones **btrfs** (la opción por defecto). En ext4 no hay
  snapshots: cada transacción de pacman muestra un aviso de `churros-snapshot`
  y sigue adelante.
- Los snapshots consumen espacio: con los 5 conservados y `compress=zstd:1` el
  costo típico es bajo, pero conviene revisar `sudo churros-snapshot cleanup`
  si el disco está justo.
