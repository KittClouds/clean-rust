"""Synthetic, model-free tests for the immutable E4 stage-auth issuer."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import issue_e4_stage_authorization_v01 as issuer
import e4_runner_common_v01 as runner_common


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_file(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
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
        "status": "SEALED_E4_0_V05",
        "predecessors": dict(issuer.PREDECESSOR_ROOTS),
    }
    _json_file(contract_path, contract_value)
    contract_bytes = contract_path.read_bytes()
    contract_hash = _digest(contract_bytes)
    contract_entry = {
        "artifact_id": "E4_0_CONTRACT_V05_FINAL",
        "path": "contracts/e4-0-contract-v05-final.json",
        "bytes": len(contract_bytes),
        "sha256": contract_hash,
    }
    contract_root = _seal_root([contract_entry])
    seal_path = paths_by_role["e4_contract_seal_manifest"]
    _json_file(seal_path, {
        "schema": issuer.ARTIFACT_SEAL_SCHEMA,
        "status": "SEALED",
        "stage": "E4_0_CONTRACT",
        "contract_sha256": contract_hash,
        "root_sha256": contract_root,
        "entries": [contract_entry],
    })
    _json_file(paths_by_role["e4_contract_audit"], {
        "status": "PASS_INDEPENDENT_CONTRACT_AUDIT",
        "e4_0_contract_root_sha256": contract_root,
    })

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
            "status": "PASS_INDEPENDENT_POPULATION_AUDIT",
            "population_root_sha256": population_root,
            "all_checks_passed": True,
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

    bindings: dict[str, object] = {
        "output_root": str((root / "e4-run").resolve()),
        "valid_for_seconds": 600,
        "artifacts": {role: str(path.resolve()) for role, path in paths_by_role.items()},
        "paths": path_map,
        "gpu_lease": {"lock_path": str((root / "locks" / "cuda0-exclusive.json").resolve())},
    }
    return bindings


class AuthorizationIssuerTests(unittest.TestCase):
    def test_all_runtime_stages_match_track_d_exact_fields_roots_and_scope(self) -> None:
        from e4_independent_audit_v01.cli import _auth

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for stage in (
                "POPULATION_GENERATION",
                "PARITY_PANEL_MATERIALIZATION",
                "ONLINE_CACHE_PARITY",
                "FRESH_FEATURE_EXTRACTION",
            ):
                bindings = _fixture_bindings(root / stage, stage)
                authorization = issuer.build_authorization(stage=stage, bindings=bindings)
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
                auth_path = root / f"{stage}.json"
                _json_file(auth_path, authorization)
                _auth(auth_path, stage, root)
                if stage != "POPULATION_GENERATION":
                    mode = {
                        "PARITY_PANEL_MATERIALIZATION": "materialize-parity-panel",
                        "ONLINE_CACHE_PARITY": "parity",
                        "FRESH_FEATURE_EXTRACTION": "extract-e4",
                    }[stage]
                    runner_common.validate_stage_authorization(
                        authorization, mode, now=datetime.now(timezone.utc),
                    )
                expected_count = 4 + (0 if stage == "POPULATION_GENERATION" else {
                    "PARITY_PANEL_MATERIALIZATION": 2,
                    "ONLINE_CACHE_PARITY": 3,
                    "FRESH_FEATURE_EXTRACTION": 4,
                }[stage])
                self.assertEqual(len(authorization["exact_predecessor_roots"]), expected_count)
                self.assertFalse(authorization["scope"]["heldout_template_label_opening"])
                self.assertFalse(authorization["scope"]["joint_template_label_opening"])

    def test_fresh_scoring_preserves_scorer_exact_fourteen_fields(self) -> None:
        from e4_fresh_scorer_v01 import scorer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "FRESH_SCORING")
            authorization = issuer.build_authorization(stage="FRESH_SCORING", bindings=bindings, now_unix_seconds=2000)
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
                issuer.build_authorization(stage="POPULATION_GENERATION", bindings=bindings, now_unix_seconds=1)

    def test_artifact_role_extra_and_truth_paths_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "POPULATION_GENERATION")
            bindings["artifacts"]["unexpected"] = str(root / "x")
            with self.assertRaises(issuer.AuthorizationError):
                issuer.build_authorization(stage="POPULATION_GENERATION", bindings=bindings)
            bindings = _fixture_bindings(root / "second", "POPULATION_GENERATION")
            bindings["artifacts"]["e1_rows"] = str(root / "labels" / "truth.jsonl")
            with self.assertRaises(issuer.AuthorizationError):
                issuer.build_authorization(stage="POPULATION_GENERATION", bindings=bindings)

    def test_interval_must_be_finite_integer_and_create_is_once(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bindings = _fixture_bindings(root, "POPULATION_GENERATION")
            bindings["valid_for_seconds"] = True
            with self.assertRaises(issuer.AuthorizationError):
                issuer.build_authorization(stage="POPULATION_GENERATION", bindings=bindings)
            bindings["valid_for_seconds"] = 600
            authorization = issuer.build_authorization(stage="POPULATION_GENERATION", bindings=bindings, now_unix_seconds=100)
            self.assertEqual((authorization["issued_utc_unix_seconds"], authorization["valid_from_utc_unix_seconds"], authorization["valid_until_utc_unix_seconds"]), (100, 100, 700))
            output = root / "auth.json"
            byte_count, digest = issuer.create_once(output, authorization)
            original = output.read_bytes()
            self.assertEqual(byte_count, len(original))
            self.assertEqual(digest, _digest(original))
            with self.assertRaises(issuer.AuthorizationError):
                issuer.create_once(output, authorization)
            self.assertEqual(output.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
