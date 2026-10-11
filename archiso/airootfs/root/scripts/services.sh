#!/usr/bin/env bash
set -e

echo "==> Enabling services..."

# systemctl enable aborts customize_airootfs (set -e) when the unit file was
# not installed. Enable a unit only when it exists and warn otherwise.
enable_unit() {
    local unit="$1"
    local dir template
    for dir in /etc/systemd/system /usr/lib/systemd/system /lib/systemd/system; do
        if [ -e "$dir/$unit" ] || [ -L "$dir/$unit" ]; then
            systemctl enable "$unit"
            return 0
        fi
        case "$unit" in
            *@*)
                template="${unit%%@*}@.${unit##*.}"
                if [ -e "$dir/$template" ] || [ -L "$dir/$template" ]; then
                    systemctl enable "$unit"
                    return 0
                fi
                ;;
        esac
    done
    printf 'warning: unit %s does not exist; not enabling it\n' "$unit" >&2
}

systemctl mask getty@tty1.service
systemctl mask plymouth-start.service 2>/dev/null || true
systemctl mask plymouth-quit.service 2>/dev/null || true
systemctl mask plymouth-quit-wait.service 2>/dev/null || true
systemctl mask systemd-time-wait-sync.service 2>/dev/null || true
systemctl mask NetworkManager-wait-online.service 2>/dev/null || true
# NetworkManager owns interface configuration. systemd-networkd is not started
# by the Live profile; systemd-resolved remains enabled for the DNS stub resolver.

enable_unit NetworkManager.service
enable_unit greetd.service
enable_unit ufw.service

echo "✓ Services enabled."