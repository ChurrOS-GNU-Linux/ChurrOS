"""Comprueba la robustez de la tarjeta de red en churros-control-center sin wlan.

En ediciones de servidor o equipos sin adaptador Wi-Fi, control-center no debe
ejecutar consultas a dispositivos wlan inexistentes ni mostrar estados erróneos.
"""
from __future__ import annotations

import re
import unittest

from tests import testlib
from tests.static.test_rust_contract import lex_rust


class ControlCenterNetworkTests(unittest.TestCase):
    def test_network_widget_checks_wifi_available(self):
        """NetworkCard comprueba wifi_available directamente para evitar falsos estados."""
        source = testlib.read_text(
            testlib.ROOT / "rust/control-center/src/widgets/network.rs"
        )
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)

        self.assertIn(
            "if !info.wifi_available",
            clean,
            "[network-card:wifi-available] NetworkCard debe verificar info.wifi_available "
            "para reportar ausencia del adaptador inalámbrico.",
        )

    def test_window_guards_active_wifi_query(self):
        """window.rs solo consulta active_wifi cuando wifi está disponible."""
        source = testlib.read_text(
            testlib.ROOT / "rust/control-center/src/widgets/window.rs"
        )
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)

        self.assertTrue(
            "wifi::available()" in clean and "ActiveWifiInfo::default()" in clean,
            "[control-center:guard-wifi-active] window.rs debe comprobar wifi::available() "
            "antes de llamar a wifi::get_active() para evitar bloqueos sin interfaz inalámbrica.",
        )

    def test_services_wifi_avoids_wlan0_when_adapter_missing(self):
        """wifi.rs no debe asumir wlan0 si available() es falso."""
        source = testlib.read_text(testlib.ROOT / "rust/services/src/wifi.rs")
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)

        self.assertIn(
            "if !available() { return ActiveWifiInfo::default(); }",
            clean,
            "[services-wifi:no-wlan0-fallback] wifi::get_active() no debe asumir wlan0 "
            "si no hay interfaces inalámbricas disponibles.",
        )
