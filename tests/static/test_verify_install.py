"""verify-install: lo que enseña Calamares y el autologin elegido en el instalador.

verify-install corre al final de shellprocess@post-install y aborta la
instalación si una invariante falla. Calamares solo enseña stdout: con el
detalle solo en el log del disco, la ventana decía "There was no output from
the command". Y [initial_session] en greetd es el autologin que el usuario
puede marcar en Calamares; solo es un residuo si es del usuario del Live.

El script se ejecuta en el host con la config de greetd y el log en un
directorio temporal; el resto de comprobaciones fallan aquí (no es un sistema
instalado), y eso sirve para ver la salida. Ejecutar:
python3 -m unittest tests.static.test_verify_install -v
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import testlib

SCRIPT = testlib.AIROOTFS / "usr/share/churros/scripts/verify-install"
INSTALLED_USER = "ana"

# id(1) falso: solo existe el usuario que creó Calamares.
ID = f'''#!/usr/bin/env bash
for a in "$@"; do case "$a" in -*) ;; *) name=$a ;; esac; done
[ "${{name:-}}" = {INSTALLED_USER} ] && {{ echo "uid=1000({INSTALLED_USER})"; exit 0; }}
echo "id: '${{name:-}}': no such user" >&2
exit 1
'''


class VerifyInstall(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="churros-verify-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        fake_id = self.bin / "id"
        fake_id.write_text(ID)
        fake_id.chmod(fake_id.stat().st_mode | stat.S_IXUSR)
        self.greetd = self.tmp / "config.toml"
        self.log = self.tmp / "verify.log"

    def run_script(self, greetd_config: str):
        """(código, stdout). Solo stdout, como lo enseña Calamares; stderr se descarta."""
        self.greetd.write_text(greetd_config)
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}",
               "CHURROS_VERIFY_LOG": str(self.log), "CHURROS_GREETD_CONF": str(self.greetd)}
        result = subprocess.run(["bash", str(SCRIPT)], env=env, timeout=60, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return result.returncode, result.stdout

    def greetd_failures(self, out: str):
        """Fallos que no salen con la config del greeter sin autologin (la base del host)."""
        _, base = self.run_script(self.GREETER)
        failed = {line for line in base.splitlines() if "FALLO" in line}
        return [line for line in out.splitlines() if "FALLO" in line and line not in failed]

    GREETER = '[terminal]\nvt = 7\n\n[default_session]\ncommand = "cage -s -- regreet"\nuser = "greeter"\n'

    def test_failures_reach_stdout(self):
        code, out = self.run_script(self.GREETER)
        self.assertEqual(code, 1, "en el host fallan invariantes: tiene que abortar")
        self.assertIn("verify-install: FALLO: /etc/churros-edition legible", out,
                      "[verify-stdout] Calamares no enseña qué comprobación falló")
        self.assertRegex(out, r"verify-install: \d+ comprobaciones fallidas; detalle en ",
                         "[verify-stdout] falta el resumen con la ruta del log")
        self.assertIn("AVISO /etc/churros-edition legible", self.log.read_text())

    def test_no_autologin_is_fine(self):
        _, out = self.run_script(self.GREETER)
        self.assertNotIn("autologin", out)

    def test_autologin_chosen_in_calamares_is_fine(self):
        _, out = self.run_script(self.GREETER + f'\n[initial_session]\ncommand = "/usr/bin/churros-niri-session"\n'
                                                f'user = "{INSTALLED_USER}"\n')
        self.assertEqual(self.greetd_failures(out), [],
                         "[verify-autologin-allowed] el autologin que marcó el usuario aborta la instalación")

    def test_live_user_autologin_fails(self):
        for user_line in ('user = "churros"', "user = 'churros'", ""):
            with self.subTest(user_line=user_line):
                _, out = self.run_script(self.GREETER + f'\n[initial_session]\ncommand = "niri"\n{user_line}\n')
                self.assertTrue(self.greetd_failures(out),
                                f"[verify-live-autologin] autologin del Live sin detectar ({user_line or 'sin user'})")

    def test_user_of_another_section_is_not_the_autologin_user(self):
        """El user = "greeter" de [default_session] no cuenta como usuario del autologin."""
        _, out = self.run_script('[initial_session]\ncommand = "niri"\n\n[default_session]\n'
                                 f'command = "cage -s -- regreet"\nuser = "{INSTALLED_USER}"\n')
        self.assertTrue(self.greetd_failures(out), "[verify-live-autologin] [initial_session] sin user pasó")


if __name__ == "__main__":
    unittest.main()
