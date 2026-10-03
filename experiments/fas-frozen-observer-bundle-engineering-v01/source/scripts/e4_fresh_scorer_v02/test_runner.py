from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

import numpy as np

import runner
import scorer


def _write(path: Path, payload: bytes) -> tuple[str, int]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest(), len(payload)


def _e4_seal(
    *,
    path: Path,
    path_root: Path,
    stage: str,
    contract_hash: str,
    contract_root: str | None,
    predecessors: dict[str, str],
    members: list[tuple[str, Path]],
) -> dict[str, Any]:
    entries = []
    for artifact_id, artifact_path in members:
        digest, size = runner.sha256_file(artifact_path)
        entries.append({
            "artifact_id": artifact_id,
            "path": artifact_path.resolve().relative_to(path_root.resolve()).as_posix(),
            "bytes": size,
            "sha256": digest,
        })
    entries.sort(key=lambda item: item["artifact_id"].encode("utf-8"))
    seal = {
        "schema": runner.SEAL_SCHEMA,
        "status": "SEALED",
        "seal_id": runner.CONTRACT_SEAL_ID if stage == runner.CONTRACT_STAGE else f"SYNTHETIC_{stage}",
        "stage": stage,
        "path_root_kind": "WORKSPACE_ROOT" if stage == runner.CONTRACT_STAGE else "E4_RUN_ROOT",
        "created_utc": "2026-09-26T00:00:00+00:00",
        "contract_sha256": contract_hash,
        "contract_seal_root_sha256": contract_root,
        "exact_predecessor_roots": predecessors,
        "entries": entries,
        "entry_count": len(entries),
        "root_sha256": runner.e4_artifact_tree_root(entries),
    }
    runner.atomic_json(path, seal)
    return seal


def _legacy_path_seal(path: Path, status: str, path_member: Path) -> str:
    digest, size = _write(path_member, f"{path.name}-sealed-member".encode())
    entry = {"path": path_member.relative_to(path.parents[2]).as_posix(), "bytes": size, "sha256": digest}
    seal = {"status": status, "entries": [entry], "entry_count": 1}
    seal["root_sha256"] = runner.path_tree_root([entry])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json(seal))
    return seal["root_sha256"]


def _legacy_artifact_seal(path: Path, entries: list[dict[str, Any]], status: str = "SEALED") -> str:
    seal = {"status": status, "entries": entries, "entry_count": len(entries)}
    seal["root_sha256"] = runner.legacy_artifact_tree_root(entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json(seal))
    return seal["root_sha256"]


def _audit(path: Path, root_key: str, root: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json({
        "status": "PASS",
        "all_checks_passed": True,
        root_key: root,
    }))


def _row_manifest() -> list[dict[str, Any]]:
    rows = []
    for prefix, surface, custody in (
        ("primary", scorer.PRIMARY_SURFACE, scorer.PRIMARY_TRUTH_PARTITION),
        ("heldout", "HELDOUT_TEMPLATE", "TEMPLATE_ESCROW"),
    ):
        for variant in scorer.QUARTET_VARIANTS:
            rows.append({
                "row_index": len(rows),
                "row_id": f"{prefix}-{variant}",
                "quartet_id": prefix,
                "variant_id": variant,
                "surface_id": surface,
                "truth_partition": custody,
            })
    return rows


def _primary_labels(manifest: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = []
    for row in manifest[:4]:
        context, entity = (1, 0) if row["variant_id"] == "C" else (0, 1) if row["variant_id"] == "E" else (0, 0)
        labels.append({
            "row_id": row["row_id"],
            "quartet_id": row["quartet_id"],
            "variant_id": row["variant_id"],
            "context_term_id": context,
            "entity_term_id": entity,
            "relation_id": 1,
            "state_id": 2,
            "exact_target": 1,
            "target_candidate_identity": 2,
            "candidate_identity_order": [0, 2, 1],
            "both_terms_train_side": True,
            "fit_eligibility": {
                "CONTEXT_IDENTITY": True,
                "ENTITY_IDENTITY": True,
                "RELATION_IDENTITY": True,
                "OBSERVED_STATE": True,
                "EXACT_TARGET": True,
            },
            "score_strata": scorer.target_stratum(context, entity),
        })
    return labels


def _write_stage_receipt(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(runner.canonical_json(value))


def synthetic_layout(workspace: Path) -> tuple[Path, dict[str, str]]:
    project = workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
    run_root = workspace / "runs" / "e4-0-v01"
    e1_root = run_root.parent / "e1-panel-v04"
    e2_root = run_root.parent / "e2-v07"
    e3_root = run_root.parent / "e3-v02"

    e0_root = _legacy_path_seal(project / "seals" / "e0-seal-v10.json", "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT", project / "sealed-e0-member.json")
    e1_root_hash = _legacy_path_seal(e1_root / "e1-seal-v01.json", "E1_PANEL_SEALED_MODEL_CONTACT_NOT_AUTHORIZED", e1_root / "sealed-e1-member.json")
    e2_member = e2_root / "e2-member.bin"
    _write(e2_member, b"synthetic e2 sealed member")
    e2_root_hash = _legacy_artifact_seal(e2_root / "e2-v07-seal.json", [{
        "artifact_id": "e2_v07_feature_cache",
        "bytes": runner.E2_REFERENCE_CACHE_BYTES,
        "sha256": runner.E2_REFERENCE_CACHE_SHA256,
    }])
    e2_seal_path = e2_root / "e2-v07-seal.json"
    e2_seal = json.loads(e2_seal_path.read_text())
    e2_seal["feature_cache_sha256"] = runner.E2_REFERENCE_CACHE_SHA256
    e2_seal["feature_cache_bytes"] = runner.E2_REFERENCE_CACHE_BYTES
    e2_seal_path.write_bytes(runner.canonical_json(e2_seal))

    tasks = scorer.TASKS
    e3_entries = []
    for task, (_field, classes, _scope) in tasks.items():
        tensors = {
            "mean": np.zeros(scorer.DIMENSION, dtype="<f4"),
            "scale": np.ones(scorer.DIMENSION, dtype="<f4"),
            "weight": np.zeros((classes, scorer.DIMENSION), dtype="<f4"),
            "bias": np.zeros(classes, dtype="<f4"),
        }
        for kind, tensor in tensors.items():
            artifact_id = f"e3_v02_{task}_{kind}"
            head_path = e3_root / f"{task}.{kind}.f32le"
            digest, size = _write(head_path, tensor.tobytes(order="C"))
            e3_entries.append({
                "artifact_id": artifact_id,
                "path": str(head_path.resolve()),
                "bytes": size,
                "sha256": digest,
            })
    e3_root_hash = _legacy_artifact_seal(e3_root / "e3-v02-seal.json", e3_entries)

    static = {
        "e0_v10_root_sha256": e0_root,
        "e1_v04_root_sha256": e1_root_hash,
        "e2_v07_root_sha256": e2_root_hash,
        "e3_v02_bundle_root_sha256": e3_root_hash,
    }
    _audit(project / "audits" / "e0-v10-independent-audit-v01.json", "seal_root_sha256", e0_root)
    _audit(project / "audits" / "e1-independent-audit-v04.json", "e1_root_sha256", e1_root_hash)
    e2_audit_path = project / "audits" / "e2-v07-independent-audit-v01.json"
    _audit(e2_audit_path, "e2_root_sha256", e2_root_hash)
    e2_audit = json.loads(e2_audit_path.read_text())
    e2_audit["feature_cache_sha256"] = runner.E2_REFERENCE_CACHE_SHA256
    e2_audit["feature_cache_bytes"] = runner.E2_REFERENCE_CACHE_BYTES
    e2_audit_path.write_bytes(runner.canonical_json(e2_audit))
    _audit(e3_root / "e3-v02-independent-audit-v01.json", "e3_root_sha256", e3_root_hash)

    source_project = Path(__file__).resolve().parents[3]
    superseded_contract_path = project / "contracts" / "e4-0-contract-v05-final.json"
    superseded_seal_path = project / "seals" / "e4-0-contract-v05-seal.json"
    superseded_contract_path.parent.mkdir(parents=True, exist_ok=True)
    superseded_seal_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_project / "contracts" / "e4-0-contract-v05-final.json", superseded_contract_path)
    shutil.copyfile(source_project / "seals" / "e4-0-contract-v05-seal.json", superseded_seal_path)

    contract_path = project / "contracts" / "e4-0-contract-v06-final.json"
    contract = {
        "contract_id": runner.CONTRACT_ID,
        "status": "SEALED",
        "supersedes": {
            "contract": dict(runner.V05_CONTRACT_SUPERSEDES),
            "seal": dict(runner.V05_SEAL_SUPERSEDES),
        },
        "predecessors": static,
        "fresh_qualification": {
            "bootstrap": {
                "replicates": scorer.BOOTSTRAP_REPLICATES,
                "seed": scorer.BOOTSTRAP_SEED,
                "chunk_replicates": scorer.BOOTSTRAP_CHUNK_REPLICATES,
                "lower_tail_alpha_per_endpoint": scorer.BOOTSTRAP_ALPHA,
            },
            "gate": {
                "endpoint_order": list(scorer.ENDPOINT_ORDER),
                "balanced_accuracy_lower_bound_minimum": scorer.PERFORMANCE_FLOOR,
            },
        },
        "population": {"support": {"scoring_minimum_rows_per_class": scorer.MINIMUM_ROWS_PER_CLASS}},
    }
    contract_bytes = runner.canonical_json(contract)
    contract_hash, _ = _write(contract_path, contract_bytes)
    contract_seal_path = project / "seals" / "e4-0-contract-v06-seal.json"
    contract_seal = _e4_seal(
        path=contract_seal_path,
        path_root=workspace,
        stage=runner.CONTRACT_STAGE,
        contract_hash=contract_hash,
        contract_root=None,
        predecessors=static,
        members=[
            (runner.CONTRACT_ARTIFACT_ID, contract_path),
            (runner.V05_SUPERSEDED_CONTRACT_ARTIFACT_ID, superseded_contract_path),
            (runner.V05_SUPERSEDED_SEAL_ARTIFACT_ID, superseded_seal_path),
        ],
    )

    manifest = _row_manifest()
    manifest_path = run_root / "population" / "row-manifest-v01.jsonl"
    manifest_bytes = runner.jsonl_bytes(manifest)
    manifest_hash, manifest_size = _write(manifest_path, manifest_bytes)
    inputs_path = run_root / "population" / "panel-inputs-v01.jsonl"
    _write(inputs_path, b'{"row_id":"synthetic"}\n')
    labels = _primary_labels(manifest)
    label_path = run_root / "labels" / "primary-terminal-labels-v01.jsonl"
    label_bytes = runner.jsonl_bytes(labels)
    _write(label_path, label_bytes)
    escrow_path = run_root / "labels" / "template-joint-escrow-v01.jsonl"
    _write(escrow_path, b"SYNTHETIC_ESCROW_SENTINEL_DO_NOT_OPEN\n")
    population_receipt_path = run_root / "receipts" / "population-generation-receipt-v01.json"
    _write_stage_receipt(population_receipt_path, {"status": "POPULATION_GENERATION_COMPLETE"})
    population_seal_path = run_root / "seals" / "e4-0-population-v01-seal.json"
    population_seal = _e4_seal(
        path=population_seal_path,
        path_root=run_root,
        stage="POPULATION_GENERATION",
        contract_hash=contract_hash,
        contract_root=contract_seal["root_sha256"],
        predecessors=static,
        members=[
            ("E4_POPULATION_INPUTS_V01", inputs_path),
            ("E4_POPULATION_ROW_MANIFEST_V01", manifest_path),
            ("E4_PRIMARY_TERMINAL_LABELS_V01", label_path),
            ("E4_TEMPLATE_JOINT_ESCROW_LABELS_V01", escrow_path),
            ("E4_POPULATION_GENERATION_RECEIPT_V01", population_receipt_path),
        ],
    )
    population_audit_path = project / "audits" / "e4-0-population-v01-independent-audit.json"
    _audit(population_audit_path, "population_root_sha256", population_seal["root_sha256"])
    population_audit_hash = runner.sha256_file(population_audit_path)[0]

    panel_members = []
    panel_dir = run_root / "parity-panel"
    for artifact_id, name in (
        ("panel_inputs", "inputs-v01.jsonl"),
        ("panel_row_manifest", "row-manifest-v01.jsonl"),
    ):
        member = panel_dir / name
        _write(member, b"synthetic panel member\n")
        panel_members.append((artifact_id, member))
    panel_receipt_path = panel_dir / "selection-receipt-v01.json"
    _write_stage_receipt(panel_receipt_path, {"status": "PARITY_PANEL_SEALED"})
    panel_members.append(("selection_receipt", panel_receipt_path))
    panel_predecessors = {**static, "e4_population_root_sha256": population_seal["root_sha256"], "e4_population_audit_root_sha256": population_audit_hash}
    panel_seal = _e4_seal(
        path=panel_dir / "stage-seal-v01.json", path_root=run_root, stage="PARITY_PANEL_MATERIALIZATION",
        contract_hash=contract_hash, contract_root=contract_seal["root_sha256"],
        predecessors=panel_predecessors, members=panel_members,
    )

    parity_dir = run_root / "parity"
    parity_receipt_path = parity_dir / "parity-receipt-v01.json"
    _write_stage_receipt(parity_receipt_path, {
        "status": "ONLINE_CACHE_PARITY_PASS",
        "feature_byte_identical": True,
        "feature_max_abs_deviation": 0.0,
        "e2_reference_cache": {
            "sha256": runner.E2_REFERENCE_CACHE_SHA256,
            "bytes": runner.E2_REFERENCE_CACHE_BYTES,
        },
        "prediction_agreement_by_head": {task: 1.0 for task in scorer.TASKS},
    })
    parity_predecessors = {**panel_predecessors, "e4_parity_panel_root_sha256": panel_seal["root_sha256"]}
    parity_gpu_receipt = parity_dir / "gpu-lease-receipt-v01.json"
    _write_stage_receipt(parity_gpu_receipt, {"status": "GPU_LEASE_RELEASED"})
    online_features = parity_dir / "parity-online-features.f32le"
    _write(online_features, np.zeros((4, scorer.DIMENSION), dtype="<f4").tobytes())
    parity_seal = _e4_seal(
        path=parity_dir / "stage-seal-v01.json", path_root=run_root, stage="ONLINE_CACHE_PARITY",
        contract_hash=contract_hash, contract_root=contract_seal["root_sha256"],
        predecessors=parity_predecessors,
        members=[
            ("gpu_lease_receipt", parity_gpu_receipt),
            ("parity_receipt", parity_receipt_path),
            ("online_feature_cache", online_features),
        ],
    )

    features_dir = run_root / "features"
    feature_cache_path = features_dir / "V1_FINAL_POSITION.f32le"
    feature_bytes = np.zeros((len(manifest), scorer.DIMENSION), dtype="<f4").tobytes()
    feature_hash, feature_size = _write(feature_cache_path, feature_bytes)
    feature_receipt_path = features_dir / "feature-extraction-receipt-v01.json"
    _write_stage_receipt(feature_receipt_path, {
        "status": "FEATURE_CACHE_COMPLETE_GATE_PASS",
        "predictions_emitted": False,
        "labels_opened": False,
        "heldout_template_or_joint_labels_opened": False,
        "feature_cache": {
            "path": "features/V1_FINAL_POSITION.f32le",
            "sha256": feature_hash,
            "bytes": feature_size,
            "rows": len(manifest),
            "row_count": len(manifest),
            "dimension": scorer.DIMENSION,
            "dtype": "<f4",
            "layout": "C_ROW_MAJOR",
        },
        "row_identity": {
            "manifest_sha256": manifest_hash,
            "row_count": len(manifest),
            "ordered_row_identity_match": True,
            "quartet_atomicity_and_order_verified": True,
            "surface_id_values": ["PRIMARY_SEEN", "HELDOUT_TEMPLATE"],
            "truth_partition_values": ["PRIMARY_TERMINAL", "TEMPLATE_ESCROW"],
        },
    })
    gpu_receipt = features_dir / "gpu-lease-receipt-v01.json"
    _write_stage_receipt(gpu_receipt, {"status": "GPU_LEASE_RELEASED"})
    feature_predecessors = {**parity_predecessors, "e4_parity_receipt_root_sha256": parity_seal["root_sha256"]}
    feature_seal = _e4_seal(
        path=features_dir / "stage-seal-v01.json", path_root=run_root, stage="FRESH_FEATURE_EXTRACTION",
        contract_hash=contract_hash, contract_root=contract_seal["root_sha256"],
        predecessors=feature_predecessors,
        members=[
            ("feature_cache", feature_cache_path),
            ("population_row_manifest", manifest_path),
            ("feature_extraction_receipt", feature_receipt_path),
            ("gpu_lease_receipt", gpu_receipt),
        ],
    )

    roots = {
        **static,
        "e4_population_root_sha256": population_seal["root_sha256"],
        "e4_population_audit_root_sha256": population_audit_hash,
        "e4_parity_panel_root_sha256": panel_seal["root_sha256"],
        "e4_parity_receipt_root_sha256": parity_seal["root_sha256"],
        "e4_feature_cache_root_sha256": feature_seal["root_sha256"],
    }
    authorization = {
        "schema": scorer.AUTH_SCHEMA,
        "authorization_id": "synthetic-cli-scoring-auth",
        "status": "AUTHORIZED",
        "stage": "FRESH_SCORING",
        "contract_sha256": contract_hash,
        "contract_seal_manifest_sha256": runner.sha256_file(contract_seal_path)[0],
        "contract_seal_root_sha256": contract_seal["root_sha256"],
        "exact_predecessor_roots": roots,
        "output_root": str(run_root.resolve()),
        "scope": dict(scorer.SCORING_AUTH_SCOPE),
        "authorized_by": "ACTIVE_USER_REQUEST",
        "issued_utc_unix_seconds": 1,
        "valid_from_utc_unix_seconds": 1,
        "valid_until_utc_unix_seconds": 4_102_444_800,
    }
    auth_path = project / "audits" / "e4-0-fresh-scoring-authorization-v01.json"
    _write_stage_receipt(auth_path, authorization)
    return auth_path, static


class RunnerCliTests(unittest.TestCase):
    def test_v06_contract_successor_and_v05_lineage_identities_are_frozen(self) -> None:
        self.assertEqual(runner.CONTRACT_ID, "FAS_FROZEN_CAPABILITY_FABRIC_E4_0_V06")
        self.assertEqual(runner.CONTRACT_ARTIFACT_ID, "E4_0_CONTRACT_V06_FINAL")
        self.assertEqual(runner.CONTRACT_SEAL_ID, "FAS_E4_0_CONTRACT_V06_SEAL")
        self.assertEqual(runner.V05_SUPERSEDED_CONTRACT_ARTIFACT_ID, "E4_0_CONTRACT_V05_SUPERSEDED")
        self.assertEqual(runner.V05_SUPERSEDED_SEAL_ARTIFACT_ID, "E4_0_CONTRACT_V05_SEAL_SUPERSEDED")
        self.assertEqual(runner.V05_CONTRACT_SUPERSEDES["bytes"], 39_944)
        self.assertEqual(
            runner.V05_CONTRACT_SUPERSEDES["sha256"],
            "ad709bd1496536e6fb1464bd89a06ec0eed552b89ef4159bfc1aa0f406fcc71a",
        )
        self.assertEqual(runner.V05_SEAL_SUPERSEDES["manifest_bytes"], 29_668)
        self.assertEqual(
            runner.V05_SEAL_SUPERSEDES["manifest_sha256"],
            "434e4472275adbd6514e5b6a0e8d905c7a283ea6ea294edc0068c050336cd9eb",
        )
        self.assertEqual(
            runner.V05_SEAL_SUPERSEDES["root_sha256"],
            "38fa25b9433319fc706a1d7fc1e56f20a267f30d467c42ac75ff0850ec656fd1",
        )

    def test_synthetic_stages_use_exact_track_b_member_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            auth_path, _static = synthetic_layout(workspace)
            run_root = Path(json.loads(auth_path.read_text())["output_root"])
            expected = {
                "parity-panel/stage-seal-v01.json": {"panel_inputs", "panel_row_manifest", "selection_receipt"},
                "parity/stage-seal-v01.json": {"gpu_lease_receipt", "parity_receipt", "online_feature_cache"},
                "features/stage-seal-v01.json": {"gpu_lease_receipt", "feature_extraction_receipt", "feature_cache", "population_row_manifest"},
            }
            for relative_path, required_ids in expected.items():
                seal = json.loads((run_root / relative_path).read_text())
                self.assertEqual({entry["artifact_id"] for entry in seal["entries"]}, required_ids)

    def test_preflight_only_cli_smoke_leaves_labels_unopened_and_score_absent(self) -> None:
        original_roots = runner.EXPECTED_ROOTS
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            auth_path, static = synthetic_layout(workspace)
            runner.EXPECTED_ROOTS = static
            stdout, stderr = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result_code = runner.main([
                        "--workspace-root", str(workspace),
                        "--authorization", str(auth_path),
                        "--preflight-only",
                    ])
            finally:
                runner.EXPECTED_ROOTS = original_roots
            self.assertEqual(result_code, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["status"], "SCORING_PREFLIGHT_PASS_LABELS_UNOPENED")
            self.assertFalse(result["labels_opened"])
            self.assertFalse(result["model_or_tokenizer_contact"])
            run_root = Path(json.loads(auth_path.read_text())["output_root"])
            self.assertFalse((run_root / "score").exists())
            self.assertEqual(
                (run_root / "labels" / "template-joint-escrow-v01.jsonl").read_bytes(),
                b"SYNTHETIC_ESCROW_SENTINEL_DO_NOT_OPEN\n",
            )

    def test_synthetic_seal_chain_opens_only_primary_once_and_seals_outputs(self) -> None:
        original_roots = runner.EXPECTED_ROOTS
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            auth_path, static = synthetic_layout(workspace)
            runner.EXPECTED_ROOTS = static
            stdout = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout):
                    result_code = runner.main([
                        "--workspace-root", str(workspace),
                        "--authorization", str(auth_path),
                    ])
            finally:
                runner.EXPECTED_ROOTS = original_roots
            self.assertEqual(result_code, 0, stdout.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["terminal_disposition"], "FAIL_FRESH_QUALIFICATION")
            self.assertEqual(result["failed_endpoints"], list(scorer.ENDPOINT_ORDER))
            run_root = Path(json.loads(auth_path.read_text()) ["output_root"])
            score = run_root / "score"
            receipt = json.loads((score / "label-open-receipt-v01.json").read_text())
            self.assertEqual(receipt["label_file_open_count"], 1)
            self.assertEqual(receipt["semantic_label_open_count"], 1)
            self.assertEqual(receipt["escrow_label_file_open_count"], 0)
            self.assertEqual(receipt["label_sha256"], runner.sha256_file(run_root / "labels" / "primary-terminal-labels-v01.jsonl")[0])
            prediction_rows = [json.loads(line) for line in (score / "predictions-v01.jsonl").read_text().splitlines()]
            self.assertEqual(len(prediction_rows), 4)
            self.assertTrue(all(row["truth_partition"] == "PRIMARY_TERMINAL" for row in prediction_rows))
            metrics = json.loads((score / "metrics-v01.json").read_text())
            self.assertEqual(metrics["schema"], "fas-e4-0-fresh-qualification-v01")
            self.assertEqual(metrics["endpoint_order"], list(scorer.ENDPOINT_ORDER))
            with np.load(score / "bootstrap-v01.npz", allow_pickle=False) as bootstrap:
                self.assertEqual(bootstrap.files, [
                    f"endpoint_{index:02d}__bootstrap_balanced_accuracy"
                    for index in range(len(scorer.ENDPOINT_ORDER))
                ])
                self.assertTrue(all(bootstrap[key].dtype == np.float64 and len(bootstrap[key]) == 0 for key in bootstrap.files))
            terminal = json.loads((score / "terminal-receipt-v01.json").read_text())
            self.assertEqual(terminal["primary_label_file_open_count"], 1)
            self.assertFalse(terminal["heldout_template_labels_opened"])
            seal = json.loads((score / "stage-seal-v01.json").read_text())
            verified = runner.verify_artifact_seal(
                score / "stage-seal-v01.json",
                path_root=run_root,
                expected_stage="FRESH_SCORING",
                contract_sha256=authorization_contract_hash(auth_path),
                contract_seal_root_sha256=json.loads((workspace / "experiments" / "fas-frozen-observer-bundle-engineering-v01" / "seals" / "e4-0-contract-v06-seal.json").read_text())["root_sha256"],
                expected_predecessors=static | json.loads(auth_path.read_text())["exact_predecessor_roots"],
            )
            self.assertEqual(verified.root_sha256, seal["root_sha256"])
            escrow = run_root / "labels" / "template-joint-escrow-v01.jsonl"
            self.assertEqual(escrow.read_bytes(), b"SYNTHETIC_ESCROW_SENTINEL_DO_NOT_OPEN\n")

    def test_cli_rejects_broader_scope_before_creating_score_or_opening_labels(self) -> None:
        original_roots = runner.EXPECTED_ROOTS
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            auth_path, static = synthetic_layout(workspace)
            auth = json.loads(auth_path.read_text())
            auth["scope"]["heldout_template_label_opening"] = True
            auth_path.write_bytes(runner.canonical_json(auth))
            runner.EXPECTED_ROOTS = static
            stdout, stderr = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    result_code = runner.main([
                        "--workspace-root", str(workspace),
                        "--authorization", str(auth_path),
                    ])
            finally:
                runner.EXPECTED_ROOTS = original_roots
            self.assertEqual(result_code, 2)
            self.assertIn("scope is broader", stderr.getvalue())
            run_root = Path(auth["output_root"])
            self.assertFalse((run_root / "score").exists())
            self.assertEqual(
                (run_root / "labels" / "template-joint-escrow-v01.jsonl").read_bytes(),
                b"SYNTHETIC_ESCROW_SENTINEL_DO_NOT_OPEN\n",
            )

    def test_cli_rejects_tampered_feature_bytes_before_label_open(self) -> None:
        original_roots = runner.EXPECTED_ROOTS
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            auth_path, static = synthetic_layout(workspace)
            run_root = Path(json.loads(auth_path.read_text())["output_root"])
            feature_path = run_root / "features" / "V1_FINAL_POSITION.f32le"
            tampered = bytearray(feature_path.read_bytes())
            tampered[0] = 1
            feature_path.write_bytes(tampered)
            runner.EXPECTED_ROOTS = static
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    result_code = runner.main([
                        "--workspace-root", str(workspace),
                        "--authorization", str(auth_path),
                    ])
            finally:
                runner.EXPECTED_ROOTS = original_roots
            self.assertEqual(result_code, 2)
            self.assertIn("sealed artifact bytes/hash mismatch: feature_cache", stderr.getvalue())
            self.assertFalse((run_root / "score").exists())


def authorization_contract_hash(auth_path: Path) -> str:
    return json.loads(auth_path.read_text())["contract_sha256"]


if __name__ == "__main__":
    unittest.main()
