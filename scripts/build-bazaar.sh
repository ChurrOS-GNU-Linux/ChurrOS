#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=scripts/lib/local-repo.sh
source "$SCRIPT_DIR/lib/local-repo.sh"
PACKAGE_DIR="$(churros_local_repo_dir)"

choose_work_dir() {
    local parent="$PROJECT_DIR/work"
    if [ -e "$parent" ] && [ ! -w "$parent" ]; then
        WORK_DIR="$(mktemp -d /tmp/churros-bazaar-build.XXXXXX)"
        return
    fi
    mkdir -p "$parent"
    WORK_DIR="$parent/bazaar-build"
}

# Cierto si $1 >= $2 (sort -V).
version_ge() {
    local first
    first="$(printf '%s\n%s\n' "$1" "$2" | sort -V | head -n1 || true)"
    [ "$first" = "$2" ]
}

# Versión de libdex en los repos (sin epoch ni pkgrel). Vacío si no está.
repo_libdex_version() {
    local line ver
    line="$(pacman -Si libdex 2>/dev/null | awk -F: '/^Version/ { gsub(/[[:space:]]/, "", $2); print $2; exit }' || true)"
    if [ -z "$line" ]; then
        sudo pacman -Sy --noconfirm
        line="$(pacman -Si libdex 2>/dev/null | awk -F: '/^Version/ { gsub(/[[:space:]]/, "", $2); print $2; exit }' || true)"
    fi
    [ -n "$line" ] || return 1
    ver="${line#*:}"
    ver="${ver%%-*}"
    printf '%s\n' "$ver"
}

# El paquete local sirve si meson puede enlazar libdex-1 >= 1.2. Un bazaar
# viejo que hacía provides/conflicts de libdex no cuenta: se compiló sin la
# librería y hay que rehacerlo.
bazaar_pkg_ok() {
    local pkg info
    pkg="$(churros_first_pkg "$PACKAGE_DIR" 'bazaar-*' || true)"
    [ -n "$pkg" ] || return 1
    command -v bsdtar >/dev/null 2>&1 || return 1
    info="$(bsdtar -xOf "$pkg" .PKGINFO 2>/dev/null || true)"
    printf '%s\n' "$info" | grep -qx 'depend = libdex>=1.2.0'
}

# meson pide dependency('libdex-1', version: '>= 1.2.0'). Arch extra trae
# 1.2.0; Arch Linux ARM se queda en 1.1.0 y no hay wrap en bazaar 0.9.7.
# Si el repo no llega, se construye el PKGBUILD de Arch, se instala en el
# contenedor y se publica en [churros] para que la ISO lo resuelva.
ensure_libdex() {
    local repo_ver existing libdex_dir
    repo_ver="$(repo_libdex_version || true)"
    if [ -n "$repo_ver" ] && version_ge "$repo_ver" 1.2.0; then
        echo "    libdex $repo_ver is in the repos (>= 1.2.0)"
        return 0
    fi
    echo "    libdex ${repo_ver:-not in the repos} is older than 1.2.0; building Arch libdex 1.2.0"

    existing="$(churros_first_pkg "$PACKAGE_DIR" 'libdex-[0-9]*' || true)"
    if [ -z "$existing" ]; then
        libdex_dir="$WORK_DIR/libdex"
        rm -rf "$libdex_dir"
        mkdir -p "$libdex_dir"
        curl -fsSL "https://gitlab.archlinux.org/archlinux/packaging/packages/libdex/-/raw/main/PKGBUILD" \
            -o "$libdex_dir/PKGBUILD"
        python3 - "$libdex_dir/PKGBUILD" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = text.replace("\n  libdex-docs\n", "\n")
text = text.replace("\n  gi-docgen\n", "\n")
text = text.replace("-D docs=true", "-D docs=false")
docs_mv = '  mkdir -p doc/usr/share\n  mv {"$pkgdir",doc}/usr/share/doc\n'
if docs_mv not in text:
    raise SystemExit("libdex PKGBUILD: docs install step not found")
text = text.replace(docs_mv, "")
text = re.sub(r"\npackage_libdex-docs\(\) \{.*?\n\}\n", "\n", text, count=1, flags=re.S)
if "libdex-docs" in text or "package_libdex-docs" in text:
    raise SystemExit("libdex PKGBUILD: docs package still present")
open(path, "w", encoding="utf-8").write(text)
print("    libdex: docs disabled")
PY
        if ! pacman -Si libsysprof-capture >/dev/null 2>&1; then
            python3 - "$libdex_dir/PKGBUILD" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = text.replace("-D sysprof=true", "-D sysprof=false")
text = text.replace("\n  libsysprof-capture\n", "\n")
open(path, "w", encoding="utf-8").write(text)
print("    libdex: sysprof disabled (not in this repo)")
PY
        fi
        if ! pacman -Si glib2-devel >/dev/null 2>&1; then
            python3 - "$libdex_dir/PKGBUILD" <<'PY'
import sys
path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = text.replace("\n  glib2-devel\n", "\n")
open(path, "w", encoding="utf-8").write(text)
print("    libdex: glib2-devel not in this repo; headers come from glib2")
PY
        fi
        churros_pkgbuild_allow_arch "$libdex_dir/PKGBUILD"
        (
            cd "$libdex_dir"
            makepkg -sf --noconfirm --skippgpcheck --nocheck
        )
        churros_copy_pkgs "$libdex_dir" "$PACKAGE_DIR" 'libdex-*'
        churros_remove_pkgs "$PACKAGE_DIR" 'libdex-debug-*'
        churros_repo_add "$PACKAGE_DIR"
        existing="$(churros_first_pkg "$PACKAGE_DIR" 'libdex-[0-9]*')"
    fi
    echo "    installing $(basename "$existing") so bazaar can link libdex-1"
    sudo pacman -U --noconfirm "$existing"
}

choose_work_dir

echo "======================================"
echo "  Building Bazaar app store from Arch"
echo "======================================"

mkdir -p "$PACKAGE_DIR"

if bazaar_pkg_ok; then
    echo "[skip] Bazaar already built (depends on libdex>=1.2.0)."
    exit 0
fi

if [ -n "$(churros_first_pkg "$PACKAGE_DIR" 'bazaar-*' || true)" ]; then
    echo "[rebuild] local bazaar does not depend on libdex>=1.2.0."
    churros_remove_pkgs "$PACKAGE_DIR" 'bazaar-*'
    churros_remove_pkgs "$PACKAGE_DIR" 'bazaar-debug-*'
fi

rm -rf "$WORK_DIR" 2>/dev/null || true
mkdir -p "$WORK_DIR"

echo "[1/4] Fetching Arch PKGBUILD for bazaar..."
for f in PKGBUILD bazaar.install; do
    curl -fsSL "https://gitlab.archlinux.org/archlinux/packaging/packages/bazaar/-/raw/main/$f" \
        -o "$WORK_DIR/$f" 2>/dev/null || true
done

if [ ! -s "$WORK_DIR/PKGBUILD" ]; then
    echo "ERROR: could not download the bazaar PKGBUILD." >&2
    exit 1
fi

echo "[2/4] Requiring libdex>=1.2.0 (meson looks up libdex-1)..."

python3 - "$WORK_DIR/PKGBUILD" <<'PY'
import re
import sys

path = sys.argv[1]
text = open(path, encoding="utf-8").read()
text = re.sub(r"\nprovides=\('libdex'\)", "", text)
text = re.sub(r"\nconflicts=\('libdex'\)", "", text)
new, count = re.subn(r"^(\s*)['\"]?libdex['\"]?\s*$", r"\1'libdex>=1.2.0'", text, count=1, flags=re.M)
if count != 1:
    if re.search(r"^\s*['\"]?libdex>=1\.2\.0['\"]?\s*$", text, flags=re.M):
        new = text
    else:
        raise SystemExit("PKGBUILD: no libdex depend to pin")
open(path, "w", encoding="utf-8").write(new)
print("    depend = libdex>=1.2.0")
PY

churros_pkgbuild_allow_arch "$WORK_DIR/PKGBUILD"
ensure_libdex

echo "[3/4] Building bazaar (this may take a while)..."

(
    cd "$WORK_DIR"
    makepkg -sf --noconfirm --skippgpcheck
)

echo "[4/4] Installing package to local repo..."

churros_copy_pkgs "$WORK_DIR" "$PACKAGE_DIR" 'bazaar-*'
churros_remove_pkgs "$PACKAGE_DIR" 'bazaar-debug-*'
churros_repo_add "$PACKAGE_DIR"

rm -rf "$WORK_DIR"

echo
echo "======================================"
echo "  Bazaar build complete."
echo "======================================"
churros_pkg_archives "$PACKAGE_DIR" 'bazaar-*'
echo
echo "  Now run: ./churros build"
