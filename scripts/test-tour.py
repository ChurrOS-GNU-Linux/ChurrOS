#!/usr/bin/env python3
"""Test Tour widgets/installation using GTK Broadway, a temporary home and fake yay.

Requires the existing cargo + gtk4-broadwayd; installs nothing. The display binds
only private Unix sockets. No desktop session, terminal or package manager on the
host is modified. The GTK test is excluded from ordinary headless cargo test runs.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def main():
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
                result = subprocess.run([
                    "cargo", "test", "--offline", "--locked", "--manifest-path",
                    str(repo / "rust/Cargo.toml"), "-p", "churros-tour", "--",
                    "--include-ignored", "--test-threads=1"
                ], cwd=repo, env=env, timeout=180)
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
