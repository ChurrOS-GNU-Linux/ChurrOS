"""Tokens de marca, diff de píxeles y el comentario que no bloquea."""
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


tokens = load("visual_tokens", "tokens.py")
report = load("visual_report", "report.py")
imageutil = load("visual_imageutil", "imageutil.py")


class Tokens(unittest.TestCase):
    def test_committed_file_matches_the_guides(self):
        fresh = tokens.extract(ROOT)
        committed = json.loads((ROOT / "scripts/qa/visual/design-tokens.json").read_text(encoding="utf-8"))
        self.assertEqual(fresh, committed)

    def test_palette_fonts_and_known_conflicts(self):
        data = tokens.extract(ROOT)
        hexes = {item["hex"] for item in data["colors"]}
        self.assertIn("#F97316", hexes)
        self.assertIn("#111827", hexes)
        self.assertIn("#0F0F10", hexes)
        families = {item["family"] for item in data["fonts"]}
        self.assertIn("Inter", families)
        self.assertIn("JetBrains Mono", families)
        self.assertEqual(data["metrics"]["logo_min_symbol_px"], 24)
        self.assertEqual(data["metrics"]["spacing_px"], [8, 16, 24, 32])
        text = " ".join(data["conflicts"])
        self.assertIn("#111827", text)
        self.assertIn("#1F1F1F", text)
        self.assertIn("Inter", text)
        self.assertIn("Noto Sans", text)


class PixelReport(unittest.TestCase):
    def test_identical_changed_and_missing(self):
        token_doc = {
            "colors": [{"hex": "#F97316", "name": "Naranja", "role": "primary", "source": "branding/colors.md"}],
            "fonts": [],
            "metrics": {"logo_min_symbol_px": 24, "logo_min_full_px": 120},
            "conflicts": ["El fondo no coincide."],
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            before = root / "before"
            after = root / "after"
            before.mkdir()
            after.mkdir()
            same = bytes([1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3])
            changed = bytearray(same)
            changed[0] = 9
            imageutil.write_png(before / "desktop.png", 2, 2, same)
            imageutil.write_png(after / "desktop.png", 2, 2, same)
            imageutil.write_png(before / "bar.png", 2, 2, same)
            imageutil.write_png(after / "bar.png", 2, 2, bytes(changed))
            imageutil.write_png(before / "grub.png", 2, 2, same)
            payload = report.build_report(before, after, root / "report", token_doc, 0.01)
            self.assertEqual(payload["pairs_total"], 3)
            by_name = {pair["name"]: pair for pair in payload["pairs"]}
            self.assertFalse(by_name["desktop.png"]["deviation"])
            self.assertEqual(by_name["desktop.png"]["ratio"], 0)
            self.assertTrue(by_name["bar.png"]["deviation"])
            self.assertEqual(by_name["bar.png"]["ratio"], 0.25)
            self.assertEqual(by_name["grub.png"]["reason"], "missing-after")
            self.assertEqual(payload["deviations"], 2)
            html_text = (root / "report" / "report.html").read_text(encoding="utf-8")
            summary = (root / "report" / "summary.md").read_text(encoding="utf-8")
            self.assertIn("bar.png", html_text)
            self.assertIn("desviación", html_text)
            self.assertIn("#F97316", html_text)
            self.assertTrue(summary.startswith("<!-- visual-qa-report -->"))
            self.assertIn("2 desviaciones", summary)
            self.assertIn("1 conflicto conocido", summary)


class CommentScript(unittest.TestCase):
    def test_without_a_pull_request_it_does_not_call_github(self):
        script = ROOT / "scripts/qa/visual/pr-comment.sh"
        with tempfile.TemporaryDirectory() as tmp:
            body = Path(tmp) / "summary.md"
            body.write_text("<!-- visual-qa-report -->\nhola\n", encoding="utf-8")
            env = os.environ.copy()
            for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY", "PR"):
                env.pop(name, None)
            result = testlib.run(["bash", str(script), str(body)], timeout=30, env=env)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("sin pull request", result.stdout)

    def test_wait_shots_without_credentials_finishes(self):
        script = ROOT / "scripts/qa/visual/wait-shots.sh"
        env = os.environ.copy()
        for name in ("GH_TOKEN", "GITHUB_TOKEN", "GITHUB_REPOSITORY"):
            env.pop(name, None)
        env["VISUAL_QA_WAIT_SECONDS"] = "0"
        with tempfile.TemporaryDirectory() as tmp:
            result = testlib.run(
                ["bash", str(script), "--sha", "abc123", "--dest", tmp],
                timeout=30, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            data = json.loads((Path(tmp) / "status.json").read_text(encoding="utf-8"))
        self.assertFalse(data["before"])
        self.assertFalse(data["after"])
        self.assertEqual(data["before_name"], "visual-qa-before-abc123")


class ReportWorkflow(unittest.TestCase):
    def test_comment_only_and_does_not_block(self):
        testlib.require_module(self, "yaml")
        import yaml
        path = ROOT / ".github/workflows/visual-qa-report.yml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = data.get("on", data.get(True))
        self.assertIn("pull_request", triggers)
        report_job = data["jobs"]["report"]
        self.assertTrue(data["jobs"]["gate"]["continue-on-error"])
        self.assertTrue(report_job["continue-on-error"])
        self.assertEqual(report_job["if"], "needs.gate.outputs.visual == 'true'")
        text = path.read_text(encoding="utf-8")
        self.assertIn("pr-comment.sh", text)
        self.assertIn("visual-qa-report-", text)
        self.assertNotIn("statuses:", text)
        self.assertNotRegex(text, r"echo\s+.*API_KEY")
