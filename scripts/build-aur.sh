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
        WORK_DIR="$(mktemp -d /tmp/churros-aur-build.XXXXXX)"
        return
    fi
    mkdir -p "$parent"
    WORK_DIR="$parent/aur-build"
}

choose_work_dir

echo "======================================"
echo "  Building AUR extras for ChurrOS"
echo "======================================"

mkdir -p "$PACKAGE_DIR" "$WORK_DIR"

build_aur() {
    local name="$1"
    local package_dir="$WORK_DIR/$name"

    if [ -n "$(churros_first_pkg "$PACKAGE_DIR" "$name-*" || true)" ]; then
        echo "[skip] $name already built"
        return
    fi

    echo "[build] $name from AUR..."
    rm -rf "$package_dir"
    git clone "https://aur.archlinux.org/${name}.git" "$package_dir"
    (
        cd "$package_dir"
        churros_pkgbuild_allow_arch PKGBUILD
        makepkg -sf --noconfirm --skippgpcheck
    )
    churros_copy_pkgs "$package_dir" "$PACKAGE_DIR" "$name-*"
    churros_remove_pkgs "$PACKAGE_DIR" "$name-debug-*"
    echo "[done] $name built"
}

build_aur python-pywal
build_aur yay
build_aur wlogout

echo
echo "Updating churros local repo..."
(
    cd "$PACKAGE_DIR"
    churros_repo_add "$PACKAGE_DIR"
)

rm -rf "$WORK_DIR"

echo
echo "======================================"
echo "  AUR extras built."
echo "======================================"
show_pkg() {
    local label="$1"
    local glob="$2"
    if churros_first_pkg "$PACKAGE_DIR" "$glob" >/dev/null; then
        churros_pkg_archives "$PACKAGE_DIR" "$glob"
    else
        echo "($label not built)"
    fi
}
show_pkg pywal 'python-pywal-*'
show_pkg yay 'yay-*'
show_pkg wlogout 'wlogout-*'
echo
echo "  Run: ./churros build"
