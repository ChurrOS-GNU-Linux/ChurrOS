#!/usr/bin/env bash
#
# build-churros-release.sh — genera el bundle de utilidades de ChurrOS
# (churros-utils-<version>-<arch>.tar.zst) y su updates.json para publicar
# en el servidor de actualizaciones.
#
# Uso:
#   CHURROS_RELEASE_SECRET_KEY=/ruta/release.key \
#     ./scripts/build-churros-release.sh [x86_64|aarch64|i686]
#
# Produce en release/:
#   <arch>/churros-utils-<version>-<arch>.tar.zst
#   <arch>/updates.json
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUST_DIR="$PROJECT_DIR/rust"
AIROOTFS="$PROJECT_DIR/archiso/airootfs"
VERSION="$(cat "$PROJECT_DIR/VERSION")"
OUT="$PROJECT_DIR/release"
STAGE="$(mktemp -d)"
ARCH="${1:-$(uname -m)}"
SECRET_KEY="${CHURROS_RELEASE_SECRET_KEY:-}"

case "$ARCH" in
    x86_64|aarch64|i686) ;;
    *)
        echo "Error: unsupported architecture '$ARCH' (use x86_64, aarch64 or i686)." >&2
        exit 1
        ;;
esac

[ -n "$SECRET_KEY" ] || {
    echo "Error: CHURROS_RELEASE_SECRET_KEY debe apuntar a la clave minisign privada." >&2
    exit 1
}
[ -r "$SECRET_KEY" ] || {
    echo "Error: no se puede leer la clave minisign privada: $SECRET_KEY" >&2
    exit 1
}
command -v minisign >/dev/null 2>&1 || {
    echo "Error: minisign es obligatorio para publicar una release." >&2
    exit 1
}

ARCH_OUT="$OUT/$ARCH"
BUNDLE="churros-utils-${VERSION}-${ARCH}.tar.zst"

echo "==> ChurrOS release build — v${VERSION}"

# 1. Compilar las apps Rust (release)
echo "  [1/4] compilando apps Rust..."
export RUST_MIN_STACK="${RUST_MIN_STACK:-67108864}"
HOST_ARCH="$(uname -m)"
[ "$HOST_ARCH" = arm64 ] && HOST_ARCH=aarch64
case "$ARCH" in
    x86_64) TARGET_TRIPLE=x86_64-unknown-linux-gnu ;;
    aarch64) TARGET_TRIPLE=aarch64-unknown-linux-gnu ;;
    i686) TARGET_TRIPLE=i686-unknown-linux-gnu ;;
esac
CARGO_ARGS=(build --release --manifest-path "$RUST_DIR/Cargo.toml" --jobs "$(nproc)")
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST_DIR/target}"
TARGET_RELEASE="$TARGET_DIR/release"
if [ "$ARCH" != "$HOST_ARCH" ]; then
    CARGO_ARGS+=(--target "$TARGET_TRIPLE")
    TARGET_RELEASE="$TARGET_DIR/$TARGET_TRIPLE/release"
fi
cargo "${CARGO_ARGS[@]}"

# 2. Staging: binarios Rust (solo crates con deploy = true)
echo "  [2/4] montando staging..."
mkdir -p "$STAGE/usr/bin" "$STAGE/usr/local/bin" "$STAGE/etc"
for crate_dir in "$RUST_DIR"/*/; do
    [ -f "$crate_dir/Cargo.toml" ] || continue
    grep -q '^deploy = true$' "$crate_dir/Cargo.toml" || continue
    crate_name=$(sed -n 's/^name = "\(.*\)"/\1/p' "$crate_dir/Cargo.toml" | head -1)
    [ -n "$crate_name" ] || continue
    binary="$TARGET_RELEASE/$crate_name"
    [ -x "$binary" ] || {
        echo "Error: cargo no produjo el binario desplegable $binary" >&2
        exit 1
    }
    cp "$binary" "$STAGE/usr/bin/$crate_name"
    echo "    + usr/bin/$crate_name"
done

# 3. Scripts de la ISO (usr/bin y usr/local/bin)
for s in churros-apply-wallpaper churros-pick-image churros-pkexec churros-portal-start churros-update-utils; do
    if [ -f "$AIROOTFS/usr/bin/$s" ]; then
        cp "$AIROOTFS/usr/bin/$s" "$STAGE/usr/bin/$s"
        chmod 755 "$STAGE/usr/bin/$s"
        echo "    + usr/bin/$s"
    fi
done
# churros-write-root-config va con churros-settings: el Ajustes nuevo le pasa
# operaciones (greetd-autologin on|off...) que la versión anterior no entiende.
for s in churros-theme churros-update-auto churros-snapshot churros-write-root-config; do
    if [ -f "$AIROOTFS/usr/local/bin/$s" ]; then
        cp "$AIROOTFS/usr/local/bin/$s" "$STAGE/usr/local/bin/$s"
        chmod 755 "$STAGE/usr/local/bin/$s"
        echo "    + usr/local/bin/$s"
    fi
done

# 4a. Hook de rollback (snapshot antes de cada transacción de pacman)
if [ -f "$AIROOTFS/etc/pacman.d/hooks/50-churros-snapshot.hook" ]; then
    mkdir -p "$STAGE/etc/pacman.d/hooks"
    cp "$AIROOTFS/etc/pacman.d/hooks/50-churros-snapshot.hook" \
        "$STAGE/etc/pacman.d/hooks/50-churros-snapshot.hook"
    echo "    + etc/pacman.d/hooks/50-churros-snapshot.hook"
fi

# 4. Assets de /usr/share/churros (estilos, defaults, wallpapers, set-*)
if [ -d "$AIROOTFS/usr/share/churros" ]; then
    mkdir -p "$STAGE/usr/share"
    cp -r "$AIROOTFS/usr/share/churros" "$STAGE/usr/share/churros"
    echo "    + usr/share/churros"
fi
# App assets are generated from the Rust workspace and may not exist in a
# fresh checkout's ignored airootfs overlay. Stage them directly in the bundle.
bash "$SCRIPT_DIR/deploy-rust-assets.sh" "$STAGE/usr/share/churros"

# 5. Versión instalada (se autoactualiza al extraer el bundle)
echo "$VERSION" > "$STAGE/etc/churros-version"

# 6. Empaquetar bundles (unificado + por edición)
echo "  [3/4] empaquetando bundles..."
ARCH_OUT="$OUT/$ARCH"
mkdir -p "$ARCH_OUT"

# Bundle principal unificado
tar --zstd -cf "$ARCH_OUT/$BUNDLE" -C "$STAGE" usr etc
SHA_MAIN=$(sha256sum "$ARCH_OUT/$BUNDLE" | awk '{print $1}')

# Bundle Niri
BUNDLE_NIRI="churros-utils-niri-${VERSION}-${ARCH}.tar.zst"
cp "$ARCH_OUT/$BUNDLE" "$ARCH_OUT/$BUNDLE_NIRI"
SHA_NIRI="$SHA_MAIN"

# Bundle XFCE
BUNDLE_XFCE="churros-utils-xfce-${VERSION}-${ARCH}.tar.zst"
cp "$ARCH_OUT/$BUNDLE" "$ARCH_OUT/$BUNDLE_XFCE"
SHA_XFCE="$SHA_MAIN"


# 7. updates.json (manifiesto con versión + arquitectura + ediciones)
DATE=$(date +%Y-%m-%d)
cat > "$ARCH_OUT/updates.json" <<EOF
{
  "version": "$VERSION",
    "arch": "$ARCH",
  "date": "$DATE",
  "file": "$BUNDLE",
  "sha256": "$SHA_MAIN",
  "editions": {
    "niri": {
      "file": "$BUNDLE_NIRI",
      "sha256": "$SHA_NIRI"
    },
    "xfce": {
      "file": "$BUNDLE_XFCE",
      "sha256": "$SHA_XFCE"
    }
  }
}
EOF

minisign -S -s "$SECRET_KEY" -m "$ARCH_OUT/updates.json" \
    -x "$ARCH_OUT/updates.json.minisig" \
    -t "ChurrOS utilities v${VERSION} ${ARCH}"

rm -rf "$STAGE"

echo "  [4/4] listo:"
echo "    $ARCH_OUT/$BUNDLE"
echo "    $ARCH_OUT/$BUNDLE_NIRI"
echo "    $ARCH_OUT/$BUNDLE_XFCE"
echo "    $ARCH_OUT/updates.json"
echo "    $ARCH_OUT/updates.json.minisig"
echo
echo "  Sube los archivos a: https://download.churroslinux.org/churros/"
