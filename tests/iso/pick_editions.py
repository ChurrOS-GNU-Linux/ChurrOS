#!/usr/bin/env python3
"""Qué ediciones construye y arranca iso.yml, y si arranca también por BIOS.

Un pull request construye siempre niri (la que más cambia) y además cada
edición x86_64 cuyos ficheros toca: un cambio en la lista de XFCE, en el
wrapper de su sesión o en la configuración de X no lo ve la ISO niri, y sin
esto solo fallaría de madrugada, después del merge. Igual con BIOS: un cambio
en archiso/syslinux solo se nota arrancando por syslinux.

Uso (la salida va a $GITHUB_OUTPUT):
  git diff --name-only HEAD^1 HEAD | python3 tests/iso/pick_editions.py --pull-request
  python3 tests/iso/pick_editions.py --all
  python3 tests/iso/pick_editions.py --edition xfce
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import testlib  # noqa: E402

DEFAULT = "niri"
# Palabras de ruta que delatan un escritorio, además de su nombre: XFCE va
# sobre X (startx de xorg-xinit, /etc/X11).
DESKTOP_WORDS = {"xfce": ("xfce", "x11", "xinit", "xorg", "startx")}
# build.sh monta cada edición por su lado (lista, sesión, greetd): un cambio
# ahí puede romper una edición que no se nombra. La bienvenida corre en todos
# los escritorios (y tiene fallos conocidos solo en XFCE/server), y
# known_issues.toml lleva las entradas iso-*/boot-* de cada edición: un PR que
# arregla o apunta una tiene que construir esa edición antes del merge.
ALL_EDITIONS_PATHS = ("scripts/cli/build.sh", "tests/iso/pick_editions.py", "rust/churros-welcome/",
                      "tests/known_issues.toml")
# Un fichero común que decide según la edición (desktop.sh, customize_airootfs.sh,
# edition-session.sh...) afecta a todas, aunque su ruta no nombre ninguna.
BRANCHES_ON_EDITION = re.compile(r"\$\{?EDITION\b|churros-edition", re.IGNORECASE)
# Lo que solo se ejecuta arrancando por BIOS (syslinux) o lo cambia todo.
BIOS_PATHS = ("archiso/syslinux/", "archiso/profiledef.sh", "tests/vm/", ".github/workflows/iso.yml")


def editions() -> list[testlib.Edition]:
    return [item for item in testlib.EDITIONS if item.arch == "x86_64"]


def words(item: testlib.Edition) -> set[str]:
    found = {item.name, Path(item.session_cmd).name}
    found.update(DESKTOP_WORDS.get(item.desktop or "", (item.desktop or item.name,)))
    return {word.lower() for word in found}


# Solo se lee el contenido de lo que entra en la ISO (no la documentación).
CONTENT_PATHS = ("archiso/", "installer/", "branding/", "rust/", "scripts/")


def content(root: Path, path: str) -> str:
    """Texto del fichero tal como queda con el PR ('' si se borra, es binario
    o no entra en la ISO)."""
    if not path.startswith(CONTENT_PATHS) or path.endswith(".md"):
        return ""
    try:
        return (root / path).read_text(encoding="utf-8").lower()
    except (OSError, UnicodeDecodeError):
        return ""


def pick(changed: list[str], root: Path = testlib.ROOT) -> tuple[list[str], bool]:
    """(ediciones, BIOS) para un pull request que cambia `changed`.

    Cuenta la ruta y, para los ficheros que siguen existiendo, su contenido:
    el autostart de la bienvenida (OnlyShowIn=XFCE) o un script con una rama
    para XFCE no nombran la edición en la ruta.
    """
    paths = [path.strip() for path in changed if path.strip()]
    texts = {path: content(root, path) for path in paths}
    every = any(path.startswith(ALL_EDITIONS_PATHS) or BRANCHES_ON_EDITION.search(texts[path])
                for path in paths)
    chosen = [DEFAULT]
    for item in editions():
        if item.name != DEFAULT and item.name not in chosen and (
                every or any(word in path.lower() for path in paths for word in words(item))
                or any(re.search(rf"\b{re.escape(item.desktop or item.name)}\b", texts[path]) for path in paths)):
            chosen.append(item.name)
    bios = any(path.startswith(BIOS_PATHS) for path in paths)
    return chosen, bios


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--pull-request", action="store_true", help="ficheros cambiados por stdin")
    group.add_argument("--all", action="store_true", help="todas las ediciones x86_64 (noche)")
    group.add_argument("--edition", help="una edición (workflow_dispatch)")
    args = parser.parse_args()
    names = [item.name for item in editions()]
    if args.pull_request:
        chosen, bios = pick(sys.stdin.read().splitlines())
    elif args.all:
        chosen, bios = names, True
    else:
        if args.edition not in names:
            parser.error(f"edición x86_64 desconocida: {args.edition} (hay {', '.join(names)})")
        chosen, bios = [args.edition], True
    print(f"editions={json.dumps(chosen)}")
    print(f"bios={'true' if bios else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
