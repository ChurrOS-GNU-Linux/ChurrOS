"""Qué ventanas abre niri flotantes y cuáles en mosaico.

En niri, varios `match` dentro de un window-rule son O: la regla de imagen
en imagen de Firefox (`match app-id="firefox"` y `match title=...` en líneas
separadas) hacía flotar todo Firefox. Los diálogos de ChurrOS (bienvenida y
recorrido) sí flotan; navegador, terminal y ajustes van en mosaico.

Ejecutar: python3 -m unittest tests.static.test_niri_window_rules -v
"""
from __future__ import annotations

import re
import unittest

from tests import testlib

CONFIGS = ("etc/skel/.config/niri/config.kdl", "usr/share/churros/defaults/niri/config.kdl")

# Apps que abren flotantes enteras: diálogos y paneles, no ventanas de trabajo.
FLOATING_APPS = {
    "pavucontrol", "dev.noctalia.Noctalia", r"^org\.churros\.popup",
    "org.churros.controlcenter", "org.churros.welcome", "org.churros.tour",
}
MUST_FLOAT = ("org.churros.welcome", "org.churros.tour")
MUST_TILE = ("firefox", "foot", "org.churros.preferences")

MATCH_PROP = re.compile(r'(app-id|title)=(r#"(.*?)"#|"((?:[^"\\]|\\.)*)")')


def window_rules(text: str):
    """[(matches, floating)]; matches = [{prop: valor}] por cada línea `match`."""
    code = re.sub(r"//[^\n]*", "", text)
    rules = []
    for body in re.findall(r"^window-rule\s*\{(.*?)^\}", code, re.S | re.M):
        matches = [{prop: raw if raw is not None and raw != "" else plain
                    for prop, _, raw, plain in MATCH_PROP.findall(line)}
                   for line in re.findall(r"^\s*match\s+(.*)$", body, re.M)]
        floating = re.search(r"^\s*open-floating\s+true\b", body, re.M) is not None
        rules.append((matches, floating))
    return rules


def floats(rules, app_id: str, title: str = "") -> bool:
    result = False
    for matches, floating in rules:
        hit = any(all(re.search(value, app_id if prop == "app-id" else title) for prop, value in m.items())
                  for m in matches if m)
        if hit:
            result = floating
    return result


class NiriWindowRules(unittest.TestCase):
    def test_only_dialogs_float_as_a_whole_app(self):
        for rel in CONFIGS:
            rules = window_rules(testlib.read_text(testlib.AIROOTFS / rel))
            for matches, floating in rules:
                if not floating:
                    continue
                for m in matches:
                    if "title" in m:
                        continue
                    self.assertIn(m.get("app-id"), FLOATING_APPS,
                                  f"[niri-floating-whole-app] {rel}: `match app-id=\"{m.get('app-id')}\"` "
                                  "sin title hace flotar todas sus ventanas (varios match son O en niri)")

    def test_expected_windows(self):
        for rel in CONFIGS:
            rules = window_rules(testlib.read_text(testlib.AIROOTFS / rel))
            for app in MUST_FLOAT:
                self.assertTrue(floats(rules, app), f"[niri-dialog-floats] {rel}: {app} no abre flotante")
            for app in MUST_TILE:
                self.assertFalse(floats(rules, app, "Mozilla Firefox"),
                                 f"[niri-app-tiles] {rel}: {app} abre flotante en vez de en mosaico")
            self.assertTrue(floats(rules, "firefox", "Picture-in-Picture"),
                            f"{rel}: la ventana de imagen en imagen de Firefox ya no flota")


if __name__ == "__main__":
    unittest.main()
