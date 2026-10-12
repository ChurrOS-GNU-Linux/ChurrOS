#!/usr/bin/env python3
"""Isolated KDE regression checks. Never writes the host's /etc or session.

Run with python3 scripts/test-kde-integration.py. kwriteconfig6 and rustc are
optional: their integration tests report SKIP when unavailable.
"""
import configparser
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "archiso/airootfs"


class KdeIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="churros-kde-test-")
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.env = {**os.environ, "HOME": str(self.home),
                    "XDG_CONFIG_HOME": str(self.home / "config")}

    def run_command(self, args, env=None, **kwargs):
        try:
            return subprocess.run(args, env=self.env if env is None else env, check=True,
                                  text=True, capture_output=True, **kwargs)
        except subprocess.CalledProcessError as exc:
            self.fail(f"{args} exited {exc.returncode}\n{exc.stdout}\n{exc.stderr}")

    def executable(self, name, source):
        path = self.home / name
        path.write_text(source)
        path.chmod(0o755)
        return path

    def test_panel_missing_config(self):
        self.run_command(["bash", str(OVERLAY / "usr/share/churros/scripts/configure-kde-panel")])
        self.assertFalse((self.home / "config").exists())

    @unittest.skipUnless(shutil.which("kwriteconfig6"), "kwriteconfig6 unavailable")
    def test_panel_multiple_containments_and_repeat(self):
        config = self.home / "config/plasma-org.kde.plasma.desktop-appletsrc"
        config.parent.mkdir()
        config.write_text(
            "[Containments][42][Applets][7]\nplugin=org.kde.plasma.kickoff\n"
            "[Containments][99][Applets][8]\nplugin=org.kde.plasma.kickoff\n"
            "[Containments][99][Applets][9]\nplugin=org.kde.plasma.icontasks\n"
            "[Containments][99][Applets][9][Configuration][General]\nicon=keep-me\n")
        script = OVERLAY / "usr/share/churros/scripts/configure-kde-panel"
        self.run_command(["bash", str(script)])
        before = config.read_text()
        self.run_command(["bash", str(script)])
        self.assertEqual(config.read_text(), before)
        parsed = configparser.ConfigParser()
        parsed.read(config)
        for containment, applet in ((42, 7), (99, 8)):
            section = f"Containments][{containment}][Applets][{applet}][Configuration][General"
            self.assertEqual(parsed[section]["icon"], "churros-logo")
            self.assertEqual(parsed[section]["useCustomButtonImage"], "true")
        self.assertEqual(parsed["Containments][99][Applets][9][Configuration][General"]["icon"], "keep-me")
        self.assertNotIn("[Containments][1]", before)

    def test_systemsettings_dispatch_preserves_arguments(self):
        # Only replace absolute paths in a disposable copy of the real wrapper.
        edition_file = self.home / "edition"
        native = self.executable("native", '#!/bin/sh\nprintf "native:%s\\n" "$*"\n')
        churros = self.executable("churros", '#!/bin/sh\nprintf "churros:%s\\n" "$*"\n')
        source = (OVERLAY / "usr/local/bin/systemsettings").read_text()
        source = source.replace("/etc/churros-edition", str(edition_file))
        source = source.replace("/usr/bin/systemsettings", str(native))
        source = source.replace("/usr/bin/churros-settings", str(churros))
        wrapper = self.executable("wrapper", source)
        for edition in ("kde", "niri", "xfce", "server"):
            edition_file.write_text(edition + "\n")
            output = self.run_command(["bash", str(wrapper), "kcm_kscreen"]).stdout.strip()
            self.assertEqual(output, ("native" if edition == "kde" else "churros") + ":kcm_kscreen")

    def test_calamares_preserves_native_kde_binary(self):
        lines = (ROOT / "installer/calamares/modules/shellprocess-cleanup.conf").read_text().splitlines()
        commands = [json.loads(line.split("command: ", 1)[1]) for line in lines
                    if "command: " in line]
        self.assertFalse(
            any("/usr/bin/systemsettings" in command for command in commands),
            "Calamares cleanup must not replace or remove Plasma's native binary",
        )
        wrapper = (OVERLAY / "usr/local/bin/systemsettings").read_text()
        self.assertIn('exec /usr/bin/systemsettings "$@"', wrapper)

    def test_portal_kde_selection(self):
        config = configparser.ConfigParser()
        config.read(OVERLAY / "etc/xdg/xdg-desktop-portal/kde-portals.conf")
        self.assertEqual(config["preferred"]["default"], "kde")
        self.assertEqual(config["preferred"]["org.freedesktop.impl.portal.Secret"], "kwallet")
        self.assertEqual(config["preferred"]["org.freedesktop.impl.portal.Notification"], "plasmanotify")

    @unittest.skipUnless(shutil.which("rustc"), "rustc unavailable")
    def test_autologin_uses_edition_session(self):
        # Compile the complete UsersService and run it against the real
        # churros-write-root-config in this disposable tree. Settings only asks
        # for "greetd-autologin on|off"; the helper picks the user (PKEXEC_UID)
        # and the session (edition table shared with configure-greetd-session).
        etc = self.home / "etc"
        (etc / "greetd").mkdir(parents=True)
        lib = self.home / "edition-session.sh"
        lib.write_text((OVERLAY / "usr/share/churros/scripts/edition-session.sh").read_text()
                       .replace("/etc/churros-edition", str(etc / "churros-edition")))
        helper = (OVERLAY / "usr/local/bin/churros-write-root-config").read_text()
        helper = helper.replace("/usr/share/churros/scripts/edition-session.sh", str(lib))
        helper = helper.replace("/etc/greetd", str(etc / "greetd"))
        helper = helper.replace("/etc/lightdm", str(etc / "lightdm"))
        helper_path = self.executable("churros-write-root-config", helper)
        # pkexec exports PKEXEC_UID; a fake getent keeps the host's users out.
        self.executable("churros-pkexec", '#!/bin/sh\nPKEXEC_UID=1000 exec "$@"\n')
        self.executable("getent", '#!/bin/sh\n[ "$1 $2" = "passwd 1000" ] && '
                                  'echo "ana:x:1000:1000::/home/ana:/bin/zsh"\n')
        self.env["PATH"] = str(self.home) + os.pathsep + os.environ["PATH"]
        source = (ROOT / "rust/preferences/src/services/users.rs").read_text()
        source = source.replace("/usr/local/bin/churros-write-root-config", str(helper_path))
        source = source.replace("/etc/greetd", str(etc / "greetd"))
        source = source.replace("/etc/lightdm", str(etc / "lightdm"))
        harness = self.home / "users.rs"
        harness.write_text(source + '''
fn main() {
    assert!(UsersService::set_auto_login(true));
    assert!(UsersService::auto_login());
    assert!(UsersService::set_auto_login(false));
    assert!(!UsersService::auto_login());
    assert!(UsersService::set_auto_login(true));
}
''')
        binary = self.home / "users-test"
        # The compiler runs with the real environment: with HOME pointing at
        # the disposable tree, rustup cannot find its toolchains.
        self.run_command(["rustc", "--edition=2024", "-A", "dead_code", str(harness), "-o", str(binary)],
                         env=os.environ)
        config = etc / "greetd/config.toml"
        for edition, session in (("kde", "/usr/bin/startplasma-wayland"),
                                 ("xfce", "/usr/bin/startxfce4"),
                                 ("niri", "/usr/bin/churros-niri-session")):
            config.write_text("[default_session]\ncommand = \"regreet\"\n")
            (etc / "churros-edition").write_text(edition + "\n")
            self.run_command([str(binary)])
            text = config.read_text()
            self.assertIn(f'command = "{session}"', text)
            self.assertIn('user = "ana"', text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
