"""El soporte NVIDIA: coherencia entre el instalador, el airootfs y las listas.

Lo que estas pruebas protegen, y por qué cada una existe:

- El grupo de netinstall tiene que instalar el módulo del kernel que se
  instala de verdad. Con `nvidia-open` (el precompilado de Arch) pacman
  arrastraría el paquete `linux`, que no es el kernel de ninguna edición; con
  `nvidia-open-dkms` haría falta `linux-cachyos-headers` y un compilador en el
  destino. Ninguno de los dos es lo que se quiere y los dos fallan en silencio:
  pacman termina bien y el sistema arranca sin salida gráfica (niri 26.04
  descarta los renderizadores EGL por software).
- Ningún grupo puede marcarse solo. El nodo raíz del árbol de netinstall nace
  marcado y los hijos heredan el estado del padre, así que un grupo sin
  `selected: false` se instalaría a todo el mundo.
- Las dos familias de módulos (moderna y heredada) no pueden anidarse: marcar
  el padre marca a los hijos y se instalarían las dos, que chocan entre sí.
- El perfil de VRAM de niri tiene que seguir ahí y con el valor documentado.

Los nombres de paquete se comprueban contra los repos reales en
tests/container/test_arch_repos.py; aquí solo se comprueba la coherencia
interna, que es lo que un cambio descuidado rompe.
"""
from __future__ import annotations

import json
from pathlib import Path
import unittest

from tests import testlib

NETINSTALL = testlib.ROOT / "installer/calamares/modules/netinstall.yaml"
NETINSTALL_AARCH64 = testlib.ROOT / "installer/calamares/modules/aarch64/netinstall.yaml"
PROFILE = (testlib.ROOT / "archiso/airootfs/etc/nvidia/nvidia-application-profiles-rc.d"
           / "50-limit-free-buffer-pool-in-wayland-compositors.json")

# Paquetes que solo existen para el driver: no están en ninguna lista de la ISO
# a propósito (ver docs/nvidia.md, Decisión C).
MODULE_PACKAGES = {"linux-cachyos-nvidia-open", "linux-cachyos-nvidia-580xx"}
LEGACY_PACKAGES = {"linux-cachyos-nvidia-580xx", "nvidia-580xx-utils",
                   "nvidia-580xx-settings", "lib32-nvidia-580xx-utils"}
MODERN_PACKAGES = {"linux-cachyos-nvidia-open", "nvidia-utils", "nvidia-settings",
                   "nvidia-prime", "lib32-nvidia-utils"}


def load_groups(path) -> dict:
    """YAML del fichero de grupos. `yaml` es opcional: sin él, la prueba se salta."""
    yaml = testlib.require_module(unittest.TestCase("run"), "yaml")
    return yaml.safe_load(testlib.read_text(path))


def package_names(group: dict) -> set[str]:
    names = set()
    for entry in group.get("packages") or []:
        names.add(entry.get("name") if isinstance(entry, dict) else entry)
    for child in group.get("subgroups") or []:
        names |= package_names(child)
    return {name for name in names if isinstance(name, str)}


class NetinstallGroups(unittest.TestCase):
    def groups(self) -> list[dict]:
        return load_groups(NETINSTALL).get("groups") or []

    def test_groups_are_not_preselected(self):
        """Un grupo sin `selected: false` se instala siempre (el raíz nace marcado)."""
        for group in self.groups():
            self.assertIs(group.get("selected"), False,
                          f"[nvidia-preselected] el grupo '{group.get('name')}' no lleva "
                          "selected: false; netinstall lo marcaría para todo el mundo")

    def test_families_are_siblings_not_nested(self):
        """Marcar un grupo marca a sus hijos: anidar las dos familias instala ambas."""
        for group in self.groups():
            nested = package_names({"subgroups": group.get("subgroups") or []})
            self.assertFalse(nested & MODULE_PACKAGES,
                             f"[nvidia-nested] el grupo '{group.get('name')}' anida otro que "
                             f"instala un módulo ({sorted(nested & MODULE_PACKAGES)}); marcar el padre "
                             "instalaría las dos familias, que chocan entre sí")
            self.assertEqual(group.get("subgroups") or [], [],
                             f"[nvidia-nested] el grupo '{group.get('name')}' tiene subgrupos")

    def test_each_group_installs_a_kernel_module_for_cachyos(self):
        """El módulo tiene que ser el de linux-cachyos: es el kernel de x86_64."""
        installers = [item for item in testlib.EDITIONS
                      if item.arch == "x86_64" and item.installer]
        self.assertTrue(installers)
        for item in installers:
            if "linux-cachyos" not in testlib.packages(item):
                continue
            for group in self.groups():
                names = package_names(group)
                modules = names & MODULE_PACKAGES
                self.assertTrue(modules,
                                f"[nvidia-module] el grupo '{group.get('name')}' no instala un módulo "
                                f"del kernel para {item.id} (linux-cachyos): sin módulo no hay driver")
                # nvidia-open depende de `linux` y arrastraría otro kernel.
                self.assertNotIn("nvidia-open", names,
                                 "[nvidia-module] nvidia-open depende de `linux`; en ChurrOS "
                                 "arrastraría un kernel que no se usa")
                self.assertNotIn("nvidia-open-dkms", names,
                                 "[nvidia-module] nvidia-open-dkms necesita linux-cachyos-headers "
                                 "y un compilador en el destino; usa el módulo precompilado")

    def test_module_matches_the_rest_of_its_group(self):
        """Un grupo no puede mezclar el driver moderno con el heredado."""
        for group in self.groups():
            names = package_names(group)
            if not names:
                continue
            self.assertIn(names, (MODERN_PACKAGES, LEGACY_PACKAGES),
                          f"[nvidia-family] el grupo '{group.get('name')}' mezcla paquetes de las dos "
                          f"familias ({sorted(names)}); nvidia-utils y nvidia-580xx-utils ocupan "
                          "las mismas rutas y pacman no puede instalar los dos")

    def test_aarch64_has_no_groups(self):
        """Sin módulo precompilado para linux-aarch64, no se ofrece nada."""
        data = load_groups(NETINSTALL_AARCH64)
        self.assertEqual(data.get("groups") or [], [],
                         "[nvidia-aarch64] la variante aarch64 ofrece grupos NVIDIA; no hay módulo "
                         "precompilado para linux-aarch64 y la instalación acabaría en DKMS")


class NiriVramProfile(unittest.TestCase):
    """El perfil que evita el consumo desmedido de VRAM de niri con el driver."""

    def test_profile_limits_the_buffer_pool(self):
        self.assertTrue(PROFILE.is_file(), "[nvidia-vram] falta el perfil de VRAM de niri")
        data = json.loads(testlib.read_text(PROFILE))
        rules = data.get("rules") or []
        self.assertTrue(rules, "[nvidia-vram] el perfil no tiene reglas")
        self.assertIn("niri", [rule.get("pattern", {}).get("matches") for rule in rules],
                      "[nvidia-vram] ninguna regla se aplica al proceso niri")
        profiles = {profile.get("name"): profile for profile in data.get("profiles") or []}
        referenced = [rule.get("profile") for rule in rules]
        for name in referenced:
            self.assertIn(name, profiles,
                          f"[nvidia-vram] la regla apunta al perfil '{name}', que no existe")
            settings = {item.get("key"): item.get("value")
                        for item in profiles[name].get("settings") or []}
            self.assertEqual(settings.get("GLVidHeapReuseRatio"), 0,
                             "[nvidia-vram] GLVidHeapReuseRatio tiene que ser 0 (el valor que "
                             "documentan niri y el wiki de Arch); sin él niri reserva cientos de "
                             "MiB de VRAM ociosos")


class VerifyInstallNvidia(unittest.TestCase):
    """verify-install tiene que ver el driver instalado a medias.

    Se ejecuta el script real con un `pacman` falso y un directorio de módulos
    temporal (CHURROS_NVIDIA_MODULES), así que no depende del equipo donde
    corre. Las comprobaciones que no son de NVIDIA fallan aquí porque no es un
    sistema instalado: lo que se mira es si aparece la línea de NVIDIA.
    """

    def setUp(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory(prefix="churros-nvidia-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        bindir = self.tmp / "bin"
        bindir.mkdir()
        self.installed = self.tmp / "installed"
        fake = bindir / "pacman"
        # `pacman -Q <paquete>`: 0 solo si está en la lista.
        fake.write_text(
            "#!/usr/bin/env bash\n"
            'grep -qx "${2:-}" "$PACMAN_INSTALLED" 2>/dev/null && exit 0\nexit 1\n')
        fake.chmod(0o755)
        self.bin = bindir
        self.modules = self.tmp / "modules"
        self.greetd = self.tmp / "greetd.toml"
        self.greetd.write_text("")

    def run_verify(self, installed: list[str]) -> str:
        import os
        import subprocess
        self.installed.write_text("".join(f"{name}\n" for name in installed))
        env = {**os.environ,
               "PATH": f"{self.bin}:{os.environ['PATH']}",
               "PACMAN_INSTALLED": str(self.installed),
               "CHURROS_VERIFY_LOG": str(self.tmp / "verify.log"),
               "CHURROS_GREETD_CONF": str(self.greetd),
               "CHURROS_NVIDIA_MODULES": str(self.modules)}
        subprocess.run(["bash", str(testlib.AIROOTFS / "usr/share/churros/scripts/verify-install")],
                       env=env, timeout=120, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return (self.tmp / "verify.log").read_text()

    def test_without_driver_nothing_is_checked(self):
        """Quien no pidió NVIDIA no ve ninguna comprobación nueva (el Live sigue igual)."""
        log = self.run_verify([])
        self.assertNotIn("driver NVIDIA", log,
                         "[nvidia-verify-quiet] verify-install habla de NVIDIA sin haber driver "
                         "instalado: añadiría ruido a todas las instalaciones")

    def test_missing_kernel_module_fails(self):
        """Módulo pedido, sin nvidia.ko: es el caso de la pantalla negra."""
        (self.modules / "linux-cachyos").mkdir(parents=True)
        log = self.run_verify(["linux-cachyos-nvidia-open", "nvidia-utils"])
        self.assertIn("módulo nvidia.ko instalado", log,
                      "[nvidia-verify-module] verify-install no comprueba el módulo")
        self.assertIn("AVISO driver NVIDIA", log,
                      "[nvidia-verify-module] sin nvidia.ko no avisa: la instalación seguiría "
                      "hasta un sistema sin salida gráfica")

    def test_installed_module_is_found_in_either_layout(self):
        """nvidia.ko vive en kernel/drivers/video/ o en extra/: se busca el fichero."""
        for relative in ("kernel/drivers/video/nvidia.ko", "extra/nvidia.ko.zst"):
            with self.subTest(layout=relative):
                target = self.modules / "linux-cachyos"
                if target.exists():
                    import shutil
                    shutil.rmtree(target)
                (target / relative).parent.mkdir(parents=True)
                (target / relative).touch()
                log = self.run_verify(["linux-cachyos-nvidia-open", "nvidia-utils"])
                self.assertIn("OK   driver NVIDIA (linux-cachyos-nvidia-open): módulo nvidia.ko instalado",
                              log, f"[nvidia-verify-layout] no encuentra el módulo en {relative}")

    def test_module_without_libraries_fails(self):
        """Módulo sin nvidia-utils: el driver no enlaza.

        Un `for` que solo comprueba al encontrar el paquete dejaba pasar este
        caso en silencio (lo encontró la prueba manual de los cuatro escenarios).
        """
        target = self.modules / "linux-cachyos" / "kernel/drivers/video"
        target.mkdir(parents=True)
        (target / "nvidia.ko").touch()
        log = self.run_verify(["linux-cachyos-nvidia-580xx"])
        self.assertIn("AVISO driver NVIDIA (linux-cachyos-nvidia-580xx): bibliotecas", log,
                      "[nvidia-verify-utils] no avisa cuando falta nvidia-utils: el módulo está "
                      "pero el driver no puede enlazar")


if __name__ == "__main__":
    unittest.main()
