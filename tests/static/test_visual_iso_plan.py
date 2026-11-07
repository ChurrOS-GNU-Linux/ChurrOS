"""Plan en seco de la ISO de QA visual y el contrato del workflow.

No construye una ISO. Comprueba el JSON de --dry-run, los nombres de
artefacto y que visual-qa-iso.yml solo dispara la construcción cuando
visual=true, con --container, SHA256 y continue-on-error.
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import testlib

ROOT = testlib.ROOT
SCRIPT = ROOT / "scripts/qa/visual/build-local.sh"
NAMES = ROOT / "scripts/qa/visual/artifact-names.sh"
WORKFLOW = ROOT / ".github/workflows/visual-qa-iso.yml"


def fixture_repo(tmp: Path) -> Path:
    """Repo mínimo con build-local.sh y una historia conocida.

    El checkout de la CI es superficial y sin origin/main, y las copias de
    --mutations son un git nuevo con un solo commit: la base no se puede
    sacar del repo real. Aquí main avanza después de abrir la rama, así
    merge-base, origin/main y HEAD^1 son tres commits distintos.
    """
    repo = tmp / "repo"
    visual = repo / "scripts/qa/visual"
    visual.mkdir(parents=True)
    shutil.copy2(SCRIPT, visual / SCRIPT.name)
    shutil.copy2(NAMES, visual / NAMES.name)
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@localhost",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@localhost"}

    def git(*args):
        return testlib.run(["git", *args], cwd=repo, env=env, timeout=30, check=True).stdout.strip()

    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "fork point")
    git("checkout", "-q", "-b", "pr")
    git("commit", "-q", "--allow-empty", "-m", "pr 1")
    git("commit", "-q", "--allow-empty", "-m", "pr 2")
    git("checkout", "-q", "main")
    git("commit", "-q", "--allow-empty", "-m", "main sigue")
    git("update-ref", "refs/remotes/origin/main", "main")
    git("checkout", "-q", "pr")
    return repo


def git_sha(repo: Path, rev: str) -> str:
    return testlib.run(["git", "rev-parse", rev], cwd=repo, timeout=30, check=True).stdout.strip()


class BuildPlan(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="churros-visual-plan-")
        self.addCleanup(tmp.cleanup)
        self.repo = fixture_repo(Path(tmp.name))
        self.script = self.repo / "scripts/qa/visual" / SCRIPT.name

    def dry_run(self, *args):
        return testlib.run(
            ["bash", str(self.script), "--dry-run", *args],
            cwd=self.repo, env={**os.environ, "VISUAL_QA_BASE": ""}, timeout=30,
        )

    def test_dry_run_names_both_commits(self):
        result = self.dry_run("--edition", "niri", "--role", "both")
        self.assertEqual(result.returncode, 0, result.stdout)
        data = json.loads(result.stdout)
        self.assertEqual(data["edition"], "niri")
        self.assertEqual(data["role"], "both")
        self.assertEqual(data["pr_sha"], git_sha(self.repo, "HEAD"))
        # La base es donde la rama salió de main, no la punta de origin/main.
        self.assertEqual(data["main_sha"], git_sha(self.repo, "main~1"), "[base-merge-base]")
        self.assertFalse(data["container"])
        self.assertEqual(data["out"], "out/qa-visual")

    def test_dry_run_without_origin_main_uses_first_parent(self):
        testlib.run(["git", "update-ref", "-d", "refs/remotes/origin/main"],
                    cwd=self.repo, timeout=30, check=True)
        result = self.dry_run("--role", "both")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["main_sha"], git_sha(self.repo, "HEAD^1"),
                         "[base-first-parent]")

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
