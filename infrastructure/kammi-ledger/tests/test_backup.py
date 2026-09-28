import gc
import shutil
import tempfile
import unittest
from pathlib import Path

from ledgerd.backup import backup, restore
from ledgerd.core import Ledger
from scripts.independent_verify import verify_store


class BackupTests(unittest.TestCase):
    def test_restore_without_projection_and_tamper_refusal(self):
        with tempfile.TemporaryDirectory(prefix="kammi-backup-test-") as directory:
            root = Path(directory)
            ledger = Ledger(root / "live")
            try:
                artifact, _ = ledger.register_bytes(b"backup exact source", kind="source",
                                                    actor="admin", request_id="source")
                seal, _ = ledger.create_seal([artifact], [], "admin", "seal")
                expected = ledger.status()
                before = verify_store(ledger.root)
                manifest = backup(ledger, root / "backup")
                self.assertFalse((root / "backup" / "custody.lbdb").exists())
                restore(root / "backup", root / "restored")
                restored = Ledger(root / "restored")
                try:
                    observed = restored.status()
                    self.assertEqual({k: v for k, v in observed.items() if k != "writer"},
                                     {k: v for k, v in expected.items() if k != "writer"})
                    self.assertEqual(restored.verify_seal(seal), [artifact])
                    self.assertEqual(verify_store(restored.root), before)
                finally:
                    restored.close()
                file = root / "backup" / manifest["files"][0]["path"]
                file.write_bytes(file.read_bytes() + b"tamper")
                with self.assertRaises(ValueError):
                    restore(root / "backup", root / "bad-restore")
                self.assertFalse((root / "bad-restore").exists())
            finally:
                ledger.close()
                gc.collect()
