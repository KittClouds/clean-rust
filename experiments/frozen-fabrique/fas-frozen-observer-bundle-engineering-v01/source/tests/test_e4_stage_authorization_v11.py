"""Synthetic, model-free tests for the immutable E4 stage-auth issuer."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue_e4_stage_authorization_v11 as issuer


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_file(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return path


def _generic_seal(stage: str, root: str) -> dict[str, object]:
    return {
        "schema": issuer.ARTIFACT_SEAL_SCHEMA,
        "status": "SEALED",
        "stage": stage,
        "root_sha256": root,
    }


def _seal_root(entries: list[dict[str, object]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: str(row["artifact_id"]).encode("utf-8")):
        digest.update(
            f'{entry["artifact_id"]}\t{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8")
        )
    return digest.hexdigest()


@contextmanager
def _patched_v06_reference(bindings: dict[str, object]):
    config = bindings["_test_reference_config"]
    with patch.multiple(issuer, **config):
        yield


def _build(stage: str, bindings: dict[str, object], now_unix_seconds: int | None = None) -> dict[str, object]:
    with _patched_v06_reference(bindings):
        return issuer.build_authorization(stage=stage, bindings=bindings, now_unix_seconds=now_unix_seconds)


def _refresh_contract_binding(bindings: dict[str, object], contract: dict[str, object]) -> None:
    artifacts = bindings["artifacts"]
    contract_path = Path(artifacts["e4_contract"])
    _json_file(contract_path, contract)
    payload = contract_path.read_bytes()
    entry = {
        "artifact_id": issuer.CONTRACT_MEMBER_ARTIFACT_ID,
        "path": issuer.CONTRACT_MEMBER_PATH,
        "bytes": len(payload),
        "sha256": _digest(payload),
    }
    _rewrite_contract_seal(bindings, [entry])


def _rewrite_contract_seal(
    bindings: dict[str, object],
    entries: list[dict[str, object]],
    overrides: dict[str, object] | None = None,
) -> None:
    artifacts = bindings["artifacts"]
    contract_path = Path(artifacts["e4_contract"])
    payload = contract_path.read_bytes()
    root = _seal_root(entries)
    seal: dict[str, object] = {
        "schema": issuer.ARTIFACT_SEAL_SCHEMA,
        "status": "SEALED",
        "seal_id": issuer.CONTRACT_SEAL_ID,
        "stage": "E4_0_CONTRACT",
        "path_root_kind": "WORKSPACE_ROOT",
        "created_utc": "2026-09-26T00:00:00+00:00",
        "contract_seal_root_sha256": None,
        "exact_predecessor_roots": dict(issuer.PREDECESSOR_ROOTS),
        "contract_sha256": _digest(payload),
        "root_sha256": root,
        "entry_count": len(entries),
        "entries": entries,
    }
    if overrides:
        seal.update(overrides)
    _json_file(Path(artifacts["e4_contract_seal_manifest"]), seal)
    _json_file(Path(artifacts["e4_contract_audit"]), {
        "status": "E4_0_TRACK_E_POSTSEAL_PASS_V07_SEAL_ROOT_AND_MEMBERS_RECOMPUTED",
        "pass": True,
        "e4_0_contract_root_sha256": root,
    })


def _fixture_bindings(root: Path, stage: str) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    paths_by_role: dict[str, Path] = {}
    root_values = dict(issuer.PREDECESSOR_ROOTS)
    for role in issuer.ARTIFACTS_BY_STAGE[stage]:
        path = root / "source-artifacts" / f"{role}.json"
        paths_by_role[role] = path

    contract_path = paths_by_role["e4_contract"]
    contract_value = {
        "contract_id": issuer.CONTRACT_ID,
        "status": "SEALED",
        "predecessors": {
            **issuer.PREDECESSOR_ROOTS,
            "e1_term_inventory_sha256": "43b793068ad759a7ec77bd0027e7113a0145a35b1daacb8ea1cefa551803c672",
            "e1_row_manifest_sha256": "ebfdf0064430ecae7a9ae2edd139f47c0c61291aa6c30c8ccb97daa195f835bc",
            "e1_split_manifest_sha256": "fb20dd79b5d02a46e7ac65f8a69b621c19f47b193db4e9c5f898778032464e70",
            "e1_fit_labels_sha256": "1c4223544ff8e164a393f6313db46dd814c50e3ea484a14ebdbed5070ebdfc15",
            "e1_model_inputs_sha256": "9f0076daa147bac37aa80d4f9a55f9225289910ceb8acc41998354c5a166917a",
            "e1_generator_source_sha256": "fa2bd0617135a0dce4e12f0e0967f82e461133b394a7d969daba5afb11e2cce1",
        },
        "supersedes": {
            "contract": {"contract_id": issuer.V10_CONTRACT_ID,
                          "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v10-final.json",
                          "bytes": issuer.V10_CONTRACT_BYTES, "sha256": issuer.V10_CONTRACT_SHA256},
            "seal": {"seal_id": "FAS_E4_0_CONTRACT_V10_SEAL",
                     "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v10-seal.json",
                     "manifest_bytes": issuer.V10_SEAL_BYTES, "manifest_sha256": issuer.V10_SEAL_SHA256,
                     "root_sha256": issuer.V10_SEAL_ROOT_SHA256,
                     "contract_member_artifact_id": "E4_0_CONTRACT_V10_FINAL"},
        },
        "engineering_amendment": {
            "scientific_baseline": {
                "contract_id": issuer.V06_CONTRACT_ID,
                "contract_sha256": issuer.V06_CONTRACT_SHA256,
                "seal_root_sha256": issuer.V06_CONTRACT_SEAL_ROOT_SHA256,
            },
            "immediate_predecessor": {
                "contract": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v10-final.json", "bytes": issuer.V10_CONTRACT_BYTES, "sha256": issuer.V10_CONTRACT_SHA256, "contract_id": issuer.V10_CONTRACT_ID},
                "source_map": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v09.md", "bytes": issuer.V10_MAP_BYTES, "sha256": issuer.V10_MAP_SHA256},
                "preseal_receipt": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v10.json", "bytes": issuer.V10_PRESEAL_BYTES, "sha256": issuer.V10_PRESEAL_SHA256, "status": "E4_0_TRACK_E_PRESEAL_PASS_V10_CONTRACT_AND_SOURCE_MAP_CLOSED"},
                "seal": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v10-seal.json", "bytes": issuer.V10_SEAL_BYTES, "sha256": issuer.V10_SEAL_SHA256, "seal_id": "FAS_E4_0_CONTRACT_V10_SEAL", "root_sha256": issuer.V10_SEAL_ROOT_SHA256},
            },
            "last_sealed_predecessor": {
                "contract": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v10-final.json", "bytes": issuer.V10_CONTRACT_BYTES, "sha256": issuer.V10_CONTRACT_SHA256, "contract_id": issuer.V10_CONTRACT_ID},
                "seal": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v10-seal.json", "bytes": issuer.V10_SEAL_BYTES, "sha256": issuer.V10_SEAL_SHA256, "seal_id": "FAS_E4_0_CONTRACT_V10_SEAL", "root_sha256": issuer.V10_SEAL_ROOT_SHA256},
            },
            "failed_v09_preseal_attempt": {
                "source_map": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/plans/E4-0-IMPLEMENTATION-SOURCE-MAP-v08.md", "bytes": issuer.V09_MAP_BYTES, "sha256": issuer.V09_MAP_SHA256},
                "contract": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v09-final.json", "bytes": issuer.V09_CONTRACT_BYTES, "sha256": issuer.V09_CONTRACT_SHA256},
                "preseal_receipt": {"path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-preseal-receipt-v09.json", "bytes": issuer.V09_PRESEAL_BYTES, "sha256": issuer.V09_PRESEAL_SHA256, "status": "E4_0_TRACK_E_PRESEAL_STOP_MISMATCHES_RECORDED_V09"},
                "pass": False, "final_seal": None,
                "population_truth_files_opened": False, "template_or_joint_truth_opened": False,
                "authorization_written": False, "tokenizer_contact": False, "model_contact": False,
                "cuda_initialized": False, "gpu_lease_acquired": False, "feature_cache_created": False, "labels_opened": False,
            },
            "failed_v10_postseal_attempts": [
                {
                    "receipt": {
                        "path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v10.json",
                        "bytes": issuer.V10_POSTSEAL_V01_BYTES,
                        "sha256": issuer.V10_POSTSEAL_V01_SHA256,
                        "status": "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10",
                    },
                    "issues": ["postseal mode requires a contract seal"],
                    "pass": False,
                    "final_seal": None,
                    "receipt_contact_fields": {
                        key: None for key in (
                            "authorization_written", "tokenizer_contact", "model_contact",
                            "cuda_initialized", "gpu_lease_acquired", "feature_cache_created",
                            "labels_opened",
                        )
                    },
                    **{key: False for key in (
                        "authorization_written", "tokenizer_contact", "model_contact",
                        "cuda_initialized", "gpu_lease_acquired", "feature_cache_created",
                        "labels_opened",
                    )},
                },
                {
                    "receipt": {
                        "path": "experiments/fas-frozen-observer-bundle-engineering-v01/audits/e4-0-track-e/track-e-postseal-receipt-v10-v02.json",
                        "bytes": issuer.V10_POSTSEAL_V02_BYTES,
                        "sha256": issuer.V10_POSTSEAL_V02_SHA256,
                        "status": "E4_0_TRACK_E_POSTSEAL_STOP_MISMATCHES_RECORDED_V10",
                    },
                    "issues": [
                        "v10 seal omits required member paths: ['experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json', 'experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json']",
                        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SUPERSEDED",
                        "v10 seal lacks exact scientific-baseline/immediate-predecessor member: E4_0_CONTRACT_V07_SEAL_SUPERSEDED",
                    ],
                    "pass": False,
                    "final_seal": {
                        "root_sha256": issuer.V10_SEAL_ROOT_SHA256,
                        "root_match": True,
                        "member_set_exact": False,
                        "entry_count": 221,
                        "expected_member_count": 223,
                    },
                    "receipt_contact_fields": {
                        key: None for key in (
                            "authorization_written", "tokenizer_contact", "model_contact",
                            "cuda_initialized", "gpu_lease_acquired", "feature_cache_created",
                            "labels_opened",
                        )
                    },
                    **{key: False for key in (
                        "authorization_written", "tokenizer_contact", "model_contact",
                        "cuda_initialized", "gpu_lease_acquired", "feature_cache_created",
                        "labels_opened",
                    )},
                },
            ],
            "transitive_seal_members": [
                {"artifact_id": "E4_0_CONTRACT_V07_SUPERSEDED", "path": "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v07-final.json", "bytes": 48881, "sha256": issuer.V07_CONTRACT_SHA256},
                {"artifact_id": "E4_0_CONTRACT_V07_SEAL_SUPERSEDED", "path": "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v07-seal.json", "bytes": 52723, "sha256": issuer.V07_CONTRACT_SEAL_MANIFEST_SHA256},
            ],
            "amendment_kind": "VERSIONED_TRANSITIVE_SEAL_MEMBER_INVENTORY_REPAIR",
            "scope": "The v11 update preserves the v06 scientific object and all v10/v09/v08 lineage. It corrects only the v10 contract sealer's transitive member inventory by adding the exact v07 superseded contract and seal entries identified by the independent v10 postseal audit. No scientific field or execution boundary changes; no E4 stage authorization is granted.",
        },
    }
    _json_file(contract_path, contract_value)
    contract_artifacts = {
        "e4_contract": contract_path,
        "e4_contract_seal_manifest": paths_by_role["e4_contract_seal_manifest"],
        "e4_contract_audit": paths_by_role["e4_contract_audit"],
    }
    _refresh_contract_binding({"artifacts": contract_artifacts}, contract_value)

    historical_audit_fields = {
        "e0_audit": ("E0_V10_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED", "seal_root_sha256", issuer.PREDECESSOR_ROOTS["e0_v10_root_sha256"]),
        "e1_audit": ("PASS", "e1_root_sha256", issuer.PREDECESSOR_ROOTS["e1_v04_root_sha256"]),
        "e2_audit": ("E2_V07_INDEPENDENT_AUDIT_PASS_E3_NOT_AUTHORIZED_BY_E0_FREEZE", "e2_root_sha256", issuer.PREDECESSOR_ROOTS["e2_v07_root_sha256"]),
        "e3_audit": ("E3_V02_FIVE_FITS_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED", "e3_root_sha256", issuer.PREDECESSOR_ROOTS["e3_v02_bundle_root_sha256"]),
    }
    historical_seal_roles = {
        "e0_seal": "e0_v10_root_sha256",
        "e1_seal": "e1_v04_root_sha256",
        "e2_seal": "e2_v07_root_sha256",
        "e3_seal": "e3_v02_bundle_root_sha256",
    }
    for role, root_key in historical_seal_roles.items():
        _json_file(paths_by_role[role], {"root_sha256": issuer.PREDECESSOR_ROOTS[root_key]})
    for role, (status, root_key, value) in historical_audit_fields.items():
        _json_file(paths_by_role[role], {"status": status, root_key: value, "all_checks_passed": True})

    if "population_seal" in paths_by_role:
        population_root = "b" * 64
        root_values["e4_population_root_sha256"] = population_root
        _json_file(paths_by_role["population_seal"], _generic_seal("POPULATION_GENERATION", population_root))
        audit_path = paths_by_role["population_audit"]
        _json_file(audit_path, {
            "status": "PASS_POPULATION_FRESHNESS_SUPPORT",
            "population_root_sha256": population_root,
            "all_checks_passed": True,
            "population_truth_files_opened": False,
            "primary_support": {"heldout_or_joint_support_read": False},
        })

    if "parity_panel_seal" in paths_by_role:
        root_values["e4_parity_panel_root_sha256"] = "c" * 64
        _json_file(paths_by_role["parity_panel_seal"], _generic_seal("PARITY_PANEL_MATERIALIZATION", "c" * 64))

    if "parity_receipt_seal" in paths_by_role:
        root_values["e4_parity_receipt_root_sha256"] = "d" * 64
        receipt_path = root / "parity" / "parity-receipt-v01.json"
        _json_file(receipt_path, {"status": "ONLINE_CACHE_PARITY_PASS"})
        receipt_bytes = receipt_path.read_bytes()
        _json_file(paths_by_role["parity_receipt_seal"], {
            **_generic_seal("ONLINE_CACHE_PARITY", "d" * 64),
            "entries": [{
                "artifact_id": "parity_receipt",
                "path": "parity/parity-receipt-v01.json",
                "bytes": len(receipt_bytes),
                "sha256": _digest(receipt_bytes),
            }],
        })

    if "feature_cache_seal" in paths_by_role:
        root_values["e4_feature_cache_root_sha256"] = "e" * 64
        feature_path = root / "features" / "feature-extraction-receipt-v01.json"
        _json_file(feature_path, {"status": "FEATURE_CACHE_COMPLETE_GATE_PASS"})
        feature_bytes = feature_path.read_bytes()
        _json_file(paths_by_role["feature_cache_seal"], {
            **_generic_seal("FRESH_FEATURE_EXTRACTION", "e" * 64),
            "entries": [{
                "artifact_id": "feature_extraction_receipt",
                "path": "features/feature-extraction-receipt-v01.json",
                "bytes": len(feature_bytes),
                "sha256": _digest(feature_bytes),
            }],
        })

    # Populate all otherwise-unused declared binding roles with deterministic
    # inert files. The artifact map hashes them but no runtime is loaded.
    for role, path in paths_by_role.items():
        if not path.exists():
            _json_file(path, {"synthetic_role": role, "model_contact": False})

    model_dir = root / "models" / "model"
    tokenizer_dir = root / "models" / "tokenizer"
    model_dir.mkdir(parents=True, exist_ok=True)
    tokenizer_dir.mkdir(parents=True, exist_ok=True)
    path_map = {
        "model_snapshot": str(model_dir.resolve()),
        "tokenizer_snapshot": str(tokenizer_dir.resolve()),
        "model_asset_manifest": str(paths_by_role["model_manifest"].resolve()),
        "tokenizer_asset_manifest": str(paths_by_role["tokenizer_manifest"].resolve()),
    }
    # Replace the generic manifest fixtures with valid JSON metadata objects.
    _json_file(paths_by_role["model_manifest"], {"resolved_revision": "synthetic", "model_contact": False})
    _json_file(paths_by_role["tokenizer_manifest"], {"resolved_commit": "synthetic", "loaded_snapshot_files": []})

    # The v08 issuer treats the preserved v06 authorization as a read-only
    # identity index for the sealed population/panel inputs. Synthetic seals
    # exercise the same byte-and-root checks without accessing truth rows.
    reference_root = root / "v06-reference"
    reference_root.mkdir(parents=True, exist_ok=True)
    population_seal_path = paths_by_role.get("population_seal", reference_root / "population-seal.json")
    population_audit_path = paths_by_role.get("population_audit", reference_root / "population-audit.json")
    panel_seal_path = paths_by_role.get("parity_panel_seal", reference_root / "parity-panel-seal.json")
    population_root = "b" * 64
    panel_root = "c" * 64
    if not population_seal_path.exists():
        _json_file(population_seal_path, _generic_seal("POPULATION_GENERATION", population_root))
    if not population_audit_path.exists():
        _json_file(population_audit_path, {
            "status": "PASS_POPULATION_FRESHNESS_SUPPORT",
            "population_root_sha256": population_root,
            "all_checks_passed": True,
            "population_truth_files_opened": False,
            "heldout_or_joint_support_read": False,
        })
    if not panel_seal_path.exists():
        _json_file(panel_seal_path, _generic_seal("PARITY_PANEL_MATERIALIZATION", panel_root))
    pop_identity = issuer.artifact_identity(population_seal_path)
    audit_identity = issuer.artifact_identity(population_audit_path)
    panel_identity = issuer.artifact_identity(panel_seal_path)
    v06_contract_path = issuer.EXPERIMENT_ROOT / "contracts" / "e4-0-contract-v06-final.json"
    v06_contract_seal_path = issuer.EXPERIMENT_ROOT / "seals" / "e4-0-contract-v06-seal.json"
    v06_contract_identity = issuer.artifact_identity(v06_contract_path)
    v06_contract_seal_identity = issuer.artifact_identity(v06_contract_seal_path)
    reference = {
        "schema": issuer.SCHEMA,
        "authorization_id": issuer.AUTHORIZATION_ID,
        "status": "AUTHORIZED",
        "stage": "ONLINE_CACHE_PARITY",
        "contract_sha256": issuer.V06_CONTRACT_SHA256,
        "contract_seal_manifest_sha256": issuer.V06_CONTRACT_SEAL_MANIFEST_SHA256,
        "contract_seal_root_sha256": issuer.V06_CONTRACT_SEAL_ROOT_SHA256,
        "exact_predecessor_roots": {
            **issuer.PREDECESSOR_ROOTS,
            "e4_population_root_sha256": population_root,
            "e4_population_audit_root_sha256": audit_identity["sha256"],
            "e4_parity_panel_root_sha256": panel_root,
        },
        "artifacts": {
            "e4_contract": v06_contract_identity,
            "e4_contract_seal_manifest": v06_contract_seal_identity,
            "population_seal": pop_identity,
            "population_audit": audit_identity,
            "parity_panel_seal": panel_identity,
        },
    }
    ref_path = _json_file(reference_root / "online-parity-authorization-v01.json", reference)
    operation_path = _json_file(reference_root / "population-seal-operation-v01.json", {
        "status": "POPULATION_STAGE_SEALED",
        "stage_seal_root_sha256": population_root,
        "truth_handling": "label and escrow files were included by byte length and SHA-256 only",
    })
    reference_config = {
        "V06_REFERENCE_AUTHORIZATION_PATH": ref_path,
        "V06_REFERENCE_AUTHORIZATION_SHA256": _digest(ref_path.read_bytes()),
        "V06_REFERENCE_AUTHORIZATION_BYTES": len(ref_path.read_bytes()),
        "V06_INHERITED_ROOTS": {
            "e4_population_root_sha256": population_root,
            "e4_population_audit_root_sha256": audit_identity["sha256"],
            "e4_parity_panel_root_sha256": panel_root,
        },
        "V06_INHERITED_ARTIFACT_IDENTITIES": {
            "population_seal": (pop_identity["sha256"], pop_identity["bytes"]),
            "population_audit": (audit_identity["sha256"], audit_identity["bytes"]),
            "parity_panel_seal": (panel_identity["sha256"], panel_identity["bytes"]),
        },
        "V06_POPULATION_OPERATION_RECEIPT_PATH": operation_path,
        "V06_POPULATION_OPERATION_RECEIPT_SHA256": _digest(operation_path.read_bytes()),
        "V06_POPULATION_OPERATION_RECEIPT_BYTES": len(operation_path.read_bytes()),
    }

    bindings: dict[str, object] = {
        "output_root": str((root / "e4-run").resolve()),
        "valid_for_seconds": 600,
        "artifacts": {role: str(path.resolve()) for role, path in paths_by_role.items()},
        "paths": path_map,
        "gpu_lease": {"lock_path": str((root / "locks" / "cuda0-exclusive.json").resolve())},
        "_test_reference_config": reference_config,
    }
    return bindings


class AuthorizationIssuerTests(unittest.TestCase):
    def test_actual_nested_population_audit_schema_is_accepted(self) -> None:
        audit = {
            "status": "PASS_POPULATION_FRESHNESS_SUPPORT",
            "population_root_sha256": "b" * 64,
            "all_checks_passed": True,
            "population_truth_files_opened": False,
            "primary_support": {
                "construction_minimum_rows_per_class": 252,
                "scoring_minimum_rows_per_class": 200,
                "primary_support_cells": 81,
                "heldout_or_joint_support_read": False,
            },
        }
        self.assertTrue(issuer._population_audit_truth_closed_pass(audit, "b" * 64))

    def test_population_audit_normalization_fails_closed(self) -> None:
        base = {
            "status": "PASS_POPULATION_FRESHNESS_SUPPORT",
            "population_root_sha256": "b" * 64,
            "all_checks_passed": True,
            "population_truth_files_opened": False,
            "primary_support": {"heldout_or_joint_support_read": False},
        }
        mutations = (
            {"primary_support": {"heldout_or_joint_support_read": True}},
            {"primary_support": {}},
            {"primary_support": None, "heldout_or_joint_support_read": True},
            {"population_truth_files_opened": True},
            {"all_checks_passed": False},
            {"population_root_sha256": "c" * 64},
            {"status": "FAIL_POPULATION_FRESHNESS_SUPPORT"},
            {
                "primary_support": {"heldout_or_joint_support_read": False},
                "heldout_or_joint_support_read": True,
            },
        )
        for mutation in mutations:
            candidate = {**base, **mutation}
            with self.subTest(mutation=mutation):
                self.assertFalse(issuer._population_audit_truth_closed_pass(candidate, "b" * 64))

    def test_nested_population_audit_drives_parity_authorization_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bindings = _fixture_bindings(Path(temp), "ONLINE_CACHE_PARITY")
            authorization = _build("ONLINE_CACHE_PARITY", bindings, now_unix_seconds=7)
            self.assertEqual(
                authorization["exact_predecessor_roots"]["e4_population_audit_root_sha256"],
                bindings["_test_reference_config"]["V06_INHERITED_ROOTS"]["e4_population_audit_root_sha256"],
            )

    def test_e1_identity_extensions_are_allowed_with_four_frozen_roots_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root / "extended", "POPULATION_GENERATION")
            contract_path = Path(bindings["artifacts"]["e4_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            self.assertGreater(len(contract["predecessors"]), len(issuer.PREDECESSOR_ROOTS))
            authorization = _build("POPULATION_GENERATION", bindings, now_unix_seconds=1)
            self.assertEqual(
                {key: contract["predecessors"][key] for key in issuer.PREDECESSOR_ROOTS},
                issuer.PREDECESSOR_ROOTS,
            )
            self.assertEqual(authorization["stage"], "POPULATION_GENERATION")

            contract["predecessors"].pop("e1_v04_root_sha256")
            _refresh_contract_binding(bindings, contract)
            with self.assertRaisesRegex(issuer.AuthorizationError, "required E0/E1/E2/E3 predecessor roots"):
                _build("POPULATION_GENERATION", bindings)

    def test_v11_amendment_preserves_v06_baseline_v10_parent_and_v09_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root / "baseline", "POPULATION_GENERATION")
            contract_path = Path(bindings["artifacts"]["e4_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["engineering_amendment"]["scientific_baseline"]["contract_sha256"] = "0" * 64
            _refresh_contract_binding(bindings, contract)
            with self.assertRaisesRegex(issuer.AuthorizationError, "exact immutable v06 scientific baseline"):
                _build("POPULATION_GENERATION", bindings)

            bindings = _fixture_bindings(root / "parent", "POPULATION_GENERATION")
            contract_path = Path(bindings["artifacts"]["e4_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["engineering_amendment"]["last_sealed_predecessor"]["seal"]["root_sha256"] = "0" * 64
            _refresh_contract_binding(bindings, contract)
            with self.assertRaisesRegex(issuer.AuthorizationError, "exact sealed v10 predecessor"):
                _build("POPULATION_GENERATION", bindings)

            bindings = _fixture_bindings(root / "failed-v09", "POPULATION_GENERATION")
            contract_path = Path(bindings["artifacts"]["e4_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["engineering_amendment"]["failed_v09_preseal_attempt"]["final_seal"] = "invented"
            _refresh_contract_binding(bindings, contract)
            with self.assertRaisesRegex(issuer.AuthorizationError, "failed v09 no-contact preseal stop"):
                _build("POPULATION_GENERATION", bindings)

    def test_all_runtime_stages_match_track_d_exact_fields_roots_and_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stage in (
                "POPULATION_GENERATION",
                "ONLINE_CACHE_PARITY",
                "FRESH_FEATURE_EXTRACTION",
            ):
                bindings = _fixture_bindings(root / stage, stage)
                authorization = _build(stage, bindings)
                self.assertEqual(authorization["stage"], stage)
                self.assertEqual(set(authorization), {
                    "schema", "authorization_id", "status", "stage", "contract_sha256",
                    "contract_seal_manifest_sha256", "contract_seal_root_sha256",
                    "exact_predecessor_roots", "output_root", "scope", "authorized_by",
                    "issued_utc_unix_seconds", "valid_from_utc_unix_seconds",
                    "valid_until_utc_unix_seconds", "artifacts", "paths", "gpu_lease",
                    "gpu_lease_required_before_model_contact",
                })
                self.assertEqual(authorization["gpu_lease_required_before_model_contact"], stage in {
                    "ONLINE_CACHE_PARITY", "FRESH_FEATURE_EXTRACTION",
                })
                self.assertEqual(authorization["gpu_lease"], {
                    "lock_path": str((Path(bindings["gpu_lease"]["lock_path"])).resolve()),
                    "expected_reserved_ceiling_bytes": 10 * 1024**3,
                    "quiet_window_seconds": 30,
                    "poll_interval_seconds": 5,
                })
                expected_scope = issuer.TRUE_SCOPES[stage]
                self.assertEqual(
                    {name for name, enabled in authorization["scope"].items() if enabled},
                    expected_scope,
                )
                expected_count = 4 + (0 if stage == "POPULATION_GENERATION" else {
                    "ONLINE_CACHE_PARITY": 3,
                    "FRESH_FEATURE_EXTRACTION": 4,
                }[stage])
                self.assertEqual(len(authorization["exact_predecessor_roots"]), expected_count)
                self.assertFalse(authorization["scope"]["heldout_template_label_opening"])
                self.assertFalse(authorization["scope"]["joint_template_label_opening"])

    def test_sealed_v06_panel_cannot_be_materialized_as_v08_stage(self) -> None:
        with self.assertRaisesRegex(issuer.AuthorizationError, "unsupported E4 stage"):
            issuer.build_authorization(stage="PARITY_PANEL_MATERIALIZATION", bindings={})

    def test_fresh_scoring_preserves_scorer_exact_fourteen_fields(self) -> None:
        from e4_fresh_scorer_v02 import scorer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "FRESH_SCORING")
            authorization = _build("FRESH_SCORING", bindings, now_unix_seconds=2000)
            self.assertEqual(set(authorization), scorer.AUTH_FIELDS)
            self.assertNotIn("artifacts", authorization)
            self.assertEqual(len(authorization["exact_predecessor_roots"]), 9)
            expected = scorer.ScoringAuthIdentity(
                contract_sha256=authorization["contract_sha256"],
                contract_seal_manifest_sha256=authorization["contract_seal_manifest_sha256"],
                contract_seal_root_sha256=authorization["contract_seal_root_sha256"],
                exact_predecessor_roots=authorization["exact_predecessor_roots"],
                output_root=authorization["output_root"],
            )
            scorer.validate_scoring_authorization(authorization, expected, now_unix_seconds=2000)

    def test_contract_audit_and_stage_seal_identity_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "POPULATION_GENERATION")
            bad_path = Path(bindings["artifacts"]["e4_contract_audit"])
            _json_file(bad_path, {"status": "FAIL", "e4_0_contract_root_sha256": "a" * 64})
            with self.assertRaises(issuer.AuthorizationError):
                _build("POPULATION_GENERATION", bindings, now_unix_seconds=1)

    def test_postseal_audit_nested_final_seal_root_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bindings = _fixture_bindings(Path(temp), "POPULATION_GENERATION")
            artifacts = bindings["artifacts"]
            seal_path = Path(artifacts["e4_contract_seal_manifest"])
            root = json.loads(seal_path.read_text(encoding="utf-8"))["root_sha256"]
            _json_file(Path(artifacts["e4_contract_audit"]), {
                "status": "E4_0_TRACK_E_POSTSEAL_PASS_V08_SEAL_ROOT_AND_MEMBERS_RECOMPUTED",
                "pass": True,
                "final_seal": {"root_sha256": root},
            })
            artifact_rows = {
                role: issuer.artifact_identity(path)
                for role, path in artifacts.items()
                if role in {"e4_contract", "e4_contract_seal_manifest", "e4_contract_audit"}
            }
            _contract_sha, _seal_sha, actual_root, _contract = issuer._contract_binding(artifact_rows)
            self.assertEqual(actual_root, root)

    def test_contract_seal_requires_exact_v10_contract_member_and_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root / "seal-id", "POPULATION_GENERATION")
            seal_path = Path(bindings["artifacts"]["e4_contract_seal_manifest"])
            manifest = json.loads(seal_path.read_text(encoding="utf-8"))
            _rewrite_contract_seal(bindings, manifest["entries"], {"seal_id": "OTHER_V08_SEAL"})
            with self.assertRaisesRegex(issuer.AuthorizationError, "manifest identity"):
                _build("POPULATION_GENERATION", bindings)

            bindings = _fixture_bindings(root / "member-id", "POPULATION_GENERATION")
            seal_path = Path(bindings["artifacts"]["e4_contract_seal_manifest"])
            entries = json.loads(seal_path.read_text(encoding="utf-8"))["entries"]
            entries[0]["artifact_id"] = "E4_0_CONTRACT_OTHER"
            _rewrite_contract_seal(bindings, entries)
            with self.assertRaisesRegex(issuer.AuthorizationError, "exactly one matching v11 contract member"):
                _build("POPULATION_GENERATION", bindings)

            bindings = _fixture_bindings(root / "member-path", "POPULATION_GENERATION")
            seal_path = Path(bindings["artifacts"]["e4_contract_seal_manifest"])
            entries = json.loads(seal_path.read_text(encoding="utf-8"))["entries"]
            entries[0]["path"] = "contracts/other-contract.json"
            _rewrite_contract_seal(bindings, entries)
            with self.assertRaisesRegex(issuer.AuthorizationError, "exact final v11 contract path and bytes"):
                _build("POPULATION_GENERATION", bindings)

    def test_contract_seal_rejects_duplicate_or_ambiguous_membership(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root / "duplicate", "POPULATION_GENERATION")
            seal_path = Path(bindings["artifacts"]["e4_contract_seal_manifest"])
            entries = json.loads(seal_path.read_text(encoding="utf-8"))["entries"]
            entries.append(dict(entries[0]))
            _rewrite_contract_seal(bindings, entries)
            with self.assertRaisesRegex(issuer.AuthorizationError, "duplicate member identity"):
                _build("POPULATION_GENERATION", bindings)

            bindings = _fixture_bindings(root / "ambiguous", "POPULATION_GENERATION")
            seal_path = Path(bindings["artifacts"]["e4_contract_seal_manifest"])
            entries = json.loads(seal_path.read_text(encoding="utf-8"))["entries"]
            second = dict(entries[0])
            second["artifact_id"] = "E4_0_CONTRACT_COPY"
            second["path"] = "contracts/copy.json"
            entries.append(second)
            _rewrite_contract_seal(bindings, entries)
            with self.assertRaisesRegex(issuer.AuthorizationError, "exactly one matching v11 contract member"):
                _build("POPULATION_GENERATION", bindings)

    def test_artifact_role_extra_and_truth_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "POPULATION_GENERATION")
            bindings["artifacts"]["unexpected"] = str(root / "x")
            with self.assertRaises(issuer.AuthorizationError):
                _build("POPULATION_GENERATION", bindings)
            bindings = _fixture_bindings(root / "second", "POPULATION_GENERATION")
            bindings["artifacts"]["e1_rows"] = str(root / "labels" / "truth.jsonl")
            with self.assertRaises(issuer.AuthorizationError):
                _build("POPULATION_GENERATION", bindings)

    def test_interval_must_be_finite_integer_and_create_is_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "POPULATION_GENERATION")
            bindings["valid_for_seconds"] = True
            with self.assertRaises(issuer.AuthorizationError):
                _build("POPULATION_GENERATION", bindings)
            bindings["valid_for_seconds"] = 600
            authorization = _build("POPULATION_GENERATION", bindings, now_unix_seconds=100)
            self.assertEqual((authorization["issued_utc_unix_seconds"], authorization["valid_from_utc_unix_seconds"], authorization["valid_until_utc_unix_seconds"]), (100, 100, 700))
            output = root / "auth.json"
            byte_count, digest = issuer.create_once(output, authorization)
            original = output.read_bytes()
            self.assertEqual(byte_count, len(original))
            self.assertEqual(digest, _digest(original))
            with self.assertRaises(issuer.AuthorizationError):
                issuer.create_once(output, authorization)
            self.assertEqual(output.read_bytes(), original)

    def test_online_parity_reuses_exact_v06_population_and_panel_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            bindings = _fixture_bindings(Path(temp), "ONLINE_CACHE_PARITY")
            authorization = _build("ONLINE_CACHE_PARITY", bindings, now_unix_seconds=3000)
            roots = authorization["exact_predecessor_roots"]
            self.assertEqual(roots["e4_population_root_sha256"], bindings["_test_reference_config"]["V06_INHERITED_ROOTS"]["e4_population_root_sha256"])
            self.assertEqual(roots["e4_population_audit_root_sha256"], bindings["_test_reference_config"]["V06_INHERITED_ROOTS"]["e4_population_audit_root_sha256"])
            self.assertEqual(roots["e4_parity_panel_root_sha256"], bindings["_test_reference_config"]["V06_INHERITED_ROOTS"]["e4_parity_panel_root_sha256"])
            self.assertEqual(authorization["contract_sha256"], _digest(Path(bindings["artifacts"]["e4_contract"]).read_bytes()))
            self.assertEqual(authorization["schema"], "FAS_E4_0_STAGE_AUTH_V01")

    def test_online_parity_rejects_same_root_panel_copy_and_non_v10_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root / "copy", "ONLINE_CACHE_PARITY")
            panel = Path(bindings["artifacts"]["parity_panel_seal"])
            copied = root / "same-bytes-different-path.json"
            copied.write_bytes(panel.read_bytes())
            bindings["artifacts"]["parity_panel_seal"] = str(copied.resolve())
            with self.assertRaisesRegex(issuer.AuthorizationError, "exact v06 parity_panel_seal bytes and path"):
                _build("ONLINE_CACHE_PARITY", bindings)

            bindings = _fixture_bindings(root / "lineage", "ONLINE_CACHE_PARITY")
            contract_path = Path(bindings["artifacts"]["e4_contract"])
            contract = json.loads(contract_path.read_text(encoding="utf-8"))
            contract["supersedes"]["contract"]["sha256"] = "0" * 64
            _refresh_contract_binding(bindings, contract)
            with self.assertRaisesRegex(issuer.AuthorizationError, "directly supersede the exact sealed v10"):
                _build("ONLINE_CACHE_PARITY", bindings)

    def test_v08_v09_or_v10_contract_identity_cannot_authorize_v11(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for version in ("V08", "V09", "V10"):
                bindings = _fixture_bindings(root / version, "POPULATION_GENERATION")
                contract_path = Path(bindings["artifacts"]["e4_contract"])
                contract = json.loads(contract_path.read_text(encoding="utf-8"))
                contract["contract_id"] = f"FAS_FROZEN_CAPABILITY_FABRIC_E4_0_{version}"
                _refresh_contract_binding(bindings, contract)
                with self.subTest(version=version), self.assertRaisesRegex(
                        issuer.AuthorizationError, "not the final sealed v11 contract"):
                    _build("POPULATION_GENERATION", bindings)


if __name__ == "__main__":
    unittest.main()
