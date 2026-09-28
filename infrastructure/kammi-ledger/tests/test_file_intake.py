from __future__ import annotations

import gc
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ledgerd.api import create_app
from ledgerd.core import Ledger


class FileIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="kammi-file-intake-"))
        self.ledger = Ledger(self.root / "ledger")
        self.client = TestClient(create_app(self.ledger, "intake-secret"))
        self.headers = {"Authorization": "Bearer intake-secret"}

    def tearDown(self) -> None:
        self.client.close()
        self.ledger.close()
        del self.ledger
        gc.collect()
        shutil.rmtree(self.root)

    def test_large_local_file_import_and_idempotent_retry(self) -> None:
        source = self.root / "large-panel.bin"
        block = b"sealed-panel-fixture\n" * 1024
        with source.open("wb") as stream:
            for _ in range(900):
                stream.write(block)
        data = source.read_bytes()
        self.assertGreater(len(data), 16 * 1024 * 1024)
        expected = "sha256:" + hashlib.sha256(data).hexdigest()
        body = {"path": str(source), "expected_sha256": expected,
                "expected_bytes": len(data), "kind": "panel-fixture",
                "actor": "chief", "request_id": "local-intake-1"}
        first = self.client.post("/v1/artifacts/import-local", headers=self.headers, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["artifact_id"], expected)
        self.assertEqual(self.ledger.cas.get(expected), data)
        before = self.ledger.status()["journal_events"]
        second = self.client.post("/v1/artifacts/import-local", headers=self.headers, json=body)
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(second.json()["event_id"], first.json()["event_id"])
        self.assertEqual(self.ledger.status()["journal_events"], before)

    def test_wrong_identity_and_unauthorized_intake_do_not_register(self) -> None:
        source = self.root / "panel.bin"
        source.write_bytes(b"sealed bytes")
        body = {"path": str(source), "expected_sha256": "sha256:" + "0" * 64,
                "expected_bytes": source.stat().st_size, "kind": "panel-fixture",
                "actor": "chief", "request_id": "bad-intake"}
        self.assertEqual(self.client.post("/v1/artifacts/import-local", json=body).status_code, 401)
        wrong = self.client.post("/v1/artifacts/import-local", headers=self.headers, json=body)
        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(self.ledger.status()["journal_events"], 0)
        self.assertEqual(self.ledger.artifacts, {})

    def test_relative_source_is_rejected(self) -> None:
        body = {"path": "relative.bin", "expected_sha256": "sha256:" + "0" * 64,
                "expected_bytes": 0, "kind": "panel-fixture",
                "actor": "chief", "request_id": "relative-intake"}
        response = self.client.post("/v1/artifacts/import-local", headers=self.headers, json=body)
        self.assertEqual(response.status_code, 400)
