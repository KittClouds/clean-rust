"""Resume the final locked head-masking model after verified Base/NER completion."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import head_masking
import head_masking_protocol as protocol

OUTPUT = Path(r"D:\phoenix-target-overgraph\lexi-head-masking-20260930-v2")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            h.update(block)
    return h.hexdigest()


def verify_completed_model(lock: dict, model: str) -> dict:
    folder = OUTPUT / "results" / model
    manifest = protocol.read_json(folder / "model-complete.json")
    if manifest.get("execution_lock_sha256") != lock["lock_sha256"]:
        raise RuntimeError(f"{model} completion manifest lock mismatch")
    for item in manifest["conditions"]:
        path = Path(item["path"])
        if not path.is_file() or digest(path) != item["sha256"]:
            raise RuntimeError(f"{model} condition receipt mismatch: {path}")
        result = protocol.read_json(path)
        if (result.get("truth_fields_used") is not False or
                result.get("execution_lock_sha256") != lock["lock_sha256"]):
            raise RuntimeError(f"{model} result is not the locked label-blind run")
    if len(manifest.get("conditions", [])) != lock["condition_count"]:
        raise RuntimeError(f"{model} completion manifest has the wrong condition count")
    return manifest


def main() -> None:
    lock_path = OUTPUT / "HEAD-MASKING-LOCK.json"
    lock = protocol.read_json(lock_path)
    claimed = lock.pop("lock_sha256")
    if protocol.canonical_hash(lock) != claimed:
        raise RuntimeError("execution lock digest mismatch")
    lock["lock_sha256"] = claimed
    if lock.get("status") != "LOCKED_LABEL_BLIND_INFERENCE":
        raise RuntimeError("execution lock is not label-blind")
    if digest(protocol.PROTOCOL) != lock["protocol_sha256"]:
        raise RuntimeError("protocol changed after lock")
    for name, value in lock["implementation"].items():
        if digest(HERE / name) != value:
            raise RuntimeError(f"locked implementation changed: {name}")
    sample_path = Path(lock["sampling"]["sample_file"])
    if digest(sample_path) != lock["sampling"]["sample_file_sha256"]:
        raise RuntimeError("sample selection changed after lock")
    for model, seals in lock["feature_seals"].items():
        for receipt in seals.values():
            if digest(Path(receipt["path"])) != receipt["sha256"]:
                raise RuntimeError(f"{model} feature seal changed")
    completed = {
        "base": verify_completed_model(lock, "base"),
        "ner_lora_step500": verify_completed_model(lock, "ner_lora_step500"),
    }
    resume = {
        "schema": "phoenix.lexi-head-masking/resume-receipt-v1",
        "execution_lock_sha256": claimed,
        "resumed_model": "nli_lora_step500",
        "completed_model_manifest_sha256": {
            key: digest(Path(value["conditions"][0]["path"]).parent / "model-complete.json")
            for key, value in completed.items()
        },
        "reason": "The original locked invocation completed Base and NER; NLI is resumed directly after checking their condition receipts and the unchanged protocol, implementation, sample, and feature seals.",
        "label_access": False,
        "fitting": False,
        "retrieval": False,
    }
    protocol.write_json(OUTPUT / "NLI-RESUME-RECEIPT.json", resume)
    rows, pairs = protocol.load_sample(lock)
    torch = protocol.configure_torch()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 is required")
    head_masking.summarize_model(
        torch, "nli_lora_step500", OUTPUT, lock, rows, pairs
    )
    head_masking.aggregate_results(OUTPUT, lock)
    resume["status"] = "RESUMED_MODEL_COMPLETE_LABEL_BLIND"
    protocol.write_json(OUTPUT / "NLI-RESUME-RECEIPT.json", resume)
    print(json.dumps({
        "status": resume["status"],
        "execution_lock_sha256": claimed,
        "models_complete": list(protocol.MODEL_INFO),
        "conditions_per_model": lock["condition_count"],
        "truth_fields_used": False,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
