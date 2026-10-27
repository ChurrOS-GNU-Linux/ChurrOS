#!/usr/bin/env bash
set -euo pipefail

echo "==> Configuring desktop..."

# Copiar configuración por defecto
cp -r /etc/skel/.config /home/churros/

# Permisos
chown -R churros:churros /home/churros/.config

# Setear variables de sesion segun la edicion (Niri / XFCE)
EDITION="niri"
if [ -f /etc/churros-edition ]; then
    EDITION="$(tr -d '[:space:]' < /etc/churros-edition | tr '[:upper:]' '[:lower:]')"
fi

SESSION_FILE="/home/churros/.config/environment.d/churros-session.conf"
mkdir -p "/home/churros/.config/environment.d"

if [ "$EDITION" = "xfce" ] || [ "$EDITION" = "server" ]; then
    cat > "$SESSION_FILE" << 'EOF'
XDG_CURRENT_DESKTOP=XFCE
XDG_SESSION_DESKTOP=xfce
XDG_SESSION_TYPE=x11
DESKTOP_SESSION=xfce
EOF

    # Sesión X11 con el wrapper churros-xfce-session y sin la sesión Wayland
    # experimental de xfce4-session 4.20 ('startxfce4 --wayland' exige labwc).
    # El hook 92-churros-xfce-x11-session lo reaplica tras cada pacman -Syu.
    /usr/share/churros/scripts/fix-xfce-sessions

    # Asegurar que el fondo de ChurrOS se aplique incluso en monitores no preconfigurados por XFCE
    mkdir -p /usr/share/backgrounds/xfce
    ln -sf /usr/share/churros/wallpapers/default.png /usr/share/backgrounds/xfce/xfce-shapes.svg
    ln -sf /usr/share/churros/wallpapers/default.png /usr/share/backgrounds/xfce/xfce-verticals.png
    ln -sf /usr/share/churros/wallpapers/default.png /usr/share/backgrounds/xfce/xfce-teal.jpg
    ln -sf /usr/share/churros/wallpapers/default.png /usr/share/backgrounds/xfce/xfce-stripes.png
else
    cat > "$SESSION_FILE" << 'EOF'
XDG_CURRENT_DESKTOP=niri
XDG_SESSION_DESKTOP=niri
XDG_SESSION_TYPE=wayland
XCURSOR_THEME=Adwaita
XCURSOR_SIZE=24
EOF

    # Asegurar que la sesión Wayland ejecute directamente churros-niri-session en el scope de LightDM
    if [ -f /usr/share/wayland-sessions/niri.desktop ]; then
        sed -i 's|^Exec=.*|Exec=/usr/bin/churros-niri-session|' /usr/share/wayland-sessions/niri.desktop
    fi

    # El usuario live no tiene contraseña (users.sh) y Noctalia ignora Enter
    # con la contraseña vacía: sin esto, el bloqueo por inactividad dejaría la
    # sesión sin poder entrar. Solo en el Live; /etc/skel llega a los usuarios
    # del sistema instalado.
    mkdir -p /home/churros/.config/noctalia
    cat > /home/churros/.config/noctalia/live.toml << 'EOF'
[lockscreen]
allow_empty_password = true
EOF
    chown -R churros:churros /home/churros/.config/noctalia
fi
chown -R churros:churros "/home/churros/.config/environment.d"

# Regenerar cache de iconos GTK para que encuentre los iconos Churros
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    for theme_dir in /usr/share/icons/hicolor /usr/share/icons/Adwaita; do
        if [ -d "$theme_dir" ]; then
            gtk-update-icon-cache -f -t "$theme_dir" 2>/dev/null || true
        fi
    done
fi

echo "✓ Desktop configured."
