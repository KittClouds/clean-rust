from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from s09_common import RUN_ROOT, entry_for, read_json, sha256_file, tree_root, write_json


PROJECT_ROOT = Path(__file__).resolve().parents[1]
V04_ROOT = RUN_ROOT / "history-v04" / "full-run-v04"
V04_PROJECT = RUN_ROOT / "history-v04" / "project-v04"
V06_ROOT = RUN_ROOT / "history-v06" / "full-run-v06"
V06_PROJECT = RUN_ROOT / "history-v06" / "project-v06"
V07_ROOT = RUN_ROOT / "history-v07" / "full-run-v07"
V07_PROJECT = RUN_ROOT / "history-v07" / "project-v07"
V08_ROOT = RUN_ROOT / "history-v08" / "full-run-v08"
V08_PROJECT = RUN_ROOT / "history-v08" / "project-v08"
CONTRACT = read_json(PROJECT_ROOT / "contracts" / "s09-analysis-contract-v09.json")
CORRECTION = read_json(PROJECT_ROOT / "contracts" / "analysis-correction-record-v09.json")


def verify_sealed_tree(base: Path, seal_path: Path, expected_root: str) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError(f"seal declares an unexpected root: {seal_path}")
    entries = [entry_for(base.joinpath(*item["path"].split("/")), base) for item in seal["entries"]]
    entries.sort(key=lambda item: item["path"])
    if entries != seal["entries"] or tree_root(entries) != expected_root:
        raise RuntimeError(f"sealed tree does not verify: {seal_path}")
    return {"root_sha256": expected_root, "entries_verified": len(entries)}


def verify_v08_preflight_with_sibling_histories() -> dict[str, Any]:
    """Verify v08's original preflight through byte-identical sibling archives."""
    seal_path = V08_ROOT / "seals" / "preflight-seal-v08.json"
    seal = read_json(seal_path)
    expected_root = CORRECTION["superseded_preflight_root_sha256"]
    if seal.get("root_sha256") != expected_root:
        raise RuntimeError("v08 preflight declares an unexpected root")
    sibling_history_names = {"history-v04", "history-v05", "history-v06", "history-v07"}
    entries = []
    for item in seal["entries"]:
        parts = item["path"].split("/")
        if parts[0] in sibling_history_names:
            base = RUN_ROOT
        else:
            base = V08_ROOT
        path = base.joinpath(*parts)
        actual = entry_for(path, base)
        if actual != item:
            raise RuntimeError(f"v08 preflight entry differs after sibling-history resolution: {item['path']}")
        entries.append(actual)
    entries.sort(key=lambda item: item["path"])
    if entries != seal["entries"] or tree_root(entries) != expected_root:
        raise RuntimeError("v08 preflight does not reproduce through its verified sibling histories")
    audit = read_json(RUN_ROOT / "history-v08" / "sibling-history-equivalence-audit-v09.json")
    if audit.get("manifest_id") != "FAS_S09_V08_SIBLING_HISTORY_EQUIVALENCE_AUDIT_V09":
        raise RuntimeError("v08 sibling-history equivalence audit has an unexpected identity")
    if audit.get("source_v08_preflight_root_sha256") != expected_root or audit.get("nested_history_copy_preserved") is not True:
        raise RuntimeError("v08 sibling-history audit is not bound to the preserved preflight and nested copy")
    if audit.get("source_v08_original_run_untouched") is not True or audit.get("sibling_history_byte_equivalence", "").split(";")[0] != "PASS":
        raise RuntimeError("v08 sibling-history audit does not establish byte equivalence and original preservation")
    history_rows = audit.get("verified_sibling_histories", [])
    if {row.get("sibling_archive_path") for row in history_rows} != sibling_history_names:
        raise RuntimeError("v08 sibling-history audit does not enumerate the complete v04-v07 archive set")
    for row in history_rows:
        prefix = row["sibling_archive_path"] + "/"
        selected = [item for item in entries if item["path"].startswith(prefix)]
        relative = [
            {"path": item["path"][len(prefix):], "bytes": item["bytes"], "sha256": item["sha256"]}
            for item in selected
        ]
        if len(relative) != row["file_count"] or sum(item["bytes"] for item in relative) != row["byte_count"]:
            raise RuntimeError(f"sibling-history audit counts differ for {row['sibling_archive_path']}")
        if tree_root(relative) != row["tree_root_sha256"] or len(selected) != row["files_referenced_by_v08_preflight"]:
            raise RuntimeError(f"sibling-history audit root differs for {row['sibling_archive_path']}")
    return {"root_sha256": expected_root, "entries_verified": len(entries), "history_resolution": "V09_SIBLING_ARCHIVES"}


def copy_protocol_snapshot(protocol: dict[str, Any]) -> Path:
    source_seal = PROJECT_ROOT / "seals" / "protocol-seal-v09.json"
    snapshot = RUN_ROOT / "inputs" / "project-snapshot"
    if snapshot.exists():
        raise RuntimeError("v09 project snapshot already exists; refusing overwrite")
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
    if (RUN_ROOT / "seals" / "preflight-seal-v09.json").exists() or (RUN_ROOT / "parent-verification-receipt-v09.json").exists():
        raise RuntimeError("v09 analysis preflight already exists; refusing overwrite")
    protocol = read_json(PROJECT_ROOT / "seals" / "protocol-seal-v09.json")
    protocol_check = verify_sealed_tree(PROJECT_ROOT, PROJECT_ROOT / "seals" / "protocol-seal-v09.json", protocol["root_sha256"])
    if (RUN_ROOT / "inputs" / "project-snapshot").exists():
        raise RuntimeError("v09 project snapshot already exists; refusing overwrite")

    v04_parent = CORRECTION["v04_formula_parent"]
    v04_protocol = verify_sealed_tree(
        V04_PROJECT,
        V04_PROJECT / "seals" / "protocol-seal-v04.json",
        v04_parent["protocol_root_sha256"],
    )
    if sha256_file(V04_PROJECT / "seals" / "protocol-seal-v04.json")[0] != v04_parent["protocol_seal_file_sha256"]:
        raise RuntimeError("archived v04 protocol seal file differs from v09 correction binding")
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
        raise RuntimeError("v09 S01/S08 input inventory differs from the sealed v04 input inventory")
    for relative, path in current_input_paths.items():
        if entry_for(path, RUN_ROOT / "inputs") != {**archived_input_entries[relative], "path": relative}:
            raise RuntimeError(f"v09 parent input differs from sealed v04 input: {relative}")

    v05_project = RUN_ROOT / "history-v05" / "project-v05"
    v05_protocol_path = v05_project / "seals" / "protocol-seal-v05.json"
    v05_protocol = read_json(v05_protocol_path)
    v05_root = CORRECTION["prior_attempt_failure"]["v05_protocol_root_sha256"]
    v05_seal_hash = CORRECTION["prior_attempt_failure"]["v05_protocol_seal_file_sha256"]
    if v05_protocol.get("root_sha256") != v05_root:
        raise RuntimeError("archived v05 protocol root differs from correction binding")
    verify_sealed_tree(v05_project, v05_protocol_path, v05_root)
    if sha256_file(v05_protocol_path)[0] != v05_seal_hash:
        raise RuntimeError("archived v05 protocol seal file differs from correction binding")
    v05_failure_path = RUN_ROOT / "history-v05" / "full-run-v05" / "analysis-failure-v05.json"
    if sha256_file(v05_failure_path)[0] != CORRECTION["prior_attempt_failure"]["failure_receipt_sha256"]:
        raise RuntimeError("archived v05 audit failure differs from correction binding")
    v05_failure = read_json(v05_failure_path)
    if v05_failure.get("model_loaded") is not False or v05_failure.get("feature_cache_read") is not False or v05_failure.get("probe_fits_performed") is not False:
        raise RuntimeError("v05 failed audit crossed its authorized read-only boundary")

    v06_protocol_path = V06_PROJECT / "seals" / "protocol-seal-v06.json"
    v06_protocol = read_json(v06_protocol_path)
    v06_binding = CORRECTION["v06_history"]
    if v06_protocol.get("root_sha256") != v06_binding["protocol_root_sha256"]:
        raise RuntimeError("archived v06 protocol root differs from correction binding")
    verify_sealed_tree(V06_PROJECT, v06_protocol_path, v06_binding["protocol_root_sha256"])
    if sha256_file(v06_protocol_path)[0] != v06_binding["protocol_seal_file_sha256"]:
        raise RuntimeError("archived v06 protocol seal file differs from correction binding")
    v06_preflight = verify_sealed_tree(
        V06_ROOT,
        V06_ROOT / "seals" / "preflight-seal-v06.json",
        v06_binding["preflight_root_sha256"],
    )
    v06_failure_path = V06_ROOT / "analysis-failure-v06.json"
    if sha256_file(v06_failure_path)[0] != v06_binding["failure_sha256"]:
        raise RuntimeError("archived v06 failure receipt differs from correction binding")
    v06_failure = read_json(v06_failure_path)
    if "principal_angle_degrees" not in v06_failure.get("error", "") or "plane fails S08 terminal reproduction" not in v06_failure.get("error", ""):
        raise RuntimeError("archived v06 failure is not the contracted arccos terminal gate failure")
    for surface in ("M", "F"):
        state_path = V06_ROOT / "analysis-v06" / "probes" / "layer-16" / surface / "probe-state-v06.npz"
        expected_hash = CORRECTION["failure_artifacts"][f"{surface}_terminal_probe_state_v06_sha256"]
        if sha256_file(state_path)[0] != expected_hash:
            raise RuntimeError(f"archived v06 {surface} terminal state differs from correction binding")
    if (V06_ROOT / "analysis-v06" / "probes" / "layer-01").exists() or (V06_ROOT / "metrics-v06.json").exists():
        raise RuntimeError("v06 crossed the terminal gate and produced forbidden earlier-layer outputs")
    v06_geometry_path = V06_ROOT / "geometry-semantics-audit-v06.json"
    if sha256_file(v06_geometry_path)[0] != CORRECTION["failure_artifacts"]["v06_geometry_semantics_audit_sha256"]:
        raise RuntimeError("archived v06 geometry audit differs from correction binding")

    v07_protocol_path = V07_PROJECT / "seals" / "protocol-seal-v07.json"
    v07_protocol = read_json(v07_protocol_path)
    v07_binding = CORRECTION["v07_prior_attempt"]
    if v07_protocol.get("root_sha256") != v07_binding["protocol_root_sha256"]:
        raise RuntimeError("archived v07 protocol root differs from correction binding")
    verify_sealed_tree(V07_PROJECT, v07_protocol_path, v07_binding["protocol_root_sha256"])
    if sha256_file(v07_protocol_path)[0] != v07_binding["protocol_seal_file_sha256"]:
        raise RuntimeError("archived v07 protocol seal file differs from correction binding")
    v07_failure_path = V07_ROOT / "analysis-failure-v07.json"
    if sha256_file(v07_failure_path)[0] != v07_binding["failure_sha256"]:
        raise RuntimeError("archived v07 preflight failure differs from correction binding")
    v07_failure = read_json(v07_failure_path)
    if v07_failure.get("model_loaded") is not False or v07_failure.get("feature_cache_read") is not False or v07_failure.get("probe_fits_performed") is not False or v07_failure.get("preflight_sealed") is not False:
        raise RuntimeError("v07 preflight failure crossed its declared boundary")
    if (V07_ROOT / "seals" / "preflight-seal-v07.json").exists():
        raise RuntimeError("v07 unexpectedly produced a preflight seal")
    v07_snapshot = V07_ROOT / "inputs" / "project-snapshot"
    verify_sealed_tree(v07_snapshot, v07_snapshot / "seals" / "protocol-seal-v07.json", v07_binding["protocol_root_sha256"])
    if sha256_file(v07_snapshot / "seals" / "protocol-seal-v07.json")[0] != v07_binding["protocol_seal_file_sha256"]:
        raise RuntimeError("archived v07 snapshot seal file differs from correction binding")

    v08_protocol_path = V08_PROJECT / "seals" / "protocol-seal-v08.json"
    v08_protocol = read_json(v08_protocol_path)
    if v08_protocol.get("root_sha256") != CORRECTION["superseded_protocol_root_sha256"]:
        raise RuntimeError("archived v08 protocol root differs from correction binding")
    verify_sealed_tree(V08_PROJECT, v08_protocol_path, CORRECTION["superseded_protocol_root_sha256"])
    if sha256_file(v08_protocol_path)[0] != CORRECTION["superseded_protocol_seal_file_sha256"]:
        raise RuntimeError("archived v08 protocol seal file differs from correction binding")
    v08_preflight = verify_v08_preflight_with_sibling_histories()
    v08_failure_path = V08_ROOT / "analysis-failure-v08.json"
    if sha256_file(v08_failure_path)[0] != CORRECTION["failure_artifacts"]["analysis_failure_v08_sha256"]:
        raise RuntimeError("archived v08 analysis failure differs from correction binding")
    v08_failure = read_json(v08_failure_path)
    if v08_failure.get("error_type") != "KeyError" or v08_failure.get("error") != "'layer'":
        raise RuntimeError("archived v08 failure is not the contracted replay helper layer-key error")
    fit_manifest_path = V08_ROOT / "fit-state-manifest-v08.json"
    if sha256_file(fit_manifest_path)[0] != CORRECTION["failure_artifacts"]["fit_state_manifest_v08_sha256"]:
        raise RuntimeError("archived v08 fit-state manifest differs from correction binding")
    fit_manifest = read_json(fit_manifest_path)
    fit_entries = [entry_for(V08_ROOT.joinpath(*item["path"].split("/")), V08_ROOT) for item in fit_manifest["entries"]]
    fit_entries.sort(key=lambda item: item["path"])
    if len(fit_entries) != 32 or fit_entries != fit_manifest["entries"] or tree_root(fit_entries) != fit_manifest["root_sha256"]:
        raise RuntimeError("archived v08 fixed-fit states do not reproduce their 32-state inventory seal")
    if fit_manifest["root_sha256"] != CORRECTION["failure_artifacts"]["fit_state_root_v08_sha256"]:
        raise RuntimeError("archived v08 fit-state root differs from correction binding")
    if (V08_ROOT / "metrics-v08.json").exists() or (V08_ROOT / "analysis-v08" / "analysis-seal-v08.json").exists():
        raise RuntimeError("v08 unexpectedly produced replay metrics or an analysis seal")

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
        raise RuntimeError("v03 feature cache root differs from v09 parent binding")
    if recovery.get("feature_cache_root_sha256") != cache_seal["root_sha256"] or recovery.get("rows") != 106496 or recovery.get("matrices") != 32:
        raise RuntimeError("v03 recovery receipt does not bind the expected cache")
    if recovery.get("backbone_parameter_delta") != 0 or recovery.get("probe_fitting_performed") is not False:
        raise RuntimeError("v03 recovery receipt violates the frozen extraction boundary")
    if sha256_file(recovery_path)[0] != bound["recovery_receipt_sha256"]:
        raise RuntimeError("v03 recovery receipt bytes differ from v09 parent binding")
    if sha256_file(cache_seal_path)[0] != bound["recovery_cache_seal_file_sha256"]:
        raise RuntimeError("v03 recovery cache seal bytes differ from v09 parent binding")

    v04_audit_path = V04_ROOT / "metric-schema-audit-v04.json"
    if sha256_file(v04_audit_path)[0] != CORRECTION["failure_artifacts"]["metric_schema_audit_v04_sha256"]:
        raise RuntimeError("preserved v04 metric audit differs from v09 correction binding")
    v04_audit = read_json(v04_audit_path)
    if v04_audit.get("all_computed_condition_metric_fields_exact") is not True or v04_audit.get("feature_cache_root_sha256") != cache_seal["root_sha256"]:
        raise RuntimeError("v04 terminal metric-schema audit is not a valid inherited parent")
    metric_audit = dict(v04_audit)
    metric_audit["audit_id"] = "FAS_S09_METRIC_SCHEMA_AUDIT_V09_INHERITED"
    metric_audit["source_run_id"] = "fas-s09-depthwise-decision-subspace-emergence-v04"
    metric_audit["source_audit_sha256"] = sha256_file(v04_audit_path)[0]
    metric_audit["v09_terminal_reproduction_required"] = True
    metric_audit_path = RUN_ROOT / "metric-schema-audit-v09.json"

    geometry_audit_path = RUN_ROOT / "geometry-semantics-audit-v09.json"
    geometry_audit = read_json(geometry_audit_path)
    if geometry_audit.get("disposition") != "RUNTIME_SCALER_PRECISION_CORRECTION_QUALIFIED":
        raise RuntimeError("v09 geometry-semantics audit has not passed")

    snapshot = copy_protocol_snapshot(protocol)
    snapshot_check = verify_sealed_tree(snapshot, snapshot / "seals" / "protocol-seal-v09.json", protocol["root_sha256"])
    write_json(metric_audit_path, metric_audit)

    parent_roots = {
        "S01_2_CONSTRUCTION": bound["S01_2_construction_root_sha256"],
        "S01_2_EXTRACTION_RESULT": bound["S01_2_extraction_result_root_sha256"],
        "S01_2_FEATURE_CACHE": bound["S01_2_feature_cache_root_sha256"],
        "S01_3_LINEAR_ACCESSIBILITY": bound["S01_3_result_root_sha256"],
        "S08_S01_ANALYSIS": bound["S08_S01_analysis_root_sha256"],
    }
    receipt = {
        "receipt_id": "FAS_S09_V09_ANALYSIS_PARENT_RECEIPT",
        "project_protocol_root_sha256": protocol["root_sha256"],
        "v04_project_protocol_root_sha256": v04_parent["protocol_root_sha256"],
        "v04_preflight_root_sha256": v04_parent["preflight_root_sha256"],
        "v05_failed_protocol_root_sha256": v05_protocol["root_sha256"],
        "v05_failed_protocol_seal_file_sha256": sha256_file(v05_protocol_path)[0],
        "v05_read_only_failure_sha256": sha256_file(v05_failure_path)[0],
        "v06_failed_protocol_root_sha256": v06_protocol["root_sha256"],
        "v06_failed_protocol_seal_file_sha256": sha256_file(v06_protocol_path)[0],
        "v06_preflight_root_sha256": v06_preflight["root_sha256"],
        "v06_terminal_gate_failure_sha256": sha256_file(v06_failure_path)[0],
        "v06_terminal_probe_states": {
            surface: CORRECTION["failure_artifacts"][f"{surface}_terminal_probe_state_v06_sha256"]
            for surface in ("M", "F")
        },
        "v07_failed_protocol_root_sha256": v07_protocol["root_sha256"],
        "v07_failed_protocol_seal_file_sha256": sha256_file(v07_protocol_path)[0],
        "v07_preflight_failure_sha256": sha256_file(v07_failure_path)[0],
        "v08_failed_protocol_root_sha256": v08_protocol["root_sha256"],
        "v08_failed_protocol_seal_file_sha256": sha256_file(v08_protocol_path)[0],
        "v08_preflight_root_sha256": v08_preflight["root_sha256"],
        "v08_analysis_failure_sha256": sha256_file(v08_failure_path)[0],
        "v08_fit_state_manifest_sha256": sha256_file(fit_manifest_path)[0],
        "v08_fit_state_root_sha256": fit_manifest["root_sha256"],
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
    receipt_path = RUN_ROOT / "parent-verification-receipt-v09.json"
    write_json(receipt_path, receipt)

    included = [path for path in (RUN_ROOT / "inputs").rglob("*") if path.is_file()]
    included.extend(path for path in (RUN_ROOT / "history-v04").rglob("*") if path.is_file())
    included.extend(path for path in (RUN_ROOT / "history-v05").rglob("*") if path.is_file())
    included.extend(path for path in (RUN_ROOT / "history-v06").rglob("*") if path.is_file())
    included.extend(path for path in (RUN_ROOT / "history-v07").rglob("*") if path.is_file())
    included.extend(path for path in (RUN_ROOT / "history-v08").rglob("*") if path.is_file())
    included.extend([cache_seal_path, recovery_path, metric_audit_path, geometry_audit_path, receipt_path])
    entries = [entry_for(path, RUN_ROOT) for path in included]
    entries.sort(key=lambda item: item["path"])
    preflight_root = tree_root(entries)
    write_json(RUN_ROOT / "seals" / "preflight-seal-v09.json", {
        "seal_id": "FAS_S09_ANALYSIS_PREFLIGHT_SEAL_V09",
        "entries": entries,
        "root_sha256": preflight_root,
        "protocol_root_sha256": protocol["root_sha256"],
        "feature_cache_root_sha256": cache_seal["root_sha256"],
        "geometry_semantics_audit_sha256": receipt["geometry_semantics_audit_sha256"],
        "v04_history_project_root_sha256": v04_protocol["root_sha256"],
        "v04_history_preflight_root_sha256": v04_preflight["root_sha256"],
        "v06_history_protocol_root_sha256": v06_protocol["root_sha256"],
        "v06_history_preflight_root_sha256": v06_preflight["root_sha256"],
        "v07_history_protocol_root_sha256": v07_protocol["root_sha256"],
        "v08_history_protocol_root_sha256": v08_protocol["root_sha256"],
        "v08_history_preflight_root_sha256": v08_preflight["root_sha256"],
        "model_loaded": False,
        "probe_fitting_performed": False,
    })
    print(f"analysis_preflight_v09=PASS root_sha256={preflight_root} entries={len(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
