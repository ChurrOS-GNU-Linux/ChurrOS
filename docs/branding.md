# Branding

Mapa técnico de la identidad de ChurrOS: qué elemento sale de qué fichero y
cómo llega a la imagen Live y al sistema instalado. Las reglas visuales
(colores, tipografía, logo, mascota) están en [`branding/README.md`](../branding/README.md)
y en las guías de ese directorio; la licencia y la procedencia de cada recurso gráfico,
en [`docs/licencias.md`](licencias.md).

`branding/`, `installer/calamares/branding/churros/`,
`archiso/airootfs/etc/skel/.config/` y las imágenes del arranque figuran en la
lista «What NOT to Modify» de [`AGENTS.md`](../AGENTS.md): cambiarlas es una
decisión de identidad del proyecto, no un arreglo de paso.

---

## Qué → dónde

| Elemento | Fichero fuente | Live | Sistema instalado |
|---|---|---|---|
| `os-release` | `branding/files/os-release` + `branding/stamp-os-release.sh` | `build.sh` lo copia a `airootfs/root/branding/` y le estampa versión y edición; `customize_airootfs.sh` lo instala en `/etc/os-release` y `/usr/lib/os-release` | Llega con `unpackfs`; `post-install` vuelve a copiar `/etc/os-release` a `/usr/lib/os-release` |
| `/etc/issue` | `branding/files/issue` | `customize_airootfs.sh` | Llega con `unpackfs`, sin cambios |
| `/etc/motd` | `branding/files/motd` | `customize_airootfs.sh` | `post-install` lo sustituye por `ChurrOS instalado correctamente.` |
| Hostname | `archiso/airootfs/etc/hostname` (`churros`) | Tal cual | Lo escribe Calamares con la plantilla `churros-pc` de `installer/calamares/modules/users.conf` |
| Arranque BIOS del Live | `archiso/syslinux/splash.png` (`MENU BACKGROUND` en `archiso_head.cfg`). Hoy es la imagen de archiso, con el logo de Arch Linux | Menú de Syslinux | No aplica: el instalado arranca con GRUB |
| GRUB | `branding/grub-theme/` (`theme.txt`, fondo, fuentes `.pf2`) | El GRUB UEFI del Live (`archiso/grub/grub.cfg`) no carga tema. `build.sh` copia el tema a `/usr/share/churros/grub-theme/` | `shellprocess@grub-theme` lo copia a `/boot/grub/themes/churros/` y añade `GRUB_THEME` a `/etc/default/grub` |
| Plymouth | `archiso/airootfs/usr/share/plymouth/themes/churros/` | Desactivado: `services.sh` enmascara las unidades de Plymouth y el initramfs del Live no lleva el hook | Hook `plymouth` en el initramfs (`initcpiocfg.conf`); `post-install` reescribe `churros.plymouth` y lo activa con `plymouth-set-default-theme -R churros` |
| Pantalla de login (ReGreet) | `archiso/airootfs/etc/greetd/regreet.toml` y `regreet.css` | Tal cual; `build.sh` escribe `config.toml` con inicio automático como `churros` | `configure-greetd-session` reescribe `config.toml`; `configure-greeter-locale` adapta saludo y reloj al idioma. Ver [login-greeter.md](login-greeter.md) |
| Instalador | `installer/calamares/branding/churros/` (`branding.desc`, `stylesheet.qss`, `show.qml`, SVG) | `apply-calamares.sh` lo copia a `/etc/calamares/branding/churros/`; `build.sh` pone el nombre de la edición en `show.qml` | `post-install` borra Calamares y `/etc/calamares` |
| Logo del sistema | `archiso/airootfs/usr/share/pixmaps/churros-logo.{svg,png}` y `usr/share/icons/hicolor/*/apps/` | Tal cual | Llega con `unpackfs` |
| Logos e iconos de las apps | `rust/<crate>/assets/` | `build-rust.sh` los copia a `/usr/share/churros/<binario>/assets/` | Llega con `unpackfs` |
| Wallpapers | `archiso/airootfs/usr/share/churros/wallpapers/` | Tal cual | Llega con `unpackfs`; `post-install` ejecuta `wal` sobre `default.png` |
| Fastfetch | `archiso/airootfs/etc/skel/.config/fastfetch/` (`config.jsonc`, `churros-logo`) | Se copia al home del usuario Live | Se copia al home de cada usuario nuevo |

---

## Notas

- **os-release.** El fichero de git deja `PRETTY_NAME="ChurrOS Rolling"`.
  `stamp-os-release.sh` escribe `VERSION_ID`, `VERSION`, `PRETTY_NAME`,
  `VARIANT` y `VARIANT_ID` a partir de `VERSION` y de la edición (niri, xfce,
  server, pi). `churros-update-utils` usa `VARIANT_ID` cuando falta
  `/etc/churros-edition`. Lo leen fastfetch, `hostnamectl` y el resto de
  herramientas que consultan `/etc/os-release`.
- **issue y motd.** `issue` muestra el banner ASCII, «Welcome to ChurrOS» y
  «Rolling Release • \m»; `motd`, un saludo, el lema y la URL del proyecto.
  `archiso/airootfs/etc/motd` es otro texto que `customize_airootfs.sh`
  sobrescribe al construir: no se ve en ninguna imagen.
- **GRUB.** `scripts/build-grub-theme.sh` (lo llama cada build) genera las
  fuentes `.pf2` que falten (si hay `grub-mkfont`) y, si no hay
  `background.png`, lo copia de `wallpapers/ChurrOSDarkMinimal.png`. Detalle
  en [boot.md](boot.md).
- **Plymouth.** `churros.plymouth` usa `ModuleName=text`, así que se ve el
  tema de texto: `churros.script` y `boot.png` están en el directorio, pero
  ese módulo no los carga. La edición pi no instala Plymouth.
- **Instalador.** Los comentarios de `stylesheet.qss` explican por qué no se
  pinta `QWidget` global (el parche `calamares-partition-labels.patch` elige el
  color de las leyendas de particiones según el fondo) y que la lista de pasos
  del lateral la dibuja un delegate C++ (`sidebar: widget`), así que
  `calamares-sidebar.qml` no se usa. `Presentation` no rellena el panel:
  `show.qml` pone detrás un `Rectangle` `#0F0F10`. No se usa `productWallpaper`
  (Calamares lo repite de fondo y queda ilegible). `./churros check` comprueba
  `componentName`, la API 2 del slideshow y que existan las imágenes; para
  verlo en el host sin ISO: `./churros apps calamares` (usa
  `installer/calamares/preview/`, que no se copia a la ISO).
- **Wallpapers.** `default.png` es el fondo por defecto de Noctalia, XFCE y
  ReGreet. Ajustes ofrece todos los ficheros del directorio, y el bundle de
  utilidades (`scripts/build-churros-release.sh`) copia `usr/share/churros`
  entero, así que cualquier imagen que se añada ahí se distribuye. La
  procedencia de cada fondo está en [licencias.md](licencias.md#wallpapers).
- **Fastfetch.** `usr/share/churros/defaults/fastfetch/` es una copia
  idéntica que usa Ajustes para restaurar los valores por defecto;
  `./churros check` falla si difiere del skel, así que se editan las dos.
- **Terceros.** El cursor (Adwaita) y el tema de iconos del sistema
  (Papirus-Dark) no son propios; propios son solo los iconos de las apps
  `churros-*`.
- **Copias generadas.** `airootfs/root/customize_airootfs.sh`,
  `airootfs/root/branding/` y `airootfs/usr/share/churros/grub-theme/` se
  regeneran en cada build y se borran al terminar: editarlas no sirve.

---

## Decisiones abiertas

- Las guías de `branding/` no coinciden entre sí ni con lo que usa el sistema:
  el fondo es `#111827` en `colors.md`, `#1F1F1F` en `ui-guidelines.md` y
  `#0F0F10` en Calamares; `typography.md` fija Inter y JetBrains Mono («no más
  de dos familias») y `ui-guidelines.md` pide JetBrains Mono, Symbols Nerd Font
  Mono y Noto Sans.
- Plymouth: decidir si se activa el tema gráfico (`churros.script`) o se
  retiran sus ficheros. Además, las unidades de Plymouth que `services.sh`
  enmascara en el Live llegan enmascaradas al sistema instalado, porque ningún
  paso de la instalación las desenmascara; falta comprobar en una VM si el
  splash llega a verse.
- `branding/files/os-release` declara `LOGO=churros`, pero ningún icono tiene
  ese nombre: los del sistema se llaman `churros-logo`.
- El splash BIOS del Live (`archiso/syslinux/splash.png`) es la imagen de
  archiso, con el logo de Arch Linux. Sustituirla es una de las decisiones
  pendientes de [licencias.md](licencias.md#decisiones-pendientes).
