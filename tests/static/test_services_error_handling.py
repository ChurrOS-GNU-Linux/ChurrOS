"""Robustez de la capa de servicios: punteros y errores no se descartan.

Contexto (auditoría):

V3 — `home_dir()` comprobaba que `getpwuid` no devolviera NULL, pero no que
`(*pwd).pw_dir` no lo fuera. `CStr::from_ptr(NULL)` es comportamiento
indefinido, no un panic recuperable: una entrada de passwd con home vacío
lo dispara.

V6 — `repair_pending()` hacía `run(...).map(|r| r.1).unwrap_or_default()`
sobre `pacman -Qi` y `pacman -Sl`. `run` devuelve None en timeout o error de
ejecución, así que una base de datos bloqueada se colapsaba a cadena vacía,
la lista de reparaciones salía vacía y la UI decía que el sistema estaba
sano.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "rust/services/src/lib.rs"
UPDATE = ROOT / "rust/preferences/src/services/update.rs"
UPDATE_PAGE = ROOT / "rust/preferences/src/pages/update.rs"


def without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


class GetpwuidChecksPwDir(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(LIB.read_text(encoding="utf-8"))

    def test_checks_the_field_not_only_the_struct(self) -> None:
        home = self.code.split("pub fn home_dir", 1)
        self.assertEqual(len(home), 2, "home_dir tiene que existir")
        body = home[1].split("\npub fn ", 1)[0]
        self.assertIn(
            "pw_dir",
            body,
            "[services:pw-dir-null] home_dir tiene que mirar pw_dir",
        )
        self.assertNotIn(
            "CStr::from_ptr((*pwd).pw_dir)",
            body,
            "[services:pw-dir-null] CStr::from_ptr((*pwd).pw_dir) sin comprobar el "
            "campo es UB cuando pw_dir es NULL: guarda el puntero y compruébalo.",
        )
        self.assertIn(
            "raw.is_null()",
            body,
            "[services:pw-dir-null] falta la comprobación `raw.is_null()` del campo "
            "pw_dir antes de construir la CStr.",
        )


class RepairPendingReportsFailure(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(UPDATE.read_text(encoding="utf-8"))

    def test_returns_option_so_failure_is_distinguishable(self) -> None:
        self.assertIn(
            "pub fn repair_pending() -> Option<Vec<String>>",
            self.code,
            "[update:repair-option] repair_pending tiene que devolver Option: una "
            "lista vacía significa 'no hay nada' y None 'no se pudo comprobar'.",
        )

    def test_checks_pacman_exit_codes(self) -> None:
        body = self.code.split("pub fn repair_pending", 1)[1].split("\n    ///", 1)[0]
        self.assertIn(
            "query_code != 0",
            body,
            "[update:repair-exit-code] tiene que mirar el código de salida de "
            "`pacman -Qi`; antes se ignoraba y un fallo parecía 'sistema sano'.",
        )
        self.assertIn(
            "sync_code != 0",
            body,
            "[update:repair-exit-code] tiene que mirar el código de salida de `pacman -Sl`.",
        )

    def test_does_not_swallow_the_error(self) -> None:
        body = self.code.split("pub fn repair_pending", 1)[1].split("\n    ///", 1)[0]
        # Se permite unwrap_or_default en la lectura de /etc/pacman.conf (un
        # fichero ausente no es el fallo que importa); lo que no puede es
        # aplicarse al resultado de pacman.
        self.assertNotIn(
            'run(&["pacman", "-Qi"], 30_000).map(|r| r.1).unwrap_or_default()',
            body,
            "[update:repair-swallow] repair_pending no puede colapsar el resultado de "
            "pacman a cadena vacía: eso presenta una base bloqueada como sistema sano.",
        )
        self.assertNotIn(
            'run(&["pacman", "-Sl"], 30_000).map(|r| r.1).unwrap_or_default()',
            body,
            "[update:repair-swallow] lo mismo con `pacman -Sl`.",
        )


class UpdatePageShowsTheUnknownState(unittest.TestCase):
    def setUp(self) -> None:
        self.code = without_comments(UPDATE_PAGE.read_text(encoding="utf-8"))

    def test_page_reports_that_it_could_not_check(self) -> None:
        self.assertIn(
            "pending.is_none()",
            self.code,
            "[update-page:unknown] la página tiene que distinguir 'no se pudo "
            "comprobar' de 'no hay nada que reparar'.",
        )
        self.assertIn(
            "No se pudo comprobar el estado de los paquetes",
            self.code,
            "[update-page:unknown] falta el mensaje que avisa de que pacman no respondió.",
        )


if __name__ == "__main__":
    unittest.main()
