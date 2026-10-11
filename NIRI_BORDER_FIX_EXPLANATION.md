# ChurrOS Glassmorphism Issue - Actual Root Cause & Solution

## Real Problem Identified
The glassmorphism rendering issue in ChurrOS applications (`churros-welcome`, `churros-control-center`, `churros-tour`) was NOT due to GTK widget hierarchy transparency problems, but due to **Niri compositor border rendering behavior**.

## Actual Root Cause
Niri, by default, renders window borders by filling a solid rectangle behind the entire window geometry (`draw-border-with-background true`). The border colors are:
- Active windows: `#DE8636` (orange)
- Inactive windows: `#766561` (brown)

For translucent windows, this solid rectangle was visible UNDER the glass effect, completely blocking the blur effect and showing as the unwanted opaque orange/brown background.

## Solution Implemented
Set `draw-border-with-background false` in the window rules for all ChurrOS applications in Niri configuration:

```kdl
window-rule {
    match app-id="org.churros.controlcenter"
    open-floating true
    opacity 0.9
    draw-border-with-background false  // ← This fixes the issue
    background-effect {
        blur true
    }
    geometry-corner-radius 22
    clip-to-geometry true
}
```

This tells Niri to only draw the border outline around the window perimeter, allowing the blur effect to properly show through the transparent window areas.

## Files Fixed
- `archiso/airootfs/etc/skel/.config/niri/config.kdl`
- `archiso/airootfs/usr/share/churros/defaults/niri/config.kdl`

## Verification Status
✅ All ChurrOS applications now properly display glassmorphism effects
✅ Blur effects work correctly with translucent backgrounds
✅ No unwanted solid color layers visible
✅ Consistent behavior across all ChurrOS GTK4 applications

This was fixed in commit 4b04907 and is already working correctly.