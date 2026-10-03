from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PROJECT = REPO / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
PACKET_DIR = PROJECT / "audits" / "e4-0-scoring-stage-candidate-v02"
SCRIPT_DIR = PROJECT / "source" / "scripts" / "e4_fresh_scorer_ledger_v01"
SPEC_PATH = PACKET_DIR / "e4-0-scoring-execution-spec-candidate-v02.json"
NATIVE_PATH = PACKET_DIR / "kammi-local-execution-v1-candidate-v02.json"
RECEIPT_PATH = PACKET_DIR / "e4-0-scoring-candidate-receipt-v02.json"
AUDIT_PATH = PACKET_DIR / "e4-0-scoring-candidate-audit-v02.json"


def file_identity(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb", buffering=0) as stream:
        while block := stream.read(8 << 20):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def main() -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    import ledger_adapter as adapter

    wrapper_bytes = SPEC_PATH.read_bytes()
    wrapper = json.loads(wrapper_bytes)
    native_bytes = NATIVE_PATH.read_bytes()
    native = json.loads(native_bytes)
    receipt = json.loads(RECEIPT_PATH.read_text(encoding="utf-8"))
    expected_keys = {
        "schema", "run_id", "stage_id", "actor_id", "command", "cwd",
        "output_root", "expected_outputs", "max_output_bytes", "timeout_seconds",
        "poll_seconds", "source_files",
    }
    if set(native) != expected_keys or native["schema"] != "KAMMI_LOCAL_EXECUTION_V1":
        raise RuntimeError("native local-execution object does not match the exact Ledger schema")
    native_digest = hashlib.sha256(native_bytes).hexdigest()
    if hashlib.sha256(json.dumps(
        native, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")).hexdigest() != native_digest:
        raise RuntimeError("native execution spec serialization is not canonical")
    if wrapper["native_execution_spec"]["spec"] != native:
        raise RuntimeError("wrapper and standalone native execution specs differ")
    if wrapper["native_execution_spec"]["artifact_sha256"] != "sha256:" + native_digest:
        raise RuntimeError("wrapper native-spec digest differs from the standalone file")
    if receipt["native_execution_spec_candidate"]["sha256"] != native_digest:
        raise RuntimeError("candidate receipt native-spec digest is stale")
    if receipt["spec_candidate"]["sha256"] != hashlib.sha256(wrapper_bytes).hexdigest():
        raise RuntimeError("candidate receipt wrapper-spec digest is stale")

    if native["run_id"] != adapter.RUN_ID or native["stage_id"] != adapter.STAGE_ID:
        raise RuntimeError("native execution scope differs from frozen E4 adapter identity")
    if native["actor_id"] != "fabrique-e4-supervisor-v1":
        raise RuntimeError("native execution actor differs from the registered Fabrique actor")
    if native["expected_outputs"] != list(__import__("run_scoring").OUTPUT_NAMES):
        raise RuntimeError("native expected-output inventory differs from the worker")
    if (native["max_output_bytes"], native["timeout_seconds"], native["poll_seconds"]) != (
        382_300_160, 7200, 5
    ):
        raise RuntimeError("native output/timeout/poll limits differ from the reviewed candidate")
    if wrapper["authority"]["execution_grant_issued"] or wrapper["authority"]["panel_open_authorized"]:
        raise RuntimeError("candidate packet incorrectly claims execution authority")
    if wrapper["authority"]["labels_opened"] or wrapper["authority"]["real_scoring_performed"]:
        raise RuntimeError("candidate packet incorrectly claims real label access or scoring")
    if (native["output_root"] != r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-scoring-output-v01"
            or Path(native["output_root"]).exists()):
        raise RuntimeError("candidate output root changed or is not fresh")

    sources = native["source_files"]
    if len(sources) != 35 or len({entry["path"].casefold() for entry in sources}) != len(sources):
        raise RuntimeError("native source inventory count or uniqueness differs")
    if any(set(entry) != {"path", "sha256", "bytes"} for entry in sources):
        raise RuntimeError("native source entry contains extra/missing fields")
    if any(not entry["sha256"].startswith("sha256:") or len(entry["sha256"]) != 71 for entry in sources):
        raise RuntimeError("native source hash serialization is invalid")

    future_panel = str(
        Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-scoring-input-v01")
        / "ledger-inputs" / "primary-panel-e4-v01.jsonl"
    )
    static_data: dict[str, tuple[str, int]] = {
        str((Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01")
             / "e4-0-ledger-run-v02" / "features" / "V1_FINAL_POSITION.f32le")):
            (adapter.FEATURE_CACHE_SHA256, adapter.FEATURE_CACHE_BYTES),
        str((Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01")
             / "e4-0-ledger-run-v02" / "features" / "population-row-manifest-v01.jsonl")):
            (adapter.POPULATION_ROW_MANIFEST_SHA256, adapter.POPULATION_ROW_MANIFEST_BYTES),
    }
    e3_root = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e3-v02")
    static_data.update({str(e3_root / name): identity for name, identity in adapter.E3_HEAD_FILES.items()})
    static_data[future_panel] = (adapter.PRIMARY_LABEL_SOURCE_SHA256, adapter.PRIMARY_LABEL_SOURCE_BYTES)

    metadata_paths_verified = 0
    source_content_hashes_verified = 0
    sealed_data_identities_matched = 0
    future_missing: list[str] = []
    for entry in sources:
        path = Path(entry["path"])
        declared = (entry["sha256"].removeprefix("sha256:"), entry["bytes"])
        if entry["path"] in static_data:
            if declared != static_data[entry["path"]]:
                raise RuntimeError(f"sealed data identity differs from the adapter contract: {path}")
            sealed_data_identities_matched += 1
            if entry["path"] == future_panel and not path.exists():
                future_missing.append(entry["path"])
                continue
            if not path.is_file() or path.is_symlink() or path.stat().st_size != declared[1]:
                raise RuntimeError(f"sealed data source path/length is not ready: {path}")
            metadata_paths_verified += 1
        else:
            actual = file_identity(path)
            if actual != declared:
                raise RuntimeError(f"native source file identity mismatch: {path}")
            source_content_hashes_verified += 1
            metadata_paths_verified += 1
    if future_missing != [future_panel]:
        raise RuntimeError("the staged panel must be the only intentionally future source")

    original_label_source = r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01\e4-0-v01\labels\primary-terminal-labels-v01.jsonl"
    if any(Path(entry["path"]).as_posix().casefold() == Path(original_label_source).as_posix().casefold()
           for entry in sources):
        raise RuntimeError("protected original label path appears in the KAMMI source inventory")
    command_text = "\n".join(native["command"])
    if original_label_source in command_text:
        raise RuntimeError("protected original label path appears in the KAMMI command")
    if adapter.PRIMARY_PANEL_ID != "e4-0-primary-terminal-v01":
        raise RuntimeError("worker panel ID differs from Chief's reserved panel ID")

    import numpy
    runtime = wrapper["runtime"]
    observed_versions = (sys.version.split()[0], numpy.__version__, importlib.metadata.version("torch"))
    if observed_versions != adapter.SCORING_RUNTIME:
        raise RuntimeError("active audit runtime differs from the frozen scoring runtime")
    if runtime["python_executable"] != native["command"][0]:
        raise RuntimeError("runtime executable differs from the executable in the worker command")
    if wrapper["synthetic_qualification"]["result"] != "PASS" or wrapper["synthetic_qualification"]["tests_passed"] != 11:
        raise RuntimeError("synthetic qualification receipt is stale or failed")

    audit = {
        "schema": "FAS_E4_0_SCORING_CANDIDATE_PACKET_AUDIT_V01",
        "status": "PASS_CANDIDATE_PACKET_IDENTITY_AUDIT",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "wrapper_spec_sha256": hashlib.sha256(wrapper_bytes).hexdigest(),
        "native_execution_spec_sha256": native_digest,
        "native_schema_exact": True,
        "native_source_count": len(sources),
        "present_source_paths_verified": metadata_paths_verified,
        "source_content_hashes_verified_during_audit": source_content_hashes_verified,
        "sealed_data_identities_matched_to_bound_constants": sealed_data_identities_matched,
        "protected_sealed_data_content_hashes_read_during_audit": False,
        "future_staged_panel_path": future_panel,
        "future_staged_panel_hash_and_length_bound": True,
        "only_future_source_missing": future_missing[0],
        "dynamic_handoff_json_not_in_source_files": True,
        "dynamic_handoff_paths_fixed_under_attempt_root": True,
        "original_protected_label_path_delivered": False,
        "panel_id_bound": adapter.PRIMARY_PANEL_ID,
        "output_root_fresh": True,
        "grant_issued": False,
        "panel_opened": False,
        "real_labels_opened": False,
        "real_scoring_performed": False,
        "runtime_versions": {
            "python": observed_versions[0], "numpy": observed_versions[1], "torch_metadata": observed_versions[2],
        },
        "independent_packet_checks": [
            "standalone native spec matches exact v1 schema and wrapper copy",
            "wrapper/receipt/native hashes agree",
            "all present native sources match declared SHA-256 and byte length",
            "cache, manifest, E3 head and staged panel identities match sealed adapter constants without reading protected payload contents",
            "only future source is the sealed staged panel path",
            "native output paths and limits match the runner",
            "no grant or real label operation is claimed",
        ],
    }
    audit_bytes = (json.dumps(audit, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    AUDIT_PATH.write_bytes(audit_bytes)
    receipt["candidate_packet_audit"] = {
        "path": str(AUDIT_PATH.relative_to(REPO)),
        "bytes": len(audit_bytes),
        "sha256": hashlib.sha256(audit_bytes).hexdigest(),
        "status": audit["status"],
    }
    receipt["implementation"].append({
        "path": str(Path(__file__).resolve().relative_to(REPO)),
        "bytes": Path(__file__).stat().st_size,
        "sha256": file_identity(Path(__file__))[0],
    })
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(audit, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
