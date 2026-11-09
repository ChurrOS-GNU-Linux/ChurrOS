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

Estilo de pantalla de bloqueo, sin tarjeta: el reloj grande arriba y los controles directamente sobre el fondo. Usa la identidad de ChurrOS (Inter, naranja `#F97316`, el logo como avatar), no la de ningún otro sistema.

- **Fondo**: `/var/lib/churros/greeter/background.jpg`. Por defecto es el fondo del escritorio, difuminado, y se actualiza solo (sección 5). `tmpfiles.d/churros-greeter.conf` lo siembra con `/usr/share/churros/greeter/background.jpg`, el fondo de fábrica ya difuminado. Difuminar en GTK con `filter: blur()` cuesta en equipos sin aceleración, así que se difumina al escribir el fichero. Sobre `#0B1020`, la imagen va al 52 % de opacidad (ajustable) para que el texto blanco se lea también en fondos claros.
- **Reloj**: fecha en pequeño y hora grande debajo. ReGreet 0.5 pinta el reloj con `set_markup`, así que `format` es marcado Pango (dos `<span>` con `size`; `tnum` deja las cifras de ancho fijo y la hora no baila). `configure-greeter-locale` solo traduce la fecha del primer `<span>`.
- **Avatar y saludo**: un círculo translúcido con el logo (`/usr/share/pixmaps/churros-logo.png`) pintado como fondo del texto de saludo (`greeting_msg`).
- **Campos en píldora**: usuario, sesión y contraseña son píldoras translúcidas con el foco en halo naranja. Las etiquetas «User:»/«Session:» y el aviso de PAM quedan transparentes. Su columna sigue ocupando 100 px, y la columna de los botones de editar se ensancha lo mismo con margen, para que las píldoras queden centradas.
- **Botones**: «Login» es una píldora naranja y «Cancel» es texto. Reiniciar y apagar son círculos translúcidos con el icono simbólico del tema (`-gtk-icontheme`) y el texto debajo; el de apagar se vuelve rojo al pasar el ratón.
- **Selección recordada**: `skip_selection = true` hace que, después del primer inicio de sesión correcto, ReGreet muestre directamente el campo de contraseña usando el último usuario y sesión. «Cancel» vuelve al selector para cambiar cualquiera de los dos.

ReGreet 0.5 no da nombre a sus widgets (el `#[name]` de relm4 solo nombra el campo en Rust): los selectores de `regreet.css` siguen el árbol de su plantilla (`overlay > frame.background:nth-child(2)` es el formulario y `:nth-child(3)` el reloj). Los textos «User:», «Login», «Cancel», «Reboot» y «Power Off» están en inglés en el código de 0.5.0; la traducción (gettext) solo está en la rama principal de ReGreet.

El paquete `inter-font` solo está en las listas de la edición niri (`packages.x86_64` y `packages.aarch64`); en las demás ediciones GTK usa otra fuente.

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
path = "/usr/share/churros/greeter/background.jpg"
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
greeting_msg = "ChurrOS"

[widget.clock]
format = "<span size='15pt' weight='600'>%A, %-d %B</span>\n<span size='72pt' weight='bold' font_features='tnum' letter_spacing='-2048'>%H:%M</span>"
resolution = "1s"
label_width = 520
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

*Usuarios y Login* tiene el **inicio automático**: `churros-write-root-config greetd-autologin on|off` vía `churros-pkexec` (pide la contraseña de administrador). El helper genera `/etc/greetd/config.toml`: el usuario es quien lo pide y la sesión, la de la edición instalada, con la misma tabla que usa el instalador (`/usr/share/churros/scripts/edition-session.sh`; en Niri, `/usr/bin/churros-niri-session`). Desde ahí se enlaza a la página siguiente.

*Apariencia → Pantalla de inicio* (`pages/greeter.rs`, `services/greeter.rs`):

| Opción | Dónde se guarda | Cómo se aplica |
|---|---|---|
| Usar el fondo del escritorio, imagen propia, difuminar | `~/.config/churros/settings.json` (`greeter.*`) | La sesión escribe `/var/lib/churros/greeter/background.jpg`, **sin contraseña** |
| Oscurecer (0–80 %), mostrar el logo, color de acento | `/etc/greetd/churros-greeter.conf` | `churros-write-root-config greeter-set` reescribe las líneas de `regreet.css` marcadas con `churros:<clave>` |
| Reloj: 24/12 h, segundos, fecha, tamaño | `/etc/greetd/churros-greeter.conf` | `greeter-set` regenera `format` en `regreet.toml` |
| Mensaje de bienvenida | `regreet.toml` (`greeting_msg`) | `churros-write-root-config regreet-greeting` |

**Fondo sin contraseña.** `/var/lib/churros/greeter` es del grupo `wheel` con setgid (`tmpfiles.d/churros-greeter.conf`): la sesión de un administrador escribe ahí la imagen y el greeter solo la lee. Root nunca abre esa imagen ni la del usuario. El trabajo lo hace `churros-settings --sync-greeter`:

- Toma el fondo del escritorio (Noctalia o `settings.json`; en XFCE, el `last-image` de `xfce4-desktop.xml`) o la imagen elegida.
- Lo reduce a 1920×1080, o lo difumina: reducido a 320 px, tres pasadas de desenfoque de caja y ampliado a 1280 px.
- Lo guarda como JPEG con una escritura atómica.
- Si ni el origen ni el difuminado cambiaron, no hace nada (marca en `~/.cache/churros/greeter-sync`).

Lo lanzan la unidad de usuario `churros-greeter-sync.path`, que vigila los ficheros donde Noctalia, Ajustes y xfdesktop guardan el fondo, y `churros-greeter-sync.service` al iniciar sesión (habilitadas para todos en `/etc/systemd/user/default.target.wants`). Un fichero de imagen malicioso solo llega al proceso del greeter, que no es root: el mismo riesgo que cualquier fondo que el usuario ya puede poner en su escritorio.

**Opciones del sistema.** `greeter-set` solo acepta esas claves con valores de una lista o un patrón cerrado (`accent` es `#RRGGBB`, `dim` es un número de 0 a 80): nada libre llega a `regreet.css`. `date_pattern` (el formato de la fecha según el idioma) solo lo fija `configure-greeter-locale` al instalar, como root. Con los valores por defecto, `greeter-set` reproduce exactamente el `regreet.css` y el `regreet.toml` de la ISO (`scripts/test-privileged-helpers.py`).

Los permisos de `churros-write-root-config` están en [privileged-execution.md](privileged-execution.md).

---

## 6. Integración con el instalador Calamares

1. **Módulo `displaymanager`** (`installer/calamares/modules/displaymanager.conf`): configurado para `greetd`, con `churros-xsession` como ejecutable de sesión (este script lee `/etc/churros-edition` y lanza la sesión de la edición). `customize_airootfs.sh` parchea el módulo DMgreetd de Calamares para que use `cage` + `regreet` como `[default_session]`.
2. **Casilla de inicio automático**: viene desmarcada (`doAutologin: false` en `users.conf`). Si se marca, Calamares escribe `[initial_session]` con el usuario creado.
3. **`/usr/share/churros/scripts/configure-greetd-session`** (paso `shellprocess@post-install`): reescribe `/etc/greetd/config.toml` con la sesión de la edición (tabla de `edition-session.sh`), conserva el usuario de autologin que dejó Calamares, si lo hay, y escribe `/etc/greetd/environments`. En la edición server sale sin hacer nada.
4. **XFCE, sesión X11**: ReGreet no usa el comando de `[initial_session]`; descubre las sesiones en `/usr/share/xsessions` y `/usr/share/wayland-sessions`. `xfce4-session` trae una sesión `xfce-wayland` que exige labwc y una `xfce.desktop` que lanza `startxfce4` sin el wrapper. En la edición xfce, `configure-greetd-session` ejecuta `/usr/share/churros/scripts/fix-xfce-sessions` para dejar solo la sesión X11 con `churros-xfce-session`; sin eso, iniciar sesión sin autologin vuelve al greeter en bucle. El hook de pacman `92-churros-xfce-x11-session.hook` lo vuelve a aplicar cuando una actualización reinstala esos ficheros.
5. **Idioma**: el script post-instalación `/usr/share/churros/scripts/configure-greeter-locale` adapta el saludo (`greeting_msg`) y el formato de la fecha del reloj (`churros-write-root-config greeter-set date_pattern=…`; la hora y el resto de opciones no cambian) según el idioma elegido en Calamares.
