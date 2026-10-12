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
        echo "[warn] $parent is not writable (usually leftover from sudo mkarchiso)."
        echo "       Fix with: ./churros clean"
        echo "       or: sudo chown -R $USER:$USER $parent"
        WORK_DIR="$(mktemp -d /tmp/churros-calamares-build.XXXXXX)"
        echo "[warn] Building in $WORK_DIR instead."
        return
    fi
    mkdir -p "$parent"
    WORK_DIR="$parent/calamares-build"
}

echo "======================================"
echo "  Building Calamares from AUR"
echo "======================================"

mkdir -p "$PACKAGE_DIR"

HOST_PYTHON="$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PATCHES_DIR="$PROJECT_DIR/installer/patches"
STAMP_FILE="$PACKAGE_DIR/.calamares-build.stamp"

calamares_want_stamp() {
    (
        cd "$PATCHES_DIR"
        ls calamares-*.patch | sort | xargs sha256sum
        echo "python=$HOST_PYTHON"
    ) | sha256sum | awk '{print $1}'
}

WANT_STAMP="$(calamares_want_stamp)"

if [ -n "$(churros_first_pkg "$PACKAGE_DIR" 'calamares-[0-9]*' || true)" ]; then
    HAVE_STAMP="$(cat "$STAMP_FILE" 2>/dev/null || true)"
    if [ "$HAVE_STAMP" = "$WANT_STAMP" ]; then
        echo "[skip] Calamares already built (python $HOST_PYTHON + patches stamp match)."
        exit 0
    fi
    echo "[rebuild] Calamares stamp mismatch (libpython or installer/patches changed)."
    churros_remove_pkgs "$PACKAGE_DIR" 'calamares-[0-9]*'
    churros_remove_pkgs "$PACKAGE_DIR" 'calamares-debug-*' 
fi

choose_work_dir
rm -rf "$WORK_DIR" 2>/dev/null || true

echo "[1/4] Cloning calamares from AUR..."
git clone https://aur.archlinux.org/calamares.git "$WORK_DIR"

echo "[2/4] Applying installer/patches/calamares-*.patch..."

PATCH_LIST="$WORK_DIR/churros-patches.list"
: > "$PATCH_LIST"
shopt -s nullglob
for patch in "$PATCHES_DIR"/calamares-*.patch; do
    name="$(basename "$patch")"
    sha="$(sha256sum "$patch" | cut -d' ' -f1)"
    cp "$patch" "$WORK_DIR/$name"
    printf '%s %s\n' "$name" "$sha" >> "$PATCH_LIST"
    echo "    $name"
done
shopt -u nullglob

if [ ! -s "$PATCH_LIST" ]; then
    echo "ERROR: no calamares-*.patch files in $PATCHES_DIR" >&2
    exit 1
fi

python3 - "$WORK_DIR/PKGBUILD" "$HOST_PYTHON" "$PATCH_LIST" <<'PY'
import sys

path, pyver, patch_list = sys.argv[1], sys.argv[2], sys.argv[3]

pairs = []
for raw in open(patch_list, encoding="utf-8"):
    name, sha = raw.split()
    pairs.append((name, sha))

lines = open(path, encoding="utf-8").read().splitlines()
out = []
inserted_prepare = False
inserted_python = False
extra_src = " ".join(f"'{name}'" for name, _ in pairs)
extra_sha = " ".join(f"'{sha}'" for _, sha in pairs)

for line in lines:
    if line.startswith("source=("):
        line = line.rstrip(")") + f" {extra_src})"
    elif line.startswith("sha256sums=("):
        line = line.rstrip(")") + f" {extra_sha})"
    elif line.startswith("build() {") and not inserted_prepare:
        out.append("prepare() {")
        for name, _ in pairs:
            out.append(f'    patch -Np1 -d "$_pkgname-$pkgver" -i "$srcdir/{name}"')
        out.append("}")
        out.append("")
        inserted_prepare = True
    out.append(line)
    if (not inserted_python) and line.strip() == "-DBUILD_TESTING=OFF":
        # Pin distro Python so CMake does not pick ~/.local uv interpreters
        # (FindPython was linking libpython3.11 while the ISO ships 3.14).
        out.append(f"    -DPYTHONLIBS_VERSION={pyver}")
        out.append("    -DPython_ROOT_DIR=/usr")
        out.append("    -DPython_EXECUTABLE=/usr/bin/python3")
        out.append("    -DPython3_EXECUTABLE=/usr/bin/python3")
        out.append("    -DPython_FIND_VIRTUALENV=STANDARD")
        inserted_python = True

if not inserted_python:
    raise SystemExit("PKGBUILD: did not find -DBUILD_TESTING=OFF to pin PYTHONLIBS_VERSION")

open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
PY

echo "    PKGBUILD patched (source + prepare + checksum)"
churros_pkgbuild_allow_arch "$WORK_DIR/PKGBUILD"

echo "[3/4] Pre-downloading calamares source (codeberg can be flaky)..."

PKGVER="$(sed -n 's/^pkgver=//p' "$WORK_DIR/PKGBUILD")"
SRC_URL="https://codeberg.org/Calamares/calamares/releases/download/v$PKGVER/calamares-$PKGVER.tar.gz"
SRC_FILE="$WORK_DIR/calamares-$PKGVER.tar.gz"
EXPECTED_SHA="$(sed -n 's/.*sha256sums=('"'"'\([0-9a-f]*\)'"'"'.*/\1/p' "$WORK_DIR/PKGBUILD")"

CACHE_DIR="$HOME/.cache/churros-build"
mkdir -p "$CACHE_DIR"

if [[ -s "$CACHE_DIR/calamares-$PKGVER.tar.gz" ]] \
    && [[ "$(sha256sum "$CACHE_DIR/calamares-$PKGVER.tar.gz" | cut -d' ' -f1)" == "$EXPECTED_SHA" ]]; then
    echo "    Using cached source from $CACHE_DIR..."
    cp "$CACHE_DIR/calamares-$PKGVER.tar.gz" "$SRC_FILE"
elif [[ -n "${SRCDEST:-}" ]] && [[ -s "$SRCDEST/calamares-$PKGVER.tar.gz" ]] \
    && [[ "$(sha256sum "$SRCDEST/calamares-$PKGVER.tar.gz" | cut -d' ' -f1)" == "$EXPECTED_SHA" ]]; then
    echo "    Using cached source from SRCDEST..."
    cp "$SRCDEST/calamares-$PKGVER.tar.gz" "$SRC_FILE"
fi

for attempt in 1 2 3 4 5; do
    if [[ -s "$SRC_FILE" ]] && [[ "$(sha256sum "$SRC_FILE" | cut -d' ' -f1)" == "$EXPECTED_SHA" ]]; then
        echo "    Source already present and valid (attempt $attempt)."
        break
    fi
    echo "    Downloading source (attempt $attempt)..."
    rm -f "$SRC_FILE"
    if ! curl -4 -fsSL --connect-timeout 30 --max-time 900 --retry 3 --retry-delay 2 --retry-all-errors -o "$SRC_FILE" "$SRC_URL"; then
        echo "    WARNING: curl download failed (attempt $attempt), retrying in 3s..."
        rm -f "$SRC_FILE"
        sleep 3
        continue
    fi
    if [[ ! -s "$SRC_FILE" ]] || [[ "$(sha256sum "$SRC_FILE" | cut -d' ' -f1)" != "$EXPECTED_SHA" ]]; then
        echo "    WARNING: checksum mismatch or empty file, retrying..."
        rm -f "$SRC_FILE"
        sleep 2
        continue
    fi
    break
done

if [[ ! -s "$SRC_FILE" ]] || [[ "$(sha256sum "$SRC_FILE" | cut -d' ' -f1)" != "$EXPECTED_SHA" ]]; then
    echo "ERROR: could not download a valid calamares source tarball." >&2
    exit 1
fi

cp -f "$SRC_FILE" "$CACHE_DIR/calamares-$PKGVER.tar.gz" 2>/dev/null || true
echo "    Source ready: $SRC_FILE ($(du -h "$SRC_FILE" | cut -f1))"

echo "[4/4] Building calamares against Python $HOST_PYTHON (this may take a while)..."

(
    cd "$WORK_DIR"
    # Prefer /usr/bin over ~/.local so ninja/cmake helpers match the ISO.
    PATH="/usr/bin:$PATH" makepkg -sf --noconfirm --skippgpcheck
)

echo "    makepkg done."

echo "[5/5] Installing package to local repo..."

churros_copy_pkgs "$WORK_DIR" "$PACKAGE_DIR" 'calamares-*'
churros_remove_pkgs "$PACKAGE_DIR" 'calamares-debug-*' 

(
    cd "$PACKAGE_DIR"
    churros_repo_add "$PACKAGE_DIR"
)

rm -rf "$WORK_DIR"

echo "$WANT_STAMP" > "$STAMP_FILE"

echo
echo "======================================"
echo "  Calamares build complete."
echo "======================================"
echo "  Packages:"
churros_pkg_archives "$PACKAGE_DIR" 'calamares-[0-9]*' 
echo
echo "  Now run: ./churros build"
