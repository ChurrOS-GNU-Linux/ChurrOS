#!/usr/bin/env bash
#
# build-rust.sh — Compila las apps ChurrOS en Rust y despliega los binarios
# en archiso/airootfs/usr/bin/ (donde los wrappers python originales vivían).
#
# Cada crate del workspace produce un binario con el mismo nombre que el
# wrapper que reemplaza (p.ej. churros-welcome). Los assets se siguen
# leyendo desde /usr/share/churros/<app>/ en runtime.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUST_DIR="$PROJECT_DIR/rust"
BIN_DIR="$PROJECT_DIR/archiso/airootfs/usr/bin"
# El contenedor de build compila en otro directorio (CARGO_TARGET_DIR).
TARGET_DIR="${CARGO_TARGET_DIR:-$RUST_DIR/target}"

if [ ! -f "$RUST_DIR/Cargo.toml" ]; then
    echo "  [rust] no hay workspace en $RUST_DIR — saltando"
    exit 0
fi

# Asegurar que cargo/rust están instalados en el host
if ! command -v cargo >/dev/null 2>&1; then
    echo "  [rust] cargo no encontrado — instalando rust/cargo..."
    if command -v pacman >/dev/null 2>&1; then
        sudo pacman -S --needed --noconfirm rust cargo
    elif command -v apt >/dev/null 2>&1; then
        sudo apt update && sudo apt install -y rustc cargo
    elif command -v dnf >/dev/null 2>&1; then
        sudo dnf install -y rust cargo
    else
        echo "  [rust] ERROR: no se pudo instalar cargo automáticamente"
        echo "  Instala rust/cargo manualmente y vuelve a intentar"
        exit 1
    fi
fi

echo "[rust] Compilando apps Rust (release)..."

# Evitar stack overflow (SIGSEGV en ModuleInlinerWrapperPass de LLVM) al optimizar gtk4
export RUST_MIN_STACK="${RUST_MIN_STACK:-268435456}"

# Linker rápido si está disponible (lld); reduce drásticamente el tiempo de enlace
if command -v ld.lld >/dev/null 2>&1; then
    export RUSTFLAGS="${RUSTFLAGS:-} -C link-arg=-fuse-ld=lld"
fi

# Usar todos los núcleos disponibles para compilar en paralelo
cargo build --release --manifest-path "$RUST_DIR/Cargo.toml" --jobs "$(nproc)"

# Desplegar cada binario del workspace en airootfs/usr/bin/
# SOLO los crates marcados con [package.metadata.churros] deploy = true
# (un crate sin la marca está en port activo y aún no reemplaza al Python).
for crate_dir in "$RUST_DIR"/*/; do
    [ -f "$crate_dir/Cargo.toml" ] || continue
    grep -q '^deploy = true$' "$crate_dir/Cargo.toml" || continue
    # El nombre del binario es el "name" del package (p.ej. el crate
    # preferences/ produce churros-settings), no el del directorio.
    crate_name=$(sed -n 's/^name = "\(.*\)"/\1/p' "$crate_dir/Cargo.toml" | head -1)
    [ -n "$crate_name" ] || continue
    binary="$TARGET_DIR/release/$crate_name"
    if [ -x "$binary" ]; then
        echo "  [rust] $crate_name -> $BIN_DIR/$crate_name"
        cp "$binary" "$BIN_DIR/$crate_name"
    fi
done

# Desplegar assets de cada crate Rust a /usr/share/churros/<app>/
for crate_dir in "$RUST_DIR"/*/; do
    [ -f "$crate_dir/Cargo.toml" ] || continue
    grep -q '^deploy = true$' "$crate_dir/Cargo.toml" || continue
    crate_name=$(sed -n 's/^name = "\(.*\)"/\1/p' "$crate_dir/Cargo.toml" | head -1)
    [ -n "$crate_name" ] || continue
    # Assets: si existe directorio assets/ en el crate, copiarlo
    if [ -d "$crate_dir/assets" ]; then
        echo "  [rust] assets $crate_name -> $PROJECT_DIR/archiso/airootfs/usr/share/churros/$crate_name/"
        mkdir -p "$PROJECT_DIR/archiso/airootfs/usr/share/churros/$crate_name"
        cp -r "$crate_dir/assets" "$PROJECT_DIR/archiso/airootfs/usr/share/churros/$crate_name/"
    fi
done

echo "[rust] Apps Rust desplegadas."
