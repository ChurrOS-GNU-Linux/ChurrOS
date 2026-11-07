# Release

Cómo se publica una versión de ChurrOS y por dónde se distribuye. El proceso es manual: no hay un comando `./churros release`.

## Versionado

- `VERSION` guarda la versión de la distro en formato `MAJOR.MINOR` (por ejemplo `1.3`). Cada versión publicada debe llevar un tag anotado `vMAJOR.MINOR`. Los crates de Rust usan `MAJOR.MINOR.0`.
- `VERSION` lo leen `./churros version`, `./churros info`, el build (lo estampa en el `os-release` de la ISO), `scripts/build-churros-release.sh` y las apps Rust al compilar (`churros-services` lo incluye con `include_str!`). La versión también está escrita a mano en otros ficheros, que hay que cambiar en el mismo PR:
  - `rust/Cargo.toml` y el `Cargo.toml` de cada crate (`version = "X.Y.0"`). Después, `cargo update --workspace --manifest-path rust/Cargo.toml` para actualizar `rust/Cargo.lock`: `./churros rust` usa `--locked` y falla si el lock no está al día.
  - `archiso/airootfs/etc/churros-version`.
  - El banner de fastfetch: `archiso/airootfs/etc/skel/.config/fastfetch/config.jsonc` y `archiso/airootfs/usr/share/churros/defaults/fastfetch/config.jsonc`.
  - `installer/calamares/branding/churros/branding.desc` (`version`, `shortVersion`, `versionedName`, `shortVersionedName`).
  - `README.md`: la tabla de ediciones, la sección de descarga y la línea final con la versión del proyecto.

  `etc/skel/.config/` y el branding de Calamares son rutas protegidas en `AGENTS.md`: en un release solo se cambia el número de versión. Antes del commit, `git grep -n '<versión anterior>'` muestra lo que falte (revisa los falsos positivos).
- Tags existentes incluyen `v0.1.1`, `v0.4.0`, `v0.6`, `v1.0` (ligero, sin anotar), `v1.3` y `v1.4`. La release GitHub `v1.4` se publicó el 26 de octubre de 2026 y adjunta `SHA256SUMS`, no las ISO. Las versiones 0.7, 1.1 y 1.2 se publicaron sin tag.

## Checklist

### 1. Preparar el release en una rama

```bash
git fetch origin
git switch -c chore/release-X.Y origin/main
# cambia la versión en los ficheros de la lista anterior
./churros check
./churros rust
git add VERSION rust/ archiso/airootfs/etc/churros-version <resto de ficheros cambiados>
git commit -m "chore(release): versión X.Y"
```

Abre un pull request. Espera los checks requeridos y la revisión humana; actualmente `ci.yml` (incluida la autoprueba por mutaciones), `polkit.yml` y `rust.yml` corren en PR. Los workflows de ISO corren aparte, a diario en `main` o manualmente, no en cada PR.

### 2. Construir y probar cada ISO

Desde `main` actualizado, una vez por cada edición y arquitectura que se publique (hoy, Niri y XFCE en x86_64). Cada `./churros build` vacía `out/`, así que prueba la ISO y muévela antes del siguiente build:

```bash
V=$(tr -d '[:space:]' < VERSION)
mkdir -p release/iso

./churros build --edition niri
./churros run --fresh            # pruebas de la lista siguiente
mv out/ChurrOS-*-x86_64.iso "release/iso/ChurrOS-$V-niri-x86_64.iso"

./churros build --edition xfce
./churros run --fresh
mv out/ChurrOS-*-x86_64.iso "release/iso/ChurrOS-$V-xfce-x86_64.iso"
```

Formato del nombre: `ChurrOS-<versión>-<edición>-<arch>.iso`, con la edición en minúsculas, sin espacios ni comas. `release/` está en `.gitignore`.

En cada ISO comprueba:

- El Live arranca y entra en la sesión de la edición; Welcome, Ajustes y fastfetch muestran la versión nueva.
- Calamares instala en el disco de la VM y el sistema instalado arranca (`./churros run`, sin `--fresh`).
- `vm_serial.log` no tiene errores críticos.

### 3. Crear el tag

```bash
git tag -a vX.Y -m "ChurrOS X.Y" <commit de main>
git push origin vX.Y
```

### 4. Sumas de verificación

Un único `SHA256SUMS` cubre todas las ISO de la versión. La release v1.4 incluye el manifiesto, que también está publicado en el servidor oficial:

```bash
cd release/iso
sha256sum ChurrOS-*.iso > SHA256SUMS
sha256sum -c SHA256SUMS
cd ../..
```

**Estado actual: pendiente.** Las ISO 1.4 tienen un `SHA256SUMS` disponible tanto en el servidor oficial como adjunto a la GitHub Release v1.4. El manifiesto no está firmado y no hay una cadena de confianza publicada: una suma compartida por el mismo publicador no autentica el origen. No se debe anunciar autenticidad verificada hasta completar y probar esa cadena de confianza. Una suma SHA-256 descargada del mismo servidor detecta corrupción accidental, pero no protege contra la sustitución coordinada de ISO y suma. Antes de una publicación estable, custodiar una clave de firma offline o en un servicio de firma aprobado, registrar su huella en un canal independiente, firmar el manifiesto de sumas y verificar la firma desde otra instalación antes de publicar. Nunca añadir una clave privada al repositorio, a la ISO o al CI como texto plano.

### 5. Subir las ISO

- **download.churroslinux.org**: las ISO y `SHA256SUMS`; publicar la firma todavía es un objetivo pendiente. Tras el paso 6, también los `.torrent`.
- **SourceForge** ([churr-os](https://sourceforge.net/projects/churr-os/files/)), en una carpeta por versión. Para ficheros de más de 100 MB SourceForge [recomienda rsync](https://sourceforge.net/p/forge/documentation/Files/), porque permite reanudar la subida:

  ```bash
  rsync -avP -e ssh release/iso/ <usuario>@frs.sourceforge.net:/home/frs/project/churr-os/vX.Y/
  ```

- **Internet Archive**: un item por versión con las ISO y `SHA256SUMS`, por ejemplo con la herramienta `internetarchive`:

  ```bash
  ia upload <identificador> release/iso/ChurrOS-*.iso release/iso/SHA256SUMS \
      --metadata="mediatype:software" --metadata="title:ChurrOS X.Y"
  ```

### 6. Torrent

Un `.torrent` por ISO con web seeds ([BEP 19](https://www.bittorrent.org/beps/bep_0019.html)) que apunten al mismo fichero en Internet Archive y SourceForge, como los de v0.6, v0.7 y v1.0 (creados con qBittorrent). Con `mktorrent`:

```bash
cd release/iso
ISO=ChurrOS-$V-niri-x86_64.iso
mktorrent -a http://tracker.opentrackr.org:1337/announce \
    -w "https://archive.org/download/<identificador>/$ISO,https://downloads.sourceforge.net/project/churr-os/v$V/$ISO" \
    -o "$ISO.torrent" "$ISO"
cd ../..
```

Los web seeds solo funcionan si el fichero subido en el paso 5 se llama igual y es idéntico. Sube los `.torrent` a download.churroslinux.org.

### 7. Bundle OTA

```bash
export CHURROS_RELEASE_SECRET_KEY=/ruta/segura/churros-release.key
./scripts/build-churros-release.sh x86_64
```

La clave privada minisign no se guarda en el repositorio ni en la máquina de build de forma permanente: se conserva cifrada en el gestor de secretos del proyecto y solo se expone durante la publicación. La clave pública fijada en la ISO es `archiso/airootfs/usr/share/churros/churros-release.pubkey`, con identificador `7E53502CD2747C80`. Rotarla exige publicar antes una ISO nueva que confíe en la clave sustituta.

El script aborta si no puede leer la clave o no encuentra `minisign`. Compila para la arquitectura solicitada y deja en `release/<arch>/` los bundles, `updates.json` y `updates.json.minisig`. Sube el contenido completo de ese directorio a `https://download.churroslinux.org/churros/<arch>/`. El cliente selecciona su arquitectura, valida también el campo `arch` y verifica la firma antes de interpretar versión, nombres o hashes; falla cerrado si falta cualquier pieza.

El bundle lleva los binarios Rust con `deploy = true`, los scripts `churros-*` de `/usr/bin` y `/usr/local/bin`, el hook de pacman `50-churros-snapshot.hook`, `/usr/share/churros/` y `/etc/churros-version`. El manifiesto tiene esta forma:

```json
{
  "version": "X.Y",
  "arch": "x86_64",
  "date": "AAAA-MM-DD",
  "file": "churros-utils-X.Y-x86_64.tar.zst",
  "sha256": "<sha256>",
  "editions": {
    "niri": { "file": "churros-utils-niri-X.Y-x86_64.tar.zst", "sha256": "<sha256>" },
    "xfce": { "file": "churros-utils-xfce-X.Y-x86_64.tar.zst", "sha256": "<sha256>" }
  }
}
```

Los sistemas instalados lo ven al buscar actualizaciones en Ajustes; el cliente elige el fichero de su edición y, si no la encuentra, el de `niri`. Limitaciones conocidas:


- La instalación automática desde el timer de usuario falla porque pkexec pide contraseña ([#142](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/142)).

Después de subirlo, comprueba la actualización desde un sistema instalado con la versión anterior.

### 8. GitHub Release

GitHub Releases solo admite ficheros de [menos de 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases). Las ISO 1.4 se distribuyen desde download.churroslinux.org; la release GitHub v1.4 adjunta `SHA256SUMS`, no las ISO. En futuros tags, adjunta el manifiesto y los `.torrent`; publica la imagen en un canal que admita su tamaño.

- Notas: cambios, enlaces de descarga (download.churroslinux.org, SourceForge, Internet Archive) y dónde está el código fuente (paso 9).
- `SHA256SUMS` y los `.torrent`. Adjunta una firma del manifiesto solo cuando la clave pública de confianza esté publicada y los destinatarios puedan verificarla.

```bash
gh release create vX.Y --title "ChurrOS X.Y" --notes-file <notas.md> \
    release/iso/SHA256SUMS release/iso/*.torrent
```

### 9. Código fuente (GPL)

La ISO redistribuye programas con licencia GPL, así que las notas del release indican dónde está la fuente correspondiente:

- Código de ChurrOS: el tag `vX.Y` del repositorio (perfil archiso, scripts, apps Rust, configuración de Calamares y los parches de `installer/patches/`).
- Paquetes de Arch Linux sin cambios: [sources.archlinux.org](https://sources.archlinux.org/sources/packages/). Las ISO aarch64 e i686, que hoy no se publican, usan paquetes de Arch Linux ARM y Arch Linux 32: si se publican, las notas tienen que indicar dónde están las fuentes de esos paquetes.
- Paquetes recompilados en local (repositorio `[churros]`: calamares con parches, bazaar, yay, wlogout, python-pywal y, en aarch64, libdex): publica junto a la ISO el PKGBUILD exacto y sus fuentes (`makepkg --allsource`). Los scripts fijan la revisión remota; actualizarla exige revisar el diff del PKGBUILD y cambiar el commit en el mismo PR.

Las licencias de cada componente están en [Licencias](licencias.md).

## Distribución y mirrors

Canales actuales:

| Canal | Contenido | Versiones |
|-------|-----------|-----------|
| [download.churroslinux.org](https://download.churroslinux.org/) | ISO y bundles OTA (`/churros/`) | ISO 1.4 Niri y XFCE (x86_64), publicada el 25-oct-2026 |
| [SourceForge](https://sourceforge.net/projects/churr-os/files/) | ISO | v0.6, v0.7 y v1.0 |
| Internet Archive | ISO, un item por versión | v0.6, v0.7 y v1.0 |
| BitTorrent | `.torrent` en download.churroslinux.org, con web seeds en Internet Archive y SourceForge | v0.6, v0.7 y v1.0 |
| [GitHub Releases](https://github.com/ChurrOS-GNU-Linux/ChurrOS/releases) | v1.4 incluye `SHA256SUMS` sin ISO; ISO 7z solo en v0.1.1 y v0.6; bundle OTA en v1.0 | última release de distro: v1.4 |

Problemas:

- La ISO 1.4 Niri y XFCE están en el directorio de descargas oficial. El índice publica `SHA256SUMS` para ambas y la GitHub Release v1.4 adjunta el manifiesto, pero las ISO no están adjuntas a GitHub Releases.
- El manifiesto no tiene una firma verificable publicada. Descargar ISO y suma desde un mismo origen no autentica al publicador, aunque permite detectar daños accidentales. Confirma los nombres publicados y no asumas que versiones antiguas tienen la misma cobertura.
- Los nombres publicados no siguen un formato (`…-v1.0.iso`, `…-1.0-xfce.iso`, `…-niri-1.2.iso`, `…-Niri-1.3.iso`, `…-Xfce-1,3.iso`).

Pasos propuestos, en este orden:

1. Repositorio pacman `[churros]` firmado ([#141](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/141)) en lugar de los bundles tarball de `churros-update-utils`. Las actualizaciones pasarían por pacman y cualquier mirror podría servir el repositorio junto con las ISO.
2. Un maestro rsync: un servidor que publique por rsync el árbol de descargas (ISO, `SHA256SUMS`, torrents y repositorio) para que los mirrors se sincronicen desde él.
3. Un redirector de descargas, como [mirrorbits](https://github.com/etix/mirrorbits), que mande cada descarga a un mirror cercano que tenga el fichero al día.
4. Pedir mirror a organizaciones que alojan proyectos libres:
   - [ACC, Umeå](https://mirror.accum.se/about/index.html): piden descripción y licencia del proyecto, un correo de contacto, tamaño y número de ficheros, la URL rsync, la frecuencia de actualización y la URL de la lista de mirrors, y recomiendan usar un redirector.
   - [Clarkson University (COSI)](https://mirror.clarkson.edu/): un issue con la etiqueta "Mirror Request" en su repositorio de GitHub.
   - dotsrc.org: por correo a staff@dotsrc.org.
   - Mirrors de Latinoamérica, contactándolos directamente.
