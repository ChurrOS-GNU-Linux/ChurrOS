"""Máquina virtual QEMU para las pruebas de arranque (tests/vm).

Arranca una ISO (o un disco) sin pantalla y deja tres canales:

- serial.log: la consola serie (los menús de GRUB ya pasan console=ttyS0).
- QMP (qmp.sock): control de QEMU; aquí sirve para la captura de pantalla.
- QGA (qga.sock): qemu-guest-agent dentro del invitado. Todas las listas de
  paquetes con escritorio lo incluyen y su regla udev lo arranca en cuanto
  aparece el puerto virtio org.qemu.guest_agent.0, así que la prueba ejecuta
  comandos en la sesión Live sin tocar la ISO ni depender de la consola.

Solo biblioteca estándar. La usan boot_smoke.py y las pruebas que vengan
(instalación, segundo arranque).
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]


class VMError(RuntimeError):
    pass


def kvm_available() -> bool:
    return os.access("/dev/kvm", os.R_OK | os.W_OK)


def render_node() -> str | None:
    nodes = sorted(Path("/dev/dri").glob("renderD*")) if Path("/dev/dri").is_dir() else []
    return str(nodes[0]) if nodes else None


def virgl_available() -> bool:
    """QEMU puede dar 3D al invitado: con un nodo DRM, o con Mesa en un Xvfb."""
    return bool(render_node() or (shutil.which("Xvfb") and _qemu_has_display("sdl")))


def _qemu_has_display(name: str) -> bool:
    try:
        out = subprocess.run(["qemu-system-x86_64", "-display", "help"], text=True,
                             capture_output=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    return name in out.split()


def resolve_firmware(arch: str, workdir: Path) -> tuple[str, str]:
    """CODE y una copia escribible de VARS, con la misma tabla que ./churros run."""
    script = 'source scripts/lib/ovmf.sh && churros_resolve_pflash "$1" "$2"'
    result = subprocess.run(
        ["bash", "-c", script, "ovmf", arch, str(workdir)], cwd=ROOT,
        text=True, capture_output=True,
    )
    lines = result.stdout.split()
    if result.returncode != 0 or len(lines) != 2:
        raise VMError(f"no hay firmware UEFI para {arch} (instala ovmf/edk2-ovmf): {result.stderr.strip()}")
    code, vars_template = lines
    vars_copy = workdir / "efivars.fd"
    shutil.copyfile(vars_template, vars_copy)
    return code, str(vars_copy)


class _JsonSocket:
    """Socket de líneas JSON (QMP y QGA hablan el mismo formato)."""

    def __init__(self, path: Path, timeout: float):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(str(path))
        self.buffer = b""

    def send(self, message: dict) -> None:
        self.sock.sendall(json.dumps(message).encode() + b"\n")

    def recv(self) -> dict:
        while b"\n" not in self.buffer:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise VMError("el socket se cerró")
            self.buffer += chunk
        line, self.buffer = self.buffer.split(b"\n", 1)
        line = line.strip().lstrip(b"\xff")
        return json.loads(line) if line else self.recv()

    def close(self) -> None:
        self.sock.close()


class QMP:
    def __init__(self, path: Path, timeout: float = 30):
        self.conn = _JsonSocket(path, timeout)
        self.conn.recv()  # saludo
        self.execute("qmp_capabilities")

    def execute(self, command: str, **arguments) -> dict:
        message = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        self.conn.send(message)
        while True:
            reply = self.conn.recv()
            if "event" in reply:
                continue
            if "error" in reply:
                raise VMError(f"QMP {command}: {reply['error']}")
            return reply.get("return", {})

    def close(self) -> None:
        self.conn.close()


class GuestAgent:
    """Cliente mínimo de qemu-guest-agent (guest-exec con salida capturada)."""

    def __init__(self, path: Path, timeout: float = 10):
        self.conn = _JsonSocket(path, timeout)
        self.timeout = timeout
        self.token = 0

    def sync(self, timeout: float = 5) -> bool:
        """guest-sync-delimited: descarta respuestas viejas del canal.

        Antes de que el agente arranque, el puerto virtio acepta datos pero
        nadie contesta: se reintenta con un id nuevo hasta que vuelve el suyo.
        """
        self.token += 1
        token = (int(time.monotonic() * 1000) + self.token) % 2**31
        self.conn.sock.settimeout(timeout)
        try:
            self.conn.sock.sendall(b"\xff")
            self.conn.send({"execute": "guest-sync-delimited", "arguments": {"id": token}})
            while self.conn.recv().get("return") != token:
                pass
            return True
        except (OSError, json.JSONDecodeError):
            return False
        finally:
            self.conn.sock.settimeout(self.timeout)

    def call(self, command: str, **arguments):
        message = {"execute": command}
        if arguments:
            message["arguments"] = arguments
        self.conn.send(message)
        reply = self.conn.recv()
        if "error" in reply:
            raise VMError(f"QGA {command}: {reply['error'].get('desc', reply['error'])}")
        return reply.get("return")

    def exec(self, argv: list[str], timeout: float = 60, env: list[str] | None = None) -> tuple[int, str, str]:
        """Ejecuta argv como root en el invitado: (código, stdout, stderr)."""
        arguments = {"path": argv[0], "arg": argv[1:], "capture-output": True}
        if env:
            arguments["env"] = env
        pid = self.call("guest-exec", **arguments)["pid"]
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.call("guest-exec-status", pid=pid)
            if status.get("exited"):
                out = base64.b64decode(status.get("out-data", "")).decode("utf-8", "replace")
                err = base64.b64decode(status.get("err-data", "")).decode("utf-8", "replace")
                code = status.get("exitcode", 128 + status.get("signal", 0))
                return code, out, err
            time.sleep(0.5)
        raise VMError(f"'{' '.join(argv)}' no terminó en {timeout:.0f} s")

    def sh(self, script: str, timeout: float = 60) -> tuple[int, str, str]:
        return self.exec(["/bin/sh", "-c", script], timeout=timeout)

    def close(self) -> None:
        self.conn.close()


class VM:
    """Una VM de QEMU con el directorio de artefactos como estado."""

    def __init__(self, *, iso: Path | None = None, disk: Path | None = None, arch: str = "x86_64",
                 firmware: str = "uefi", memory: int = 4096, cpus: int = 4,
                 artifacts: Path, accel: str | None = None, gpu: str = "auto"):
        self.iso, self.disk, self.arch, self.firmware = iso, disk, arch, firmware
        # niri (26.04) descarta los renderizadores EGL por software: con una
        # virtio-vga sin virgl arranca sin ninguna salida y la pantalla queda
        # negra. 'virgl' da 3D al invitado (llvmpipe en el host si no hay GPU).
        self.gpu = ("virgl" if virgl_available() else "plain") if gpu == "auto" else gpu
        self.xvfb: subprocess.Popen | None = None
        self.memory, self.cpus = memory, cpus
        self.artifacts = artifacts
        self.accel = accel or ("kvm" if kvm_available() and arch == os.uname().machine else "tcg")
        self.proc: subprocess.Popen | None = None
        self.serial_log = artifacts / "serial.log"
        self.qmp_path = artifacts / "qmp.sock"
        self.qga_path = artifacts / "qga.sock"

    def command(self) -> list[str]:
        binary = {"x86_64": "qemu-system-x86_64", "aarch64": "qemu-system-aarch64", "i686": "qemu-system-i386"}[self.arch]
        if self.arch == "aarch64":
            machine = f"virt,accel={self.accel}"
            cpu = "host" if self.accel == "kvm" else "max"
        else:
            machine = f"q35,accel={self.accel}"
            cpu = "host" if self.accel == "kvm" else "max"
        cmd = [
            binary, "-machine", machine, "-cpu", cpu,
            "-smp", str(self.cpus), "-m", str(self.memory),
            *self.display_args(),
            "-serial", f"file:{self.serial_log}",
            "-qmp", f"unix:{self.qmp_path},server=on,wait=off",
            "-chardev", f"socket,path={self.qga_path},server=on,wait=off,id=qga0",
            "-device", "virtio-serial-pci",
            "-device", "virtserialport,chardev=qga0,name=org.qemu.guest_agent.0",
            "-nic", "user,model=virtio-net-pci",
            "-device", "qemu-xhci", "-device", "usb-tablet", "-device", "usb-kbd",
            "-no-reboot",
        ]
        if self.firmware == "uefi":
            code, vars_copy = resolve_firmware(self.arch, self.artifacts)
            cmd += ["-drive", f"if=pflash,format=raw,readonly=on,file={code}",
                    "-drive", f"if=pflash,format=raw,file={vars_copy}"]
        if self.iso:
            cmd += ["-device", "virtio-scsi-pci,id=scsi0",
                    "-device", "scsi-cd,bus=scsi0.0,drive=cd0,bootindex=0",
                    "-drive", f"id=cd0,if=none,format=raw,readonly=on,media=cdrom,file={self.iso}"]
        if self.disk:
            cmd += ["-drive", f"file={self.disk},if=virtio,format=qcow2"]
        return cmd

    def display_args(self) -> list[str]:
        if self.gpu != "virgl":
            return ["-display", "none", "-device", "virtio-vga" if self.arch != "aarch64" else "virtio-gpu-pci"]
        device = "virtio-vga-gl" if self.arch != "aarch64" else "virtio-gpu-gl-pci"
        node = render_node()
        if node:
            return ["-display", f"egl-headless,rendernode={node}", "-device", device]
        # Sin GPU en el host (runners de CI): la ventana SDL de QEMU vive en un
        # Xvfb privado y virglrenderer usa el GL de Mesa por software.
        return ["-display", "sdl,gl=on", "-device", device]

    def _start_xvfb(self) -> dict:
        env = dict(os.environ)
        if self.gpu != "virgl" or render_node():
            return env
        read_fd, write_fd = os.pipe()
        self.xvfb = subprocess.Popen(
            ["Xvfb", "-displayfd", str(write_fd), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
            pass_fds=(write_fd,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(write_fd)
        with os.fdopen(read_fd) as handle:
            number = handle.readline().strip()
        if not number:
            raise VMError("Xvfb no arrancó (necesario para dar 3D al invitado sin GPU en el host)")
        env["DISPLAY"] = f":{number}"
        env.setdefault("SDL_VIDEODRIVER", "x11")
        return env

    def start(self) -> None:
        self.artifacts.mkdir(parents=True, exist_ok=True)
        for path in (self.serial_log, self.qmp_path, self.qga_path):
            path.unlink(missing_ok=True)
        cmd = self.command()
        (self.artifacts / "qemu-cmdline.txt").write_text(" ".join(cmd) + "\n")
        self.log = (self.artifacts / "qemu.log").open("w")
        self.proc = subprocess.Popen(cmd, stdout=self.log, stderr=subprocess.STDOUT, env=self._start_xvfb())
        deadline = time.monotonic() + 30
        while not self.qmp_path.exists():
            if self.proc.poll() is not None:
                raise VMError(f"QEMU salió con {self.proc.returncode}: {(self.artifacts / 'qemu.log').read_text()[-2000:]}")
            if time.monotonic() > deadline:
                raise VMError("QEMU no abrió el socket QMP")
            time.sleep(0.2)

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def serial(self) -> str:
        try:
            return self.serial_log.read_text(errors="replace")
        except FileNotFoundError:
            return ""

    def wait_for_agent(self, timeout: float, abort_patterns: tuple[str, ...] = ()) -> GuestAgent:
        """Espera a que qemu-guest-agent conteste. Falla antes si el arranque muere."""
        deadline = time.monotonic() + timeout
        agent = None
        while time.monotonic() < deadline:
            if not self.running():
                raise VMError(f"QEMU terminó durante el arranque (código {self.proc.returncode})")
            serial = self.serial()
            for pattern in abort_patterns:
                if pattern in serial:
                    raise VMError(f"el arranque falló: la consola serie muestra '{pattern}'")
            if agent is None:
                try:
                    agent = GuestAgent(self.qga_path, timeout=30)
                except OSError:
                    time.sleep(2)
                    continue
            if agent.sync(timeout=5):
                return agent
        if agent:
            agent.close()
        raise VMError(f"qemu-guest-agent no respondió en {timeout:.0f} s")

    def screenshot(self, path: Path) -> Path | None:
        """Captura de la pantalla del invitado en PPM (lo admite cualquier QEMU)."""
        target = path.with_suffix(".ppm")
        try:
            qmp = QMP(self.qmp_path)
        except OSError:
            return None
        try:
            qmp.execute("screendump", filename=str(target))
            return target if target.exists() else None
        except (OSError, VMError):
            return None
        finally:
            qmp.close()

    def stop(self) -> None:
        try:
            self._stop_qemu()
        finally:
            if self.xvfb and self.xvfb.poll() is None:
                self.xvfb.terminate()
                self.xvfb.wait()

    def _stop_qemu(self) -> None:
        if not self.running():
            return
        try:
            qmp = QMP(self.qmp_path, timeout=5)
            qmp.execute("quit")
            qmp.close()
        except (OSError, VMError):
            pass
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
