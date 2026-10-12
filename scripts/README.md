# Scripts de Desarrollo y Construcción — ChurrOS

Este directorio contiene todos los scripts de compilación, herramientas auxiliares y subcomandos de la CLI oficial de desarrollo de ChurrOS ([`./churros`](../churros)).

---

## 📁 Estructura del Directorio

```text
scripts/
├── cli/                       # Subcomandos invocados por el dispatcher ./churros
│   ├── apps.sh                # Lanzador de vista previa de apps en el host
│   ├── apps-dev-stub.sh       # Entorno de pruebas y aislamiento de llamadas
│   ├── build.sh               # Flujo completo de construcción de la ISO
│   ├── check.sh               # Suite de comprobaciones estáticas del repo
│   ├── clean.sh               # Limpieza de work/ y out/
│   ├── doctor.sh              # Diagnóstico de herramientas requeridas
│   ├── info.sh                # Información del proyecto y entorno
│   ├── logo.sh                # Logotipo en ASCII art
│   ├── run.sh                 # Ejecución automática en QEMU con UEFI/KVM
│   └── version.sh             # Impresión de la versión
│
├── build-rust.sh              # Compila crates de rust/ -> archiso/airootfs/usr/bin/
├── build-calamares.sh         # Compila Calamares desde AUR (.pkg.tar.zst o .xz)
├── build-aur.sh               # Compila paquetes AUR (python-pywal, yay, wlogout)
├── build-bazaar.sh            # Compila la tienda de apps Bazaar
├── build-grub-theme.sh        # Genera fuentes .pf2 y assets de GRUB
├── build-i18n.sh              # Compila catálogos gettext (po/*.po -> .mo)
└── build-churros-release.sh   # Empaqueta el bundle de utilidades OTA y updates.json
```

---

## 🛠️ Scripts de Compilación (`scripts/build-*.sh`)

| Script | Propósito | Salida generada |
| :--- | :--- | :--- |
| **`build-rust.sh`** | Compila en release los crates de `rust/` con `deploy = true`. | Binarios en `archiso/airootfs/usr/bin/` |
| **`build-calamares.sh`** | Compila Calamares con parches locales y libpython acorde al sistema. | `archiso/packages/calamares-*.pkg.tar.*` |
| **`build-aur.sh`** | Construye dependencias de AUR necesarias para el Live y el sistema instalado. | `archiso/packages/{python-pywal,yay,wlogout}-*.pkg.tar.*` |
| **`build-bazaar.sh`** | Compila Bazaar contra libdex >= 1.2 (en ALARM construye y publica libdex 1.2). | `archiso/packages/bazaar-*.pkg.tar.*` |
| **`build-grub-theme.sh`** | Convierte fuentes TTF a formato de mapa de bits de GRUB (`.pf2`). | `branding/grub-theme/*.pf2` |
| **`build-i18n.sh`** | Compila archivos `.po` de localización con `msgfmt`. | `archiso/airootfs/usr/share/locale/*/LC_MESSAGES/churros.mo` |
| **`build-churros-release.sh`** | Genera el tarball OTA de utilidades y el manifiesto JSON. | `release/churros-utils-<version>.tar.zst`, `release/updates.json` |

---

## 💻 Subcomandos de la CLI (`scripts/cli/`)

Cada comando público del dispatcher principal [`./churros`](../churros) se implementa en un script dentro de `scripts/cli/<comando>.sh`:

- **`./churros build`**: Ejecuta el pipeline completo de compilación de la ISO con `mkarchiso`.
- **`./churros run`**: Inicia la ISO en QEMU con gráficos virtio y aceleración por hardware.
- **`./churros check`**: Ejecuta 20+ pruebas estáticas sobre scripts bash, python, desktop files, orden de Calamares y traducciones.
- **`./churros apps <target>`**: Permite probar las aplicaciones GTK en el host con aislamiento de seguridad.
- **`./churros clean`**: Limpia los directorios temporales `work/` y `out/`.
- **`./churros doctor`**: Comprueba que herramientas como `mkarchiso`, `qemu`, `xorriso` y `mksquashfs` estén presentes en el sistema.

---

## 📖 Documentación Relacionada

- [Manual de la CLI de ChurrOS](../docs/cli.md)
- [Documentación del Sistema de Compilación](../docs/build-system.md)
- [Guía de Desarrollo y Flujo de Trabajo](../docs/development.md)
