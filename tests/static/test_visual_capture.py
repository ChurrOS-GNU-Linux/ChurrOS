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
