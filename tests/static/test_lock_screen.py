"""Contrato swaylock stock y confirmación de la vista previa, sin GTK ni bloqueo real."""
from __future__ import annotations

import json
from pathlib import Path
import re
import unittest

from tests import testlib
from tests.static.test_rust_contract import RustFile, lex_rust

SERVICE = testlib.ROOT / "rust/preferences/src/services/lock_screen.rs"
PAGE = testlib.ROOT / "rust/preferences/src/pages/lock_screen.rs"


def source(path: Path) -> RustFile:
    # Las cadenas de las regresiones Rust no son opciones del programa.
    code, strings = lex_rust(path.read_text().split("#[cfg(test)]", 1)[0])
    return RustFile(path, code, strings)


def restore(item: RustFile, code: str) -> str:
    return re.sub(r'"(\d+)"', lambda m: json.dumps(item.strings[int(m[1])]), code)


def function(item: RustFile, name: str) -> str:
    for found, _params, start, _body, end in item.functions():
        if found == name:
            return restore(item, item.code[start:end])
    raise AssertionError(f"Falta la función {name} en {item.path}")


class LockScreenTests(unittest.TestCase):
    def setUp(self):
        self.service = source(SERVICE)
        self.page = source(PAGE)
        self.builder = function(self.service, "build_swaylock_cmd")

    def test_stock_color_options(self):
        for key, flag in {
            "ring_color": "--ring-color",
            "inside_color": "--inside-color",
            "key_hl_color": "--key-hl-color",
            "bs_color": "--bs-hl-color",
            "separator_color": "--separator-color",
        }.items():
            with self.subTest(key=key):
                self.assertRegex(self.builder, rf'\("{key}",\s*"{flag}"\)',
                                 "[lock-stock-colors] Cada color necesita su opción larga stock")
        # El lexer compartido enmascara los literales char como 'c'.
        self.assertIn("trim_start_matches('#')", SERVICE.read_text().split("#[cfg(test)]", 1)[0])

    def test_builder_only_uses_supported_stock_options(self):
        flags = set(re.findall(r'"(-[\w-]+)"', self.builder))
        self.assertEqual(flags, {
            "--no-unlock-indicator", "--image", "--font", "--font-size",
            "--ring-color", "--inside-color", "--key-hl-color",
            "--bs-hl-color", "--separator-color",
        }, "[lock-stock-cli] No usar abreviaturas ambiguas ni efectos de swaylock-effects")
        for key in ("screenshot", "fade_in", "grace"):
            self.assertNotIn(f'"{key}"', self.builder,
                             "[lock-stock-effects] Ignorar efectos guardados por versiones antiguas")
            self.assertNotIn(f'"{key}"', function(self.service, "defaults"),
                             "[lock-stock-effects] No activar efectos en la configuración predeterminada")

    def test_ui_only_offers_supported_features(self):
        for key in ("screenshot", "fade_in", "grace"):
            self.assertNotRegex(self.page.code, rf'\b{key}\b',
                                "[lock-stock-ui] No ofrecer controles de efectos no soportados")
            self.assertNotIn(key, self.page.strings,
                             "[lock-stock-ui] No leer ni guardar efectos desde la UI")
        service = restore(self.service, self.service.code)
        self.assertRegex(service, r'INDICATORS:\s*\[&str;\s*2\]\s*=\s*\["none",\s*"auto"\]',
                         "[lock-stock-indicators] Stock solo ofrece indicador automático u oculto")
        page = function(self.page, "build")
        self.assertIn("lock_screen::INDICATORS", page)
        self.assertRegex(page, r'get\("indicator",\s*json!\("auto"\)\)\s*==\s*json!\("none"\)',
                         "[lock-stock-indicators] Normalizar tipos antiguos a auto en la UI")

    def test_preview_confirms_lock_and_returns_diagnostics(self):
        preview = function(self.service, "preview")
        self.assertRegex(preview, r'->\s*Result<\(\),\s*String>', "[lock-preview-result]")
        self.assertIn("build_swaylock_cmd(&read_data())", preview)
        self.assertIn("run_preview(&mut command)", preview)
        runner = function(self.service, "run_preview")
        self.assertIn('.arg("--daemonize")', runner,
                      "[lock-preview-daemonize] Confirmar bloqueo sin esperar al desbloqueo")
        self.assertIn(".status()", runner, "[lock-preview-status] spawn no confirma el bloqueo")
        self.assertIn("if status.success()", runner, "[lock-preview-status] Comprobar código de salida")
        self.assertIn("return Ok(())", runner)
        self.assertIn("Err(format!", runner, "[lock-preview-stderr] Devolver el error a la UI")
        self.assertIn("String::from_utf8_lossy(&detail)", runner, "[lock-preview-stderr]")
        self.assertIn("{status}", runner, "[lock-preview-stderr]")
        self.assertRegex(runner, r'stderr\s*\.read_to_end\(&mut detail\)', "[lock-preview-stderr]")

    def test_preview_does_not_wait_for_inherited_stderr_eof(self):
        runner = function(self.service, "run_preview")
        self.assertNotRegex(runner, r'\.(output|wait_with_output)\s*\(',
                            "[lock-preview-no-pipe] PAM puede mantener stderr abierto hasta el desbloqueo")
        self.assertNotIn("Stdio::piped()", runner, "[lock-preview-no-pipe]")
        self.assertIn("gio::File::new_tmp", runner, "[lock-preview-no-pipe]")
        self.assertIn("fs::remove_file(&path)", runner, "[lock-preview-no-pipe] No dejar logs temporales")
        self.assertRegex(runner, r'\.stderr\(\s*stderr\s*\.try_clone\(\)',
                         "[lock-preview-stderr] No descartar stderr")
        self.assertRegex(runner, r'stderr\s*\.rewind\(\)', "[lock-preview-stderr]")

    def test_preview_ui_runs_off_main_thread_and_shows_error(self):
        page = function(self.page, "build")
        self.assertIn("glib::spawn_future_local", page, "[lock-preview-ui-async]")
        self.assertRegex(page, r'gio::spawn_blocking\(LockScreenService::preview\)\.await',
                         "[lock-preview-ui-async] No bloquear GTK esperando al compositor")
        self.assertIn("Ok(Err(error)) => error", page, "[lock-preview-ui-error]")
        self.assertIn("gtk::AlertDialog::builder()", page, "[lock-preview-ui-error]")
        self.assertIn(".detail(&error)", page, "[lock-preview-ui-error] Mostrar stderr en el diálogo")
        self.assertIn(".show(parent.as_ref())", page, "[lock-preview-ui-error]")

    def test_idle_uses_shared_builder_and_shell_quoting(self):
        apply = function(self.service, "apply")
        self.assertIn("build_swaylock_cmd(&data)", apply, "[lock-idle-stock]")
        self.assertIn(".map(|a| sh_quote(a))", apply, "[lock-idle-quoting]")
        self.assertIn(".stderr(Stdio::inherit())", apply, "[lock-idle-diagnostics]")
        self.assertIn("if let Err(error) = cmd.spawn()", apply, "[lock-idle-diagnostics]")


if __name__ == "__main__":
    unittest.main()
