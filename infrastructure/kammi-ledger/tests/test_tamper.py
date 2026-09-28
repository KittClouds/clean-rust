import gc
import hashlib
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path

from ledgerd.backup import backup, restore
from ledgerd.core import Ledger
from scripts.independent_verify import verify_store
from scripts.projection_compare import compare_rebuild


class TamperTests(unittest.TestCase):
    def test_authoritative_and_projection_mutations(self):
        with tempfile.TemporaryDirectory(prefix="kammi-tamper-") as directory:
            root = Path(directory)
            ledger = Ledger(root / "source")
            try:
                source, _ = ledger.register_bytes(b"exact source", kind="source", actor="admin", request_id="source")
                seal, _ = ledger.create_seal([source], [], "admin", "seal")
                backup(ledger, root / "backup")
                self.assertEqual(compare_rebuild(ledger)["status"], "PASS")
                conn = ledger.graph.conn
                conn.execute("MATCH (a:Artifact {id:$id}) SET a.byte_count=999", {"id": source})
                with self.assertRaisesRegex(ValueError, "projection content"):
                    compare_rebuild(ledger)
                for mutation in ("artifact_byte", "json_field", "journal_frame", "event_predecessor", "seal_parent", "seal_member"):
                    with self.subTest(mutation=mutation):
                        target = root / mutation
                        restore(root / "backup", target)
                        if mutation == "artifact_byte":
                            path = target / "objects" / "sha256" / source[7:9] / source[9:]
                            path.write_bytes(b"wrong source")
                        elif mutation in {"seal_parent", "seal_member", "json_field"}:
                            identity = ledger.seal_artifacts[seal]
                            path = target / "objects" / "sha256" / identity[7:9] / identity[9:]
                            value = json.loads(path.read_bytes())
                            field = "parents" if mutation == "seal_parent" else "direct_members"
                            value[field] = ["sha256:" + "1" * 64]
                            path.write_text(json.dumps(value))
                        else:
                            path = target / "journal" / "events.log"
                            raw = bytearray(path.read_bytes())
                            if mutation == "journal_frame":
                                raw[10] ^= 1
                            else:
                                length = struct.unpack(">I", raw[:4])[0]
                                value = json.loads(raw[4:4 + length])
                                value["prev"] = "sha256:" + "1" * 64
                                import jcs
                                event = jcs.canonicalize(value)
                                raw = bytearray(struct.pack(">I", len(event)) + event + hashlib.sha256(event).digest() + raw[4 + length + 32:])
                            path.write_bytes(raw)
                        with self.assertRaises((ValueError, FileNotFoundError)):
                            verify_store(target)
            finally:
                ledger.close()
                gc.collect()
