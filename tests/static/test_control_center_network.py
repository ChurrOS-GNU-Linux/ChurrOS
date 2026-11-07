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

    def test_window_never_blocks_startup_or_overlaps_refreshes(self):
        source = testlib.read_text(testlib.ROOT / "rust/control-center/src/widgets/window.rs")
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)
        constructor = clean.split("pub fn new", 1)[1].split("fn build_header", 1)[0]
        self.assertNotIn("battery::get()", constructor,
                         "[control-center:startup-blocking] la ventana consulta upower en el main loop")
        self.assertNotIn("brightness::get()", constructor,
                         "[control-center:startup-blocking] la ventana consulta brightnessctl en el main loop")
        self.assertNotIn("audio::get_volume_status()", constructor,
                         "[control-center:startup-blocking] la ventana consulta wpctl en el main loop")
        self.assertIn("if self.refresh_in_flight.replace(true) { return; }", clean,
                      "[control-center:refresh-overlap] falta exclusión de refrescos lentos")
        self.assertIn("Rc::downgrade(self)", clean,
                      "[control-center:timer-lifetime] el timer mantiene viva la ventana")

    def test_update_page_serializes_operations_and_bounds_output(self):
        source = testlib.read_text(testlib.ROOT / "rust/preferences/src/pages/update.rs")
        code, _ = lex_rust(source)
        clean = re.sub(r"\s+", " ", code)
        update_fn = clean.split("fn run_update", 1)[1].split("fn set_log", 1)[0]
        self.assertIn("button.set_sensitive(false)", update_fn,
                      "[updates:concurrent] el botón permite lanzar varias actualizaciones")
        self.assertIn("button.set_sensitive(true)", update_fn,
                      "[updates:lifecycle] el botón no se recupera al terminar")
        self.assertIn("sync_channel::<String>(256)", update_fn,
                      "[updates:unbounded-output] la salida usa un canal sin límite")
        service = testlib.read_text(testlib.ROOT / "rust/preferences/src/services/update.rs")
        service_code, _ = lex_rust(service)
        service_clean = re.sub(r"\s+", " ", service_code)
        self.assertIn("recv_timeout(Duration::from_millis(100))", service_clean,
                      "[updates:no-deadline] los procesos de actualización pueden esperar indefinidamente")
        self.assertIn("libc::kill(-(child.id() as i32), libc::SIGKILL)", service_clean,
                      "[updates:descendants] el timeout no detiene descendientes")
