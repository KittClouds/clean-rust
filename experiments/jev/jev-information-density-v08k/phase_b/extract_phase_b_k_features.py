"""Extract the frozen, training-only LFM feature cache for v0.8K."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
AUTH = RUN / "preflight/model-contact-authorization.json"
FEATURE_DIR = RUN / "feature-cache"
FEATURES = FEATURE_DIR / "phase-b-train-features.pt"
F100 = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\F100-groups.jsonl")
STATE_TABLE = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\state-inputs.jsonl")
CANDIDATE_TABLE = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean\materialized\candidate-inputs-name_definition.jsonl")
MODEL_ROOT = Path(r"D:\codex-runs\jev-lfm-variable-v07\models")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_adapter() -> Any:
    path = ROOT / "experiments/jev-lfm-variable-v07/extract_lfm.py"
    spec = importlib.util.spec_from_file_location("jev_v08k_lfm_adapter", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load LFM adapter: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def tensor_sha256(tensor: torch.Tensor) -> str:
    return hashlib.sha256(tensor.detach().cpu().contiguous().numpy().tobytes()).hexdigest()


def main() -> int:
    auth = read_json(AUTH)
    contract = read_json(CODE / "phase-b-v01-contract.json")
    require(auth["status"] == "PASS" and auth["feature_extraction_authorized"] is True, "K feature authorization absent")
    require(auth["phase_a_identity"] == "phase-a-v01-clean", "K Phase-A identity drift")
    require(auth["objective_graph_sha256"] == contract["objective_graph_sha256"], "K graph binding drift")
    require(auth["source_code_sha256"]["extract_phase_b_k_features.py"] == sha256_file(Path(__file__)), "extractor changed after preflight")
    require(sha256_file(F100) == auth["verified_primary_bank_sha256"], "F100 changed after preflight")

    states = read_jsonl(STATE_TABLE)
    candidates = read_jsonl(CANDIDATE_TABLE)
    primary = read_jsonl(F100)
    require(len(primary) == 100000 and len(states) > 0 and len(candidates) == 373, "training table counts drift")
    require(all(int(row["state_idx"]) < len(states) for row in primary), "state index outside training table")
    require(all(max(row["candidate_indices"]["name_definition"]) < len(candidates) for row in primary), "candidate index outside training table")

    adapter = load_adapter()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer, model = adapter.load_model(MODEL_ROOT, device)
    layer = int(model.config.num_hidden_layers)
    key = f"mean_full@{layer}"
    started = time.perf_counter()
    state_features = adapter.encode_lfm_texts(model, tokenizer, [row["text"] for row in states], ["mean_full"], [layer], 1, device, adapter.MODEL_SPEC)[key]
    candidate_features = adapter.encode_lfm_texts(model, tokenizer, [row["text"] for row in candidates], ["mean_full"], [layer], 1, device, adapter.MODEL_SPEC)[key]
    require(state_features.dtype == torch.float32 and candidate_features.dtype == torch.float32, "feature dtype drift")
    require(state_features.shape[1] == 2048 and candidate_features.shape[1] == 2048, "feature shape drift")

    payload = {
        "protocol": contract["protocol"],
        "objective_graph_sha256": contract["objective_graph_sha256"],
        "revision": adapter.MODEL_SPEC["revision"],
        "hidden_dim": int(model.config.hidden_size),
        "layer_count": layer,
        "backbone_frozen": True,
        "features": {"state": {key: state_features}, "candidate": {"name_definition": {key: candidate_features}},
        },
        "source_scope": "v0.8K training-only F100 state/candidate tables; no protected evaluation bodies",
    }
    FEATURE_DIR.mkdir(parents=True, exist_ok=True)
    torch.save(payload, FEATURES)
    receipt = {
        "status": "FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY",
        "protocol": contract["protocol"],
        "objective_graph_sha256": contract["objective_graph_sha256"],
        "phase_a_identity": auth["phase_a_identity"],
        "source_scope": payload["source_scope"],
        "input_counts": {"primary_groups": len(primary), "state_texts": len(states), "candidate_texts": len(candidates)},
        "feature_shape": {"state": list(state_features.shape), "candidate": list(candidate_features.shape)},
        "feature_hashes": {"state": tensor_sha256(state_features), "candidate": tensor_sha256(candidate_features)},
        "feature_cache": {"path": str(FEATURES), "sha256": sha256_file(FEATURES), "bytes": FEATURES.stat().st_size},
        "model": {"repo_id": adapter.MODEL_SPEC["repo_id"], "revision": adapter.MODEL_SPEC["revision"], "snapshot_directory": str(MODEL_ROOT / adapter.MODEL_NAME)},
        "representation": {"layer": "final", "pooling": "mean_full", "dtype": "bfloat16_backbone_float32_features", "max_length": 1024, "exact_length": True, "single_row": True, "padding": False},
        "runtime": {"device": device, "elapsed_seconds": time.perf_counter() - started, "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if device == "cuda" else 0},
        "backbone_frozen": True,
        "evaluation_bodies_opened": False,
        "phoenix_access": False,
    }
    (FEATURE_DIR / "extraction-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
