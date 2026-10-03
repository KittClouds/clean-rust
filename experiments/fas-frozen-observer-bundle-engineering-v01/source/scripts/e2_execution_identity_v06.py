from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


PROJECT = "fas-frozen-observer-bundle-engineering-v01"
PROJECT_REL = f"experiments/{PROJECT}"
EXPECTED_E0_V08_ROOT = "a782f0baaf04b97c00c64f5c63a5b954ce0df1b2d1cf1665833c374d568a9bf4"
EXPECTED_E1_V04_ROOT = "6ba77a899363651e3ba119b005f59a22e86f011f83c86b873857cd3f9ab64b03"
EXPECTED_E2_V01_ROOT = "0ff309d833cd87017f7384247e4420a508f582ad9f375c5637f586d73b703f4c"
EXPECTED_REFERENCE_SHA256 = "8eb80df5f73e761fe6c025fc1c66abef2027d639b6c14f56d4177d6e6a7a45a4"
EXPECTED_REFERENCE_BYTES = 872_415_232
EXPECTED_WAIT_SHA256 = "b926124f9aa55b1b9fec2d794d0ac6a7a808128d43df9d53babb6cf143454b80"
EXPECTED_S12_PROCESS = {
    "pid": 34332,
    "executable": r"C:\Users\shuga\AppData\Local\Programs\Python\Python313\python.exe",
    "script": r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v02\source\run_s12_v02.py",
    "creation_time_local": "2026-09-25T20:08:43",
}


@dataclass(frozen=True)
class ExecutionIdentity:
    seal_root_sha256: str
    freeze_contract_sha256: str
    e1_root_sha256: str
    extractor_sha256: str
    verifier_sha256: str
    representation_abi_sha256: str
    comparator_sha256: str


@dataclass(frozen=True)
class PreflightResult:
    identity: ExecutionIdentity
    abi: dict[str, Any]
    equivalence: dict[str, Any]
    checks: dict[str, bool]
    observations: dict[str, Any]
    repo_root: Path
    e0_seal_path: Path
    e1_run_root: Path
    panel_input_path: Path
    row_manifest_path: Path
    protocol_path: Path
    abi_path: Path
    extractor_path: Path
    output_root: Path
    reference_cache_path: Path
    model_snapshot_root: Path
    tokenizer_snapshot_root: Path
    tokenizer_manifest_path: Path
    model_asset_manifest_path: Path
    comparator_path: Path


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


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries, key=lambda row: row["path"]):
        digest.update(f'{entry["path"]}\t{entry["bytes"]}\t{entry["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def safe_relative(root: Path, raw_path: str) -> Path:
    relative = Path(raw_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"sealed path escapes its root: {raw_path}")
    resolved_root = root.resolve(strict=True)
    resolved_path = (resolved_root / relative).resolve(strict=True)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as error:
        raise RuntimeError(f"sealed path resolves outside its root: {raw_path}") from error
    return resolved_path


def verify_seal(root: Path, seal_path: Path, expected_root: str | None = None) -> dict[str, Any]:
    seal = read_json(seal_path)
    entries = seal.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError(f"seal has no usable membership list: {seal_path}")
    actual_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in entries:
        raw_path = entry.get("path")
        if not isinstance(raw_path, str) or raw_path in seen:
            raise RuntimeError(f"seal has an invalid or duplicate member path: {raw_path!r}")
        seen.add(raw_path)
        path = safe_relative(root, raw_path)
        digest, size = sha256_file(path)
        if digest != entry.get("sha256") or size != entry.get("bytes"):
            raise RuntimeError(f"sealed member identity mismatch: {raw_path}")
        actual_entries.append({"path": Path(raw_path).as_posix(), "bytes": size, "sha256": digest})
    computed_root = tree_root(actual_entries)
    if computed_root != seal.get("root_sha256") or len(entries) != seal.get("entry_count"):
        raise RuntimeError(f"seal root or member count failed recomputation: {seal_path}")
    if expected_root is not None and computed_root != expected_root:
        raise RuntimeError(f"seal root differs from the bound predecessor: {seal_path}")
    return seal


def member_path(root: Path, seal: dict[str, Any], manifest_field: str) -> tuple[Path, str, int]:
    raw_path = seal.get(manifest_field)
    if not isinstance(raw_path, str):
        raise RuntimeError(f"seal has no usable {manifest_field} reference")
    path = safe_relative(root, raw_path)
    relative = Path(raw_path).as_posix()
    entry = next((row for row in seal["entries"] if row.get("path") == relative), None)
    if entry is None:
        raise RuntimeError(f"referenced sealed artifact is not a member: {manifest_field}")
    digest, size = sha256_file(path)
    if digest != entry.get("sha256") or size != entry.get("bytes"):
        raise RuntimeError(f"referenced sealed artifact differs from its member identity: {manifest_field}")
    return path, digest, size


def normalize_e0_manifest(
    repo_root: Path,
    e0_seal_path: Path,
    expected_root: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any], ExecutionIdentity, dict[str, Any]]:
    """Derive execution identity from verified contents, not metadata field spelling."""
    seal = verify_seal(repo_root, e0_seal_path, expected_root)
    if seal.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 seal permits model contact")
    freeze_path, freeze_hash, _ = member_path(repo_root, seal, "freeze_contract_path")
    freeze = read_json(freeze_path)
    if freeze.get("model_contact_authorized") is not False or freeze.get("tokenizer_contact_authorized") is not False:
        raise RuntimeError("E0 freeze contract does not keep preflight authority closed")
    abi_path, abi_hash, _ = member_path(repo_root, seal, "representation_abi_path")
    identity = ExecutionIdentity(
        seal_root_sha256=seal["root_sha256"],
        freeze_contract_sha256=freeze_hash,
        e1_root_sha256=seal.get("e1_v04_root_sha256", ""),
        extractor_sha256=freeze.get("extractor_source_sha256", ""),
        verifier_sha256=freeze.get("execution_identity_verifier_sha256", ""),
        representation_abi_sha256=abi_hash,
        comparator_sha256=freeze.get("representation_equivalence_gate", {}).get("reference_cache_sha256", ""),
    )
    if not all((identity.seal_root_sha256, identity.freeze_contract_sha256, identity.e1_root_sha256,
                identity.extractor_sha256, identity.representation_abi_sha256, identity.comparator_sha256)):
        raise RuntimeError("normalized E0 execution identity is incomplete")
    return seal, freeze, identity, {
        "manifest_seal_id": seal.get("seal_id"),
        "manifest_status": seal.get("status"),
        "manifest_freeze_id": seal.get("freeze_id"),
        "contract_freeze_id": freeze.get("freeze_id"),
        "freeze_contract_path": seal.get("freeze_contract_path"),
    }


def resolve_inside(root: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve(strict=True)
    return safe_relative(root, value)


def verify_frozen_e2_protocol(protocol: dict[str, Any]) -> None:
    if protocol.get("protocol_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_RUN_V06":
        raise RuntimeError("E2 protocol identity is not v06")
    authority = protocol.get("authority", {})
    if any(authority.get(name) is not False for name in (
        "model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized",
        "observer_fitting_authorized", "evaluation_scoring_authorized",
    )):
        raise RuntimeError("E2 v06 protocol is not in its frozen unauthorized state")
    if authority.get("successful_e2_does_not_authorize_e3") is not True:
        raise RuntimeError("E2 v06 protocol does not preserve the E3 boundary")
    equivalence = protocol.get("representation_equivalence", {})
    if (
        equivalence.get("required") is not True
        or equivalence.get("reference_cache_sha256") != EXPECTED_REFERENCE_SHA256
        or equivalence.get("reference_cache_bytes") != EXPECTED_REFERENCE_BYTES
        or equivalence.get("gate") != "exact SHA-256 equality and exact byte length equality"
    ):
        raise RuntimeError("E2 v06 protocol does not bind the exact preserved comparator gate")


def verify_wait_receipt(protocol: dict[str, Any], repo_root: Path) -> tuple[dict[str, Any], str]:
    paths = protocol["preflight_paths"]
    receipt_path = resolve_inside(repo_root, paths["concurrent_run_wait_receipt_path"])
    receipt_hash, _ = sha256_file(receipt_path)
    if receipt_hash != protocol["wait_gate"].get("receipt_sha256") or receipt_hash != EXPECTED_WAIT_SHA256:
        raise RuntimeError("concurrent-run wait receipt hash differs from the frozen identity")
    receipt = read_json(receipt_path)
    if receipt.get("status") != protocol["wait_gate"].get("receipt_status"):
        raise RuntimeError("concurrent-run wait receipt did not satisfy the explicitly frozen wait state")
    if receipt.get("model_contact_performed_by_waiter") is not False:
        raise RuntimeError("wait receipt reports model contact by the waiter")
    expected = protocol["wait_gate"].get("target_process", {})
    observed = receipt.get("exact_bound_identity_observed_during_wait", {})
    bound = receipt.get("bound_process", {})
    for key, value in expected.items():
        if bound.get(key) != value or observed.get(key) != value:
            raise RuntimeError(f"wait receipt does not bind the expected process field: {key}")
    if receipt.get("matching_script_processes_at_final_sample") != []:
        raise RuntimeError("wait receipt ended while the named concurrent workload remained active")
    if receipt.get("stable_absent_samples") != 2 or receipt.get("sample_interval_seconds", 0) < 30:
        raise RuntimeError("wait receipt lacks two stable-absence samples separated by 30 seconds")
    return receipt, receipt_hash


def verify_live_wait_target_absent(protocol: dict[str, Any]) -> list[dict[str, Any]]:
    if os.name != "nt":
        raise RuntimeError("the frozen live-process check requires Windows process identity APIs")
    target = protocol["wait_gate"]["target_process"]["script"]
    escaped = target.replace("'", "''")
    command = (
        f"$needle = '{escaped}'; "
        "$matches = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.IndexOf($needle, [StringComparison]::OrdinalIgnoreCase) -ge 0 }; "
        "@($matches | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,CreationDate) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True, capture_output=True, text=True, timeout=20,
    )
    payload = result.stdout.strip()
    matches = json.loads(payload) if payload else []
    if isinstance(matches, dict):
        matches = [matches]
    if matches:
        raise RuntimeError(f"the frozen concurrent script is currently active: {matches}")
    return []


def verify_reference_cache(path: Path, expected_hash: str, expected_size: int) -> tuple[str, int]:
    digest, size = sha256_file(path.resolve(strict=True))
    if digest != expected_hash or size != expected_size:
        raise RuntimeError("preserved E2 v01 comparator failed its pinned SHA-256 or byte-length check")
    return digest, size


def verify_model_and_tokenizer_assets(
    model_root: Path, model_manifest_path: Path, tokenizer_root: Path, tokenizer_manifest_path: Path,
    abi: dict[str, Any],
) -> dict[str, Any]:
    if not model_root.is_dir() or not tokenizer_root.is_dir():
        raise RuntimeError("pinned local model or tokenizer snapshot directory is missing")
    model_manifest_hash, _ = sha256_file(model_manifest_path.resolve(strict=True))
    if model_manifest_hash != abi.get("model_asset_manifest_sha256"):
        raise RuntimeError("pinned model asset manifest differs from the ABI")
    model_manifest = read_json(model_manifest_path)
    if model_manifest.get("resolved_revision") != abi.get("model_revision"):
        raise RuntimeError("model asset manifest resolved revision differs from the ABI")
    model_assets = {Path(item["path"]).name: item for item in model_manifest.get("assets", [])}
    for filename, field in (("config.json", "model_config_sha256"), ("model.safetensors", "model_weights_sha256")):
        path = model_root / filename
        digest, size = sha256_file(path.resolve(strict=True))
        expected = abi.get(field)
        manifest_item = model_assets.get(filename)
        if digest != expected or manifest_item is None or digest != manifest_item.get("sha256") or size != manifest_item.get("bytes"):
            raise RuntimeError(f"pinned model asset identity mismatch: {filename}")
        manifest_asset = (model_manifest_path.parent / manifest_item["path"]).resolve(strict=True)
        if manifest_asset != path.resolve(strict=True):
            raise RuntimeError(f"model asset manifest path does not identify the loaded snapshot file: {filename}")

    tokenizer_manifest_hash, _ = sha256_file(tokenizer_manifest_path.resolve(strict=True))
    if tokenizer_manifest_hash != abi.get("tokenizer_assets_manifest_sha256"):
        raise RuntimeError("pinned tokenizer asset manifest differs from the ABI")
    tokenizer_manifest = read_json(tokenizer_manifest_path)
    if tokenizer_manifest.get("resolved_commit") != abi.get("tokenizer_revision"):
        raise RuntimeError("tokenizer asset manifest revision differs from the ABI")
    tokenizer_files = tokenizer_manifest.get("loaded_snapshot_files", [])
    if not tokenizer_files:
        raise RuntimeError("tokenizer manifest has no loaded-file identity list")
    for item in tokenizer_files:
        path = (tokenizer_root / item["path"]).resolve(strict=True)
        path.relative_to(tokenizer_root.resolve(strict=True))
        digest, size = sha256_file(path)
        if digest != item.get("sha256") or size != item.get("bytes"):
            raise RuntimeError(f"pinned tokenizer asset changed: {item['path']}")
    return {
        "model_asset_manifest_sha256": model_manifest_hash,
        "model_config_sha256": abi["model_config_sha256"],
        "model_weights_sha256": abi["model_weights_sha256"],
        "tokenizer_manifest_sha256": tokenizer_manifest_hash,
        "tokenizer_loaded_file_count": len(tokenizer_files),
    }


def verify_runtime_metadata(abi: dict[str, Any]) -> dict[str, str]:
    expected = abi.get("runtime_versions", {})
    observed = {"python": platform.python_version()}
    for package in ("torch", "transformers", "tokenizers", "huggingface_hub", "safetensors", "numpy"):
        observed[package] = importlib.metadata.version(package)
    cuda_match = re.search(r"\+cu(\d+)$", observed["torch"])
    if cuda_match is None:
        raise RuntimeError("installed PyTorch distribution does not identify a CUDA runtime build")
    cuda_digits = cuda_match.group(1)
    observed["cuda_runtime"] = f"{int(cuda_digits[:-1])}.{cuda_digits[-1]}"
    gpu_result = subprocess.run(
        ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
        check=True, capture_output=True, text=True, timeout=20,
    )
    gpu_names = [line.strip() for line in gpu_result.stdout.splitlines() if line.strip()]
    if len(gpu_names) != 1:
        raise RuntimeError(f"expected one visible GPU device while checking runtime metadata, observed {gpu_names}")
    observed["expected_device_0"] = gpu_names[0]
    if observed != expected:
        raise RuntimeError(f"runtime distribution metadata mismatch: expected={expected}, observed={observed}")
    return observed


def verify_panel_row_identity(run_root: Path, e1_seal: dict[str, Any], paths: dict[str, Any], expected_rows: int) -> dict[str, Any]:
    input_path = resolve_inside(run_root, paths["panel_inputs_relative_path"])
    manifest_path = resolve_inside(run_root, paths["row_manifest_relative_path"])
    for path in (input_path, manifest_path):
        relative = path.relative_to(run_root.resolve(strict=True)).as_posix()
        entry = next((row for row in e1_seal["entries"] if row.get("path") == relative), None)
        if entry is None:
            raise RuntimeError(f"E1 panel input is not a member of its verified seal: {relative}")
    count = 0
    with input_path.open("r", encoding="utf-8") as inputs, manifest_path.open("r", encoding="utf-8") as rows:
        for index, (input_line, row_line) in enumerate(zip(inputs, rows, strict=True)):
            record = json.loads(input_line)
            expected = json.loads(row_line)
            if set(record) != {"row_id", "quartet_id", "variant_id", "input_text"}:
                raise RuntimeError("sealed panel input contains unexpected fields or labels")
            if (
                expected.get("row_index") != index
                or record.get("row_id") != expected.get("row_id")
                or record.get("quartet_id") != expected.get("quartet_id")
                or record.get("variant_id") != expected.get("variant_id")
            ):
                raise RuntimeError(f"panel row identity/order mismatch at row {index}")
            count += 1
    if count != expected_rows:
        raise RuntimeError(f"panel row count mismatch: {count} != {expected_rows}")
    return {"row_count": count, "ordered_identity_match": True, "labels_opened": False}


def system_memory_status() -> dict[str, int] | None:
    if os.name != "nt":
        return None
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]
    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise RuntimeError("Windows host-memory preflight query failed")
    return {"total_bytes": int(status.ullTotalPhys), "available_bytes": int(status.ullAvailPhys)}


def verify_resource_preflight(freeze: dict[str, Any], output_root: Path) -> dict[str, Any]:
    limits = freeze["resource_limits"]
    drive = output_root.drive
    if not drive:
        raise RuntimeError("feature output target has no drive volume")
    usage = shutil.disk_usage(drive + "\\")
    projected = int(limits["projected_peak_bytes"])
    reserve = int(projected * float(limits["minimum_free_space_after_projected_peak_fraction"]))
    required_free = projected + reserve
    if usage.free < required_free:
        raise RuntimeError(f"disk preflight failed: free={usage.free}, required={required_free}")
    if output_root.exists():
        raise RuntimeError("E2 v06 output root already exists; preserving prior artifacts")
    memory = system_memory_status()
    if memory is not None and memory["total_bytes"] < int(limits["peak_host_ram_bytes_max"]):
        raise RuntimeError("host RAM capacity is below the frozen E2 peak-host-memory envelope")
    command = [
        "nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=20)
    gpu_rows = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if len(gpu_rows) != 1:
        raise RuntimeError(f"expected one visible GPU device, observed {gpu_rows}")
    fields = [field.strip() for field in gpu_rows[0].split(",")]
    if len(fields) != 5 or fields[0] != limits["observed_gpu"] or int(fields[1]) * 1024**2 != int(limits["observed_gpu_vram_bytes"]):
        raise RuntimeError(f"device identity differs from the frozen E2 resource envelope: {gpu_rows[0]}")
    return {
        "target_drive_free_bytes": int(usage.free),
        "projected_peak_bytes": projected,
        "required_free_bytes": required_free,
        "host_memory": memory,
        "device_wide_gpu_diagnostic": gpu_rows[0],
        "total_gpu_memory_claimed": False,
    }


def verify_pre_model_bindings(
    extractor_path: Path,
    authorization: dict[str, Any] | None = None,
) -> PreflightResult:
    repo_root = extractor_path.resolve(strict=True).parents[4]
    project_root = repo_root / PROJECT_REL
    e0_seal_path = project_root / "seals" / "e0-seal-v09.json"
    e0_seal, freeze, identity, metadata = normalize_e0_manifest(repo_root, e0_seal_path)
    if e0_seal.get("model_contact_authorized") is not False:
        raise RuntimeError("E0 seal authority is open before fresh E2 authorization")
    predecessor_seal_path = project_root / "seals" / "e0-seal-v08.json"
    predecessor_seal = verify_seal(repo_root, predecessor_seal_path, EXPECTED_E0_V08_ROOT)
    if e0_seal.get("predecessor_e0_seal_manifest_sha256") != sha256_file(predecessor_seal_path)[0]:
        raise RuntimeError("E0 v09 does not bind the exact E0 v08 predecessor manifest bytes")
    paths_in_protocol = member_path(repo_root, e0_seal, "e2_protocol_path")[0]
    protocol_path = paths_in_protocol
    protocol_hash, _ = sha256_file(protocol_path)
    if protocol_hash != freeze.get("e2_v06_protocol_sha256"):
        raise RuntimeError("E0 freeze and E2 v06 protocol digest disagree")
    if resolve_inside(repo_root, freeze["e2_v06_protocol_path"]) != protocol_path.resolve(strict=True):
        raise RuntimeError("E0 freeze and E0 manifest resolve to different E2 protocol files")
    protocol = read_json(protocol_path)
    verify_frozen_e2_protocol(protocol)
    paths = protocol["preflight_paths"]
    expected_paths = {
        "repo_root": repo_root,
        "e0_seal_manifest_path": e0_seal_path,
        "e2_protocol_path": protocol_path,
        "representation_abi_path": member_path(repo_root, e0_seal, "representation_abi_path")[0],
        "extractor_source_path": extractor_path.resolve(strict=True),
        "execution_identity_verifier_path": Path(__file__).resolve(strict=True),
    }
    for key, expected_path in expected_paths.items():
        if Path(paths[key]).resolve(strict=True) != expected_path.resolve(strict=True):
            raise RuntimeError(f"E2 protocol path does not identify the sealed {key}")
    predecessors = protocol.get("predecessors", {})
    if predecessors.get("e0_v08_root_sha256") != EXPECTED_E0_V08_ROOT:
        raise RuntimeError("E2 v06 does not bind the sealed E0 v08 predecessor")
    if predecessors.get("e1_v04_root_sha256") != EXPECTED_E1_V04_ROOT:
        raise RuntimeError("E2 v06 does not bind the sealed E1 v04 panel")
    if predecessors.get("e2_v01_preservation_root_sha256") != EXPECTED_E2_V01_ROOT:
        raise RuntimeError("E2 v06 does not preserve the E2 v01 attempt")

    if freeze.get("predecessor_e0_root_sha256") != EXPECTED_E0_V08_ROOT:
        raise RuntimeError("E0 v09 does not preserve the sealed E0 v08 predecessor")
    if e0_seal.get("predecessor_e0_root_sha256") != EXPECTED_E0_V08_ROOT:
        raise RuntimeError("E0 v09 seal predecessor root differs from the frozen direct predecessor")
    if any(freeze.get(name) is not False for name in (
        "model_contact_authorized", "tokenizer_contact_authorized", "feature_extraction_authorized",
        "observer_fitting_authorized", "evaluation_scoring_authorized",
    )):
        raise RuntimeError("E0 v09 freeze authority is not closed before fresh E2 authorization")
    if identity.e1_root_sha256 != EXPECTED_E1_V04_ROOT:
        raise RuntimeError("E0 v09 manifest does not bind the expected E1 v04 root")

    abi_path, abi_hash, _ = member_path(repo_root, e0_seal, "representation_abi_path")
    if abi_hash != freeze.get("representation_abi_sha256"):
        raise RuntimeError("E0 freeze and representation ABI digest disagree")
    if resolve_inside(repo_root, freeze["representation_abi_path"]) != abi_path.resolve(strict=True):
        raise RuntimeError("E0 freeze and E0 manifest resolve to different ABI files")
    abi = read_json(abi_path)
    model_spec = protocol.get("model_and_representation", {})
    if (
        model_spec.get("model_id") != abi.get("model_id")
        or model_spec.get("revision") != abi.get("model_revision")
        or model_spec.get("surface") != abi.get("forward_call", {}).get("surface_id")
        or model_spec.get("representation_abi_sha256") != abi_hash
        or model_spec.get("extractor_source_sha256") != identity.extractor_sha256
        or model_spec.get("full_panel_rows") != 106_496
        or model_spec.get("hidden_dimension") != 2_048
        or model_spec.get("repeat_gate_rows") != 256
    ):
        raise RuntimeError("E2 model and representation fields differ from sealed ABI identities")
    extractor_hash, _ = sha256_file(extractor_path.resolve(strict=True))
    verifier_path = Path(__file__).resolve(strict=True)
    verifier_hash, _ = sha256_file(verifier_path)
    if abi.get("extractor_source_sha256") != extractor_hash or freeze.get("extractor_source_sha256") != extractor_hash:
        raise RuntimeError("extractor bytes do not match the ABI and E0 freeze bindings")
    if freeze.get("execution_identity_verifier_sha256") != verifier_hash:
        raise RuntimeError("execution-identity verifier bytes differ from the E0 freeze binding")
    if abi.get("execution_identity_verifier_sha256") != verifier_hash:
        raise RuntimeError("execution-identity verifier bytes differ from the representation ABI binding")
    if resolve_inside(repo_root, freeze["execution_identity_verifier_path"]) != verifier_path:
        raise RuntimeError("E0 freeze verifier path does not resolve to the executing verifier")
    if resolve_inside(repo_root, freeze["extractor_source_path"]) != extractor_path.resolve(strict=True):
        raise RuntimeError("E0 freeze extractor path does not resolve to this verifier/extractor")
    if (identity.extractor_sha256 != extractor_hash or identity.verifier_sha256 != verifier_hash
            or identity.representation_abi_sha256 != abi_hash):
        raise RuntimeError("normalized execution identity differs from frozen source or ABI bytes")
    protocol_identity = protocol.get("execution_identity", {})
    expected_protocol_identity = {
        "e1_root_sha256": identity.e1_root_sha256,
        "extractor_source_sha256": identity.extractor_sha256,
        "verifier_source_sha256": identity.verifier_sha256,
        "representation_abi_sha256": identity.representation_abi_sha256,
        "comparator_sha256": identity.comparator_sha256,
    }
    if any(protocol_identity.get(key) != value for key, value in expected_protocol_identity.items()):
        raise RuntimeError("E2 protocol fields differ from normalized sealed root/hash identities")
    if abi.get("representation_abi_id") != "FAS_FROZEN_OBSERVER_BUNDLE_REPRESENTATION_ABI_V06":
        raise RuntimeError("representation ABI content identity is not v06")
    if abi.get("forward_call", {}).get("tensor_identity") != "output.last_hidden_state[0, sequence_length - 1, :]":
        raise RuntimeError("representation tensor identity differs from the frozen ABI")
    forward_call = abi.get("forward_call", {})
    if forward_call.get("surface_id") != "V1_FINAL_POSITION":
        raise RuntimeError("representation surface differs from the frozen ABI")
    if forward_call.get("serialization_dtype") != "little-endian float32" or forward_call.get("feature_shape") != [2048]:
        raise RuntimeError("feature serialization identity differs from the frozen ABI")

    gpu_gate = protocol.get("gpu_measurement", {})
    freeze_gpu = freeze.get("resource_limits", {}).get("gpu_measurement_protocol", {})
    gpu_ceiling = int(freeze.get("resource_limits", {}).get("peak_gpu_memory_bytes_max", 0))
    if (
        gpu_gate.get("ceiling_bytes") != gpu_ceiling
        or gpu_gate.get("total_gpu_memory_claimed") is not False
        or freeze_gpu.get("total_gpu_memory_claimed") is not False
        or gpu_gate.get("scope_claim_exact") != freeze_gpu.get("scope_claim_exact")
    ):
        raise RuntimeError("E0/E2 process-scoped PyTorch allocator semantics differ")

    e1_root = Path(paths["e1_run_root"]).resolve(strict=True)
    if Path(paths["repo_root"]).resolve(strict=True) != repo_root.resolve(strict=True):
        raise RuntimeError("E2 protocol repo root differs from the running checkout")
    e1_seal_path = e1_root / "e1-seal-v01.json"
    e1_seal = verify_seal(e1_root, e1_seal_path, EXPECTED_E1_V04_ROOT)
    if e1_seal.get("model_contact_authorized") is not False or e1_seal.get("fitting_authorized") is not False:
        raise RuntimeError("E1 panel authority is not closed")
    if e1_seal.get("root_sha256") != identity.e1_root_sha256:
        raise RuntimeError("E1 panel root differs from the normalized E0 execution identity")
    row_identity = verify_panel_row_identity(
        e1_root, e1_seal, paths, int(protocol["model_and_representation"]["full_panel_rows"]),
    )
    input_path = resolve_inside(e1_root, paths["panel_inputs_relative_path"])
    row_manifest_path = resolve_inside(e1_root, paths["row_manifest_relative_path"])

    equivalence = protocol["representation_equivalence"]
    freeze_equivalence = freeze["representation_equivalence_gate"]
    if (
        equivalence.get("reference_cache_sha256") != freeze_equivalence.get("reference_cache_sha256")
        or equivalence.get("reference_cache_bytes") != freeze_equivalence.get("reference_cache_bytes")
        or equivalence.get("reference_cache_sha256") != EXPECTED_REFERENCE_SHA256
        or equivalence.get("reference_cache_bytes") != EXPECTED_REFERENCE_BYTES
    ):
        raise RuntimeError("E0 and E2 comparator identities differ")
    comparator_path = Path(paths["reference_cache_path"]).resolve(strict=True)
    if resolve_inside(repo_root, equivalence["reference_cache_path"]) != comparator_path:
        raise RuntimeError("E2 preflight path and frozen comparator path resolve differently")
    comparator_hash, comparator_size = verify_reference_cache(
        comparator_path, EXPECTED_REFERENCE_SHA256, EXPECTED_REFERENCE_BYTES,
    )
    if comparator_hash != identity.comparator_sha256 or comparator_size != EXPECTED_REFERENCE_BYTES:
        raise RuntimeError("comparator bytes differ from the normalized execution identity")

    wait_receipt, wait_hash = verify_wait_receipt(protocol, repo_root)
    live_matches = verify_live_wait_target_absent(protocol)

    model_root = Path(paths["model_snapshot_root"]).resolve(strict=True)
    tokenizer_root = Path(paths["tokenizer_snapshot_root"]).resolve(strict=True)
    model_manifest_path = Path(paths["model_asset_manifest_path"]).resolve(strict=True)
    tokenizer_manifest_path = Path(paths["tokenizer_asset_manifest_path"]).resolve(strict=True)
    assets = verify_model_and_tokenizer_assets(model_root, model_manifest_path, tokenizer_root, tokenizer_manifest_path, abi)
    runtime_versions = verify_runtime_metadata(abi)
    output_root = Path(paths["feature_output_root"]).resolve(strict=False)
    resources = verify_resource_preflight(freeze, output_root)

    checks = {
        "actual_e0_seal_root_and_members_recomputed": True,
        "e0_v08_predecessor_root_and_members_recomputed": True,
        "freeze_contract_derived_from_manifest_membership": True,
        "manifest_metadata_spelling_not_used_as_identity_gate": True,
        "e0_v08_direct_predecessor_verified": True,
        "e1_v04_root_and_panel_row_order_verified": True,
        "e2_v06_protocol_hash_and_authority_verified": True,
        "representation_abi_and_extractor_hashes_verified": True,
        "model_and_tokenizer_asset_hashes_verified": True,
        "runtime_distribution_versions_verified_without_importing_model_libraries": True,
        "concurrent_wait_receipt_and_live_absence_verified": True,
        "comparator_hash_and_length_verified_read_only": True,
        "storage_host_and_device_resource_preflight_passed": True,
        "feature_output_root_is_new": True,
        "labels_not_opened": True,
        "cuda_allocator_not_initialized": True,
    }
    observations = {
        "manifest_metadata": metadata,
        "wait_receipt_status": wait_receipt.get("status"),
        "live_wait_target_matches": live_matches,
        "panel_row_identity": row_identity,
        "assets": assets,
        "runtime_versions": runtime_versions,
        "resources": resources,
        "comparator_sha256": comparator_hash,
        "comparator_bytes": comparator_size,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "cuda_allocator_initialized": False,
    }

    if authorization is not None:
        require_authorization(authorization, identity, protocol, protocol_hash, wait_hash, comparator_hash, comparator_size, output_root)
    if "torch" in sys.modules or "transformers" in sys.modules or "tokenizers" in sys.modules:
        if authorization is None:
            raise RuntimeError("preauthorization verifier imported a model/tokenizer runtime package")

    return PreflightResult(
        identity=identity, abi=abi, equivalence=equivalence, checks=checks, observations=observations, repo_root=repo_root,
        e0_seal_path=e0_seal_path, e1_run_root=e1_root, panel_input_path=input_path,
        row_manifest_path=row_manifest_path, protocol_path=protocol_path,
        abi_path=abi_path, extractor_path=extractor_path.resolve(strict=True), output_root=output_root,
        reference_cache_path=comparator_path,
        model_snapshot_root=model_root, tokenizer_snapshot_root=tokenizer_root,
        tokenizer_manifest_path=tokenizer_manifest_path, model_asset_manifest_path=model_manifest_path,
        comparator_path=comparator_path,
    )


def require_authorization(
    authorization: dict[str, Any], identity: ExecutionIdentity, protocol: dict[str, Any],
    protocol_hash: str, wait_hash: str, comparator_hash: str, comparator_size: int, output_root: Path,
) -> None:
    if authorization.get("authorization_id") != "FAS_FROZEN_OBSERVER_BUNDLE_E2_MODEL_CONTACT_AUTHORIZATION_V06":
        raise RuntimeError("fresh E2 v06 authorization identity is required")
    if authorization.get("model_contact_authorized") is not True or authorization.get("feature_extraction_authorized") is not True:
        raise RuntimeError("E2 v06 model contact and extraction are not explicitly authorized")
    if authorization.get("observer_fitting_authorized") is not False or authorization.get("evaluation_scoring_authorized") is not False:
        raise RuntimeError("E2 authorization cannot open fitting, scoring, or evaluation")
    if authorization.get("execution_identity") != asdict(identity):
        raise RuntimeError("authorization execution identity differs from verified root/hash identities")
    if authorization.get("e0_root_sha256") != identity.seal_root_sha256:
        raise RuntimeError("authorization E0 root differs from verified identity")
    if authorization.get("e1_root_sha256") != identity.e1_root_sha256:
        raise RuntimeError("authorization E1 root differs from verified identity")
    if authorization.get("e2_protocol_sha256") != protocol_hash:
        raise RuntimeError("authorization E2 protocol digest differs from verified identity")
    if authorization.get("concurrent_run_wait_receipt_sha256") != wait_hash:
        raise RuntimeError("authorization wait receipt digest differs from verified prerequisite")
    if authorization.get("e2_v01_reference_cache_sha256") != comparator_hash or authorization.get("e2_v01_reference_cache_bytes") != comparator_size:
        raise RuntimeError("authorization comparator identity differs from the frozen cache")
    if Path(authorization.get("feature_output_root", "")).resolve(strict=False) != output_root:
        raise RuntimeError("authorization output path differs from the frozen new output root")
    paths = protocol["preflight_paths"]
    path_pairs = (
        ("repo_root", paths["repo_root"]),
        ("e0_seal_manifest_path", paths["e0_seal_manifest_path"]),
        ("e1_run_root", paths["e1_run_root"]),
        ("e2_protocol_path", paths["e2_protocol_path"]),
        ("representation_abi_path", paths["representation_abi_path"]),
        ("extractor_source_path", paths["extractor_source_path"]),
        ("execution_identity_verifier_path", paths["execution_identity_verifier_path"]),
        ("model_snapshot_root", paths["model_snapshot_root"]),
        ("tokenizer_snapshot_root", paths["tokenizer_snapshot_root"]),
        ("model_asset_manifest_path", paths["model_asset_manifest_path"]),
        ("tokenizer_asset_manifest_path", paths["tokenizer_asset_manifest_path"]),
        ("concurrent_run_wait_receipt_path", paths["concurrent_run_wait_receipt_path"]),
        ("e2_v01_reference_cache_path", paths["reference_cache_path"]),
    )
    for key, expected in path_pairs:
        if Path(authorization.get(key, "")).resolve(strict=False) != Path(expected).resolve(strict=False):
            raise RuntimeError(f"authorization path differs from the frozen preflight location: {key}")
    if protocol["authority"].get("successful_e2_does_not_authorize_e3") is not True:
        raise RuntimeError("protocol does not preserve the E3 authorization boundary")


def read_authorization(path: Path) -> dict[str, Any]:
    return read_json(path)


def result_json(result: PreflightResult) -> dict[str, Any]:
    return {
        "status": "PREFLIGHT_PASS_MODEL_CONTACT_NOT_AUTHORIZED",
        "execution_identity": asdict(result.identity),
        "checks": result.checks,
        "observations": result.observations,
        "paths": {
            "e0_seal_manifest": str(result.e0_seal_path),
            "e1_run_root": str(result.e1_run_root),
            "e2_protocol": str(result.protocol_path),
            "representation_abi": str(result.abi_path),
            "extractor": str(result.extractor_path),
            "feature_output_root": str(result.output_root),
        },
    }
