"""Cómo se lanzan los contenedores: lo que llega al motor y a X.

- `./churros run --container` (scripts/cli/run.sh) arranca QEMU en el
  contenedor y le deja usar la pantalla X del host. QEMU corre como root del
  contenedor sin la cookie de ~/.Xauthority, así que X solo lo acepta por UID:
  se autoriza ese UID (`xhost +SI:localuser:<usuario>`) y se revoca al salir.
  `xhost +local:` abría la pantalla a cualquier usuario local (capturar
  teclas, inyectar eventos) y quedaba abierta tras cerrar QEMU.
- container_run (scripts/lib/container.sh) usa el DNS del host. Un DNS fijo
  (1.1.1.1, 8.8.8.8) rompía los builds en redes con DNS interno, mirrors
  locales o salida a internet filtrada; quien lo necesite lo pasa con
  CHURROS_CONTAINER_ARGS.

Motor (podman) y xhost simulados en un PATH propio que guarda cada llamada.
No necesita contenedores, X ni red.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

from tests import testlib

ROOT = testlib.ROOT

# podman falso: guarda los argumentos; `image exists` dice que no hay imagen
# y `run` sale con FAKE_RUN_STATUS.
PODMAN = r"""#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_LOG.podman"
[ "$1 $2" = "image exists" ] && exit 1
[ "$1" = run ] && exit "${FAKE_RUN_STATUS:-0}"
exit 0
"""

# xhost falso con estado: sin argumentos lista las entradas como el real.
XHOST = r"""#!/usr/bin/env bash
state="$FAKE_LOG.xhost-state"
touch "$state"
if [ "$#" -eq 0 ]; then
    echo "access control enabled, only authorized clients can connect"
    cat "$state"
    exit 0
fi
printf '%s\n' "$*" >> "$FAKE_LOG.xhost"
case "$1" in
    +*) grep -qxF -- "${1#+}" "$state" || printf '%s\n' "${1#+}" >> "$state" ;;
    -*) grep -vxF -- "${1#-}" "$state" > "$state.new" || true; mv "$state.new" "$state" ;;
esac
"""


def expected_x_user() -> str:
    # El root del contenedor de podman sin sudo es el propio usuario.
    return "root" if os.geteuid() == 0 else getpass.getuser()


class RunContainerX11(unittest.TestCase):

    def run_container(self, preset: list[str] | None = None, status: int = 0):
        tmp = Path(tempfile.mkdtemp(prefix="churros-run-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)], check=False)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        for name, body in (("podman", PODMAN), ("xhost", XHOST)):
            (bin_dir / name).write_text(body)
            (bin_dir / name).chmod(0o755)
        log = tmp / "log"
        if preset:
            Path(f"{log}.xhost-state").write_text("".join(f"{line}\n" for line in preset))
        env = {
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp),
            "DISPLAY": ":0",
            "FAKE_LOG": str(log),
            "FAKE_RUN_STATUS": str(status),
        }
        result = subprocess.run(["bash", "scripts/cli/run.sh", "--container", "--arch", "x86_64"],
                                cwd=ROOT, env=env, capture_output=True, text=True, timeout=60)

        def read(suffix):
            path = Path(f"{log}.{suffix}")
            return path.read_text().splitlines() if path.exists() else []
        return result, read("podman"), read("xhost"), read("xhost-state")

    def test_grants_only_the_container_user_and_revokes(self):
        result, podman, xhost, state = self.run_container()
        user = expected_x_user()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(any(line.startswith("run ") for line in podman),
                        f"run.sh --container no lanzó el contenedor: {podman}\n{result.stderr}")
        self.assertEqual(xhost, [f"+SI:localuser:{user}", f"-SI:localuser:{user}"],
                         "run.sh debe autorizar en X solo al UID que corre QEMU en el contenedor y "
                         f"revocarlo al salir; llamó a xhost con: {xhost}")
        self.assertEqual(state, [], f"run.sh dejó permisos de X abiertos tras salir: {state}")

    def test_keeps_an_existing_grant_and_exit_status(self):
        user = expected_x_user()
        result, _podman, xhost, state = self.run_container(preset=[f"SI:localuser:{user}"], status=3)
        self.assertEqual(result.returncode, 3, "run.sh debe salir con el código del contenedor")
        self.assertEqual(xhost, [], f"el permiso ya existía y run.sh lo tocó: {xhost}")
        self.assertEqual(state, [f"SI:localuser:{user}"], "run.sh quitó un permiso de X que no puso él")


class ContainerRunDns(unittest.TestCase):

    def run_args(self, extra: str | None = None) -> list[str]:
        tmp = Path(tempfile.mkdtemp(prefix="churros-crun-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(tmp)], check=False)
        log = tmp / "args"
        script = (
            f"source {shlex.quote(str(ROOT / 'scripts/lib/container.sh'))}\n"
            f"fake_engine() {{ printf '%s\\n' \"$@\" > {shlex.quote(str(log))}; }}\n"
            "CONTAINER_ENGINE=(fake_engine)\n"
            "container_run -- true </dev/null\n"
        )
        env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp)}
        if extra is not None:
            env["CHURROS_CONTAINER_ARGS"] = extra
        result = subprocess.run(["bash", "-c", script], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return log.read_text().splitlines()

    def test_uses_host_dns_by_default(self):
        args = self.run_args()
        self.assertIn("run", args)
        self.assertNotIn("--dns", args,
                         "container_run fija servidores DNS: rompe redes con DNS interno o filtrado; "
                         f"que quien lo necesite use CHURROS_CONTAINER_ARGS. Argumentos: {args}")

    def test_dns_override_through_container_args(self):
        args = self.run_args("--dns 9.9.9.9")
        self.assertEqual(args.count("--dns"), 1, args)
        self.assertEqual(args[args.index("--dns") + 1], "9.9.9.9")


if __name__ == "__main__":
    unittest.main()
