import gc
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient
from ledgerd.api import create_app
from ledgerd.core import Ledger
from ledgerd.wire import validate_request


class BoundaryTests(unittest.TestCase):
    def test_closed_wire_vocabulary_and_types(self):
        with tempfile.TemporaryDirectory(prefix="kammi-wire-") as directory:
            ledger = Ledger(Path(directory))
            try:
                with TestClient(create_app(ledger, "admin")) as client:
                    response = client.post("/v1/runs", headers={"Authorization": "Bearer admin"},
                        json={"run_id": "run", "lab": "lab", "actor": "admin", "request_id": "run",
                              "jev_special_pre_contact_thing": True})
                    self.assertEqual(response.status_code, 400)
                    self.assertFalse(ledger.runs)
                with self.assertRaises(ValueError):
                    validate_request("/v1/leases/id/renew", {"actor_id": "actor", "fencing_token": True,
                                                          "ttl_seconds": 1, "request_id": "request"})
            finally:
                ledger.close()
                gc.collect()

    def test_native_database_refuses_accidental_independent_writer(self):
        with tempfile.TemporaryDirectory(prefix="kammi-native-owner-") as directory:
            ledger = Ledger(Path(directory))
            try:
                code = ("from pathlib import Path;from ledgerd.projection_runtime import open_database;import sys;"
                        "db=open_database(Path(sys.argv[1]),'custody.lbdb');db.close()")
                result = subprocess.run([sys.executable, "-c", code, directory], capture_output=True, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(b"lock", result.stderr.lower())
                ledger.create_run("still-owned", "library", "admin", "still-owned")
            finally:
                ledger.close()
                gc.collect()
