"""Test exact clean-process replay of one sealed step-80 1X continuation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r3-selectivity-v02")
TRAINING = RUN / "calibration-training-v02"
PREFLIGHT = RUN / "calibration-preflight-v03"
OUTPUT = RUN / "continuation-replay-v02"
RUNNER_PATH = ROOT / "experiments/jev-information-density-v08q-r3-selectivity/source/run_r3_pretreatment_calibration_v01.py"
PROBE_PATH = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
BATCHER_PATH = ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py"
OBJECTIVE_PATH = ROOT / "experiments/jev-information-density-v08q/source/q_weighted_objective_v02.py"
SCHEDULE_SEED_OFFSET = 2
PROFILE = "name_definition"


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_module(path: Path, name: str) -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def hash_training_tree(runner: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    seal_path = TRAINING / "step80-training-seal.json"
    seal = runner.read_json(seal_path)
    if seal.get("status") != "R3_ALL_48_STEP80_COMMON_HISTORIES_SEALED_BEFORE_CALIBRATION_PANEL_READ":
        raise RuntimeError("step-80 common-history training tree is not sealed")
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in seal["entries"])
    if hashlib.sha256(body.encode()).hexdigest() != seal["entries_root_sha256"]:
        raise RuntimeError("step-80 training tree seal root mismatch")
    for row in seal["entries"]:
        path = TRAINING / row["path"]
        if not path.is_file() or path.stat().st_size != row["bytes"] or sha_file(path) != row["sha256"]:
            raise RuntimeError(f"step-80 training artifact mismatch: {row['path']}")
    return seal, {row["path"]: row for row in seal["entries"]}


def epoch3_schedule(primary: list[dict[str, Any]], seed: int) -> list[dict[str, Any]]:
    group_index = {str(row["group_id"]): index for index, row in enumerate(primary)}
    if len(group_index) != 10_000:
        raise RuntimeError("primary group identities are not unique")
    ordered = sorted(group_index)
    random.Random(seed + SCHEDULE_SEED_OFFSET).shuffle(ordered)
    rows = []
    for step in range(1, 41):
        groups = ordered[(step - 1) * 256 : step * 256]
        indices = [group_index[group] for group in groups]
        aux_slots = [int(primary[index]["occurrence_index"]) // 2
                     for index in indices if primary[index]["role"] == "anchor"]
        rows.append({
            "seed": seed,
            "epoch": 3,
            "step": step,
            "global_step": 80 + step,
            "primary_occurrence_indices": indices,
            "primary_group_ids": groups,
            "auxiliary_anchor_batch_slots": aux_slots,
        })
    if len(rows) != 40 or [row["global_step"] for row in rows] != list(range(81, 121)):
        raise RuntimeError("epoch-3 continuation schedule shape mismatch")
    if sorted(i for row in rows for i in row["primary_occurrence_indices"]) != list(range(10_000)):
        raise RuntimeError("epoch-3 primary coverage mismatch")
    if sorted(i for row in rows for i in row["auxiliary_anchor_batch_slots"]) != list(range(5_000)):
        raise RuntimeError("epoch-3 auxiliary coverage mismatch")
    if any(len(row["primary_occurrence_indices"]) != (16 if row["step"] == 40 else 256) for row in rows):
        raise RuntimeError("epoch-3 batch geometry mismatch")
    return rows


def restore_rng(state: dict[str, Any]) -> None:
    random.setstate(state["python"])
    torch.set_rng_state(state["torch_cpu"].cpu())
    torch.cuda.set_rng_state_all([value.cpu() for value in state["torch_cuda"]])


def worker(label: str) -> dict[str, Any]:
    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available() or torch.cuda.get_device_name(0) != "NVIDIA GeForce RTX 3080":
        raise RuntimeError("continuation replay runtime identity mismatch")
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = True
    torch.backends.cudnn.benchmark = False
    if torch.are_deterministic_algorithms_enabled():
        raise RuntimeError("R3 calibration runner expects default nondeterministic-algorithm mode")
    runner = load_module(RUNNER_PATH, f"r3_continuation_runner_{label}")
    training_seal, training_entries = hash_training_tree(runner)
    preflight_manifest = runner.read_json(PREFLIGHT / "calibration-schedule-manifest.json")
    if sha_file(RUNNER_PATH) != preflight_manifest["runner_sha256"]:
        raise RuntimeError("bound pretreatment runner source identity mismatch")
    seeds = preflight_manifest["seed_derivation"]["seeds"]
    seed = seeds[0]
    checkpoint_rel = f"seed-{seed}/step-080.pt"
    checkpoint_entry = training_entries.get(checkpoint_rel)
    checkpoint_path = TRAINING / checkpoint_rel
    if checkpoint_entry is None or sha_file(checkpoint_path) != checkpoint_entry["sha256"]:
        raise RuntimeError("selected step-80 checkpoint not bound by training seal")

    # Revalidate bound construction inputs; this reads no predictions or treatment metrics.
    _manifest, primary, auxiliary, _base_schedule, states, candidates = runner.verify_preflight_seal()
    if runner.verify_authorities() != preflight_manifest["bindings"]:
        raise RuntimeError("frozen calibration input/code bindings do not reproduce")
    states = states.to("cuda")
    candidates = candidates.to("cuda")
    schedule = epoch3_schedule(primary, seed)
    schedule_bytes = b"".join(runner.canonical_jsonl(row) for row in schedule)
    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    if payload.get("global_step") != 80 or payload.get("event_cursor") != 80 or payload.get("auxiliary_multiplier") != 1.0:
        raise RuntimeError("fork checkpoint cursor or treatment identity mismatch")
    if payload.get("evaluation_panel_opened") is not False:
        raise RuntimeError("fork checkpoint records prior panel contact")
    expected_seed_row = [row for row in _base_schedule if row["seed"] == seed]
    if len(expected_seed_row) != 80 or payload.get("seed") != seed:
        raise RuntimeError("fork checkpoint seed/schedule mismatch")

    out_dir = OUTPUT / label
    out_dir.mkdir(parents=True, exist_ok=False)
    probe = load_module(PROBE_PATH, f"r3_replay_probe_{label}")
    batcher = load_module(BATCHER_PATH, f"r3_replay_batcher_{label}")
    objective = load_module(OBJECTIVE_PATH, f"r3_replay_objective_{label}")
    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
    head.load_state_dict(payload["head_state"], strict=True)
    head.train()
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01,
                                 betas=(0.9, 0.999), eps=1e-8, amsgrad=False)
    optimizer.load_state_dict(payload["optimizer_state"])
    if runner.state_sha(head.state_dict()) != payload["head_sha256"]:
        raise RuntimeError("restored head state differs from fork")
    if runner.tree_sha(optimizer.state_dict()) != payload["optimizer_sha256"]:
        raise RuntimeError("restored optimizer state differs from fork")
    restore_rng(payload["rng_state"])

    telemetry_path = out_dir / "continuation-telemetry.jsonl"
    with telemetry_path.open("xb") as telemetry:
        for item in schedule:
            base_rows = [primary[index] for index in item["primary_occurrence_indices"]]
            auxiliary_rows = [auxiliary[index] for index in item["auxiliary_anchor_batch_slots"]]
            batch = [runner.prepare(row) for row in base_rows] + [runner.prepare(row) for row in auxiliary_rows]
            state, candidate, gold, mask, kinds, sources = batcher.fast_tensor_batch(
                batch, states, candidates, PROFILE, "cuda", reorder=True)
            weights = torch.ones(len(batch), device="cuda")
            optimizer.zero_grad(set_to_none=True)
            logits = head(state, candidate)
            loss, brier = objective.q_weighted_loss(logits, gold, mask, kinds, sources, 0.25, weights)
            if not bool(torch.isfinite(loss).item()) or not bool(torch.isfinite(brier).item()):
                raise RuntimeError(f"nonfinite continuation loss at step {item['global_step']}")
            loss.backward()
            grad_sq = torch.zeros((), device="cuda")
            for parameter in head.parameters():
                if parameter.grad is not None:
                    if not bool(torch.isfinite(parameter.grad).all().item()):
                        raise RuntimeError(f"nonfinite continuation gradient at step {item['global_step']}")
                    grad_sq += parameter.grad.detach().float().square().sum()
            optimizer.step()
            event = {
                "seed": seed,
                "global_step": item["global_step"],
                "epoch": 3,
                "step_in_epoch": item["step"],
                "primary_indices": item["primary_occurrence_indices"],
                "auxiliary_anchor_batch_slots": item["auxiliary_anchor_batch_slots"],
                "auxiliary_multiplier": 1.0,
                "loss": float(loss.detach()),
                "brier": float(brier.detach()),
                "gradient_norm": float(grad_sq.sqrt()),
                "panel_opened": False,
            }
            telemetry.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")
            telemetry.flush()
            os.fsync(telemetry.fileno())
    if len(telemetry_path.read_bytes().splitlines()) != 40:
        raise RuntimeError("continuation telemetry row count mismatch")
    torch.cuda.synchronize()
    final_payload = {
        "status": "R3_1X_CONTINUATION_REPLAY_ONLY_NO_TREATMENT_COMPARISON",
        "seed": seed,
        "global_step": 120,
        "event_cursor": 120,
        "auxiliary_multiplier": 1.0,
        "head_state": runner.clone_cpu(head.state_dict()),
        "optimizer_state": runner.clone_cpu(optimizer.state_dict()),
        "head_sha256": runner.state_sha(head.state_dict()),
        "optimizer_sha256": runner.tree_sha(optimizer.state_dict()),
        "rng_state": runner.capture_rng(),
        "training_seal_sha256": sha_file(TRAINING / "step80-training-seal.json"),
        "step80_checkpoint_sha256": checkpoint_entry["sha256"],
        "epoch3_schedule_sha256": hashlib.sha256(schedule_bytes).hexdigest(),
        "panel_opened": False,
        "dose_branches": 1,
    }
    final_path = out_dir / "step-120-replay.pt"
    final_checkpoint_sha = runner.save_payload(final_path, final_payload)
    receipt = {
        "status": "R3_1X_CONTINUATION_REPLAY_COMPLETE",
        "replica": label,
        "seed": seed,
        "start_step": 80,
        "end_step": 120,
        "step80_training_seal_sha256": sha_file(TRAINING / "step80-training-seal.json"),
        "step80_checkpoint_sha256": checkpoint_entry["sha256"],
        "head_at_fork_sha256": payload["head_sha256"],
        "optimizer_at_fork_sha256": payload["optimizer_sha256"],
        "epoch3_schedule_sha256": hashlib.sha256(schedule_bytes).hexdigest(),
        "final_head_sha256": final_payload["head_sha256"],
        "final_optimizer_sha256": final_payload["optimizer_sha256"],
        "final_rng_tree_sha256": runner.tree_sha(final_payload["rng_state"]),
        "telemetry_sha256": sha_file(telemetry_path),
        "final_checkpoint_sha256": final_checkpoint_sha,
        "steps": 40,
        "auxiliary_multiplier": 1.0,
        "half_branch": False,
        "panel_opened": False,
        "metrics_computed": False,
    }
    write_json(out_dir / "replay-receipt.json", receipt)
    return receipt


def parent() -> int:
    if OUTPUT.exists():
        raise RuntimeError(f"refusing existing replay namespace: {OUTPUT}")
    OUTPUT.mkdir(parents=True)
    results = []
    for label in ("replica-A", "replica-B"):
        completed = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--worker", label],
            cwd=str(ROOT), text=True, capture_output=True, check=False,
        )
        stdout_path = OUTPUT / f"{label}-stdout.txt"
        stderr_path = OUTPUT / f"{label}-stderr.txt"
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        if completed.returncode != 0:
            failure = {
                "status": "R3_CONTINUATION_REPLAY_FAILED_CLOSED",
                "failed_replica": label,
                "return_code": completed.returncode,
                "stdout_sha256": sha_file(stdout_path),
                "stderr_sha256": sha_file(stderr_path),
                "no_half_branch": True,
                "panel_opened": False,
            }
            write_json(OUTPUT / "replay-disposition.json", failure)
            print(json.dumps(failure, indent=2))
            return 2
        receipt = json.loads((OUTPUT / label / "replay-receipt.json").read_text(encoding="utf-8"))
        results.append(receipt)
    fields = ("final_head_sha256", "final_optimizer_sha256", "final_rng_tree_sha256", "telemetry_sha256")
    differences = {field: [item[field] for item in results] for field in fields
                   if len({item[field] for item in results}) != 1}
    passed = not differences
    disposition = {
        "status": "R3_SAME_FORK_1X_CONTINUATION_EXACT_REPLAY_PASS" if passed else "R3_SAME_FORK_1X_CONTINUATION_REPLAY_DIVERGENCE",
        "seed": results[0]["seed"],
        "step80_checkpoint_sha256": results[0]["step80_checkpoint_sha256"],
        "schedule_sha256": results[0]["epoch3_schedule_sha256"],
        "replica_receipts": [sha_file(OUTPUT / label / "replay-receipt.json") for label in ("replica-A", "replica-B")],
        "compared_fields": list(fields),
        "differences": differences,
        "same_fork_same_cursor_same_rng": True,
        "half_branch": False,
        "panel_opened": False,
        "metrics_computed": False,
        "implication": "omit redundant A/A continuation controls" if passed else "cross dose with continuation stream in prospective study",
        "replay_runner_sha256": sha_file(Path(__file__).resolve()),
        "training_seal_sha256": sha_file(TRAINING / "step80-training-seal.json"),
    }
    write_json(OUTPUT / "replay-disposition.json", disposition)
    entries = []
    for path in sorted(OUTPUT.rglob("*")):
        if path.is_file() and path.name != "replay-root-seal.json":
            entries.append({"path": path.relative_to(OUTPUT).as_posix(), "bytes": path.stat().st_size, "sha256": sha_file(path)})
    body = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n" for row in entries)
    root = hashlib.sha256(body.encode()).hexdigest()
    write_json(OUTPUT / "replay-root-seal.json", {
        "status": disposition["status"],
        "entries": entries,
        "entries_root_sha256": root,
        "entry_count": len(entries),
        "disposition_sha256": sha_file(OUTPUT / "replay-disposition.json"),
        "training_seal_sha256": disposition["training_seal_sha256"],
        "no_half_branch": True,
        "panel_opened": False,
    })
    print(json.dumps(disposition, indent=2))
    return 0 if passed else 3


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("replica-A", "replica-B"))
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker(args.worker), indent=2))
        return 0
    return parent()


if __name__ == "__main__":
    raise SystemExit(main())
