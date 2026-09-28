"""Phoenix vault product authority, replay, and single-database qualification."""
from __future__ import annotations

import base64
import gc
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from ledgerd.api import create_app
from ledgerd.core import Ledger
from ledgerd.identity import canonical


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="kammi-vault-test-"))
        self.ledger = Ledger(self.root)
        self.secret = "phoenix-service-token"
        self.ledger.register_actor("phoenix-service", "service", "phoenix",
                                   hashlib.sha256(self.secret.encode()).hexdigest(), "actor")
        self.client = TestClient(create_app(self.ledger, "admin", acceptance_mode=True))
        self.headers = {"Authorization": "Bearer " + self.secret}

    def tearDown(self):
        self.client.close()
        self.ledger.close()
        gc.collect()
        shutil.rmtree(self.root)

    def post(self, path, body):
        response = self.client.post(path, headers=self.headers,
                                    json={**body, "actor_id": "phoenix-service"})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_source_generation_reader_and_rebuild(self):
        self.post("/v1/vaults", {"vault_id": "phoenix.vault.a", "request_id": "create"})
        first = self.post("/v1/vaults/source", {
            "vault_id": "phoenix.vault.a", "source_id": "note.3", "base_revision": 0,
            "content_base64": base64.b64encode(b"hello vault").decode(),
            "request_id": "source-1"})["source"]
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["epoch"], 1)
        retry = self.post("/v1/vaults/source", {
            "vault_id": "phoenix.vault.a", "source_id": "note.3", "base_revision": 0,
            "content_base64": base64.b64encode(b"hello vault").decode(),
            "request_id": "source-1"})["source"]
        self.assertEqual(retry, first)
        stale = self.client.post("/v1/vaults/source", headers=self.headers, json={
            "vault_id": "phoenix.vault.a", "source_id": "note.3", "base_revision": 0,
            "content_base64": base64.b64encode(b"stale").decode(),
            "actor_id": "phoenix-service", "request_id": "stale"})
        self.assertEqual(stale.status_code, 400)
        asset = self.post("/v1/vaults/asset", {
            "vault_id": "phoenix.vault.a", "kind": "scene", "request_id": "asset",
            "content_base64": base64.b64encode(b"scene bytes").decode()})["artifact_id"]
        manifest = {"schema": "PHOENIX_VAULT_GENERATION_V1",
                    "vault_id": "phoenix.vault.a", "source_epoch": 1,
                    "generation_id": 1, "asset_ids": [asset]}
        manifest_id = self.post("/v1/vaults/asset", {
            "vault_id": "phoenix.vault.a", "kind": "manifest", "request_id": "manifest",
            "content_base64": base64.b64encode(canonical(manifest)).decode()})["artifact_id"]
        asset_response = self.client.get(f"/v1/vaults/phoenix.vault.a/assets/{asset}",
            headers=self.headers, params={"actor_id": "phoenix-service"})
        self.assertEqual(asset_response.status_code, 200)
        self.assertEqual(asset_response.content, b"scene bytes")
        self.post("/v1/vaults/generation", {
            "vault_id": "phoenix.vault.a", "source_epoch": 1, "generation_id": 1,
            "manifest_artifact_id": manifest_id, "asset_ids": [asset],
            "request_id": "generation"})
        self.post("/v1/vaults/reader", {
            "vault_id": "phoenix.vault.a", "source_id": "note.3",
            "revision": 1, "offset": 5, "request_id": "reader"})
        view = self.client.get("/v1/vaults/phoenix.vault.a",
                               headers=self.headers, params={"actor_id": "phoenix-service"}).json()
        self.assertTrue(view["generation_current"])
        self.assertEqual(view["reader"]["offset"], 5)
        second = self.post("/v1/vaults/source", {
            "vault_id": "phoenix.vault.a", "source_id": "note.3", "base_revision": 1,
            "content_base64": base64.b64encode(b"edited vault").decode(),
            "request_id": "source-2"})["source"]
        self.assertEqual(second["revision"], 2)
        self.assertFalse(self.ledger.vault_view("phoenix.vault.a", "phoenix-service")["generation_current"])
        stale_generation = self.client.post("/v1/vaults/generation", headers=self.headers, json={
            "vault_id": "phoenix.vault.a", "source_epoch": 1, "generation_id": 2,
            "manifest_artifact_id": manifest_id, "asset_ids": [asset],
            "actor_id": "phoenix-service", "request_id": "stale-generation"})
        self.assertEqual(stale_generation.status_code, 400)
        journal_head = self.ledger.journal.head
        self.ledger.close()
        gc.collect()
        db = self.root / "custody.lbdb"
        if db.is_dir():
            shutil.rmtree(db)
        elif db.exists():
            db.unlink()
        self.ledger = Ledger(self.root)
        self.assertEqual(self.ledger.journal.head, journal_head)
        self.assertEqual(self.ledger.vault_view("phoenix.vault.a", "phoenix-service")["reader"]["revision"], 1)
        self.assertEqual(self.ledger.vault_source("phoenix.vault.a", "note.3", "phoenix-service")[1], b"edited vault")
        rows = list(self.ledger.graph.conn.execute(
            "MATCH (v:PhoenixVault {id:'phoenix.vault.a'}) RETURN v.source_epoch, v.generation_epoch"))
        self.assertEqual(rows, [[2, 1]])

    def test_other_actor_cannot_open_vault(self):
        self.post("/v1/vaults", {"vault_id": "phoenix.vault.b", "request_id": "create"})
        self.ledger.register_actor("other-service", "service", "phoenix",
                                   hashlib.sha256(b"other").hexdigest(), "other")
        response = self.client.get("/v1/vaults/phoenix.vault.b",
                                   headers={"Authorization": "Bearer other"},
                                   params={"actor_id": "other-service"})
        self.assertEqual(response.status_code, 404)
        foreign_asset = self.client.get("/v1/vaults/phoenix.vault.b/assets/sha256:" + "0" * 64,
            headers={"Authorization": "Bearer other"}, params={"actor_id": "other-service"})
        self.assertEqual(foreign_asset.status_code, 404)

    def test_large_asset_streams_past_json_limit(self):
        self.post("/v1/vaults", {"vault_id": "phoenix.vault.large", "request_id": "create"})
        content = b"s" * (17 * 1024 * 1024)
        response = self.client.post(
            "/v1/vaults/asset-stream", content=content,
            headers={**self.headers, "x-actor-id": "phoenix-service",
                     "x-vault-id": "phoenix.vault.large", "x-kind": "scene",
                     "x-request-id": "large-scene"})
        self.assertEqual(response.status_code, 200, response.text[:500])
        self.assertEqual(response.json()["byte_count"], len(content))
        self.assertEqual(self.ledger.cas.get(response.json()["artifact_id"]), content)

    def test_full_size_document_stream_and_replay(self):
        vault_id = "phoenix.fullsize"
        self.post("/v1/vaults", {"vault_id": vault_id, "request_id": "create-fullsize"})
        content = b"x" * (16 * 1024 * 1024)
        headers = {**self.headers, "x-actor-id": "phoenix-service",
                   "x-vault-id": vault_id, "x-source-id": "note.full",
                   "x-base-revision": "0", "x-request-id": "fullsize-source"}
        response = self.client.post("/v1/vaults/source-stream", content=content, headers=headers)
        self.assertEqual(response.status_code, 200, response.text[:500])
        receipt = response.json()["source"]
        self.assertEqual(receipt["byte_count"], len(content))
        retry = self.client.post("/v1/vaults/source-stream", content=content, headers=headers)
        self.assertEqual(retry.status_code, 200, retry.text[:500])
        self.assertEqual(retry.json()["source"], receipt)
        fetched = self.client.get(f"/v1/vaults/{vault_id}/sources/note.full/bytes",
            headers=self.headers, params={"actor_id": "phoenix-service"})
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.content, content)
        self.assertEqual(fetched.headers["x-source-revision"], "1")
        prior_head = self.ledger.journal.head
        too_large = self.client.post("/v1/vaults/source-stream", content=content + b"x",
            headers={**headers, "x-base-revision": "1", "x-request-id": "oversize"})
        self.assertEqual(too_large.status_code, 413)
        self.assertEqual(self.ledger.journal.head, prior_head)

    def test_portable_vault_reopens_on_another_library_and_rejects_tamper(self):
        vault_id = "phoenix.portable"
        self.post("/v1/vaults", {"vault_id": vault_id, "request_id": "create-portable"})
        self.post("/v1/vaults/source", {"vault_id": vault_id, "source_id": "note.1",
            "base_revision": 0, "content_base64": base64.b64encode(b"portable note").decode(),
            "request_id": "portable-source"})
        asset = self.post("/v1/vaults/asset", {"vault_id": vault_id, "kind": "graph",
            "content_base64": base64.b64encode(b"packed graph").decode(),
            "request_id": "portable-asset"})["artifact_id"]
        manifest = {"schema": "PHOENIX_VAULT_GENERATION_V1", "vault_id": vault_id,
                    "source_epoch": 1, "generation_id": 1, "asset_ids": [asset]}
        manifest_id = self.post("/v1/vaults/asset", {"vault_id": vault_id, "kind": "manifest",
            "content_base64": base64.b64encode(canonical(manifest)).decode(),
            "request_id": "portable-manifest"})["artifact_id"]
        self.post("/v1/vaults/generation", {"vault_id": vault_id, "source_epoch": 1,
            "generation_id": 1, "manifest_artifact_id": manifest_id,
            "asset_ids": [asset], "request_id": "portable-generation"})
        self.post("/v1/vaults/reader", {"vault_id": vault_id, "source_id": "note.1",
            "revision": 1, "offset": 4, "request_id": "portable-reader"})
        cutover_record = {"schema": "PHOENIX_VAULT_CUTOVER_V1", "vault_id": vault_id,
            "source_epoch": 1, "legacy_snapshot_id": "sha256:" + "1" * 64,
            "cold_open_root": "sha256:" + "2" * 64}
        cutover_id = self.post("/v1/vaults/asset", {"vault_id": vault_id,
            "kind": "cutover-receipt", "request_id": "portable-cutover-receipt",
            "content_base64": base64.b64encode(canonical(cutover_record)).decode()})["artifact_id"]
        cutover = {"vault_id": vault_id, "source_epoch": 1,
                   "receipt_artifact_id": cutover_id, "request_id": "portable-cutover"}
        self.post("/v1/vaults/product-primary", cutover)
        self.post("/v1/vaults/product-primary", cutover)
        self.assertEqual(self.ledger.vault_view(vault_id, "phoenix-service")
                         ["product_authority"]["mode"], "LIBRARY_PRIMARY")
        duplicate = self.client.post("/v1/vaults/product-primary", headers=self.headers,
            json={**cutover, "actor_id": "phoenix-service", "request_id": "duplicate-cutover"})
        self.assertEqual(duplicate.status_code, 400)
        package = self.root.parent / (self.root.name + "-export")
        root = self.ledger.vault_export(vault_id, "phoenix-service", package)
        try:
            transfer = self.client.get(f"/v1/vaults/{vault_id}/package", headers=self.headers,
                params={"actor_id": "phoenix-service"})
            self.assertEqual(transfer.status_code, 200, transfer.text[:300] if transfer.status_code != 200 else "")
            self.assertEqual(transfer.headers["x-vault-package-root"], root)
            with tempfile.TemporaryDirectory(prefix="kammi-vault-http-") as destination:
                fresh = Ledger(Path(destination))
                try:
                    fresh.register_actor("phoenix-service", "service", "phoenix",
                        hashlib.sha256(self.secret.encode()).hexdigest(), "actor")
                    with TestClient(create_app(fresh, "admin", acceptance_mode=True)) as receiver:
                        received = receiver.post("/v1/vaults/package", content=transfer.content,
                            headers={**self.headers, "x-actor-id": "phoenix-service",
                                     "x-package-root": root})
                        self.assertEqual(received.status_code, 200, received.text[:500])
                        self.assertEqual(received.json()["vault"]["reader"]["offset"], 4)
                        self.assertEqual(received.json()["vault"]["product_authority"]["mode"],
                                         "LIBRARY_PRIMARY")
                        retry = receiver.post("/v1/vaults/package", content=transfer.content,
                            headers={**self.headers, "x-actor-id": "phoenix-service",
                                     "x-package-root": root})
                        self.assertEqual(retry.status_code, 200, retry.text[:500])
                finally:
                    fresh.close()
            with tempfile.TemporaryDirectory(prefix="kammi-vault-destination-") as destination:
                fresh = Ledger(Path(destination))
                try:
                    fresh.register_actor("phoenix-service", "service", "phoenix",
                        hashlib.sha256(self.secret.encode()).hexdigest(), "actor")
                    opened = fresh.vault_import(package, "phoenix-service", root)
                    self.assertEqual(opened, self.ledger.vault_view(vault_id, "phoenix-service"))
                    self.assertEqual(fresh.vault_source(vault_id, "note.1", "phoenix-service")[1],
                                     b"portable note")
                    self.assertEqual(fresh.vault_asset(vault_id, asset, "phoenix-service")[0].read_bytes(),
                                     b"packed graph")
                finally:
                    fresh.close()
            object_file = package / "objects" / "sha256" / asset[7:9] / asset[9:]
            object_file.write_bytes(b"tampered")
            with tempfile.TemporaryDirectory(prefix="kammi-vault-reject-") as destination:
                fresh = Ledger(Path(destination))
                try:
                    fresh.register_actor("phoenix-service", "service", "phoenix",
                        hashlib.sha256(self.secret.encode()).hexdigest(), "actor")
                    with self.assertRaises(ValueError):
                        fresh.vault_import(package, "phoenix-service", root)
                    self.assertNotIn(vault_id, fresh.vaults.vaults)
                finally:
                    fresh.close()
        finally:
            shutil.rmtree(package)


if __name__ == "__main__":
    unittest.main()
