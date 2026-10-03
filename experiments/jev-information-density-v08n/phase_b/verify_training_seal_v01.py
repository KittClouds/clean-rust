"""Independent read-only validation of the v0.8N unevaluated training seal."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(memoryview(value.numpy()).cast("B"))
    return digest.hexdigest()


def verify() -> dict[str, Any]:
    event = read_json(PHASE / "phase-b-authorization-event-v01.json")
    contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    analysis = read_json(PHASE / "phase-b-analysis-contract-v01.json")
    if event.get("phase_b_authorized") is not True or event.get("status") != "PHASE_B_AUTHORIZED":
        raise RuntimeError("Phase-B authorization event is not active")
    for relative, expected in event["implementation_bindings"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"authorized source changed: {relative}")
    for name, path in (("run_contract", PHASE / "phase-b-run-contract-v01.json"), ("analysis_contract", PHASE / "phase-b-analysis-contract-v01.json")):
        if sha256_file(path) != event["bindings"][name]["sha256"]:
            raise RuntimeError(f"frozen {name} changed")

    seal_path = RUN / "training-seal-manifest.json"
    tree_path = RUN / "checkpoint-hash-tree.json"
    order_path = RUN / "execution-order.json"
    seal = read_json(seal_path)
    tree = read_json(tree_path)
    order = read_json(order_path)
    if seal.get("status") != "ALL_NINE_RUNS_TRAINED_SEALED_UNEVALUATED":
        raise RuntimeError("training seal status mismatch")
    if seal.get("evaluation_access") is not False or seal.get("protected_panel_opened") is not False:
        raise RuntimeError("training seal claims evaluation access")
    if seal.get("checkpoint_count") != 27 or seal.get("run_count") != 9:
        raise RuntimeError("training run/checkpoint count mismatch")
    if sha256_file(tree_path) != seal.get("checkpoint_hash_tree_sha256"):
        raise RuntimeError("checkpoint tree file hash mismatch")
    if sha256_file(order_path) != seal.get("execution_order_sha256") or order.get("status") != "COMPLETE":
        raise RuntimeError("execution-order receipt mismatch")
    expected_order = contract["training"]["global_execution_order"]
    if order.get("completed_order") != expected_order or seal.get("execution_order") != expected_order:
        raise RuntimeError("run order differs from frozen contract")

    entries = tree.get("entries", [])
    if len(entries) != tree.get("entry_count") or len({item["path"] for item in entries}) != len(entries):
        raise RuntimeError("hash tree cardinality/uniqueness failure")
    for item in entries:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"hash-tree file mismatch: {path}")
    if entries != seal.get("hash_tree_entries"):
        raise RuntimeError("seal manifest and detached hash tree entries differ")

    checkpoint_count = 0
    run_count = 0
    for seed in contract["training"]["seed_set"]:
        template_path = RUN / "head-templates" / f"seed-{seed}.pt"
        template = torch.load(template_path, map_location="cpu", weights_only=True)
        template_hash = state_digest(template["state_dict"])
        if template.get("seed") != seed or template.get("state_sha256") != template_hash:
            raise RuntimeError(f"paired seed template identity/hash mismatch: {seed}")
        for arm in contract["arms"]["order"]:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            integrity = read_json(run_dir / "run-integrity.json")
            if integrity.get("status") != "TRAINING_COMPLETE_UNEVALUATED" or integrity.get("seed") != seed or integrity.get("arm") != arm:
                raise RuntimeError(f"run integrity identity mismatch: {seed}/{arm}")
            if integrity.get("evaluation_access") is not False or integrity.get("phoenix_access") is not False:
                raise RuntimeError(f"run crossed prohibited boundary: {seed}/{arm}")
            if integrity.get("epochs") != 3 or integrity.get("optimizer_steps") != 120:
                raise RuntimeError(f"run budget mismatch: {seed}/{arm}")
            if integrity.get("initial_head_sha256") != template_hash:
                raise RuntimeError(f"paired initialization mismatch: {seed}/{arm}")
            config_path = run_dir / "run-config.json"
            if not config_path.is_file() or sha256_file(config_path) != integrity.get("run_config_sha256"):
                raise RuntimeError(f"run configuration hash mismatch: {seed}/{arm}")
            config = read_json(config_path)
            if config.get("authorization_event_sha256") != sha256_file(PHASE / "phase-b-authorization-event-v01.json"):
                raise RuntimeError(f"run was created under a different authorization: {seed}/{arm}")
            if config.get("run_contract_sha256") != event["bindings"]["run_contract"]["sha256"] or config.get("analysis_contract_sha256") != event["bindings"]["analysis_contract"]["sha256"]:
                raise RuntimeError(f"run contract binding mismatch: {seed}/{arm}")
            for item in integrity.get("epoch_checkpoints", []):
                path = run_dir / item["path"]
                if not path.is_file() or sha256_file(path) != item["sha256"]:
                    raise RuntimeError(f"checkpoint hash mismatch: {path}")
                checkpoint_count += 1
            if len(integrity.get("epoch_checkpoints", [])) != 3:
                raise RuntimeError(f"epoch checkpoint count mismatch: {seed}/{arm}")
            terminal_path = run_dir / "epoch-3-terminal.pt"
            terminal = torch.load(terminal_path, map_location="cpu", weights_only=False)
            if terminal.get("seed") != seed or terminal.get("arm") != arm or terminal.get("epoch") != 3:
                raise RuntimeError(f"terminal checkpoint identity mismatch: {seed}/{arm}")
            if state_digest(terminal["head_state"]) != integrity.get("terminal_head_sha256"):
                raise RuntimeError(f"terminal head-state digest mismatch: {seed}/{arm}")
            events = read_jsonl(run_dir / "training-events.jsonl")
            step_events = [row for row in events if row.get("event") == "training_step"]
            if len(step_events) != 120 or any(row.get("seed") != seed or row.get("arm") != arm for row in step_events):
                raise RuntimeError(f"step telemetry identity/count mismatch: {seed}/{arm}")
            for epoch in range(1, 4):
                epoch_steps = [row for row in step_events if row.get("epoch") == epoch]
                if len(epoch_steps) != 40 or [row.get("step") for row in epoch_steps] != list(range(1, 41)):
                    raise RuntimeError(f"epoch step telemetry mismatch: {seed}/{arm}/{epoch}")
                if sum(int(row.get("primary_events", 0)) for row in epoch_steps) != 10_000 or sum(int(row.get("auxiliary_events", 0)) for row in epoch_steps) != 5_000:
                    raise RuntimeError(f"epoch event exposure mismatch: {seed}/{arm}/{epoch}")
            run_count += 1
    if run_count != 9 or checkpoint_count != 27:
        raise RuntimeError(f"verified count mismatch: {run_count} runs/{checkpoint_count} checkpoints")
    return {
        "status": "TRAINING_SEAL_INDEPENDENTLY_VALIDATED_UNEVALUATED",
        "authorization_event_sha256": sha256_file(PHASE / "phase-b-authorization-event-v01.json"),
        "training_seal_sha256": sha256_file(seal_path), "checkpoint_hash_tree_sha256": sha256_file(tree_path),
        "run_count": run_count, "checkpoint_count": checkpoint_count,
        "evaluation_access": False, "protected_panel_opened": False, "newtight_access": False, "phoenix_access": False,
    }


def main() -> int:
    result = verify()
    print(json.dumps(result, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
