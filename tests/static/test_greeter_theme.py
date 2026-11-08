"""Pantalla de inicio (ReGreet): reloj con marcado Pango y recursos del tema.

El reloj de regreet.toml es marcado Pango (fecha pequeña arriba, hora grande
abajo; ReGreet 0.5 lo pinta con set_markup). configure-greeter-locale, que
corre al instalar, cambiaba la línea `format` entera por "fecha - hora" y
perdía ese diseño: ahora solo cambia la fecha. regreet.css pinta el logo del
avatar con url(): una ruta que no está en la ISO deja el círculo vacío.

Ejecutar: python3 -m unittest tests.static.test_greeter_theme -v
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from tests import testlib

REGREET_TOML = testlib.AIROOTFS / "etc/greetd/regreet.toml"
REGREET_CSS = testlib.AIROOTFS / "etc/greetd/regreet.css"
LOCALE_SCRIPT = testlib.AIROOTFS / "usr/share/churros/scripts/configure-greeter-locale"


class GreeterTheme(unittest.TestCase):
    def clock_format(self, toml_text: str) -> str:
        return tomllib.loads(toml_text)["widget"]["clock"]["format"]

    def run_locale(self, lang: str) -> str:
        """configure-greeter-locale sobre una copia de regreet.toml; devuelve el TOML."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "regreet.toml").write_text(testlib.read_text(REGREET_TOML))
            (tmp / "locale.conf").write_text(f"LANG={lang}\n")
            script = testlib.read_text(LOCALE_SCRIPT)
            script = script.replace("/etc/greetd/regreet.toml", str(tmp / "regreet.toml"))
            script = script.replace("/etc/locale.conf", str(tmp / "locale.conf"))
            result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return (tmp / "regreet.toml").read_text()

    def test_shipped_clock_is_date_over_large_time(self):
        fmt = self.clock_format(testlib.read_text(REGREET_TOML))
        spans = re.findall(r"<span ([^>]*)>([^<]*)</span>", fmt)
        self.assertEqual(len(spans), 2, f"[greeter-clock-markup] {fmt!r}")
        (date_attrs, date), (time_attrs, time) = spans
        self.assertIn("%B", date)
        self.assertEqual(time, "%H:%M")
        self.assertIn("\n", fmt, "fecha y hora en dos líneas")
        size = lambda attrs: int(re.search(r"size='(\d+)pt'", attrs).group(1))
        self.assertGreater(size(time_attrs), size(date_attrs) * 3, "la hora es la protagonista")

    def test_locale_script_only_translates_the_date(self):
        shipped = self.clock_format(testlib.read_text(REGREET_TOML))
        time_span = shipped[shipped.index("\n"):]
        for lang, date in (("es_ES.UTF-8", "%A, %-d de %B"), ("en_US.UTF-8", "%A, %B %-d"),
                           ("de_DE.UTF-8", "%A, %-d. %B")):
            with self.subTest(lang=lang):
                text = self.run_locale(lang)
                fmt = self.clock_format(text)  # TOML válido tras el script
                self.assertTrue(fmt.endswith(time_span),
                                f"[greeter-clock-markup] {lang}: el script rompió la hora grande: {fmt!r}")
                self.assertIn(f">{date}</span>", fmt, f"[greeter-clock-date] {lang}: {fmt!r}")
                self.assertEqual(text.count("\nformat = "), 1)

    def test_css_assets_ship(self):
        css = re.sub(r"/\*.*?\*/", "", testlib.read_text(REGREET_CSS), flags=re.S)
        urls = re.findall(r'url\("file://(/[^"]+)"\)', css)
        self.assertTrue(urls, "regreet.css ya no pinta el logo del avatar: actualiza esta prueba")
        for path in urls:
            self.assertTrue((testlib.AIROOTFS / path.lstrip("/")).is_file(),
                            f"[greeter-css-asset] regreet.css usa {path}, que no está en la ISO")


if __name__ == "__main__":
    unittest.main()
