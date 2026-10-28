#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RUST_DIR="$PROJECT_DIR/rust"
DEST_DIR="${1:-$PROJECT_DIR/archiso/airootfs/usr/share/churros}"

for crate_dir in "$RUST_DIR"/*/; do
    [ -f "$crate_dir/Cargo.toml" ] || continue
    grep -q '^deploy = true$' "$crate_dir/Cargo.toml" || continue
    crate_name=$(sed -n 's/^name = "\(.*\)"/\1/p' "$crate_dir/Cargo.toml" | head -1)
    [ -n "$crate_name" ] || continue
    [ -d "$crate_dir/assets" ] || continue

    asset_dest="$DEST_DIR/$crate_name/assets"
    mkdir -p "$asset_dest"
    cp -R "$crate_dir/assets/." "$asset_dest/"
    echo "  [rust] assets $crate_name -> $asset_dest/"
done
