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

Cargo: con un CARGO_TARGET_DIR absoluto (el contenedor exporta
/churros/rust/target/container), cada copia compila en su propio target
(worker_target): la base parte del compartido y cada worker de lo que
compiló la base; nunca en el del repo original: cargo reconoce los crates del workspace en cualquier ruta
y decide por fecha, así que el build-rust.sh del original reutilizaría (y
metería en la ISO) un binario compilado desde una copia mutada, y dos workers
con un target común se prestarían los binarios mutados. En el contenedor van
2 workers por defecto: cada uno lleva su copia del target.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests import testlib  # noqa: E402

MUTATIONS_FILE = testlib.ROOT / "tests/mutations/mutations.toml"
KEYS = {"name", "file", "find", "find_re", "replace", "delete", "caught_by", "expect", "requires", "why"}
# None: el host (./churros test --mutations); "container": --container.
LAYERS = (None, "container")


def validate(mutations: list[dict]) -> list[dict]:
    """Rechaza entradas que no se ejecutarían nunca o no como dicen."""
    names = [m.get("name") for m in mutations]
    duplicated = {n for n in names if names.count(n) > 1}
    if duplicated:
        raise SystemExit(f"nombres de mutación repetidos: {sorted(duplicated)}")
    for mutation in mutations:
        for key in ("name", "file", "caught_by", "expect"):
            if not mutation.get(key):
                raise SystemExit(f"mutación sin '{key}': {mutation}")
        unknown = sorted(set(mutation) - KEYS)
        if unknown:
            raise SystemExit(f"mutación con claves desconocidas {unknown} (¿errata?): {mutation['name']}")
        # Un `requires` mal escrito la sacaría de todas las capas sin avisar.
        if mutation.get("requires") not in LAYERS:
            raise SystemExit(f"'requires' desconocido ({mutation['requires']!r}; vale \"container\" o nada): "
                             f"{mutation['name']}")
        if not mutation.get("delete") and ("find" in mutation) == ("find_re" in mutation):
            raise SystemExit(f"mutación sin 'find', 'find_re' ni 'delete' (o con los dos): {mutation['name']}")
    return mutations


def load_mutations() -> list[dict]:
    data = testlib.tomllib.loads(testlib.read_text(MUTATIONS_FILE))
    return validate(data.get("mutation", []))


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


# Lo que tiene una prueba, tras SIGTERM, para cerrar lo que abrió (las apps
# de scripts/test-gui-smoke.py viven en su propia sesión) antes del SIGKILL.
GRACE_SECONDS = 15
# La línea base puede compilar en frío (un target vacío o un Cargo.lock
# nuevo): las dependencias de GTK en release y en debug tardan minutos.
BASELINE_TIMEOUT = 1800


def worker_target(tmp: Path, copy: Path, seed: Path | None = None, move: bool = False) -> Path | None:
    """CARGO_TARGET_DIR propio de la copia `copy`, sembrado con otro target.

    cargo identifica los miembros del workspace por su ruta relativa a la
    raíz: todas las copias (base, workerN) comparten artefactos y fingerprints
    en un CARGO_TARGET_DIR absoluto común. Si un worker escribe su mutación
    mientras otro compila, sus ficheros quedan más viejos que el fingerprint
    del otro, cargo los da por compilados y ejecuta el binario del otro: la
    mutación sobrevive, o se le cuenta a otra, al azar. Y lo que compila una
    copia mutada lo reutilizaría el build del repo original. Sin
    CARGO_TARGET_DIR (o relativo) cada copia ya usa el suyo.

    La base se siembra con el compartido y cada worker con lo que compiló la
    base (`seed`; `move` se lo lleva sin copiar): un target frío o viejo
    (rustc nuevo tras --upgrade, Cargo.lock cambiado) se compila una vez, en
    la línea base con su plazo largo, y no otra vez en cada worker con el de
    una mutación. Sin incremental/ (solo acelera recompilar el workspace).
    Después se olvida lo compilado del workspace: sus binarios llevan dentro
    el CARGO_MANIFEST_DIR y las rutas absolutas de los include_str! de quien
    los compiló, y una prueba de una copia leería los ficheros sin mutar de
    otra. Las dependencias se quedan. Dentro de un worker, restaurar el
    fichero mutado le da una fecha nueva: cargo lo recompila.
    """
    shared = os.environ.get("CARGO_TARGET_DIR", "")
    if not os.path.isabs(shared):
        return None
    source = seed if seed is not None else Path(shared)
    target = tmp / f"target-{copy.name}"
    if not target.exists():
        if move and source.is_dir():
            shutil.move(source, target)
            shutil.rmtree(target / "incremental", ignore_errors=True)
        elif source.is_dir():
            shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns("incremental"))
        else:
            target.mkdir()
        testlib.forget_workspace_build(target)
    return target


def run(cmd: list[str], cwd: Path, timeout: float, target: Path | None = None) -> tuple[int, str]:
    """(código, salida). Al vencer el plazo termina el grupo entero (SIGTERM
    y, tras GRACE_SECONDS, SIGKILL): check.sh y el build.sh del dry run
    dejarían nietos vivos en la copia del worker, y un cargo huérfano seguiría
    compilando la copia mutada."""
    env = testlib.scratch_env(PYTHONDONTWRITEBYTECODE="1")
    if target is not None:
        env["CARGO_TARGET_DIR"] = str(target)
    proc = subprocess.Popen(cmd, cwd=cwd, env=env, text=True, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    try:
        output, _ = proc.communicate(timeout=timeout)
        return proc.returncode, output
    except subprocess.TimeoutExpired:
        # Primero SIGTERM: una prueba que lo atiende cierra lo que abrió fuera
        # de su grupo (test-gui-smoke.py: las apps y gtk4-broadwayd).
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            output, _ = proc.communicate(timeout=GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            output = None
        # Después SIGKILL al grupo entero, también si el líder ya salió.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        if output is None:
            output, _ = proc.communicate()
        return 124, (output or "") + f"\n[timeout tras {timeout:.0f} s]"


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
    subprocess.run(["git", "checkout", "-q", "HEAD", "--", mutation["file"]], cwd=copy, check=True,
                   env=testlib.scratch_env())


def evaluate(mutation: dict, copy: Path, timeout: float, target: Path | None = None) -> dict:
    """Aplica la mutación en `copy`, ejecuta su prueba y deja la copia como estaba."""
    error = apply(mutation, copy)
    if error:
        # No se tocó nada: no hay que restaurar (y un fichero que ya no
        # existe ni siquiera se podría).
        return {"mutation": mutation, "status": "stale", "detail": error}
    try:
        code, output = run(command_for(mutation["caught_by"]), copy, timeout, target)
    finally:
        restore(mutation, copy)
    if code == 0:
        status = "survived"
    elif mutation["expect"] not in output:
        status = "wrong-message"
    else:
        status = "killed"
    return {"mutation": mutation, "status": status, "detail": output}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-k", dest="filter", default="", help="solo mutaciones cuyo nombre contenga esto")
    parser.add_argument("-j", dest="jobs", type=int, default=None,
                        help="en paralelo (4 en el host; 2 con --container, cada uno con su copia del target)")
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--container", action="store_true",
                        help="solo las mutaciones que requieren el contenedor Arch")
    args = parser.parse_args()

    if args.jobs is None:
        args.jobs = min(2 if args.container else 4, os.cpu_count() or 1)
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
        base_target = worker_target(Path(tmp), base)
        if base_target is not None:
            print(f"  (cada copia compila en su propio CARGO_TARGET_DIR, como {base_target})")
        broken = False
        for caught_by in sorted({m["caught_by"] for m in mutations}):
            code, output = run(command_for(caught_by), base, max(args.timeout, BASELINE_TIMEOUT), base_target)
            print(f"  {'✓' if code == 0 else '✗'} {caught_by}")
            if code != 0:
                broken = True
                print("\n".join("      " + line for line in output.splitlines()[-30:]))
        if broken:
            print("\nLa batería ya falla sin mutaciones: arregla eso primero.")
            return 1

        workers = queue.Queue()
        targets: dict[Path, Path | None] = {}
        # El worker0 se lleva el target de la base (ya no se usa); los demás,
        # una copia: así no quedan dos copias de más en disco.
        for index in reversed(range(max(1, args.jobs))):
            copy = Path(tmp) / f"worker{index}"
            shutil.copytree(base, copy, symlinks=True)
            targets[copy] = worker_target(Path(tmp), copy, seed=base_target, move=index == 0)
            workers.put(copy)

        def in_worker(mutation: dict) -> dict:
            copy = workers.get()
            try:
                return evaluate(mutation, copy, args.timeout, targets[copy])
            finally:
                # Siempre de vuelta a la cola: una copia perdida bloquea a
                # las mutaciones que esperan en workers.get().
                workers.put(copy)

        print(f"\n== {len(mutations)} mutaciones ({args.jobs} en paralelo)")
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            results = list(pool.map(in_worker, mutations))

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
