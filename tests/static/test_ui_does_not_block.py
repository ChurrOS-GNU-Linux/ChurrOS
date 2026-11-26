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


class NetworkPopupDoesNotBlock(unittest.TestCase):
    """El popup de red no puede llamar a nmcli desde un callback (A4/V5).

    `wifi::get()` encadena available(), enabled(), saved_networks() y
    `nmcli ... wifi list`, cada uno con 5 s de espera; `wifi::scan()` es otro
    nmcli y `connect` puede tardar (asociación, DHCP, handshake). En el
    callback del botón eso son decenas de segundos de ventana congelada.
    """

    def setUp(self) -> None:
        self.path = ROOT / "rust/popups/src/network.rs"
        self.code = without_comments(self.path.read_text(encoding="utf-8"))

    def test_reload_runs_nmcli_off_the_ui_thread(self) -> None:
        body = self.code.split("fn reload_async", 1)
        self.assertEqual(len(body), 2, "reload_async tiene que existir")
        chunk = body[1].split("\n    ///", 1)[0].split("\n    fn ", 1)[0]
        self.assertIn(
            "run_bg",
            chunk,
            "[popup:no-blocking-reload] reload_async tiene que hacer wifi::get() y "
            "wifi::scan() dentro de run_bg: son nmcli con 5 s de espera cada uno.",
        )
        self.assertIn(
            "wifi::get()",
            chunk,
            "[popup:no-blocking-reload] falta la llamada a wifi::get().",
        )

    def test_reload_drops_a_stale_result(self) -> None:
        """Una recarga vieja no puede pintar el interruptor después de otra."""
        body = self.code.split("fn reload_async", 1)
        self.assertEqual(len(body), 2, "reload_async tiene que existir")
        chunk = body[1].split("\n    fn ", 1)[0]
        guard = chunk.find("generation == w.generation.get()")
        assign = chunk.find("*w.last.borrow_mut() = info")
        self.assertGreater(
            guard, -1,
            "[popup:stale-reload] el resultado de reload_async tiene que comparar "
            "su generación con la actual antes de guardar el estado",
        )
        self.assertLess(
            guard, assign,
            "[popup:stale-reload] la comparación de generación tiene que ir antes "
            "de escribir last: si no, una recarga vieja enciende el interruptor",
        )
        inflight = chunk.find("if self.reloading.get()")
        run = chunk.find("run_bg")
        self.assertGreater(
            inflight, -1,
            "[popup:reload-overlap] reload_async no puede lanzar otro nmcli "
            "mientras el anterior sigue en curso",
        )
        self.assertLess(inflight, run, "[popup:reload-overlap] la guarda tiene que ir antes de run_bg")
        self.assertIn(
            "reload_pending",
            chunk,
            "[popup:reload-overlap] una petición llegada durante la recarga tiene que "
            "quedar pendiente y correr al terminar",
        )

    def test_no_nmcli_call_outside_run_bg(self) -> None:
        """Ninguna llamada a wifi::* que ejecute nmcli en el hilo de UI."""
        blocking = (
            "wifi::get()",
            "wifi::scan()",
            "wifi::connect(",
            "wifi::connect_hidden(",
            "wifi::forget(",
            "wifi::disconnect()",
        )
        offenders = []
        for number, line in enumerate(self.code.splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            if not any(call in line for call in blocking):
                continue
            # Se permite dentro de un closure que se pasa a run_bg: se mira el
            # bloque anterior más cercano.
            before = "\n".join(self.code.splitlines()[max(0, number - 12):number])
            if "run_bg" not in before:
                offenders.append(f"network.rs:{number}: {line.strip()}")
        self.assertFalse(
            offenders,
            "[popup:no-blocking-reload] llamadas a nmcli fuera de run_bg (bloquean "
            "el hilo de GTK): " + "; ".join(offenders),
        )

    def test_forget_reports_failure(self) -> None:
        forget = self.code.split("fn forget_network", 1)
        self.assertEqual(len(forget), 2, "forget_network tiene que existir")
        body = forget[1].split("\n    fn ", 1)[0]
        self.assertIn(
            "if !ok",
            body,
            "[popup:forget-reports-failure] forget_network tiene que mirar el "
            "resultado de wifi::forget: si falla, la red reaparece como guardada "
            "sin explicación (auditoría V5).",
        )


class WifiServiceReportsFailures(unittest.TestCase):
    """nmcli no puede fallar en silencio (V5).

    `run` devuelve None en timeout o error de ejecución; si el resultado se
    descarta, la UI recarga y la red reaparece como guardada sin explicación:
    el usuario no distingue «no se pudo borrar el perfil» de «no pasó nada».
    """

    def setUp(self) -> None:
        self.code = without_comments(
            (ROOT / "rust/services/src/wifi.rs").read_text(encoding="utf-8")
        )

    def test_operations_return_whether_they_worked(self) -> None:
        for name in ("forget", "disconnect", "enable", "disable"):
            self.assertIn(
                f"pub fn {name}(",
                self.code,
                f"[popup:forget-reports-failure] falta wifi::{name}",
            )
            chunk = self.code.split(f"pub fn {name}(", 1)[1]
            signature = chunk.split("{", 1)[0]
            self.assertIn(
                "-> bool",
                signature,
                f"[popup:forget-reports-failure] wifi::{name} tiene que devolver si "
                "la operación funcionó: descartar el resultado hace indistinguible un "
                "fallo de un éxito (auditoría V5).",
            )

    def test_failure_is_not_swallowed(self) -> None:
        for name in ("forget", "disconnect", "enable", "disable"):
            chunk = self.code.split(f"pub fn {name}(", 1)[1].split("\n}", 1)[0]
            self.assertNotIn(
                "let _ =",
                chunk,
                f"[popup:forget-reports-failure] wifi::{name} descarta el resultado "
                "de nmcli con `let _ =`.",
            )
