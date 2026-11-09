#!/usr/bin/env bash
#
# Generates the GRUB theme assets in branding/grub-theme/ (docs/boot.md).
#
# The assets are committed: build.sh runs this on every build and it only
# creates what is missing, so an ISO build does not need ImageMagick or the
# fonts. After changing the design, run it with --regen and commit the result.
#
#   scripts/build-grub-theme.sh          create missing assets
#   scripts/build-grub-theme.sh --regen  recreate every generated asset
#
# Needs grub-mkfont (fonts), magick (images), the Inter collection
# (inter-font: Inter.ttc) and JetBrains Mono (ttf-jetbrains-mono): the brand
# typefaces in branding/typography.md. INTER_TTC and MONO_TTF override the
# Arch paths.
#
# GRUB rules this follows (checked in tests/static/test_config_syntax.py):
# - PNGs must be 8-bit RGB or RGBA: GRUB's png reader rejects palette images
#   ("png: color type not supported") and then drops the whole theme. Every
#   image is written as PNG24:/PNG32:.
# - Fonts are requested by the NAME inside the .pf2. grub-mkfont only knows
#   Regular and Bold, so SemiBold/Medium get their own family name (-n) or
#   they would all be called "Inter Regular N".
# - No spaces in file names.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THEME_DIR="$SCRIPT_DIR/../branding/grub-theme"
LOGO_SRC="$SCRIPT_DIR/../archiso/airootfs/usr/share/pixmaps/churros-logo.png"
INTER_TTC="${INTER_TTC:-/usr/share/fonts/inter/Inter.ttc}"
MONO_TTF="${MONO_TTF:-/usr/share/fonts/TTF/JetBrainsMono-Regular.ttf}"

regen=0
case "${1:-}" in
    --regen) regen=1 ;;
    "") ;;
    *) echo "build-grub-theme: opción desconocida: $1" >&2; exit 1 ;;
esac

# Latin-1 + Latin Extended-A (á é í ó ú ñ ü...), punctuation, arrows and ↵.
GLYPHS="0x20-0x7E,0xA0-0x17F,0x2010-0x2027,0x2030-0x203A,0x2190-0x2193,0x21B5-0x21B5"

need() { [ "$regen" = 1 ] || [ ! -f "$THEME_DIR/$1" ]; }

echo "======================================"
echo "  Building GRUB theme assets"
echo "======================================"
mkdir -p "$THEME_DIR/icons"

# ------------------------------------------------------------------ fonts
# file  size  face index in Inter.ttc  family override
font() {
    local file=$1 size=$2 index=$3 family=${4:-}
    need "$file" || return 0
    if ! command -v grub-mkfont >/dev/null 2>&1 || [ ! -f "$INTER_TTC" ]; then
        echo "  ! $file: falta grub-mkfont o $INTER_TTC; se mantiene la del repositorio"
        return 0
    fi
    echo "  $file"
    grub-mkfont -o "$THEME_DIR/$file" -s "$size" -i "$index" ${family:+-n "$family"} -r "$GLYPHS" "$INTER_TTC" 2>/dev/null
}
font inter-regular-18.pf2 18 0
font inter-semibold-18.pf2 18 12 "Inter SemiBold"
font inter-bold-30.pf2 30 14
font inter-medium-14.pf2 14 10 "Inter Medium"
if need jetbrains-mono-16.pf2; then
    if command -v grub-mkfont >/dev/null 2>&1 && [ -f "$MONO_TTF" ]; then
        echo "  jetbrains-mono-16.pf2"
        grub-mkfont -o "$THEME_DIR/jetbrains-mono-16.pf2" -s 16 -r "$GLYPHS" "$MONO_TTF" 2>/dev/null
    else
        echo "  ! jetbrains-mono-16.pf2: falta grub-mkfont o $MONO_TTF; se mantiene la del repositorio"
    fi
fi

# ------------------------------------------------------------------ images
if ! command -v magick >/dev/null 2>&1; then
    echo "  ! magick no está: se mantienen las imágenes del repositorio"
else
    # Rounded rectangle cut into the 9 pieces of a GRUB styled box
    # (<prefix>_nw.png ... _se.png): corners keep their radius, edges stretch.
    nine_slice() {
        local prefix=$1 radius=$2 fill=$3 stroke=${4:-none} width=${5:-0}
        need "${prefix}_c.png" || return 0
        echo "  ${prefix}_*.png"
        local size=$((radius * 2 + 1)) tmp
        tmp=$(mktemp --suffix=.png)
        magick -size "${size}x${size}" xc:none -fill "$fill" -stroke "$stroke" -strokewidth "$width" \
            -draw "roundrectangle 0,0 $((size - 1)),$((size - 1)) $radius,$radius" "PNG32:$tmp"
        local r=$radius piece
        for piece in "nw 0 0 $r $r" "n $r 0 1 $r" "ne $((r + 1)) 0 $r $r" \
                     "w 0 $r $r 1" "c $r $r 1 1" "e $((r + 1)) $r $r 1" \
                     "sw 0 $((r + 1)) $r $r" "s $r $((r + 1)) 1 $r" "se $((r + 1)) $((r + 1)) $r $r"; do
            # shellcheck disable=SC2086 # split "name x y w h"
            set -- $piece
            magick "$tmp" -crop "${4}x${5}+${2}+${3}" +repage "PNG32:$THEME_DIR/${prefix}_$1.png"
        done
        rm -f "$tmp"
    }

    # Midnight (#111827 family) with a faint orange halo behind the logo. The
    # edges are #0B1020, the theme's desktop-color, so fitheight can pad any
    # aspect ratio without a seam. Fixed seed: same input, same file.
    if need background.png; then
        echo "  background.png"
        magick -size 1920x1080 -define gradient:center=960,330 -define gradient:radii=1500,1000 \
            radial-gradient:'#172036-#0B1020' \
            \( -size 1920x1080 xc:none -fill '#F97316' -draw "ellipse 960,210 360,170 0,360" \
               -blur 0x150 -channel A -evaluate multiply 0.11 +channel \) \
            -compose over -composite -seed 7 -attenuate 0.15 +noise Uniform \
            -depth 8 -strip "PNG24:$THEME_DIR/background.png"
    fi

    nine_slice select 6 '#F97316'                                # selected entry
    nine_slice terminal_box 14 '#0B1020F2' '#F9731655' 1         # console (c) and editor (e)
    nine_slice scrollbar_thumb 2 '#F97316'
    nine_slice scrollbar_frame 2 '#FFFFFF14'

    if need logo.png; then
        echo "  logo.png"
        magick "$LOGO_SRC" -filter Lanczos -resize 72x72 "PNG32:$THEME_DIR/logo.png"
    fi

    # Entry icons by class (grub-mkconfig): grubcfg sets GRUB_DISTRIBUTOR to
    # bootloaderEntryName (ChurrOS), so 10_linux adds --class churros.
    if need icons/churros.png; then
        echo "  icons/*.png"
        magick "$LOGO_SRC" -filter Lanczos -resize 26x26 "PNG32:$THEME_DIR/icons/churros.png"
        for alias in arch gnu-linux; do
            cp "$THEME_DIR/icons/churros.png" "$THEME_DIR/icons/$alias.png"
        done
        # Generic outline icons: another system (window) and the firmware (chip).
        magick -size 104x104 xc:none -fill none -stroke '#CBD5E1' -strokewidth 7 \
            -draw "roundrectangle 10,16 94,88 10,10" -draw "line 10,36 94,36" \
            -resize 26x26 "PNG32:$THEME_DIR/icons/os.png"
        cp "$THEME_DIR/icons/os.png" "$THEME_DIR/icons/windows.png"
        magick -size 104x104 xc:none -fill none -stroke '#CBD5E1' -strokewidth 7 \
            -draw "circle 52,52 52,34" -draw "roundrectangle 20,20 84,84 14,14" \
            -resize 26x26 "PNG32:$THEME_DIR/icons/efi.png"
    fi
fi

echo
echo "======================================"
echo "  GRUB theme assets ready."
echo "======================================"
ls -la "$THEME_DIR"
