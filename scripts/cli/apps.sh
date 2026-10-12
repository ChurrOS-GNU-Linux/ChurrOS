#!/usr/bin/env bash
#
# Open distro apps on the host (no ISO, no QEMU). GTK crates in dummy
# preview (CHURROS_DEV + throwaway HOME + PATH stubs); Calamares via a
# throwaway config overlay that cannot install.
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

CARGO_MANIFEST="$REPO_ROOT/rust/Cargo.toml"
CALAMARES_SRC="$REPO_ROOT/installer/calamares"
PREVIEW_DIR="$CALAMARES_SRC/preview"
POPUPS=(network audio volume bluetooth power brightness battery)

LIVE_HOST=0
TMP_DIRS=()
CALAMARES_BIN=""
CALAMARES_PREFIX=""

cleanup() {
    local dir
    for dir in "${TMP_DIRS[@]+"${TMP_DIRS[@]}"}"; do
        rm -rf "$dir"
    done
}
trap cleanup EXIT

die() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

require_not_root() {
    if [ "$(id -u)" -eq 0 ]; then
        die "./churros apps must not run as root"
    fi
}

have_display() {
    [ -n "${WAYLAND_DISPLAY:-}" ] || [ -n "${DISPLAY:-}" ]
}

print_check() {
    local ok=$1
    shift
    if [ "$ok" -eq 1 ]; then
        printf '✓ %s\n' "$*"
    else
        printf '✗ %s\n' "$*"
    fi
}

calamares_pkg() {
    if [ ! -d "$REPO_ROOT/archiso/packages" ]; then
        return 0
    fi
    find "$REPO_ROOT/archiso/packages" -maxdepth 1 -name 'calamares-[0-9]*.pkg.tar.*' ! -name '*.sig' -print -quit
}

show_help() {
    cat <<'EOF'
Usage:
  ./churros apps
  ./churros apps doctor
  ./churros apps welcome|settings|control-center|tour|calamares
  ./churros apps popup <audio|volume|network|bluetooth|brightness|battery|power>

Open ChurrOS apps on this machine without building the ISO.

GTK apps compile from rust/. By default they run in preview mode:
writes go to a throwaway HOME, and commands that change the system
(volume, network, power, gsettings, pkill) are dummy. Watch stderr
for lines starting with [churros-dev].

Calamares uses a temporary config: no /etc/calamares, no partition
page, no polkit, no live timezone/keyboard, no reboot. Install is sleep.

  --live-host   GTK only; buttons CAN change this machine. Rejected
                for calamares.

This does not replace ./churros run.
EOF
}

run_doctor() {
    local ok=1 display_ok=0 cargo_ok=0 gtk_ok=0 cala_ok=0 pkg

    echo "Apps host diagnostics"
    echo

    if have_display; then
        display_ok=1
        if [ -n "${WAYLAND_DISPLAY:-}" ]; then
            print_check 1 "display (Wayland)"
        else
            print_check 1 "display (X11)"
        fi
    else
        print_check 0 "display — set WAYLAND_DISPLAY or DISPLAY"
        ok=0
    fi

    if command -v cargo >/dev/null 2>&1; then
        cargo_ok=1
        print_check 1 "cargo"
    else
        print_check 0 "cargo — pacman -S rust"
        ok=0
    fi

    if command -v pkg-config >/dev/null 2>&1 \
        && pkg-config --exists gtk4 libadwaita-1; then
        gtk_ok=1
        print_check 1 "gtk4 + libadwaita"
    else
        print_check 0 "gtk4 + libadwaita — pacman -S gtk4 libadwaita"
        ok=0
    fi

    if command -v calamares >/dev/null 2>&1; then
        cala_ok=1
        print_check 1 "calamares ($(command -v calamares))"
    else
        pkg="$(calamares_pkg)"
        if [ -n "$pkg" ]; then
            cala_ok=1
            print_check 1 "calamares package ($pkg)"
        else
            print_check 0 "calamares — install it or run ./scripts/build-calamares.sh"
        fi
    fi

    echo
    if [ -e "$REPO_ROOT/work" ] && [ ! -w "$REPO_ROOT/work" ]; then
        echo "note: work/ is not writable (leftover from sudo mkarchiso)."
        echo "      ./scripts/build-calamares.sh will use /tmp. Or run: ./churros clean"
        echo
    fi

    if [ "$ok" -eq 1 ] && [ "$cala_ok" -eq 1 ]; then
        echo "Diagnostics complete."
        return 0
    fi
    if [ "$display_ok" -eq 1 ] && [ "$cargo_ok" -eq 1 ] && [ "$gtk_ok" -eq 1 ]; then
        echo "GTK targets can run. Calamares preview needs a binary or local package."
        return 0
    fi
    echo "Diagnostics found missing dependencies."
    return 1
}

require_display() {
    if ! have_display; then
        die "no graphical session (WAYLAND_DISPLAY / DISPLAY). Try ./churros apps doctor"
    fi
}

require_cargo() {
    command -v cargo >/dev/null 2>&1 || die "cargo is not installed. pacman -S rust"
}

require_gtk() {
    if command -v pkg-config >/dev/null 2>&1 && ! pkg-config --exists gtk4 libadwaita-1; then
        die "gtk4/libadwaita not found. pacman -S gtk4 libadwaita"
    fi
}

STUB_NAMES=(
    nmcli wpctl brightnessctl bluetoothctl rfkill systemctl loginctl
    gsettings dconf pkill kill killall pkexec sudo churros-pkexec
    calamares wal timedatectl localectl ufw makoctl niri hyprctl swaymsg swaybg
    swaylock swayidle wlsunset waybar install pacman flatpak
    sh bash foot churros-apply-wallpaper waypaper churros-update-utils
    churros-pick-image setxkbmap loadkeys awww awww-daemon noctalia
)

prepare_dev_sandbox() {
    local stub name
    stub="$REPO_ROOT/scripts/cli/apps-dev-stub.sh"
    [ -x "$stub" ] || die "missing $stub"

    DEV_HOME="$(mktemp -d /tmp/churros-dev-home.XXXXXX)"
    DEV_BIN="$(mktemp -d /tmp/churros-dev-bin.XXXXXX)"
    TMP_DIRS+=("$DEV_HOME" "$DEV_BIN")

    mkdir -p "$DEV_HOME/.config" "$DEV_HOME/.local/share" \
        "$DEV_HOME/.local/state" "$DEV_HOME/.cache"

    for name in "${STUB_NAMES[@]}"; do
        ln -s "$stub" "$DEV_BIN/$name"
    done
}

CALAMARES_STUB_NAMES=(
    pkexec sudo churros-pkexec timedatectl localectl setxkbmap loadkeys
    systemctl loginctl reboot shutdown halt poweroff
    mount umount mkfs mkfs.btrfs mkfs.ext4 mkfs.vfat mkfs.fat mkswap
    parted sgdisk sfdisk wipefs dd cryptsetup
    pacman
)

prepare_calamares_stubs() {
    local stub name
    stub="$REPO_ROOT/scripts/cli/apps-dev-stub.sh"
    [ -x "$stub" ] || die "missing $stub"

    DEV_BIN="$(mktemp -d /tmp/churros-dev-bin.XXXXXX)"
    TMP_DIRS+=("$DEV_BIN")

    for name in "${CALAMARES_STUB_NAMES[@]}"; do
        ln -s "$stub" "$DEV_BIN/$name"
    done
}

crate_bin_name() {
    case "$1" in
        churros-welcome) printf '%s\n' churros-welcome ;;
        churros-tour) printf '%s\n' churros-tour ;;
        churros-settings) printf '%s\n' churros-settings ;;
        churros-control-center) printf '%s\n' churros-control-center ;;
        churros-popup) printf '%s\n' churros-popup ;;
        *) die "unknown crate $1" ;;
    esac
}

run_gtk_crate() {
    local crate=$1 bin
    shift
    require_not_root
    require_display
    require_cargo
    require_gtk

    cargo build --manifest-path "$CARGO_MANIFEST" -p "$crate"
    bin="$REPO_ROOT/rust/target/debug/$(crate_bin_name "$crate")"
    [ -x "$bin" ] || die "cargo did not produce $bin"

    if [ "$LIVE_HOST" -eq 1 ]; then
        echo "WARNING: --live-host: buttons CAN change this machine."
        echo
        "$bin" "$@"
        return
    fi

    prepare_dev_sandbox
    echo "Preview mode: system changes are dummy. Host configs are not written."
    echo "  HOME=$DEV_HOME"
    echo "  Blocked commands log as [churros-dev] on stderr."
    echo

    # Keep WAYLAND_DISPLAY / XDG_RUNTIME_DIR / DBUS from the real session.
    env \
        CHURROS_DEV=1 \
        HOME="$DEV_HOME" \
        XDG_CONFIG_HOME="$DEV_HOME/.config" \
        XDG_DATA_HOME="$DEV_HOME/.local/share" \
        XDG_STATE_HOME="$DEV_HOME/.local/state" \
        XDG_CACHE_HOME="$DEV_HOME/.cache" \
        CHURROS_TOUR_PREVIEW=1 \
        PATH="$DEV_BIN:$PATH" \
        "$bin" "$@"
}

is_popup() {
    local name=$1 p
    for p in "${POPUPS[@]}"; do
        if [ "$p" = "$name" ]; then
            return 0
        fi
    done
    return 1
}

# Extract the local Calamares package into a prefix. Host Qt/KF stay in use;
# only Calamares libs, plugins and QML come from the archive.
prepare_extracted_calamares() {
    local pkg prefix qml plugins
    pkg="$(calamares_pkg)"
    [ -n "$pkg" ] || return 1
    prefix="$(mktemp -d /tmp/churros-calamares-prefix.XXXXXX)"
    TMP_DIRS+=("$prefix")
    if command -v bsdtar >/dev/null 2>&1; then
        bsdtar -xf "$pkg" -C "$prefix"
    elif tar --help 2>/dev/null | grep -q -- --zstd; then
        tar --zstd -xf "$pkg" -C "$prefix"
    else
        die "need bsdtar (or tar --zstd) to extract the Calamares package"
    fi
    CALAMARES_BIN="$prefix/usr/bin/calamares"
    CALAMARES_PREFIX="$prefix"
    [ -x "$CALAMARES_BIN" ] || die "extracted package has no usr/bin/calamares"

    if [ -d "$prefix/usr/lib" ]; then
        export LD_LIBRARY_PATH="$prefix/usr/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    fi
    for qml in "$prefix/usr/share/calamares/qml" "$prefix/usr/lib/qt6/qml" "$prefix/usr/lib/qt/qml"; do
        if [ -d "$qml" ]; then
            export QML2_IMPORT_PATH="$qml${QML2_IMPORT_PATH:+:$QML2_IMPORT_PATH}"
            export QML_IMPORT_PATH="$qml${QML_IMPORT_PATH:+:$QML_IMPORT_PATH}"
        fi
    done
    for plugins in "$prefix/usr/lib/qt6/plugins" "$prefix/usr/lib/qt/plugins"; do
        if [ -d "$plugins" ]; then
            export QT_PLUGIN_PATH="$plugins${QT_PLUGIN_PATH:+:$QT_PLUGIN_PATH}"
        fi
    done
}

resolve_calamares_bin() {
    # Prefer the local package so the netinstall patch matches the ISO.
    if prepare_extracted_calamares; then
        return 0
    fi
    if command -v calamares >/dev/null 2>&1; then
        CALAMARES_BIN="$(command -v calamares)"
        CALAMARES_PREFIX=""
        return 0
    fi
    die "calamares not in PATH and no archiso/packages/calamares-*.pkg.tar.*. Run ./scripts/build-calamares.sh"
}

# -c DIR replaces SHARE/calamares, so DIR/qml must exist or Calamares exits.
calamares_qml_src() {
    local root
    if [ -n "${CALAMARES_PREFIX:-}" ] && [ -d "$CALAMARES_PREFIX/usr/share/calamares/qml" ]; then
        printf '%s\n' "$CALAMARES_PREFIX/usr/share/calamares/qml"
        return 0
    fi
    if [ -n "${CALAMARES_BIN:-}" ]; then
        root="$(cd "$(dirname "$CALAMARES_BIN")/.." && pwd)"
        if [ -d "$root/share/calamares/qml" ]; then
            printf '%s\n' "$root/share/calamares/qml"
            return 0
        fi
    fi
    if [ -d /usr/share/calamares/qml ]; then
        printf '%s\n' /usr/share/calamares/qml
        return 0
    fi
    return 1
}

# "local" in modules-search is $LIBDIR/calamares/modules (baked in as /usr/lib).
# An extracted package lives elsewhere; put that path first.
inject_extracted_modules_search() {
    local settings=$1 modules_dir=$2
    python3 - "$settings" "$modules_dir" <<'PY'
from pathlib import Path
import sys

settings, modules_dir = Path(sys.argv[1]), sys.argv[2]
text = settings.read_text(encoding="utf-8")
needle = "modules-search:\n"
if needle not in text:
    sys.exit("settings.conf has no modules-search key")
settings.write_text(text.replace(needle, needle + f"  - {modules_dir}\n", 1), encoding="utf-8")
PY
}

run_calamares() {
    local cfg branding_src qml_src modules_dir preview_conf

    require_not_root
    require_display

    if [ "$LIVE_HOST" -eq 1 ]; then
        die "--live-host is not allowed for calamares (would risk installing on this machine)"
    fi

    [ -f "$PREVIEW_DIR/settings.conf" ] || die "missing $PREVIEW_DIR/settings.conf"
    [ -f "$PREVIEW_DIR/shellprocess-preview.conf" ] || die "missing $PREVIEW_DIR/shellprocess-preview.conf"
    branding_src="$CALAMARES_SRC/branding/churros"
    [ -f "$branding_src/branding.desc" ] || die "missing $branding_src/branding.desc"

    resolve_calamares_bin
    prepare_calamares_stubs

    cfg="$(mktemp -d /tmp/churros-calamares-XXXXXX)"
    TMP_DIRS+=("$cfg")

    mkdir -p "$cfg/modules" "$cfg/branding/churros" "$cfg/cache" "$cfg/xdg-config"
    cp "$PREVIEW_DIR/settings.conf" "$cfg/settings.conf"
    cp "$CALAMARES_SRC/modules/"*.conf "$cfg/modules/"
    cp "$CALAMARES_SRC/modules/"*.yaml "$cfg/modules/"
    for preview_conf in "$PREVIEW_DIR"/*.conf; do
        case "$(basename "$preview_conf")" in
            settings.conf) continue ;;
            *) cp "$preview_conf" "$cfg/modules/" ;;
        esac
    done
    cp -a "$branding_src/." "$cfg/branding/churros/"

    qml_src="$(calamares_qml_src)" || die "Calamares QML not found (expected usr/share/calamares/qml in the package)"
    ln -s "$qml_src" "$cfg/qml"

    if [ -n "${CALAMARES_PREFIX:-}" ]; then
        modules_dir="$CALAMARES_PREFIX/usr/lib/calamares/modules"
        [ -d "$modules_dir" ] || die "extracted package has no usr/lib/calamares/modules"
        inject_extracted_modules_search "$cfg/settings.conf" "$modules_dir"
    fi

    python3 - "$cfg/modules/netinstall.conf" "$cfg/modules/netinstall.yaml" <<'PY'
from pathlib import Path
import sys

conf, yaml_path = Path(sys.argv[1]), Path(sys.argv[2]).resolve()
text = conf.read_text(encoding="utf-8")
conf.write_text(
    text.replace(
        "file:///etc/calamares/modules/netinstall.yaml",
        f"file://{yaml_path}",
    ),
    encoding="utf-8",
)
PY

    echo "Calamares preview (UI only)."
    echo "  config : $cfg"
    echo "  binary : $CALAMARES_BIN"
    echo "  No partition page, no polkit, no live timezone/keyboard, no reboot."
    echo "  Install runs sleep. Nothing is written to /etc/calamares."
    echo

    (
        cd "$cfg"
        # Do not pass -X: that would mix in ~/.config/calamares.
        env \
            PATH="$DEV_BIN:$PATH" \
            XDG_CACHE_HOME="$cfg/cache" \
            XDG_CONFIG_HOME="$cfg/xdg-config" \
            "$CALAMARES_BIN" -d -c "$cfg"
    )
}

parse_args() {
    local args=()
    while [ $# -gt 0 ]; do
        case "$1" in
            --live-host)
                LIVE_HOST=1
                shift
                ;;
            -h | --help | help)
                show_help
                exit 0
                ;;
            --)
                shift
                args+=("$@")
                break
                ;;
            -*)
                die "unknown option: $1"
                ;;
            *)
                args+=("$1")
                shift
                ;;
        esac
    done
    if [ "${#args[@]}" -gt 0 ]; then
        set -- "${args[@]}"
    else
        set --
    fi
    TARGET="${1-}"
    shift || true
    TARGET_ARGS=("$@")
}

require_not_root
parse_args "$@"

case "${TARGET:-}" in
    "")
        show_help
        ;;
    doctor)
        run_doctor
        ;;
    welcome)
        run_gtk_crate churros-welcome "${TARGET_ARGS[@]+"${TARGET_ARGS[@]}"}"
        ;;
    tour)
        run_gtk_crate churros-tour "${TARGET_ARGS[@]+"${TARGET_ARGS[@]}"}"
        ;;
    settings)
        run_gtk_crate churros-settings "${TARGET_ARGS[@]+"${TARGET_ARGS[@]}"}"
        ;;
    control-center)
        run_gtk_crate churros-control-center "${TARGET_ARGS[@]+"${TARGET_ARGS[@]}"}"
        ;;
    popup)
        if [ "${#TARGET_ARGS[@]}" -lt 1 ]; then
            die "usage: ./churros apps popup {network|audio|bluetooth|power|brightness|battery}"
        fi
        is_popup "${TARGET_ARGS[0]}" || die "unknown popup '${TARGET_ARGS[0]}'"
        run_gtk_crate churros-popup "${TARGET_ARGS[@]}"
        ;;
    calamares)
        run_calamares
        ;;
    *)
        die "unknown target '${TARGET}'. Try ./churros apps"
        ;;
esac
