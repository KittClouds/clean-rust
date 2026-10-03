import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_freeze", ROOT / "tools" / "check_freeze.py")
cf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cf)


class Freeze(unittest.TestCase):
    def test_frozen_files_are_unchanged(self):
        """Fails if anything in vcs/, the golden fixtures or VCS-1A-FREEZE.md changed since the seal. A deliberate change needs a dated amendment and a new seal."""
        self.assertEqual(cf.main([]), 0)

    def test_manifest_covers_every_runtime_module(self):
        import json
        rec = json.loads(cf.MANIFEST.read_text(encoding="ascii"))
        for name in ("canon", "schema", "region", "authority", "scalar", "harness", "transport", "substrate", "__main__"):
            self.assertIn(f"vcs/{name}.py", rec["files"])
        self.assertIn("VCS-1A-FREEZE.md", rec["files"])


if __name__ == "__main__":
    unittest.main()
