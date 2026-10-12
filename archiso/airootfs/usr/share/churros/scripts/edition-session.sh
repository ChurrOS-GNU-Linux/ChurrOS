# shellcheck shell=bash
#
# edition-session.sh — edición instalada y sesión gráfica que le corresponde.
#
# Tabla única para configure-greetd-session (al instalar) y
# churros-write-root-config (autologin desde Ajustes): si se añade una
# edición, se añade aquí. Se carga con `.`; no se ejecuta.
#
#   edición  greetd [initial_session]         LightDM autologin-session
#   niri     /usr/bin/churros-niri-session     niri
#   xfce     /usr/bin/startxfce4               xfce
#   kde      /usr/bin/startplasma-wayland      plasma
#   server   (sin sesión: el sistema instalado no tiene display manager)
#
# Sin /etc/churros-edition, o con una edición desconocida, cuenta como niri,
# igual que en churros-xsession.

# Edición instalada, en minúsculas y sin espacios.
churros_edition() {
    local edition=""
    if [ -f /etc/churros-edition ]; then
        edition="$(tr -d '[:space:]' < /etc/churros-edition | tr '[:upper:]' '[:lower:]')"
    fi
    printf '%s\n' "${edition:-niri}"
}

# Comando de [initial_session] de greetd para una edición. Sale con 1 en
# server, que no tiene sesión gráfica.
churros_session_command() {
    case "$1" in
        server) return 1 ;;
        xfce)   printf '%s\n' /usr/bin/startxfce4 ;;
        kde)    printf '%s\n' /usr/bin/startplasma-wayland ;;
        pi)     printf '%s\n' /usr/bin/churros-pi-session ;;
        *)      printf '%s\n' /usr/bin/churros-niri-session ;;
    esac
}

# Nombre de la sesión (fichero .desktop) para autologin-session de LightDM.
churros_lightdm_session() {
    case "$1" in
        server) return 1 ;;
        xfce)   printf '%s\n' xfce ;;
        kde)    printf '%s\n' plasma ;;
        pi)     printf '%s\n' pi ;;
        *)      printf '%s\n' niri ;;
    esac
}

# /etc/greetd/config.toml completo: greeter ReGreet y, si se pasa usuario,
# inicio automático con [initial_session].
#   churros_greetd_config COMANDO_DE_SESION [USUARIO]
churros_greetd_config() {
    local session="$1" user="${2:-}"
    cat <<EOF
[terminal]
vt = 7

[default_session]
command = "env WLR_NO_HARDWARE_CURSORS=1 XCURSOR_THEME=Adwaita XCURSOR_SIZE=24 cage -s -- regreet"
user = "greeter"
EOF
    if [ -n "$user" ]; then
        cat <<EOF

[initial_session]
command = "$session"
user = "$user"
EOF
    fi
}
