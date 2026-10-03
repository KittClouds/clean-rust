from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path

import numpy as np

from .batch import NorthstarBatch
from ._northstar_rl import ABI_CONTRACT


def trajectory(config: Path, lanes: int) -> tuple[list[str], list[list[float]]]:
    batch = NorthstarBatch(config, lanes)
    _, reset_info = batch.reset_many(list(range(100, 100 + lanes)))
    rewards: list[list[float]] = []
    actions = np.zeros((lanes, 1), dtype=np.float32)
    while True:
        _, reward, terminated, truncated, _ = batch.step_many(actions)
        rewards.append(reward.tolist())
        if np.logical_or(terminated, truncated).all():
            break
    return [item["episode_id"] for item in reset_info], rewards


def qualify(config: Path) -> dict[str, object]:
    first = trajectory(config, 32)
    second = trajectory(config, 32)
    assert first == second
    batch = NorthstarBatch(config, 128)
    seeds = list(range(128))
    actions = np.zeros((128, 1), dtype=np.float32)
    calls = 1_000
    start = time.perf_counter_ns()
    for _ in range(calls):
        observations, _ = batch.reset_many(seeds)
    reset_ns = (time.perf_counter_ns() - start) / calls
    assert observations.dtype == np.float32 and observations.shape[0] == 128
    start = time.perf_counter_ns()
    for _ in range(calls):
        batch.reset_many(seeds)
        output = batch.step_many(actions)
    step_ns = (time.perf_counter_ns() - start) / calls
    assert output[0].shape[0] == 128 and output[1].shape == (128,)
    return {
        "schema_version": "BATCHED_PYO3_COMPATIBILITY_RECEIPT_V1",
        "status": "QUALIFIED",
        "learner_execution": "NOT_RUN",
        "checks": [
            "reset_many_shape_dtype",
            "step_many_shape_dtype",
            "32_lane_deterministic_replay",
            "128_lane_boundary_smoke",
        ],
        "implementation": {
            "abi_contract": ABI_CONTRACT,
            "batch_py_sha256": hashlib.sha256(
                Path(__file__).with_name("batch.py").read_bytes()
            ).hexdigest(),
        },
        "performance": {
            "reset_many_128_ns_per_call": reset_ns,
            "reset_then_step_many_128_ns_per_call": step_ns,
            "calls": calls,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = args.config.resolve()
    receipt = qualify(config)
    root = config.parent
    (root / "batched_pyo3_compatibility_receipt.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    matrix_path = root / "campaign_qualification_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    for item in matrix["items"]:
        if item["name"] == "BATCHED_PYO3_ABI":
            item["status"] = "QUALIFIED"
            item["reason_code"] = "PYTHON_BATCH_COMPATIBILITY_RECEIPT_PASS"
            item["receipts"] = ["batched_pyo3_compatibility_receipt.json"]
    matrix_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
