"""Sintaxis, ShellCheck y shebang de todos los scripts de shell del repo.

check.sh solo revisa `git ls-files '*.sh' churros`: los scripts sin extensión
que corren en la ISO (usr/bin/churros-niri-session, usr/local/bin/churros-xsession,
churros-snapshot, usr/share/churros/scripts/verify-install...) nunca pasan
por `bash -n` ni ShellCheck. Aquí se buscan por shebang
(testlib.shell_scripts), con los ficheros nuevos aún sin `git add`.

- Sintaxis: `bash -n` (bash), `bash --posix -n` (sh: en Arch /bin/sh es
  bash, que con ese nombre arranca en modo POSIX) y `zsh -f -n` (.zlogin y
  .zshrc: zsh es la shell de root y del usuario Live). Un subtest por fichero;
  cualquier aviso cuenta (un heredoc sin cerrar solo da un warning y se come
  el resto del script).
- ShellCheck: `shellcheck -S error -s <dialecto>` en lotes paralelos. El
  dialecto sale del shebang, así que los ficheros sin extensión se analizan
  igual que los .sh. Los hallazgos actuales van a tests/known_issues.toml.
- Shebang: todo lo que se ejecuta directamente en el airootfs (los
  directorios de test_file_permissions.EXEC_DIRS y las rutas que lanzan
  unidades, hooks, greetd, niri, Calamares o los propios scripts) empieza por
  un #! válido: sin BOM ni CR, intérprete absoluto, `env` con un solo
  argumento (Linux le pasa el resto de la línea como uno) e intérprete
  instalado en todas las ediciones (todas copian el mismo airootfs). Una
  biblioteca para `source` (sin #!, con `# shellcheck shell=`, como
  edition-session.sh) no puede aparecer como programa en ninguno de esos sitios.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import unittest

from tests import testlib
from tests.static.test_file_permissions import (
    airootfs_exec_references, airootfs_files, exec_dir_files, head, is_elf,
    is_sourced_library, link_target,
)

SYNTAX = {"bash": ["bash", "-n"], "sh": ["bash", "--posix", "-n"], "zsh": ["zsh", "-f", "-n"]}

# Paquete de Arch que instala cada intérprete (/usr/bin/sh es de bash). El
# resto se resuelve con testlib.resolve_command (airootfs, crates, paquetes).
INTERPRETER_PACKAGES = {
    "sh": "bash", "bash": "bash", "env": "coreutils", "zsh": "zsh",
    "python": "python", "python3": "python", "perl": "perl", "node": "nodejs",
}
SYSTEM_BIN_DIRS = {"/bin", "/sbin", "/usr/bin", "/usr/sbin"}  # en Arch, symlinks a /usr/bin


def interpreter_missing(name: str, absolute: str | None) -> list[str]:
    """Ediciones en las que no está el intérprete `name` (o la ruta `absolute`)."""
    missing = []
    for item in testlib.EDITIONS:
        package = INTERPRETER_PACKAGES.get(name)
        if absolute and os.path.dirname(absolute) not in SYSTEM_BIN_DIRS:
            ok = link_target(absolute) is not None or testlib.resolve_command(absolute, item).ok
        elif package:
            ok = package in testlib.installed(item)
        else:
            ok = testlib.resolve_command(name, item).ok
        if not ok:
            missing.append(item.id)
    return missing


def shebang_problem(path: Path) -> str | None:
    """Por qué el kernel no podría ejecutar `path` como script (None si puede)."""
    data = head(path, 512)
    if data.startswith(b"\xef\xbb\xbf"):
        return "empieza por un BOM UTF-8: el kernel no ve el #! (Exec format error)"
    if not data.startswith(b"#!"):
        return "no empieza por #!: systemd, pacman y execve fallan con 'Exec format error'"
    line = data.split(b"\n", 1)[0][2:]
    if line.endswith(b"\r"):
        return "la línea #! acaba en CR (fin de línea CRLF): el intérprete se busca con '\\r' en el nombre y no existe"
    words = line.decode("utf-8", "replace").split()
    if not words:
        return "#! sin intérprete"
    if not words[0].startswith("/"):
        return f"el intérprete '{words[0]}' no es una ruta absoluta: el kernel no lo busca en PATH"
    if Path(words[0]).name == "env":
        if len(words) > 2 and not words[1].startswith("-S"):
            return (f"'#!{line.decode(errors='replace').strip()}': Linux pasa '{' '.join(words[1:])}' a env "
                    f"como un solo argumento y env no encuentra ese programa (usa `env -S` o quita las opciones)")
        names = [word for word in words[1:] if not word.startswith("-")]
        if not names:
            return "#!/usr/bin/env sin programa"
        name, absolute = names[0], None
    else:
        name, absolute = Path(words[0]).name, words[0]
    missing = interpreter_missing(name, absolute)
    if missing:
        return f"el intérprete '{name}' no está instalado en {', '.join(missing)} (todas las ediciones copian el mismo airootfs)"
    return None


class ShellScripts(unittest.TestCase):
    def setUp(self):
        self.scripts = testlib.shell_scripts()
        self.assertGreater(len(self.scripts), 30, "testlib.shell_scripts() apenas encuentra scripts: ¿cambió la búsqueda?")

    def test_syntax(self):
        """bash -n / bash --posix -n / zsh -n sin errores ni avisos, fichero a fichero."""
        for path, dialect in self.scripts:
            with self.subTest(script=testlib.rel(path)):
                command = SYNTAX[dialect]
                testlib.require_tool(self, command[0])
                result = testlib.run([*command, str(path)], timeout=30)
                self.assertTrue(result.returncode == 0 and not result.stdout.strip(),
                                f"{testlib.rel(path)}: `{' '.join(command)}` falla (salida {result.returncode}):\n"
                                f"{result.stdout.strip()}")

    def test_shellcheck(self):
        """shellcheck -S error con el dialecto del shebang, también sin extensión."""
        shellcheck = testlib.require_tool(self, "shellcheck")
        batches = []
        for dialect in ("bash", "sh"):
            files = [testlib.rel(path) for path, d in self.scripts if d == dialect]
            batches += [(dialect, files[i:i + 8]) for i in range(0, len(files), 8)]

        def check(batch):
            dialect, files = batch
            result = subprocess.run([shellcheck, "-S", "error", "-f", "json1", "-s", dialect, *files],
                                    cwd=testlib.ROOT, capture_output=True, text=True, timeout=120)
            # 0: limpio; 1: hay hallazgos; otro: no pudo leer algún fichero u opción inválida.
            if result.returncode not in (0, 1):
                raise AssertionError(f"shellcheck salió con {result.returncode} en {files}:\n{result.stderr}{result.stdout}")
            return json.loads(result.stdout or "{}").get("comments", [])

        with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
            comments = [c for found in pool.map(check, batches) for c in found]
        findings: dict[str, list[str]] = {}
        for c in sorted(comments, key=lambda c: (c["file"], c["line"], c["column"])):
            findings.setdefault(f"shellcheck:{c['file']}:SC{c['code']}", []).append(
                f"{c['file']}:{c['line']}:{c['column']}: SC{c['code']} {c['message']}")
        testlib.assert_findings(self, "shellcheck", {key: " | ".join(msgs) for key, msgs in findings.items()})

    def test_executables_have_valid_shebang(self):
        """Lo que se ejecuta directamente tiene #! válido; las bibliotecas no se ejecutan."""
        findings = {}
        for abs_path, why in exec_dir_files().items():
            path = airootfs_files()[abs_path]
            problem = None if is_elf(path) else shebang_problem(path)
            if problem:
                findings[f"shebang:{abs_path}"] = f"{abs_path} ({why}): {problem}"
        for abs_path, origins in airootfs_exec_references(self).items():
            path = airootfs_files()[abs_path]
            who = ", ".join(sorted(origins))
            if is_elf(path):
                continue
            if is_sourced_library(path):
                findings[f"shebang:{abs_path}"] = (
                    f"{abs_path} es una biblioteca para cargar con `.` (sin #!, con `# shellcheck shell=`) y "
                    f"{who} la ejecuta como programa: cárgala con `. {abs_path}`")
            elif problem := shebang_problem(path):
                findings[f"shebang:{abs_path}"] = f"{abs_path} (lo ejecuta {who}): {problem}"
        testlib.assert_findings(self, "shebang", findings)


if __name__ == "__main__":
    unittest.main()
