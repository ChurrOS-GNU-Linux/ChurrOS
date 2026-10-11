# Pantalla de Inicio de Sesión (Login Screen / Greeter)

ChurrOS utiliza una arquitectura gráfica moderna y ultraligera para la pantalla de bienvenida e inicio de sesión basada en **`greetd`** + **`ReGreet`** + **`cage`**.

---

## 1. Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                     greetd.service                      │
│                (Ejecutándose en VT7)                    │
└───────────────────────────┬─────────────────────────────┘
                            │
               Lanza [default_session]
                            ▼
┌─────────────────────────────────────────────────────────┐
│                          cage                           │
│       (Compositor kiosko Wayland en modo seguro)        │
│       env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita│
└───────────────────────────┬─────────────────────────────┘
                            │
                      Abre interfaz
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     greetd-regreet                      │
│             (Greeter gráfico en GTK4 / Rust)            │
│       Tema: macOS Liquid Glass (/etc/greetd/regreet.css)│
└───────────────────────────┬─────────────────────────────┘
                            │
                 Autenticación PAM / Sesión
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     Sesión de Usuario                   │
│     churros-niri-session / churros-xfce-session         │
└─────────────────────────────────────────────────────────┘
```

- **`greetd`**: Demonio del gestor de sesiones. Administra terminales virtuales, sesiones PAM e IPC.
- **`cage`**: Compositor kiosko Wayland de una sola ventana (< 1MB de RAM), configurado con `WLR_NO_HARDWARE_CURSORS=1` para evitar artefactos en tarjetas gráficas virtuales y reales.
- **`ReGreet`**: Greeter gráfico nativo escrito en Rust y GTK4. Lee la configuración desde `/etc/greetd/regreet.toml` y estilos CSS desde `/etc/greetd/regreet.css`.

---

## 2. Diseño Estilo macOS Liquid Glass

El greeter implementa una estética de cristal esmerilado inspirada en macOS con detalles de acento naranja ChurrOS:

- **Fondo de Pantalla**: Carga `/usr/share/churros/wallpapers/default.png` o el fondo personalizado configurado por el usuario.
- **Campos de Entrada y Botones en Píldora (`border-radius: 9999px`)**: Entradas de contraseña y selector de sesión translúcidos (`rgba(255, 255, 255, 0.16)`).
- **Efectos de Foco**: Resplandor dinámico en color acento naranja ChurrOS (`#F97316`).
- **Avatar Circular**: Con bordes luminosos y sombras suaves.
- **Reloj y Saludo**: Tipografía `Inter` con renderizado limpio.

---

## 3. Archivos de Configuración

### `/etc/greetd/config.toml`
```toml
[terminal]
vt = 7

[default_session]
command = "env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24 cage -s -- regreet"
user = "greeter"

[initial_session]
command = "niri"
user = "churros"
```

- En la sesión **Live ISO**, `initial_session` permite entrar directamente al escritorio del usuario `churros`.
- En el **sistema instalado**, `default_session` lanza la interfaz gráfica de `regreet` para solicitar credenciales.

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

## 4. Integración con Preferencias (`churros-settings`)

En el crate `preferences` (`churros-settings` -> *Usuarios y Login*):
- **Inicio Automático (Autologin)**: Permite activar o desactivar el autologin en vivo con `churros-write-root-config greetd-autologin on|off` vía `churros-pkexec` (pide la contraseña de administrador). El helper genera `/etc/greetd/config.toml`: el usuario es quien lo pide y la sesión, la de la edición instalada, con la misma tabla que usa el instalador (`/usr/share/churros/scripts/edition-session.sh`; en Niri, `/usr/bin/churros-niri-session`).
- **Sincronizar Fondo**: Pone el wallpaper actual del escritorio como fondo en `/etc/greetd/regreet.toml` (`regreet-wallpaper`). Solo admite fondos del sistema (`/usr/share/churros/wallpapers`, `/usr/share/backgrounds`, `/usr/share/wallpapers`): uno del home no lo puede leer el greeter. Si no se puede, la fila lo indica.
- **Mensaje de Bienvenida**: Muestra el saludo configurado en la pantalla de inicio.

---

## 5. Integración con el Instalador Calamares

- **Módulo `displaymanager`**: Configurado para `greetd`.
- **Checkbox de Inicio Automático**:
  - Si se marca *"Iniciar sesión automáticamente"*, Calamares genera `[initial_session]` con el usuario creado.
  - Si se desmarca, Calamares deja `[default_session]` apuntando a `regreet` para solicitar usuario y contraseña.
- **Sincronización de Idioma**: El script post-instalación `/usr/share/churros/scripts/configure-greeter-locale` adapta automáticamente el saludo (`greeting_msg`) y el formato de fecha (`format`) de `regreet.toml` según el idioma seleccionado por el usuario en Calamares.
