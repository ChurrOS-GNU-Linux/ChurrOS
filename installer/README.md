# Instalador Gráfico — Calamares para ChurrOS

Este directorio contiene toda la configuración, personalización, branding y scripts de despliegue del instalador gráfico de ChurrOS, basado en **Calamares 3.4**.

---

## 📁 Estructura del Directorio

```text
installer/
├── apply-calamares.sh         # Despliega módulos, branding y reglas polkit al airootfs
├── calamares/
│   ├── settings.conf          # Secuencia oficial de ejecución y módulos
│   ├── branding/churros/      # Identidad visual, slideshow QML y estilos QSS
│   ├── modules/               # Configuraciones .conf y .yaml de cada módulo
│   └── preview/               # Overlay aislado para previsualizar en el host
└── patches/                   # Parches aplicados sobre Calamares al compilar
```

---

## ⚙️ Secuencia de Instalación (`settings.conf`)

La instalación en disco sigue una secuencia validada y crítica con 5 instancias `shellprocess` (pasos principales de `exec` en `settings.conf`; `tests/static/test_calamares_config.py` comprueba este orden):

```text
1. partition / mount            -> Particiona y monta el disco destino.
2. shellprocess@boot-nocow      -> Aplica chattr +C en /boot para evitar zstd en GRUB.
3. unpackfs                     -> Extrae la imagen squashfs del Live al disco destino.
4. shellprocess@pacman-init     -> Inicializa y puebla el keyring de pacman en el sistema instalado.
5. shellprocess@fix-boot        -> Regenera presets de mkinitcpio y módulos del kernel.
6. initcpiocfg / initcpio       -> Configura y genera el initramfs del sistema instalado.
7. users / displaymanager / services-systemd -> Usuario, greetd y servicios.
8. grubcfg / bootloader         -> Configura e instala GRUB.
9. shellprocess@grub-theme      -> Aplica el tema GRUB centrado y hook de lectura Btrfs.
10. shellprocess@post-install   -> Quita sudoers NOPASSWD, reglas polkit de Calamares, ajustes
                                de ssh del Live y rastros del usuario Live.
11. umount                      -> Desmonta las particiones instaladas.
```

Los paquetes locales (calamares, yay, wlogout, python-pywal, bazaar) ya vienen en la ISO por pacstrap: no hay paso `netinstall` ni `packages`.

---

## 🔒 Regla Polkit (`49-calamares.rules`)

`apply-calamares.sh` instala automáticamente una regla en `/etc/polkit-1/rules.d/49-calamares.rules` que autoriza al usuario de la sesión Live (`churros`) a ejecutar Calamares como superusuario sin solicitud interactiva de contraseña:

```javascript
polkit.addRule(function(action, subject) {
    if ((action.id == "org.freedesktop.policykit.exec" &&
         action.lookup("program") == "/usr/bin/calamares") &&
        subject.isInGroup("wheel")) {
        return polkit.Result.YES;
    }
});
```

---

## 🖼️ Vista Previa en el Host

Puedes previsualizar el diseño del instalador y el carrusel de diapositivas en el sistema anfitrión sin riesgo de modificar discos reales:

```bash
./churros apps calamares
```

Este comando utiliza el overlay en `calamares/preview/`:
- No toca `/etc/calamares` del host.
- Omite el módulo de particionado real para proteger los discos.
- Simula la fase de instalación con un temporizador para apreciar el slideshow.

---

## 📖 Documentación Relacionada

- [Roadmap de la Fase 4: Instalador](../docs/roadmap.md)
- [Documentación del Sistema de Arranque](../docs/boot.md)
- [Documentación de Snapshots y Rollback Btrfs](../docs/rollback.md)
