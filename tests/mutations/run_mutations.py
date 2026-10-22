#!/usr/bin/env python3
"""Autoprueba de la batería: cada regresión sembrada tiene que hacerla fallar.

tests/mutations/mutations.toml lista cambios dañinos y realistas (quitar un
paquete, perder un permiso, desordenar Calamares, romper un script que solo
corre al arrancar...) junto con la prueba que debe detectarlos. Este script
copia el repo a un directorio temporal, aplica cada mutación por separado,
ejecuta esa prueba y exige que falle mostrando el texto esperado.

Si una mutación sobrevive (la prueba sigue en verde), alguien ha debilitado
una comprobación o ha dejado de cubrir lo que dice cubrir. Es la red contra
el "arreglo" típico de un cambio generado sin revisar: hacer pasar el CI
borrando o suavizando la prueba.

Formato de cada entrada:
  [[mutation]]
  name = "descripción corta"
  file = "ruta/relativa"
  find = "texto exacto, que aparece una sola vez"   # o delete = true
  find_re = "^foot\\n"   # en vez de find: regex (re.MULTILINE) con una sola coincidencia
  replace = "texto nuevo"   # con find_re admite \\1, \\g<nombre>
  caught_by = "tests.static.test_x"   # módulo unittest, "check" o comando de shell
  expect = "texto que debe salir en el fallo"
  requires = "container"   # opcional: solo con --container, dentro del contenedor Arch

Uso: python3 tests/mutations/run_mutations.py [-k filtro] [-j N] [--container]
(--container ejecuta solo las mutaciones de tests/container; tiene que correr
dentro del contenedor de build, como ./churros test --container.)
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import testlib  # noqa: E402

MUTATIONS_FILE = testlib.ROOT / "tests/mutations/mutations.toml"


def load_mutations() -> list[dict]:
    data = testlib.tomllib.loads(testlib.read_text(MUTATIONS_FILE))
    mutations = data.get("mutation", [])
    names = [m.get("name") for m in mutations]
    duplicated = {n for n in names if names.count(n) > 1}
    if duplicated:
        raise SystemExit(f"nombres de mutación repetidos: {sorted(duplicated)}")
    for mutation in mutations:
        for key in ("name", "file", "caught_by", "expect"):
            if not mutation.get(key):
                raise SystemExit(f"mutación sin '{key}': {mutation}")
        if not mutation.get("delete") and ("find" in mutation) == ("find_re" in mutation):
            raise SystemExit(f"mutación sin 'find', 'find_re' ni 'delete' (o con los dos): {mutation['name']}")
    return mutations


def command_for(caught_by: str) -> list[str]:
    if caught_by == "check":
        return ["bash", "scripts/cli/check.sh"]
    if caught_by.startswith("tests."):
        return [sys.executable, "-m", "unittest", caught_by]
    return ["bash", "-c", caught_by]


def make_copy(source: Path, target: Path) -> None:
    """Copia de los ficheros del repo (sin artefactos) con su propio git."""
    for path in testlib.repo_files():
        relpath = path.relative_to(source)
        dest = target / relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            dest.symlink_to(os.readlink(path))
        else:
            shutil.copy2(path, dest)
    quiet = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "env": testlib.scratch_env()}
    subprocess.run(["git", "init", "-q"], cwd=target, check=True, **quiet)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True, **quiet)
    subprocess.run(["git", "-c", "user.name=mutations", "-c", "user.email=mutations@localhost",
                    "commit", "-q", "-m", "base"], cwd=target, check=True, **quiet)


def run(cmd: list[str], cwd: Path, timeout: float) -> tuple[int, str]:
    env = testlib.scratch_env(PYTHONDONTWRITEBYTECODE="1")
    try:
        result = subprocess.run(cmd, cwd=cwd, env=env, text=True, timeout=timeout,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.stdout or "") + f"\n[timeout tras {timeout:.0f} s]"


def mutated_text(mutation: dict, root: Path) -> tuple[str | None, str | None]:
    """(texto mutado, None) o (None, motivo por el que ya no se puede aplicar)."""
    target = root / mutation["file"]
    if not target.exists():
        return None, f"{mutation['file']} no existe"
    if mutation.get("delete"):
        return "", None
    text = target.read_text(encoding="utf-8")
    replace = mutation.get("replace", "")
    if "find_re" in mutation:
        matches = list(re.finditer(mutation["find_re"], text, re.MULTILINE))
        if len(matches) != 1:
            return None, (f"'find_re' coincide {len(matches)} veces en {mutation['file']} "
                          "(tiene que ser 1): actualiza la mutación")
        match = matches[0]
        return text[:match.start()] + match.expand(replace) + text[match.end():], None
    count = text.count(mutation["find"])
    if count != 1:
        return None, f"'find' aparece {count} veces en {mutation['file']} (tiene que ser 1): actualiza la mutación"
    return text.replace(mutation["find"], replace, 1), None


def apply(mutation: dict, copy: Path) -> str | None:
    """Aplica la mutación. Devuelve un error si ya no se puede aplicar."""
    text, error = mutated_text(mutation, copy)
    if error:
        return error
    target = copy / mutation["file"]
    if mutation.get("delete"):
        target.unlink()
    else:
        target.write_text(text, encoding="utf-8")
    return None


def restore(mutation: dict, copy: Path) -> None:
    subprocess.run(["git", "checkout", "-q", "--", mutation["file"]], cwd=copy, check=True,
                   env=testlib.scratch_env())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-k", dest="filter", default="", help="solo mutaciones cuyo nombre contenga esto")
    parser.add_argument("-j", dest="jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--container", action="store_true",
                        help="solo las mutaciones que requieren el contenedor Arch")
    args = parser.parse_args()

    layer = "container" if args.container else None
    every = [m for m in load_mutations() if args.filter in m["name"]]
    mutations = [m for m in every if m.get("requires") == layer]
    if len(mutations) < len(every):
        others = "las del host" if layer else "las de tests/container (--container)"
        print(f"{len(every) - len(mutations)} mutaciones son de otra capa ({others}) y no se ejecutan aquí")
    if not mutations:
        print("no hay mutaciones que ejecutar")
        return 1
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="churros-mutations-") as tmp:
        base = Path(tmp) / "base"
        make_copy(testlib.ROOT, base)

        # Sin una línea base en verde, que una mutación "falle" no demuestra nada.
        print("== Línea base (repo sin mutar)")
        broken = False
        for caught_by in sorted({m["caught_by"] for m in mutations}):
            code, output = run(command_for(caught_by), base, args.timeout)
            print(f"  {'✓' if code == 0 else '✗'} {caught_by}")
            if code != 0:
                broken = True
                print("\n".join("      " + line for line in output.splitlines()[-30:]))
        if broken:
            print("\nLa batería ya falla sin mutaciones: arregla eso primero.")
            return 1

        workers = queue.Queue()
        for index in range(max(1, args.jobs)):
            copy = Path(tmp) / f"worker{index}"
            shutil.copytree(base, copy, symlinks=True)
            workers.put(copy)

        def evaluate(mutation: dict) -> dict:
            copy = workers.get()
            try:
                error = apply(mutation, copy)
                if error:
                    return {"mutation": mutation, "status": "stale", "detail": error}
                code, output = run(command_for(mutation["caught_by"]), copy, args.timeout)
                if code == 0:
                    status = "survived"
                elif mutation["expect"] not in output:
                    status = "wrong-message"
                else:
                    status = "killed"
                return {"mutation": mutation, "status": status, "detail": output}
            finally:
                restore(mutation, copy)
                workers.put(copy)

        print(f"\n== {len(mutations)} mutaciones ({args.jobs} en paralelo)")
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            results = list(pool.map(evaluate, mutations))

    bad = 0
    labels = {"killed": "✓", "survived": "✗ SOBREVIVE", "wrong-message": "✗ MENSAJE", "stale": "✗ OBSOLETA"}
    for result in results:
        mutation, status = result["mutation"], result["status"]
        print(f"  {labels[status]:<12} {mutation['name']}  [{mutation['caught_by']}]")
        if status != "killed":
            bad += 1
            if status == "stale":
                print(f"      {result['detail']}")
            elif status == "wrong-message":
                print(f"      la prueba falló, pero sin '{mutation['expect']}' en la salida:")
                print("\n".join("      | " + line for line in result["detail"].splitlines()[-15:]))
            else:
                print(f"      {mutation['file']}: la prueba sigue en verde con este cambio")
    print(f"\n{len(results) - bad}/{len(results)} mutaciones detectadas en {time.monotonic() - started:.0f} s")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
