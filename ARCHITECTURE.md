# ChurrOS Architecture

Este documento describe la arquitectura general del proyecto.

Su objetivo es mantener una estructura limpia, organizada y fácil de mantener a medida que ChurrOS evolucione.

---

# Organización

Cada directorio tiene una única responsabilidad.

```
archiso/
```

Perfil de ArchISO: paquetes, airootfs, cargadores de la ISO.

---

```
rust/
```

Apps oficiales (gtk4-rs + libadwaita) y la librería `churros_services`. Los binarios se despliegan en el airootfs al construir.

---

```
branding/
```

Identidad visual y `customize_airootfs.sh` (se copia al Live en cada build).

- Archivos de sistema (`os-release`, issue, motd)
- Tema GRUB
- Guías de color, tipografía, logo y mascota

---

```
installer/
```

Configuración de Calamares (`settings.conf`, módulos, `apply-calamares.sh`).

---

```
docs/
```

Documentación oficial.

---

```
scripts/
```

CLI (`./churros`) y scripts de build. Nunca deberán contener recursos del sistema instalado.

---

```
po/
```

Traducciones gettext.

---

# Stack del escritorio

| Pieza | Implementación |
|-------|----------------|
| Compositor | Niri |
| Shell | Noctalia v5 (paquete `noctalia` de [extra]) |
| Display manager | greetd (regreet + cage con autologin en Live) |
| Terminal | foot |
| Launcher | Fuzzel |
| Panel | Noctalia (Waybar como alternativa) |
| Notificaciones | Noctalia (Mako como alternativa) |
| Audio | PipeWire + WirePlumber |
| Instalador | Calamares |
| Arranque ISO | GRUB (UEFI) + Syslinux (BIOS) |

---

# Filosofía

Cada componente del proyecto debe ser independiente.

Esto facilita:

- mantenimiento
- pruebas
- reutilización
- colaboración

---

# Evolución

La arquitectura podrá cambiar cuando sea necesario.

Cualquier modificación importante deberá mantener la simplicidad del proyecto.

---

# Principios

- Una responsabilidad por carpeta.
- Código reutilizable.
- Documentación primero.
- Automatización siempre que sea posible.
- Evitar duplicación.
