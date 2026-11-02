"""Plan en seco de la ISO de QA visual y el contrato del workflow.

No construye una ISO. Comprueba el JSON de --dry-run, los nombres de
artefacto y que visual-qa-iso.yml solo dispara la construcción cuando
visual=true, con --container, SHA256 y continue-on-error.
"""
from __future__ import annotations

import json
import unittest

from tests import testlib

ROOT = testlib.ROOT
SCRIPT = ROOT / "scripts/qa/visual/build-local.sh"
NAMES = ROOT / "scripts/qa/visual/artifact-names.sh"
WORKFLOW = ROOT / ".github/workflows/visual-qa-iso.yml"


class BuildPlan(unittest.TestCase):
    def test_dry_run_names_both_commits(self):
        result = testlib.run(
            ["bash", str(SCRIPT), "--dry-run", "--edition", "niri", "--role", "both"],
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["edition"], "niri")
        self.assertEqual(data["role"], "both")
        self.assertEqual(len(data["pr_sha"]), 40)
        self.assertEqual(len(data["main_sha"]), 40)
        self.assertFalse(data["container"])
        self.assertEqual(data["out"], "out/qa-visual")

    def test_dry_run_honours_base_and_container(self):
        base = testlib.run(["git", "rev-parse", "HEAD"], timeout=30)
        self.assertEqual(base.returncode, 0, base.stdout)
        sha = base.stdout.strip()
        result = testlib.run(
            ["bash", str(SCRIPT), "--dry-run", "--edition", "xfce", "--role", "pr",
             "--base", sha, "--container"],
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["edition"], "xfce")
        self.assertEqual(data["role"], "pr")
        self.assertEqual(data["main_sha"], sha)
        self.assertTrue(data["container"])

    def test_unknown_edition_fails(self):
        result = testlib.run(
            ["bash", str(SCRIPT), "--dry-run", "--edition", "no-existe"],
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("edición", result.stdout)

    def test_artifact_names(self):
        result = testlib.run(
            ["bash", "-c",
             'source "$1"; visual_qa_pr_iso_name "$2" "$3"; visual_qa_main_iso_name "$2" "$3"',
             "names", str(NAMES), "abc123", "niri"],
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(
            result.stdout.splitlines(),
            ["visual-qa-pr-abc123-niri", "visual-qa-main-abc123-niri"],
        )


class IsoWorkflow(unittest.TestCase):
    def setUp(self):
        testlib.require_module(self, "yaml")
        import yaml
        self.data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
        self.text = WORKFLOW.read_text(encoding="utf-8")

    def test_builds_only_when_visual_and_does_not_block(self):
        triggers = self.data.get("on", self.data.get(True))
        self.assertIn("pull_request", triggers)
        self.assertIn("workflow_dispatch", triggers)
        self.assertIn("concurrency", self.data)
        gate = self.data["jobs"]["gate"]
        iso = self.data["jobs"]["iso"]
        self.assertTrue(gate["continue-on-error"])
        self.assertTrue(iso["continue-on-error"])
        self.assertIn("timeout-minutes", gate)
        self.assertIn("timeout-minutes", iso)
        self.assertEqual(iso["if"], "needs.gate.outputs.visual == 'true'")
        self.assertIn("--container", self.text)
        self.assertIn("build-local.sh", self.text)
        self.assertIn("SHA256SUMS", self.text)
        self.assertIn("visual-qa-main-", self.text)
        self.assertNotRegex(self.text, r"echo\s+.*API_KEY")
