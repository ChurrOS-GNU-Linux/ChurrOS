# Scripts de desarrollo y construcción — ChurrOS

Este directorio contiene los scripts de compilación, las herramientas auxiliares y los subcomandos de la CLI de desarrollo de ChurrOS ([`./churros`](../churros)). Ninguno forma parte del sistema instalado.

---

## Estructura del directorio

```text
scripts/
├── cli/                         # Subcomandos invocados por el dispatcher ./churros
│   ├── apps.sh                  # Abre las apps en el host (vista previa, sin ISO)
│   ├── apps-dev-stub.sh         # Sustitutos de comandos del sistema para la vista previa
│   ├── build.sh                 # Flujo completo de construcción de la ISO
│   ├── check.sh                 # Comprobaciones estáticas del repo
│   ├── clean.sh                 # Limpieza de work/, out/ y artefactos del airootfs
│   ├── doctor.sh                # Diagnóstico de herramientas requeridas
│   ├── info.sh                  # Información del proyecto y del entorno
│   ├── logo.sh                  # Logotipo en ASCII
│   ├── run.sh                   # Arranque de la ISO en QEMU
│   ├── rust.sh                  # cargo build/test/clippy de rust/ (contenedor o --host)
│   └── version.sh               # Versión
│
├── lib/                         # Funciones compartidas (se cargan con source)
│   ├── container.sh             # Imagen y ejecución del contenedor de build
│   ├── host.sh                  # Distro del host, contenedor, binfmt de aarch64
│   ├── local-repo.sh            # Repositorio local [churros]
│   └── ovmf.sh                  # Elección del firmware UEFI para QEMU
│
├── build-rust.sh                # Compila rust/ y despliega binarios y assets en el airootfs
├── build-calamares.sh           # Compila Calamares desde AUR con installer/patches/
├── build-aur.sh                 # Compila python-pywal, yay y wlogout desde AUR
├── build-bazaar.sh              # Compila la tienda Bazaar (y libdex 1.2 en aarch64)
├── build-grub-theme.sh          # Genera fuentes .pf2 y assets del tema GRUB
├── build-i18n.sh                # Regenera los .mo a partir de po/*.po (manual)
├── build-churros-release.sh     # Bundle OTA y updates.json (manual, al publicar)
│
├── container-entrypoint.sh      # Entrada del contenedor: crea el usuario builder con el UID del host
├── apply-aarch64-mkinitcpio.sh  # Preset de mkinitcpio para el build aarch64 (apply/restore)
├── patch-mkarchiso-grubmodules.sh # Ajusta los módulos GRUB de mkarchiso para arm64-efi
├── host/grub-mkstandalone       # Envoltorio de un build ARM anterior en el host; no lo usa ningún script
│
└── test-*                       # Pruebas (ver más abajo)
```

---

## Scripts de compilación (`scripts/build-*.sh`)

| Script | Propósito | Salida generada |
| :--- | :--- | :--- |
| **`build-rust.sh`** | Compila en release todo el workspace `rust/` y despliega los crates con `deploy = true`. | Binarios en `archiso/airootfs/usr/bin/` y assets en `archiso/airootfs/usr/share/churros/<binario>/assets/` |
| **`build-calamares.sh`** | Compila Calamares desde AUR con los parches de `installer/patches/`. Recompila si cambian los parches o la versión de Python. | `archiso/packages/calamares-*.pkg.tar.*` |
| **`build-aur.sh`** | Compila los extras de AUR que faltan en el repositorio local. | `archiso/packages/{python-pywal,yay,wlogout}-*.pkg.tar.*` |
| **`build-bazaar.sh`** | Compila Bazaar con el PKGBUILD de Arch contra libdex >= 1.2 (en Arch Linux ARM construye y publica libdex 1.2). | `archiso/packages/bazaar-*.pkg.tar.*` |
| **`build-grub-theme.sh`** | Convierte fuentes TTF al formato de GRUB (`.pf2`) si faltan. | `branding/grub-theme/*.pf2` |
| **`build-i18n.sh`** | Compila `po/*.po` con `msgfmt`. `./churros build` no lo ejecuta y hoy ningún componente carga esos catálogos. | `archiso/airootfs/usr/share/locale/*/LC_MESSAGES/churros.mo` |
| **`build-churros-release.sh [arch]`** | Genera el bundle OTA y su manifiesto. Compila para la arquitectura del equipo. | `release/<arch>/churros-utils-<versión>-<arch>.tar.zst` (y una copia por edición), `release/<arch>/updates.json`; en x86_64 también `release/updates.json` |

En la ISO aarch64 los paquetes locales van a `archiso/packages/aarch64/` en lugar de `archiso/packages/`.

---

## Subcomandos de la CLI (`scripts/cli/`)

Cada comando del dispatcher [`./churros`](../churros) se implementa en `scripts/cli/<comando>.sh`:

- **`./churros build`**: construye la ISO con `mkarchiso` (`--edition`, `--arch`, `--container`).
- **`./churros run`**: arranca la ISO en QEMU con firmware UEFI y KVM si está disponible.
- **`./churros check`**: comprobaciones estáticas: scripts bash y Python, listas de paquetes, ficheros `.desktop`, configuración y branding de Calamares, traducciones, reglas polkit y enlaces de la documentación.
- **`./churros rust`**: `cargo build`, `cargo test` y `cargo clippy` del workspace `rust/`, en el contenedor Arch como la CI (`--host` en el equipo).
- **`./churros apps <app>`**: abre las apps en el host en modo de vista previa, sin tocar el sistema; Calamares usa una configuración temporal que no puede instalar.
- **`./churros clean`**: borra `work/`, `out/` y los artefactos generados en `archiso/airootfs/`.
- **`./churros doctor`**: comprueba que las herramientas necesarias (`mkarchiso`, `xorriso`, `mksquashfs`, QEMU, podman o docker…) están instaladas y si `/dev/kvm` está disponible.

---

## Pruebas (`scripts/test-*`)

| Script | Qué prueba |
| :--- | :--- |
| `test-polkit-rules.js` | Cada decisión de la regla polkit `50-churros-store.rules` y que los llamadores usan el argv permitido (Node, lo lanza `./churros check`). |
| `test-privileged-helpers.py` | `churros-update-utils`, `churros-write-root-config` y la tabla edición → sesión, sin root (lo lanza `./churros check`). |
| `test-polkit-pkexec.sh` | La regla contra polkitd y pkexec reales. Necesita root: solo en la CI (`polkit.yml`). |
| `test-network-services.py`, `test-apply-wallpaper.sh` | Qué servicio gestiona la red en el Live y en el sistema instalado, y que `churros-apply-wallpaper` no arranca swaybg con Noctalia en marcha (los lanza `./churros check`). |
| `test-tour.py` | Widgets e instalación del Tour con GTK Broadway, un HOME temporal y un yay falso. Se ejecuta a mano. |

---

## Documentación relacionada

- [Manual de la CLI de ChurrOS](../docs/cli.md)
- [Sistema de compilación](../docs/build-system.md)
- [Cómo contribuir](../docs/contributing.md)
