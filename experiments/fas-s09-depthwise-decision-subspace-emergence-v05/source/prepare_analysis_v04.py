from __future__ import annotations

from pathlib import Path
from typing import Any

from s09_common import RUN_ROOT, entry_for, read_json, sha256_file, tree_root, write_json


def main() -> int:
    contract = read_json(Path(__file__).resolve().parents[1] / "contracts" / "s09-analysis-contract-v04.json")
    if (RUN_ROOT / "seals" / "preflight-seal-v04.json").exists() or (RUN_ROOT / "parent-verification-receipt-v04.json").exists():
        raise RuntimeError("v04 analysis preflight already exists; refusing overwrite")
    snapshot = RUN_ROOT / "inputs" / "project-snapshot"
    protocol = read_json(snapshot / "seals" / "protocol-seal-v04.json")
    protocol_entries = [entry_for(snapshot.joinpath(*item["path"].split("/")), snapshot) for item in protocol["entries"]]
    protocol_entries.sort(key=lambda item: item["path"])
    if protocol_entries != protocol["entries"] or tree_root(protocol_entries) != protocol["root_sha256"]:
        raise RuntimeError("v04 project snapshot differs from its protocol seal")

    cache_seal = read_json(RUN_ROOT / "recovery-feature-cache-seal-v03.json")
    recovery = read_json(RUN_ROOT / "recovery-extraction-receipt-v03.json")
    bound = contract["inputs"]
    if cache_seal.get("root_sha256") != bound["recovered_feature_cache_root_sha256"] or recovery.get("feature_cache_root_sha256") != cache_seal.get("root_sha256"):
        raise RuntimeError("v03 recovered cache root differs from v04 parent binding")
    if sha256_file(RUN_ROOT / "recovery-extraction-receipt-v03.json")[0] != bound["recovery_receipt_sha256"]:
        raise RuntimeError("v03 recovery receipt bytes differ from v04 parent binding")
    if sha256_file(RUN_ROOT / "recovery-feature-cache-seal-v03.json")[0] != bound["recovery_cache_seal_file_sha256"]:
        raise RuntimeError("v03 recovery cache seal bytes differ from v04 parent binding")
    v03_seal = read_json(RUN_ROOT / "history-v03" / "seals" / "preflight-seal-v03.json")
    if v03_seal.get("root_sha256") != "53fe2f5c0be78ec1e35a48b6f0c9058ce3604ad3bfdfd20edfdf9855e8f47002":
        raise RuntimeError("v03 recovery preflight root differs from its sealed run")
    v03_snapshot = RUN_ROOT / "history-v03" / "project-snapshot-v03"
    v03_protocol = read_json(v03_snapshot / "seals" / "protocol-seal-v03.json")
    v03_protocol_entries = [entry_for(v03_snapshot.joinpath(*item["path"].split("/")), v03_snapshot) for item in v03_protocol["entries"]]
    v03_protocol_entries.sort(key=lambda item: item["path"])
    if v03_protocol_entries != v03_protocol["entries"] or tree_root(v03_protocol_entries) != contract["supersedes"]["protocol_root_sha256"]:
        raise RuntimeError("v03 protocol parent snapshot failed verification")
    if sha256_file(v03_snapshot / "seals" / "protocol-seal-v03.json")[0] != contract["supersedes"]["protocol_seal_file_sha256"]:
        raise RuntimeError("v03 protocol seal file differs from v04 parent binding")
    correction = read_json(Path(__file__).resolve().parents[1] / "contracts" / "analysis-correction-record-v04.json")
    failure_path = RUN_ROOT / "history-v03" / "analysis-failure-v03.json"
    probe_path = RUN_ROOT / "history-v03" / "M-terminal-probe-state-v03.npz"
    if sha256_file(failure_path)[0] != correction["failure_artifacts"]["analysis_failure_sha256"]:
        raise RuntimeError("preserved v03 failure receipt differs from correction binding")
    if sha256_file(probe_path)[0] != correction["failure_artifacts"]["M_terminal_probe_state_sha256"]:
        raise RuntimeError("preserved v03 terminal probe differs from correction binding")
    audit = read_json(RUN_ROOT / "metric-schema-audit-v04.json")
    if audit.get("all_computed_condition_metric_fields_exact") is not True or audit.get("feature_cache_root_sha256") != cache_seal["root_sha256"]:
        raise RuntimeError("v04 metric-schema audit has not passed")

    verified_parents = {
        "S01_2_CONSTRUCTION": bound["S01_2_construction_root_sha256"],
        "S01_2_EXTRACTION_RESULT": bound["S01_2_extraction_result_root_sha256"],
        "S01_2_FEATURE_CACHE": bound["S01_2_feature_cache_root_sha256"],
        "S01_3_LINEAR_ACCESSIBILITY": bound["S01_3_result_root_sha256"],
        "S08_S01_ANALYSIS": bound["S08_S01_analysis_root_sha256"],
    }
    receipt: dict[str, Any] = {
        "receipt_id": "FAS_S09_V04_ANALYSIS_PARENT_RECEIPT",
        "project_protocol_root_sha256": protocol["root_sha256"],
        "verified_parent_roots": verified_parents,
        "v03_recovery_cache_root_sha256": cache_seal["root_sha256"],
        "v03_recovery_receipt_sha256": bound["recovery_receipt_sha256"],
        "v03_failed_analysis_preserved": True,
        "metric_schema_audit_passed": True,
        "model_loaded": False,
        "probe_fitting_performed": False,
        "fas00_access": False,
    }
    write_json(RUN_ROOT / "parent-verification-receipt-v04.json", receipt)

    included_paths = []
    for base_name in ("inputs", "history-v03"):
        included_paths.extend(path for path in (RUN_ROOT / base_name).rglob("*") if path.is_file())
    included_paths.extend(
        RUN_ROOT / name
        for name in (
            "recovery-feature-cache-seal-v03.json",
            "recovery-extraction-receipt-v03.json",
            "metric-schema-audit-v04.json",
            "parent-verification-receipt-v04.json",
        )
    )
    entries = [entry_for(path, RUN_ROOT) for path in included_paths]
    entries.sort(key=lambda item: item["path"])
    root = tree_root(entries)
    write_json(RUN_ROOT / "seals" / "preflight-seal-v04.json", {
        "seal_id": "FAS_S09_ANALYSIS_PREFLIGHT_SEAL_V04",
        "entries": entries,
        "root_sha256": root,
        "protocol_root_sha256": protocol["root_sha256"],
        "feature_cache_root_sha256": cache_seal["root_sha256"],
        "model_loaded": False,
        "probe_fitting_performed": False,
    })
    print(f"analysis_preflight_v04=PASS root_sha256={root} entries={len(entries)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
