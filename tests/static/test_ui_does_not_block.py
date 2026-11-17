"""Guardar un ajuste de root no puede congelar la ventana de Ajustes.

Contexto (auditoría, A4): los callbacks de la página «Pantalla de inicio»
llamaban directamente a `GreeterService::set_dim()` y compañía, que terminan
en `Command::new("churros-pkexec").status()`. `.status()` espera a que el
proceso acabe; con pkexec, eso incluye el tiempo que la persona tarda en
teclear la contraseña de administrador en el diálogo de polkit. Durante ese
tiempo el bucle principal de GTK está parado: la ventana no repinta y el
compositor puede marcarla como «no responde».

La forma correcta (que ya usaban pages/update.rs y pages/logs.rs) es lanzar el
trabajo en un hilo y sondear el resultado con glib::timeout_add_local. Ese
patrón vive ahora en churros_services::background, con sus pruebas.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
GREETER_PAGE = ROOT / "rust/preferences/src/pages/greeter.rs"
BACKGROUND = ROOT / "rust/services/src/background.rs"


def without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


class GreeterDoesNotBlockTheUi(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(GREETER_PAGE.read_text(encoding="utf-8"))

    def test_pkexec_paths_go_through_the_background_helper(self) -> None:
        """Las cinco rutas que piden contraseña usan apply_in_background."""
        self.assertIn(
            "fn apply_in_background",
            self.code,
            "[greeter:background] falta el helper que ejecuta en un hilo",
        )
        for call in (
            "GreeterService::set_dim",
            "GreeterService::set_clock",
            "GreeterService::set_accent",
            "GreeterService::set_avatar",
            "UsersService::set_regreet_greeting",
        ):
            count = self.code.count(call)
            self.assertGreater(count, 0, f"{call} tiene que seguir existiendo")
            # Cada llamada tiene que estar dentro del closure que se pasa a
            # apply_in_background: se mira hacia atrás hasta el cierre del
            # helper ("// ===" o 900 caracteres).
            for chunk in self.code.split(call)[:-1]:
                tail = chunk[-900:]
                self.assertIn(
                    "apply_in_background",
                    tail,
                    f"[greeter:background] {call} se llama fuera de "
                    "apply_in_background: el callback bloquea el hilo de GTK "
                    "mientras polkit pide la contraseña.",
                )

    def test_no_blocking_status_in_the_page(self) -> None:
        self.assertNotIn(
            ".status()",
            self.code,
            "[greeter:blocking] la página no puede llamar a .status() en un "
            "callback: bloquea el bucle de GTK.",
        )


class BackgroundHelperContract(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(BACKGROUND.read_text(encoding="utf-8"))

    def test_polls_without_blocking(self) -> None:
        self.assertIn(
            "try_recv",
            self.code,
            "[background:non-blocking] el sondeo tiene que usar try_recv: recv "
            "bloquearía igual que la llamada directa.",
        )

    def test_reports_a_panicked_thread(self) -> None:
        self.assertIn(
            "Disconnected",
            self.code,
            "[background:panic] si el hilo entra en pánico, la UI tiene que "
            "enterarse y rehabilitar el control, no esperar para siempre.",
        )

    def test_covers_the_panic_in_tests(self) -> None:
        self.assertIn(
            "reports_disconnected_when_the_thread_panics",
            self.code,
            "[background:panic-test] falta la prueba del hilo que entra en pánico.",
        )


if __name__ == "__main__":
    unittest.main()
