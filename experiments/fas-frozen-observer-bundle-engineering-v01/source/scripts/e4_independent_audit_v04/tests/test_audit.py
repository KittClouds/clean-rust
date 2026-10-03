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

import e4_independent_audit_v04.integrity as integrity_module
import e4_independent_audit_v04.cli as cli_module
from e4_independent_audit_v04.constants import (
    CONTRACT_ID, CONTRACT_SEAL_ID, CONTRACT_STAGE, ENDPOINT_ORDER, ENDPOINT_SPECS,
    E4_ROOT_KEYS, EXPECTED_PREDECESSORS, INHERITED_V06_CONTRACT,
    INHERITED_V06_SEAL, SEAL_SCHEMA, TASKS,
)
from e4_independent_audit_v04.integrity import (
    AuditError, canonical_seal_bytes, e4_root, stage_contract_binding,
    validate_contract_seal, validate_inherited_v06_contract_seal,
    verify_e4_seal, verify_e4_stage_seal,
)
from e4_independent_audit_v04.replay import compare_scored_artifacts, reconstruct_qualification
from e4_independent_audit_v04.cli import (
    _auth,
    _validate_inherited_population_paths,
    resolve_workspace_root,
)
from e4_independent_audit_v04.integrity import validate_source_map


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
    def test_independent_replay_and_population_feature_logic_are_byte_identical_to_v03(self) -> None:
        current = Path(__file__).resolve().parents[1]
        prior = current.parent / "e4_independent_audit_v03"
        for name in ("replay.py", "population.py", "features.py"):
            with self.subTest(source=name):
                self.assertEqual((current / name).read_bytes(), (prior / name).read_bytes())

    def test_v06_population_paths_match_source_map_and_reject_stale_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp) / "workspace"
            project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
            run_root = Path(temp) / "runs" / "e4-0-v01"
            population_seal = run_root / "stage-seal-v01.json"
            population_audit = project / "audits" / "e4-0-execution" / "population-independent-audit-receipt-v01.json"

            self.assertIsNone(_validate_inherited_population_paths(
                run_root=run_root,
                workspace_root=workspace,
                population_seal_path=population_seal,
                population_audit_path=population_audit,
            ))
            with self.assertRaisesRegex(AuditError, "population seal path"):
                _validate_inherited_population_paths(
                    run_root=run_root,
                    workspace_root=workspace,
                    population_seal_path=run_root / "seals" / "e4-0-population-v01-seal.json",
                    population_audit_path=population_audit,
                )
            with self.assertRaisesRegex(AuditError, "population audit path"):
                _validate_inherited_population_paths(
                    run_root=run_root,
                    workspace_root=workspace,
                    population_seal_path=population_seal,
                    population_audit_path=project / "audits" / "e4-0-population-v01-independent-audit.json",
                )

    def test_v08_contract_seal_binds_v07_parent_and_retains_v06_science_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
            contracts = project / "contracts"
            seals = project / "seals"
            contracts.mkdir(parents=True)
            seals.mkdir(parents=True)

            v06_contract_path = contracts / "e4-0-contract-v06-final.json"
            v06_contract = {
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
                "status": "SEALED",
                "predecessors": EXPECTED_PREDECESSORS,
            }
            v06_contract_bytes = (json.dumps(v06_contract, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            v06_contract_path.write_bytes(v06_contract_bytes)
            v06_contract_sha = hashlib.sha256(v06_contract_bytes).hexdigest()
            v06_contract_member = {
                "artifact_id": "E4_0_CONTRACT_V06_FINAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json",
                "bytes": len(v06_contract_bytes),
                "sha256": v06_contract_sha,
            }
            v06_seal_path = seals / "e4-0-contract-v06-seal.json"
            v06_manifest = {
                "schema": SEAL_SCHEMA,
                "status": "SEALED",
                "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
                "stage": CONTRACT_STAGE,
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": v06_contract_sha,
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "entries": [v06_contract_member],
                "entry_count": 1,
                "root_sha256": e4_root([v06_contract_member]),
            }
            v06_seal_bytes = canonical_seal_bytes(v06_manifest)
            v06_seal_path.write_bytes(v06_seal_bytes)
            v06_seal_sha = hashlib.sha256(v06_seal_bytes).hexdigest()
            v06_lineage = {
                "contract": {
                    "contract_id": v06_contract["contract_id"],
                    "path": v06_contract_member["path"],
                    "bytes": len(v06_contract_bytes),
                    "sha256": v06_contract_sha,
                },
                "seal": {
                    "seal_id": v06_manifest["seal_id"],
                    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v06-seal.json",
                    "manifest_bytes": len(v06_seal_bytes),
                    "manifest_sha256": v06_seal_sha,
                    "root_sha256": v06_manifest["root_sha256"],
                    "contract_member_artifact_id": v06_contract_member["artifact_id"],
                },
            }
            v06_member_ids = {
                "contract_artifact_id": "E4_0_CONTRACT_V06_SUPERSEDED",
                "seal_artifact_id": "E4_0_CONTRACT_V06_SEAL_SUPERSEDED",
            }
            v07_contract_path = contracts / "e4-0-contract-v07-final.json"
            v07_contract = {
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V07",
                "status": "SEALED",
                "predecessors": EXPECTED_PREDECESSORS,
                "supersedes": v06_lineage,
            }
            v07_contract_bytes = (json.dumps(v07_contract, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            v07_contract_path.write_bytes(v07_contract_bytes)
            v07_contract_sha = hashlib.sha256(v07_contract_bytes).hexdigest()
            v07_contract_member = {
                "artifact_id": "E4_0_CONTRACT_V07_FINAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json",
                "bytes": len(v07_contract_bytes),
                "sha256": v07_contract_sha,
            }
            v06_contract_superseded = {**v06_contract_member, "artifact_id": v06_member_ids["contract_artifact_id"]}
            v06_seal_superseded = {
                "artifact_id": v06_member_ids["seal_artifact_id"],
                "path": v06_lineage["seal"]["path"],
                "bytes": len(v06_seal_bytes),
                "sha256": v06_seal_sha,
            }
            v07_entries = [v07_contract_member, v06_contract_superseded, v06_seal_superseded]
            v07_manifest = {
                "schema": SEAL_SCHEMA,
                "status": "SEALED",
                "seal_id": "FAS_E4_0_CONTRACT_V07_SEAL",
                "stage": CONTRACT_STAGE,
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": v07_contract_sha,
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "entries": sorted(v07_entries, key=lambda row: row["artifact_id"].encode("utf-8")),
                "entry_count": len(v07_entries),
                "root_sha256": e4_root(v07_entries),
            }
            v07_seal_path = seals / "e4-0-contract-v07-seal.json"
            v07_seal_bytes = canonical_seal_bytes(v07_manifest)
            v07_seal_path.write_bytes(v07_seal_bytes)
            v07_seal_sha = hashlib.sha256(v07_seal_bytes).hexdigest()
            v07_audit_path = project / "audits" / "e4-0-track-e" / "track-e-postseal-receipt-v07.json"
            v07_audit_payload = {
                "receipt_id": "FAS_E4_0_TRACK_E_V07_POSTSEAL_AUDIT_V01",
                "status": "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED",
                "final_seal": {"root_sha256": v07_manifest["root_sha256"]},
            }
            v07_audit_bytes = (json.dumps(v07_audit_payload, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            v07_audit_path.parent.mkdir(parents=True, exist_ok=True)
            v07_audit_path.write_bytes(v07_audit_bytes)
            v07_audit_identity = {
                "receipt_id": v07_audit_payload["receipt_id"],
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v07.json",
                "bytes": len(v07_audit_bytes),
                "sha256": hashlib.sha256(v07_audit_bytes).hexdigest(),
                "status": v07_audit_payload["status"],
                "root_sha256": v07_manifest["root_sha256"],
            }
            v07_lineage = {
                "contract": {
                    "contract_id": v07_contract["contract_id"],
                    "path": v07_contract_member["path"],
                    "bytes": len(v07_contract_bytes),
                    "sha256": v07_contract_sha,
                },
                "seal": {
                    "seal_id": v07_manifest["seal_id"],
                    "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json",
                    "manifest_bytes": len(v07_seal_bytes),
                    "manifest_sha256": v07_seal_sha,
                    "root_sha256": v07_manifest["root_sha256"],
                    "contract_member_artifact_id": v07_contract_member["artifact_id"],
                },
            }
            v07_member_ids = {
                "contract_artifact_id": "E4_0_CONTRACT_V07_SUPERSEDED",
                "seal_artifact_id": "E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
            }
            contract = {
                "contract_id": CONTRACT_ID,
                "status": "SEALED",
                "predecessors": EXPECTED_PREDECESSORS,
                "supersedes": v07_lineage,
                "engineering_amendment": {
                    "scientific_baseline": {
                        "contract_id": v06_lineage["contract"]["contract_id"],
                        "contract_sha256": v06_contract_sha,
                        "seal_root_sha256": v06_manifest["root_sha256"],
                        "contract_path": v06_lineage["contract"]["path"],
                        "contract_bytes": len(v06_contract_bytes),
                        "seal_id": v06_lineage["seal"]["seal_id"],
                        "seal_manifest_sha256": v06_seal_sha,
                        "seal_manifest_bytes": len(v06_seal_bytes),
                    },
                    "immediate_predecessor": {
                        "contract_id": v07_lineage["contract"]["contract_id"],
                        "contract_sha256": v07_contract_sha,
                        "contract_path": v07_lineage["contract"]["path"],
                        "contract_bytes": len(v07_contract_bytes),
                        "seal_id": v07_lineage["seal"]["seal_id"],
                        "manifest_sha256": v07_seal_sha,
                        "manifest_bytes": len(v07_seal_bytes),
                        "root_sha256": v07_manifest["root_sha256"],
                        "postseal_audit": {
                            key: v07_audit_identity[key]
                            for key in ("path", "bytes", "sha256", "status", "root_sha256")
                        },
                    },
                    "changed_scientific_fields": [],
                },
                "fresh_qualification": {"gate": {"endpoint_order": list(ENDPOINT_ORDER)}},
            }
            contract_path = contracts / "e4-0-contract-v08-final.json"
            contract_bytes = (json.dumps(contract, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            contract_path.write_bytes(contract_bytes)
            contract_sha = hashlib.sha256(contract_bytes).hexdigest()
            contract_entry = {
                "artifact_id": "E4_0_CONTRACT_V08_FINAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v08-final.json",
                "bytes": len(contract_bytes),
                "sha256": contract_sha,
            }
            v07_contract_superseded = {**v07_contract_member, "artifact_id": v07_member_ids["contract_artifact_id"]}
            v07_seal_superseded = {
                "artifact_id": v07_member_ids["seal_artifact_id"],
                "path": v07_lineage["seal"]["path"],
                "bytes": len(v07_seal_bytes),
                "sha256": v07_seal_sha,
            }
            entries = [contract_entry, v07_contract_superseded, v07_seal_superseded]
            manifest = {
                "schema": SEAL_SCHEMA,
                "status": "SEALED",
                "seal_id": CONTRACT_SEAL_ID,
                "stage": CONTRACT_STAGE,
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": contract_sha,
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "entries": sorted(entries, key=lambda row: row["artifact_id"].encode("utf-8")),
                "entry_count": len(entries),
                "root_sha256": e4_root(entries),
            }
            seal_path = seals / "e4-0-contract-v08-seal.json"
            seal_path.write_bytes(canonical_seal_bytes(manifest))

            previous_lineage = {
                "contract": v07_lineage["contract"],
                "seal": v07_lineage["seal"],
                "seal_members": v07_member_ids,
            }
            with (
                patch.object(integrity_module, "PREVIOUS_CONTRACT_LINEAGE", previous_lineage),
                patch.object(integrity_module, "INHERITED_V06_CONTRACT", v06_lineage["contract"]),
                patch.object(integrity_module, "INHERITED_V06_SEAL", v06_lineage["seal"]),
                patch.object(integrity_module, "INHERITED_V06_SEAL_MEMBERS", v06_member_ids),
                patch.object(integrity_module, "IMMEDIATE_V07_CONTRACT", v07_lineage["contract"]),
                patch.object(integrity_module, "IMMEDIATE_V07_SEAL", v07_lineage["seal"]),
                patch.object(integrity_module, "IMMEDIATE_V07_SEAL_MEMBERS", v07_member_ids),
                patch.object(integrity_module, "IMMEDIATE_V07_POSTSEAL_AUDIT", v07_audit_identity),
                patch.object(
                    integrity_module,
                    "IMMEDIATE_V07_AMENDMENT_AUDIT",
                    {
                        key: v07_audit_identity[key]
                        for key in ("path", "bytes", "sha256", "status", "root_sha256")
                    },
                ),
                patch.object(integrity_module, "V07_PREVIOUS_LINEAGE", v06_lineage),
            ):
                result = validate_contract_seal(workspace, contract_path, seal_path)
            self.assertEqual(result["status"], "PASS_CONTRACT_SEAL")
            self.assertEqual(result["contract_sha256"], contract_entry["sha256"])

            amendment_patches = (
                patch.object(integrity_module, "INHERITED_V06_CONTRACT", v06_lineage["contract"]),
                patch.object(integrity_module, "INHERITED_V06_SEAL", v06_lineage["seal"]),
                patch.object(integrity_module, "IMMEDIATE_V07_CONTRACT", v07_lineage["contract"]),
                patch.object(integrity_module, "IMMEDIATE_V07_SEAL", v07_lineage["seal"]),
                patch.object(integrity_module, "IMMEDIATE_V07_POSTSEAL_AUDIT", v07_audit_identity),
                patch.object(
                    integrity_module,
                    "IMMEDIATE_V07_AMENDMENT_AUDIT",
                    {
                        key: v07_audit_identity[key]
                        for key in ("path", "bytes", "sha256", "status", "root_sha256")
                    },
                ),
            )
            with amendment_patches[0], amendment_patches[1], amendment_patches[2], amendment_patches[3], amendment_patches[4], amendment_patches[5]:
                integrity_module._validate_v08_amendment(contract)
                altered = json.loads(json.dumps(contract))
                altered["engineering_amendment"]["scientific_baseline"]["seal_root_sha256"] = "0" * 64
                with self.assertRaises(AuditError):
                    integrity_module._validate_v08_amendment(altered)
                altered = json.loads(json.dumps(contract))
                altered["engineering_amendment"]["immediate_predecessor"]["contract_sha256"] = "f" * 64
                with self.assertRaises(AuditError):
                    integrity_module._validate_v08_amendment(altered)

            manifest["entries"] = [contract_entry]
            manifest["entry_count"] = 1
            manifest["root_sha256"] = e4_root([contract_entry])
            missing_lineage_path = seals / "v08-seal-without-lineage.json"
            missing_lineage_path.write_bytes(canonical_seal_bytes(manifest))
            with patch.object(integrity_module, "PREVIOUS_CONTRACT_LINEAGE", previous_lineage):
                with self.assertRaises(AuditError):
                    validate_contract_seal(workspace, contract_path, missing_lineage_path)

    def test_v06_population_and_panel_are_inherited_while_later_stages_require_v08(self) -> None:
        v08_contract_sha = "a" * 64
        v08_contract_root = "b" * 64
        inherited = {
            "POPULATION_GENERATION",
            "PARITY_PANEL_MATERIALIZATION",
        }
        new_stages = {
            "ONLINE_CACHE_PARITY",
            "FRESH_FEATURE_EXTRACTION",
            "FRESH_SCORING",
        }
        for stage in inherited | new_stages:
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                member_path = root / "artifacts" / "marker.bin"
                member_path.parent.mkdir(parents=True)
                payload = f"synthetic-{stage}".encode("ascii")
                member_path.write_bytes(payload)
                entry = {
                    "artifact_id": "synthetic_marker",
                    "path": "artifacts/marker.bin",
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                bound_sha, bound_root = stage_contract_binding(stage, v08_contract_sha, v08_contract_root)
                seal_path = root / "stage-seal.json"
                seal_path.write_bytes(canonical_seal_bytes({
                    "schema": SEAL_SCHEMA,
                    "status": "SEALED",
                    "seal_id": f"SYNTHETIC_{stage}",
                    "stage": stage,
                    "path_root_kind": "E4_RUN_ROOT",
                    "created_utc": "2026-09-26T00:00:00Z",
                    "contract_sha256": bound_sha,
                    "contract_seal_root_sha256": bound_root,
                    "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                    "entries": [entry],
                    "entry_count": 1,
                    "root_sha256": e4_root([entry]),
                }))
                verified = verify_e4_stage_seal(
                    seal_path,
                    root=root,
                    expected_stage=stage,
                    current_contract_sha256=v08_contract_sha,
                    current_contract_root_sha256=v08_contract_root,
                    expected_predecessors=EXPECTED_PREDECESSORS,
                )
                self.assertEqual(verified.value["contract_sha256"], bound_sha)
                if stage in inherited:
                    self.assertEqual(bound_sha, INHERITED_V06_CONTRACT["sha256"])
                    self.assertEqual(bound_root, INHERITED_V06_SEAL["root_sha256"])
                else:
                    self.assertEqual(bound_sha, v08_contract_sha)
                    self.assertEqual(bound_root, v08_contract_root)
                    with self.assertRaises(AuditError):
                        stage_contract_binding(stage, INHERITED_V06_CONTRACT["sha256"], INHERITED_V06_SEAL["root_sha256"])

    def test_inherited_v06_contract_seal_checks_exact_synthetic_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            workspace = Path(temp)
            project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
            contract_path = project / "contracts" / "e4-0-contract-v06-final.json"
            seal_path = project / "seals" / "e4-0-contract-v06-seal.json"
            contract_path.parent.mkdir(parents=True)
            seal_path.parent.mkdir(parents=True)
            contract_bytes = (json.dumps({
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
                "status": "SEALED",
                "predecessors": EXPECTED_PREDECESSORS,
            }, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
            contract_path.write_bytes(contract_bytes)
            contract_entry = {
                "artifact_id": "E4_0_CONTRACT_V06_FINAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v06-final.json",
                "bytes": len(contract_bytes),
                "sha256": hashlib.sha256(contract_bytes).hexdigest(),
            }
            manifest = {
                "schema": SEAL_SCHEMA,
                "status": "SEALED",
                "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
                "stage": CONTRACT_STAGE,
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": contract_entry["sha256"],
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "entries": [contract_entry],
                "entry_count": 1,
                "root_sha256": e4_root([contract_entry]),
            }
            seal_bytes = canonical_seal_bytes(manifest)
            seal_path.write_bytes(seal_bytes)
            fake_contract = {
                "contract_id": "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06",
                "path": contract_entry["path"],
                "bytes": len(contract_bytes),
                "sha256": contract_entry["sha256"],
            }
            fake_seal = {
                "seal_id": "FAS_E4_0_CONTRACT_V06_SEAL",
                "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v06-seal.json",
                "manifest_bytes": len(seal_bytes),
                "manifest_sha256": hashlib.sha256(seal_bytes).hexdigest(),
                "root_sha256": manifest["root_sha256"],
                "contract_member_artifact_id": "E4_0_CONTRACT_V06_FINAL",
            }
            with patch.object(integrity_module, "INHERITED_V06_CONTRACT", fake_contract), patch.object(
                integrity_module, "INHERITED_V06_SEAL", fake_seal
            ):
                result = validate_inherited_v06_contract_seal(workspace)
                self.assertEqual(result["status"], "PASS_INHERITED_V06_CONTRACT_SEAL")
                contract_path.write_bytes(contract_bytes + b" ")
                with self.assertRaises(AuditError):
                    validate_inherited_v06_contract_seal(workspace)

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
            prefix = "experiments/fas-frozen-observer-bundle-engineering-v01/"
            relative_paths = [
                prefix + "source/e4-population-v01/src/bin/e4-population-v01.rs",
                prefix + "source/scripts/e4_online_parity_v01.py",
                prefix + "source/scripts/e4_runner_common_v01.py",
                prefix + "source/scripts/e4_runner_modes_v01.py",
                prefix + "source/scripts/e4_runner_artifacts_v01.py",
                prefix + "source/scripts/e4_fresh_scorer_v04/runner.py",
                prefix + "source/scripts/e4_fresh_scorer_v04/scorer.py",
                prefix + "source/scripts/e4_fresh_scorer_v04/output_artifacts.py",
                prefix + "source/scripts/e4_independent_audit_v04/cli.py",
                prefix + "source/scripts/e4_independent_audit_v04/constants.py",
                prefix + "source/scripts/e4_independent_audit_v04/integrity.py",
                prefix + "source/scripts/e4_independent_audit_v04/population.py",
                prefix + "source/scripts/e4_independent_audit_v04/features.py",
                prefix + "source/scripts/e4_independent_audit_v04/replay.py",
            ]
            members = []
            for index, relative in enumerate(relative_paths):
                source = root.joinpath(*relative.split("/"))
                source.parent.mkdir(parents=True, exist_ok=True)
                payload = f"workspace-root bound fixture {index}\n".encode()
                source.write_bytes(payload)
                members.append((relative, len(payload), hashlib.sha256(payload).hexdigest()))
            source_map = root / "source-map-v04.md"
            source_map.write_text(
                "# E4-0 Implementation Source Map v04\n\n"
                f"| Path | Bytes | SHA-256 | Role |\n| --- | ---: | --- | --- |\n"
                + "".join(
                    f"| `{relative}` | {size} | `{digest}` | Different human-readable description. |\n"
                    for relative, size, digest in members
                ),
                encoding="utf-8",
            )
            result = validate_source_map(root, source_map)
            self.assertEqual(result["status"], "PASS_SOURCE_MAP")
            self.assertEqual(result["checked_members"], len(relative_paths))
            self.assertEqual(
                result["members"][0]["path"],
                relative_paths[0],
            )

            omitted_path = relative_paths[-1]
            source_map.write_text(
                "# E4-0 Implementation Source Map v04\n\n"
                "| Path | Bytes | SHA-256 | Role |\n| --- | ---: | --- | --- |\n"
                + "".join(
                    f"| `{relative}` | {size} | `{digest}` | Different human-readable description. |\n"
                    for relative, size, digest in members
                    if relative != omitted_path
                ),
                encoding="utf-8",
            )
            with self.assertRaises(AuditError):
                validate_source_map(root, source_map)


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
            inherited = stage in {"POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION"}
            contract_version = "v06" if inherited else "v08"
            contract_id = (
                "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06"
                if inherited else CONTRACT_ID
            )
            seal_id = "FAS_E4_0_CONTRACT_V06_SEAL" if inherited else CONTRACT_SEAL_ID
            member_id = "E4_0_CONTRACT_V06_FINAL" if inherited else "E4_0_CONTRACT_V08_FINAL"
            project_prefix = "experiments/fas-frozen-observer-bundle-engineering-v01"
            contract_rel = f"{project_prefix}/contracts/e4-0-contract-{contract_version}-final.json"
            contract_path = root.joinpath(*contract_rel.split("/"))
            contract_path.parent.mkdir(parents=True, exist_ok=True)
            contract_payload = (json.dumps({
                "contract_id": contract_id,
                "status": "SEALED",
            }, indent=2) + "\n").encode("utf-8")
            contract_path.write_bytes(contract_payload)
            contract_sha = hashlib.sha256(contract_payload).hexdigest()
            seal_entry = {
                "artifact_id": member_id,
                "path": contract_rel,
                "bytes": len(contract_payload),
                "sha256": contract_sha,
            }
            seal_root = e4_root([seal_entry])
            seal_rel = f"{project_prefix}/seals/e4-0-contract-{contract_version}-seal.json"
            seal_path = root.joinpath(*seal_rel.split("/"))
            seal_path.parent.mkdir(parents=True, exist_ok=True)
            seal_payload = (json.dumps({
                "schema": "FAS_E4_0_ARTIFACT_SEAL_V01",
                "status": "SEALED",
                "seal_id": seal_id,
                "stage": "E4_0_CONTRACT",
                "path_root_kind": "WORKSPACE_ROOT",
                "created_utc": "2026-09-26T00:00:00Z",
                "contract_sha256": contract_sha,
                "contract_seal_root_sha256": None,
                "exact_predecessor_roots": EXPECTED_PREDECESSORS,
                "root_sha256": seal_root,
                "entries": [seal_entry],
                "entry_count": 1,
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

    def _validate_auth(self, auth_path: Path, stage: str, root: Path) -> dict[str, object]:
        if stage in {"POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION"}:
            value = json.loads(auth_path.read_text(encoding="utf-8"))
            if "artifacts" not in value:
                return _auth(auth_path, stage, root)
            artifacts = value["artifacts"]
            contract = json.loads(Path(artifacts["e4_contract"]["path"]).read_text(encoding="utf-8"))
            seal = json.loads(Path(artifacts["e4_contract_seal_manifest"]["path"]).read_text(encoding="utf-8"))
            fake_contract = {
                "contract_id": contract["contract_id"],
                "path": artifacts["e4_contract"]["path"].replace(str(root.resolve()) + "\\", "").replace("\\", "/"),
                "bytes": artifacts["e4_contract"]["bytes"],
                "sha256": artifacts["e4_contract"]["sha256"],
            }
            fake_seal = {
                "seal_id": seal["seal_id"],
                "path": artifacts["e4_contract_seal_manifest"]["path"].replace(str(root.resolve()) + "\\", "").replace("\\", "/"),
                "manifest_bytes": artifacts["e4_contract_seal_manifest"]["bytes"],
                "manifest_sha256": artifacts["e4_contract_seal_manifest"]["sha256"],
                "root_sha256": seal["root_sha256"],
                "contract_member_artifact_id": "E4_0_CONTRACT_V06_FINAL",
            }
            with patch.object(cli_module, "INHERITED_V06_CONTRACT", fake_contract), patch.object(
                cli_module, "INHERITED_V06_SEAL", fake_seal
            ):
                return _auth(auth_path, stage, root)
        return _auth(auth_path, stage, root)

    def test_runtime_authorization_requires_artifact_map_and_exact_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth_path = root / "auth.json"
            value = self._authorization(root, "POPULATION_GENERATION")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            self._validate_auth(auth_path, "POPULATION_GENERATION", root)
            value["gpu_lease"]["quiet_window_seconds"] = 31
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                self._validate_auth(auth_path, "POPULATION_GENERATION", root)
            value = self._authorization(root, "POPULATION_GENERATION")
            value.pop("artifacts")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                self._validate_auth(auth_path, "POPULATION_GENERATION", root)
            value = self._authorization(root, "POPULATION_GENERATION")
            value["exact_predecessor_roots"] = {**EXPECTED_PREDECESSORS, "unexpected": "5" * 64}
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                self._validate_auth(auth_path, "POPULATION_GENERATION", root)

    def test_scoring_authorization_forbids_runtime_artifact_map(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            auth_path = root / "auth.json"
            value = self._authorization(root, "FRESH_SCORING")
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            self._validate_auth(auth_path, "FRESH_SCORING", root)
            value["artifacts"] = {}
            auth_path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(AuditError):
                self._validate_auth(auth_path, "FRESH_SCORING", root)

    def test_all_non_scoring_runtime_stage_shapes(self) -> None:
        for stage in (
            "POPULATION_GENERATION", "PARITY_PANEL_MATERIALIZATION",
            "ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION",
        ):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                auth_path = root / "auth.json"
                auth_path.write_text(json.dumps(self._authorization(root, stage)), encoding="utf-8")
                self._validate_auth(auth_path, stage, root)


if __name__ == "__main__":
    unittest.main()
