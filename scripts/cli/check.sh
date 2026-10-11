#!/usr/bin/env bash
#
# Static checks over the repository. Runs locally (./churros check) and in CI.
# Exits 1 if any check fails. Hygiene notices are reported but never fail.

# No -e here: every check must run so the report is complete.
set -uo pipefail

cd "$(dirname "$0")/../.." || exit 1

# shellcheck source=scripts/lib/host.sh
source scripts/lib/host.sh

# Arquitectura objetivo del port (x86_64 por defecto solo si el perfil arm64 no existe)
TARGET_ARCH="${TARGET_ARCH:-aarch64}"

FAILURES=0
NOTICES=0

section() { printf '\n== %s\n' "$1"; }
pass()    { printf '  ✓ %s\n' "$1"; }
fail()    { printf '  ✗ %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
notice()  { printf '  ! %s\n' "$1"; NOTICES=$((NOTICES + 1)); }

mapfile -t SCRIPTS < <(git ls-files '*.sh' 'churros')

# ------------------------------------------------------------- Bash syntax

section "Bash syntax"

syntax_errors=0
for script in "${SCRIPTS[@]}"; do
    if ! err=$(bash -n "$script" 2>&1); then
        fail "$script: $err"
        syntax_errors=$((syntax_errors + 1))
    fi
done
[ "$syntax_errors" -eq 0 ] && pass "${#SCRIPTS[@]} scripts parse"

# --------------------------------------------------------------- ShellCheck

section "ShellCheck"

if command -v shellcheck >/dev/null 2>&1; then
    if shellcheck -S error "${SCRIPTS[@]}"; then
        pass "no error-level findings"
    else
        fail "shellcheck reported errors"
    fi
    warnings=$(shellcheck -S warning -f gcc "${SCRIPTS[@]}" 2>/dev/null | grep -c warning || true)
    [ "$warnings" -gt 0 ] && notice "$warnings style warnings (non-blocking)"
else
    notice "shellcheck not installed"
fi

# ----------------------------------------------------------- Python syntax

section "Python syntax"

# ast.parse only reads the source: it neither runs it nor writes .pyc files.
if git ls-files '*.py' | python3 -c '
import ast, sys

files = [line.strip() for line in sys.stdin if line.strip()]
broken = 0
for path in files:
    try:
        ast.parse(open(path, encoding="utf-8").read(), filename=path)
    except SyntaxError as exc:
        print(f"    {path}:{exc.lineno}: {exc.msg}")
        broken += 1
print(f"    {len(files) - broken}/{len(files)} files parse")
sys.exit(1 if broken else 0)
'; then
    pass "all Python files parse"
else
    fail "some Python files have syntax errors"
fi

# ---------------------------------------------------------- Package list

section "ISO package list"

# Una lista por edicion (packages.<edicion>.x86_64). Se recorren todas para
# que anadir una edicion no obligue a tocar este script.
for pkg_list in archiso/packages*.x86_64 archiso/packages.aarch64; do
    [ -f "$pkg_list" ] || continue

    dups=$(grep -v '^#' "$pkg_list" | grep -v '^$' | sort | uniq -d)
    if [ -n "$dups" ]; then
        fail "duplicate entries in $pkg_list:"
        # shellcheck disable=SC2086
        printf '      %s\n' $dups
    else
        pass "no duplicates ($pkg_list)"
    fi
done

# ------------------------------------------ archiso profile per architecture

section "archiso profile per architecture"

# profiledef.sh deriva arch, bootmodes, compresion y pacman.<arch>.conf de
# CHURROS_ARCH (build.sh: sudo env CHURROS_ARCH=... mkarchiso). Se carga como
# lo hace mkarchiso (cwd archiso/, file_permissions asociativo) para cada arch.
profile_ok=1
for target in x86_64 aarch64; do
    # shellcheck disable=SC2016
    if ! pv=$(CHURROS_ARCH="$target" bash -c '
        set -eu
        declare -A file_permissions=()
        cd archiso
        . ./profiledef.sh
        printf "%s|%s|%s|%s\n" "$arch" "$pacman_conf" "${bootmodes[*]}" "${airootfs_image_tool_options[*]}"
    ' 2>&1); then
        fail "profiledef.sh does not load with CHURROS_ARCH=$target: $pv"
        profile_ok=0
        continue
    fi
    IFS='|' read -r p_arch p_conf p_boot p_sfs <<< "$pv"
    conf_arch=$(awk -F= '/^[[:space:]]*Architecture[[:space:]]*=/ { gsub(/[[:space:]]/, "", $2); print $2; exit }' \
        "archiso/$p_conf" 2>/dev/null || true)
    if [ "$p_arch" != "$target" ] || [ "$conf_arch" != "$target" ]; then
        fail "$target: profiledef.sh gives arch=$p_arch and archiso/$p_conf declares Architecture=${conf_arch:-?}"
        profile_ok=0
    fi
    if [ "$target" != x86_64 ] && [[ " $p_boot " == *" bios."* ]]; then
        fail "$target: BIOS boot modes are x86-only"
        profile_ok=0
    fi
    # uefi.systemd-boot y uefi-x64 también escriben EFI/BOOT/BOOTAA64.EFI.
    # mkarchiso ya nombra ese binario vía uefi_arch[aarch64]=AA64.
    if [ "$target" = aarch64 ] && [ "$p_boot" != "uefi.grub" ]; then
        fail "$target: boot modes must be only uefi.grub (got: $p_boot)"
        profile_ok=0
    fi
    if [ "$target" = x86_64 ] && [ "$p_boot" != "bios.syslinux uefi.grub" ]; then
        fail "$target: boot modes must stay bios.syslinux and uefi.grub (got: $p_boot)"
        profile_ok=0
    fi
    # -Xbcj solo existe para xz: mksquashfs sale con error si va con zstd.
    if [[ " $p_sfs " == *" -Xbcj "* && " $p_sfs " != *" -comp xz "* ]]; then
        fail "$target: -Xbcj requires -comp xz in airootfs_image_tool_options"
        profile_ok=0
    fi
    # apply-calamares.sh copia modules/<arch>/*.conf encima de los comunes.
    unpackfs=installer/calamares/modules/unpackfs.conf
    [ -f "installer/calamares/modules/$target/unpackfs.conf" ] &&
        unpackfs="installer/calamares/modules/$target/unpackfs.conf"
    if ! grep -q "bootmnt/churros/$target/airootfs.sfs" "$unpackfs"; then
        fail "$target: $unpackfs does not unpack churros/$target/airootfs.sfs"
        profile_ok=0
    fi
    # pacstrap usa este conf. Bajo qemu-user, pacman 7 falla en seccomp si
    # falta DisableSandboxSyscalls (EINVAL 22) aunque Landlock esté apagado.
    if [ "$target" = aarch64 ]; then
        for sandbox_opt in DisableSandbox DisableSandboxFilesystem DisableSandboxSyscalls; do
            if ! grep -qx "$sandbox_opt" "archiso/$p_conf"; then
                fail "$target: archiso/$p_conf is missing $sandbox_opt (pacman sandbox breaks under qemu-user)"
                profile_ok=0
            fi
        done
    fi
done
[ "$profile_ok" -eq 1 ] && pass "x86_64 and aarch64 get their own pacman.conf, boot modes, squashfs options and unpackfs source"

# -------------------------------------------- Defaults vs skel (coherencia)

# /usr/share/churros/defaults lo usa churros-settings para "restaurar valores
# por defecto": copia esos ficheros sobre ~/.config. Si divergen de
# /etc/skel/.config, que es lo que recibe una instalacion nueva, el usuario
# recibe otra configuracion distinta cada vez que restaura. Pasa a ser fallo de
# CI en vez de sorpresa.
DEFAULTS_DIR="archiso/airootfs/usr/share/churros/defaults"
SKEL_DIR="archiso/airootfs/etc/skel/.config"
defaults_drift=0

if [ -d "$DEFAULTS_DIR" ]; then
    while IFS= read -r def_file; do
        rel="${def_file#"$DEFAULTS_DIR"/}"
        skel_file="$SKEL_DIR/$rel"
        if [ ! -f "$skel_file" ]; then
            fail "defaults/$rel no tiene equivalente en el skel"
            defaults_drift=$((defaults_drift + 1))
        elif ! cmp -s "$def_file" "$skel_file"; then
            fail "defaults/$rel difiere del skel (restaurar valores por defecto daria otra config)"
            defaults_drift=$((defaults_drift + 1))
        fi
    done < <(find "$DEFAULTS_DIR" -type f | sort)

    if [ "$defaults_drift" -eq 0 ]; then
        pass "defaults sincronizado con el skel ($(find "$DEFAULTS_DIR" -type f | wc -l) ficheros)"
    fi
fi

# ------------------------------------------------------- Installer por edicion

# Anadir una edicion a medias (lista de paquetes pero sin lanzador de sesion,
# o al reves) deja instalaciones que no arrancan. Se comprueba que cada lista
# de paquetes tenga su edicion cableada en los cuatro sitios que la necesitan:
# build.sh, stamp-os-release.sh, edition-session.sh (sesion de greetd del
# sistema instalado) y el dispatcher.

EDITION_SESSION=archiso/airootfs/usr/share/churros/scripts/edition-session.sh

# Brazo de un case. Se admiten los brazos combinados (xfce|server).
arm_pattern() {
    printf '^[[:space:]][^#]*\\b%s\\b[|)]' "$1"
}

list_editions() {
    for list in archiso/packages*.x86_64; do
        [ -f "$list" ] || continue
        base="${list##*/}"
        base="${base#packages.}"
        # packages.${TARGET_ARCH} es el perfil por defecto y es la edicion niri.
        if [ "$base" = "x86_64" ]; then
            echo "niri"
        else
            echo "${base%.x86_64}"
        fi
    done
}

for ed in $(list_editions); do
    problems=""

    # En build.sh el brazo que importa es el que asigna el comando de sesion;
    # el case del nombre que ve el slideshow tambien menciona la edicion y no
    # cuenta.
    if ! grep -qE "$(arm_pattern "$ed")[^#]*SESSION_CMD=" scripts/cli/build.sh; then
        problems="$problems build.sh-sin-brazo-de-sesion"
    fi

    if [ "$ed" = "niri" ]; then
        # niri es el valor por defecto: en estos dos scripts no aparece con su
        # nombre, sino como el brazo * del case o como valor inicial.
        if ! grep -qE '^[[:space:]]*\*\)' branding/stamp-os-release.sh; then
            problems="$problems os-release-sin-variante"
        fi
        if ! grep -qE '\*\)|churros-niri-session' "$EDITION_SESSION"; then
            problems="$problems greetd-sin-edicion"
        fi
    else
        if ! grep -qE "$(arm_pattern "$ed")" branding/stamp-os-release.sh; then
            problems="$problems os-release-sin-variante"
        fi
        if ! grep -qE "$(arm_pattern "$ed")" "$EDITION_SESSION"; then
            problems="$problems greetd-sin-edicion"
        fi
    fi

    if [ -z "$problems" ]; then
        pass "edicion $ed cableada en el instalador"
    else
        fail "edicion $ed incompleta:$problems"
    fi
done

# La tabla edicion -> sesion solo vive en edition-session.sh: la instalacion
# (configure-greetd-session) y el autologin de Ajustes
# (churros-write-root-config) la cargan en vez de llevar una copia propia.
if grep -q 'edition-session.sh' archiso/airootfs/usr/share/churros/scripts/configure-greetd-session &&
   grep -q 'edition-session.sh' archiso/airootfs/usr/local/bin/churros-write-root-config; then
    pass "configure-greetd-session y churros-write-root-config comparten edition-session.sh"
else
    fail "configure-greetd-session o churros-write-root-config no cargan edition-session.sh"
fi

# El instalador no puede quedarse en una sola edicion: el ejecutable que
# declara Calamares tiene que resolver la edicion en runtime.
if grep -q 'executable: "churros-xsession"' installer/calamares/modules/displaymanager.conf &&
   [ -x archiso/airootfs/usr/local/bin/churros-xsession ]; then
    pass "el instalador resuelve la edicion en runtime (churros-xsession)"
else
    fail "displaymanager.conf sigue con un ejecutable de una sola edicion, o falta churros-xsession"
fi

# ------------------------------------------------------- Shared resolvers

mapfile -t PACKAGES < <(grep -v '^#' archiso/packages.${TARGET_ARCH} | grep -v '^$')

# AUR extras built into archiso/packages/ by scripts/build-aur.sh
mapfile -t LOCAL_AUR < <(
    grep -E '^[[:space:]]*build_aur[[:space:]]+' scripts/build-aur.sh |
        awk '{print $2}'
)

# Binary names do not always match package names: awww-daemon ships in 'awww',
# so a substring match counts as a hit.
# Rust apps (churros-*) are compiled at build time by scripts/build-rust.sh and
# are not present in a clean checkout, so a crate with deploy = true resolves.
# Calamares and AUR extras live in archiso/packages/ after the ISO build scripts.
command_exists() {
    local command=$1 package crate_toml
    [ -e "archiso/airootfs/usr/bin/$command" ] && return 0

    for crate_toml in rust/*/Cargo.toml; do
        [ -f "$crate_toml" ] || continue
        grep -q '^deploy = true$' "$crate_toml" || continue
        grep -q "^name = \"$command\"$" "$crate_toml" && return 0
    done

    if [ "$command" = calamares ]; then
        return 0
    fi
    for package in "${LOCAL_AUR[@]}"; do
        [ "$command" = "$package" ] && return 0
    done

    for package in "${PACKAGES[@]}"; do
        # Exact name always counts (short packages like mpv).
        [ "$command" = "$package" ] && return 0
        # Substring only for longer names (awww-daemon ⊆ awww) to avoid
        # false hits from tiny tokens.
        [ "${#package}" -ge 4 ] || continue
        [[ $command == *"$package"* ]] && return 0
    done
    return 1
}

# ------------------------------------------------------------ Niri autostart

section "Commands referenced by Niri"

NIRI_CONFIG=archiso/airootfs/etc/skel/.config/niri/config.kdl

mapfile -t COMMANDS < <(
    grep -oE '(spawn|spawn-at-startup) "[^"]+"' "$NIRI_CONFIG" |
        sed -E 's/.*"([^"]+)"/\1/' | sort -u
)

missing=0
for command in "${COMMANDS[@]}"; do
    if ! command_exists "$command"; then
        fail "'$command' is spawned by Niri but is neither in usr/bin nor in packages.${TARGET_ARCH}"
        missing=$((missing + 1))
    fi
done
[ "$missing" -eq 0 ] && pass "${#COMMANDS[@]} commands resolve"

# ------------------------------------------------------- Noctalia integration

section "Noctalia shell integration"

# The Niri session must not stack swaybg under Noctalia's wallpaper, and the
# launcher / control center binds have to call the Noctalia 5.2.1 IPC
# (`noctalia msg panel-toggle <id>`). spawn-sh keeps the whole command in one
# string so churros-settings can round-trip it.
if grep -Eq '^[[:space:]]*spawn-at-startup[[:space:]]+"swaybg"' "$NIRI_CONFIG"; then
    fail "Niri autostart still launches swaybg (Noctalia owns the wallpaper)"
else
    pass "Niri autostart leaves the wallpaper to Noctalia"
fi

if grep -Fq 'spawn-sh "noctalia msg panel-toggle launcher"' "$NIRI_CONFIG" &&
   grep -Fq 'hotkey-overlay-title="Abrir el lanzador"' "$NIRI_CONFIG"; then
    pass "Mod+Space opens the Noctalia launcher and is listed in the hotkey overlay"
else
    fail "Mod+Space does not open the Noctalia launcher via panel-toggle"
fi

if grep -Fq 'spawn "fuzzel"' "$NIRI_CONFIG" &&
   grep -Fq 'hotkey-overlay-title="Lanzador alternativo (Fuzzel)"' "$NIRI_CONFIG"; then
    pass "Fuzzel stays available as the Mod+Shift+Space fallback"
else
    fail "Fuzzel fallback bind is missing"
fi

if grep -Fq 'spawn-sh "noctalia msg panel-toggle control-center"' "$NIRI_CONFIG" &&
   grep -Fq 'hotkey-overlay-title="Abrir el centro de control"' "$NIRI_CONFIG"; then
    pass "Mod+C opens the Noctalia control center and is listed in the hotkey overlay"
else
    fail "Mod+C does not open the Noctalia control center via panel-toggle"
fi

if grep -vE '^[[:space:]]*//' "$NIRI_CONFIG" | grep -Eq 'churros-popup|churros-control-center'; then
    fail "Niri still binds churros-popup or churros-control-center (Noctalia panels cover them)"
else
    pass "churros-popup and churros-control-center are not bound in Niri"
fi

if grep -Eiq 'waybar' "$NIRI_CONFIG"; then
    fail "Niri config mentions Waybar; this session does not run it"
else
    pass "Niri config does not mention Waybar"
fi

if grep -Eq '^[[:space:]]*hide-not-bound[[:space:]]+true[[:space:]]*$' "$NIRI_CONFIG"; then
    pass "hotkey overlay hides actions that are not bound"
else
    fail "hotkey-overlay hide-not-bound is not set (unbound actions stay in English)"
fi

overlay_titles=(
    "Cerrar la ventana"
    "Salir de Niri"
    "Maximizar la columna"
    "Pantalla completa"
    "Alternar el bloqueo de atajos"
    "Mostrar los atajos"
    "Abrir la vista general"
    "Cambiar el ancho de columna"
    "Alternar ventana flotante"
    "Cambiar entre flotante y mosaico"
    "Capturar la pantalla"
    "Capturar toda la pantalla"
    "Capturar la ventana"
    "Enfocar la columna izquierda"
    "Enfocar la columna derecha"
    "Mover la columna a la izquierda"
    "Mover la columna a la derecha"
)
missing_titles=0
for title in "${overlay_titles[@]}"; do
    if ! grep -Fq "hotkey-overlay-title=\"${title}\"" "$NIRI_CONFIG"; then
        fail "hotkey overlay is missing the Spanish title: ${title}"
        missing_titles=$((missing_titles + 1))
    fi
done
if [ "$missing_titles" -eq 0 ]; then
    pass "hotkey overlay entries that Niri shows have a Spanish title"
fi

if grep -Fq 'noctalia::uses_waybar()' rust/preferences/src/window.rs &&
   grep -Fq 'noctalia::uses_mako()' rust/preferences/src/window.rs &&
   grep -Fq 'noctalia::uses_waybar()' rust/preferences/src/pages/appearance.rs &&
   grep -Fq 'noctalia::uses_mako()' rust/preferences/src/pages/appearance.rs; then
    pass "Waybar and Mako settings pages follow the running shell"
else
    fail "Waybar or Mako settings are still shown for every Niri edition"
fi

if grep -Fq '"dynamic_colors": false' rust/preferences/src/services/settings.rs &&
   grep -Fq 'get_bool("theme.dynamic_colors", false)' rust/preferences/src/services/pywal.rs &&
   grep -Fq 'get_bool("theme.dynamic_colors", false)' rust/preferences/src/pages/appearance.rs &&
   ! grep -Fq '"dynamic_colors": true' rust/preferences/src/services/settings.rs &&
   ! grep -Fq '"dynamic_colors": true' rust/preferences/src/services/backup_service.rs; then
    pass "dynamic colors default off so pywal does not replace the ChurrOS accent"
else
    fail "theme.dynamic_colors still defaults to true"
fi

if python3 - "$NIRI_CONFIG" <<'PY'
import json
import sys
import tomllib
from pathlib import Path

errors = 0

def fail(msg: str) -> None:
    global errors
    errors += 1
    print(f"    {msg}")

def contrast(a: str, b: str) -> float:
    def channel(h: str, i: int) -> float:
        c = int(h[i:i + 2], 16) / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h: str) -> float:
        h = h.lstrip("#")
        return 0.2126 * channel(h, 0) + 0.7152 * channel(h, 2) + 0.0722 * channel(h, 4)

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)

skel = Path("archiso/airootfs/etc/skel/.config/noctalia")
config = tomllib.loads((skel / "config.toml").read_text(encoding="utf-8"))
theme = config["theme"]
shell = config["shell"]
if theme.get("source") != "custom" or theme.get("custom_palette") != "ChurrOS":
    fail("Noctalia theme is not the ChurrOS custom palette")
if theme.get("shell_mode") != "follow":
    fail("shell_mode must follow mode so churros-settings switches the shell")
if theme.get("mode") not in {"dark", "light"}:
    fail("theme.mode must be dark or light")
if shell.get("font_family") != "Inter":
    fail("Noctalia font_family is not Inter")
radius = shell.get("corner_radius_scale")
if not isinstance(radius, (int, float)) or not 0 <= float(radius) <= 2:
    fail("corner_radius_scale is outside the Noctalia 5.2.1 range 0..2")
scale = config.get("accessibility", {}).get("ui_scale")
if not isinstance(scale, (int, float)) or not 0.5 <= float(scale) <= 2.5:
    fail("accessibility.ui_scale is outside the Noctalia 5.2.1 range 0.5..2.5")
if config.get("shell", {}).get("launcher", {}).get("compact") is not False:
    fail("launcher compact should stay off (comfortable density)")
panel_mode = config.get("shell", {}).get("panel", {}).get("transparency_mode")
if panel_mode != "soft":
    fail(
        f"panel transparency_mode is {panel_mode!r}; "
        "glass drops the floating panel to 55% and dark mode turns muddy over a light wallpaper"
    )
wallpaper = config.get("wallpaper", {})
default = wallpaper.get("default", {}).get("path")
if default != "/usr/share/churros/wallpapers/default.png":
    fail(f"wallpaper.default.path is {default!r}")
elif not Path("archiso/airootfs" + default).is_file():
    fail("default wallpaper file is missing from the ISO root")
if wallpaper.get("fill_mode") != "crop":
    fail("wallpaper fill_mode should be crop (same coverage as the old swaybg -m fill)")

palette_path = skel / "palettes" / "ChurrOS.json"
palette = json.loads(palette_path.read_text(encoding="utf-8"))
required = [
    "mPrimary", "mOnPrimary", "mSecondary", "mOnSecondary", "mTertiary", "mOnTertiary",
    "mError", "mOnError", "mSurface", "mOnSurface", "mSurfaceVariant", "mOnSurfaceVariant",
    "mOutline", "mShadow", "mHover", "mOnHover",
]
for mode in ("dark", "light"):
    colors = palette.get(mode)
    if not isinstance(colors, dict):
        fail(f"palette is missing the {mode} variant")
        continue
    missing = [key for key in required if not isinstance(colors.get(key), str)]
    if missing:
        fail(f"{mode} palette is missing {', '.join(missing)}")
        continue
    pairs = (
        ("mOnSurface", "mSurface", 4.5),
        ("mOnSurfaceVariant", "mSurfaceVariant", 4.5),
        ("mOnPrimary", "mPrimary", 4.5),
        ("mOnSecondary", "mSecondary", 4.5),
        ("mOnHover", "mHover", 4.5),
        ("mOnError", "mError", 4.5),
    )
    for fg, bg, minimum in pairs:
        ratio = contrast(colors[fg], colors[bg])
        if ratio < minimum:
            fail(f"{mode} {fg} on {bg} contrast {ratio:.2f} is below {minimum}")

apply = Path("archiso/airootfs/usr/bin/churros-apply-wallpaper").read_text(encoding="utf-8")
apply_fn = apply.split("apply() {", 1)[-1]
noctalia_at = apply_fn.find("if noctalia_running")
sway_at = apply_fn.find("apply_swaybg")
if "for attempt in 1 2 3" not in apply or "noctalia msg wallpaper-set" not in apply:
    fail("churros-apply-wallpaper must retry noctalia msg wallpaper-set three times")
elif noctalia_at < 0 or sway_at < 0 or noctalia_at > sway_at:
    fail("swaybg must stay behind the Noctalia guard in apply()")
elif "return" not in apply_fn[noctalia_at:sway_at]:
    fail("a running Noctalia must return before swaybg, even when wallpaper-set fails")

wallpaper_rs = Path("rust/preferences/src/services/wallpaper.rs").read_text(encoding="utf-8")
noctalia_rs = wallpaper_rs.find("running_shells().noctalia")
sway_rs = wallpaper_rs.find('"-m", "fill"')
if noctalia_rs < 0 or sway_rs < 0 or noctalia_rs > sway_rs:
    fail("wallpaper.rs must notice a running Noctalia before starting swaybg")
elif "return apply_with_noctalia" not in wallpaper_rs[noctalia_rs:sway_rs]:
    fail("wallpaper.rs must return without swaybg when Noctalia is running")

for pkg_list in ("archiso/packages.x86_64", "archiso/packages.aarch64"):
    names = [
        line.strip()
        for line in Path(pkg_list).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    if "inter-font" not in names:
        fail(f"{pkg_list} does not install inter-font (Noctalia font_family = Inter)")
    if "noctalia" not in names:
        fail(f"{pkg_list} does not install noctalia")

sys.exit(1 if errors else 0)
PY
then
    pass "Noctalia config, palette, wallpaper and Inter font check out"
else
    fail "Noctalia integration check failed"
fi

if wallpaper_out=$(bash scripts/test-apply-wallpaper.sh 2>&1); then
    pass "Noctalia en marcha no arranca swaybg (scripts/test-apply-wallpaper.sh)"
else
    fail "scripts/test-apply-wallpaper.sh"
    printf '%s\n' "$wallpaper_out" | sed 's/^/    /'
fi

# -------------------------------------------------- Niri Xwayland integration

section "Niri Xwayland integration"

# packages.${TARGET_ARCH} is the default Niri profile; build.sh substitutes an edition-
# specific list for XFCE, KDE, and Server builds. Keep the satellite scoped to Niri.
XWAYLAND_SATELLITE="xwayland-satellite"
if grep -Fxq "$XWAYLAND_SATELLITE" archiso/packages.${TARGET_ARCH}; then
    pass "xwayland-satellite is included in the Niri profile"
else
    fail "xwayland-satellite is missing from archiso/packages.${TARGET_ARCH} (Niri)"
fi

other_profile_satellite=0
for pkg_list in archiso/packages.*.x86_64; do
    [ -f "$pkg_list" ] || continue
    if grep -Fxq "$XWAYLAND_SATELLITE" "$pkg_list"; then
        fail "$XWAYLAND_SATELLITE must stay out of alternate profile $pkg_list"
        other_profile_satellite=$((other_profile_satellite + 1))
    fi
done
[ "$other_profile_satellite" -eq 0 ] && pass "xwayland-satellite is excluded from alternate profiles"

# Niri owns DISPLAY when its automatic Xwayland integration is enabled. The
# portal startup helper propagates that value to systemd and D-Bus activation.
NIRI_SESSION_WRAPPER="archiso/airootfs/usr/bin/churros-niri-session"
NIRI_PORTAL_HELPER="archiso/airootfs/usr/bin/churros-portal-start"
if grep -Eq '^[[:space:]]*(DISPLAY[[:space:]]+|spawn(-at-startup)?[[:space:]].*xwayland-satellite)' "$NIRI_CONFIG"; then
    fail "Niri config overrides DISPLAY or starts xwayland-satellite manually"
else
    pass "Niri config leaves DISPLAY and satellite startup to Niri"
fi

if grep -Eq '(^|[[:space:]])(unset[[:space:]]+DISPLAY|export[[:space:]]+DISPLAY=|DISPLAY=)' "$NIRI_SESSION_WRAPPER"; then
    fail "Niri session wrapper overrides DISPLAY"
else
    pass "Niri session wrapper preserves Niri's DISPLAY"
fi

if grep -Eq '^[[:space:]]*spawn-at-startup[[:space:]]+"churros-portal-start"[[:space:]]*$' "$NIRI_CONFIG" &&
   grep -A8 -F 'systemctl --user import-environment' "$NIRI_PORTAL_HELPER" |
       grep -qE '^[[:space:]]+DISPLAY([[:space:]]|$)' &&
   grep -A8 -F 'dbus-update-activation-environment --systemd' "$NIRI_PORTAL_HELPER" |
       grep -qE '^[[:space:]]+DISPLAY([[:space:]]|$)'; then
    pass "Niri startup imports DISPLAY into systemd and D-Bus environments"
else
    fail "Niri startup does not propagate DISPLAY to systemd and D-Bus"
fi

# ------------------------------------------------------- Desktop entries

section "Desktop Exec / TryExec"

DESKTOP_DIR=archiso/airootfs/usr/share/applications
desktop_missing=0
desktop_path_missing=0
desktop_count=0

# Prefer TryExec when present; otherwise first token of Exec (field codes stripped).
desktop_command() {
    local file=$1 line
    line=$(grep -E '^TryExec=' "$file" | head -1 | cut -d= -f2- || true)
    if [ -n "$line" ]; then
        printf '%s\n' "$line"
        return
    fi
    line=$(grep -E '^Exec=' "$file" | head -1 | cut -d= -f2- || true)
    # Desktop Entry field codes: %f %F %u %U %i %c %k …
    line=$(printf '%s' "$line" | sed -E 's/ %[[:alpha:]]//g')
    printf '%s\n' "${line%% *}"
}

for desktop in "$DESKTOP_DIR"/*.desktop; do
    [ -f "$desktop" ] || continue
    desktop_count=$((desktop_count + 1))
    base=$(basename "$desktop")

    cmd=$(desktop_command "$desktop")
    if [ -z "$cmd" ]; then
        fail "$base: no Exec= or TryExec="
        desktop_missing=$((desktop_missing + 1))
        continue
    fi
    if ! command_exists "$cmd"; then
        fail "$base: '$cmd' does not resolve (usr/bin, deployable crate, packages.${TARGET_ARCH}, or local build)"
        desktop_missing=$((desktop_missing + 1))
    fi

    # Absolute paths in Exec must exist under airootfs (catches stale python main.py paths).
    exec_line=$(grep -E '^Exec=' "$desktop" | head -1 | cut -d= -f2- || true)
    # shellcheck disable=SC2086
    for token in $exec_line; do
        [[ $token == /* ]] || continue
        token=${token#\"}
        token=${token%\"}
        if [ ! -e "archiso/airootfs$token" ]; then
            fail "$base: Exec path '$token' missing under archiso/airootfs"
            desktop_path_missing=$((desktop_path_missing + 1))
        fi
    done
done

if [ "$desktop_missing" -eq 0 ] && [ "$desktop_path_missing" -eq 0 ]; then
    pass "$desktop_count desktop entries resolve"
fi

# ---------------------------------------------------- Calamares sequence

section "Calamares exec order"

SETTINGS=installer/calamares/settings.conf
MODULES_DIR=installer/calamares/modules

if [ ! -f "$SETTINGS" ]; then
    fail "$SETTINGS missing"
else
    mapfile -t EXEC_STEPS < <(
        awk '
            /^  - exec:/{ in_exec=1; next }
            in_exec && /^  - /{ exit }
            in_exec && /^      - /{
                sub(/^[[:space:]]+-[[:space:]]+/, "")
                print
            }
        ' "$SETTINGS"
    )

    step_index() {
        local needle=$1 i
        for i in "${!EXEC_STEPS[@]}"; do
            if [ "${EXEC_STEPS[$i]}" = "$needle" ]; then
                printf '%s\n' "$i"
                return 0
            fi
        done
        printf '%s\n' '-1'
        return 1
    }

    pacman_i=$(step_index 'shellprocess@pacman-init' || true)
    fixboot_i=$(step_index 'shellprocess@fix-boot' || true)
    post_i=$(step_index 'shellprocess@post-install' || true)
    umount_i=$(step_index 'umount' || true)
    mount_i=$(step_index 'mount' || true)
    bootnocow_i=$(step_index 'shellprocess@boot-nocow' || true)
    unpackfs_i=$(step_index 'unpackfs' || true)

    order_ok=1
    for pair in \
        "shellprocess@pacman-init:$pacman_i" \
        "shellprocess@fix-boot:$fixboot_i" \
        "shellprocess@post-install:$post_i" \
        "umount:$umount_i" \
        "mount:$mount_i" \
        "shellprocess@boot-nocow:$bootnocow_i" \
        "unpackfs:$unpackfs_i"
    do
        name=${pair%%:*}
        idx=${pair##*:}
        if [ "$idx" -lt 0 ]; then
            fail "exec sequence missing '$name'"
            order_ok=0
        fi
    done

    if [ "$order_ok" -eq 1 ]; then
        if [ "$pacman_i" -ge "$fixboot_i" ]; then
            fail "shellprocess@pacman-init must run before shellprocess@fix-boot"
            order_ok=0
        fi
        if [ "$((post_i + 1))" -ne "$umount_i" ]; then
            fail "shellprocess@post-install must be the last step before umount"
            order_ok=0
        fi
        if [ "$mount_i" -ge "$bootnocow_i" ]; then
            fail "shellprocess@boot-nocow must run after mount"
            order_ok=0
        fi
        if [ "$bootnocow_i" -ge "$unpackfs_i" ]; then
            fail "shellprocess@boot-nocow must run before unpackfs"
            order_ok=0
        fi
    fi

    [ "$order_ok" -eq 1 ] && pass "boot-nocow after mount; pacman-init → fix-boot; post-install before umount"
fi

# --------------------------------------------- Calamares shellprocess confs

section "Calamares shellprocess configs"

if [ ! -f "$SETTINGS" ]; then
    fail "cannot check instances without $SETTINGS"
else
    mapfile -t INSTANCE_IDS < <(
        awk '
            /^instances:/{ in_i=1; next }
            in_i && /^[a-zA-Z]/{ exit }
            in_i && /^[[:space:]]+- id:/{
                sub(/^[[:space:]]+- id:[[:space:]]*/, "")
                print
            }
        ' "$SETTINGS"
    )
    mapfile -t INSTANCE_CONFIGS < <(
        awk '
            /^instances:/{ in_i=1; next }
            in_i && /^[a-zA-Z]/{ exit }
            in_i && /^[[:space:]]+config:/{
                sub(/^[[:space:]]+config:[[:space:]]*/, "")
                print
            }
        ' "$SETTINGS"
    )

    conf_ok=1
    if [ "${#INSTANCE_IDS[@]}" -eq 0 ]; then
        fail "no shellprocess instances declared"
        conf_ok=0
    fi
    if [ "${#INSTANCE_IDS[@]}" -ne "${#INSTANCE_CONFIGS[@]}" ]; then
        fail "instances: id/config count mismatch (${#INSTANCE_IDS[@]} ids, ${#INSTANCE_CONFIGS[@]} configs)"
        conf_ok=0
    fi

    i=0
    while [ "$i" -lt "${#INSTANCE_CONFIGS[@]}" ]; do
        conf=${INSTANCE_CONFIGS[$i]}
        if [ ! -f "$MODULES_DIR/$conf" ]; then
            fail "instance '${INSTANCE_IDS[$i]:-?}' config missing: $MODULES_DIR/$conf"
            conf_ok=0
        fi
        i=$((i + 1))
    done

    # Every shellprocess@id in the exec sequence must have a matching instance id.
    for step in "${EXEC_STEPS[@]+"${EXEC_STEPS[@]}"}"; do
        case "$step" in
            shellprocess@*)
                id=${step#shellprocess@}
                found=0
                for known in "${INSTANCE_IDS[@]}"; do
                    if [ "$known" = "$id" ]; then
                        found=1
                        break
                    fi
                done
                if [ "$found" -eq 0 ]; then
                    fail "exec references shellprocess@$id but no matching instances id"
                    conf_ok=0
                fi
                ;;
        esac
    done

    [ "$conf_ok" -eq 1 ] && pass "${#INSTANCE_CONFIGS[@]} shellprocess configs present and referenced"
fi

# Calamares reads defaultFileSystemType (capital S). The other spelling is ignored and ext4 is used.
PARTITION_CONF=installer/calamares/modules/partition.conf
if [ -f "$PARTITION_CONF" ]; then
    if grep -qE '^[[:space:]]*defaultFilesystemType:' "$PARTITION_CONF"; then
        fail "$PARTITION_CONF uses defaultFilesystemType (ignored); need defaultFileSystemType"
    elif grep -qE '^[[:space:]]*defaultFileSystemType:' "$PARTITION_CONF"; then
        pass "partition.conf defaultFileSystemType is the key Calamares reads"
    else
        notice "$PARTITION_CONF has no defaultFileSystemType (Calamares falls back to ext4)"
    fi
fi

# GRUB gfxmenu rejects unknown global properties and unknown + components
# (install then fails to boot the kernel *and* prints theme.txt errors).
# Styled-box pixmaps are a filename pattern with '*', not a + pixmap_style block.
# /boot on btrfs+zstd is unreadable unless images are rewritten into +C inodes.
GRUB_THEME_TXT=branding/grub-theme/theme.txt
if [ -f "$GRUB_THEME_TXT" ]; then
    if grep -qE '^[[:space:]]*title-align:' "$GRUB_THEME_TXT"; then
        fail "$GRUB_THEME_TXT: title-align is not a GRUB gfxmenu property"
    elif grep -qE 'selected_item_pixmap_style_(left|right)' "$GRUB_THEME_TXT"; then
        fail "$GRUB_THEME_TXT: selected_item_pixmap_style_left/right are not GRUB properties"
    elif grep -qE '^\+[[:space:]]*pixmap_style\b' "$GRUB_THEME_TXT"; then
        fail "$GRUB_THEME_TXT: + pixmap_style is not a GRUB gfxmenu component"
    else
        pass "GRUB theme.txt uses only gfxmenu global properties"
    fi

    unknown_comp=0
    while IFS= read -r comp; do
        case "$comp" in
            boot_menu|label|image|hbox|vbox|canvas|circular_progress|progress_bar) ;;
            *)
                fail "$GRUB_THEME_TXT: unknown GRUB component + $comp"
                unknown_comp=$((unknown_comp + 1))
                ;;
        esac
    done < <(grep -E '^\+[[:space:]]+[A-Za-z0-9_]+' "$GRUB_THEME_TXT" \
        | sed -E 's/^\+[[:space:]]+([A-Za-z0-9_]+).*/\1/')
    [ "$unknown_comp" -eq 0 ] && pass "GRUB theme.txt components are gfxmenu types"

    style=$(grep -E '^[[:space:]]*selected_item_pixmap_style[[:space:]]*=' "$GRUB_THEME_TXT" \
        | sed -E 's/.*=[[:space:]]*"([^"]+)".*/\1/' | tail -n1)
    if [ -z "$style" ]; then
        pass "GRUB theme.txt has no selected_item_pixmap_style"
    elif [[ "$style" != *'*'* ]]; then
        fail "$GRUB_THEME_TXT: selected_item_pixmap_style must be a styled-box pattern (e.g. select_*.png), not '$style'"
    else
        center=${style/\*/c}
        if [ ! -f "branding/grub-theme/$center" ]; then
            fail "branding/grub-theme/$center missing (GRUB styled box center slice)"
        else
            pass "GRUB selected_item_pixmap_style uses $style ($center present)"
        fi
    fi

    spaced=0
    for f in branding/grub-theme/*; do
        [ -e "$f" ] || continue
        base=$(basename "$f")
        if [[ "$base" == *' '* ]]; then
            fail "branding/grub-theme/$base: GRUB cannot open filenames with spaces"
            spaced=$((spaced + 1))
        fi
    done
    [ "$spaced" -eq 0 ] && pass "GRUB theme filenames have no spaces"

    if grep -qE '(title-font|terminal-font|[[:space:]]font[[:space:]]*=|[[:space:]]item_font|[[:space:]]selected_item_font).*\.pf2' "$GRUB_THEME_TXT"; then
        fail "$GRUB_THEME_TXT: font properties must use the PFF2 name, not the .pf2 filename"
    else
        pass "GRUB theme.txt font properties use font names, not filenames"
    fi

    if grep -qE '%[[:space:]]+[+-]|[+-][[:space:]]+[0-9]' "$GRUB_THEME_TXT"; then
        fail "$GRUB_THEME_TXT: position expressions must be 50%-260 (no spaces; grub_strtoull fails)"
    else
        pass "GRUB theme.txt position expressions have no spaces"
    fi
fi

BOOT_GRUB_SCRIPT=archiso/airootfs/usr/share/churros/scripts/make-boot-grub-readable
GRUB_THEME_CONF=installer/calamares/modules/shellprocess-grub-theme.conf
BOOT_GRUB_HOOK=archiso/airootfs/etc/pacman.d/hooks/91-churros-boot-grub-readable.hook
if [ ! -f "$BOOT_GRUB_SCRIPT" ]; then
    fail "$BOOT_GRUB_SCRIPT missing (GRUB premature EOF on btrfs zstd /boot)"
elif [ ! -f "$GRUB_THEME_CONF" ] || ! grep -q 'make-boot-grub-readable' "$GRUB_THEME_CONF"; then
    fail "$GRUB_THEME_CONF does not run make-boot-grub-readable after grub-mkconfig"
elif ! grep -q 'conv=fsync' "$BOOT_GRUB_SCRIPT" || grep -qE 'cp -a --' "$BOOT_GRUB_SCRIPT"; then
    fail "$BOOT_GRUB_SCRIPT must full-copy into a +C inode (cp -a reflinks zstd extents on btrfs)"
elif [ ! -f "$BOOT_GRUB_HOOK" ]; then
    fail "$BOOT_GRUB_HOOK missing (kernel updates would rewrite compressed /boot images)"
elif grep -q 'remove from airootfs' "$BOOT_GRUB_HOOK"; then
    fail "$BOOT_GRUB_HOOK would be deleted by the ISO-only hook cleaner"
elif grep -qE 'Type[[:space:]]*=[[:space:]]*Package' "$BOOT_GRUB_HOOK" \
    && grep -qE 'Type[[:space:]]*=[[:space:]]*Path' "$BOOT_GRUB_HOOK" \
    && [ "$(grep -c '^\[Trigger\]' "$BOOT_GRUB_HOOK")" -lt 2 ]; then
    fail "$BOOT_GRUB_HOOK mixes Path and Package Type in one Trigger (pacman applies the last Type to every Target)"
else
    pass "GRUB btrfs /boot rewrite is wired (install + pacman hook)"
fi

# linux-aarch64 instala /boot/Image. mkarchiso y grub-mkconfig buscan vmlinuz-*.
PUBLISH_KERNEL=archiso/airootfs/usr/share/churros/scripts/publish-aarch64-kernel
publish_ok=1
if [ ! -x "$PUBLISH_KERNEL" ]; then
    fail "$PUBLISH_KERNEL missing or not executable"
    publish_ok=0
fi
if ! grep -q 'publish-aarch64-kernel --require' branding/customize_airootfs.sh \
    || ! grep -q 'publish-aarch64-kernel --require' installer/calamares/modules/aarch64/shellprocess-fixboot.conf \
    || ! grep -q 'publish-aarch64-kernel' "$BOOT_GRUB_SCRIPT" \
    || ! grep -q 'boot/Image' "$BOOT_GRUB_HOOK" \
    || ! grep -q 'initramfs-linux-aarch64.img' installer/calamares/modules/aarch64/shellprocess-fixboot.conf \
    || ! grep -q 'vmlinuz-linux-aarch64' archiso/grub/grub.cfg \
    || ! grep -q 'vmlinuz-linux' archiso/grub/grub.cfg; then
    fail "aarch64 kernel names are not wired (Image -> vmlinuz-linux-aarch64, x86 menu kept)"
    publish_ok=0
fi
if [ -x "$PUBLISH_KERNEL" ]; then
    publish_tmp=$(mktemp -d)
    mkdir -p "$publish_tmp/boot"
    printf 'kernel\n' > "$publish_tmp/boot/Image"
    printf 'old-initrd\n' > "$publish_tmp/boot/initramfs-linux.img"
    if ! CHURROS_ROOT="$publish_tmp" "$PUBLISH_KERNEL" --require \
        || ! cmp -s "$publish_tmp/boot/Image" "$publish_tmp/boot/vmlinuz-linux-aarch64" \
        || ! cmp -s "$publish_tmp/boot/initramfs-linux.img" "$publish_tmp/boot/initramfs-linux-aarch64.img"; then
        fail "publish-aarch64-kernel did not copy Image and initramfs-linux.img"
        publish_ok=0
    fi
    printf 'installed-initrd\n' > "$publish_tmp/boot/initramfs-linux-aarch64.img"
    touch -d '2020-01-01' "$publish_tmp/boot/initramfs-linux.img"
    if ! CHURROS_ROOT="$publish_tmp" "$PUBLISH_KERNEL" \
        || ! grep -qx 'installed-initrd' "$publish_tmp/boot/initramfs-linux-aarch64.img"; then
        fail "publish-aarch64-kernel overwrote a newer initramfs-linux-aarch64.img"
        publish_ok=0
    fi
    rm -rf "$publish_tmp"
fi
[ "$publish_ok" -eq 1 ] && pass "aarch64 kernel is published as vmlinuz-linux-aarch64"

# Preset aarch64: ALL_kver=/boot/Image, imagen initramfs-linux.img (la que
# publica publish-aarch64-kernel). Los hooks memdisk y pxe se quedan en x86.
A64_PRESET=archiso/mkinitcpio/aarch64/linux-aarch64.preset
A64_HOOKS=archiso/mkinitcpio/aarch64/archiso.conf
X64_PRESET=archiso/airootfs/etc/mkinitcpio.d/linux.preset
X64_HOOKS=archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf
preset_ok=1
if [ ! -f "$A64_PRESET" ] \
    || ! grep -q "ALL_kver='/boot/Image'" "$A64_PRESET" \
    || ! grep -q 'archiso_image="/boot/initramfs-linux.img"' "$A64_PRESET" \
    || ! grep -q "PRESETS=('archiso')" "$A64_PRESET"; then
    fail "aarch64 preset must set ALL_kver=/boot/Image and archiso_image=initramfs-linux.img"
    preset_ok=0
fi
a64_hooks_line=""
[ -f "$A64_HOOKS" ] && a64_hooks_line=$(grep -E '^HOOKS=' "$A64_HOOKS" || true)
x64_hooks_line=""
[ -f "$X64_HOOKS" ] && x64_hooks_line=$(grep -E '^HOOKS=' "$X64_HOOKS" || true)
if [ -z "$a64_hooks_line" ] \
    || grep -Eq '(^|[[:space:]])memdisk([[:space:]]|$)' <<<"$a64_hooks_line" \
    || grep -q 'archiso_pxe' <<<"$a64_hooks_line" \
    || ! grep -q ' archiso ' <<<"$a64_hooks_line" \
    || ! grep -q 'archiso_loop_mnt' <<<"$a64_hooks_line"; then
    fail "aarch64 archiso hooks must keep archiso and archiso_loop_mnt and drop memdisk and archiso_pxe_*"
    preset_ok=0
fi
if ! grep -q "ALL_kver='/boot/vmlinuz-linux'" "$X64_PRESET" \
    || ! grep -Eq '(^|[[:space:]])memdisk([[:space:]]|$)' <<<"$x64_hooks_line" \
    || ! grep -q 'archiso_pxe_common' <<<"$x64_hooks_line"; then
    fail "x86_64 preset and hooks must keep vmlinuz-linux, memdisk and pxe"
    preset_ok=0
fi
if [ -f "$A64_PRESET" ]; then
    preset_sed=$(mktemp)
    cp "$A64_PRESET" "$preset_sed"
    sed -i "s/PRESETS=('archiso')/PRESETS=('default')/" "$preset_sed"
    sed -i 's|archiso_config=.*|default_config="/etc/mkinitcpio.conf"|' "$preset_sed"
    sed -i 's|archiso_image=|default_image=|' "$preset_sed"
    sed -i 's|^default_image=.*|default_image="/boot/initramfs-linux-aarch64.img"|' "$preset_sed"
    if ! grep -q "PRESETS=('default')" "$preset_sed" \
        || ! grep -q "ALL_kver='/boot/Image'" "$preset_sed" \
        || ! grep -q 'default_image="/boot/initramfs-linux-aarch64.img"' "$preset_sed"; then
        fail "Calamares sed does not turn the aarch64 preset into initramfs-linux-aarch64.img"
        preset_ok=0
    fi
    rm -f "$preset_sed"
fi
if ! grep -q 'mkinitcpio -p linux-aarch64' branding/customize_airootfs.sh \
    || ! grep -q 'publish-aarch64-kernel --require' branding/customize_airootfs.sh; then
    fail "customize_airootfs.sh must rebuild linux-aarch64 before publishing kernel names"
    preset_ok=0
else
    mkinit_line=$(grep -n 'mkinitcpio -p linux-aarch64' branding/customize_airootfs.sh | head -1 | cut -d: -f1)
    publish_line=$(grep -n 'publish-aarch64-kernel --require' branding/customize_airootfs.sh | head -1 | cut -d: -f1)
    if [ -z "$mkinit_line" ] || [ -z "$publish_line" ] || [ "$mkinit_line" -ge "$publish_line" ]; then
        fail "mkinitcpio -p linux-aarch64 must run before publish-aarch64-kernel"
        preset_ok=0
    fi
fi
if ! grep -q 'apply-aarch64-mkinitcpio.sh apply' scripts/cli/build.sh \
    || ! grep -q 'apply-aarch64-mkinitcpio.sh restore' scripts/cli/build.sh; then
    fail "build.sh must apply the aarch64 mkinitcpio files and restore them"
    preset_ok=0
fi
if [ -x scripts/apply-aarch64-mkinitcpio.sh ]; then
    # linux-aarch64 owns etc/mkinitcpio.d/linux-aarch64.preset. apply must
    # not create it; customize_airootfs.sh copies it after pacstrap.
    if ! bash scripts/apply-aarch64-mkinitcpio.sh apply \
        || [ -e archiso/airootfs/etc/mkinitcpio.d/linux.preset ] \
        || [ -e archiso/airootfs/etc/mkinitcpio.d/linux-aarch64.preset ] \
        || grep -q 'archiso_pxe' <<<"$(grep -E '^HOOKS=' archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf)" \
        || ! grep -q "ALL_kver='/boot/Image'" archiso/airootfs/usr/share/churros/mkinitcpio/aarch64/linux-aarch64.preset \
        || ! grep -q 'archiso_loop_mnt' archiso/airootfs/usr/share/churros/mkinitcpio/aarch64/archiso.conf; then
        fail "apply-aarch64-mkinitcpio.sh apply must stage the preset under /usr/share and not under /etc/mkinitcpio.d"
        preset_ok=0
    fi
    if ! bash scripts/apply-aarch64-mkinitcpio.sh restore \
        || [ -e archiso/airootfs/etc/mkinitcpio.d/linux-aarch64.preset ] \
        || [ -e archiso/airootfs/usr/share/churros/mkinitcpio ] \
        || ! grep -q "ALL_kver='/boot/vmlinuz-linux'" archiso/airootfs/etc/mkinitcpio.d/linux.preset \
        || ! grep -q 'archiso_pxe_common' archiso/airootfs/etc/mkinitcpio.conf.d/archiso.conf; then
        fail "apply-aarch64-mkinitcpio.sh restore did not put the x86 preset back"
        preset_ok=0
    fi
else
    fail "scripts/apply-aarch64-mkinitcpio.sh missing or not executable"
    preset_ok=0
fi
[ "$preset_ok" -eq 1 ] && pass "aarch64 mkinitcpio preset uses /boot/Image; x86 preset unchanged"

# archiso hardcodea grubmodules. En aarch64 el build filtra los .mod que
# no existen. x86 no llama al parche. El menú no hace insmod de usbserial
# cuando grub_cpu es arm64.
section "aarch64 GRUB modules"

grub_ok=1
if ! grep -q 'patch-mkarchiso-grubmodules.sh /usr/bin/mkarchiso' scripts/cli/build.sh; then
    fail "build.sh must patch mkarchiso's GRUB module list on aarch64"
    grub_ok=0
fi
patch_line=$(grep -n 'patch-mkarchiso-grubmodules.sh' scripts/cli/build.sh | head -1 | cut -d: -f1)
mkarchiso_line=$(grep -n 'mkarchiso -v' scripts/cli/build.sh | head -1 | cut -d: -f1)
if [ -z "$patch_line" ] || [ -z "$mkarchiso_line" ] || [ "$patch_line" -ge "$mkarchiso_line" ]; then
    fail "patch-mkarchiso-grubmodules.sh must run before mkarchiso"
    grub_ok=0
fi
# El if que envuelve la llamada tiene que ser el de aarch64, y cerrarse
# antes de mkarchiso. Hay más ifs de aarch64 arriba; no valen.
if [ -z "${patch_line:-}" ]; then
    :
elif ! sed -n "$((patch_line - 3)),$((patch_line + 1))p" scripts/cli/build.sh | grep -q 'TARGET_ARCH.*= aarch64' \
    || ! sed -n "$((patch_line + 1))p" scripts/cli/build.sh | grep -qx 'fi'; then
    fail "the mkarchiso GRUB patch must run inside the aarch64 block, before mkarchiso"
    grub_ok=0
fi
if [ "$(grep -c 'patch-mkarchiso-grubmodules.sh' scripts/cli/build.sh)" -ne 1 ]; then
    fail "build.sh must call the GRUB module patch only from the aarch64 path"
    grub_ok=0
fi
if ! awk '
    /grub_cpu\}" != "arm64"/ { guard=1; next }
    guard && /insmod usbserial_common/ { ok=1 }
    guard && /^fi$/ { guard=0 }
    END { exit ok ? 0 : 1 }
' archiso/grub/grub.cfg; then
    fail "archiso/grub/grub.cfg must skip usbserial_* when grub_cpu is arm64"
    grub_ok=0
fi
if ! grep -q 'insmod serial' archiso/grub/grub.cfg \
    || ! grep -q 'insmod usbserial_usbdebug' archiso/grub/grub.cfg; then
    fail "archiso/grub/grub.cfg must keep serial and the x86 usbserial modules"
    grub_ok=0
fi
if [ ! -x scripts/patch-mkarchiso-grubmodules.sh ]; then
    fail "scripts/patch-mkarchiso-grubmodules.sh missing or not executable"
    grub_ok=0
else
    grub_fix=$(mktemp -d)
    cat > "$grub_fix/mkarchiso" <<'EOF'
#!/usr/bin/env bash
_msg_warning() { printf 'warn %s\n' "$1" >&2; }
_msg_error() { printf 'err %s\n' "$1" >&2; exit "$2"; }
grub_target="${arch}-efi"
grubmodules=(all_video at_keyboard boot btrfs cat chain configfile echo efifwsetup efinet exfat ext2 f2fs fat font \
                 gfxmenu gfxterm gzio halt hfsplus iso9660 jpeg keylayouts linux loadenv loopback lsefi lsefimmap \
                 minicmd normal ntfs ntfscomp part_apple part_gpt part_msdos png read reboot regexp search \
                 search_fs_file search_fs_uuid search_label serial sleep tpm udf usb usbserial_common usbserial_ftdi \
                 usbserial_pl2303 usbserial_usbdebug video xfs zstd)
EOF
    chmod 755 "$grub_fix/mkarchiso"
    if ! bash scripts/patch-mkarchiso-grubmodules.sh "$grub_fix/mkarchiso" \
        || ! bash -n "$grub_fix/mkarchiso" \
        || ! grep -q 'churros: keep only GRUB modules that exist' "$grub_fix/mkarchiso" \
        || ! grep -q 'at_keyboard' "$grub_fix/mkarchiso"; then
        fail "patch-mkarchiso-grubmodules.sh did not insert the runtime filter"
        grub_ok=0
    fi
    inserted=$(sed -n '/churros: keep only GRUB modules/,/unset -v _churros_grub_keep/p' "$grub_fix/mkarchiso")
    if ! grep -q '/usr/lib/grub}/${grub_target}/' <<<"$inserted" \
        || grep -q 'at_keyboard' <<<"$inserted"; then
        fail "GRUB filter must test /usr/lib/grub/\${grub_target}/<mod>.mod and must not hardcode removals"
        grub_ok=0
    fi
    cp -a "$grub_fix/mkarchiso" "$grub_fix/mkarchiso.once"
    if ! bash scripts/patch-mkarchiso-grubmodules.sh "$grub_fix/mkarchiso" \
        || ! cmp -s "$grub_fix/mkarchiso" "$grub_fix/mkarchiso.once"; then
        fail "patch-mkarchiso-grubmodules.sh is not idempotent"
        grub_ok=0
    fi
    printf 'echo untouched\n' > "$grub_fix/no-pattern"
    if bash scripts/patch-mkarchiso-grubmodules.sh "$grub_fix/no-pattern" >/dev/null 2>&1; then
        fail "patch-mkarchiso-grubmodules.sh must fail when grubmodules=( is absent"
        grub_ok=0
    fi
    mkdir -p "$grub_fix/lib/arm64-efi"
    touch "$grub_fix/lib/arm64-efi/boot.mod" "$grub_fix/lib/arm64-efi/linux.mod"
    {
        printf '%s\n' 'set -euo pipefail' \
            '_msg_warning() { printf "warn %s\n" "$1" >&2; }' \
            '_msg_error() { printf "err %s\n" "$1" >&2; exit "$2"; }' \
            'grub_target=arm64-efi' \
            'grubmodules=(at_keyboard boot linux serial)'
        printf '%s\n' "$inserted"
        printf '%s\n' 'printf "%s\n" "${grubmodules[@]}"'
    } > "$grub_fix/run-filter.sh"
    if ! filtered=$(CHURROS_GRUB_LIB="$grub_fix/lib" bash "$grub_fix/run-filter.sh" 2>"$grub_fix/warn") \
        || [ "$filtered" != $'boot\nlinux' ] \
        || ! grep -q 'at_keyboard' "$grub_fix/warn"; then
        fail "GRUB filter did not drop missing modules and keep the ones on disk"
        grub_ok=0
    fi
    mkdir -p "$grub_fix/empty/arm64-efi"
    {
        printf '%s\n' 'set -euo pipefail' \
            '_msg_warning() { printf "warn %s\n" "$1" >&2; }' \
            '_msg_error() { printf "err %s\n" "$1" >&2; exit "$2"; }' \
            'grub_target=arm64-efi' \
            'grubmodules=(boot)'
        printf '%s\n' "$inserted"
        printf '%s\n' 'printf "%s\n" "${grubmodules[@]}"'
    } > "$grub_fix/run-empty.sh"
    if CHURROS_GRUB_LIB="$grub_fix/empty" bash "$grub_fix/run-empty.sh" >/dev/null 2>&1; then
        fail "GRUB filter must abort when no module file exists"
        grub_ok=0
    fi
    rm -rf "$grub_fix"
fi
[ "$grub_ok" -eq 1 ] && pass "aarch64 drops missing GRUB modules; x86 boot modes and module list stay"

# ------------------------------------------- QEMU pflash and live login

section "QEMU pflash and live login"

# shellcheck source=scripts/lib/ovmf.sh
source scripts/lib/ovmf.sh

pflash_ok=1
if ! grep -q 'churros_resolve_pflash' scripts/cli/run.sh \
    || grep -q 'OVMF_CODE_CANDIDATES' scripts/cli/run.sh; then
    fail "run.sh must select CODE/VARS as matched pairs"
    pflash_ok=0
fi
if grep -q 'x86_64' branding/files/issue || ! grep -q '\\m' branding/files/issue; then
    fail "branding/files/issue must use the agetty \\\\m escape, not a hardcoded arch"
    pflash_ok=0
fi
if ! grep -q '/dev/tty1' archiso/airootfs/root/.zlogin \
    || ! grep -q 'is-active --quiet greetd.service' archiso/airootfs/root/.zlogin \
    || ! grep -q -- '-x ~/.automated_script.sh' archiso/airootfs/root/.zlogin; then
    fail "root .zlogin must start greetd only on tty1 and only run an executable automated_script"
    pflash_ok=0
fi
if ! grep -q '\["/root/.automated_script.sh"\]="0:0:755"' archiso/profiledef.sh; then
    fail "profiledef.sh must mark /root/.automated_script.sh executable"
    pflash_ok=0
fi

fw_root=$(mktemp -d)
fw_out=$(mktemp -d)
mk_fw() {
    mkdir -p "$(dirname "$1")"
    truncate -s "$2" "$1"
    printf '%s' "$3" | dd of="$1" conv=notrunc status=none
}
# Debian: QEMU_EFI.fd de 3 MiB junto a AAVMF de 64 MiB. El par de 64 gana.
mk_fw "$fw_root/usr/share/qemu-efi-aarch64/QEMU_EFI.fd" 3145728 RAW
mk_fw "$fw_root/usr/share/AAVMF/AAVMF_CODE.fd" 67108864 AAVM
mk_fw "$fw_root/usr/share/AAVMF/AAVMF_VARS.fd" 67108864 VARS
if ! fw_pair=$(CHURROS_FIRMWARE_ROOT="$fw_root" churros_resolve_pflash aarch64 "$fw_out") \
    || [ "$(printf '%s\n' "$fw_pair" | sed -n '1p')" != "$fw_root/usr/share/AAVMF/AAVMF_CODE.fd" ] \
    || [ "$(printf '%s\n' "$fw_pair" | sed -n '2p')" != "$fw_root/usr/share/AAVMF/AAVMF_VARS.fd" ]; then
    fail "aarch64 firmware must prefer the 64 MiB AAVMF pair over the raw QEMU_EFI.fd"
    pflash_ok=0
fi
rm -f "$fw_root/usr/share/AAVMF/AAVMF_CODE.fd"
fw_pad=$(mktemp -d)
if ! fw_pair=$(CHURROS_FIRMWARE_ROOT="$fw_root" churros_resolve_pflash aarch64 "$fw_pad") \
    || [ "$(stat -c %s "$(printf '%s\n' "$fw_pair" | sed -n '1p')")" -ne 67108864 ] \
    || [ "$(stat -c %s "$(printf '%s\n' "$fw_pair" | sed -n '2p')")" -ne 67108864 ] \
    || [ "$(head -c 3 "$(printf '%s\n' "$fw_pair" | sed -n '1p')")" != RAW ] \
    || [ "$(head -c 4 "$(printf '%s\n' "$fw_pair" | sed -n '2p')")" != VARS ]; then
    fail "a raw QEMU_EFI.fd must be padded to 64 MiB with the VARS template"
    pflash_ok=0
fi
rm -rf "$fw_root/usr/share/AAVMF" "$fw_root/usr/share/qemu-efi-aarch64"
mk_fw "$fw_root/usr/share/qemu-efi-aarch64/QEMU_EFI.fd" 3145728 RAW
fw_pad2=$(mktemp -d)
if ! fw_pair=$(CHURROS_FIRMWARE_ROOT="$fw_root" churros_resolve_pflash aarch64 "$fw_pad2") \
    || [ "$(stat -c %s "$(printf '%s\n' "$fw_pair" | sed -n '2p')")" -ne 67108864 ] \
    || [ -n "$(head -c 4 "$(printf '%s\n' "$fw_pair" | sed -n '2p')" | tr -d '\0')" ]; then
    fail "a raw QEMU_EFI.fd without VARS must get a zeroed 64 MiB vars image"
    pflash_ok=0
fi
# x86: CODE.4m con VARS.4m, no el CODE de 2 MiB con el VARS de 4 MiB.
rm -rf "$fw_root"
fw_root=$(mktemp -d)
mk_fw "$fw_root/usr/share/OVMF/OVMF_CODE.fd" 2097152 CODE2
mk_fw "$fw_root/usr/share/OVMF/OVMF_VARS.fd" 2097152 VARS2
mk_fw "$fw_root/usr/share/OVMF/OVMF_CODE_4M.fd" 4194304 CODE4
mk_fw "$fw_root/usr/share/OVMF/OVMF_VARS_4M.fd" 4194304 VARS4
if ! fw_pair=$(CHURROS_FIRMWARE_ROOT="$fw_root" churros_resolve_pflash x86_64 "$fw_out") \
    || [ "$(printf '%s\n' "$fw_pair" | sed -n '1p')" != "$fw_root/usr/share/OVMF/OVMF_CODE_4M.fd" ] \
    || [ "$(printf '%s\n' "$fw_pair" | sed -n '2p')" != "$fw_root/usr/share/OVMF/OVMF_VARS_4M.fd" ]; then
    fail "x86 firmware must pair OVMF_CODE_4M with OVMF_VARS_4M"
    pflash_ok=0
fi
rm -f "$fw_root/usr/share/OVMF/OVMF_CODE_4M.fd" "$fw_root/usr/share/OVMF/OVMF_VARS.fd"
if CHURROS_FIRMWARE_ROOT="$fw_root" churros_resolve_pflash x86_64 "$fw_out" >/dev/null 2>&1; then
    fail "x86 must not pair a 4 MiB VARS image with a different-sized CODE"
    pflash_ok=0
fi
rm -rf "$fw_root" "$fw_out" "$fw_pad" "$fw_pad2"
unset CHURROS_FIRMWARE_ROOT
[ "$pflash_ok" -eq 1 ] && pass "pflash pairs match in size; live login stays on tty1"

# ------------------------------------------- Rollback (churros-snapshot)

section "Rollback snapshots btrfs"

SNAP_SCRIPT=archiso/airootfs/usr/local/bin/churros-snapshot
SNAP_HOOK=archiso/airootfs/etc/pacman.d/hooks/50-churros-snapshot.hook

snap_ok=1
if [ ! -f "$SNAP_SCRIPT" ]; then
    fail "$SNAP_SCRIPT missing (rollback btrfs)"
    snap_ok=0
else
    if ! grep -q 'subvolid=5' "$SNAP_SCRIPT"; then
        fail "$SNAP_SCRIPT must mount the top-level subvol (subvolid=5) for snapshots"
        snap_ok=0
    fi
    if ! grep -q 'btrfs subvol snapshot' "$SNAP_SCRIPT"; then
        fail "$SNAP_SCRIPT must create snapshots with btrfs subvol snapshot"
        snap_ok=0
    fi
    if ! grep -q 'meta.txt' "$SNAP_SCRIPT"; then
        fail "$SNAP_SCRIPT must write per-snapshot metadata (meta.txt)"
        snap_ok=0
    fi
fi

if [ ! -f "$SNAP_HOOK" ]; then
    fail "$SNAP_HOOK missing (no snapshot before pacman transactions)"
    snap_ok=0
else
    if ! grep -q 'When[[:space:]]*=[[:space:]]*PreTransaction' "$SNAP_HOOK"; then
        fail "$SNAP_HOOK must be PreTransaction (snapshot BEFORE the upgrade)"
        snap_ok=0
    fi
    if ! grep -q 'churros-snapshot' "$SNAP_HOOK"; then
        fail "$SNAP_HOOK does not call churros-snapshot"
        snap_ok=0
    fi
    if ! grep -q '||' "$SNAP_HOOK"; then
        fail "$SNAP_HOOK must tolerate snapshot failure (a snapshot error must not block pacman)"
        snap_ok=0
    fi
    if grep -q 'remove from airootfs' "$SNAP_HOOK"; then
        fail "$SNAP_HOOK would be deleted by the ISO-only hook cleaner"
        snap_ok=0
    fi
fi

if ! grep -q 'churros-snapshot' archiso/profiledef.sh; then
    fail "archiso/profiledef.sh must declare the file_permissions entry for /usr/local/bin/churros-snapshot"
    snap_ok=0
fi

if ! grep -q 'churros-snapshot' rust/preferences/src/services/update.rs; then
    fail "UpdateService must expose snapshot management (create/list/delete)"
    snap_ok=0
fi

[ "$snap_ok" -eq 1 ] && pass "rollback btrfs wired (script + hook + profiledef + UI)"

# PartitionLabelsView fills palette().window() and upstream paints Qt::black / Qt::gray.
LABELS_PATCH=installer/patches/calamares-partition-labels.patch
if [ ! -f "$LABELS_PATCH" ]; then
    fail "$LABELS_PATCH missing (partition size/fs text stays Qt::gray on the legend)"
elif ! grep -q 'bg.lightness()' "$LABELS_PATCH"; then
    fail "$LABELS_PATCH does not pick label pens from the view background"
else
    pass "partition labels secondary-text patch present"
fi

# ------------------------------------------------ XFCE X11-only session

section "XFCE X11 session"

XFCE_FIX=archiso/airootfs/usr/share/churros/scripts/fix-xfce-sessions
XFCE_HOOK=archiso/airootfs/etc/pacman.d/hooks/92-churros-xfce-x11-session.hook
XFCE_WRAPPER=archiso/airootfs/usr/bin/churros-xfce-session

xfce_ok=1
if [ ! -f "$XFCE_FIX" ]; then
    fail "$XFCE_FIX missing (xfce-wayland.desktop would need labwc and bounce the login)"
    xfce_ok=0
elif ! grep -q 'fix-xfce-sessions' archiso/profiledef.sh; then
    fail "archiso/profiledef.sh must declare the file_permissions entry for $XFCE_FIX"
    xfce_ok=0
else
    # Run the script against a fixture shaped like xfce4-session 4.20.
    xfce_tmp=$(mktemp -d)
    mkdir -p "$xfce_tmp/usr/share/wayland-sessions" "$xfce_tmp/usr/share/xsessions"
    printf '[Desktop Entry]\nName=Xfce Session (Wayland)\nExec=startxfce4 --wayland\n' \
        > "$xfce_tmp/usr/share/wayland-sessions/xfce-wayland.desktop"
    printf '[Desktop Entry]\nName=Xfce Session\nExec=startxfce4\nType=Application\n' \
        > "$xfce_tmp/usr/share/xsessions/xfce.desktop"
    if ! CHURROS_SESSION_ROOT="$xfce_tmp" bash "$XFCE_FIX" \
        || ! CHURROS_SESSION_ROOT="$xfce_tmp" bash "$XFCE_FIX"; then
        fail "$XFCE_FIX failed (it must be idempotent: the pacman hook reruns it)"
        xfce_ok=0
    elif [ -e "$xfce_tmp/usr/share/wayland-sessions/xfce-wayland.desktop" ]; then
        fail "$XFCE_FIX does not remove xfce-wayland.desktop"
        xfce_ok=0
    elif ! grep -qx 'Exec=/usr/bin/churros-xfce-session' "$xfce_tmp/usr/share/xsessions/xfce.desktop"; then
        fail "$XFCE_FIX does not point xfce.desktop at churros-xfce-session"
        xfce_ok=0
    fi
    rm -rf "$xfce_tmp"
fi

if [ ! -f "$XFCE_HOOK" ]; then
    fail "$XFCE_HOOK missing (pacman -Syu would bring back xfce-wayland.desktop)"
    xfce_ok=0
elif grep -q 'remove from airootfs' "$XFCE_HOOK"; then
    fail "$XFCE_HOOK would be deleted by the ISO-only hook cleaner"
    xfce_ok=0
elif ! grep -qE 'Type[[:space:]]*=[[:space:]]*Path' "$XFCE_HOOK" \
    || ! grep -q 'usr/share/wayland-sessions/xfce-wayland.desktop' "$XFCE_HOOK" \
    || ! grep -q 'usr/share/xsessions/xfce.desktop' "$XFCE_HOOK" \
    || ! grep -q 'When[[:space:]]*=[[:space:]]*PostTransaction' "$XFCE_HOOK" \
    || ! grep -q 'Exec[[:space:]]*=[[:space:]]*/usr/share/churros/scripts/fix-xfce-sessions' "$XFCE_HOOK"; then
    fail "$XFCE_HOOK must be a PostTransaction Path hook on both XFCE session files running fix-xfce-sessions"
    xfce_ok=0
fi

for f in archiso/airootfs/root/scripts/desktop.sh \
    archiso/airootfs/usr/share/churros/scripts/configure-greetd-session; do
    if ! grep -q 'fix-xfce-sessions' "$f"; then
        fail "$f must run fix-xfce-sessions (live boot / install)"
        xfce_ok=0
    fi
done

# ReGreet runs X11 sessions as 'startx /usr/bin/env <Exec>': the wrapper must
# notice the running X server instead of nesting a second startx.
if ! grep -q 'DISPLAY' "$XFCE_WRAPPER" || ! grep -q 'xset q' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER must detect an already running X server (ReGreet x11_prefix = startx)"
    xfce_ok=0
fi
# Arch's /etc/X11/xinit/xinitrc ends in 'exec xterm' (not installed): sourcing
# it kills the session with 127 before XFCE starts.
if grep -qE '^[^#]*(\.|source)[[:space:]]+/etc/X11/xinit/xinitrc' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER sources /etc/X11/xinit/xinitrc (ends in 'exec xterm', exit 127)"
    xfce_ok=0
fi
# startxfce4 runs /etc/xdg/xfce4/xinitrc (XDG_MENU_PREFIX, xrdb, dbus/systemd
# env); a bare xfce4-session skips all of it.
if grep -qE '^[^#]*exec[[:space:]]+(/usr/bin/)?xfce4-session' "$XFCE_WRAPPER" \
    || ! grep -qE '^[^#]*exec[[:space:]]+/usr/bin/startxfce4' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER must exec startxfce4, not a bare xfce4-session"
    xfce_ok=0
fi
# A hardcoded display defeats startx's free-display search (stale .X0-lock).
if grep -qE '^[^#]*startx[^#]*--[[:space:]]+:[0-9]' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER hardcodes the X display in startx (let startx pick a free one)"
    xfce_ok=0
fi
# startx only accepts its client as the session program when the path starts
# with '/' or './' (startx.c: case "$1" in /''*|\./''*)). Given a bare name it
# silently falls back to its default client, xterm, which is not installed in
# any ChurrOS package list: xinit exits 127 and greetd bounces to the greeter.
# So the wrapper must resolve itself to an absolute path before calling startx.
if grep -qE '^[^#]*exec[[:space:]]+startx[[:space:]]+"\$0"' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER passes \"\$0\" to startx: a relative \$0 makes startx run xterm (not installed) and greetd bounce to the greeter"
    xfce_ok=0
fi
if ! grep -qE '^[^#]*exec[[:space:]]+startx[[:space:]]+"\$self"' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER must exec startx with an absolute, pre-resolved path (got \$self, not \$0)"
    xfce_ok=0
fi
# Xorg finds the VT to take by inspecting its own fds 0-2 (lnx_init.c,
# parse_vt_settings) and greetd watches the session on that same tty, so the
# wrapper must not redirect stdout/stderr before exec'ing startx. Diagnostics
# belong in a log() helper, not in an 'exec >' at the top of the session.
if grep -qE '^[^#]*\{[[:space:]]*exec[[:space:]]*>{1,2}' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER redirects its own stdout/stderr before starting Xorg (Xorg reads fds 0-2 to find the VT; greetd watches that tty)"
    xfce_ok=0
fi
# 'xsetroot -cursor_name' goes through XLoadFont on the core X11 "cursor" font
# and XDefineCursor on the root window; libXcursor is only reached via -cursor
# and -xcf. So it overrides the theme xsettings.xml asks for (Adwaita, 24) with
# a 1-bit 16x16 glyph that does not scale and vanishes against the wallpaper.
# It was inert until d9f285a added xorg-fonts-misc, which ships the cursor.pcf
# that XLoadFont needs; xsetroot exits 0 either way, so '|| true' never hid it.
if grep -qE '^[^#]*xsetroot[[:space:]]+-cursor_name' "$XFCE_WRAPPER"; then
    fail "$XFCE_WRAPPER calls 'xsetroot -cursor_name': it bypasses the Xcursor theme (Adwaita) with a 1-bit core-font glyph and hides the pointer. Set CursorThemeName in xsettings.xml instead"
    xfce_ok=0
fi

# A "Device" section forcing Driver "modesetting" breaks the NVIDIA driver
# that netinstall offers; VM-only tweaks go in an OutputClass.
if grep -lE '^[[:space:]]*Driver[[:space:]]+"modesetting"' archiso/airootfs/etc/X11/xorg.conf.d/*.conf 2>/dev/null \
    | xargs -r grep -lE '^[[:space:]]*Section[[:space:]]+"Device"' | grep -q .; then
    fail "archiso/airootfs/etc/X11/xorg.conf.d forces Driver \"modesetting\" in a Device section (breaks NVIDIA)"
    xfce_ok=0
fi

[ "$xfce_ok" -eq 1 ] && pass "XFCE stays X11-only (wrapper + session fix + pacman hook)"

# ----------------------------------------------- Calamares branding files

section "Calamares branding"

# Stdlib only (CI has no PyYAML). Mirrors Branding.cpp bail() checks:
# componentName == directory, slideshow exists, image paths exist and
# are non-empty, slideshowAPI 2 requires onActivate/onLeave.
if python3 - installer/calamares/branding <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
errors = 0


def fail(msg: str) -> None:
    global errors
    errors += 1
    print(f"    {msg}")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def parse_desc(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    data: dict[str, object] = {"images": {}}
    section = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip() or line.strip() == "---":
            continue
        if re.match(r"^[A-Za-z][A-Za-z0-9_]*:\s*$", line):
            section = line.split(":", 1)[0]
            if section == "images":
                data["images"] = {}
            continue
        m = re.match(r"^([A-Za-z][A-Za-z0-9_]*):\s*(.*)$", line)
        if m:
            section = None
            data[m.group(1)] = unquote(m.group(2))
            continue
        if section == "images":
            m = re.match(r"^\s+([A-Za-z][A-Za-z0-9_]*):\s*(.*)$", line)
            if m:
                data["images"][m.group(1)] = unquote(m.group(2))  # type: ignore[index]
    return data


if not root.is_dir():
    fail(f"{root} missing")
    sys.exit(1)

for component in sorted(p for p in root.iterdir() if p.is_dir()):
    desc = component / "branding.desc"
    if not desc.is_file():
        fail(f"{desc} missing")
        continue
    data = parse_desc(desc)
    name = str(data.get("componentName") or "")
    if name != component.name:
        fail(f"{desc}: componentName '{name}' != directory '{component.name}'")

    sidebar = str(data.get("sidebar") or "widget")
    if sidebar.split(",")[0].strip() == "qml":
        qml_sidebar = component / "calamares-sidebar.qml"
        if not qml_sidebar.is_file():
            fail(f"{desc}: sidebar: qml requires {qml_sidebar}")

    slideshow = str(data.get("slideshow") or "")
    if not slideshow:
        fail(f"{desc}: slideshow is missing")
    else:
        show = component / slideshow
        if not show.is_file():
            fail(f"{desc}: slideshow file {show} does not exist")
        else:
            api = str(data.get("slideshowAPI") or "")
            if api == "2":
                qml = show.read_text(encoding="utf-8")
                if not re.search(r"function\s+onActivate\s*\(", qml):
                    fail(f"{show}: slideshowAPI 2 requires onActivate()")
                if not re.search(r"function\s+onLeave\s*\(", qml):
                    fail(f"{show}: slideshowAPI 2 requires onLeave()")
                if "#0F0F10" not in qml:
                    fail(f"{show}: slideshow has no dark fill (Install page stays Fusion-white)")

    images = data.get("images") or {}
    if not isinstance(images, dict) or not images:
        fail(f"{desc}: images: must list productLogo/productIcon files")
    else:
        for key, value in images.items():
            if value == "":
                fail(f"{desc}: images.{key} is empty (Calamares exits)")
                continue
            image_path = component / value
            if not image_path.is_file():
                fail(f"{desc}: images.{key} file {image_path} does not exist")
            elif image_path.stat().st_size == 0:
                fail(f"{desc}: images.{key} file {image_path} is empty")

    qss = component / "stylesheet.qss"
    if qss.is_file():
        qss_text = qss.read_text(encoding="utf-8")
        if re.search(r"^QWidget\s*\{", qss_text, re.M):
            fail(f"{qss}: QWidget {{ }} paints PartitionLabelsView unreadable")
        if "PrettyRadioButton" not in qss_text or "ChoicePage" not in qss_text:
            fail(f"{qss}: partition ChoicePage/PrettyRadioButton styles missing (white-on-white)")
        if "#summaryStep QWidget" not in qss_text:
            fail(f"{qss}: summary page QWidget styles missing (white-on-white)")
        if "PartitionLabelsView" not in qss_text or "QQuickWidget" not in qss_text:
            fail(f"{qss}: PartitionLabelsView/QQuickWidget styles missing (Fusion-white panels)")
        if "combo-arrow.svg" in qss_text and not (component / "combo-arrow.svg").is_file():
            fail(f"{qss}: combo-arrow.svg is referenced but missing")

sys.exit(1 if errors else 0)
PY
then
    pass "branding component would load"
else
    fail "branding component would make Calamares exit"
fi

# ------------------------------------------- Calamares host preview (no ISO)

section "Calamares host preview"

PREVIEW=installer/calamares/preview
if [ ! -f "$PREVIEW/settings.conf" ]; then
    fail "$PREVIEW/settings.conf missing"
else
    preview_ok=1
    if grep -E '^[[:space:]]+-[[:space:]]*partition[[:space:]]*$' "$PREVIEW/settings.conf" >/dev/null; then
        fail "preview settings.conf must not load partition (polkit / real disks)"
        preview_ok=0
    fi
    if [ -f "$PREVIEW/finished.conf" ] && ! grep -q '^restartNowMode:[[:space:]]*never' "$PREVIEW/finished.conf"; then
        fail "preview finished.conf must set restartNowMode: never"
        preview_ok=0
    fi
    if [ -f "$PREVIEW/locale.conf" ] && ! grep -q '^adjustLiveTimezone:[[:space:]]*false' "$PREVIEW/locale.conf"; then
        fail "preview locale.conf must set adjustLiveTimezone: false"
        preview_ok=0
    fi
    if [ -f "$PREVIEW/keyboard.conf" ] && ! grep -q '^useLocale1:[[:space:]]*false' "$PREVIEW/keyboard.conf"; then
        fail "preview keyboard.conf must set useLocale1: false"
        preview_ok=0
    fi
    [ "$preview_ok" -eq 1 ] && pass "preview does not partition, reboot, or push layout/timezone"
fi

# ------------------------------------------- Calamares finished (producción)

# restartNowMode solo admite never|user-unchecked|user-checked|always en
# Calamares 3.4.x; un valor inválido oculta el botón de reinicio de la
# pantalla final (regresión: "no aparece la opción de reiniciar").
FINISHED_CONF=installer/calamares/modules/finished.conf
if [ ! -f "$FINISHED_CONF" ]; then
    fail "$FINISHED_CONF missing (finished page defaults; restart option may vanish)"
else
    mode=$(grep -E '^restartNowMode:' "$FINISHED_CONF" | head -1 | awk '{print $2}')
    case "$mode" in
        never|user-unchecked|user-checked|always)
            pass "finished.conf restartNowMode=$mode is a valid Calamares 3.4 value"
            ;;
        *)
            fail "$FINISHED_CONF restartNowMode='$mode' is invalid (hide the restart checkbox); use never|user-unchecked|user-checked|always"
            ;;
    esac
    if ! grep -q '^restartNowCommand:' "$FINISHED_CONF"; then
        fail "$FINISHED_CONF should set restartNowCommand (systemctl -i reboot)"
    fi
fi

# Local AUR extras check removed as netinstall module was deprecated in favor of churros-tour

# ------------------------------------------- Calamares Python ABI

# ----------------------------------------- Package extension and binfmt C

# shellcheck source=scripts/lib/local-repo.sh
source scripts/lib/local-repo.sh

section "Package archives and aarch64 binfmt"

if grep -q "PKGEXT='.pkg.tar.zst'" Containerfile.aarch64; then
    pass "aarch64 image forces PKGEXT=.pkg.tar.zst"
else
    fail "Containerfile.aarch64 does not set PKGEXT=.pkg.tar.zst (ALARM defaults to .xz)"
fi

pkg_tmp="$(mktemp -d)"
: > "$pkg_tmp/calamares-3.3.14-1-aarch64.pkg.tar.xz"
: > "$pkg_tmp/calamares-debug-3.3.14-1-aarch64.pkg.tar.xz"
: > "$pkg_tmp/calamares-3.3.14-1-aarch64.pkg.tar.xz.sig"
: > "$pkg_tmp/yay-12.1.3-1-x86_64.pkg.tar.zst"
found="$(churros_first_pkg "$pkg_tmp" 'calamares-[0-9]*' || true)"
if [ "$found" = "$pkg_tmp/calamares-3.3.14-1-aarch64.pkg.tar.xz" ]; then
    pass "cache detection accepts .pkg.tar.xz and skips debug packages and signatures"
else
    fail "churros_first_pkg returned '${found:-empty}' for a .pkg.tar.xz cache"
fi
mapfile -t pkg_all < <(churros_pkg_archives "$pkg_tmp")
if [ "${#pkg_all[@]}" -eq 2 ]; then
    pass "package listing keeps real .xz and .zst archives"
else
    fail "expected 2 package archives, got ${#pkg_all[@]}"
fi
rm -rf "$pkg_tmp"

binfmt_tmp="$(mktemp -d)"
printf '%s\n' enabled 'interpreter /bin/true' 'flags: POF' > "$binfmt_tmp/qemu-aarch64"
CHURROS_BINFMT_DIR="$binfmt_tmp"
if churros_aarch64_emulation_ready; then
    fail "binfmt flags POF (no C) were treated as ready"
else
    pass "binfmt without flag C is not ready for sudo inside makepkg"
fi
printf '%s\n' enabled 'interpreter /bin/true' 'flags: FPOC' > "$binfmt_tmp/qemu-aarch64"
if churros_aarch64_emulation_ready; then
    pass "binfmt flags FPOC count as ready"
else
    fail "binfmt flags FPOC were rejected"
fi
unset CHURROS_BINFMT_DIR
rm -rf "$binfmt_tmp"

section "Calamares libpython"

# El python del host solo representa al de la ISO en Arch. En otra distro
# (paquete construido con ./churros build --container) la comparación daría un
# fallo falso: build-calamares.sh ya recompila dentro del contenedor si la
# versión de python de Arch cambia.
CALAMARES_LOCAL="$(churros_first_pkg archiso/packages 'calamares-[0-9]*' || true)"
if [ -z "$CALAMARES_LOCAL" ]; then
    notice "no local calamares package (ISO build will compile it)"
elif ! churros_host_is_arch; then
    notice "host is not Arch: libpython of $(basename "$CALAMARES_LOCAL") is checked by ./churros build --container"
elif ! command -v readelf >/dev/null 2>&1; then
    notice "readelf not available; skip libpython check"
else
    host_python=$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    abi_tmp=$(mktemp -d)
    if command -v bsdtar >/dev/null 2>&1; then
        bsdtar -xf "$CALAMARES_LOCAL" -C "$abi_tmp" usr/lib/libcalamares.so.3.4.2 2>/dev/null || \
            bsdtar -xf "$CALAMARES_LOCAL" -C "$abi_tmp" usr/lib/libcalamares.so 2>/dev/null || true
    else
        case "$CALAMARES_LOCAL" in
            *.zst) tar_cmd=(tar --zstd -xf) ;;
            *.xz) tar_cmd=(tar -Jxf) ;;
            *.gz) tar_cmd=(tar -zxf) ;;
            *) tar_cmd=(tar -xf) ;;
        esac
        "${tar_cmd[@]}" "$CALAMARES_LOCAL" -C "$abi_tmp" usr/lib/libcalamares.so.3.4.2 2>/dev/null || \
            "${tar_cmd[@]}" "$CALAMARES_LOCAL" -C "$abi_tmp" usr/lib/libcalamares.so 2>/dev/null || true
    fi
    abi_so=$(find "$abi_tmp" -name 'libcalamares.so*' -type f | head -1 || true)
    pkg_python=""
    if [ -n "$abi_so" ]; then
        pkg_python=$(readelf -d "$abi_so" | sed -n 's/.*libpython\([0-9.]*\)\.so.*/\1/p' | head -1)
    fi
    rm -rf "$abi_tmp"
    if [ -z "$pkg_python" ]; then
        fail "$(basename "$CALAMARES_LOCAL"): could not read libpython NEEDED"
    elif [ "$pkg_python" != "$host_python" ]; then
        fail "$(basename "$CALAMARES_LOCAL") links libpython${pkg_python} but ISO python is ${host_python} (Calamares will not start). Run ./scripts/build-calamares.sh"
    else
        pass "Calamares links libpython${pkg_python} (matches host)"
    fi
    want_stamp=$(
        (
            cd installer/patches || exit 1
            ls calamares-*.patch | sort | xargs sha256sum
            echo "python=$host_python"
        ) | sha256sum | awk '{print $1}'
    )
    have_stamp=$(cat archiso/packages/.calamares-build.stamp 2>/dev/null || true)
    if [ "$have_stamp" != "$want_stamp" ]; then
        fail "local calamares package is stale vs installer/patches (run ./scripts/build-calamares.sh)"
    else
        pass "local calamares package matches installer/patches stamp"
    fi
fi

# El config de greetd versionado debe arrancar la sesión niri en el Live;
# build.sh lo reescribe por edición y lo restaura en el trap.
section "greetd initial_session"
if grep -A3 '\[initial_session\]' archiso/airootfs/etc/greetd/config.toml | grep -q 'niri'; then
    pass "greetd initial_session es niri"
else
    fail "greetd initial_session no es niri"
fi

# ------------------------------------------------------- Live overlay size

section "Live overlay size"

BOOT_CMDLINE_FILES=(
    archiso/grub/grub.cfg
    archiso/grub/loopback.cfg
    archiso/syslinux/archiso_sys-linux.cfg
    archiso/syslinux/archiso_pxe-linux.cfg
    archiso/efiboot/loader/entries/01-archiso-linux.conf
    archiso/efiboot/loader/entries/02-archiso-speech-linux.conf
)

cow_ok=1
for boot_file in "${BOOT_CMDLINE_FILES[@]}"; do
    if [ ! -f "$boot_file" ]; then
        fail "$boot_file missing"
        cow_ok=0
        continue
    fi
    if ! grep -qE '(^|[[:space:]])cow_spacesize=' "$boot_file"; then
        fail "$boot_file missing cow_spacesize= (Flatpak/Bazaar needs >500M overlay)"
        cow_ok=0
    fi
done
[ "$cow_ok" -eq 1 ] && pass "live boot entries set cow_spacesize"

# ------------------------------------------------------------ Translations

section "Translations"

# Aviso honesto: el catalogo sigue apuntando a la interfaz en Python
# (preferences/pages/*.py, popups/*/widgets/*.py), que ya no existe; las apps
# Rust no usan gettext y escriben los textos en castellano directamente. El
# chequeo de abajo es de sintaxis del .po, no de que las traducciones se
# apliquen a la interfaz actual.
notice "po/*.po cubren la UI en Python antigua; las apps Rust no usan gettext"

if command -v msgfmt >/dev/null 2>&1; then
    for po in po/*.po; do
        [ -e "$po" ] || continue
        if msgfmt --check -o /dev/null "$po" 2>/dev/null; then
            pass "$po"
        else
            fail "$po has errors"
        fi
    done
else
    notice "msgfmt not available (gettext package)"
fi

# ---------------------------------------------------------- Distro version

section "Distro version"

if [ ! -f VERSION ]; then
    fail "VERSION missing at repo root"
else
    ver=$(tr -d '[:space:]' < VERSION)
    if [[ ! "$ver" =~ ^[0-9]+(\.[0-9]+)*$ ]]; then
        fail "VERSION must be dotted numeric (got '$ver')"
    else
        pass "VERSION=$ver"
    fi
fi

if grep -q 'include_str!("../../../VERSION")' rust/services/src/version.rs 2>/dev/null; then
    pass "churros-services bakes VERSION at compile time"
else
    fail "rust/services/src/version.rs must include_str the repo VERSION file"
fi

if grep -qE 'const VERSION:[[:space:]]*&str[[:space:]]*=[[:space:]]*"[0-9]' rust/churros-welcome/src/footer.rs; then
    fail "welcome footer has a hardcoded version; use churros_services::version::distro()"
elif grep -q 'churros_services::version::distro' rust/churros-welcome/src/footer.rs; then
    pass "welcome footer reads churros_services::version::distro"
else
    fail "welcome footer must call churros_services::version::distro()"
fi

if grep -qE 'fn version\(\) -> &' rust/preferences/src/services/about.rs \
    && grep -q 'churros_services::version::distro' rust/preferences/src/services/about.rs; then
    pass "Settings About reads churros_services::version::distro"
else
    fail "preferences AboutService::version must call churros_services::version::distro()"
fi

if [ -f branding/stamp-os-release.sh ]; then
    pass "branding/stamp-os-release.sh present"
else
    fail "branding/stamp-os-release.sh missing"
fi

if grep -q 'stamp-os-release.sh' branding/customize_airootfs.sh \
    && grep -q 'stamp-os-release.sh' scripts/cli/build.sh; then
    pass "ISO build stamps os-release from VERSION"
else
    fail "build.sh and customize_airootfs.sh must stamp os-release from VERSION"
fi

# --------------------------------------------- Ejecución privilegiada (polkit)

section "Privileged execution"

POLKIT_RULE=archiso/airootfs/etc/polkit-1/rules.d/50-churros-store.rules

# pkexec publica `program` y `command_line`. `command` no existe y una regla que
# lo lea no autoriza nunca nada: así pasó en #152 sin que nadie lo notara. Se
# mira solo el código (las líneas `//` lo explican y lo nombran).
rule_code=$(grep -nvE '^[[:space:]]*//' "$POLKIT_RULE" || true)
if printf '%s\n' "$rule_code" |
    grep -E "lookup\([[:space:]]*[\"']command[\"'][[:space:]]*\)|getDetails"; then
    fail "$POLKIT_RULE lee lookup(\"command\") o getDetails(): pkexec solo publica program y command_line"
else
    pass "la regla polkit lee las claves que publica pkexec (program, command_line)"
fi

if command -v node >/dev/null 2>&1; then
    if polkit_out=$(node scripts/test-polkit-rules.js 2>&1); then
        pass "decisiones de la regla polkit ($polkit_out)"
    else
        printf '%s\n' "$polkit_out"
        fail "scripts/test-polkit-rules.js"
    fi
else
    notice "node no está instalado: no se prueban las decisiones de la regla polkit"
fi

# churros-update-utils sobre un root falso, churros-write-root-config y la
# tabla edición -> sesión. Sin root y sin tocar /.
if helpers_out=$(python3 scripts/test-privileged-helpers.py 2>&1); then
    pass "helpers privilegiados en un root falso (scripts/test-privileged-helpers.py)"
else
    printf '%s\n' "$helpers_out" | tail -n 40
    fail "scripts/test-privileged-helpers.py"
fi

if network_out=$(python3 scripts/test-network-services.py 2>&1); then
    pass "network service ownership (scripts/test-network-services.py)"
else
    printf '%s\n' "$network_out" | tail -n 40
    fail "scripts/test-network-services.py"
fi

# --------------------------------------------------------------- Hygiene

section "Repository hygiene"

tracked_artifacts=$(git ls-files | grep -cE '\.pyc$|\.pkg\.tar\.zst$|churros\.(db|files)|OVMF_VARS|^\.vscode/|^session-' || true)
if [ "$tracked_artifacts" -gt 0 ]; then
    notice "$tracked_artifacts generated files are tracked in git"
else
    pass "no generated files tracked"
fi

# ---------------------------------------------------------------- Summary

printf '\n----------------------------------------\n'
if [ "$FAILURES" -eq 0 ]; then
    printf 'All checks passed (%s notices)\n' "$NOTICES"
    exit 0
else
    printf '%s checks failed (%s notices)\n' "$FAILURES" "$NOTICES"
    exit 1
fi
