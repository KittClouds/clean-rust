"""Extract the authorized v0.8N-E1 held-out candidate semantic basis.

This sidecar encodes only the 16 rows in the sealed E1 text manifest. It never
opens held-out panel files, training heads, targets, predictions, or metrics.
Two separate worker processes perform the frozen extraction; the orchestrator
accepts the basis only when their tensors agree within the sealed 1e-5 gate.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[4]
E1 = ROOT / "experiments/jev-information-density-v08n/phase_b/e1"
CONTRACT_PATH = E1 / "e1-repair-contract-v01.json"
AUDIT_PATH = E1 / "e1-candidate-basis-metadata-audit-v01.json"
MANIFEST_PATH = E1 / "e1-candidate-text-manifest-v01.jsonl"
AUTH_PATH = E1 / "e1-candidate-extraction-authorization-v01.json"
DISPOSITION_PATH = ROOT / "experiments/jev-information-density-v08n/phase_b/phase-b-final-disposition-v01.json"
RUN_CONTRACT_PATH = ROOT / "experiments/jev-information-density-v08n/phase_b/phase-b-run-contract-v01.json"
PANEL_UNLOCK_PATH = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01\panel-unlock-receipt.json")
EVALUATION_DIR = PANEL_UNLOCK_PATH.parent / "evaluation"
MODEL_NAME = "lfm2.5-1.2b-base"
EXPECTED = {
    "contract": "770d2e3a548e4e31e6a1e7af878f19db925f901666c5bceecd0c11454ee858e2",
    "manifest": "7987ae385454b32ddec548e48ef6543253b7b061ee1f077c064363c06304a285",
    "original_disposition": "bae6d7ac88f5ca0c5684c219e0e0b82f03962bf6f0292c205cba58765c75a656",
    "run_contract": "da538aa03355732a2ba362da45d947e169b87aa644d0efd6ba7ef7a546306c1f",
    "audit": "f91b27f60905280d86cbf302520945c59619a501ae749b6ecfeee75d5c5ed752",
    "authorization": "e1b0c2894eaa9330cabdb500330570d6d0edad9bba7a3067d2df41b10f32552f",
}


def sha256_bytes(value: bytes | memoryview) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def write_new_json(path: Path, value: Any) -> None:
    payload = json_bytes(value)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def tensor_hash(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return sha256_bytes(memoryview(array).cast("B"))


def file_hashes_match(root: Path, expected: dict[str, str]) -> dict[str, str]:
    actual: dict[str, str] = {}
    for name, wanted in expected.items():
        path = root / name
        if not path.is_file():
            raise FileNotFoundError(f"pinned model file missing: {path}")
        digest = sha256_file(path)
        actual[name] = digest
        if digest != wanted:
            raise RuntimeError(f"pinned model file hash mismatch: {name}")
    return actual


def validate_runtime(runtime: dict[str, Any]) -> dict[str, Any]:
    actual = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": torch.__version__,
        "transformers": metadata.version("transformers"),
        "tokenizers": metadata.version("tokenizers"),
        "numpy": metadata.version("numpy"),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "compute_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
        "torch_matmul_tf32": torch.backends.cuda.matmul.allow_tf32 if torch.cuda.is_available() else None,
        "torch_cudnn_tf32": torch.backends.cudnn.allow_tf32 if torch.cuda.is_available() else None,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    for key in ("python", "torch", "transformers", "tokenizers", "numpy", "cuda_runtime", "cudnn", "device", "compute_capability"):
        if actual[key] != runtime[key]:
            raise RuntimeError(f"frozen runtime mismatch {key}: got {actual[key]!r}, expected {runtime[key]!r}")
    if not torch.cuda.is_available():
        raise RuntimeError("frozen CUDA device is unavailable")
    if actual["torch_matmul_tf32"] is not runtime["torch_matmul_tf32"]:
        raise RuntimeError("matmul TF32 setting differs from the frozen run")
    if actual["torch_cudnn_tf32"] is not runtime["torch_cudnn_tf32"]:
        raise RuntimeError("cuDNN TF32 setting differs from the frozen run")
    if actual["deterministic_algorithms"] is not runtime["torch_deterministic_algorithms"]:
        raise RuntimeError("deterministic-algorithm setting differs from the frozen run")
    return actual


def validate_static_inputs(*, check_output_absent: bool) -> dict[str, Any]:
    for key, path in (
        ("contract", CONTRACT_PATH),
        ("manifest", MANIFEST_PATH),
        ("original_disposition", DISPOSITION_PATH),
        ("run_contract", RUN_CONTRACT_PATH),
        ("audit", AUDIT_PATH),
        ("authorization", AUTH_PATH),
    ):
        if sha256_file(path) != EXPECTED[key]:
            raise RuntimeError(f"sealed input hash mismatch: {key}")

    contract = load_json(CONTRACT_PATH)
    audit = load_json(AUDIT_PATH)
    authorization = load_json(AUTH_PATH)
    disposition = load_json(DISPOSITION_PATH)
    run_contract = load_json(RUN_CONTRACT_PATH)
    if contract["identity"] != "v0.8N-E1-heldout-candidate-semantic-basis-recovery-v01":
        raise RuntimeError("wrong E1 identity")
    if authorization["status"] != "EXPLICITLY_AUTHORIZED_EXTRACTION_AND_TARGET_FREE_JOIN_ONLY":
        raise RuntimeError("separate E1 extraction authorization is absent or invalid")
    if authorization["bindings"]["e1_repair_contract_sha256"] != EXPECTED["contract"] or authorization["bindings"]["candidate_text_manifest_sha256"] != EXPECTED["manifest"]:
        raise RuntimeError("E1 authorization does not bind this contract and manifest")
    if authorization["bindings"]["model_revision"] != contract["frozen_extraction_recipe"]["backbone"]["revision"]:
        raise RuntimeError("E1 authorization model revision mismatch")
    if authorization["second_panel_opening_authorized"] is not False or authorization["head_inference_authorized"] is not False:
        raise RuntimeError("E1 authorization exceeds its extraction/join-only scope")
    if disposition["status"] != "EVALUATION_INPUT_CONTRACT_INCOMPLETE" or disposition["training"]["status"] != "VALID_AND_SEALED":
        raise RuntimeError("original Phase-B disposition drift")
    if disposition["evaluation"]["opening_count"] != 1:
        raise RuntimeError("original panel opening count drift")
    if EVALUATION_DIR.exists():
        raise RuntimeError("unexpected original evaluation output directory")

    rows = load_jsonl(MANIFEST_PATH)
    ids = [row["candidate_semantic_id"] for row in rows]
    if len(rows) != 16 or len(set(ids)) != 16:
        raise RuntimeError("E1 candidate manifest must contain exactly 16 unique semantic IDs")
    if [row["candidate_vector_index"] for row in rows] != list(range(16)):
        raise RuntimeError("E1 manifest storage order is not canonical 0..15")
    if len({row["model_input_utf8_sha256"] for row in rows}) != 16:
        raise RuntimeError("E1 candidate texts are not unique")
    for row in rows:
        if hashlib.sha256(row["model_input_text"].encode("utf-8")).hexdigest() != row["model_input_utf8_sha256"]:
            raise RuntimeError(f"E1 text hash mismatch: {row['candidate_semantic_id']}")
        if row["feature_key"] != "mean_full@16" or row["expected_feature_dimension"] != 2048 or row["expected_feature_dtype"] != "float32":
            raise RuntimeError(f"E1 feature contract mismatch: {row['candidate_semantic_id']}")

    model = contract["frozen_extraction_recipe"]["backbone"]
    encoder = contract["frozen_extraction_recipe"]["encoder"]
    run_model = run_contract["model_and_representation"]
    if model["revision"] != run_model["revision"] or model["snapshot_file_sha256"] != run_model["snapshot_file_sha256"]:
        raise RuntimeError("E1 model snapshot differs from the frozen run contract")
    if encoder["sha256"] != run_model["extractor_sha256"]:
        raise RuntimeError("E1 generic encoder differs from the frozen run contract")
    encoder_path = ROOT / encoder["path"].split("::", 1)[0]
    if sha256_file(encoder_path) != encoder["sha256"]:
        raise RuntimeError("frozen LFM encoder source changed")

    output_root = Path(contract["frozen_extraction_recipe"]["future_output_root"])
    if check_output_absent and output_root.exists():
        raise FileExistsError(f"E1 output identity already exists; refusing overwrite: {output_root}")
    if not check_output_absent and not output_root.is_dir():
        raise FileNotFoundError(f"E1 extraction output root absent: {output_root}")

    expected_token_counts = audit["tokenizer_only_preflight"]["token_counts"]
    if len(expected_token_counts) != 16:
        raise RuntimeError("metadata audit token count vector is malformed")
    return {
        "contract": contract,
        "audit": audit,
        "authorization": authorization,
        "run_contract": run_contract,
        "rows": rows,
        "expected_token_counts": expected_token_counts,
        "output_root": output_root,
        "model_directory": Path(model["snapshot_directory"]),
    }


def load_adapter(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("jev_e1_frozen_lfm_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen LFM adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def worker(pass_number: int, attempt_directory: Path) -> int:
    attempt_directory.mkdir(parents=True, exist_ok=False)
    try:
        inputs = validate_static_inputs(check_output_absent=False)
        contract = inputs["contract"]
        model_contract = contract["frozen_extraction_recipe"]["backbone"]
        encoder_contract = contract["frozen_extraction_recipe"]["encoder"]
        run_contract = inputs["run_contract"]
        runtime = validate_runtime(run_contract["runtime_environment"])
        model_hashes = file_hashes_match(inputs["model_directory"], model_contract["snapshot_file_sha256"])
        adapter_path = ROOT / encoder_contract["path"].split("::", 1)[0]
        adapter = load_adapter(adapter_path)
        if adapter.MODEL_SPEC["revision"] != model_contract["revision"]:
            raise RuntimeError("loaded adapter revision differs from the E1 contract")
        tokenizer, model = adapter.load_model(inputs["model_directory"].parent, "cuda")
        if int(model.config.hidden_size) != 2048 or int(model.config.num_hidden_layers) != 16:
            raise RuntimeError("loaded frozen LFM architecture differs from the contract")
        if any(parameter.requires_grad for parameter in model.parameters()):
            raise RuntimeError("LFM backbone is not frozen")

        rows = inputs["rows"]
        texts = [row["model_input_text"] for row in rows]
        encoded = tokenizer(texts, add_special_tokens=True, padding=False, truncation=False)
        token_rows: list[list[int]] = encoded["input_ids"]
        token_counts = [len(row) for row in token_rows]
        if token_counts != inputs["expected_token_counts"]:
            raise RuntimeError(f"token IDs/lengths differ from the sealed tokenizer-only preflight: {token_counts}")
        if len(token_rows) != 16 or max(token_counts) > 1024:
            raise RuntimeError("E1 input would truncate or has the wrong row count")

        features = adapter.encode_lfm_texts(
            model, tokenizer, texts, ["mean_full"], [16], 1, "cuda", adapter.MODEL_SPEC,
        )["mean_full@16"].detach().cpu().contiguous().to(torch.float32)
        if tuple(features.shape) != (16, 2048) or features.dtype != torch.float32 or not features.is_contiguous():
            raise RuntimeError("E1 feature tensor shape, dtype, or layout mismatch")
        if not torch.isfinite(features).all().item():
            raise RuntimeError("E1 feature tensor contains non-finite values")

        feature_records = []
        token_records = []
        for index, row in enumerate(rows):
            token_payload = json.dumps(token_rows[index], separators=(",", ":")).encode("ascii")
            vector_hash = tensor_hash(features[index])
            feature_records.append({
                "output_row": index,
                "candidate_vector_index": index,
                "candidate_semantic_id": row["candidate_semantic_id"],
                "schema_family_id": row["schema_family_id"],
                "feature_sha256": vector_hash,
            })
            token_records.append({
                "candidate_vector_index": index,
                "candidate_semantic_id": row["candidate_semantic_id"],
                "schema_family_id": row["schema_family_id"],
                "model_input_utf8_sha256": row["model_input_utf8_sha256"],
                "token_ids": token_rows[index],
                "token_ids_sha256": sha256_bytes(token_payload),
                "sequence_length": token_counts[index],
                "feature_sha256": vector_hash,
            })

        tensor_path = attempt_directory / "candidate-features.pt"
        with tensor_path.open("xb") as stream:
            torch.save(features, stream)
            stream.flush()
            os.fsync(stream.fileno())
        reloaded = torch.load(tensor_path, map_location="cpu", weights_only=True)
        if reloaded.dtype != torch.float32 or tuple(reloaded.shape) != (16, 2048) or tensor_hash(reloaded) != tensor_hash(features):
            raise RuntimeError("pass tensor serialization/reload parity failed")

        token_path = attempt_directory / "candidate-token-records.json"
        write_new_json(token_path, {"records": token_records, "count": len(token_records)})
        receipt = {
            "status": "E1_EXTRACTION_PASS_MATERIALIZED",
            "pass_number": pass_number,
            "process_id": os.getpid(),
            "contract_sha256": EXPECTED["contract"],
            "extraction_authorization_sha256": EXPECTED["authorization"],
            "candidate_text_manifest_sha256": EXPECTED["manifest"],
            "extractor_path": encoder_contract["path"],
            "extractor_sha256": encoder_contract["sha256"],
            "model_revision": model_contract["revision"],
            "model_snapshot_sha256": model_hashes,
            "runtime": runtime,
            "settings": {
                "feature_key": "mean_full@16",
                "pooling": "final-layer mean_full over valid token positions",
                "batch_size": 1,
                "exact_length": True,
                "padding": False,
                "maximum_length": 1024,
                "backbone_internal_dtype": "bfloat16",
                "feature_dtype": "float32",
            },
            "shape": [16, 2048],
            "dtype": "float32",
            "tensor_sha256": tensor_hash(features),
            "tensor_file_sha256": sha256_file(tensor_path),
            "token_records_sha256": sha256_file(token_path),
            "feature_records": feature_records,
            "heads_loaded": False,
            "targets_read_or_used": False,
            "predictions_or_metrics": False,
            "panel_files_opened": False,
            "phoenix_access": False,
        }
        write_new_json(attempt_directory / "pass-receipt.json", receipt)
        return 0
    except BaseException as exc:
        try:
            write_new_json(attempt_directory / "failure-receipt.json", {
                "status": "E1_EXTRACTION_PASS_FAILED_FAIL_CLOSED",
                "pass_number": pass_number,
                "exception_type": type(exc).__name__,
                "exception": str(exc),
                "traceback": traceback.format_exc(),
                "heads_loaded": False,
                "targets_read_or_used": False,
                "predictions_or_metrics": False,
            })
        except Exception:
            pass
        raise


def run_worker(script: Path, pass_number: int, attempt_directory: Path, root: Path) -> None:
    env = os.environ.copy()
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    command = [sys.executable, str(script), "--worker", str(pass_number), "--attempt-dir", str(attempt_directory)]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    (attempt_directory / "stdout.log").write_text(result.stdout, encoding="utf-8")
    (attempt_directory / "stderr.log").write_text(result.stderr, encoding="utf-8")
    if result.returncode != 0:
        write_new_json(root / f"pass-{pass_number}-failure.json", {
            "status": "E1_REPEAT_EXTRACTION_FAILED_FAIL_CLOSED",
            "pass_number": pass_number,
            "returncode": result.returncode,
            "attempt_directory": str(attempt_directory),
            "heads_loaded": False,
            "predictions_or_metrics": False,
        })
        raise RuntimeError(f"E1 extraction process {pass_number} failed; see retained attempt artifacts")


def orchestrate() -> int:
    script = Path(__file__).resolve()
    script_sha = sha256_file(script)
    inputs = validate_static_inputs(check_output_absent=True)
    contract = inputs["contract"]
    run_contract = inputs["run_contract"]
    runtime = validate_runtime(run_contract["runtime_environment"])
    model_hashes = file_hashes_match(inputs["model_directory"], contract["frozen_extraction_recipe"]["backbone"]["snapshot_file_sha256"])
    root: Path = inputs["output_root"]
    root.mkdir(parents=True, exist_ok=False)
    attempts = root / "attempts"
    attempts.mkdir(exist_ok=False)
    write_new_json(root / "e1-extraction-start-receipt.json", {
        "status": "E1_CANDIDATE_EXTRACTION_AUTHORIZED_AND_STARTED",
        "contract_sha256": EXPECTED["contract"],
        "manifest_sha256": EXPECTED["manifest"],
        "original_phase_b_disposition": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
        "original_panel_opening_count": 1,
        "separate_candidate_extraction_authorization": "explicit user authorization in this thread",
        "extraction_authorization_receipt_sha256": EXPECTED["authorization"],
        "implementation_script_sha256": script_sha,
        "runtime_preflight": runtime,
        "model_snapshot_sha256_before_extraction": model_hashes,
        "only_16_manifest_texts": True,
        "heads_loaded": False,
        "heldout_targets_read_or_used": False,
        "predictions_or_metrics": False,
        "panel_files_opened": False,
        "second_panel_opening_authorized": False,
        "phoenix_access": False,
    })

    pass_dirs = [attempts / "pass-1", attempts / "pass-2"]
    for pass_number, pass_dir in enumerate(pass_dirs, 1):
        run_worker(script, pass_number, pass_dir, root)

    pass_receipts = [load_json(path / "pass-receipt.json") for path in pass_dirs]
    pass_tokens = [load_json(path / "candidate-token-records.json") for path in pass_dirs]
    if pass_receipts[0]["tensor_sha256"] != pass_receipts[1]["tensor_sha256"]:
        first = torch.load(pass_dirs[0] / "candidate-features.pt", map_location="cpu", weights_only=True)
        second = torch.load(pass_dirs[1] / "candidate-features.pt", map_location="cpu", weights_only=True)
        max_error = float((first - second).abs().max().item())
    else:
        max_error = 0.0
    if pass_tokens[0] != pass_tokens[1]:
        raise RuntimeError("independent extraction token records differ; no canonical E1 basis accepted")
    first = torch.load(pass_dirs[0] / "candidate-features.pt", map_location="cpu", weights_only=True)
    second = torch.load(pass_dirs[1] / "candidate-features.pt", map_location="cpu", weights_only=True)
    max_error = float((first - second).abs().max().item())
    if not math.isfinite(max_error) or max_error > 1e-5:
        write_new_json(root / "repeat-parity-failure.json", {
            "status": "E1_INDEPENDENT_REPEAT_PARITY_FAILED",
            "max_absolute_error": max_error,
            "required_max_absolute_error": 1e-5,
            "canonical_feature_basis_accepted": False,
            "heads_loaded": False,
            "predictions_or_metrics": False,
        })
        raise RuntimeError(f"E1 clean-process repeat parity failed: max_abs={max_error}")

    # Recheck source weights after both independent processes; no artifacts are
    # accepted if the pinned model snapshot changed during the extraction.
    model_hashes_after = file_hashes_match(inputs["model_directory"], contract["frozen_extraction_recipe"]["backbone"]["snapshot_file_sha256"])
    if model_hashes_after != model_hashes:
        raise RuntimeError("pinned model snapshot changed during E1 extraction")

    feature_dir = root / "feature-cache"
    feature_dir.mkdir(exist_ok=False)
    canonical_path = feature_dir / "heldout-candidate-features.pt"
    with canonical_path.open("xb") as destination, (pass_dirs[0] / "candidate-features.pt").open("rb") as source:
        shutil.copyfileobj(source, destination, length=1 << 20)
        destination.flush()
        os.fsync(destination.fileno())
    canonical = torch.load(canonical_path, map_location="cpu", weights_only=True)
    if tuple(canonical.shape) != (16, 2048) or canonical.dtype != torch.float32 or not torch.isfinite(canonical).all().item():
        raise RuntimeError("canonical E1 feature tensor failed post-copy validation")

    token_path = feature_dir / "heldout-candidate-token-lengths.json"
    with token_path.open("xb") as destination, (pass_dirs[0] / "candidate-token-records.json").open("rb") as source:
        shutil.copyfileobj(source, destination, length=1 << 20)
        destination.flush()
        os.fsync(destination.fileno())

    parity = {
        "status": "PASS_INDEPENDENT_CLEAN_PROCESS_REPEAT",
        "contract_sha256": EXPECTED["contract"],
        "extraction_authorization_sha256": EXPECTED["authorization"],
        "pass_1_tensor_sha256": pass_receipts[0]["tensor_sha256"],
        "pass_2_tensor_sha256": pass_receipts[1]["tensor_sha256"],
        "pass_1_tensor_file_sha256": pass_receipts[0]["tensor_file_sha256"],
        "pass_2_tensor_file_sha256": pass_receipts[1]["tensor_file_sha256"],
        "max_absolute_error": max_error,
        "required_max_absolute_error": 1e-5,
        "pass_process_ids": [pass_receipts[0]["process_id"], pass_receipts[1]["process_id"]],
        "token_records_identical": True,
        "canonical_pass": 1,
        "heads_loaded": False,
        "predictions_or_metrics": False,
    }
    write_new_json(feature_dir / "repeat-parity-receipt.json", parity)

    records = pass_tokens[0]["records"]
    receipt = {
        "status": "E1_CANDIDATE_BASIS_EXTRACTED_REPEAT_PASS_PENDING_JOIN_AUDIT",
        "identity": "v0.8N-E1-heldout-candidate-semantic-basis-recovery-v01",
        "contract_sha256": EXPECTED["contract"],
        "metadata_audit_sha256": EXPECTED["audit"],
        "candidate_text_manifest_sha256": EXPECTED["manifest"],
        "implementation_script_sha256": script_sha,
        "extractor_path": contract["frozen_extraction_recipe"]["encoder"]["path"],
        "extractor_sha256": contract["frozen_extraction_recipe"]["encoder"]["sha256"],
        "model_repo_id": contract["frozen_extraction_recipe"]["backbone"]["repo_id"],
        "model_revision": contract["frozen_extraction_recipe"]["backbone"]["revision"],
        "model_snapshot_sha256_before_and_after": model_hashes,
        "settings": contract["frozen_extraction_recipe"]["encoder"]["settings"],
        "shape": [16, 2048],
        "dtype": "float32",
        "canonical_tensor_sha256": tensor_hash(canonical),
        "canonical_tensor_file_sha256": sha256_file(canonical_path),
        "token_length_records_sha256": sha256_file(token_path),
        "repeat_parity_receipt_sha256": sha256_file(feature_dir / "repeat-parity-receipt.json"),
        "row_records": records,
        "heads_loaded": False,
        "heldout_targets_read_or_used": False,
        "predictions_or_metrics": False,
        "second_panel_opening": False,
        "phoenix_access": False,
    }
    write_new_json(feature_dir / "heldout-candidate-feature-receipt.json", receipt)
    write_new_json(root / "extraction-artifact-hash-tree.json", {
        "status": "E1_FEATURE_BASIS_HASH_TREE_SEALED_PENDING_TARGET_FREE_JOIN_AUDIT",
        "contract_sha256": EXPECTED["contract"],
        "manifest_sha256": EXPECTED["manifest"],
        "implementation_script_sha256": script_sha,
        "files": {
            "feature-cache/heldout-candidate-features.pt": sha256_file(canonical_path),
            "feature-cache/heldout-candidate-feature-receipt.json": sha256_file(feature_dir / "heldout-candidate-feature-receipt.json"),
            "feature-cache/heldout-candidate-token-lengths.json": sha256_file(token_path),
            "feature-cache/repeat-parity-receipt.json": sha256_file(feature_dir / "repeat-parity-receipt.json"),
        },
        "feature_vectors": 16,
        "heads_loaded": False,
        "predictions_or_metrics": False,
        "panel_opening_count": 1,
        "second_panel_opening": False,
    })
    print(json.dumps({
        "status": receipt["status"],
        "feature_count": 16,
        "shape": [16, 2048],
        "max_repeat_error": max_error,
        "canonical_tensor_sha256": receipt["canonical_tensor_sha256"],
        "output_root": str(root),
        "heads_loaded": False,
        "predictions_or_metrics": False,
        "panel_opening_count": 1,
    }, separators=(",", ":")))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true", help="validate contracts/runtime/path without loading LFM weights")
    parser.add_argument("--worker", type=int, choices=(1, 2), help=argparse.SUPPRESS)
    parser.add_argument("--attempt-dir", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is not None:
        if args.attempt_dir is None:
            parser.error("--worker requires --attempt-dir")
        return worker(args.worker, args.attempt_dir)
    if args.preflight:
        inputs = validate_static_inputs(check_output_absent=True)
        runtime = validate_runtime(inputs["run_contract"]["runtime_environment"])
        model_hashes = file_hashes_match(inputs["model_directory"], inputs["contract"]["frozen_extraction_recipe"]["backbone"]["snapshot_file_sha256"])
        print(json.dumps({
            "status": "PASS_PREEXTRACTION_AUTHORIZED_INPUTS_RUNTIME_SNAPSHOT",
            "contract_sha256": EXPECTED["contract"],
            "extraction_authorization_sha256": EXPECTED["authorization"],
            "manifest_sha256": EXPECTED["manifest"],
            "candidate_count": len(inputs["rows"]),
            "runtime": runtime,
            "model_snapshot_sha256": model_hashes,
            "output_root_absent": True,
            "weights_loaded": False,
            "head_loaded": False,
            "panel_opened": False,
        }, indent=2))
        return 0
    return orchestrate()


if __name__ == "__main__":
    raise SystemExit(main())
