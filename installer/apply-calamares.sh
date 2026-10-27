#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

CALAMARES_SRC="$SCRIPT_DIR/calamares"
CALAMARES_DST="$PROJECT_DIR/archiso/airootfs/etc/calamares"

if [ ! -f "$CALAMARES_SRC/settings.conf" ]; then
    echo "Error: $CALAMARES_SRC/settings.conf not found." >&2
    exit 1
fi

echo "======================================"
echo "  Applying Calamares config to ISO"
echo "======================================"

mkdir -p "$CALAMARES_DST"

cp "$CALAMARES_SRC/settings.conf" "$CALAMARES_DST/"

mkdir -p "$CALAMARES_DST/branding/churros"
cp -r "$CALAMARES_SRC/branding/churros/"* "$CALAMARES_DST/branding/churros/"

mkdir -p "$CALAMARES_DST/modules"
cp "$CALAMARES_SRC/modules/"*.conf "$CALAMARES_DST/modules/"
cp "$CALAMARES_SRC/modules/"*.yaml "$CALAMARES_DST/modules/"

# Variantes por arquitectura (unpackfs, fix-boot, pacman-init) encima de las
# comunes. build.sh pasa CHURROS_ARCH; sin ella, la del equipo.
CALAMARES_ARCH="${CHURROS_ARCH:-$(uname -m)}"
if [ -d "$CALAMARES_SRC/modules/$CALAMARES_ARCH" ]; then
    cp "$CALAMARES_SRC/modules/$CALAMARES_ARCH/"*.conf "$CALAMARES_DST/modules/"
fi

echo "  Calamares config applied."
echo
echo "======================================"
echo "  Deploying PolicyKit rules"
echo "======================================"

POLKIT_DST="$PROJECT_DIR/archiso/airootfs/etc/polkit-1/rules.d"
mkdir -p "$POLKIT_DST"

cat > "$POLKIT_DST/49-calamares.rules" << 'POLKIT'
polkit.addRule(function(action, subject) {
    if (action.id == "io.calamares.calamares.pkexec.run" &&
        subject.user == "churros") {
        return polkit.Result.YES;
    }
});
POLKIT

echo "  PolicyKit rules deployed."

echo
echo "======================================"
echo "  Calamares integration complete."
echo "======================================"
