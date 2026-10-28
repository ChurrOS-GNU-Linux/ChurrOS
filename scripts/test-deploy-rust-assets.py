#!/usr/bin/env python3
"""Test Rust runtime-asset staging without invoking Cargo or touching the host."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEPLOY_SCRIPT = ROOT / "scripts/deploy-rust-assets.sh"


class RustAssetDeploymentTests(unittest.TestCase):
    def test_deploys_assets_only_for_deployable_crates(self):
        with tempfile.TemporaryDirectory(prefix="churros-assets-test-") as temp:
            project = Path(temp)
            scripts = project / "scripts"
            rust = project / "rust"
            scripts.mkdir()
            shutil.copy2(DEPLOY_SCRIPT, scripts / "deploy-rust-assets.sh")

            deployable = rust / "welcome"
            (deployable / "assets").mkdir(parents=True)
            (deployable / "Cargo.toml").write_text(
                '[package]\nname = "churros-welcome"\n'
                '[package.metadata.churros]\ndeploy = true\n',
                encoding="utf-8",
            )
            (deployable / "assets/logo.svg").write_text("welcome-logo", encoding="utf-8")

            private = rust / "internal-tool"
            (private / "assets").mkdir(parents=True)
            (private / "Cargo.toml").write_text(
                '[package]\nname = "internal-tool"\n', encoding="utf-8"
            )
            (private / "assets/secret.txt").write_text("not deployed", encoding="utf-8")

            destination = project / "bundle/usr/share/churros"
            result = subprocess.run(
                ["bash", str(scripts / "deploy-rust-assets.sh"), str(destination)],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("churros-welcome", result.stdout)
            self.assertEqual(
                (destination / "churros-welcome/assets/logo.svg").read_text(encoding="utf-8"),
                "welcome-logo",
            )
            self.assertFalse((destination / "internal-tool/assets/secret.txt").exists())

    def test_build_paths_stage_assets(self):
        release = (ROOT / "scripts/build-churros-release.sh").read_text(encoding="utf-8")
        iso = (ROOT / "scripts/build-rust.sh").read_text(encoding="utf-8")
        self.assertIn('deploy-rust-assets.sh" "$STAGE/usr/share/churros"', release)
        self.assertIn('deploy-rust-assets.sh" \\', iso)


if __name__ == "__main__":
    unittest.main(verbosity=2)
