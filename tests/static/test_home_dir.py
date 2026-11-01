"""Comprueba el contrato de resolución de home_dir() en churros-services.

En entornos desatendidos o headless (como server editions o ejecución sin sesión gráfica),
la variable de entorno HOME puede no estar definida o estar vacía. home_dir() debe
recurrir a la base de datos de usuarios (passwd) mediante getpwuid(getuid()) antes de
asumir /root.
"""
from __future__ import annotations

import os
import pwd
import re
import unittest

from tests import testlib
from tests.static.test_rust_contract import lex_rust


class HomeDirFallbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = testlib.read_text(testlib.ROOT / "rust/services/src/lib.rs")
        code, strings = lex_rust(source)
        cls.source = source
        cls.code = code
        cls.strings = strings

    def test_home_dir_has_getpwuid_fallback(self):
        """home_dir() consulta passwd por UID cuando HOME no está disponible."""
        self.assertIn("pub fn home_dir(", self.code, "home_dir() no está definido en churros-services")
        func_body = self.code.split("pub fn home_dir(", 1)[1].split("pub fn home_path(", 1)[0]
        func_body = re.sub(r"\s+", " ", func_body)

        self.assertTrue(
            "libc::getpwuid" in func_body and "pw_dir" in func_body,
            "[home-dir:getpwuid-fallback] home_dir() debe consultar passwd con libc::getpwuid(uid) "
            "y leer pw_dir para resolver el directorio del usuario si HOME está ausente.",
        )

    def test_posix_getpwuid_valid_for_current_user(self):
        """Verifica que el entorno POSIX provee un pw_dir válido para el UID efectivo actual."""
        entry = pwd.getpwuid(os.getuid())
        self.assertTrue(entry.pw_dir, "pw_dir no debe estar vacío")
        self.assertTrue(entry.pw_dir.startswith("/"), "pw_dir debe ser una ruta absoluta")
