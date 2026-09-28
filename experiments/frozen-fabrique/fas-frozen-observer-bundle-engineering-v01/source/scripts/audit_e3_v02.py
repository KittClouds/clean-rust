from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[4]
PROJECT = REPO_ROOT / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
RUNS = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01")
E0_ROOT = "899a131c09298fdafdcc6771ad01e8982857a1cd47900259800f97dd7bea7ccd"
E1_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
E2_ROOT = "a2e2aa76f77904665b9abfa2a22f609c05219d8bc64c537bed41f5c634d1da8a"
CACHE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
CACHE_BYTES = 872_415_232
ROWS = 106_496
DIM = 2_048
TASKS = {
    "context_identity": ("context_term_id", "CONTEXT_IDENTITY", 32),
    "entity_identity": ("entity_term_id", "ENTITY_IDENTITY", 32),
    "relation": ("relation_id", "RELATION_IDENTITY", 2),
    "observed_state": ("state_id", "OBSERVED_STATE", 3),
    "exact_target": ("exact_target", "EXACT_TARGET", 3),
}
FIT_V01 = RUNS / "e3-v01"
FIT_V02 = RUNS / "e3-v02"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")


def root_for_path_entries(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def root_for_artifacts(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda item: item["artifact_id"]):
        digest.update(f'{entry["artifact_id"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def verify_path_seal(path: Path, base: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(path)
    actual: list[dict[str, Any]] = []
    for entry in seal.get("entries", []):
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise RuntimeError(f"unsafe sealed relative path in {path.name}: {entry['path']}")
        digest, size = sha256_file(base / relative)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"sealed member changed: {entry['path']}")
        actual.append({"path": relative.as_posix(), "bytes": size, "sha256": digest})
    if len(actual) != seal.get("entry_count") or root_for_path_entries(actual) != expected_root:
        raise RuntimeError(f"sealed root or entry count mismatch: {path.name}")
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"unexpected sealed root: {path.name}")
    return seal


def verify_e2_seal(path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(path)
    entries = seal.get("entries", [])
    for entry in entries:
        digest, size = sha256_file(Path(entry["path"]))
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"E2 sealed artifact changed: {entry.get('artifact_id')}")
    if root_for_artifacts(entries) != expected_root or seal.get("root_sha256") != expected_root:
        raise RuntimeError("E2 v07 root recomputation failed")
    return seal


def add_artifact(entries: list[dict[str, Any]], artifact_id: str, path: Path) -> None:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    entries.append({"artifact_id": artifact_id, "path": str(resolved), "bytes": size, "sha256": digest})


def load_fit_partition(
    fit_labels_path: Path,
    row_manifest_path: Path,
    split_manifest_path: Path,
) -> tuple[dict[str, list[int]], dict[str, Any]]:
    row_by_id: dict[str, tuple[int, str, str]] = {}
    for line_no, line in enumerate(row_manifest_path.open("r", encoding="utf-8"), start=1):
        row = json.loads(line)
        row_id = row.get("row_id")
        row_index = row.get("row_index")
        quartet = row.get("quartet_id")
        split = row.get("quartet_split")
        if not isinstance(row_id, str) or not isinstance(row_index, int) or row_id in row_by_id:
            raise RuntimeError(f"invalid or duplicate row manifest identity at line {line_no}")
        if not isinstance(quartet, str) or split not in ("FIT", "TEST"):
            raise RuntimeError(f"invalid row split identity at line {line_no}")
        row_by_id[row_id] = (row_index, quartet, split)
    if len(row_by_id) != ROWS or sorted(value[0] for value in row_by_id.values()) != list(range(ROWS)):
        raise RuntimeError("row manifest is not a complete ordered feature-cache mapping")

    quartet_split: dict[str, str] = {}
    for line_no, line in enumerate(split_manifest_path.open("r", encoding="utf-8"), start=1):
        row = json.loads(line)
        quartet, split = row.get("quartet_id"), row.get("split")
        if not isinstance(quartet, str) or split not in ("FIT", "TEST") or quartet in quartet_split:
            raise RuntimeError(f"invalid or duplicate split manifest row at line {line_no}")
        quartet_split[quartet] = split
    if sum(value == "FIT" for value in quartet_split.values()) != 21_301:
        raise RuntimeError("FIT quartet count does not match the corrected sealed E1 split receipt")
    if sum(value == "TEST" for value in quartet_split.values()) != 5_323:
        raise RuntimeError("TEST quartet count does not match the corrected sealed E1 split receipt")

    expected_fit_ids = {
        row_id for row_id, (_, quartet, split) in row_by_id.items()
        if split == "FIT" and quartet_split.get(quartet) == "FIT"
    }
    indices: dict[str, list[int]] = {task: [] for task in TASKS}
    labels_by_task: dict[str, list[int]] = {task: [] for task in TASKS}
    observed_fit_ids: set[str] = set()
    eligibility_mismatches = 0
    fit_rows = 0
    for line_no, line in enumerate(fit_labels_path.open("r", encoding="utf-8"), start=1):
        row = json.loads(line)
        fit_rows += 1
        row_id, quartet = row.get("row_id"), row.get("quartet_id")
        if not isinstance(row_id, str) or row_id not in row_by_id or row_id in observed_fit_ids:
            raise RuntimeError(f"invalid, absent, or duplicate fit row at line {line_no}")
        row_index, expected_quartet, row_split = row_by_id[row_id]
        if quartet != expected_quartet or row_split != "FIT" or quartet_split.get(quartet) != "FIT":
            raise RuntimeError(f"fit label row does not map to a FIT quartet at line {line_no}")
        observed_fit_ids.add(row_id)
        context, entity = row.get("context_term_id"), row.get("entity_term_id")
        if not isinstance(context, int) or not isinstance(entity, int):
            raise RuntimeError(f"invalid factor ID in FIT labels at line {line_no}")
        train_side = context < 16 and entity < 16
        if row.get("both_terms_train_side") is not train_side:
            raise RuntimeError(f"FIT label train-side flag mismatch at line {line_no}")
        flags = row.get("fit_eligibility", {})
        expected_flags = {
            "CONTEXT_IDENTITY": True,
            "ENTITY_IDENTITY": True,
            "RELATION_IDENTITY": train_side,
            "OBSERVED_STATE": train_side,
            "EXACT_TARGET": train_side,
        }
        for task, (field, flag, class_count) in TASKS.items():
            if flags.get(flag) is not expected_flags[flag]:
                eligibility_mismatches += 1
                raise RuntimeError(f"FIT eligibility mismatch for {task} at line {line_no}")
            if expected_flags[flag]:
                label = row.get(field)
                if not isinstance(label, int) or not 0 <= label < class_count:
                    raise RuntimeError(f"invalid {task} class ID at line {line_no}")
                indices[task].append(row_index)
                labels_by_task[task].append(label)

    if fit_rows != 85_204 or observed_fit_ids != expected_fit_ids:
        raise RuntimeError("fit-label rows do not exactly cover the sealed FIT quartets")
    summary: dict[str, Any] = {
        "fit_label_rows": fit_rows,
        "fit_quartets": 21_301,
        "eligibility_mismatches": eligibility_mismatches,
    }
    for task, (_, _, class_count) in TASKS.items():
        counts = np.bincount(np.asarray(labels_by_task[task], dtype=np.int64), minlength=class_count)
        if len(indices[task]) == 0 or np.any(counts == 0):
            raise RuntimeError(f"training task lacks a declared class: {task}")
        summary[task] = {"fit_rows": len(indices[task]), "class_counts": counts.tolist()}
    return indices, summary


def verify_float_artifact(path: Path, expected_count: int, positive: bool = False) -> tuple[str, int]:
    digest, size = sha256_file(path)
    if size != expected_count * 4:
        raise RuntimeError(f"unexpected float artifact byte size: {path.name}")
    values = np.fromfile(path, dtype="<f4")
    if values.size != expected_count or not bool(np.isfinite(values).all()):
        raise RuntimeError(f"non-finite or invalid float artifact: {path.name}")
    if positive and not bool(np.all(values > 0.0)):
        raise RuntimeError(f"non-positive scaler entry: {path.name}")
    return digest, size


def main() -> int:
    seal_path = FIT_V02 / "e3-v02-seal.json"
    audit_path = FIT_V02 / "e3-v02-independent-audit-v01.json"
    bundle_path = FIT_V02 / "frozen-capability-fabric-v02.json"
    if seal_path.exists() or audit_path.exists() or bundle_path.exists():
        raise RuntimeError("E3 v02 audit outputs already exist; refusing overwrite")

    e0_seal_path = PROJECT / "seals" / "e0-seal-v10.json"
    e0_audit_path = PROJECT / "audits" / "e0-v10-independent-audit-v01.json"
    e1_root_dir = RUNS / "e1-panel-v04"
    e1_seal_path = e1_root_dir / "e1-seal-v01.json"
    e1_audit_path = PROJECT / "audits" / "e1-independent-audit-v04.json"
    e2_root_dir = RUNS / "e2-v07"
    e2_seal_path = e2_root_dir / "e2-v07-seal.json"
    e2_audit_path = e2_root_dir / "e2-v07-independent-audit-v01.json"
    e2_run_receipt = e2_root_dir / "feature-cache-receipt-v07.json"
    cache_path = e2_root_dir / "V1_FINAL_POSITION.f32le"
    e3_contract_path = PROJECT / "contracts" / "e3-fit-v02.json"
    e3_auth_path = PROJECT / "audits" / "e3-fit-authorization-v02.json"
    e3_receipt_path = FIT_V02 / "e3-fit-receipt-v01.json"
    fit_labels_path = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\labels\fit-labels-v01.jsonl")
    row_manifest_path = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\panel\row-manifest-v01.jsonl")
    split_manifest_path = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e1-panel-v04\panel\split-manifest-v01.jsonl")
    v01_disposition_path = PROJECT / "audits" / "e3-v01-resource-gate-disposition-v01.json"
    checks: dict[str, bool] = {}
    details: dict[str, Any] = {}

    try:
        e0_seal = verify_path_seal(e0_seal_path, REPO_ROOT, E0_ROOT)
        e0_audit = read_json(e0_audit_path)
        checks["e0_v10_seal_and_all_members_recomputed"] = (
            e0_seal["root_sha256"] == E0_ROOT
            and e0_audit.get("status") == "E0_V10_INDEPENDENT_AUDIT_PASS_MODEL_CONTACT_NOT_AUTHORIZED"
            and e0_audit.get("all_checks_passed") is True
        )

        e1_seal = read_json(e1_seal_path)
        e1_entries = e1_seal.get("entries", [])
        checks["e1_v04_sealed_tree_root_and_prior_audit_pass"] = (
            e1_seal.get("root_sha256") == E1_ROOT
            and root_for_path_entries(e1_entries) == E1_ROOT
            and e1_seal.get("entry_count") == len(e1_entries)
            and read_json(e1_audit_path).get("status") == "PASS"
            and read_json(e1_audit_path).get("e1_root_sha256") == E1_ROOT
        )
        # The E1 label-side audit receipt and sealed metadata are inspected. The TEST-label file itself is not opened or hashed.

        e2_seal = verify_e2_seal(e2_seal_path, E2_ROOT)
        e2_audit = read_json(e2_audit_path)
        checks["e2_v07_root_and_independent_audit_pass"] = (
            e2_seal.get("e0_v10_root_sha256") == E0_ROOT
            and e2_seal.get("e1_v04_root_sha256") == E1_ROOT
            and e2_audit.get("status") == "E2_V07_INDEPENDENT_AUDIT_PASS_E3_NOT_AUTHORIZED_BY_E0_FREEZE"
            and e2_audit.get("all_checks_passed") is True
            and e2_audit.get("e2_root_sha256") == E2_ROOT
        )

        contract = read_json(e3_contract_path)
        authorization = read_json(e3_auth_path)
        receipt = read_json(e3_receipt_path)
        contract_hash, _ = sha256_file(e3_contract_path)
        authorization_hash, _ = sha256_file(e3_auth_path)
        checks["v02_contract_auth_and_exact_fit_source_hashes"] = (
            contract_hash == authorization.get("contract_sha256")
            and authorization.get("e3_fit_authorized") is True
            and authorization.get("e3_scoring_authorized") is False
            and authorization.get("contract_sha256") == contract_hash
            and contract["predecessors"]["e0_v10_root_sha256"] == E0_ROOT
            and contract["predecessors"]["e1_v04_root_sha256"] == E1_ROOT
            and contract["predecessors"]["e2_v07_root_sha256"] == E2_ROOT
            and contract["predecessors"]["e3_v01_resource_disposition_sha256"] == sha256_file(v01_disposition_path)[0]
            and contract["implementation"]["fit_source_sha256"] == sha256_file(PROJECT / "source/scripts/fit_observers_e3_v02.py")[0]
            and contract["implementation"]["test_source_sha256"] == sha256_file(PROJECT / "source/tests/test_e3_fit_v02.py")[0]
            and contract["implementation"]["builder_source_sha256"] == sha256_file(PROJECT / "source/scripts/build_e3_contract_v02.py")[0]
        )

        for key, path in (("feature_cache", cache_path), ("fit_labels", fit_labels_path), ("row_manifest", row_manifest_path), ("split_manifest", split_manifest_path)):
            digest, size = sha256_file(path)
            pin = contract["inputs"][key]
            checks[f"input_{key}_hash_and_length"] = digest == pin["sha256"] and size == pin["bytes"]

        indices_by_task, fit_summary = load_fit_partition(fit_labels_path, row_manifest_path, split_manifest_path)
        checks["fit_only_population_reconstructed_from_fit_labels_and_manifests"] = (
            fit_summary == receipt["fit_partition_summary"]
            and fit_summary["fit_label_rows"] == 85_204
            and fit_summary["fit_quartets"] == 21_301
            and fit_summary["eligibility_mismatches"] == 0
        )

        heads = {head["task"]: head for head in receipt.get("heads", [])}
        checks["five_expected_independent_heads_and_fit_only_boundary"] = (
            set(heads) == set(TASKS)
            and receipt.get("status") == "E3_V02_FIVE_INDEPENDENT_FITS_COMPLETE_PENDING_INDEPENDENT_AUDIT_NO_SCORING"
            and receipt.get("e0_root_sha256") == E0_ROOT
            and receipt.get("e2_root_sha256") == E2_ROOT
            and receipt.get("e3_contract_sha256") == contract_hash
            and receipt.get("authorization_sha256") == authorization_hash
            and receipt.get("fit_labels_opened") is True
            and receipt.get("evaluation_labels_opened") is False
            and receipt.get("heldout_rows_read") is False
            and receipt.get("test_performance_scored") is False
            and receipt.get("e3_scoring_authorized") is False
            and receipt.get("hyperparameter_search_performed") is False
            and receipt.get("shared_or_multitask_head_used") is False
            and receipt.get("backbone_or_feature_cache_modified") is False
        )

        expected_parameters = 0
        expected_scaler_bytes = 0
        head_artifacts: dict[str, dict[str, Any]] = {}
        for task, (label_field, eligibility, class_count) in TASKS.items():
            head = heads[task]
            row_count = fit_summary[task]["fit_rows"]
            expected_class_counts = fit_summary[task]["class_counts"]
            weight_count = class_count * DIM
            parameter_count = weight_count + class_count
            expected_parameters += parameter_count
            expected_scaler_bytes += 2 * DIM * 4
            if (
                head.get("label_field") != label_field
                or head.get("eligibility_flag") != eligibility
                or head.get("class_count") != class_count
                or head.get("fit_rows") != row_count
                or head.get("fit_class_counts") != expected_class_counts
                or head.get("scaler_rows") != row_count
                or head.get("trainable_parameters") != parameter_count
                or head.get("trainable_parameter_bytes_f32") != parameter_count * 4
                or head.get("scaler_bytes_f32") != 2 * DIM * 4
                or head.get("optimizer_spec") != contract["optimizer"]
                or not np.isfinite(head.get("initial_training_objective", np.nan))
                or not np.isfinite(head.get("final_training_objective", np.nan))
                or head["final_training_objective"] > head["initial_training_objective"]
            ):
                raise RuntimeError(f"fit receipt metadata mismatch for task {task}")
            files: dict[str, dict[str, Any]] = {}
            for suffix, count, positive in (
                ("mean", DIM, False),
                ("scale", DIM, True),
                ("weight", weight_count, False),
                ("bias", class_count, False),
            ):
                path = FIT_V02 / f"{task}.{suffix}.f32le"
                digest, size = verify_float_artifact(path, count, positive)
                files[suffix] = {"path": str(path.resolve()), "sha256": digest, "bytes": size, "dtype": "little-endian float32", "elements": count}
            head_artifacts[task] = {
                "label_field": label_field,
                "fit_rows": row_count,
                "class_count": class_count,
                "weight_shape": [class_count, DIM],
                "bias_shape": [class_count],
                "trainable_parameters": parameter_count,
                "files": files,
            }

        checks["all_observer_files_have_exact_shapes_finite_values_and_positive_scales"] = True
        checks["independent_trainable_state_and_storage_totals_match_contract"] = (
            expected_parameters == contract["model"]["trainable_parameters_expected"] == receipt["trainable_parameters_total"] == 147_528
            and receipt["trainable_parameter_bytes_f32_total"] == contract["model"]["trainable_parameter_bytes_f32_expected"] == 590_112
            and expected_scaler_bytes == receipt["scaler_bytes_f32_total"] == contract["model"]["scaler_bytes_f32_expected"] == 81_920
            and receipt["trainable_parameter_bytes_f32_total"] + receipt["scaler_bytes_f32_total"] == contract["model"]["total_observer_bytes_f32_expected"] == 672_032
        )

        gpu = receipt.get("gpu_process_peak", {})
        disk = receipt.get("disk_preflight", {})
        resource_contract = contract["resources"]
        checks["process_scoped_gpu_and_frozen_disk_gates_pass"] = (
            gpu.get("scope") == "E3 fitter process PyTorch CUDA caching allocator only"
            and gpu.get("total_gpu_memory_claimed") is False
            and gpu.get("reserved_peak_bytes", 2**63) <= resource_contract["process_reserved_ceiling_bytes"]
            and gpu.get("allocated_peak_bytes", 2**63) <= gpu.get("reserved_peak_bytes", -1)
            and receipt.get("gpu_preflight", {}).get("free_bytes_at_preflight", 0) >= resource_contract["minimum_free_device_memory_bytes"]
            and disk.get("gate_passed") is True
            and disk.get("measurement") == "Python shutil.disk_usage on output-parent filesystem"
            and disk.get("free_bytes_before_fit", 0) >= resource_contract["minimum_free_disk_bytes"]
            and receipt.get("disk_free_bytes_after_fit_before_receipt", -1) >= 0
        )

        v01_disposition = read_json(v01_disposition_path)
        checks["v01_unverified_attempt_preserved_without_requalification"] = (
            v01_disposition.get("status") == "E3_V01_FITS_PRESERVED_RESOURCE_GATE_UNVERIFIED_NOT_QUALIFIED"
            and v01_disposition.get("disk_space_measured_before_fit") is False
            and v01_disposition.get("fit_artifacts_modified") is False
        )

        details = {
            "fit_partition_summary": fit_summary,
            "head_artifacts": head_artifacts,
            "gpu_process_peak": gpu,
            "disk_preflight": disk,
            "evaluation_label_file_opened_by_auditor": False,
            "evaluation_label_content_hashed_by_auditor": False,
        }
        if not all(checks.values()):
            raise RuntimeError(f"independent E3 v02 checks failed: {[key for key, value in checks.items() if not value]}")

        abi_candidates = [
            entry for entry in e0_seal["entries"]
            if entry["path"].endswith("representation-abi-v07.json")
        ]
        if len(abi_candidates) != 1:
            raise RuntimeError("E0 seal does not identify exactly one representation ABI v07 artifact")
        abi_entry = abi_candidates[0]
        bundle = {
            "bundle_id": contract["fit_outputs"]["bundle_id"],
            "status": "FROZEN_CAPABILITY_FABRIC_V02_TRAINING_ONLY_SCORING_CLOSED",
            "substrate": {
                "model_family": "LiquidAI LFM2.5-1.2B-Base",
                "model_revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
                "e0_v10_root_sha256": E0_ROOT,
                "e1_v04_root_sha256": E1_ROOT,
                "e2_v07_root_sha256": E2_ROOT,
                "feature_cache_path": str(cache_path.resolve()),
                "feature_cache_sha256": CACHE_SHA256,
                "feature_cache_bytes": CACHE_BYTES,
                "rows": ROWS,
                "dimension": DIM,
                "dtype": "little-endian float32",
                "surface": "V1_FINAL_POSITION",
                "representation_abi_path": abi_entry["path"],
                "representation_abi_sha256": abi_entry["sha256"],
            },
            "observers": head_artifacts,
            "trainable_parameters_total": receipt["trainable_parameters_total"],
            "trainable_parameter_bytes_f32_total": receipt["trainable_parameter_bytes_f32_total"],
            "scaler_bytes_f32_total": receipt["scaler_bytes_f32_total"],
            "observer_and_scaler_bytes_f32_total": 672_032,
            "independent_heads": True,
            "shared_head_or_multitask_loss": False,
            "fit_only": True,
            "evaluation_labels_opened": False,
            "heldout_rows_read": False,
            "performance_scored": False,
            "deployment_or_serving_claimed": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        bundle_path.write_bytes(canonical_json(bundle))

        entries: list[dict[str, Any]] = []
        provenance = [
            ("e0_v10_seal", e0_seal_path),
            ("e0_v10_independent_audit", e0_audit_path),
            ("e0_v10_frozen_contract", PROJECT / "contracts" / "e0-freeze-v10-sealed-v01.json"),
            ("e1_v04_seal", e1_seal_path),
            ("e1_v04_independent_audit", e1_audit_path),
            ("e1_fit_labels_only", fit_labels_path),
            ("e1_row_manifest", row_manifest_path),
            ("e1_split_manifest", split_manifest_path),
            ("e2_v07_seal", e2_seal_path),
            ("e2_v07_independent_audit", e2_audit_path),
            ("e2_v07_run_receipt", e2_run_receipt),
            ("e2_v07_feature_cache", cache_path),
            ("e3_v01_contract", PROJECT / "contracts" / "e3-fit-v01.json"),
            ("e3_v01_authorization", PROJECT / "audits" / "e3-fit-authorization-v01.json"),
            ("e3_v01_resource_gate_disposition", v01_disposition_path),
            ("e3_v01_fit_receipt_preserved_unqualified", FIT_V01 / "e3-fit-receipt-v01.json"),
            ("e3_v02_contract", e3_contract_path),
            ("e3_v02_authorization", e3_auth_path),
            ("e3_v02_builder_source", PROJECT / "source/scripts/build_e3_contract_v02.py"),
            ("e3_v02_fit_source", PROJECT / "source/scripts/fit_observers_e3_v02.py"),
            ("e3_v02_test_source", PROJECT / "source/tests/test_e3_fit_v02.py"),
            ("e3_v02_auditor_source", Path(__file__).resolve()),
            ("e3_v02_fit_receipt", e3_receipt_path),
            ("e3_v02_capability_fabric_bundle", bundle_path),
        ]
        for artifact_id, path in provenance:
            add_artifact(entries, artifact_id, path)
        for task in TASKS:
            for suffix in ("mean", "scale", "weight", "bias"):
                add_artifact(entries, f"e3_v02_{task}_{suffix}", FIT_V02 / f"{task}.{suffix}.f32le")
        for task in TASKS:
            for suffix in ("mean", "scale", "weight", "bias"):
                add_artifact(entries, f"preserved_unqualified_e3_v01_{task}_{suffix}", FIT_V01 / f"{task}.{suffix}.f32le")

        seal = {
            "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_V02_SEAL_V01",
            "status": "E3_V02_FIVE_FITS_SEALED_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED",
            "root_sha256": root_for_artifacts(entries),
            "entry_count": len(entries),
            "entries": sorted(entries, key=lambda item: item["artifact_id"]),
            "e0_v10_root_sha256": E0_ROOT,
            "e1_v04_root_sha256": E1_ROOT,
            "e2_v07_root_sha256": E2_ROOT,
            "feature_cache_sha256": CACHE_SHA256,
            "fit_only_authorized": True,
            "five_independent_heads": True,
            "evaluation_scoring_performed": False,
            "evaluation_labels_opened": False,
            "heldout_rows_read": False,
            "E4_integration_authorized": False,
            "total_gpu_memory_claimed": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        seal_path.write_bytes(canonical_json(seal))
        seal_readback = read_json(seal_path)
        if root_for_artifacts(seal_readback["entries"]) != seal_readback["root_sha256"]:
            raise RuntimeError("E3 v02 seal root failed readback recomputation")
        for entry in seal_readback["entries"]:
            digest, size = sha256_file(Path(entry["path"]))
            if digest != entry["sha256"] or size != entry["bytes"]:
                raise RuntimeError(f"E3 v02 sealed artifact failed readback: {entry['artifact_id']}")

        audit = {
            "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_V02_INDEPENDENT_AUDIT_V01",
            "status": "E3_V02_FIVE_FITS_INDEPENDENT_AUDIT_PASS_HELDOUT_SCORING_CLOSED",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "e3_root_sha256": seal["root_sha256"],
            "e3_seal_path": str(seal_path.resolve()),
            "checks": checks,
            "all_checks_passed": all(checks.values()),
            "details": details,
            "evaluation_label_file_opened_by_auditor": False,
            "evaluation_label_content_hashed_by_auditor": False,
            "performance_scored": False,
            "heldout_outcomes_opened": False,
            "E4_integration_authorized": False,
            "prior_e3_v01_resource_gate_status": "UNVERIFIED_PRESERVED_NOT_QUALIFIED",
        }
        audit_path.write_bytes(canonical_json(audit))
        print(json.dumps({
            "status": audit["status"],
            "e3_root_sha256": seal["root_sha256"],
            "entry_count": seal["entry_count"],
            "checks": checks,
            "trainable_parameters_total": receipt["trainable_parameters_total"],
            "bundle_bytes": bundle_path.stat().st_size,
        }, indent=2))
        return 0
    except Exception as error:
        failure = {
            "receipt_id": "FAS_FROZEN_OBSERVER_BUNDLE_E3_V02_INDEPENDENT_AUDIT_FAILURE_V01",
            "status": "E3_V02_AUDIT_FAILED_PRESERVE_ALL_FIT_ARTIFACTS_NO_SCORING",
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "checks": checks,
            "all_checks_passed": False,
            "error": f"{type(error).__name__}: {error}",
            "fit_artifacts_preserved": True,
            "evaluation_labels_opened_by_auditor": False,
            "performance_scored": False,
        }
        if not audit_path.exists():
            audit_path.write_bytes(canonical_json(failure))
        raise


if __name__ == "__main__":
    raise SystemExit(main())
