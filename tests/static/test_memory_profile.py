"""Regression coverage for the QEMU memory and zram profile."""
from __future__ import annotations

import unittest
from pathlib import Path

from tests.vm.boot_smoke import parse_memory_profile, zram_is_active

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

    def test_empty_reads_are_explicit(self):
        profile = parse_memory_profile("", "Filename Type Size Used Priority\n", "", "PID COMMAND RSS\n", 2048, "xfce")
        self.assertEqual(profile["meminfo_bytes"], {})
        self.assertEqual(profile["swap"], [])
        self.assertEqual(profile["top_rss_processes"], [])
        self.assertEqual(profile["qemu_memory_mib"], 2048)


if __name__ == "__main__":
    unittest.main()
