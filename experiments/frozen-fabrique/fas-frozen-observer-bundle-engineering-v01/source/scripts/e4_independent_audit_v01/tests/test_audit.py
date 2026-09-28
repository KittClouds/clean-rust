from __future__ import annotations

import hashlib
import ast
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from e4_independent_audit_v01.constants import (
    CONTRACT_ID, CONTRACT_SEAL_ID, CONTRACT_STAGE, ENDPOINT_ORDER, ENDPOINT_SPECS,
    E4_ROOT_KEYS, EXPECTED_PREDECESSORS, SEAL_SCHEMA, TASKS,
)
from e4_independent_audit_v01.integrity import (
    AuditError, canonical_seal_bytes, e4_root, validate_contract_seal, verify_e4_seal,
)
from e4_independent_audit_v01.replay import compare_scored_artifacts, reconstruct_qualification
from e4_independent_audit_v01.cli import _auth, resolve_workspace_root
from e4_independent_audit_v01.integrity import validate_source_map


ROOTS = {
    "e0_v10_root_sha256": "1" * 64,
    "e1_v04_root_sha256": "2" * 64,
    "e2_v07_root_sha256": "3" * 64,
    "e3_v02_bundle_root_sha256": "4" * 64,
}


def _truth_stratum(context_id: int, entity_id: int) -> str:
    return {
        (False, False): "IN_DOMAIN",
        (True, False): "CONTEXT_NOVEL",
        (False, True): "ENTITY_NOVEL",
        (True, True): "BOTH_NOVEL",
    }[(context_id >= 16, entity_id >= 16)]


def synthetic_scored_rows(*, bad_context: bool = False) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for q in range(32 * 32):
        context = q // 32
        entity = q % 32
        context_partner = (context // 16) * 16 + ((context % 16 + 7) % 16)
        entity_partner = (entity // 16) * 16 + ((entity % 16 + 7) % 16)
        relation = q % 2
        state = q % 3
        for position, variant in enumerate(("A", "C", "E", "P")):
            context_id = context_partner if variant == "C" else context
            entity_id = entity_partner if variant == "E" else entity
            target_position = state
            labels = {
                "context_term_id": context_id,
                "entity_term_id": entity_id,
                "relation_id": relation,
                "state_id": state,
                "exact_target": target_position,
                "target_candidate_identity": state,
                "candidate_identity_order": [0, 1, 2],
                "both_terms_train_side": context_id < 16 and entity_id < 16,
                "score_strata": _truth_stratum(context_id, entity_id),
            }
            predictions = {
                "context_identity": 0 if bad_context else context_id,
                "entity_identity": entity_id,
                "relation": relation,
                "observed_state": state,
                "exact_target": target_position,
            }
            row_index = q * 8 + position
            rows.append({
                "row_index": row_index,
                "row_id": f"q{q}:{position}",
                "quartet_id": f"q{q}",
                "variant_id": variant,
                "surface_id": "PRIMARY_SEEN",
                "truth_partition": "PRIMARY_TERMINAL",
                "labels": labels,
                "head_predictions": predictions,
            })
    return rows


def synthetic_seal(root: Path, *, stage: str, files: dict[str, tuple[str, bytes]], deferred=frozenset()) -> tuple[Path, dict[str, bytes]]:
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    contents: dict[str, bytes] = {}
    for artifact_id, (rel, payload) in files.items():
        contents[artifact_id] = payload
        path = root / Path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        if artifact_id not in deferred:
            path.write_bytes(payload)
        entries.append({
            "artifact_id": artifact_id,
            "path": rel.replace("\\", "/"),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    entries.sort(key=lambda item: item["artifact_id"].encode("utf-8"))
    manifest = {
        "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
        "status": "SEALED",
        "seal_id": "SYNTHETIC_SEAL",
        "stage": stage,
        "path_root_kind": "E4_RUN_ROOT",
        "created_utc": "2026-09-26T00:00:00Z",
        "contract_sha256": "a" * 64,
        "contract_seal_root_sha256": "b" * 64,
        "exact_predecessor_roots": ROOTS,
        "entries": entries,
        "entry_count": len(entries),
        "root_sha256": e4_root(entries),
    }
    seal_path = root / "stage-seal-v01.json"
    seal_path.write_bytes(canonical_seal_bytes(manifest))
    return seal_path, contents


class ReplayTests(unittest.TestCase):
    def test_synthetic_qualification_passes_and_bootstrap_reproduces(self) -> None:
        rows = synthetic_scored_rows()
        one, one_arrays = reconstruct_qualification(rows, replicates=64, seed=1234, chunk=16, alpha=0.05, minimum_rows_per_class=100, performance_floor=0.90)
        two, two_arrays = reconstruct_qualification(rows, replicates=64, seed=1234, chunk=16, alpha=0.05, minimum_rows_per_class=100, performance_floor=0.90)
        self.assertTrue(one["bundle_qualified"])
        self.assertEqual(one["terminal_disposition"], "PASS_SIMULTANEOUS_FRESH_BUNDLE_QUALIFICATION")
        self.assertEqual(tuple(one["endpoint_order"]), ENDPOINT_ORDER)
        self.assertEqual(set(one_arrays), {f"endpoint_{i:02d}__bootstrap_balanced_accuracy" for i in range(8)})
        for key in one_arrays:
            np.testing.assert_array_equal(one_arrays[key], two_arrays[key])
        self.assertEqual(one["endpoints"]["context_identity"]["bootstrap_lower_bound"], 1.0)

    def test_single_endpoint_failure_is_not_hidden_by_bundle(self) -> None:
        metrics, _ = reconstruct_qualification(
            synthetic_scored_rows(bad_context=True), replicates=32, seed=11, chunk=8,
            alpha=0.05, minimum_rows_per_class=100, performance_floor=0.90,
        )
        self.assertFalse(metrics["bundle_qualified"])
        self.assertEqual(metrics["failed_endpoints"], ["context_identity"])
        self.assertEqual(metrics["passed_endpoints"], list(ENDPOINT_ORDER[1:]))

    def test_support_failure_skips_endpoint_bootstrap(self) -> None:
        metrics, arrays = reconstruct_qualification(
            synthetic_scored_rows(), replicates=32, seed=11, chunk=8,
            alpha=0.05, minimum_rows_per_class=200, performance_floor=0.90,
        )
        context = metrics["endpoints"]["context_identity"]
        self.assertEqual(context["status"], "FAIL_SUPPORT")
        self.assertFalse(context["support_gate_pass"])
        self.assertEqual(arrays["endpoint_00__bootstrap_balanced_accuracy"].size, 0)

    def test_scorer_auditor_disagreement_is_rejected(self) -> None:
        metrics, arrays = reconstruct_qualification(
            synthetic_scored_rows(), replicates=32, seed=11, chunk=8,
            alpha=0.05, minimum_rows_per_class=100, performance_floor=0.90,
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            metrics_path = root / "metrics.json"
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
            archive_path = root / "bootstrap.npz"
            np.savez(archive_path, **arrays)
            compare_scored_artifacts(metrics, arrays, metrics_path, archive_path)
            altered = json.loads(metrics_path.read_text(encoding="utf-8"))
            altered["endpoints"]["context_identity"]["balanced_accuracy"] = 0.0
            metrics_path.write_text(json.dumps(altered), encoding="utf-8")
            with self.assertRaises(AuditError):
                compare_scored_artifacts(metrics, arrays, metrics_path, archive_path)
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
            broken = dict(arrays)
            first = next(iter(broken))
            broken[first] = broken[first].copy()
            broken[first][0] = 0.5
            np.savez(archive_path, **broken)
            with self.assertRaises(AuditError):
                compare_scored_artifacts(metrics, arrays, metrics_path, archive_path)


class IntegrityTests(unittest.TestCase):
    def test_contract_seal_uses_repository_root_relative_member_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
            contract_path = project / "contracts" / "e4-0-contract-v05-final.json"
            contract_path.parent.mkdir(parents=True)
            contract = {
                "contract_id": CONTRACT_ID,
                "status": "SEALED",
                "predecessors": EXPECTED_PREDECESSORS,
                "fresh_qualification": {"gate": {"endpoint_order": list(ENDPOINT_ORDER)}},
            }
            contract_bytes = (json.dumps(contract, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            contract_path.write_bytes(contract_bytes)
            entry = {
                "artifact_id": "E4_0_CONTRACT_V05_FINAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v05-final.json",
                "bytes": len(contract_bytes),
                "sha256": hashlib.sha256(contract_bytes).hexdigest(),
            }
            manifest = {
                "schema": SEAL_SCHEMA,
                "status": "SEALED",
                "seal_id": CONTRACT_SEAL_ID,
                "stage": CONTRACT_STAGE,
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": entry["sha256"],
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "entries": [entry],
                "entry_count": 1,
                "root_sha256": e4_root([entry]),
            }
            seal_path = project / "seals" / "e4-0-contract-v05-seal.json"
            seal_path.parent.mkdir()
            seal_path.write_bytes(canonical_seal_bytes(manifest))
            result = validate_contract_seal(workspace, contract_path, seal_path)
            self.assertEqual(result["status"], "PASS_CONTRACT_SEAL")

    def test_cli_workspace_root_walks_above_project_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repository"
            module = repo / "experiments" / "e4" / "source" / "scripts" / "auditor" / "cli.py"
            self.assertEqual(resolve_workspace_root(module), repo)

    def test_auditor_source_has_no_scorer_imports(self) -> None:
        package = Path(__file__).resolve().parents[1]
        forbidden = {"e4_fresh_scorer_v01", "score_e4_0_v01", "scorer"}
        imported: set[str] = set()
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
        self.assertTrue(forbidden.isdisjoint(imported), sorted(forbidden & imported))

    def test_cache_and_receipt_tamper_are_rejected(self) -> None:
        for artifact_id, relative in (("feature_cache", "features/cache.bin"), ("feature_receipt", "features/receipt.json")):
            with self.subTest(artifact_id=artifact_id), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                seal_path, _ = synthetic_seal(root, stage="FRESH_FEATURE_EXTRACTION", files={artifact_id: (relative, b"frozen bytes")})
                member = root / Path(relative)
                member.write_bytes(b"tampered bytes")
                with self.assertRaises(AuditError):
                    verify_e4_seal(
                        seal_path, root=root, expected_stage="FRESH_FEATURE_EXTRACTION",
                        contract_sha256="a" * 64, contract_seal_root_sha256="b" * 64,
                        expected_predecessors=ROOTS,
                    )

    def test_escrow_sentinel_is_never_opened_by_pre_score_seal_audit(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sentinel = root / "labels" / "escrow.jsonl"
            seal_path, _ = synthetic_seal(
                root,
                stage="POPULATION_GENERATION",
                files={"E4_TEMPLATE_JOINT_ESCROW_LABELS_V01": ("labels/escrow.jsonl", b"SENTINEL_MUST_NOT_BE_OPENED")},
                deferred={"E4_TEMPLATE_JOINT_ESCROW_LABELS_V01"},
            )
            original_open = Path.open

            def guarded_open(path: Path, *args, **kwargs):
                if path == sentinel:
                    raise AssertionError("escrow sentinel was opened")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", guarded_open):
                verified = verify_e4_seal(
                    seal_path, root=root, expected_stage="POPULATION_GENERATION",
                    contract_sha256="a" * 64, contract_seal_root_sha256="b" * 64,
                    expected_predecessors=ROOTS,
                    deferred_member_ids=frozenset({"E4_TEMPLATE_JOINT_ESCROW_LABELS_V01"}),
                )
            self.assertIn("E4_TEMPLATE_JOINT_ESCROW_LABELS_V01", verified.entries)

    def test_source_map_hash_and_path_are_checked(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source" / "audit.py"
            source.parent.mkdir()
            payload = b"independent audit source\n"
            source.write_bytes(payload)
            source_sha = hashlib.sha256(payload).hexdigest()
            source_map = root / "source-map.json"
            source_map.write_text(json.dumps({
                "implementation_units": [
                    "e4_population_generator",
                    "e4_online_feature_and_parity_runner",
                    "e4_fresh_scorer",
                    "e4_independent_auditor",
                ],
                "implementation_sources": [{
                    "path": "source/audit.py", "bytes": len(payload), "sha256": source_sha,
                }],
            }), encoding="utf-8")
            result = validate_source_map(root, source_map)
            self.assertEqual(result["status"], "PASS_SOURCE_MAP")
            self.assertEqual(result["checked_members"], 1)
            source_map.write_text(json.dumps({
                "implementation_units": [
                    "e4_population_generator",
                    "e4_online_feature_and_parity_runner",
                    "e4_fresh_scorer",
                    "e4_independent_auditor",
                ],
                "implementation_sources": [{
                    "path": "../outside.py", "bytes": len(payload), "sha256": source_sha,
                }],
            }), encoding="utf-8")
            with self.assertRaises(AuditError):
                validate_source_map(root, source_map)

    def test_markdown_source_map_accepts_exact_workspace_project_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            relative = "experiments/fas-frozen-observer-bundle-engineering-v01/source/audit.py"
            source = root.joinpath(*relative.split("/"))
            source.parent.mkdir(parents=True)
            payload = b"workspace-root bound source\n"
            source.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            source_map = root / "source-map-v04.md"
            source_map.write_text(
                "# E4-0 Implementation Source Map v04\n\n"
                "e4_population_generator e4_online_feature_and_parity_runner e4_fresh_scorer e4_independent_auditor\n\n"
                f"| Path | Bytes | SHA-256 | Role |\n| --- | ---: | --- | --- |\n"
                f"| `{relative}` | {len(payload)} | `{digest}` | Synthetic bound member. |\n",
                encoding="utf-8",
            )
            result = validate_source_map(root, source_map)
            self.assertEqual(result["status"], "PASS_SOURCE_MAP")
            self.assertEqual(result["checked_members"], 1)
            self.assertEqual(result["members"][0]["path"], relative)


class AuthorizationTests(unittest.TestCase):
    def _authorization(self, root: Path, stage: str) -> dict[str, object]:
        now = int(time.time())
        root_count = {
            "POPULATION_GENERATION": 4,
            "PARITY_PANEL_MATERIALIZATION": 6,
            "ONLINE_CACHE_PARITY": 7,
            "FRESH_FEATURE_EXTRACTION": 8,
            "FRESH_SCORING": 9,
        }[stage]
        roots = {key: EXPECTED_PREDECESSORS[key] for key in E4_ROOT_KEYS[:4]}
        for key in E4_ROOT_KEYS[4:root_count]:
            roots[key] = "5" * 64
        true_scope = {
            "POPULATION_GENERATION": {"population_generation"},
            "PARITY_PANEL_MATERIALIZATION": {"tokenizer_contact"},
            "ONLINE_CACHE_PARITY": {"model_contact", "feature_extraction"},
            "FRESH_FEATURE_EXTRACTION": {"model_contact", "feature_extraction"},
            "FRESH_SCORING": {"evaluation_label_opening", "scoring"},
        }[stage]
        scope = {key: key in true_scope for key in (
            "population_generation", "tokenizer_contact", "model_contact", "feature_extraction",
            "evaluation_label_opening", "scoring", "fitting", "e4_a",
            "heldout_template_label_opening", "joint_template_label_opening",
        )}
        value: dict[str, object] = {
            "schema": "FAS_E4_0_STAGE_AUTH_V01",
            "authorization_id": "synthetic",
            "status": "AUTHORIZED",
            "stage": stage,
            "contract_sha256": "a" * 64,
            "contract_seal_manifest_sha256": "b" * 64,
            "contract_seal_root_sha256": "c" * 64,
            "exact_predecessor_roots": roots,
            "output_root": str(root.resolve()),
            "scope": scope,
            "authorized_by": "ACTIVE_USER_REQUEST",
            "issued_utc_unix_seconds": now,
            "valid_from_utc_unix_seconds": now,
            "valid_until_utc_unix_seconds": now + 600,
        }
        if stage != "FRESH_SCORING":
            runtime_paths = {
                "model_snapshot": root / "models" / "model",
                "tokenizer_snapshot": root / "models" / "tokenizer",
                "model_asset_manifest": root / "manifests" / "model.json",
                "tokenizer_asset_manifest": root / "manifests" / "tokenizer.json",
            }
            value["paths"] = {name: str(path.resolve()) for name, path in runtime_paths.items()}
            value["gpu_lease"] = {
                "lock_path": str((root / "gpu" / "cuda0.lock").resolve()),
                "expected_reserved_ceiling_bytes": 10 * 1024**3,
                "quiet_window_seconds": 30,
                "poll_interval_seconds": 5,
            }
            value["gpu_lease_required_before_model_contact"] = stage in {
                "ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION",
            }
            contract_path = root / "contracts" / "e4-0-contract-v05-final.json"
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_payload = (json.dumps({
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V05",
                "status": "SEALED",
            }, indent=2) + "\n").encode("utf-8")
            contract_path.write_bytes(contract_payload)
            contract_sha = hashlib.sha256(contract_payload).hexdigest()
            seal_entry = {
                "artifact_id": "E4_0_CONTRACT_V05_FINAL",
                "path": "contracts/e4-0-contract-v05-final.json",
                "bytes": len(contract_payload),
                "sha256": contract_sha,
            }
            seal_root = e4_root([seal_entry])
            seal_path = root / "contract-seal.json"
            seal_payload = (json.dumps({
                "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
                "stage": "E4_0_CONTRACT",
                "root_sha256": seal_root,
                "entries": [seal_entry],
            }, indent=2) + "\n").encode("utf-8")
            seal_path.write_bytes(seal_payload)
            audit_path = root / "contract-audit.json"
            audit_payload = (json.dumps({
                "status": "PASS_CONTRACT_SEAL",
                "e4_0_contract_root_sha256": seal_root,
            }, indent=2) + "\n").encode("utf-8")
            audit_path.write_bytes(audit_payload)
            value["contract_sha256"] = contract_sha
            value["contract_seal_manifest_sha256"] = hashlib.sha256(seal_payload).hexdigest()
            value["contract_seal_root_sha256"] = seal_root
            value["artifacts"] = {
                "e4_contract": {"path": str(contract_path.resolve()), "bytes": len(contract_payload), "sha256": contract_sha},
                "e4_contract_seal_manifest": {"path": str(seal_path.resolve()), "bytes": len(seal_payload), "sha256": hashlib.sha256(seal_payload).hexdigest()},
                "e4_contract_audit": {"path": str(audit_path.resolve()), "bytes": len(audit_payload), "sha256": hashlib.sha256(audit_payload).hexdigest()},
            }
        return value

    def test_runtime_authorization_requires_artifact_map_and_exact_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth_path = root / "auth.json"
            value = self._authorization(root, "POPULATION_GENERATION")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            _auth(auth_path, "POPULATION_GENERATION", root)
            value["gpu_lease"]["quiet_window_seconds"] = 31
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                _auth(auth_path, "POPULATION_GENERATION", root)
            value = self._authorization(root, "POPULATION_GENERATION")
            value.pop("artifacts")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                _auth(auth_path, "POPULATION_GENERATION", root)
            value = self._authorization(root, "POPULATION_GENERATION")
            value["exact_predecessor_roots"] = {**EXPECTED_PREDECESSORS, "unexpected": "5" * 64}
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                _auth(auth_path, "POPULATION_GENERATION", root)

    def test_scoring_authorization_forbids_runtime_artifact_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth_path = root / "auth.json"
            value = self._authorization(root, "FRESH_SCORING")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            _auth(auth_path, "FRESH_SCORING", root)
            value["artifacts"] = {}
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                _auth(auth_path, "FRESH_SCORING", root)

    def test_all_non_scoring_runtime_stage_shapes(self) -> None:
        for stage in (
            "POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION",
            "ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION",
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                auth_path = root / "auth.json"
                auth_path.write_text(json.dumps(self._authorization(root, stage)), encoding="utf-8")
                _auth(auth_path, stage, root)


if __name__ == "__main__":
    unittest.main()
