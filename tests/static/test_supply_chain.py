#!/usr/bin/env python3
"""Auditoría de reproducibilidad de compilación y cadena de dependencias (issue #147).

Comprueba que:
- install-deps.sh en Arch instala todas las herramientas que exige el build
  de mkarchiso y doctor.sh (base-devel, dosfstools, mtools, squashfs-tools, libisoburn),
  y no realiza actualizaciones parciales peligrosas con pacman -Sy sin -u.
- archiso/profiledef.sh y scripts/cli/build.sh preservan SOURCE_DATE_EPOCH
  usando la fecha del commit de Git (%ct) para asegurar reproducibilidad.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]


class TestSupplyChainAndReproducibility(unittest.TestCase):
    def test_install_deps_arch_packages(self) -> None:
        content = (ROOT / "install-deps.sh").read_text(encoding="utf-8")

        # Comprobar que no hay pacman -Sy sin u
        self.assertNotIn("sudo pacman -Sy)", content,
                         "[supply-chain:no-partial-upgrade] install-deps.sh no debe usar pacman -Sy sin -u (actualización parcial)")

        # Extraer REQUIRED=(...) del bloque arch
        arch_match = re.search(r'arch\)\s+REQUIRED=\((.*?)\)', content, re.DOTALL)
        self.assertIsNotNone(arch_match, "No se encontró REQUIRED en el bloque arch de install-deps.sh")
        packages = set(arch_match.group(1).split())

        expected = {"base-devel", "dosfstools", "mtools", "squashfs-tools", "libisoburn", "archiso", "grub"}
        missing = expected - packages
        self.assertFalse(missing, f"[supply-chain:missing-deps] Faltan paquetes de build en install-deps.sh: {missing}")

    def test_profiledef_reproducible_timestamp(self) -> None:
        content = (ROOT / "archiso/profiledef.sh").read_text(encoding="utf-8")
        self.assertIn("git log -1 --format=%ct", content,
                      "[reproducible:profiledef-git-epoch] profiledef.sh debe usar el commit de git para SOURCE_DATE_EPOCH")

    def test_build_sh_passes_source_date_epoch(self) -> None:
        content = (ROOT / "scripts/cli/build.sh").read_text(encoding="utf-8")
        self.assertIn("SOURCE_DATE_EPOCH", content)
        self.assertRegex(content, r'sudo\s+env\s+.*?SOURCE_DATE_EPOCH=.*?mkarchiso',
                         "[reproducible:build-sudo-env] build.sh debe pasar SOURCE_DATE_EPOCH a mkarchiso por sudo env")

    def test_remote_pkgbuilds_are_pinned_and_keep_signature_checks(self) -> None:
        scripts = ["scripts/build-aur.sh", "scripts/build-calamares.sh", "scripts/build-bazaar.sh"]
        for name in scripts:
            content = (ROOT / name).read_text(encoding="utf-8")
            self.assertNotIn("--skippgpcheck", content, f"{name} desactiva firmas PGP")
            self.assertNotRegex(content, r"/-/raw/(?:main|master)/", f"{name} descarga una rama mutable")
        aur = (ROOT / "scripts/build-aur.sh").read_text(encoding="utf-8")
        calamares = (ROOT / "scripts/build-calamares.sh").read_text(encoding="utf-8")
        self.assertRegex(aur, r"git checkout --detach \"\$\{AUR_COMMITS\[\$name\]\}\"")
        self.assertRegex(calamares, r"git -C \"\$WORK_DIR\" checkout --detach \"\$CALAMARES_AUR_COMMIT\"")
        self.assertIn('key_file="$SCRIPT_DIR/keys/pgp/${key^^}.asc"', aur)
        self.assertIn('gpg --show-keys --with-colons "$key_file"', aur)
        self.assertIn('if [ "$actual_key" != "${key^^}" ]; then', aur)
        self.assertTrue((ROOT / "scripts/keys/pgp/155DC67DC25496572CDD608FF635E931C2834999.asc").is_file(),
                        "python-pywal signing key must be available offline and pinned by its full fingerprint")


if __name__ == "__main__":
    unittest.main()
