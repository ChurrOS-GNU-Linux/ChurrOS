#!/usr/bin/env python3
"""Test Tour widgets/installation using GTK Broadway, a temporary home and fake yay.

Requires the existing cargo + gtk4-broadwayd; installs nothing. The display binds
only private Unix sockets. No desktop session, terminal or package manager on the
host is modified. The GTK test is excluded from ordinary headless cargo test runs.
"""
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests import testlib  # noqa: E402


def on_terminate(signum, _frame):
    # tests/mutations termina con SIGTERM la prueba que agota su plazo: así
    # corren los finally (gtk4-broadwayd, cerrojo del target de cargo).
    raise SystemExit(128 + signum)


def main():
    signal.signal(signal.SIGTERM, on_terminate)
    repo = Path(__file__).resolve().parent.parent
    for command in ("cargo", "gtk4-broadwayd"):
        if not shutil.which(command):
            raise SystemExit(f"Required existing command: {command}")
    with tempfile.TemporaryDirectory(prefix="churros-tour-test-", dir="/tmp") as tmp:
        root = Path(tmp)
        home = root / "home"
        runtime = root / "runtime"
        home.mkdir(mode=0o700)
        runtime.mkdir(mode=0o700)
        env = os.environ.copy()
        env.update({
            "CARGO_HOME": env.get("CARGO_HOME", str(Path.home() / ".cargo")),
            "HOME": str(home),
            "TOUR_TEST_HOME": str(home),
            "XDG_RUNTIME_DIR": str(runtime),
            "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"),
            "CHURROS_TOUR_PREVIEW": "1",
            "GDK_BACKEND": "broadway",
            "BROADWAY_DISPLAY": ":95",
            "GTK_A11Y": "none",
        })
        with (root / "broadway.log").open("w+") as log:
            server = subprocess.Popen([
                "gtk4-broadwayd", "--unixsocket=" + str(runtime / "http.socket"), ":95"
            ], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 5
                while not (runtime / "http.socket").exists():
                    if server.poll() is not None or time.monotonic() >= deadline:
                        log.seek(0)
                        raise SystemExit("Private GTK display failed:\n" + log.read())
                    time.sleep(0.05)
                cargo = ["cargo", "test", "--offline", "--locked", "--manifest-path",
                         str(repo / "rust/Cargo.toml"), "-p", "churros-tour"]
                # En las copias de tests/mutations el target es ajeno y compartido:
                # cerrojo y sin reutilizar lo que compiló otra copia (mutada).
                with testlib.workspace_build(testlib.cargo_target(repo), repo):
                    # Compilar puede ir en frío (el target de las copias de
                    # tests/mutations); el plazo de 180 s es para los tests.
                    built = subprocess.run(cargo + ["--no-run"], cwd=repo, env=env, timeout=3600)
                    if built.returncode != 0:
                        return built.returncode
                    result = subprocess.run(cargo + ["--", "--include-ignored", "--test-threads=1"],
                                            cwd=repo, env=env, timeout=180)
                return result.returncode
            finally:
                server.terminate()
                try:
                    server.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()


if __name__ == "__main__":
    raise SystemExit(main())
