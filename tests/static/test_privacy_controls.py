"""No presentar preferencias locales como revocación de dispositivos."""
import unittest

from tests import testlib


class PrivacyControlsTests(unittest.TestCase):
    def test_devices_are_information_not_permission_switches(self):
        page = testlib.read_text(testlib.ROOT / "rust/preferences/src/pages/privacy.rs")
        service = testlib.read_text(testlib.ROOT / "rust/preferences/src/services/privacy.rs")
        for device in ("camera", "microphone"):
            self.assertNotIn(f"PrivacyService::{device}(", page, "[privacy:no-fake-permission]")
            self.assertNotIn(f"PrivacyService::set_{device}(", page, "[privacy:no-fake-permission]")
            self.assertNotIn(f'"privacy.{device}"', service, "[privacy:no-stale-state]")
        devices = page.split('for title in ["Acceso a la cámara", "Acceso al micrófono"]', 1)[1].split(
            "page.add(permissions.widget());", 1
        )[0]
        self.assertIn("Row::new(", devices, "[privacy:informational-row]")
        self.assertNotIn("SwitchRow::new(", devices, "[privacy:informational-row]")
        self.assertIn("row.widget().set_sensitive(false);", devices, "[privacy:unavailable]")
        self.assertIn("ChurrOS no bloquea este dispositivo desde Ajustes.", devices, "[privacy:honest-disclosure]")
        self.assertIn('Some("No disponible")', devices, "[privacy:unavailable]")


if __name__ == "__main__":
    unittest.main()
