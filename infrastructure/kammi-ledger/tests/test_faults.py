import gc
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from ledgerd.core import Ledger
from ledgerd.writer import StoreOwner, WriterBusy
from scripts.independent_verify import verify_store


class FaultTests(unittest.TestCase):
    def test_crash_matrix_valid_prefix_and_replay(self):
        points = ["cas.before_temp", "cas.during_temp", "cas.after_fsync", "cas.after_rename",
                  "journal.mid_frame", "journal.before_fsync", "journal.after_fsync",
                  "projection.before", "projection.mid_transaction"]
        with tempfile.TemporaryDirectory(prefix="kammi-faults-") as directory:
            for index, point in enumerate(points):
                with self.subTest(point=point):
                    root = Path(directory) / str(index)
                    ledger = Ledger(root)
                    ledger.create_run("baseline", "lab", "admin", "baseline")
                    before = ledger.journal.head
                    ledger.close()
                    gc.collect()
                    code = (
                        "import os,sys;from pathlib import Path;from ledgerd.core import Ledger;"
                        "ledger=Ledger(Path(sys.argv[1]));"
                        "os.environ['KAMMI_ACCEPTANCE_FAULTS']='1';"
                        "os.environ['KAMMI_FAULT_POINT']=sys.argv[2];"
                        "ledger.register_bytes(b'fault source',kind='source',actor='admin',request_id='fault');"
                    )
                    child = subprocess.run([sys.executable, "-c", code, str(root), point],
                                           capture_output=True, timeout=20)
                    self.assertEqual(child.returncode, 91, child.stderr)
                    recovered = Ledger(root)
                    try:
                        report = verify_store(root)
                        self.assertEqual(report["status"], "PASS")
                        self.assertEqual(recovered.journal.head, recovered.graph.position()[1])
                        self.assertIn(len(recovered.journal.events), [1, 2])
                        recovered.register_bytes(b"fault source", kind="source", actor="admin", request_id="fault")
                        self.assertEqual(len(recovered.journal.events), 2)
                        identity = "sha256:" + hashlib.sha256(b"fault source").hexdigest()
                        self.assertTrue(recovered.cas.verify(identity))
                        if point == "journal.mid_frame":
                            self.assertTrue(list((root / "journal" / "recovery").glob("*.partial")))
                        self.assertNotEqual(recovered.journal.head, before)
                    finally:
                        recovered.close()
                        gc.collect()

    def test_writer_crash_releases_os_lock(self):
        with tempfile.TemporaryDirectory(prefix="kammi-owner-crash-") as directory:
            root = Path(directory)
            code = "from pathlib import Path;from ledgerd.writer import StoreOwner;import sys,time;owner=StoreOwner(Path(sys.argv[1]));print('READY',flush=True);time.sleep(30)"
            process = subprocess.Popen([sys.executable, "-c", code, str(root)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(process.stdout.readline().strip(), "READY")
                with self.assertRaises(WriterBusy):
                    StoreOwner(root)
                process.kill()
                process.wait(timeout=10)
                replacement = StoreOwner(root)
                replacement.close()
            finally:
                if process.poll() is None:
                    process.kill()
                process.communicate(timeout=10)

    def test_windows_open_handle_rename_characterization(self):
        with tempfile.TemporaryDirectory(prefix="kammi-rename-") as directory:
            root = Path(directory)
            old, new = root / "old", root / "new"
            old.write_bytes(b"durable")
            with old.open("rb") as handle:
                if os.name == "nt":
                    with self.assertRaises(PermissionError):
                        os.replace(old, new)
                else:
                    os.replace(old, new)
                    self.assertEqual(handle.read(), b"durable")
            if old.exists():
                os.replace(old, new)
            self.assertEqual(new.read_bytes(), b"durable")
