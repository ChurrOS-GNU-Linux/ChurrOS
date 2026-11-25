"""Restablecer ajustes no puede destruir la configuración del usuario.

Contexto (auditoría, issue R2): `restore_dotfiles` borraba el directorio del
usuario (`let _ = fs::remove_dir_all(&dst)`) y después copiaba
(`let _ = copy_dir_all(&src, &dst)`), descartando los dos errores, y
`reset_to_defaults` devolvía `Ok(true)` siempre. Si la copia fallaba
(permisos, disco lleno, DEFAULTS_DIR incompleto) el usuario perdía su config
de niri/foot/waybar y la UI decía "restablecidas a defaults".

Se comprueba leyendo el código porque churros-settings necesita GTK 4.22 y
el runner no lo tiene. La lógica con efectos sobre ficheros vive en
churros-services (rust/services/src/dotfiles.rs), que sí se compila y se
prueba con `cargo test -p churros-services`.
"""
from __future__ import annotations

from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
BACKUP = ROOT / "rust/preferences/src/services/backup_service.rs"
DOTFILES = ROOT / "rust/services/src/dotfiles.rs"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def without_comments(text: str) -> str:
    """Código sin comentarios de línea, para no leer una explicación como código."""
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("//")
    )


class ResetKeepsUserData(unittest.TestCase):
    def test_restore_does_not_delete_before_copying(self) -> None:
        code = without_comments(source(BACKUP))
        self.assertNotIn(
            "remove_dir_all(&dst)",
            code,
            "[backup:no-delete-first] restore_dotfiles no puede borrar el directorio "
            "del usuario y copiar después: si la copia falla, la configuración ya no "
            "está. Usa churros_services::dotfiles::replace_dir, que copia a un "
            "temporal y solo entonces sustituye.",
        )

    def test_restore_propagates_errors(self) -> None:
        code = without_comments(source(BACKUP))
        restore = code.split("fn restore_dotfiles", 1)
        self.assertEqual(len(restore), 2, "restore_dotfiles tiene que existir")
        body = restore[1].split("\n    fn ", 1)[0].split("\n    pub fn ", 1)[0]
        self.assertIn(
            "Result<(), String>",
            body,
            "[backup:restore-result] restore_dotfiles tiene que devolver Result: "
            "la UI no puede decir 'restablecido' cuando la restauración falló.",
        )
        self.assertNotIn(
            "let _ =",
            body,
            "[backup:restore-ignored-error] restore_dotfiles no puede descartar "
            "errores con `let _ =`: el fallo tiene que llegar a quien llama.",
        )

    def test_reset_returns_the_restore_error(self) -> None:
        code = without_comments(source(BACKUP))
        reset = code.split("pub fn reset_to_defaults", 1)
        self.assertEqual(len(reset), 2, "reset_to_defaults tiene que existir")
        body = reset[1].split("\n    fn ", 1)[0]
        self.assertIn(
            "Self::restore_dotfiles()?",
            body,
            "[backup:reset-propagates] reset_to_defaults tiene que propagar el error "
            "de restore_dotfiles (`?`), no ignorarlo.",
        )

    def test_noctalia_restore_propagates_errors(self) -> None:
        code = without_comments(source(BACKUP))
        noctalia = code.split("fn restore_noctalia_config", 1)
        self.assertEqual(len(noctalia), 2, "restore_noctalia_config tiene que existir")
        body = noctalia[1].split("\n}", 1)[0]
        self.assertIn(
            "io::Result<()>",
            body,
            "[backup:noctalia-result] restore_noctalia_config tiene que devolver Result.",
        )
        self.assertNotIn(
            "let _ =",
            body,
            "[backup:noctalia-ignored-error] restore_noctalia_config no puede "
            "descartar errores: una restauración parcial no es un éxito.",
        )


class ReplaceDirIsSafe(unittest.TestCase):
    """El helper que se usa para sustituir cada dotfile."""

    def setUp(self) -> None:
        self.code = without_comments(source(DOTFILES))

    def test_replaces_atomically(self) -> None:
        self.assertIn(
            "fs::rename(",
            self.code,
            "[dotfiles:atomic] replace_dir tiene que intercambiar con rename, no "
            "borrar y copiar sobre el destino.",
        )

    def test_has_tests_that_cover_the_failure(self) -> None:
        self.assertIn(
            "keeps_the_original_when_the_copy_fails",
            self.code,
            "[dotfiles:failure-test] falta la prueba de que un fallo de copia deja "
            "el directorio del usuario intacto.",
        )


if __name__ == "__main__":
    unittest.main()
