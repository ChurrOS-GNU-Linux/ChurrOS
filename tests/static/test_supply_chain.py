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

from tests import testlib

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
        build = aur[aur.index("build_aur() {"):aur.index("\nbuild_aur python-pywal")]
        self.assertRegex(build, r'GNUPGHOME="\$\(mktemp -d [^\n]*\)"\n\s*export GNUPGHOME',
                         "[aur-private-gnupg] cada paquete AUR necesita su llavero: compartido, otro gpg se queda con el candado")
        self.assertLess(build.index("export GNUPGHOME"), build.index("gpg --import"),
                        "[aur-private-gnupg] el llavero propio tiene que existir antes de importar")
        self.assertLess(build.index("export GNUPGHOME"), build.index("makepkg -sf"),
                        "[aur-private-gnupg] makepkg verifica con el mismo llavero")
        self.assertTrue((ROOT / "scripts/keys/pgp/155DC67DC25496572CDD608FF635E931C2834999.asc").is_file(),
                        "python-pywal signing key must be available offline and pinned by its full fingerprint")

    def test_remote_pacman_servers_use_https(self) -> None:
        """La metadata de pacman no viaja en claro (auditoría A3).

        SigLevel protege los paquetes, no la base de datos: por http se puede
        degradar a versiones antiguas firmadas o dirigir a otro paquete
        firmado. http://mirror.archlinuxarm.org estaba en core/extra/alarm,
        con tres mirrors https en el mismo fichero que sí sirven el repo.
        """
        findings = {}
        for conf in sorted(ROOT.glob("archiso/pacman.*.conf")):
            for number, line in enumerate(conf.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or not stripped.startswith("Server ="):
                    continue
                url = stripped.split("=", 1)[1].strip()
                if url.startswith("http://"):
                    findings[f"supply-chain:https-only:{conf.name}:{number}"] = (
                        f"{conf.name}:{number} sirve paquetes por http sin cifrar ({url}): "
                        "usa un mirror https, la firma no protege la metadata")
        testlib.assert_findings(self, "supply-chain:https-only", findings)

    def test_gitignore_covers_credentials(self) -> None:
        """Material criptográfico accidental no debe entrar al repo (V7).

        Hoy no hay secretos versionados, pero sin patrones cualquier `.env`,
        `*.pem` o `id_rsa` que aparezca en el árbol se sube sin aviso.
        """
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        # Líneas efectivas: un patrón comentado no ignora nada.
        patterns = {
            line.strip()
            for line in ignore.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        findings = {}
        for pattern in (".env", "*.pem", "*.key", "id_rsa*"):
            if pattern not in patterns:
                findings[f"gitignore:{pattern}"] = f".gitignore no cubre {pattern}"
        testlib.assert_findings(self, "gitignore", findings)


if __name__ == "__main__":
    unittest.main()

if __name__ == "__main__":
    unittest.main()
