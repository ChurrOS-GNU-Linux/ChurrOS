"""make-boot-grub-readable contra un modelo de btrfs (sin root ni loop).

El script corre al final de shellprocess@grub-theme y en el hook de pacman
91-churros-boot-grub-readable. En un btrfs real (comprobado con un loop
compress=zstd:1 y grub-fstest):

- un fichero nuevo hereda +C y +m del directorio;
- `chattr` sobre un inodo que ya tiene C y m da EINVAL, también al
  directorio /boot que boot-nocow ya marcó. Eso abortaba la instalación con
  "exit code 1" y sin salida, porque Calamares solo enseña stdout.

Los chattr/lsattr/stat falsos de aquí reproducen esas reglas sobre un árbol
temporal (CHURROS_ROOT). Ejecutar: python3 -m unittest tests.static.test_boot_grub_readable -v
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests import testlib

SCRIPT = testlib.AIROOTFS / "usr/share/churros/scripts/make-boot-grub-readable"

# Atributos en <ruta>.attrs; sin fichero, se heredan del directorio padre.
FLAGS_HELPERS = r'''
flags_of() {
    local p=$1
    if [ -f "$p.attrs" ]; then cat "$p.attrs"; return; fi
    local d; d=$(dirname -- "$p")
    if [ "$d" != "$p" ] && [ -e "$d" ]; then flags_of "$d"; fi
}
'''

CHATTR = '''#!/usr/bin/env bash
''' + FLAGS_HELPERS + r'''
add=""; files=()
for a in "$@"; do
  case "$a" in
    +*) add="$add${a#+}" ;;
    --) ;;
    *) files+=("$a") ;;
  esac
done
for f in "${files[@]}"; do
  cur=$(flags_of "$f")
  # btrfs: volver a fijar C y m en un inodo que ya los tiene -> EINVAL.
  case "$cur" in *C*m*|*m*C*)
    echo "chattr: Invalid argument while setting flags on $f" >&2; exit 1 ;;
  esac
  [ "$FAKE_FS" = btrfs ] || { echo "chattr: Operation not supported while setting flags on $f" >&2; exit 1; }
  printf '%s%s' "$cur" "$add" | fold -w1 | sort -u | tr -d '\n' > "$f.attrs"
done
'''

LSATTR = '''#!/usr/bin/env bash
''' + FLAGS_HELPERS + r'''
f="${@: -1}"
[ -e "$f" ] || { echo "lsattr: No such file or directory while trying to stat $f" >&2; exit 1; }
printf -- '----%s---- %s\n' "$(flags_of "$f")" "$f"
'''

STAT = r'''#!/usr/bin/env bash
if [ "$1" = -f ]; then echo "$FAKE_FS"; exit 0; fi
exec /usr/bin/stat "$@"
'''


class MakeBootGrubReadable(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="churros-bootgrub-")
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        for name, body in (("chattr", CHATTR), ("lsattr", LSATTR), ("stat", STAT)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.root = self.tmp / "root"
        self.boot = self.root / "boot"
        (self.boot / "grub/themes/churros").mkdir(parents=True)

    def populate(self):
        (self.boot / "vmlinuz-linux-cachyos").write_bytes(b"kernel" * 1000)
        (self.boot / "initramfs-linux-cachyos.img").write_bytes(b"initrd" * 1000)
        (self.boot / "intel-ucode.img").write_bytes(b"ucode")
        (self.boot / "vmlinuz-linux").symlink_to("vmlinuz-linux-cachyos")
        (self.boot / "initramfs-linux.img").symlink_to("initramfs-linux-cachyos.img")
        (self.boot / "grub/themes/churros/theme.txt").write_text("title-text: \"\"\n")
        (self.boot / "grub/themes/churros/icons").mkdir()
        for name in ("logo.png", "select_c.png", "icons/churros.png", "inter-regular-18.pf2"):
            (self.boot / "grub/themes/churros" / name).write_bytes(b"x" * 64)

    def run_script(self, fs="btrfs"):
        """(código, stdout). Solo stdout, como lo enseña Calamares; stderr se descarta."""
        env = {**os.environ, "PATH": f"{self.bin}:{os.environ['PATH']}", "CHURROS_ROOT": str(self.root),
               "FAKE_FS": fs}
        result = subprocess.run(["bash", str(SCRIPT)], env=env, timeout=60, text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return result.returncode, result.stdout

    def mark_boot_like_boot_nocow(self):
        (self.boot.with_name("boot.attrs")).write_text("Cm")

    def test_calamares_order_and_pacman_hook_reruns(self):
        """boot-nocow marca /boot antes de unpackfs; el hook lo repite en cada kernel."""
        self.mark_boot_like_boot_nocow()
        self.populate()
        for attempt in range(3):
            code, out = self.run_script()
            self.assertEqual(code, 0, f"[boot-rerun] ejecución {attempt + 1}:\n{out}")
        self.assertEqual(list(self.boot.glob("*.grub-rewr")), [], "quedan temporales")

    def test_symlinks_stay_links_to_the_rewritten_image(self):
        self.mark_boot_like_boot_nocow()
        self.populate()
        code, out = self.run_script()
        self.assertEqual(code, 0, out)
        for link, target in (("vmlinuz-linux", "vmlinuz-linux-cachyos"),
                             ("initramfs-linux.img", "initramfs-linux-cachyos.img")):
            path = self.boot / link
            self.assertTrue(path.is_symlink(),
                            f"[symlink-kept] {link} pasó a ser una copia: la próxima actualización la deja vieja")
            self.assertEqual(os.readlink(path), target)
        self.assertEqual((self.boot / "vmlinuz-linux-cachyos").read_bytes(), b"kernel" * 1000)

    def test_every_theme_file_is_rewritten(self):
        """El logo, los iconos y las piezas del tema también: uno ilegible tira el tema entero."""
        self.mark_boot_like_boot_nocow()
        self.populate()
        theme = self.boot / "grub/themes/churros"
        files = ["theme.txt", "logo.png", "select_c.png", "icons/churros.png", "inter-regular-18.pf2"]
        before = {name: (theme / name).stat().st_ino for name in files}
        code, out = self.run_script()
        self.assertEqual(code, 0, out)
        same = [name for name in files if (theme / name).stat().st_ino == before[name]]
        self.assertEqual(same, [], "[theme-rewritten] estos ficheros del tema no se reescribieron en un inodo nuevo")

    def test_unmarked_boot_gets_nocow(self):
        """Un /boot sin marcar (instalación antigua) recibe +C y se reescribe."""
        self.populate()
        code, out = self.run_script()
        self.assertEqual(code, 0, out)
        self.assertIn("C", self.boot.with_name("boot.attrs").read_text())

    def test_non_btrfs_boot_is_left_alone(self):
        """Un /boot ext4 bajo una raíz btrfs: chattr +C no existe allí."""
        self.populate()
        code, out = self.run_script(fs="ext2/ext3")
        self.assertEqual(code, 0, f"[non-btrfs-skip]\n{out}")
        self.assertEqual(list(self.boot.glob("*.attrs")), [])
        self.assertTrue((self.boot / "vmlinuz-linux").is_symlink())

    def test_errors_reach_stdout(self):
        """Calamares solo enseña stdout: un fallo tiene que decir qué pasó."""
        self.populate()
        (self.bin / "dd").write_text("#!/usr/bin/env bash\necho 'dd: No space left on device' >&2\nexit 1\n")
        (self.bin / "dd").chmod(0o755)
        code, out = self.run_script()
        self.assertNotEqual(code, 0)
        self.assertIn("No space left on device", out, "[stdout] el error de dd no llega a la salida estándar")
        self.assertIn("make-boot-grub-readable: falló la línea", out, "[stdout] sin la línea que falló")


if __name__ == "__main__":
    unittest.main()
