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
- Tags existentes: `v0.1.1`, `v0.4.0`, `v0.6`, `v1.0` (ligero, sin anotar) y `v1.3`. Las versiones 0.7, 1.1 y 1.2 se publicaron sin tag.

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

Abre un pull request. Se fusiona en `main` con la CI en verde (`ci.yml`, `polkit.yml` y `rust.yml`).

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

Un único `SHA256SUMS` cubre todas las ISO de la versión:

```bash
cd release/iso
sha256sum ChurrOS-*.iso > SHA256SUMS
sha256sum -c SHA256SUMS
cd ../..
```

Opcional: firmarlo (`gpg --armor --detach-sign SHA256SUMS` genera `SHA256SUMS.asc`). Falta decidir con qué clave y dónde se publica la clave pública.

### 5. Subir las ISO

- **download.churroslinux.org**: las ISO, `SHA256SUMS` (y su firma) y, tras el paso 6, los `.torrent`.
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
./scripts/build-churros-release.sh x86_64
```

Compila las apps con el cargo del equipo (no usa el contenedor) y deja en `release/x86_64/` `churros-utils-X.Y-x86_64.tar.zst`, dos copias idénticas por edición (`churros-utils-niri-…` y `churros-utils-xfce-…`) y `updates.json`; en x86_64 copia además ese manifiesto a `release/updates.json`. Sube los tres `.tar.zst` y `release/updates.json` a `https://download.churroslinux.org/churros/`.

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

- Solo x86_64: Ajustes y `churros-update-utils` leen siempre `/churros/updates.json`, que es el manifiesto x86_64. Un sistema aarch64 o i686 recibiría binarios x86_64.
- El manifiesto no está firmado: no hay clave minisign publicada y el cliente solo comprueba el sha256 que viene del mismo servidor ([#139](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/139), [#141](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/141)).
- La instalación automática desde el timer de usuario falla porque pkexec pide contraseña ([#142](https://github.com/ChurrOS-GNU-Linux/ChurrOS/issues/142)).

Después de subirlo, comprueba la actualización desde un sistema instalado con la versión anterior.

### 8. GitHub Release

GitHub Releases solo admite ficheros de [menos de 2 GiB](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases), y las ISO actuales los superan (la ISO Niri 1.3 ocupa 2 438 758 400 bytes). El release del tag lleva:

- Notas: cambios, enlaces de descarga (download.churroslinux.org, SourceForge, Internet Archive) y dónde está el código fuente (paso 9).
- `SHA256SUMS` (y su firma) y los `.torrent`.

```bash
gh release create vX.Y --title "ChurrOS X.Y" --notes-file <notas.md> \
    release/iso/SHA256SUMS release/iso/*.torrent
```

### 9. Código fuente (GPL)

La ISO redistribuye programas con licencia GPL, así que las notas del release indican dónde está la fuente correspondiente:

- Código de ChurrOS: el tag `vX.Y` del repositorio (perfil archiso, scripts, apps Rust, configuración de Calamares y los parches de `installer/patches/`).
- Paquetes de Arch Linux sin cambios: [sources.archlinux.org](https://sources.archlinux.org/sources/packages/). Las ISO aarch64 e i686, que hoy no se publican, usan paquetes de Arch Linux ARM y Arch Linux 32: si se publican, las notas tienen que indicar dónde están las fuentes de esos paquetes.
- Paquetes recompilados en local (repositorio `[churros]`: calamares con parches, bazaar, yay, wlogout, python-pywal y, en aarch64, libdex): hay que publicar junto a la ISO el PKGBUILD exacto con el que se compilaron y sus fuentes (`makepkg --allsource` genera un `.src.tar.gz` con ambos). Hoy `build-calamares.sh`, `build-aur.sh` y `build-bazaar.sh` descargan la última versión del AUR o de Arch sin fijar commit y borran su directorio de trabajo al terminar, así que este punto no se puede cumplir sin cambiar esos scripts.

Las licencias de cada componente están en [Licencias](licencias.md).

## Distribución y mirrors

Canales actuales:

| Canal | Contenido | Versiones |
|-------|-----------|-----------|
| [download.churroslinux.org](https://download.churroslinux.org/) | ISO y bundles OTA (`/churros/`) | ISO hasta la 1.3 (Niri y XFCE, x86_64) |
| [SourceForge](https://sourceforge.net/projects/churr-os/files/) | ISO | v0.6, v0.7 y v1.0 |
| Internet Archive | ISO, un item por versión | v0.6, v0.7 y v1.0 |
| BitTorrent | `.torrent` en download.churroslinux.org, con web seeds en Internet Archive y SourceForge | v0.6, v0.7 y v1.0 |
| [GitHub Releases](https://github.com/ChurrOS-GNU-Linux/ChurrOS/releases) | notas; la ISO comprimida en 7z solo en v0.1.1 y v0.6; el bundle OTA en v1.0 | el último es v1.0 |

Problemas:

- download.churroslinux.org está detrás de Cloudflare, pero las ISO no quedan en su caché (las respuestas llevan `cf-cache-status: MISS`; en los planes Free, Pro y Business Cloudflare [no cachea ficheros de más de 512 MB](https://developers.cloudflare.com/cache/concepts/default-cache-behavior/)). Cada descarga sale del servidor de origen, que es además el único sitio con las ISO 1.1 a 1.3.
- Su `sha256sums.txt` solo lista una ISO antigua (`ChurrOS-2026.07.23-x86_64.iso`): las ISO 1.1, 1.2 y 1.3 no tienen suma publicada.
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
