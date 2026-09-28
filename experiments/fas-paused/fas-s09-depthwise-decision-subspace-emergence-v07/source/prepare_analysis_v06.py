from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from s09_common import RUN_ROOT, entry_for, read_json, sha256_file, tree_root, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V04_ROOT = RUN_ROOT / "history-v04" / "full-run-v04"
V04_PROJECT = RUN_ROOT / "history-v04" / "project-v04"
CONTRACT = read_json(PROJECT_ROOT / "contracts" / "s09-analysis-contract-v06.json")
CORRECTION = read_json(PROJECT_ROOT / "contracts" / "analysis-correction-record-v06.json")


def verify_sealed_tree(base: Path, seal_path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"seal declares an unexpected root: {seal_path}")
    entries = [entry_for(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    entries.sort(key=lambda item: item["path"])
    if entries != seal["entries"] or tree_root(entries) != expected_root:
        raise RuntimeError(f"sealed tree does not verify: {seal_path}")
    return {"root_sha256": expected_root, "entries_verified": len(entries)}


def copy_protocol_snapshot(protocol: dict[str, Any]) -> Path:
    source_seal = PROJECT_ROOT / "seals" / "protocol-seal-v06.json"
    snapshot = RUN_ROOT / "inputs" / "project-snapshot"
    if snapshot.exists():
        raise RuntimeError("v06 project snapshot already exists; refusing overwrite")
    for item in protocol["entries"]:
        source = PROJECT_ROOT.joinpath(*item["path"].split("/"))
        target = snapshot.joinpath(*item["path"].split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    seal_target = snapshot / "seals" / source_seal.name
    seal_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_seal, seal_target)
    return snapshot


def main() -> int:
    if (RUN_ROOT / "seals" / "preflight-seal-v06.json").exists() or (RUN_ROOT / "parent-verification-receipt-v06.json").exists():
        raise RuntimeError("v06 analysis preflight already exists; refusing overwrite")
    protocol = read_json(PROJECT_ROOT / "seals" / "protocol-seal-v06.json")
    protocol_check = verify_sealed_tree(PROJECT_ROOT, PROJECT_ROOT / "seals" / "protocol-seal-v06.json", protocol["root_sha256"])
    snapshot = copy_protocol_snapshot(protocol)
    snapshot_check = verify_sealed_tree(snapshot, snapshot / "seals" / "protocol-seal-v06.json", protocol["root_sha256"])

    v04_parent = CORRECTION["v04_formula_parent"]
    v04_protocol = verify_sealed_tree(
        V04_PROJECT,
        V04_PROJECT / "seals" / "protocol-seal-v04.json",
        v04_parent["protocol_root_sha256"],
    )
    if sha256_file(V04_PROJECT / "seals" / "protocol-seal-v04.json")[0] != v04_parent["protocol_seal_file_sha256"]:
        raise RuntimeError("archived v04 protocol seal file differs from v06 correction binding")
    v04_preflight = verify_sealed_tree(
        V04_ROOT,
        V04_ROOT / "seals" / "preflight-seal-v04.json",
        v04_parent["preflight_root_sha256"],
    )
    archived_input_entries = {
        item["path"][len("inputs/"):]: item
        for item in read_json(V04_ROOT / "seals" / "preflight-seal-v04.json")["entries"]
        if item["path"].startswith("inputs/") and not item["path"].startswith("inputs/project-snapshot/")
    }
    current_input_paths = {
        path.relative_to(RUN_ROOT / "inputs").as_posix(): path
        for path in (RUN_ROOT / "inputs").rglob("*")
        if path.is_file() and "project-snapshot" not in path.relative_to(RUN_ROOT / "inputs").parts
    }
    if set(current_input_paths) != set(archived_input_entries):
        raise RuntimeError("v06 S01/S08 input inventory differs from the sealed v04 input inventory")
    for relative, path in current_input_paths.items():
        if entry_for(path, RUN_ROOT / "inputs") != {**archived_input_entries[relative], "path": relative}:
            raise RuntimeError(f"v06 parent input differs from sealed v04 input: {relative}")

    v05_project = RUN_ROOT / "history-v05" / "project-v05"
    v05_protocol_path = v05_project / "seals" / "protocol-seal-v05.json"
    v05_protocol = read_json(v05_protocol_path)
    if v05_protocol.get("root_sha256") != CORRECTION["superseded_protocol_root_sha256"]:
        raise RuntimeError("archived v05 protocol root differs from correction binding")
    verify_sealed_tree(v05_project, v05_protocol_path, CORRECTION["superseded_protocol_root_sha256"])
    if sha256_file(v05_protocol_path)[0] != CORRECTION["superseded_protocol_seal_file_sha256"]:
        raise RuntimeError("archived v05 protocol seal file differs from correction binding")
    v05_failure_path = RUN_ROOT / "history-v05" / "full-run-v05" / "analysis-failure-v05.json"
    if sha256_file(v05_failure_path)[0] != CORRECTION["prior_attempt_failure"]["failure_receipt_sha256"]:
        raise RuntimeError("archived v05 audit failure differs from correction binding")
    v05_failure = read_json(v05_failure_path)
    if v05_failure.get("model_loaded") is not False or v05_failure.get("feature_cache_read") is not False or v05_failure.get("probe_fits_performed") is not False:
        raise RuntimeError("v05 failed audit crossed its authorized read-only boundary")

    failure_path = V04_ROOT / "analysis-failure-v04.json"
    if sha256_file(failure_path)[0] != CORRECTION["failure_artifacts"]["analysis_failure_v04_sha256"]:
        raise RuntimeError("preserved v04 failure receipt differs from correction binding")
    failure = read_json(failure_path)
    if failure.get("error") != "layer-16 M effective pair normals fail S08 identity: max_abs=4.180381107943276e-07":
        raise RuntimeError("preserved v04 failure does not match the correction record")

    cache_seal_path = RUN_ROOT / "recovery-feature-cache-seal-v03.json"
    recovery_path = RUN_ROOT / "recovery-extraction-receipt-v03.json"
    cache_seal = read_json(cache_seal_path)
    recovery = read_json(recovery_path)
    bound = CONTRACT["inputs"]
    if cache_seal.get("root_sha256") != bound["recovered_feature_cache_root_sha256"]:
        raise RuntimeError("v03 feature cache root differs from v06 parent binding")
    if recovery.get("feature_cache_root_sha256") != cache_seal["root_sha256"] or recovery.get("rows") != 106496 or recovery.get("matrices") != 32:
        raise RuntimeError("v03 recovery receipt does not bind the expected cache")
    if recovery.get("backbone_parameter_delta") != 0 or recovery.get("probe_fitting_performed") is not False:
        raise RuntimeError("v03 recovery receipt violates the frozen extraction boundary")
    if sha256_file(recovery_path)[0] != bound["recovery_receipt_sha256"]:
        raise RuntimeError("v03 recovery receipt bytes differ from v06 parent binding")
    if sha256_file(cache_seal_path)[0] != bound["recovery_cache_seal_file_sha256"]:
        raise RuntimeError("v03 recovery cache seal bytes differ from v06 parent binding")

    v04_audit_path = V04_ROOT / "metric-schema-audit-v04.json"
    if sha256_file(v04_audit_path)[0] != CORRECTION["failure_artifacts"]["metric_schema_audit_v04_sha256"]:
        raise RuntimeError("preserved v04 metric audit differs from v06 correction binding")
    v04_audit = read_json(v04_audit_path)
    if v04_audit.get("all_computed_condition_metric_fields_exact") is not True or v04_audit.get("feature_cache_root_sha256") != cache_seal["root_sha256"]:
        raise RuntimeError("v04 terminal metric-schema audit is not a valid inherited parent")
    metric_audit = dict(v04_audit)
    metric_audit["audit_id"] = "FAS_S09_METRIC_SCHEMA_AUDIT_V06_INHERITED"
    metric_audit["source_run_id"] = "fas-s09-depthwise-decision-subspace-emergence-v04"
    metric_audit["source_audit_sha256"] = sha256_file(v04_audit_path)[0]
    metric_audit["v06_terminal_reproduction_required"] = True
    metric_audit_path = RUN_ROOT / "metric-schema-audit-v06.json"
    write_json(metric_audit_path, metric_audit)

    geometry_audit_path = RUN_ROOT / "geometry-semantics-audit-v06.json"
    geometry_audit = read_json(geometry_audit_path)
    if geometry_audit.get("disposition") != "RUNTIME_SCALER_PRECISION_CORRECTION_QUALIFIED":
        raise RuntimeError("v06 geometry-semantics audit has not passed")

    parent_roots = {
        "S01_2_CONSTRUCTION": bound["S01_2_construction_root_sha256"],
        "S01_2_EXTRACTION_RESULT": bound["S01_2_extraction_result_root_sha256"],
        "S01_2_FEATURE_CACHE": bound["S01_2_feature_cache_root_sha256"],
        "S01_3_LINEAR_ACCESSIBILITY": bound["S01_3_result_root_sha256"],
        "S08_S01_ANALYSIS": bound["S08_S01_analysis_root_sha256"],
    }
    receipt = {
        "receipt_id": "FAS_S09_V06_ANALYSIS_PARENT_RECEIPT",
        "project_protocol_root_sha256": protocol["root_sha256"],
        "v04_project_protocol_root_sha256": v04_parent["protocol_root_sha256"],
        "v04_preflight_root_sha256": v04_parent["preflight_root_sha256"],
        "v05_failed_protocol_root_sha256": v05_protocol["root_sha256"],
        "v05_failed_protocol_seal_file_sha256": sha256_file(v05_protocol_path)[0],
        "v05_read_only_failure_sha256": sha256_file(v05_failure_path)[0],
        "v04_failure_sha256": sha256_file(failure_path)[0],
        "v04_terminal_probe_states": {
            surface: CORRECTION["failure_artifacts"][f"{surface}_terminal_probe_state_v04_sha256"]
            for surface in ("M", "F")
        },
        "verified_parent_roots": parent_roots,
        "v03_recovery_cache_root_sha256": cache_seal["root_sha256"],
        "v03_recovery_receipt_sha256": bound["recovery_receipt_sha256"],
        "v03_recovery_cache_seal_sha256": bound["recovery_cache_seal_file_sha256"],
        "metric_schema_audit_sha256": sha256_file(metric_audit_path)[0],
        "geometry_semantics_audit_sha256": sha256_file(geometry_audit_path)[0],
        "v04_failed_attempt_preserved": True,
        "model_loaded": False,
        "feature_extraction_performed": False,
        "probe_fitting_performed": False,
        "fas00_access": False,
    }
    receipt_path = RUN_ROOT / "parent-verification-receipt-v06.json"
    write_json(receipt_path, receipt)

    included = [path for path in (RUN_ROOT / "inputs").rglob("*") if path.is_file()]
    included.extend(path for path in (RUN_ROOT / "history-v04").rglob("*") if path.is_file())
    included.extend(path for path in (RUN_ROOT / "history-v05").rglob("*") if path.is_file())
    included.extend([cache_seal_path, recovery_path, metric_audit_path, geometry_audit_path, receipt_path])
    entries = [entry_for(path, RUN_ROOT) for path in included]
    entries.sort(key=lambda item: item["path"])
    preflight_root = tree_root(entries)
    write_json(RUN_ROOT / "seals" / "preflight-seal-v06.json", {
        "seal_id": "FAS_S09_ANALYSIS_PREFLIGHT_SEAL_V06",
        "entries": entries,
        "root_sha256": preflight_root,
        "protocol_root_sha256": protocol["root_sha256"],
        "feature_cache_root_sha256": cache_seal["root_sha256"],
        "geometry_semantics_audit_sha256": receipt["geometry_semantics_audit_sha256"],
        "v04_history_project_root_sha256": v04_protocol["root_sha256"],
        "v04_history_preflight_root_sha256": v04_preflight["root_sha256"],
        "model_loaded": False,
        "probe_fitting_performed": False,
    })
    print(f"analysis_preflight_v06=PASS root_sha256={preflight_root} entries={len(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
