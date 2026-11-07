#!/usr/bin/env python3
"""Texto que recibe OpenCode para mover la VM. Las teclas son qcodes de QMP.

QEMU rechaza super, Super_L y meta. La tecla Mod/Super es meta_l.
"""
from __future__ import annotations

import argparse
import sys


def build_prompt(qmp: str, vnc: str, out: str, vmctl: str, screens: list[str]) -> str:
    lines = [
        "Capture screenshots of a running ChurrOS live ISO. Do not print API keys or tokens.",
        f"QMP socket: {qmp}",
        f"VNC (localhost only): {vnc}",
        "Drive the VM only through this helper:",
        f"  python3 {vmctl} screendump --socket {qmp} --out {out}/NAME.png",
        f"  python3 {vmctl} send-key --socket {qmp} --key KEY [--key KEY]",
        f"  python3 {vmctl} wait-serial --log {out}/serial.log --pattern REGEX --timeout SECONDS",
        "A graphical frame is already on screen. Do not treat kernel text or a black screen as the desktop.",
        "The live user churros logs in automatically once that session is up.",
        "Key names are QEMU qcodes. The Mod/Super key is meta_l.",
        "Do not send super, Super_L or meta: QMP rejects them.",
        "meta_l+spc opens the Noctalia launcher.",
        "meta_l+shift+e opens wlogout. ret confirms.",
        "Calamares is /usr/local/bin/calamares.",
        "The hotkey overlay and wlogout are already closed.",
        "Do not write initial.png or any other file in the output directory.",
        "Write exactly these files and then exit:",
    ]
    for screen in screens:
        lines.append(f"- {out}/{screen}.png ({screen})")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt de OpenCode para la captura.")
    parser.add_argument("--qmp", required=True)
    parser.add_argument("--vnc", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--vmctl", required=True)
    parser.add_argument("--screens", nargs="*", default=[])
    args = parser.parse_args(argv)
    sys.stdout.write(build_prompt(args.qmp, args.vnc, args.out, args.vmctl, list(args.screens)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
