"""Regression coverage for the QEMU memory and zram profile."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

from tests.vm.boot_smoke import CHURROS_GUI, parse_memory_profile, parse_pss, parse_x11_clients, zram_is_active

ROOT = Path(__file__).resolve().parents[2]


class MemoryProfileTest(unittest.TestCase):
    def test_zram_detection_requires_active_swap_device(self):
        header = "Filename Type Size Used Priority\n"
        self.assertTrue(zram_is_active(header + "/dev/zram0 partition 2097152 0 100\n"))
        self.assertFalse(zram_is_active(header + "/swapfile file 1048576 0 -2\n"))
        self.assertFalse(zram_is_active(header))

    def test_qemu_smoke_checks_and_reports_live_memory(self):
        source = (ROOT / "tests/vm/boot_smoke.py").read_text()
        self.assertIn('report.check("zram0 swap active", active', source)
        self.assertIn('"meminfo_bytes": meminfo', source)
        self.assertIn('"zram_mm_stat": zram_stat', source)
        self.assertIn('"top_rss_processes": processes', source)
        self.assertIn('collect_memory_profile(agent, report, args.memory)', source)

    def test_normalizes_memory_swap_zram_and_process_rss(self):
        profile = parse_memory_profile(
            "MemTotal:       4096000 kB\nMemAvailable:   2048000 kB\nHugePages_Total: 2\n",
            "Filename Type Size Used Priority\n/dev/zram0 partition 2097152 1024 100\n/swapfile file 1048576 0 -2\n",
            "4096 1024 2048 5 4096 0 0",
            "PID COMMAND RSS\n1 systemd 4096\n22 niri 20480\n",
            4096, "niri",
        )
        self.assertEqual(profile["meminfo_bytes"]["MemTotal"], 4096000 * 1024)
        self.assertEqual(profile["meminfo_bytes"]["MemAvailable"], 2048000 * 1024)
        self.assertEqual(profile["meminfo_bytes"]["HugePages_Total"], 2)
        self.assertEqual(profile["swap"][0]["name"], "/dev/zram0")
        self.assertEqual(profile["swap"][0]["size_bytes"], 2097152 * 1024)
        self.assertEqual(profile["top_rss_processes"], [
            {"pid": 1, "name": "systemd", "rss_bytes": 4096 * 1024},
            {"pid": 22, "name": "niri", "rss_bytes": 20480 * 1024},
        ])
        self.assertEqual(profile["qemu_memory_mib"], 4096)
        self.assertEqual(profile["edition"], "niri")

    def test_pss_is_parsed_sorted_and_keeps_cmdline(self):
        processes = parse_pss(
            "838\t51200\tnoctalia\tnoctalia \n"
            "881\t90112\tXwayland\t/usr/bin/Xwayland :0 -rootless\n"
            "1\t2048\tsystemd\n"
            "basura\n"
        )
        self.assertEqual([p["name"] for p in processes], ["Xwayland", "noctalia", "systemd"],
                         "[pss-sorted]")
        self.assertEqual(processes[0]["pss_bytes"], 90112 * 1024)
        self.assertEqual(processes[0]["cmdline"], "/usr/bin/Xwayland :0 -rootless")
        self.assertEqual(processes[2]["cmdline"], "")

    def test_x11_clients_are_found_through_the_peer_inode(self):
        ss = (
            'u_str ESTAB 0 0 @/tmp/.X11-unix/X0 41000 * 41001 users:(("Xwayland",pid=881,fd=12))\n'
            'u_str ESTAB 0 0 * 41001 * 41000 users:(("steam",pid=2001,fd=5))\n'
            'u_str ESTAB 0 0 /tmp/.X11-unix/X0 42000 * 42001 users:(("Xwayland",pid=881,fd=13))\n'
            'u_str ESTAB 0 0 * 42001 * 42000 users:(("polkit-gnome-au",pid=843,fd=7))\n'
            'u_str LISTEN 0 4096 /tmp/.X11-unix/X0 40000 * 0 users:(("niri",pid=789,fd=60))\n'
            'u_str ESTAB 0 0 /run/user/1000/bus 50000 * 50001 users:(("dbus-broker",pid=700,fd=3))\n'
            'u_str ESTAB 0 0 * 50001 * 50000 users:(("noctalia",pid=838,fd=9))\n'
        )
        self.assertEqual(parse_x11_clients(ss), ["polkit-gnome-au", "steam"], "[x11-peer]")
        self.assertEqual(parse_x11_clients(""), [])

    def test_idle_sample_closes_churros_windows_and_runs_for_desktops(self):
        source = (ROOT / "tests/vm/boot_smoke.py").read_text()
        self.assertIn("churros-welcome", CHURROS_GUI)
        self.assertIn("churros-control-center", CHURROS_GUI)
        # pkill admite un solo patrón: varios -x hacen que no cierre nada.
        self.assertNotRegex(source, r"pkill -x \" \+", "[pkill-one-pattern]")
        self.assertIn("pkill -f", source)
        self.assertIn('profile["top_pss_processes"] = parse_pss(pss_text)', source)
        self.assertIn('profile["x11_clients"]', source)
        self.assertRegex(source, r"check_screen\(vm, report, artifacts\)\n\s+collect_idle_memory_profile\(",
                         "[idle-after-screen]")

    def test_ci_boots_each_desktop_with_2_gib(self):
        workflow = (ROOT / ".github/workflows/iso.yml").read_text()
        self.assertRegex(workflow, r"boot_smoke\.py out/\*\.iso [^\n]*--memory 2048",
                         "[ci-2gib] iso.yml tiene que arrancar también con 2 GiB, el mínimo que se promete")

    def test_low_memory_defaults_are_shipped(self):
        """2 GiB: systemd-oomd activo con sus límites, MGLRU y sin el applet de impresión."""
        air = ROOT / "archiso/airootfs"
        services = (air / "root/scripts/services.sh").read_text()
        self.assertRegex(services, r"(?m)^enable_unit systemd-oomd\.service$", "[oomd-enabled]")
        user = (air / "etc/systemd/system/user@.service.d/10-churros-oomd.conf").read_text()
        self.assertRegex(user, r"(?m)^ManagedOOMMemoryPressure=kill$", "[oomd-user-pressure]")
        root = (air / "etc/systemd/system/-.slice.d/10-churros-oomd.conf").read_text()
        self.assertRegex(root, r"(?m)^ManagedOOMSwap=kill$", "[oomd-swap]")
        mglru = (air / "etc/tmpfiles.d/churros-mglru.conf").read_text()
        self.assertRegex(mglru, r"(?m)^w- /sys/kernel/mm/lru_gen/min_ttl_ms( +-){4} +[1-9]\d*$", "[mglru-min-ttl]")
        preset = (air / "etc/systemd/system-preset/10-churros.preset").read_text()
        for unit in ("systemd-networkd.service", "systemd-networkd.socket", "systemd-networkd-wait-online.service",
                     "systemd-homed.service"):
            self.assertRegex(preset, rf"(?m)^disable {re.escape(unit)}$", f"[preset-{unit}]")
        applet = (air / "etc/skel/.config/autostart/print-applet.desktop").read_text()
        self.assertRegex(applet, r"(?m)^Hidden=true$", "[print-applet-hidden]")

    def test_niri_session_start_does_not_wake_xwayland(self):
        """Un cliente X al iniciar sesión deja Xwayland vivo toda la sesión niri."""
        script = (ROOT / "archiso/airootfs/usr/bin/churros-portal-start").read_text()
        for line in script.splitlines():
            code = line.split("#", 1)[0]
            # Ejecuciones de xdg-utils, no `command -v xdg-mime`.
            if re.search(r"\bxdg-(mime|settings|open)\s+(?!>)", code) and "command -v" not in code:
                self.assertIn("env -u DISPLAY", code, "[xwayland-idle] xdg-utils lanza xprop si no conoce el escritorio")

    def test_empty_reads_are_explicit(self):
        profile = parse_memory_profile("", "Filename Type Size Used Priority\n", "", "PID COMMAND RSS\n", 2048, "xfce")
        self.assertEqual(profile["meminfo_bytes"], {})
        self.assertEqual(profile["swap"], [])
        self.assertEqual(profile["top_rss_processes"], [])
        self.assertEqual(profile["qemu_memory_mib"], 2048)


if __name__ == "__main__":
    unittest.main()
