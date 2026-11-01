"""Comprueba el aislamiento y atomicidad de settings.ini en churros-settings.

En GTK4, modificar ~/.config/gtk-4.0/settings.ini en caliente dispara la recarga
inotify de CSS de GTK4 y cierra o bloquea las ventanas de la aplicación.
ThemeService, CursorService e IconsService deben limitar la escritura en caliente a
gtk-3.0 y realizar escrituras atómicas mediante rename para evitar condiciones de carrera.
"""
from __future__ import annotations

import re
import unittest

from tests import testlib
from tests.static.test_rust_contract import lex_rust


class GtkSettingsIsolationTests(unittest.TestCase):
    def test_cursor_service_avoids_gtk4_in_hot_path(self):
        """CursorService no debe escribir en gtk-4.0/settings.ini a runtime."""
        source = testlib.read_text(
            testlib.ROOT / "rust/preferences/src/services/cursor.rs"
        )
        clean = re.sub(r"\s+", " ", source)
        func = clean.split("fn write_gtk_ini(", 1)[1].split("fn apply_live_cursor_theme(", 1)[0]

        self.assertNotIn(
            "gtk-4.0",
            func,
            "[gtk-isolation:cursor-no-gtk4] CursorService no debe modificar gtk-4.0/settings.ini en caliente",
        )
        self.assertIn(
            "update_ini_key",
            func,
            "[gtk-isolation:cursor-atomic] CursorService debe usar update_ini_key para escritura atómica",
        )

    def test_icons_service_avoids_gtk4_in_hot_path(self):
        """IconsService no debe escribir en gtk-4.0/settings.ini a runtime."""
        source = testlib.read_text(
            testlib.ROOT / "rust/preferences/src/services/icons.rs"
        )
        clean = re.sub(r"\s+", " ", source)
        func = clean.split("fn write_gtk_ini(", 1)[1].split("fn apply_live_icon_theme(", 1)[0]

        self.assertNotIn(
            "gtk-4.0",
            func,
            "[gtk-isolation:icons-no-gtk4] IconsService no debe modificar gtk-4.0/settings.ini en caliente",
        )
        self.assertIn(
            "update_ini_key",
            func,
            "[gtk-isolation:icons-atomic] IconsService debe usar update_ini_key para escritura atómica",
        )

    def test_theme_update_ini_key_is_atomic(self):
        """ThemeService::update_ini_key utiliza fs::rename para reemplazo atómico."""
        source = testlib.read_text(
            testlib.ROOT / "rust/preferences/src/services/theme.rs"
        )
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)
        func = clean.split("fn update_ini_key(", 1)[1].split("fn migrate_adwaita_dark_ini(", 1)[0]

        self.assertTrue(
            "fs::rename" in func or "rename(" in func,
            "[gtk-isolation:atomic-rename] update_ini_key debe usar rename para garantizar escrituras atómicas",
        )
