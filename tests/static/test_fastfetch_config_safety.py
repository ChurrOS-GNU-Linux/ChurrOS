"""Un config de fastfetch corrupto no puede tumbar churros-settings.

Contexto (auditoría, issue R3): `read_config()` solo cubría el error de
parseo (`unwrap_or_else(|_| json!({}))`). Un config.jsonc **válido** cuya
raíz no fuera un objeto (`[]`, `"x"`, `5`, `null`) llegaba hasta los setters,
que hacían `cfg.as_object_mut().unwrap()`, y `"logo": "texto"` disparaba el
segundo `unwrap`. Con `panic = "abort"` en release, la app moría sin diálogo.

La lógica está en churros-services (rust/services/src/nested.rs), que se
prueba con `cargo test -p churros-services`; aquí se comprueba el contrato
del fichero que usa GTK y que no se reintroduzca el patrón.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
FASTFETCH = ROOT / "rust/preferences/src/services/fastfetch_config.rs"
NESTED = ROOT / "rust/services/src/nested.rs"


def without_comments(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


class FastfetchConfigDoesNotPanic(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = FASTFETCH.read_text(encoding="utf-8")
        self.code = without_comments(self.raw)

    def test_read_config_normalizes_the_root(self) -> None:
        self.assertIn(
            "nested::as_object(",
            self.code,
            "[fastfetch:root-normalized] read_config tiene que normalizar una raíz "
            "que no sea objeto; si no, `as_object_mut().unwrap()` aborta la app.",
        )

    def test_no_unchecked_object_mutation(self) -> None:
        self.assertNotIn(
            "as_object_mut().unwrap()",
            self.code,
            "[fastfetch:no-unwrap] no puede quedar ningún `as_object_mut().unwrap()`: "
            "un config con `\"logo\": \"texto\"` o raíz `[]` mataba el proceso. "
            "Usa churros_services::nested::object_at.",
        )

    def test_object_at_is_the_shared_helper(self) -> None:
        self.assertIn(
            "nested::object_at(",
            self.code,
            "[fastfetch:shared-helper] los setters tienen que usar el helper probado "
            "en churros-services, no una copia local.",
        )


class ObjectAtContract(unittest.TestCase):
    """El helper compartido tiene que cubrir los dos disparadores de R3."""

    def setUp(self) -> None:
        self.code = without_comments(NESTED.read_text(encoding="utf-8"))

    def test_replaces_a_key_that_is_not_an_object(self) -> None:
        self.assertIn(
            "is_object",
            self.code,
            "[nested:replace-non-object] object_at tiene que sustituir una clave "
            "cuyo valor no sea un objeto (`\"logo\": \"texto\"`).",
        )

    def test_handles_a_root_that_is_not_an_object(self) -> None:
        self.assertIn(
            "*cfg = json!({})",
            self.code,
            "[nested:root-recovery] object_at tiene que recuperarse de una raíz que "
            "no sea objeto antes de indexar.",
        )

    def test_covers_both_triggers_in_tests(self) -> None:
        for name in (
            "object_at_replaces_a_key_that_is_not_an_object",
            "root_that_is_not_an_object_becomes_empty",
        ):
            self.assertIn(
                name,
                self.code,
                f"[nested:test-{name}] falta la prueba de un disparador de R3.",
            )


if __name__ == "__main__":
    unittest.main()
