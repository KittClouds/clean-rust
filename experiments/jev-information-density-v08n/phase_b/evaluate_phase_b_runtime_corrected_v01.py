"""Narrow runtime-device alias adapter for the hash-frozen v0.8N evaluator."""

from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import platform
import sys
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
AUTH_PATH = PHASE / "phase-b-authorization-event-v01.json"
RUN_CONTRACT_PATH = PHASE / "phase-b-run-contract-v01.json"
ANALYSIS_PATH = PHASE / "phase-b-analysis-contract-v01.json"
RECEIPT_PATH = PHASE / "phase-b-evaluator-runtime-correction-v01.json"
FROZEN_EVALUATOR_PATH = PHASE / "evaluate_phase_b_v01.py"
TRAINING_VERIFIER_PATH = PHASE / "verify_training_seal_v01.py"
CORRECTION_VERIFIER_PATH = PHASE / "verify_phase_b_correction_v07.py"
SEAL_CORRECTION_VERIFIER_PATH = PHASE / "verify_phase_b_seal_metadata_correction_v01.py"
APPLICATION_RECEIPT = RUN / "evaluation-runtime-correction-application-v01.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen verifier/evaluator: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_runtime(contract: dict[str, Any], seal: dict[str, Any]) -> str:
    expected = contract["runtime_environment"]
    actual = {
        "python": platform.python_version(),
        "torch": torch.__version__,
        "transformers": importlib.metadata.version("transformers"),
        "tokenizers": importlib.metadata.version("tokenizers"),
        "numpy": np.__version__,
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
    }
    for key, value in actual.items():
        if str(value) != str(expected[key]):
            raise RuntimeError(f"frozen evaluation runtime mismatch for {key}: {value!r} != {expected[key]!r}")
    if not torch.cuda.is_available() or torch.cuda.device_count() != 1:
        raise RuntimeError("frozen evaluation runtime requires exactly one visible CUDA device")
    device_name = torch.cuda.get_device_name(0)
    capability = list(torch.cuda.get_device_capability(0))
    if device_name != expected["device"] or capability != expected["compute_capability"]:
        raise RuntimeError(f"CUDA device identity/capability mismatch: {device_name!r}/{capability}")
    flags = {
        "torch_matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "torch_cudnn_tf32": torch.backends.cudnn.allow_tf32,
        "torch_cudnn_benchmark": torch.backends.cudnn.benchmark,
        "torch_deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    for key, value in flags.items():
        if value is not expected[key]:
            raise RuntimeError(f"frozen runtime flag mismatch for {key}: {value!r} != {expected[key]!r}")
    if seal.get("contract_device_identity") != device_name or seal.get("runtime_device_locator") != "cuda:0":
        raise RuntimeError("training-seal device identity/locator does not match the live device")
    return "cuda:0"


def verify_candidate_tensor(contract: dict[str, Any], authorization_sha: str) -> dict[str, Any]:
    artifacts = contract["output"]["candidate_feature_artifacts"]
    tensor_path = Path(artifacts["tensor_path"])
    receipt_path = Path(artifacts["feature_receipt_path"])
    token_path = Path(artifacts["token_length_receipt_path"])
    receipt = read_json(receipt_path)
    token_receipt = read_json(token_path)
    if receipt.get("authorization_event_sha256") != authorization_sha:
        raise RuntimeError("candidate tensor belongs to another authorization event")
    if receipt.get("run_contract_sha256") != sha256_file(RUN_CONTRACT_PATH):
        raise RuntimeError("candidate tensor belongs to another run contract")
    if receipt.get("feature_file_sha256") != sha256_file(tensor_path):
        raise RuntimeError("candidate tensor file hash differs from its receipt")
    if receipt.get("token_length_receipt_sha256") != sha256_file(token_path):
        raise RuntimeError("candidate token-length receipt hash mismatch")
    if token_receipt.get("status") != "PASS_NO_TRUNCATION" or token_receipt.get("truncation") is not False:
        raise RuntimeError("candidate tokenization receipt is not a no-truncation pass")
    tensor = torch.load(tensor_path, map_location="cpu", weights_only=True)
    if tuple(tensor.shape) != (48, 2048) or tensor.dtype != torch.float32 or not tensor.is_contiguous():
        raise RuntimeError("candidate tensor differs from frozen 48x2048 contiguous float32 contract")
    if not torch.isfinite(tensor).all().item() or tensor_sha256(tensor) != receipt.get("tensor_sha256"):
        raise RuntimeError("candidate tensor content/non-finite validation failed")
    return {
        "candidate_tensor_sha256": receipt["tensor_sha256"],
        "candidate_tensor_file_sha256": receipt["feature_file_sha256"],
        "candidate_token_receipt_sha256": receipt["token_length_receipt_sha256"],
        "shape": list(tensor.shape), "dtype": str(tensor.dtype), "finite": True,
    }


def preflight() -> tuple[Any, dict[str, Any]]:
    receipt = read_json(RECEIPT_PATH)
    if receipt.get("status") != "IMPLEMENTATION_ONLY_EVALUATOR_RUNTIME_ALIAS_CORRECTION":
        raise RuntimeError("evaluator runtime correction receipt status mismatch")
    if receipt.get("adapter_sha256") != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("evaluator runtime adapter hash differs from correction receipt")
    event = read_json(AUTH_PATH)
    contract = read_json(RUN_CONTRACT_PATH)
    if event.get("status") != "PHASE_B_AUTHORIZED" or event.get("phase_b_authorized") is not True:
        raise RuntimeError("frozen Phase-B authorization is not active")
    if sha256_file(AUTH_PATH) != receipt.get("authorization_event_sha256"):
        raise RuntimeError("authorization event hash differs from correction receipt")
    if sha256_file(RUN_CONTRACT_PATH) != receipt.get("run_contract_sha256"):
        raise RuntimeError("run contract hash differs from correction receipt")
    if sha256_file(ANALYSIS_PATH) != receipt.get("analysis_contract_sha256"):
        raise RuntimeError("analysis contract hash differs from correction receipt")
    if sha256_file(FROZEN_EVALUATOR_PATH) != receipt["frozen_evaluator"]["sha256"]:
        raise RuntimeError("frozen evaluator source changed")
    relative_evaluator = str(FROZEN_EVALUATOR_PATH.relative_to(ROOT)).replace("\\", "/")
    if event.get("implementation_bindings", {}).get(relative_evaluator) != sha256_file(FROZEN_EVALUATOR_PATH):
        raise RuntimeError("frozen evaluator does not match authorization binding")

    seal = read_json(RUN / "training-seal-manifest.json")
    if sha256_file(RUN / "training-seal-manifest.json") != receipt.get("training_seal_sha256"):
        raise RuntimeError("training seal changed after correction receipt was frozen")
    if sha256_file(RUN / "checkpoint-hash-tree.json") != receipt.get("checkpoint_hash_tree_sha256"):
        raise RuntimeError("checkpoint tree changed after correction receipt was frozen")
    if seal.get("status") != "ALL_NINE_RUNS_TRAINED_SEALED_UNEVALUATED" or seal.get("run_count") != 9 or seal.get("checkpoint_count") != 27:
        raise RuntimeError("training seal is not complete for all nine runs")

    metadata_verifier = load_module(SEAL_CORRECTION_VERIFIER_PATH, "jev_v08n_runtime_correction_seal_verifier")
    metadata_result = metadata_verifier.verify()
    correction_verifier = load_module(CORRECTION_VERIFIER_PATH, "jev_v08n_runtime_correction_chain_verifier")
    chain_result = correction_verifier.verify_training()
    evaluator = load_module(FROZEN_EVALUATOR_PATH, "jev_v08n_frozen_evaluator_runtime_adapter")
    training_validation, panel_seal, panel_tree = evaluator.verify_training_and_panel_metadata()
    locator = verify_runtime(contract, seal)
    candidate = verify_candidate_tensor(contract, sha256_file(AUTH_PATH))

    if (RUN / "panel-unlock-receipt.json").exists() or (RUN / "evaluation").exists() or APPLICATION_RECEIPT.exists():
        raise RuntimeError("one-time evaluation output/unlock path is already occupied")
    if panel_seal.get("panel_locked") is not True or panel_seal.get("phase_b_authorized") is not False:
        raise RuntimeError("sealed evaluation panel is not in its locked pre-opening state")
    result = {
        "runtime_device_identity": contract["runtime_environment"]["device"],
        "runtime_device_locator": locator,
        "runtime_compute_capability": contract["runtime_environment"]["compute_capability"],
        "candidate_tensor": candidate,
        "training_seal_validation": training_validation,
        "metadata_correction_validation": metadata_result,
        "implementation_chain_validation": chain_result["status"],
        "panel_identity": read_json(ANALYSIS_PATH)["evaluation_surface"]["identity"],
        "panel_metadata_verified_locked": True,
        "panel_body_opened": False,
        "newtight_access": False,
        "phoenix_access": False,
    }
    return evaluator, result


def main() -> int:
    evaluator, result = preflight()
    if "--preflight-only" in sys.argv[1:]:
        print(json.dumps({"status": "EVALUATOR_PREFLIGHT_PASS_PANEL_STILL_LOCKED", **result}, separators=(",", ":")))
        return 0

    original_read_json = evaluator.read_json
    run_contract_resolved = RUN_CONTRACT_PATH.resolve()
    locator = result["runtime_device_locator"]

    def read_json_with_device_locator(path: Path) -> dict[str, Any]:
        value = original_read_json(path)
        if Path(path).resolve() == run_contract_resolved:
            if value["runtime_environment"]["device"] != result["runtime_device_identity"]:
                raise RuntimeError("run-contract device identity changed during evaluator dispatch")
            value["runtime_environment"]["device"] = locator
        return value

    evaluator.read_json = read_json_with_device_locator
    status = evaluator.main()
    if status != 0:
        raise RuntimeError(f"frozen evaluator returned nonzero status: {status}")
    evaluation = RUN / "evaluation"
    predictions = evaluation / "predictions.jsonl"
    diagnostics = evaluation / "geometry-and-surface-diagnostics.jsonl"
    frozen_receipt = evaluation / "evaluation-receipt.json"
    if not all(path.is_file() for path in (predictions, diagnostics, frozen_receipt)):
        raise RuntimeError("frozen evaluator did not produce its complete output set")
    application = {
        "status": "FROZEN_EVALUATOR_COMPLETED_WITH_RUNTIME_DEVICE_ALIAS",
        "adapter_sha256": sha256_file(Path(__file__).resolve()),
        "correction_receipt_sha256": sha256_file(RECEIPT_PATH),
        "authorization_event_sha256": sha256_file(AUTH_PATH),
        "frozen_evaluator_sha256": sha256_file(FROZEN_EVALUATOR_PATH),
        "training_seal_sha256": sha256_file(RUN / "training-seal-manifest.json"),
        "analysis_contract_sha256": sha256_file(ANALYSIS_PATH),
        "runtime_device_identity": result["runtime_device_identity"],
        "runtime_device_locator": locator,
        "mapping_scope": "in-memory run-contract device locator only; frozen contract file unchanged",
        "panel_open_count": 1,
        "prediction_sha256": sha256_file(predictions),
        "diagnostics_sha256": sha256_file(diagnostics),
        "evaluation_receipt_sha256": sha256_file(frozen_receipt),
        "newtight_access": False,
        "legacy_evaluation_access": False,
        "phoenix_access": False,
    }
    with APPLICATION_RECEIPT.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(application, indent=2) + "\n")
        stream.flush()
    print(json.dumps({"status": application["status"], "application_receipt": str(APPLICATION_RECEIPT),
                      "prediction_sha256": application["prediction_sha256"], "panel_open_count": 1}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
