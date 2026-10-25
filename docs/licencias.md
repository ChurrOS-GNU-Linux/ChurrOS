# Licencias

Este documento recoge la licencia del código de ChurrOS, los componentes de terceros que el repositorio y la ISO redistribuyen, y la procedencia conocida del arte. Inventario revisado el 22 de octubre de 2026.

Si añades un recurso que no es código (wallpaper, icono, logo, fuente, sonido), sigue [Licencia de las contribuciones](contributing.md#licencia-de-las-contribuciones) y añádelo a la tabla que le corresponda.

## Código

| Qué | Licencia | Dónde consta |
|---|---|---|
| Código propio: scripts, apps Rust, perfil archiso, configuración de Calamares | GPL-3.0-only | [`LICENSE`](../LICENSE) (texto de la GPL v3) y `license` en `[workspace.package]` de `rust/Cargo.toml` |
| Ficheros heredados del perfil `releng` de archiso (lista abajo) | GPL-3.0-or-later | Licencia del proyecto archiso. Solo tres scripts conservan la cabecera `SPDX-License-Identifier` |
| Parches de Calamares (`installer/patches/calamares-*.patch`) | GPL-3.0-or-later | Son modificaciones de Calamares (escritas contra la versión 3.4.2), que tiene esa licencia |

Las dos variantes son compatibles: el conjunto se distribuye bajo la GPL-3.0.

### Ficheros heredados de archiso

Comparados con `configs/releng` de la rama `master` de [archiso](https://gitlab.archlinux.org/archlinux/archiso).

| Estado | Ficheros |
|---|---|
| Copia sin cambios (28) | `archiso/airootfs/usr/local/bin/{choose-mirror,livecd-sound,Installation_guide}` (los tres con cabecera SPDX), `archiso/airootfs/usr/local/share/livecd-sound/asound.conf.in`, `archiso/airootfs/etc/systemd/system/{choose-mirror,livecd-alsa-unmuter,livecd-talk,pacman-init}.service`, `archiso/airootfs/etc/systemd/system/etc-pacman.d-gnupg.mount`, `archiso/airootfs/etc/systemd/{journald,logind,resolved}.conf.d/*.conf`, `archiso/airootfs/etc/ssh/sshd_config.d/10-archiso.conf`, `archiso/airootfs/etc/pacman.d/hooks/{uncomment-mirrors,zzzz99-remove-custom-hooks-from-airootfs}.hook`, `archiso/airootfs/etc/{locale.conf,passwd,shadow}`, `archiso/airootfs/root/.automated_script.sh`, `archiso/airootfs/root/.gnupg/scdaemon.conf`, `archiso/syslinux/{syslinux,archiso_sys,archiso_pxe,archiso_tail}.cfg`, `archiso/syslinux/splash.png`, `archiso/efiboot/loader/loader.conf`, `archiso/efiboot/loader/entries/03-archiso-memtest86+x64.conf`, `archiso/bootstrap_packages` |
| Modificados por ChurrOS (14) | `archiso/profiledef.sh`, `archiso/packages.{x86_64,aarch64}`, `archiso/grub/{grub,loopback}.cfg`, `archiso/syslinux/{archiso_head,archiso_sys-linux,archiso_pxe-linux}.cfg`, `archiso/efiboot/loader/entries/{01-archiso-linux,02-archiso-speech-linux}.conf`, `archiso/airootfs/etc/{hostname,motd}`, `archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf`, `archiso/airootfs/root/.zlogin` |

`archiso/syslinux/splash.png` es la imagen original de archiso y lleva el logo de Arch Linux.

## Componentes de terceros en el repositorio

[`LICENSES/`](../LICENSES) guarda copias exactas del fichero `LICENSE` de Feather, Lucide y DejaVu.

| Componente | Ficheros | Licencia | Texto |
|---|---|---|---|
| [Feather](https://github.com/feathericons/feather), de Cole Bemis | 13 iconos de `rust/preferences/assets/icons/` (tabla siguiente) | MIT | [`LICENSES/MIT-Feather.txt`](../LICENSES/MIT-Feather.txt) |
| [Lucide](https://github.com/lucide-icons/lucide) | `rust/preferences/assets/icons/appearance.svg` | ISC | [`LICENSES/ISC-Lucide.txt`](../LICENSES/ISC-Lucide.txt) |
| DejaVu Sans, convertida a fuente bitmap de GRUB | `branding/grub-theme/{dejavu-16,dejavu-bold-16,dejavu-bold-22}.pf2` | Bitstream Vera (los cambios de DejaVu son de dominio público) | [`LICENSES/Bitstream-Vera-DejaVu.txt`](../LICENSES/Bitstream-Vera-DejaVu.txt) |
| [Contributor Covenant](https://www.contributor-covenant.org) 2.1, traducido | [`CODE_OF_CONDUCT.md`](../CODE_OF_CONDUCT.md) | [CC-BY-4.0](https://creativecommons.org/licenses/by/4.0/deed.es) | Atribución al final del propio fichero |

### Iconos de Feather y Lucide

Comparados con `feather-icons` 4.29.2 y con `lucide-static` 0.100.0 y 0.300.0. `scripts/build-rust.sh` los copia a la ISO en `/usr/share/churros/churros-settings/assets/icons/`.

| Fichero | Icono original | Coincidencia |
|---|---|---|
| `about.svg` | Feather `info` | Idéntico |
| `applications.svg` | Feather `grid` | Idéntico |
| `connectivity.svg` | Feather `wifi` | Idéntico |
| `display.svg` | Feather `monitor` | Idéntico |
| `night_light.svg` | Feather `moon` | Idéntico |
| `power.svg` | Feather `power` | Idéntico |
| `privacy.svg` | Feather `shield` | Idéntico |
| `system.svg` | Feather `settings` | Idéntico |
| `users.svg` | Feather `users` | Idéntico |
| `audio.svg` | Feather `volume-2` | Mismo dibujo, con el trazo partido en dos |
| `mako.svg` | Feather `bell` | Mismo dibujo, escrito con coordenadas relativas |
| `backup.svg` | Feather `database` | Mismo dibujo, con un trazo en sentido inverso |
| `lock_screen.svg` | Feather `lock` | Derivado: añade el ojo de la cerradura |
| `appearance.svg` | Lucide `palette` | Derivado: los cuatro círculos son idénticos y el contorno se parece, pero no coincide |

`input.svg` tiene el mismo marco que el icono `keyboard` de Lucide, pero otras teclas; no coincide con ninguna versión comparada. El resto de iconos de `rust/preferences`, los de `rust/control-center` y los de `rust/churros-welcome` y `rust/churros-tour` no coinciden con Feather ni con Lucide y figuran en el [inventario de arte](#inventario-de-arte).

### Fuentes del tema de GRUB

`scripts/build-grub-theme.sh` genera los `.pf2` con `grub-mkfont` a partir de `DejaVuSans.ttf` y `DejaVuSans-Bold.ttf` (paquete `ttf-dejavu`). El Live los lleva en `/usr/share/churros/grub-theme/` y Calamares los copia a `/boot/grub/themes/churros/` del sistema instalado. La licencia de Bitstream Vera pide acompañar cada copia con su aviso de copyright y de licencia, y solo permite distribuir versiones modificadas con un nombre que no contenga «Bitstream» ni «Vera». El nombre interno de los `.pf2` es «DejaVu Sans», así que cumple esa condición.

## Componentes de terceros en la ISO

### Crates de Rust

Los binarios `/usr/bin/churros-*` enlazan de forma estática los 88 crates de crates.io que fija `rust/Cargo.lock`. Todas sus licencias son permisivas y compatibles con la GPL-3.0:

| Licencia (campo `license` de crates.io) | Crates |
|---|---|
| MIT OR Apache-2.0 | 46 |
| MIT | 29 |
| Apache-2.0 OR MIT | 4 |
| MIT/Apache-2.0 | 3 |
| Apache-2.0 WITH LLVM-exception OR Apache-2.0 OR MIT | 2 |
| Unlicense OR MIT | 1 |
| MIT OR Apache-2.0 OR LGPL-2.1-or-later | 1 |
| Apache-2.0 WITH LLVM-exception | 1 |
| (MIT OR Apache-2.0) AND Unicode-3.0 | 1 |

Las licencias MIT y Apache-2.0 piden distribuir su aviso de copyright y de licencia junto con el binario. Hoy la ISO no lo incluye.

### Paquetes recompilados en local

Los compilan `scripts/build-calamares.sh`, `scripts/build-aur.sh` y `scripts/build-bazaar.sh`, que los publican en el repositorio local `[churros]` (`archiso/packages/`). Qué paquetes entran en la ISO depende de la arquitectura y de la edición.

| Paquete | Origen | Licencia | Cambios de ChurrOS |
|---|---|---|---|
| `calamares` | AUR, última versión (`build-calamares.sh`) | GPL-3.0-or-later | Aplica `installer/patches/*.patch` y reescribe el PKGBUILD |
| `yay` | AUR, última versión (`build-aur.sh`) | GPL-3.0-or-later | Ninguno; si se compila en un equipo aarch64, añade esa arquitectura a `arch=()` |
| `wlogout` | AUR, última versión (`build-aur.sh`) | MIT | Igual que `yay` |
| `python-pywal` | AUR, última versión (`build-aur.sh`); el paquete no tiene mantenedor en el AUR | MIT | Igual que `yay` |
| `bazaar` | PKGBUILD de Arch, rama `main` (`build-bazaar.sh`) | GPL-3.0-or-later | Exige `libdex>=1.2.0` en las dependencias |
| `libdex` | PKGBUILD de Arch, rama `main` (`build-bazaar.sh`), solo si los repositorios traen una versión anterior a la 1.2 (hoy, en aarch64) | LGPL-2.1-or-later | Sin documentación y, si el repositorio no trae `libsysprof-capture`, sin soporte de sysprof |

Qué hay que publicar de su código fuente: [Release, paso 9](release.md#9-código-fuente-gpl).

### Paquetes de Arch Linux

El resto de programas, fuentes y temas de la ISO (`inter-font`, `ttf-jetbrains-mono`, `papirus-icon-theme`, el kernel…) son paquetes de los repositorios de Arch Linux, Arch Linux ARM o Arch Linux 32 sin cambios. Los textos de sus licencias quedan en `/usr/share/licenses/`: el paquete `licenses` (dependencia de `base`) trae las licencias comunes y cada paquete con una licencia propia instala la suya.

## Inventario de arte

Ninguno de estos recursos tiene una licencia declarada. «Sin metadatos» quiere decir que el PNG no guarda ningún dato de autor ni de herramienta.

### Wallpapers

Todos están en `archiso/airootfs/usr/share/churros/wallpapers/`. Ajustes los ofrece todos, porque lista ese directorio, y `scripts/build-churros-release.sh` los incluye en el bundle OTA.

| Fichero | Qué muestra | Procedencia conocida | Entró en |
|---|---|---|---|
| `default.png` | La mascota con un churro. Es el fondo por defecto del greeter y de Noctalia | Sin metadatos | 9b99170 (2026-07-18), sustituido en e55b560 |
| `fondo1.png` | La mascota y el logotipo | Manifiesto C2PA de OpenAI (`gpt-image`, `trainedAlgorithmicMedia`): imagen generada con IA | c1afd30 (2026-07-31) |
| `fondo2.png` | La mascota y el nombre «CHURROS» en letras grandes | Sin metadatos | fb68a4f (2026-08-02) |
| `TuxChurro.png` | La mascota abrazando a un pingüino con el aspecto de Tux | Diseño de Canva (metadatos XMP); autor indicado en los metadatos, sin identificar en el historial | e0de019 (2026-08-13) |
| `EmperadorChurrOS.png` | La mascota como emperador | Diseño de Canva; autor indicado en los metadatos, sin identificar en el historial | e0de019 (2026-08-13) |
| `ImperioChurrOS.png` | El logo en un estandarte, con cañones | Diseño de Canva; autor indicado en los metadatos, sin identificar en el historial | e0de019 (2026-08-13) |
| `ChurrOSPowerON.png` | El logo sobre fondo negro | Diseño de Canva con un manifiesto C2PA que declara contenido generado con IA («Canva AI», `compositeWithTrainedAlgorithmicMedia`); autor indicado en los metadatos, sin identificar en el historial | 9b7a40d (2026-08-09) |
| `ChurrOS-Mountains.png`, `ChurrOSDarkMinimal.png`, `ChurrOSLightMinimal.png`, `ChurrOSGT5.png`, `ChurrOSGT6.png` | El logo | Sin metadatos | 9b7a40d (2026-08-09) |
| `ChurrOSGT7.png` | El logo | Sin metadatos | e0de019 (2026-08-13) |
| `wallpaper_churrOS01v4.png`, `wallpaper_churrOS01_altv4.png` | Una variante del logotipo con el lema «slim.smart.sophisticated», que no recoge `branding/logo-guidelines.md` | Inkscape (metadatos PNG) | 9b7a40d (2026-08-09) |

Tux lo dibujó Larry Ewing con The GIMP; su permiso de uso pide que se le reconozca a él y a The GIMP si alguien lo pregunta.

### Mascota, Plymouth y GRUB

| Fichero | Qué es | Procedencia conocida | Entró en |
|---|---|---|---|
| `rust/churros-tour/assets/churr.png` (copia en `archiso/airootfs/usr/share/churros/churros-tour/assets/`) | La mascota, Churr, en la portada del recorrido | Sin metadatos | 3e0200b y 294d835 (2026-09-29) |
| `archiso/airootfs/usr/share/plymouth/themes/churros/boot.png` | La mascota y el nombre ChurrOS, con el símbolo del logo como «O» y un rayo como «S» | Sin metadatos. `churros.plymouth` usa `ModuleName=text`, así que hoy no se muestra | a661d7b (2026-07-25) |
| `branding/grub-theme/background.png` | Fondo del menú de GRUB | Copia exacta de `ChurrOSDarkMinimal.png` | f2f1c10 (2026-08-13) |
| `branding/grub-theme/{select,select_c}.png` | Barra de selección del menú de GRUB | Sin metadatos de autor | `select.png` en f2f1c10 (2026-08-13), `select_c.png` en d0dd48a (2026-08-23); los dos cambian en cf3168e (2026-08-25) |

[`branding/mascot.md`](../branding/mascot.md) dice que la mascota oficial está en desarrollo. No consta quién dibujó a Churr ni con qué herramienta. La única imagen de la mascota con datos de procedencia es `fondo1.png`, generada con IA.

### Logos e iconos propios

Ninguno coincide con Feather ni con Lucide, y ninguno lleva metadatos o texto de terceros.

| Ficheros | Qué son | Entró en |
|---|---|---|
| `installer/calamares/branding/churros/{logo,welcome,combo-arrow}.svg` | Logo y gráficos del instalador | 93991ec (2026-08-20) |
| `rust/*/assets/logo.svg`, `rust/*/assets/icons/logo.svg` | Logo de ChurrOS en las apps | a691eec y 96fb30a (2026-08-13); la copia del recorrido, en d6b9dab (2026-09-28) |
| `archiso/airootfs/usr/share/icons/hicolor/{scalable,128x128}/apps/churros-*`, `archiso/airootfs/usr/share/pixmaps/churros-*` | Iconos de aplicación | ba2c0d3 (2026-07-29) y e55b560 (2026-08-29) |
| `rust/control-center/assets/icons/*.svg` (copia en `archiso/airootfs/usr/share/churros/control-center/`) | Iconos del centro de control | 96fb30a (2026-08-13) |
| `rust/preferences/assets/icons/{cursor,font,icons,input,logs,niri,palette,terminal,wallpaper,waybar,window_rules}.svg` | Iconos de Ajustes; varios llevan comentarios en español | a691eec (2026-08-13) |
| `rust/{churros-welcome,churros-tour}/assets/icons/{community,github,install}.svg` | Iconos de la bienvenida y del recorrido. `github.svg` es un globo, no el logo de GitHub | a691eec (2026-08-13); las copias del recorrido, en d6b9dab (2026-09-28) |
| `archiso/airootfs/etc/skel/.config/fastfetch/churros-logo` (copia en `archiso/airootfs/usr/share/churros/defaults/fastfetch/`) | Logo en arte ASCII (braille) para fastfetch | a661d7b (2026-07-25) |
