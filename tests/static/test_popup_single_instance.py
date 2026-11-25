"""Los popups no pueden duplicarse ni matar procesos ajenos.

Contexto (auditoría, A5 y V4):

A5 — `main()` miraba el pidfile con `running_name()` y solo después lo
escribía (`check-then-act`). Dos clics seguidos en Waybar mientras la primera
instancia no había escrito el pid lanzaban dos apps GTK, la segunda
sobrescribía el pid y al salir la primera borraba el pidfile de la segunda:
popups huérfanos y toggles que no apagan.

V4 — `process_is_popup` comparaba una subcadena de /proc/<pid>/cmdline
(`contains("churros-popup")`), así que un `sh -c`, un grep o un editor que
mencionara el nombre pasaba el filtro y recibía SIGTERM y luego SIGKILL si su
pid quedaba en un pidfile obsoleto.

El lock vive en churros-services (rust/services/src/single_instance.rs) y se
prueba con `cargo test -p churros-services`; aquí se comprueba el contrato del
binario, que necesita GTK y no se compila en el runner.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "rust/popups/src/main.rs"
LOCK = ROOT / "rust/services/src/single_instance.rs"


def without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


class PopupSingleInstance(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(MAIN.read_text(encoding="utf-8"))

    def test_main_takes_a_lock_before_deciding(self) -> None:
        self.assertIn(
            "single_instance::InstanceLock::acquire",
            self.code,
            "[popup:lock] main() tiene que decidir con un flock, no leyendo un "
            "pidfile y escribiéndolo después: entre las dos cosas cabe otra instancia.",
        )
        # running_name() está bien para saber *qué* popup hay abierto (toggle vs
        # reemplazo). Lo que no puede volver es decidir si hay otro corriendo con
        # una lectura previa: eso es el check-then-act.
        self.assertNotIn(
            "if running_name().as_deref() == Some(name.as_str()) { kill_popup(); return; }",
            self.code,
            "[popup:lock] main() no puede volver a decidir la instancia viva leyendo "
            "el pidfile: quién manda lo dice el flock.",
        )

    def test_launch_keeps_the_lock_alive(self) -> None:
        self.assertIn(
            "let _lock = lock;",
            self.code,
            "[popup:lock-held] launch() tiene que mantener vivo el lock mientras la "
            "ventana existe; soltarlo antes deja entrar otra instancia.",
        )

    def test_state_is_cleared_through_one_helper(self) -> None:
        self.assertIn(
            "fn clear_state()",
            self.code,
            "[popup:clear-state] borrar el pid en varios sitios es cómo la instancia "
            "A borraba el pidfile de la B. Tiene que haber un único helper.",
        )

    def test_there_is_a_lock_path_in_the_runtime_dir(self) -> None:
        self.assertIn(
            "fn lock_file()",
            self.code,
            "[popup:lock-path] falta la ruta del lock en el runtime dir de la sesión.",
        )


class PopupKillsOnlyItsOwnProcess(unittest.TestCase):
    def test_does_not_trust_the_command_line(self) -> None:
        code = without_comments(MAIN.read_text(encoding="utf-8"))
        # La comprobación tiene que basarse en /proc/<pid>/exe, no en cmdline.
        self.assertNotIn(
            "/cmdline",
            code,
            '[popup:no-cmdline-match] process_is_popup no puede leer /proc/<pid>/cmdline: '
            'cualquier proceso que mencione "churros-popup" recibiría SIGKILL. '
            "Compara /proc/<pid>/exe.",
        )
        self.assertNotIn(
            '.contains("churros-popup")',
            code,
            "[popup:no-cmdline-match] no puede quedar la comparación por subcadena.",
        )

    def test_compares_the_real_executable(self) -> None:
        code = without_comments(MAIN.read_text(encoding="utf-8"))
        self.assertIn(
            "/proc/{pid}/exe",
            code,
            "[popup:exe-check] process_is_popup tiene que comparar el ejecutable real.",
        )


class InstanceLockContract(unittest.TestCase):
    """El helper compartido tiene que ser un flock no bloqueante."""

    def setUp(self) -> None:
        self.code = without_comments(LOCK.read_text(encoding="utf-8"))

    def test_uses_a_non_blocking_flock(self) -> None:
        for needle in ("libc::flock", "LOCK_EX", "LOCK_NB"):
            self.assertIn(
                needle,
                self.code,
                f"[single-instance:{needle}] falta {needle}: el lock tiene que ser "
                "exclusivo y no bloquear al segundo intento.",
            )

    def test_second_attempt_is_reported_not_waited(self) -> None:
        self.assertIn(
            "EWOULDBLOCK",
            self.code,
            "[single-instance:wouldblock] EWOULDBLOCK es el caso normal de 'ya hay "
            "un popup vivo': tiene que devolver None, no un error.",
        )

    def test_covers_the_race_in_tests(self) -> None:
        self.assertIn(
            "second_acquire_reports_an_instance_already_running",
            self.code,
            "[single-instance:race-test] falta la prueba de dos instancias a la vez.",
        )


if __name__ == "__main__":
    unittest.main()
