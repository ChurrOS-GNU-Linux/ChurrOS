# Instalador gráfico — Calamares para ChurrOS

Este directorio contiene la configuración, el branding y los scripts de despliegue del instalador gráfico de ChurrOS, basado en **Calamares 3.4** (paquete del AUR compilado por `scripts/build-calamares.sh` con los parches de `patches/`). La ISO i686 no lleva instalador: Arch Linux 32 no empaqueta `polkit-qt6`.

---

## Estructura del directorio

```text
installer/
├── apply-calamares.sh         # Copia configuración, módulos, branding y regla polkit al airootfs durante el build
├── calamares/
│   ├── settings.conf          # Instancias shellprocess y secuencia de módulos
│   ├── branding/churros/      # Identidad visual, slideshow QML y estilos QSS
│   ├── modules/               # Un .conf (o .yaml) por módulo
│   │   ├── aarch64/           # Variantes ARM64 (unpackfs, fix-boot, pacman-init, grubcfg)
│   │   └── i686/              # Variantes i686 (unpackfs, fix-boot, pacman-init)
│   └── preview/               # Configuración aislada para previsualizar en el host
└── patches/                   # Parches aplicados sobre Calamares al compilarlo
```

`apply-calamares.sh` copia primero los módulos comunes y después, encima, los de `modules/<arch>/`.

---

## Secuencia de instalación (`settings.conf`)

`settings.conf` define cinco instancias `shellprocess` (`boot-nocow`, `pacman-init`, `fix-boot`, `grub-theme` y `post-install`). La fase de ejecución sigue este orden, y el orden importa (`tests/static/test_calamares_config.py` lo comprueba):

```text
partition                    -> Crea y formatea las particiones (btrfs por defecto).
mount                        -> Monta las particiones del destino.
shellprocess@boot-nocow      -> chattr +C y sin compresión en /boot, para que GRUB lea el kernel.
unpackfs                     -> Copia la imagen squashfs del Live (y el kernel) al disco.
machineid, fstab, locale, keyboard, localecfg
shellprocess@pacman-init     -> Inicializa y puebla el keyring de pacman.
shellprocess@fix-boot        -> Cambia el preset de mkinitcpio de archiso por el normal y añade módulos de vídeo.
initcpiocfg, initcpio        -> Genera el initramfs.
users, displaymanager, networkcfg, hwclock, services-systemd
grubcfg, bootloader          -> Instala GRUB.
shellprocess@grub-theme      -> Copia el tema GRUB, regenera grub.cfg y deja /boot legible para GRUB.
shellprocess@post-install    -> Limpieza: quita el repo [churros], Calamares y su regla polkit, el sudo
                                sin contraseña, la configuración ssh del Live y el usuario churros.
umount                       -> Desmonta las particiones.
```

`pacman-init` tiene que ir antes que `fix-boot`, y `boot-nocow` antes que `unpackfs`. No hay paso `netinstall` ni `packages`: los paquetes locales (calamares, yay, wlogout, python-pywal, bazaar) ya vienen en la ISO por pacstrap, y las aplicaciones opcionales las instala [ChurrOS Tour](../docs/churros-tour.md) en el primer inicio del sistema instalado.

---

## Regla polkit (`49-calamares.rules`)

`apply-calamares.sh` instala en `/etc/polkit-1/rules.d/49-calamares.rules` una regla que permite al usuario del Live (`churros`) ejecutar Calamares como root sin pedir contraseña:

```javascript
polkit.addRule(function(action, subject) {
    if (action.id == "io.calamares.calamares.pkexec.run" &&
        subject.user == "churros") {
        return polkit.Result.YES;
    }
});
```

El paso `post-install` la borra del sistema instalado.

---

## Vista previa en el host

Puedes previsualizar el diseño del instalador y el carrusel de diapositivas en el sistema anfitrión sin riesgo de modificar discos reales:

```bash
./churros apps calamares
```

Este comando utiliza la configuración de `calamares/preview/`:
- No toca `/etc/calamares` del host.
- No incluye el módulo de particionado.
- Simula la fase de instalación con una pausa (`sleep 8`) para ver el slideshow.

---

## Documentación relacionada

- [Instalador (Calamares)](../docs/installer.md)
- [Sistema de compilación](../docs/build-system.md)
- [Sistema de arranque](../docs/boot.md)
- [Snapshots y rollback con Btrfs](../docs/rollback.md)
