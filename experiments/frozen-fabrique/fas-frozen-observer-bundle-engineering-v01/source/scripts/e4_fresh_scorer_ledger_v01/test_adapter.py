from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import ledger_adapter as adapter


def jsonl(rows):
    return b"".join(json.dumps(row, separators=(",", ":")).encode() + b"\n" for row in rows)


def synthetic_rows():
    pairs, pred = [], {k: [] for k in (
        "context_identity", "entity_identity", "relation", "observed_state", "exact_target"
    )}
    strata = (("IN_DOMAIN", 0, 0), ("CONTEXT_NOVEL", 1, 0),
              ("ENTITY_NOVEL", 0, 1), ("BOTH_NOVEL", 1, 1))
    row_index = 0
    for si, (name, cn, en) in enumerate(strata):
        for qi in range(400):
            context, entity = 16 * cn + qi % 16, 16 * en + (qi * 7) % 16
            relation, state = (qi + si) % 2, qi % 3
            quartet = f"synthetic-{si:02d}-{qi:04d}"
            for vi, variant in enumerate(("A", "C", "E", "P")):
                target = (qi + vi) % 3
                order = [v for v in range(3) if v != state]
                order.insert(target, state)
                label = {
                    "row_id": f"{quartet}:{variant}", "quartet_id": quartet,
                    "variant_id": variant, "context_term_id": context,
                    "entity_term_id": entity, "relation_id": relation, "state_id": state,
                    "exact_target": target, "target_candidate_identity": state,
                    "candidate_identity_order": order, "score_strata": name,
                    "both_terms_train_side": context < 16 and entity < 16,
                }
                row = {
                    "row_index": row_index, "row_id": label["row_id"],
                    "quartet_id": quartet, "variant_id": variant,
                    "surface_id": "PRIMARY_SEEN", "truth_partition": "PRIMARY_TERMINAL",
                }
                pairs.append((row, label))
                for task, field in (
                    ("context_identity", "context_term_id"), ("entity_identity", "entity_term_id"),
                    ("relation", "relation_id"), ("observed_state", "state_id"),
                    ("exact_target", "exact_target"),
                ):
                    pred[task].append(label[field])
                row_index += 1
    return pairs, pred


def make_invocation(root, event):
    return {
        "schema": adapter.INVOCATION_SCHEMA, "status": "AUTHORIZED",
        "run_id": adapter.RUN_ID, "stage_id": adapter.STAGE_ID,
        "contract_sha256": adapter.CONTRACT_SHA256,
        "contract_seal_manifest_sha256": adapter.CONTRACT_SEAL_MANIFEST_SHA256,
        "contract_seal_root_sha256": adapter.CONTRACT_SEAL_ROOT_SHA256,
        "predecessor_roots": adapter.PREDECESSOR_ROOTS,
        "authority": {
            "authorization_id": "synthetic-grant",
            "grant_verification": "LEDGER_VERIFIED_BY_WORKER",
            "scope": adapter.EXPECTED_SCOPE,
        },
        "attempt_root": str(root), "exposure_event_id": event,
    }


def make_delivery(body, root, event, row_count):
    (root / "ledger-inputs").mkdir(parents=True, exist_ok=True)
    (root / adapter.PANEL_DELIVERY_RELATIVE_PATH).write_bytes(body)
    return {
        "schema": adapter.PANEL_DELIVERY_SCHEMA, "status": "MATERIALIZED",
        "run_id": adapter.RUN_ID, "stage_id": adapter.STAGE_ID, "purpose": "terminal",
        "artifact_id": adapter.PRIMARY_LABEL_ARTIFACT_ID, "panel_id": "synthetic-panel",
        "panel_id_resolves_to_artifact_id": adapter.PRIMARY_LABEL_ARTIFACT_ID,
        "source_population_root_sha256": adapter.POPULATION_ROOT_SHA256,
        "source_sha256": hashlib.sha256(body).hexdigest(), "source_bytes": len(body),
        "source_rows": row_count, "open_panel_event_count": 1,
        "escrow_panel_open_count": 0, "escrow_materialized": False,
        "exposure_event_id": event,
        "materialized_relative_path": adapter.PANEL_DELIVERY_RELATIVE_PATH,
    }


class CandidateAdapterTests(unittest.TestCase):
    def setUp(self):
        self.bound = (adapter.PRIMARY_LABEL_SOURCE_BYTES, adapter.PRIMARY_LABEL_SOURCE_SHA256,
                      adapter.PRIMARY_LABEL_ROWS)

    def tearDown(self):
        (adapter.PRIMARY_LABEL_SOURCE_BYTES, adapter.PRIMARY_LABEL_SOURCE_SHA256,
         adapter.PRIMARY_LABEL_ROWS) = self.bound

    def test_bound_science_source_and_gate_constants(self):
        math = adapter.load_frozen_math()
        self.assertEqual(math.BOOTSTRAP_REPLICATES, 10000)
        self.assertEqual(math.BOOTSTRAP_SEED, 2026092604)
        self.assertEqual(math.BOOTSTRAP_ALPHA, 0.00625)
        self.assertEqual(len(math.ENDPOINT_ORDER), 8)
        self.assertEqual(adapter.SCORING_RUNTIME, ("3.13.15", "2.5.3", "2.11.0+cu128"))
        self.assertFalse(hasattr(math, "OneShotPrimaryLabelReader"))

    def test_e3_head_assets_are_hash_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = {}
            for index, name in enumerate(("head-a.bin", "head-b.bin")):
                body = f"synthetic-e3-head-{index}".encode()
                (root / name).write_bytes(body)
                expected[name] = (hashlib.sha256(body).hexdigest(), len(body))
            original = adapter.E3_HEAD_FILES
            try:
                adapter.E3_HEAD_FILES = expected
                receipt = adapter.verify_e3_head_assets(root)
                self.assertEqual(set(receipt), set(expected))
                (root / "head-b.bin").write_bytes(b"tampered synthetic head")
                with self.assertRaises(RuntimeError):
                    adapter.verify_e3_head_assets(root)
            finally:
                adapter.E3_HEAD_FILES = original

    def test_prelabel_inference_requires_authorized_ledger_handoff(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inv = make_invocation(root, "event")
            inv["status"] = "NOT_AUTHORIZED"
            with self.assertRaises(RuntimeError):
                adapter.prepare_primary_predictions(
                    invocation=inv, feature_cache_path=root / "no-cache",
                    row_manifest_path=root / "no-manifest", e3_head_root=root / "no-heads",
                )
            self.assertFalse((root / "no-cache").exists())

    def test_one_primary_panel_materialization(self):
        body = jsonl([{"row_index": 0, "row_id": "synthetic-row"}])
        with tempfile.TemporaryDirectory() as temp:
            root, event = Path(temp), "synthetic-open-event"
            adapter.PRIMARY_LABEL_SOURCE_BYTES = len(body)
            adapter.PRIMARY_LABEL_SOURCE_SHA256 = hashlib.sha256(body).hexdigest()
            adapter.PRIMARY_LABEL_ROWS = 1
            result = adapter.OneShotLibraryPanelReader().read_once(
                make_invocation(root, event), make_delivery(body, root, event, 1)
            )
            self.assertEqual(len(result.rows), 1)
            self.assertEqual(result.receipt["ledger_open_panel_event_count"], 1)
            self.assertEqual(result.receipt["scorer_materialized_file_open_count"], 1)

    def test_panel_source_argument_must_match_staged_relative_path(self):
        body = jsonl([{"row_index": 0, "row_id": "synthetic-row"}])
        with tempfile.TemporaryDirectory() as temp:
            root, event = Path(temp), "synthetic-panel-path-event"
            adapter.PRIMARY_LABEL_SOURCE_BYTES = len(body)
            adapter.PRIMARY_LABEL_SOURCE_SHA256 = hashlib.sha256(body).hexdigest()
            adapter.PRIMARY_LABEL_ROWS = 1
            invocation = make_invocation(root, event)
            delivery = make_delivery(body, root, event, 1)
            reader = adapter.OneShotLibraryPanelReader()
            with tempfile.NamedTemporaryFile() as wrong_path:
                with self.assertRaises(RuntimeError):
                    reader.read_once(invocation, delivery, Path(wrong_path.name))
            self.assertEqual(reader.local_file_open_count, 0)

    def test_rejects_source_path_escrow_and_scope_widening(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inv = make_invocation(root, "event")
            source = make_delivery(b"", root, "event", 0)
            source["materialized_relative_path"] = "../e4-0-v01/labels/primary-terminal-labels-v01.jsonl"
            with self.assertRaises(RuntimeError):
                adapter.validate_panel_delivery(inv, source, root)
            escrow = make_delivery(b"", root, "event", 0)
            escrow["escrow_panel_open_count"] = 1
            with self.assertRaises(RuntimeError):
                adapter.validate_panel_delivery(inv, escrow, root)
            inv["authority"]["scope"] = {**adapter.EXPECTED_SCOPE, "heldout_template_label_opening": True}
            with self.assertRaises(RuntimeError):
                adapter.validate_invocation(inv)

    def test_no_truth_synthetic_end_to_end_qualification(self):
        pairs, predicted = synthetic_rows()
        manifest = [r for r, _ in pairs]
        labels = [y for _, y in pairs]
        body = jsonl(labels)
        predictions = {k: np.asarray(v, dtype=np.int64) for k, v in predicted.items()}
        with tempfile.TemporaryDirectory() as temp:
            root, event = Path(temp), "synthetic-open-event-e2e"
            adapter.PRIMARY_LABEL_SOURCE_BYTES = len(body)
            adapter.PRIMARY_LABEL_SOURCE_SHA256 = hashlib.sha256(body).hexdigest()
            adapter.PRIMARY_LABEL_ROWS = len(labels)
            metrics, receipt, joined = adapter.score_from_ledger_materialization(
                invocation=make_invocation(root, event),
                delivery=make_delivery(body, root, event, len(labels)),
                manifest=manifest, predictions=predictions,
                reader=adapter.OneShotLibraryPanelReader(),
            )
        self.assertEqual(len(labels), 6400)
        self.assertTrue(metrics["bundle_qualified"])
        self.assertEqual(metrics["terminal_disposition"], "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION")
        self.assertTrue(all(r["gate_pass"] for r in metrics["endpoints"].values()))
        self.assertEqual(receipt["ledger_open_panel_event_count"], 1)
        self.assertEqual(receipt["scorer_materialized_file_open_count"], 1)
        self.assertFalse(receipt["heldout_template_labels_opened"])
        self.assertFalse(receipt["joint_template_labels_opened"])
        self.assertEqual(len(joined), len(labels))


if __name__ == "__main__":
    unittest.main()
