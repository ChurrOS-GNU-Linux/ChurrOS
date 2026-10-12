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
elif [ "$EDITION" = "kde" ]; then
    cat > "$SESSION_FILE" << 'EOF'
XDG_CURRENT_DESKTOP=KDE
XDG_SESSION_DESKTOP=plasma
XDG_SESSION_TYPE=wayland
DESKTOP_SESSION=plasma
EOF

    # Plasma arranca con su propio lanzador (startplasma-wayland).
    # Asegurar que el fondo de ChurrOS se aplique como fondo predeterminado en Plasma.
    mkdir -p /usr/share/backgrounds/xdg
    cp -f /usr/share/churros/wallpapers/default.png /usr/share/backgrounds/xdg/churros.png

    # Enlazar sobre los fondos predeterminados de Plasma (Next / Breeze)
    for wp_dir in /usr/share/wallpapers/Next /usr/share/wallpapers/Breeze; do
        mkdir -p "$wp_dir/contents/images" "$wp_dir/contents/images_dark" 2>/dev/null || true
        ln -sf /usr/share/churros/wallpapers/default.png "$wp_dir/contents/images/5120x2880.png" 2>/dev/null || true
        ln -sf /usr/share/churros/wallpapers/default.png "$wp_dir/contents/images_dark/5120x2880.png" 2>/dev/null || true
        ln -sf /usr/share/churros/wallpapers/default.png "$wp_dir/contents/screenshot.png" 2>/dev/null || true
    done

    # Asegurar que el botón de inicio de Plasma (Kickoff) use el logo de ChurrOS
    mkdir -p /usr/share/icons/hicolor/scalable/apps /usr/share/icons/hicolor/scalable/places
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/places/start-here-kde.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/places/start-here.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/places/distributor-logo.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/apps/start-here-kde.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/apps/start-here.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/apps/distributor-logo.svg 2>/dev/null || true
    ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg /usr/share/icons/hicolor/scalable/apps/distributor-logo-arch.svg 2>/dev/null || true

    for icondir in /usr/share/icons/breeze* /usr/share/icons/Papirus*; do
        if [ -d "$icondir" ]; then
            for icon_name in start-here-kde start-here distributor-logo distributor-logo-arch distributor-logo-archlinux; do
                find "$icondir" -type f \( -name "${icon_name}.svg" -o -name "${icon_name}.png" \) -exec ln -sf /usr/share/icons/hicolor/scalable/apps/churros-logo.svg {} + 2>/dev/null || true
            done
        fi
    done

    # Configurar icono y favoritos de ChurrOS en los templates de layout de Plasma
    for ljs in /usr/share/plasma/shells/org.kde.plasma.desktop/contents/layout.js /usr/share/plasma/layout-templates/org.kde.plasma.desktop.defaultPanel/contents/layout.js; do
        if [ -f "$ljs" ]; then
            sed -i 's|panel\.addWidget("org\.kde\.plasma\.kickoff")|kickoff = panel.addWidget("org.kde.plasma.kickoff"); kickoff.currentConfigGroup = ["General"]; kickoff.writeConfig("icon", "churros-logo"); kickoff.writeConfig("useCustomButtonImage", "true"); kickoff.writeConfig("customButtonImage", "/usr/share/icons/hicolor/scalable/apps/churros-logo.svg")|g' "$ljs" 2>/dev/null || true
        fi
    done

    # Conservar systemsettings y su entrada: churros-settings abre los KCM de
    # Plasma a través de ese ejecutable. No modificar archivos de su paquete.
    # Discover sigue oculto en favor de Bazaar.
    for ss_desktop in /usr/share/applications/*discover*.desktop; do
        if [ -f "$ss_desktop" ]; then
            sed -i '/^Exec=/c\Exec=churros-settings' "$ss_desktop" 2>/dev/null || true
            sed -i '/^NoDisplay=/d; /^Hidden=/d' "$ss_desktop" 2>/dev/null || true
            echo "NoDisplay=true" >> "$ss_desktop"
            echo "Hidden=true" >> "$ss_desktop"
        fi
    done

    # Symlink para compatibilidad de bazaar.desktop con io.github.kolunmi.Bazaar.desktop
    if [ -f /usr/share/applications/io.github.kolunmi.Bazaar.desktop ]; then
        ln -sf /usr/share/applications/io.github.kolunmi.Bazaar.desktop /usr/share/applications/bazaar.desktop 2>/dev/null || true
    fi
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
