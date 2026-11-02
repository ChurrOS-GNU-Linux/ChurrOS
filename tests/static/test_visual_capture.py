"""Plan de pantallas, PNG y el manifiesto en seco de la captura.

No arranca QEMU ni descarga artefactos.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

from tests import testlib

ROOT = testlib.ROOT


def load(name: str, filename: str):
    path = ROOT / "scripts/qa/visual" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


screens = load("visual_screens", "screens.py")
imageutil = load("visual_imageutil", "imageutil.py")


class ScreenPlan(unittest.TestCase):
    def test_order_is_stable_and_specific(self):
        chosen = screens.screens_for_paths([
            "branding/grub-theme/theme.txt",
            "archiso/airootfs/usr/share/plymouth/themes/churros/churros.plymouth",
            "archiso/airootfs/etc/skel/.config/waybar/style.css",
            "archiso/airootfs/etc/skel/.config/wlogout/style.css",
            "archiso/airootfs/etc/skel/.config/fuzzel/fuzzel.ini",
            "installer/calamares/branding/churros/stylesheet.qss",
        ])
        self.assertEqual(chosen, ["grub", "plymouth", "desktop", "bar", "launcher", "session-menu", "installer"])

    def test_ambiguous_rust_ui_defaults_to_the_desktop(self):
        self.assertEqual(screens.screens_for_paths(["rust/preferences/src/theme.rs"]), ["desktop"])

    def test_icons_are_the_desktop(self):
        self.assertEqual(
            screens.screens_for_paths(["rust/churros-welcome/assets/icons/logo.svg"]),
            ["desktop"],
        )


class PngRoundtrip(unittest.TestCase):
    def test_ppm_and_png(self):
        with tempfile.TemporaryDirectory() as tmp:
            ppm = Path(tmp) / "shot.ppm"
            png = Path(tmp) / "shot.png"
            rgb = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 1, 2, 3])
            ppm.write_bytes(b"P6\n2 2\n255\n" + rgb)
            imageutil.ppm_to_png(ppm, png)
            width, height, back = imageutil.read_png(png)
        self.assertEqual((width, height, back), (2, 2, rgb))


class CaptureDryRun(unittest.TestCase):
    def test_dry_run_and_missing_write_a_manifest(self):
        script = ROOT / "scripts/qa/visual/capture.sh"
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"screens": ["desktop", "bar"], "paths": ["x"]}), encoding="utf-8")
            out = Path(tmp) / "before"
            result = testlib.run(
                ["bash", str(script), "--dry-run", "--plan", str(plan), "--out", str(out), "--role", "before"],
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            data = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "dry-run")
            self.assertEqual(data["role"], "before")
            self.assertEqual(data["screens"], ["desktop", "bar"])
            self.assertEqual(data["agent"], {"tool": "opencode", "status": "dry-run", "reason": "dry-run"})
            self.assertIn(data["accel"], ("kvm", "tcg"))
            self.assertIn(data["gpu"], ("plain", "virgl"))

            missing = Path(tmp) / "after"
            result = testlib.run(
                ["bash", str(script), "--missing", "--plan", str(plan), "--out", str(missing), "--role", "after"],
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            data = json.loads((missing / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "iso-missing")
            self.assertEqual(data["role"], "after")
            self.assertEqual(data["agent"]["status"], "not-run")
            self.assertEqual(data["agent"]["reason"], "iso-missing")

    def test_wait_isos_times_out_without_credentials(self):
        script = ROOT / "scripts/qa/visual/wait-isos.sh"
        env = os.environ.copy()
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
            env.pop(name, None)
        env["VISUAL_QA_WAIT_SECONDS"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            result = testlib.run(
                ["bash", str(script), "--edition", "niri",
                 "--pr-sha", "abc123", "--main-sha", "def456", "--dest", tmp],
                timeout=30, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            data = json.loads((Path(tmp) / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(data["pr_iso"], "")
        self.assertEqual(data["main_iso"], "")
        self.assertEqual(data["pr_name"], "visual-qa-pr-abc123-niri")


class BootFrames(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = load("visual_bootframes", "bootframes.py")

    def test_blank_text_menu_and_splash(self):
        frames = self.frames
        self.assertEqual(frames.classify_frame(8, 8, bytes(8 * 8 * 3)), "blank")
        text = bytearray(16 * 8 * 3)
        for x in range(16):
            index = (4 * 16 + x) * 3
            text[index:index + 3] = b"\xff\xff\xff"
        self.assertEqual(frames.classify_frame(16, 8, bytes(text)), "text")
        menu = bytearray(16 * 8 * 3)
        for index in range(16 * 8):
            menu[index * 3:index * 3 + 3] = bytes((0x11, 0x18, 0x27))
        for x in range(16):
            index = (3 * 16 + x) * 3
            menu[index:index + 3] = bytes((0xF9, 0x73, 0x16))
        self.assertEqual(frames.classify_frame(16, 8, bytes(menu)), "menu")
        splash = bytes((0x20, 0x30, 0xA0)) * (8 * 8)
        self.assertEqual(frames.classify_frame(8, 8, splash), "splash")

    def test_kernel_text_is_not_the_menu_and_plymouth_can_be_absent(self):
        watch = self.frames.BootWatch(True, True)
        watch.feed("text")
        self.assertIsNone(watch.grub)
        watch.feed("menu")
        self.assertEqual(watch.grub, "ok")
        watch.feed("text", splash_flag=False)
        self.assertEqual(watch.plymouth, "absent")
        watch.finish()
        self.assertEqual(watch.grub, "ok")

    def test_cmdline_without_splash(self):
        self.assertIsNone(self.frames.splash_on_cmdline("Booting"))
        self.assertFalse(self.frames.splash_on_cmdline("Kernel command line: console=ttyS0"))
        self.assertTrue(self.frames.splash_on_cmdline("Kernel command line: quiet splash"))


class PromptKeys(unittest.TestCase):
    def test_mod_key_is_meta_l(self):
        prompt = load("visual_prompt", "prompt.py")
        text = prompt.build_prompt("/tmp/qmp.sock", "unavailable", "/tmp/out", "vmctl.py", ["session-menu"])
        self.assertIn("meta_l", text)
        self.assertIn("meta_l+shift+e", text)
        self.assertNotIn("super+", text)
        self.assertNotIn("is logged in automatically", text)
        self.assertIn("graphical frame is already on screen", text)


class DesktopReady(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = load("visual_bootframes_ready", "bootframes.py")
        cls.vmctl = load("visual_vmctl_crop", "vmctl.py")

    def test_menu_before_kernel_text_is_not_the_desktop(self):
        wait = self.frames.DesktopWait(stable_needed=2)
        self.assertFalse(wait.feed("menu", (b"\x10\x20\x30",), bar=True))
        self.assertFalse(wait.feed("text"))
        signature = (b"\x10\x20\x30",)
        self.assertFalse(wait.feed("menu", signature, bar=True))
        self.assertTrue(wait.feed("menu", signature, bar=True))

    def test_overlay_without_a_bar_does_not_count(self):
        wait = self.frames.DesktopWait(stable_needed=1)
        wait.feed("text")
        self.assertFalse(wait.feed("menu", (b"\x10\x20\x30",), bar=False))

    def test_bar_is_a_full_width_strip(self):
        width, height = 20, 8
        overlay = bytearray(width * height * 3)
        for y in range(3, 5):
            for x in range(8, 12):
                index = (y * width + x) * 3
                overlay[index:index + 3] = bytes((0xF9, 0x73, 0x16))
        self.assertFalse(self.frames.has_bar(width, height, bytes(overlay)))
        bar = bytearray(width * height * 3)
        for x in range(width):
            bar[x * 3:x * 3 + 3] = bytes((0xF9, 0x73, 0x16))
        self.assertTrue(self.frames.has_bar(width, height, bytes(bar)))

    def test_flat_grey_is_not_a_bar(self):
        niri = bytes((0x40, 0x40, 0x40)) * (32 * 16)
        lighter = bytes((0x80, 0x80, 0x80)) * (32 * 16)
        self.assertFalse(self.frames.has_bar(32, 16, niri), "has_bar:flat-grey")
        self.assertFalse(self.frames.has_bar(32, 16, lighter), "has_bar:flat-grey")
        ok, reason = self.frames.assess_image(32, 16, niri, 32, 16, require_bar=True)
        self.assertFalse(ok, "has_bar:flat-grey")
        self.assertEqual(reason, "no-bar")

    def test_panel_strip_on_niri_grey_is_a_bar(self):
        width, height = 32, 16
        frame = bytearray((0x40, 0x40, 0x40) * (width * height))
        for y in range(2):
            for x in range(width):
                index = (y * width + x) * 3
                frame[index:index + 3] = bytes((0x2A, 0x2A, 0x2A))
        self.assertTrue(self.frames.has_bar(width, height, bytes(frame)))

    def test_pin_requires_xdotool(self):
        original = self.vmctl.shutil.which
        self.vmctl.shutil.which = lambda name: None if name == "xdotool" else original(name)
        try:
            try:
                self.vmctl.pin_qemu_window(":99")
            except self.vmctl.QmpError as error:
                self.assertIn("xdotool", str(error))
            else:
                self.fail("xdotool:required")
        finally:
            self.vmctl.shutil.which = original

    def test_pin_fails_when_the_window_cannot_be_moved(self):
        original_which = self.vmctl.shutil.which
        original_run = self.vmctl.subprocess.run
        self.vmctl.shutil.which = lambda name: "/usr/bin/xdotool" if name == "xdotool" else original_which(name)

        def refuse(*_args, **_kwargs):
            class Result:
                returncode = 1
                stdout = b""
                stderr = b""
            return Result()

        self.vmctl.subprocess.run = refuse
        try:
            with self.assertRaises(self.vmctl.QmpError):
                self.vmctl.pin_qemu_window(":99")
        finally:
            self.vmctl.shutil.which = original_which
            self.vmctl.subprocess.run = original_run

    def test_unchanged_frame_is_not_wlogout(self):
        rgb = bytes((0x11, 0x18, 0x27)) * 16
        ok, reason = self.frames.session_menu_visible(rgb, rgb, 4, 4)
        self.assertFalse(ok)
        self.assertIn("unchanged", reason)

    def test_kernel_text_shot_is_not_ok(self):
        rgb = bytearray(4 * 2 * 3)
        rgb[0:3] = b"\xff\xff\xff"
        ok, reason = self.frames.assess_image(4, 2, bytes(rgb), 4, 2)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("not-graphical:"))

    def test_wrong_resolution_fails_even_if_graphical(self):
        color = bytes((0xF9, 0x73, 0x16))
        rgb = color * 4
        ok, reason = self.frames.assess_image(2, 2, rgb, 1920, 1080)
        self.assertFalse(ok)
        self.assertTrue(reason.startswith("wrong-resolution:"))

    def test_xwd_targets_the_qemu_window_and_crops_the_border(self):
        selectors = self.vmctl.xwd_selectors("churros-visual-qa")
        self.assertTrue(all(item[0] == "-name" for item in selectors))
        self.assertNotIn(["-root"], selectors)
        rgb = bytearray(6 * 4 * 3)
        for y in range(1, 3):
            for x in range(1, 5):
                index = (y * 6 + x) * 3
                rgb[index:index + 3] = b"\x10\x20\x30"
        width, height, cropped = self.vmctl.crop_to_content(6, 4, bytes(rgb))
        self.assertEqual((width, height), (4, 2))
        self.assertEqual(cropped, b"\x10\x20\x30" * 8)


class QemuDeath(unittest.TestCase):
    def test_socket_then_exit_is_not_a_successful_launch(self):
        script = ROOT / "scripts/qa/visual/capture.sh"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bindir = root / "bin"
            bindir.mkdir()
            attempts = root / "attempts.log"
            qemu = bindir / "qemu-system-x86_64"
            qemu.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {attempts}\n"
                "sock=\n"
                "prev=\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in\n"
                "    unix:*) sock=${arg#unix:}; sock=${sock%%,*} ;;\n"
                "  esac\n"
                "  prev=$arg\n"
                "done\n"
                "if [ -n \"$sock\" ]; then\n"
                "  python3 -c 'import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])' \"$sock\"\n"
                "fi\n"
                "sleep 0.2\n"
                "echo 'Display vnc is incompatible with the GL context' >&2\n"
                "exit 1\n",
                encoding="utf-8",
            )
            qemu.chmod(0o755)
            xvfb = bindir / "Xvfb"
            xvfb.write_text(
                "#!/bin/sh\n"
                "prev=\n"
                "fd=\n"
                "for arg in \"$@\"; do\n"
                "  if [ \"$prev\" = \"-displayfd\" ]; then fd=$arg; fi\n"
                "  prev=$arg\n"
                "done\n"
                "if [ -n \"$fd\" ]; then echo 5 >&\"$fd\"; fi\n"
                "sleep 30\n",
                encoding="utf-8",
            )
            xvfb.chmod(0o755)
            plan = root / "plan.json"
            plan.write_text(json.dumps({"screens": ["desktop"], "paths": []}), encoding="utf-8")
            iso = root / "fake.iso"
            iso.write_bytes(b"iso")
            out = root / "out"
            env = os.environ.copy()
            env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
            env["VISUAL_QA_GPU"] = "virgl"
            env["VISUAL_QA_BOOT_POLL"] = "1"
            result = testlib.run(
                ["bash", str(script), "--iso", str(iso), "--plan", str(plan), "--out", str(out), "--role", "before"],
                timeout=30, env=env,
            )
            self.assertEqual(result.returncode, 1, result.stdout)
            manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "qemu-failed")
            lines = attempts.read_text(encoding="utf-8").splitlines()
            self.assertGreaterEqual(len(lines), 2, lines)
            self.assertIn("virtio-vga-gl", lines[0])
            self.assertNotIn("-vnc", lines[0])
            self.assertIn("-vnc", lines[1])
            self.assertNotIn("virtio-vga-gl", lines[1])


class CaptureContract(unittest.TestCase):
    def test_base_shot_stays_out_of_the_report_dir_and_opencode_keeps_the_diff(self):
        script = (ROOT / "scripts/qa/visual/capture.sh").read_text(encoding="utf-8")
        self.assertIn('base="$workdir/_desktop-base.png"', script, "desktop-base:workdir")
        self.assertNotIn('base="$out/_desktop-base.png"', script, "desktop-base:out")
        self.assertEqual(script.count("opencode run"), 2, "opencode:diff-screens")
        self.assertIn('agent_reason="no-diff-screens"', script, "agent:no-diff-screens")
        self.assertIn('agent_reason="no-key"', script, "agent:no-key")
        self.assertIn('agent_status="not-run"', script)


class CaptureWorkflow(unittest.TestCase):
    def test_capture_does_not_block_and_uploads_both_sides(self):
        testlib.require_module(self, "yaml")
        import yaml
        path = ROOT / ".github/workflows/visual-qa-capture.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = data.get("on", data.get(True))
        self.assertIn("pull_request", triggers)
        self.assertIn("concurrency", data)
        capture = data["jobs"]["capture"]
        self.assertTrue(data["jobs"]["gate"]["continue-on-error"])
        self.assertTrue(capture["continue-on-error"])
        self.assertEqual(capture["if"], "needs.gate.outputs.visual == 'true'")
        text = path.read_text(encoding="utf-8")
        self.assertIn("out/before", text)
        self.assertIn("out/after", text)
        self.assertIn("visual-qa-before-", text)
        self.assertIn("qemu-system-x86", text)
        self.assertNotRegex(text, r"echo\s+.*API_KEY")
