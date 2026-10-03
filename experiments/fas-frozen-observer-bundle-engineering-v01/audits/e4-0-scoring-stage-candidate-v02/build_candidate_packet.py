from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
PROJECT = REPO / "experiments" / "fas-frozen-observer-bundle-engineering-v01"
SCRIPT_DIR = PROJECT / "source" / "scripts" / "e4_fresh_scorer_ledger_v01"
OLD_PACKET_DIR = PROJECT / "audits" / "e4-0-scoring-stage-candidate-v01"
PACKET_DIR = PROJECT / "audits" / "e4-0-scoring-stage-candidate-v02"
SPEC_PATH = PACKET_DIR / "e4-0-scoring-execution-spec-candidate-v02.json"
NATIVE_SPEC_PATH = PACKET_DIR / "kammi-local-execution-v1-candidate-v02.json"
RECEIPT_PATH = PACKET_DIR / "e4-0-scoring-candidate-receipt-v02.json"

PYTHON = Path(r"C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe")
PYTHON_DLLS = (
    PYTHON.parent / "python3.dll",
    PYTHON.parent / "python313.dll",
)
DATA_ROOT = Path(r"D:\codex-runs\fas-frozen-observer-bundle-engineering-v01")
ATTEMPT_ROOT = DATA_ROOT / "e4-0-scoring-input-v01"
OUTPUT_ROOT = DATA_ROOT / "e4-0-scoring-output-v01"
FEATURE_ROOT = DATA_ROOT / "e4-0-ledger-run-v02" / "features"
FEATURE_CACHE = FEATURE_ROOT / "V1_FINAL_POSITION.f32le"
ROW_MANIFEST = FEATURE_ROOT / "population-row-manifest-v01.jsonl"
E3_ROOT = DATA_ROOT / "e3-v02"
PANEL_SOURCE = ATTEMPT_ROOT / "ledger-inputs" / "primary-panel-e4-v01.jsonl"
INVOCATION_PATH = ATTEMPT_ROOT / "ledger-inputs" / "scoring-invocation-v01.json"
DELIVERY_PATH = ATTEMPT_ROOT / "ledger-inputs" / "panel-delivery-v01.json"

EXPECTED_OUTPUTS = [
    "score/predictions-v01.jsonl",
    "score/scored-rows-v01.jsonl",
    "score/metrics-v01.json",
    "score/bootstrap-v01.npz",
    "score/label-open-receipt-v01.json",
    "score/terminal-receipt-v01.json",
    "score/stage-seal-v01.json",
]
MAX_OUTPUT_BYTES = 382_300_160
OTHER_PERSISTENT_CAP_BYTES = 536_870_912
TEMPORARY_CAP_BYTES = 536_870_912
HOST_RAM_PEAK_CAP_BYTES = 25_769_803_776
PROJECTED_BYTES = 1_877_705_408


def digest_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def actual_source(path: Path, role: str) -> tuple[dict, dict]:
    absolute = path.resolve(strict=True)
    if absolute.is_symlink() or not absolute.is_file():
        raise RuntimeError(f"source is not a regular file: {absolute}")
    digest, size = digest_file(absolute)
    native = {"path": str(absolute), "sha256": "sha256:" + digest, "bytes": size}
    description = {**native, "role": role, "hash_read_during_packet_build": True}
    return native, description


def sealed_source(path: Path, role: str, digest: str, size: int) -> tuple[dict, dict]:
    absolute = path.resolve(strict=True) if path.exists() else path.absolute()
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.stat().st_size != size:
            raise RuntimeError(f"sealed source path/length mismatch: {path}")
    native = {"path": str(absolute), "sha256": "sha256:" + digest, "bytes": size}
    description = {
        **native, "role": role,
        "hash_read_during_packet_build": False,
        "verification": "sealed identity carried forward; KAMMI verifies bytes before launch",
    }
    return native, description


def main() -> None:
    sys.path.insert(0, str(SCRIPT_DIR))
    import ledger_adapter as adapter

    if ATTEMPT_ROOT.exists() or OUTPUT_ROOT.exists():
        raise RuntimeError("candidate attempt/output roots must remain fresh and absent")
    if not FEATURE_CACHE.is_file() or FEATURE_CACHE.stat().st_size != adapter.FEATURE_CACHE_BYTES:
        raise RuntimeError("sealed feature cache is missing or has a different byte length")
    if not ROW_MANIFEST.is_file() or ROW_MANIFEST.stat().st_size != adapter.POPULATION_ROW_MANIFEST_BYTES:
        raise RuntimeError("sealed row manifest is missing or has a different byte length")

    old_packet = json.loads((OLD_PACKET_DIR / "e4-0-scoring-execution-spec-candidate-v01.json").read_text(encoding="utf-8"))
    packet = copy.deepcopy(old_packet)
    packet["schema"] = "FAS_E4_0_SCORING_EXECUTION_SPEC_CANDIDATE_V02"
    packet["created_utc"] = datetime.now(timezone.utc).isoformat()
    packet["candidate_status"] = "CANDIDATE_ONLY_NOT_SEALED_NOT_AUTHORIZED"
    packet["authority"].update({
        "execution_grant_issued": False,
        "panel_open_authorized": False,
        "labels_opened": False,
        "real_scoring_performed": False,
        "this_document_confers_no_authority": True,
        "required_next_gate": "Chief/Kammi confirms the native execution spec and dynamic handoff mapping; a separate E4 scoring-stage authorization remains required.",
    })
    packet["ledger_and_library_handoff"]["panel_id"] = {
        "status": "RESERVED_NOT_YET_CAS_REGISTERED_OR_OPENED",
        "value": "e4-0-primary-terminal-v01",
        "source": "Chief Kammi reservation notice; registration/open requires the separate scoring authority",
    }
    if packet["ledger_and_library_handoff"]["panel_id"]["value"] != adapter.PRIMARY_PANEL_ID:
        raise RuntimeError("reserved Ledger panel ID differs from the worker's bound panel ID")
    packet["ledger_and_library_handoff"]["attempt_root"] = str(ATTEMPT_ROOT)
    packet["ledger_and_library_handoff"]["dynamic_handoff_paths"] = {
        "invocation": str(INVOCATION_PATH),
        "delivery": str(DELIVERY_PATH),
        "staged_panel": str(PANEL_SOURCE),
        "invocation_and_delivery_bytes_prebound": False,
        "reason": "authorization and exposure IDs do not exist until the separately authorized Ledger/Chief steps",
        "chief_required_action": "hash and register both handoff JSON files after creation, before worker launch",
    }
    packet["ledger_and_library_handoff"]["panel_open_event_count"] = 1
    packet["ledger_and_library_handoff"]["local_materialized_file_open_count"] = 1
    packet["ledger_and_library_handoff"]["worker_source_files"] = []

    source_native: list[dict] = []
    source_descriptions: list[dict] = []
    seen_paths: set[str] = set()

    def add_actual(path: Path, role: str) -> None:
        native, description = actual_source(path, role)
        if native["path"].casefold() not in seen_paths:
            seen_paths.add(native["path"].casefold())
            source_native.append(native)
            source_descriptions.append(description)

    def add_sealed(path: Path, role: str, digest: str, size: int) -> None:
        native, description = sealed_source(path, role, digest, size)
        if native["path"].casefold() not in seen_paths:
            seen_paths.add(native["path"].casefold())
            source_native.append(native)
            source_descriptions.append(description)

    sealed_document_identities = (
        (
            PROJECT / "contracts/e4-0-contract-v16-v09-final.json",
            "sealed E4-0 scoring contract", adapter.CONTRACT_SHA256, 146087,
        ),
        (
            PROJECT / "seals/e4-0-contract-v16-v09-seal.json",
            "sealed E4-0 contract manifest", adapter.CONTRACT_SEAL_MANIFEST_SHA256, 171220,
        ),
        (
            PROJECT / "contracts/e3-score-v02.json",
            "bound E3 score contract", "6d1c7f35a7f3405313b9b67cbebebbb1b740c7e1c670b93d5579f280a7889704", 11485,
        ),
        (
            PROJECT / "seals/e3-score-v02-seal.json",
            "bound E3 score seal manifest", "7874bd0c8e9b47973b7cae5cac44da394a6ad1113a98c80ce89d886bae729169", 4149,
        ),
        (
            E3_ROOT / "e3-v02-seal.json",
            "frozen E3 observer bundle seal", "b8dce8dc7ff2d1a1739619f1ed00444d970ccc46872bb1acca2f1e07bf31a485", 19475,
        ),
    )
    for path, role, expected_digest, expected_size in sealed_document_identities:
        native, description = actual_source(path, role)
        if (native["sha256"].removeprefix("sha256:"), native["bytes"]) != (
            expected_digest, expected_size
        ):
            raise RuntimeError(f"sealed metadata identity mismatch: {path}")
        if native["path"].casefold() not in seen_paths:
            seen_paths.add(native["path"].casefold())
            source_native.append(native)
            source_descriptions.append(description)

    for path, role in (
        (PYTHON, "Python 3.13.15 executable"),
        (PYTHON_DLLS[0], "Python runtime DLL"),
        (PYTHON_DLLS[1], "Python runtime DLL"),
        (SCRIPT_DIR / "run_scoring.py", "Ledger worker entrypoint"),
        (SCRIPT_DIR / "ledger_adapter.py", "lab-owned grant/input/scoring adapter"),
        (PROJECT / "source/scripts/e4_fresh_scorer_v04/scorer.py", "frozen E4 scoring math"),
        (PROJECT / "source/scripts/e4_fresh_scorer_v04/output_artifacts.py", "frozen E4 output/seal writer"),
    ):
        add_actual(path, role)

    add_sealed(
        FEATURE_CACHE, "read-only E4 feature cache",
        adapter.FEATURE_CACHE_SHA256, adapter.FEATURE_CACHE_BYTES,
    )
    add_sealed(
        ROW_MANIFEST, "read-only E4 feature row manifest",
        adapter.POPULATION_ROW_MANIFEST_SHA256, adapter.POPULATION_ROW_MANIFEST_BYTES,
    )
    for name, (digest, size) in sorted(adapter.E3_HEAD_FILES.items()):
        add_sealed(E3_ROOT / name, "sealed E3 observer head/scaler", digest, size)
    add_sealed(
        PANEL_SOURCE, "Chief/Kammi staged primary panel after authorized open",
        adapter.PRIMARY_LABEL_SOURCE_SHA256, adapter.PRIMARY_LABEL_SOURCE_BYTES,
    )

    python_digest, python_size = digest_file(PYTHON)
    import numpy
    import torch
    runtime = {
        "python": sys.version.split()[0],
        "python_executable": str(PYTHON.resolve(strict=True)),
        "python_executable_sha256": python_digest,
        "python_executable_bytes": python_size,
        "python_runtime_dlls": [
            {"path": str(path.resolve(strict=True)), "sha256": digest_file(path)[0], "bytes": path.stat().st_size}
            for path in PYTHON_DLLS
        ],
        "numpy": numpy.__version__,
        "numpy_import_path": str(Path(numpy.__file__).resolve()),
        "torch": torch.__version__,
        "torch_import_path": str(Path(torch.__file__).resolve()),
        "platform": "Windows 11 AMD64",
        "device": "CPU",
        "cuda_initialized_before_test": bool(torch.cuda.is_initialized()),
        "package_identity_rule": "adapter checks the exact Python, NumPy, and PyTorch versions before feature prediction",
    }
    if (runtime["python"], runtime["numpy"], runtime["torch"]) != adapter.SCORING_RUNTIME:
        raise RuntimeError("installed Python/NumPy/PyTorch runtime differs from the frozen E3 scoring runtime")
    packet["runtime"] = runtime
    packet["source_identities"] = source_descriptions
    packet["ledger_and_library_handoff"]["worker_source_files"] = source_descriptions

    command = [
        str(PYTHON.resolve(strict=True)),
        str((SCRIPT_DIR / "run_scoring.py").resolve(strict=True)),
        "--invocation", str(INVOCATION_PATH),
        "--delivery", str(DELIVERY_PATH),
        "--panel-file", str(PANEL_SOURCE),
        "--feature-cache", str(FEATURE_CACHE),
        "--row-manifest", str(ROW_MANIFEST),
        "--e3-head-root", str(E3_ROOT),
        "--output-root", str(OUTPUT_ROOT),
    ]
    native = {
        "schema": "KAMMI_LOCAL_EXECUTION_V1",
        "run_id": adapter.RUN_ID,
        "stage_id": adapter.STAGE_ID,
        "actor_id": "fabrique-e4-supervisor-v1",
        "command": command,
        "cwd": str(SCRIPT_DIR.resolve(strict=True)),
        "output_root": str(OUTPUT_ROOT),
        "expected_outputs": EXPECTED_OUTPUTS,
        "max_output_bytes": MAX_OUTPUT_BYTES,
        "timeout_seconds": 7200,
        "poll_seconds": 5,
        "source_files": source_native,
    }
    packet["native_execution_spec"] = {
        "artifact_path": str(NATIVE_SPEC_PATH.relative_to(REPO)),
        "artifact_sha256": "sha256:" + hashlib.sha256(
            json.dumps(native, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "artifact_serialization": "UTF-8 JSON, sorted keys, compact separators, no trailing newline",
        "dynamic_sidecar_paths_not_hash_bound": [str(INVOCATION_PATH), str(DELIVERY_PATH)],
        "sidecar_post_creation_audit_required": True,
        "spec": native,
    }
    packet["resource_execution_binding"] = {
        "max_output_bytes_semantics": "per expected output file, enforced by KAMMI",
        "row_output_per_file_cap_bytes": MAX_OUTPUT_BYTES,
        "other_persistent_outputs_aggregate_cap_bytes": OTHER_PERSISTENT_CAP_BYTES,
        "temporary_artifact_aggregate_cap_bytes": TEMPORARY_CAP_BYTES,
        "host_process_peak_working_set_cap_bytes": HOST_RAM_PEAK_CAP_BYTES,
        "projected_scoring_bytes_including_staged_panel": PROJECTED_BYTES,
        "formula": "2*382300160 + 536870912 + 536870912 + 39363264 = 1877705408",
        "free_space_reserve": "ceil(0.10 * live D: total bytes)",
        "current_D_free_bytes_at_candidate_build": shutil.disk_usage(Path("D:/")).free,
        "scoring_process_gpu": False,
    }
    packet["scope"]["evaluation_label_opening"] = True
    packet["scope"]["scoring"] = True
    packet["scope"]["heldout_template_label_opening"] = False
    packet["scope"]["joint_template_label_opening"] = False
    packet["synthetic_qualification"] = {
        "command": "python -m unittest -v test_adapter test_runner",
        "result": "PASS",
        "tests_passed": 11,
        "tests_failed": 0,
        "duration_seconds": 27.233,
        "actual_e4_label_bytes_read": False,
        "actual_feature_cache_bytes_read": False,
        "actual_e3_head_payload_bytes_read": False,
        "tokenizer_model_cuda_ledger_contact": False,
    }
    packet["execution_order"] = [
        "Await Chief confirmation of this candidate mapping and separate stage authorization.",
        "After authorization, Chief registers/resolves the reserved panel, opens it once, stages the exact primary bytes, and hashes/audits the dynamic handoff JSON files.",
        "KAMMI verifies its local execution spec source_files, then runs the fixed CPU command under its fenced attempt.",
        "Worker validates the authorized grant, exact invocation/delivery identities, frozen cache/manifest/heads, runtime and output preflight before primary prediction.",
        "Worker opens and hashes/parses the staged primary panel once, scores the eight frozen endpoints, writes the seven declared outputs and seals them.",
        "Independent replay remains a separate stage and authority; this candidate performs no replay.",
    ]

    native_bytes = json.dumps(native, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    NATIVE_SPEC_PATH.write_bytes(native_bytes)
    spec_bytes = (json.dumps(packet, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
    SPEC_PATH.write_bytes(spec_bytes)
    receipt = {
        "schema": "FAS_E4_0_SCORING_CANDIDATE_RECEIPT_V02",
        "status": "CANDIDATE_ONLY_NOT_SEALED_NOT_AUTHORIZED",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "spec_candidate": {
            "path": str(SPEC_PATH.relative_to(REPO)),
            "bytes": len(spec_bytes), "sha256": hashlib.sha256(spec_bytes).hexdigest(),
        },
        "native_execution_spec_candidate": {
            "path": str(NATIVE_SPEC_PATH.relative_to(REPO)),
            "bytes": len(native_bytes), "sha256": hashlib.sha256(native_bytes).hexdigest(),
            "schema": native["schema"], "source_file_count": len(source_native),
        },
        "implementation": [
            {"path": str((SCRIPT_DIR / name).relative_to(REPO)), **identity}
            for name in ("run_scoring.py", "ledger_adapter.py", "test_adapter.py", "test_runner.py", "README.md")
            for identity in [{"bytes": (SCRIPT_DIR / name).stat().st_size, "sha256": digest_file(SCRIPT_DIR / name)[0]}]
        ],
        "qualification": {
            "kind": "synthetic_only",
            "command": "Python 3.13.15 -m unittest -v test_adapter test_runner",
            "result": "PASS",
            "tests_passed": 11,
            "tests_failed": 0,
            "duration_seconds": 27.233,
            "actual_e4_label_bytes_read": False,
            "actual_feature_cache_bytes_read": False,
            "actual_e3_head_payload_bytes_read": False,
            "feature_cache_and_manifest_path_metadata_checked": True,
            "e3_head_path_metadata_checked": True,
            "tokenizer_model_cuda_ledger_contact": False,
            "final_suite_result_pending": False,
        },
        "current_state": {
            "panel_id_reserved": "e4-0-primary-terminal-v01",
            "panel_cas_registration": False,
            "panel_exposure_count": 0,
            "execution_grant_issued": False,
            "labels_opened": False,
            "real_scoring_performed": False,
            "output_root_exists_at_build": OUTPUT_ROOT.exists(),
        },
        "native_schema": {
            "fields_exact": [
                "schema", "run_id", "stage_id", "actor_id", "command", "cwd",
                "output_root", "expected_outputs", "max_output_bytes", "timeout_seconds",
                "poll_seconds", "source_files",
            ],
            "dynamic_invocation_delivery_excluded_from_source_files": True,
            "dynamic_sidecar_hash_audit_owner": "Chief Kammi after authorization/exposure and before worker launch",
        },
    }
    RECEIPT_PATH.write_text(json.dumps(receipt, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
