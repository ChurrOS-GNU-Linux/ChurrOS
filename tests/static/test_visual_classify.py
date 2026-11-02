"""Clasificador visual: reglas de ruta, Jev y el escalado a Haiku.

No hay red. ``ask_jev`` y ``ask_haiku`` se sustituyen por funciones, y el
cuerpo de la petición a Jev se compara con la forma publicada en
docs.typesafe.ai (POST /v1/systemone, primitiva Choice).
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path
import unittest

from tests import testlib

ROOT = testlib.ROOT
CLASSIFY = ROOT / "scripts/qa/visual/classify.py"
WORKFLOW = ROOT / ".github/workflows/visual-qa-classify.yml"


def load_classify():
    spec = importlib.util.spec_from_file_location("visual_classify", CLASSIFY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classify_mod = load_classify()


def jev_answer(choice: str, probability: float, *, model: str = "jev-1.14.0", confidence: float = 0.9) -> dict:
    other = "not_visual" if choice == "visual" else "visual"
    return {
        "choice": choice,
        "probabilities": {choice: probability, other: round(1.0 - probability, 4)},
        "top_probability": probability,
        "confidence": confidence,
        "model": model,
    }


class PathRules(unittest.TestCase):
    def test_branding_wayland_shell_and_boot_chrome_are_visual(self):
        visual = [
            "branding/colors.md",
            "branding/grub-theme/theme.txt",
            "archiso/airootfs/etc/skel/.config/noctalia/config.toml",
            "archiso/airootfs/etc/skel/.config/waybar/style.css",
            "archiso/airootfs/etc/skel/.config/wlogout/style.css",
            "archiso/airootfs/etc/skel/.config/niri/config.kdl",
            "archiso/airootfs/usr/share/churros/styles/churros.css",
            "archiso/airootfs/usr/share/churros/defaults/noctalia/config.toml",
            "archiso/airootfs/usr/share/churros/pi/waybar/style.css",
            "archiso/airootfs/usr/share/plymouth/themes/churros/churros.plymouth",
            "archiso/airootfs/usr/share/color-schemes/ChurrOS.colors",
            "archiso/airootfs/usr/share/icons/hicolor/scalable/apps/churros-logo.svg",
            "rust/churros-welcome/assets/icons/logo.svg",
            "installer/calamares/branding/churros/stylesheet.qss",
            "archiso/airootfs/usr/local/bin/churros-theme",
        ]
        for path in visual:
            with self.subTest(path=path):
                self.assertTrue(classify_mod.is_visual_path(path), path)

    def test_docs_tests_and_ci_are_not_visual(self):
        for path in (
            "docs/testing.md",
            "docs/branding.md",
            "tests/static/test_visual_classify.py",
            ".github/workflows/ci.yml",
            "scripts/qa/visual/classify.py",
            "scripts/cli/build.sh",
            "README.md",
            "AGENTS.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(classify_mod.is_visual_path(path), path)
                self.assertTrue(classify_mod.is_non_visual_path(path), path)

    def test_rust_ui_source_is_ambiguous(self):
        path = "rust/preferences/src/theme.rs"
        self.assertFalse(classify_mod.is_visual_path(path))
        self.assertFalse(classify_mod.is_non_visual_path(path))


class Classify(unittest.TestCase):
    def setUp(self):
        self.logs: list[str] = []

    def log(self, message: str) -> None:
        self.logs.append(message)

    def run_classify(self, paths, diff="", **kwargs):
        def fail_jev(*_args, **_kwargs):
            raise AssertionError("Jev no debería llamarse")

        def fail_haiku(*_args, **_kwargs):
            raise AssertionError("Haiku no debería llamarse")

        kwargs.setdefault("jev", fail_jev)
        kwargs.setdefault("haiku", fail_haiku)
        kwargs.setdefault("log", self.log)
        kwargs.setdefault("typesafe_api_key", "typesafe-secret-value")
        kwargs.setdefault("anthropic_api_key", "anthropic-secret-value")
        return classify_mod.classify(paths, diff, **kwargs)

    def test_visual_path_skips_models(self):
        decision = self.run_classify(["docs/testing.md", "branding/colors.md"])
        self.assertTrue(decision.visual)
        self.assertEqual(decision.decider, "rules")
        self.assertEqual(decision.probability, 1.0)
        self.assertTrue(any("decider=rules" in line and "visual=true" in line for line in self.logs))

    def test_non_visual_paths_skip_models(self):
        decision = self.run_classify(["docs/testing.md", "tests/static/test_visual_classify.py"])
        self.assertFalse(decision.visual)
        self.assertEqual(decision.decider, "rules")

    def test_empty_diff_is_not_visual(self):
        decision = self.run_classify([])
        self.assertFalse(decision.visual)
        self.assertEqual(decision.decider, "rules")

    def test_jev_accepts_when_top_probability_meets_threshold(self):
        def jev(state, *, api_key, model):
            self.assertIn("rust/preferences/src/theme.rs", state)
            self.assertEqual(api_key, "typesafe-secret-value")
            self.assertEqual(model, "jev-latest")
            return jev_answer("visual", 0.8)

        decision = self.run_classify(["rust/preferences/src/theme.rs"], jev=jev)
        self.assertTrue(decision.visual)
        self.assertEqual(decision.decider, "jev")
        self.assertEqual(decision.probability, 0.8)
        self.assertEqual(decision.model, "jev-1.14.0")
        joined = "\n".join(self.logs)
        self.assertIn("decider=jev", joined)
        self.assertIn("probability=0.8000", joined)
        self.assertNotIn("typesafe-secret-value", joined)

    def test_low_probability_escalates_to_haiku(self):
        calls = {"haiku": 0}

        def jev(state, *, api_key, model):
            return jev_answer("visual", 0.79)

        def haiku(state, *, api_key, model):
            calls["haiku"] += 1
            self.assertEqual(model, "claude-haiku-4-5")
            self.assertIn("theme.rs", state)
            return False

        decision = self.run_classify(
            ["rust/preferences/src/theme.rs"], jev=jev, haiku=haiku,
        )
        self.assertEqual(calls["haiku"], 1)
        self.assertFalse(decision.visual)
        self.assertEqual(decision.decider, "haiku")
        self.assertIsNone(decision.probability)
        self.assertEqual(decision.jev_probability, 0.79)
        joined = "\n".join(self.logs)
        self.assertIn("escalate=yes", joined)
        self.assertIn("decider=haiku", joined)
        self.assertIn("probability=n/a", joined)
        self.assertNotIn("anthropic-secret-value", joined)

    def test_not_visual_above_threshold_does_not_escalate(self):
        def jev(state, *, api_key, model):
            return jev_answer("not_visual", 0.91)

        decision = self.run_classify(["archiso/packages.niri.x86_64"], jev=jev)
        self.assertFalse(decision.visual)
        self.assertEqual(decision.decider, "jev")

    def test_jev_error_escalates_and_haiku_error_does_not_raise(self):
        def jev(state, *, api_key, model):
            raise classify_mod.JevError("http-503")

        def haiku(state, *, api_key, model):
            raise classify_mod.JevError("http-401")

        decision = self.run_classify(["rust/preferences/src/window.rs"], jev=jev, haiku=haiku)
        self.assertTrue(decision.visual)
        self.assertEqual(decision.decider, "unresolved-default-visual")
        joined = "\n".join(self.logs)
        self.assertIn("jev error=http-503", joined)
        self.assertIn("decider=unresolved-default-visual visual=true", joined)
        self.assertIn("haiku error=http-401", joined)
        self.assertNotIn("typesafe-secret-value", joined)
        self.assertNotIn("anthropic-secret-value", joined)

    def test_ambiguous_without_keys_defaults_to_visual(self):
        """Un fork no tiene secrets: no hay red y el diff ambiguo es visual."""
        decision = classify_mod.classify(
            ["rust/preferences/src/theme.rs"],
            typesafe_api_key="",
            anthropic_api_key="",
            log=self.log,
        )
        self.assertTrue(decision.visual)
        self.assertEqual(decision.decider, "unresolved-default-visual")
        self.assertIn("error=no-key", "\n".join(self.logs))

    def test_non_visual_without_keys_stays_false(self):
        decision = classify_mod.classify(
            ["docs/testing.md"],
            typesafe_api_key="",
            anthropic_api_key="",
            log=self.log,
        )
        self.assertFalse(decision.visual)
        self.assertEqual(decision.decider, "rules")

    def test_exception_text_with_a_key_is_redacted(self):
        def jev(state, *, api_key, model):
            raise RuntimeError(f"leaked {api_key}")

        decision = self.run_classify(["rust/preferences/src/window.rs"], jev=jev, haiku=lambda state, **kwargs: True)
        self.assertTrue(decision.visual)
        self.assertEqual(decision.decider, "haiku")
        self.assertNotIn("typesafe-secret-value", "\n".join(self.logs))

    def test_missing_key_is_a_jev_error_code_not_an_http_call(self):
        with self.assertRaises(classify_mod.JevError) as caught:
            classify_mod.ask_jev("state", api_key="", model="jev-latest")
        self.assertEqual(caught.exception.code, "no-key")

    def test_state_keeps_ambiguous_hunks_and_scrubs_assignments(self):
        diff = "\n".join([
            "diff --git a/docs/testing.md b/docs/testing.md",
            "+docs",
            "diff --git a/rust/preferences/src/theme.rs b/rust/preferences/src/theme.rs",
            "+ANTHROPIC_API_KEY=anthropic-secret-value",
            "+color",
        ])
        state = classify_mod.build_state(
            ["rust/preferences/src/theme.rs"], diff, ["anthropic-secret-value"],
        )
        self.assertIn("theme.rs", state)
        self.assertNotIn("+docs", state)
        self.assertNotIn("anthropic-secret-value", state)
        self.assertIn("[redacted]", state)


class JevContract(unittest.TestCase):
    def test_request_matches_the_published_choice_shape(self):
        body = classify_mod.jev_request_body("a diff", "jev-latest")
        self.assertEqual(set(body), {"model", "state", "questions"})
        self.assertEqual(body["model"], "jev-latest")
        question = body["questions"]["appearance"]
        self.assertEqual(question["type"], "choice")
        self.assertEqual(set(question["criteria"]), {"visual", "not_visual"})
        self.assertIn("instructions", question)

    def test_response_parser_reads_probabilities(self):
        parsed = classify_mod.parse_jev_response({
            "model": "jev-1.14.0",
            "answers": {
                "appearance": {
                    "type": "choice",
                    "choice": "not_visual",
                    "confidence": 0.7,
                    "probabilities": {"visual": 0.2, "not_visual": 0.8},
                },
            },
            "usage": {"input_tokens": 10, "output_tokens": 4},
        })
        self.assertEqual(parsed["choice"], "not_visual")
        self.assertEqual(parsed["top_probability"], 0.8)
        self.assertEqual(parsed["model"], "jev-1.14.0")

    def test_mismatched_choice_is_a_shape_error(self):
        with self.assertRaises(classify_mod.JevError) as caught:
            classify_mod.parse_jev_response({
                "model": "jev-1.14.0",
                "answers": {
                    "appearance": {
                        "type": "choice",
                        "choice": "visual",
                        "confidence": 0.2,
                        "probabilities": {"visual": 0.2, "not_visual": 0.8},
                    },
                },
            })
        self.assertEqual(caught.exception.code, "shape")

    def test_haiku_yes_and_no(self):
        self.assertTrue(classify_mod.parse_haiku_text("yes"))
        self.assertFalse(classify_mod.parse_haiku_text("No, the diff is internal."))
        self.assertIsNone(classify_mod.parse_haiku_text("maybe"))


class Cli(unittest.TestCase):
    def test_github_output_and_stdout(self):
        output = ROOT / "out" / "visual-classify-output.txt"
        result = ROOT / "out" / "visual-classify-result.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.unlink(missing_ok=True)
        stderr = io.StringIO()
        real_stderr = classify_mod.sys.stderr
        classify_mod.sys.stderr = stderr
        try:
            code = classify_mod.main([
                "--paths-file", str(self._paths(["branding/colors.md"])),
                "--github-output", str(output),
                "--result", str(result),
            ])
        finally:
            classify_mod.sys.stderr = real_stderr
        self.assertEqual(code, 0)
        text = output.read_text(encoding="utf-8")
        self.assertIn("visual=true\n", text)
        self.assertIn("decider=rules\n", text)
        payload = json.loads(result.read_text(encoding="utf-8"))
        self.assertTrue(payload["visual"])
        self.assertNotIn("TYPESAFE_API_KEY", stderr.getvalue())

    def test_usage_error_without_paths(self):
        real_stdin = classify_mod.sys.stdin
        classify_mod.sys.stdin = io.StringIO("")
        classify_mod.sys.stdin.isatty = lambda: True  # type: ignore[method-assign]
        try:
            with self.assertRaises(SystemExit) as caught:
                classify_mod.main([])
        finally:
            classify_mod.sys.stdin = real_stdin
        self.assertEqual(caught.exception.code, 2)

    @staticmethod
    def _paths(lines: list[str]) -> Path:
        path = ROOT / "out" / "visual-classify-paths.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path


class WorkflowContract(unittest.TestCase):
    def setUp(self):
        testlib.require_module(self, "yaml")
        import yaml
        self.data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))

    def test_pull_request_outputs_visual_and_does_not_block(self):
        # PyYAML 1.1 lee la clave `on` como True.
        triggers = self.data.get("on", self.data.get(True))
        self.assertIn("pull_request", triggers)
        job = self.data["jobs"]["classify"]
        self.assertTrue(job["continue-on-error"])
        self.assertIn("timeout-minutes", job)
        self.assertEqual(job["outputs"]["visual"], "${{ steps.classify.outputs.visual }}")
        self.assertEqual(self.data["permissions"]["contents"], "read")
        text = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("secrets.TYPESAFE_API_KEY", text)
        self.assertIn("secrets.ANTHROPIC_API_KEY", text)
        self.assertIn("visual-qa", text)
        self.assertNotIn("echo \"$TYPESAFE_API_KEY\"", text)
        self.assertNotIn("echo \"$ANTHROPIC_API_KEY\"", text)
        self.assertNotRegex(text, r"echo\s+.*API_KEY")
