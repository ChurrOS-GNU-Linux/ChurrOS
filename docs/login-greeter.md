# Pantalla de inicio de sesión (greetd + ReGreet)

ChurrOS usa **`greetd`** como gestor de sesiones y **`ReGreet`**, dentro del compositor **`cage`**, como pantalla de inicio de sesión. Este documento es la referencia única de cómo se configura greetd en el Live y en el sistema instalado.

---

## 1. Arquitectura

```text
greetd.service (VT7)
 │
 ├─ [initial_session]  autologin, una sola vez al arrancar
 │     Live: churros + la sesión de la edición
 │     Instalado: solo si se eligió inicio automático
 │
 └─ [default_session]  usuario greeter
       cage -s -- regreet
        │  autenticación PAM
        ▼
     sesión del usuario (la de la edición)
```

- **`greetd`**: demonio que gestiona el inicio de sesión. Administra el terminal virtual, las sesiones PAM y el IPC con el greeter.
- **`cage`**: compositor Wayland de tipo kiosko, de una sola ventana. Se lanza con `WLR_NO_HARDWARE_CURSORS=1` para evitar artefactos del cursor en tarjetas gráficas virtuales y reales.
- **`ReGreet`**: greeter gráfico escrito en Rust y GTK4. Lee su configuración de `/etc/greetd/regreet.toml` y sus estilos de `/etc/greetd/regreet.css`.

Si existe `[initial_session]`, greetd la lanza al arrancar sin pedir credenciales. Cuando esa sesión termina (al cerrar sesión), greetd pasa a `[default_session]` y muestra ReGreet.

### Sesión de cada edición

| Edición | Live (`[initial_session]`, usuario `churros`) | Sistema instalado |
|---|---|---|
| niri | `niri` | `/usr/bin/churros-niri-session` |
| xfce | `/usr/bin/churros-xfce-session` | `/usr/bin/churros-xfce-session` |
| pi | `/usr/bin/churros-pi-session` | `/usr/bin/churros-pi-session` |
| server | `/usr/bin/churros-xfce-session` (solo para el instalador) | Sin greeter: `greetd` queda deshabilitado ([server.md](server.md)) |

En i686 la ISO se construye como edición niri, pero `archiso/packages.i686` no incluye el paquete `niri`, así que esa sesión no puede arrancar.

---

## 2. Diseño

El tema (`/etc/greetd/regreet.css`) toma referencias de la sobriedad de la pantalla de inicio de macOS —superficies translúcidas, tarjeta compacta y una acción principal clara— sin copiar su logotipo, tipografía ni controles. Mantiene el fondo y la identidad propios de ChurrOS:

- **Fondo de pantalla**: `/usr/share/churros/wallpapers/default.png`, o el que se sincronice desde Ajustes (ver la sección 5).
- **Tarjeta central de cristal** oscura, de bordes suaves y con sombra discreta; no se desplaza con márgenes fijos para no descentrarse en pantallas pequeñas.
- **Campos y selectores** redondeados, con contraste suficiente sobre el cristal.
- **Foco y acción principal** en naranja ChurrOS (`#F97316`); los controles secundarios son más tenues.
- **Reloj y saludo** con `Inter` y fuente de respaldo. El paquete `inter-font` solo está en las listas de la edición niri (`packages.x86_64` y `packages.aarch64`); en las demás ediciones GTK usa otra fuente.

El rediseño es CSS de GTK y no cambia greetd, PAM, usuarios, sesiones ni el proceso de autenticación. La comprobación estática valida la sintaxis; para confirmar el aspecto final también se debe revisar el greeter en una sesión gráfica real.

---

## 3. Archivos de configuración

### `/etc/greetd/config.toml`

En el Live este archivo lo genera `scripts/cli/build.sh` según `--edition`. El que está en `archiso/airootfs/etc/greetd/config.toml` es la versión niri: el build lo sobrescribe y lo restaura al terminar, así que editarlo a mano no cambia la ISO. El que genera `build.sh`:

```toml
[terminal]
vt = 7

[default_session]
command = "env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24 cage -s -- regreet"
user = "greeter"

[initial_session]
command = "<comando de la edición, ver la tabla de la sección 1>"
user = "churros"
```

- En el **Live**, `[initial_session]` entra directamente al escritorio del usuario `churros`.
- En el **sistema instalado**, el archivo lo reescribe `configure-greetd-session` (sección 6): `[default_session]` siempre lanza ReGreet para pedir credenciales y `[initial_session]` solo aparece si se eligió el inicio automático.

`getty@tty1` está enmascarado (lo hace `services.sh` en el Live y el módulo `services-systemd` de Calamares en el sistema instalado): el único inicio de sesión gráfico es el de greetd.

### `/etc/greetd/regreet.toml`

```toml
[background]
path = "/usr/share/churros/wallpapers/default.png"
fit = "Cover"

[GTK]
application_prefer_dark_theme = true
cursor_theme_name = "Adwaita"
font_name = "Inter 11"
icon_theme_name = "Papirus-Dark"
theme_name = "Adwaita-dark"

[commands]
reboot = ["systemctl", "reboot"]
poweroff = ["systemctl", "poweroff"]

[appearance]
greeting_msg = "Bienvenido a ChurrOS"

[widget.clock]
format = "%A, %d de %B  -  %H:%M"
resolution = "1s"
```

### `/etc/pam.d/greetd`

```pam
#%PAM-1.0

auth       include      system-local-login
account    include      system-local-login
password   include      system-local-login
session    include      system-local-login
-session   optional     pam_gnome_keyring.so auto_start
```

---

## 4. Usuarios

- **`churros`** (solo Live): sin contraseña y con autologin. Lo crea `archiso/airootfs/root/scripts/users.sh` (detalle en [live-services.md](live-services.md#usuario-live)).
- **`greeter`**: usuario de sistema con el que corren `cage` y ReGreet. `users.sh` le añade los grupos `video`, `input`, `render` y `tty`.

---

## 5. Integración con Ajustes (`churros-settings`)

En el crate `preferences` (`churros-settings` → *Usuarios y Login*):

- **Inicio automático (autologin)**: activa o desactiva el autologin en el sistema instalado con `churros-write-root-config greetd-autologin on|off` vía `churros-pkexec` (pide la contraseña de administrador). El helper genera `/etc/greetd/config.toml`: el usuario es quien lo pide y la sesión, la de la edición instalada, con la misma tabla que usa el instalador (`/usr/share/churros/scripts/edition-session.sh`; en Niri, `/usr/bin/churros-niri-session`).
- **Sincronizar fondo**: pone el wallpaper actual del escritorio como fondo en `/etc/greetd/regreet.toml` (`regreet-wallpaper`). Solo admite fondos del sistema (`/usr/share/churros/wallpapers`, `/usr/share/backgrounds`, `/usr/share/wallpapers`): uno del home no lo puede leer el greeter. Si no se puede, la fila lo indica.
- **Mensaje de bienvenida**: muestra el saludo configurado en la pantalla de inicio.

Los permisos de `churros-write-root-config` están en [privileged-execution.md](privileged-execution.md).

---

## 6. Integración con el instalador Calamares

1. **Módulo `displaymanager`** (`installer/calamares/modules/displaymanager.conf`): configurado para `greetd`, con `churros-xsession` como ejecutable de sesión (este script lee `/etc/churros-edition` y lanza la sesión de la edición). `customize_airootfs.sh` parchea el módulo DMgreetd de Calamares para que use `cage` + `regreet` como `[default_session]`.
2. **Casilla de inicio automático**: viene desmarcada (`doAutologin: false` en `users.conf`). Si se marca, Calamares escribe `[initial_session]` con el usuario creado.
3. **`/usr/share/churros/scripts/configure-greetd-session`** (paso `shellprocess@post-install`): reescribe `/etc/greetd/config.toml` con la sesión de la edición (tabla de `edition-session.sh`), conserva el usuario de autologin que dejó Calamares, si lo hay, y escribe `/etc/greetd/environments`. En la edición server sale sin hacer nada.
4. **XFCE, sesión X11**: ReGreet no usa el comando de `[initial_session]`; descubre las sesiones en `/usr/share/xsessions` y `/usr/share/wayland-sessions`. `xfce4-session` trae una sesión `xfce-wayland` que exige labwc y una `xfce.desktop` que lanza `startxfce4` sin el wrapper. En la edición xfce, `configure-greetd-session` ejecuta `/usr/share/churros/scripts/fix-xfce-sessions` para dejar solo la sesión X11 con `churros-xfce-session`; sin eso, iniciar sesión sin autologin vuelve al greeter en bucle. El hook de pacman `92-churros-xfce-x11-session.hook` lo vuelve a aplicar cuando una actualización reinstala esos ficheros.
5. **Idioma**: el script post-instalación `/usr/share/churros/scripts/configure-greeter-locale` adapta el saludo (`greeting_msg`) y el formato de fecha (`format`) de `regreet.toml` según el idioma elegido en Calamares.
