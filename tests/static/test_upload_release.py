"""scripts/upload-release.py: qué sumas de verificación se publican."""

import importlib.util
import tempfile
import unittest
from pathlib import Path

from tests import testlib


def load_upload_release():
    spec = importlib.util.spec_from_file_location("upload_release", testlib.ROOT / "scripts/upload-release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IsoSums(unittest.TestCase):
    def test_each_version_keeps_its_own_sums(self):
        upload = load_upload_release()
        text = "a" * 64 + "  ChurrOS-1.5.7-niri-x86_64.iso\n"
        with tempfile.TemporaryDirectory() as tmp:
            files = upload.iso_sums_files(Path(tmp), "1.5.7", text)
            names = [path.name for path in files]
            self.assertIn("SHA256SUMS-1.5.7", names,
                          "[versioned-sha256sums] sin SHA256SUMS-<versión>, publicar una versión deja las ISO "
                          "anteriores del historial de la web sin suma con la que verificarlas")
            self.assertEqual(names[-1], "SHA256SUMS", "SHA256SUMS (la versión actual) se sube el último")
            for path in files:
                self.assertEqual(path.read_text(encoding="utf-8"), text)


if __name__ == "__main__":
    unittest.main()
