from __future__ import annotations

import argparse
import json
import platform
import time
from pathlib import Path

import gymnasium
import numpy as np
import stable_baselines3
from gymnasium.utils.env_checker import check_env as gymnasium_check_env
from stable_baselines3.common.env_checker import check_env
from stable_baselines3.common.vec_env import DummyVecEnv

from .env import NorthstarEnv


def trajectory(config: Path) -> tuple[str, list[tuple[float, bool, bool, str | None]]]:
    env = NorthstarEnv.from_spec(config)
    env.reset(seed=42)
    steps: list[tuple[float, bool, bool, str | None]] = []
    index = 0
    while True:
        action = np.asarray([1.0 if index % 2 == 0 else -1.0], dtype=np.float32)
        _, reward, terminated, truncated, info = env.step(action)
        steps.append((reward, terminated, truncated, info["terminal_reason"]))
        index += 1
        if terminated or truncated:
            break
    root = env.diagnostics()["trajectory_root"]
    env.close()
    return root, steps


def qualify(config_path: Path) -> dict[str, object]:
    gym_env = NorthstarEnv.from_spec(config_path)
    gymnasium_check_env(gym_env)
    gym_env.close()
    env = NorthstarEnv.from_spec(config_path)
    check_env(env, warn=True)
    observation, reset_info = env.reset(seed=42)
    assert observation.dtype == np.float32
    assert observation.shape == env.observation_space.shape
    one = env.step(np.asarray([0.0], dtype=np.float32))
    assert isinstance(one[1], float) and isinstance(one[2], bool) and isinstance(one[3], bool)
    env.close()

    vector = DummyVecEnv([lambda: NorthstarEnv.from_spec(config_path)])
    vector.seed(42)
    vector_observation = vector.reset()
    assert vector_observation.shape == (1, *env.observation_space.shape)
    vector.step(np.asarray([[0.0]], dtype=np.float32))
    vector.close()

    first_root, first_steps = trajectory(config_path)
    second_root, second_steps = trajectory(config_path)
    assert first_root == second_root and first_steps == second_steps

    native = NorthstarEnv.from_spec(config_path)
    native.reset(seed=42)
    calls = 100_000
    start = time.perf_counter_ns()
    for _ in range(calls):
        native._native.current_observation()
    native_call_ns = (time.perf_counter_ns() - start) / calls
    start = time.perf_counter_ns()
    for _ in range(calls):
        native._observation(native._native.current_observation())
    numpy_copy_ns = (time.perf_counter_ns() - start) / calls
    native.close()

    return {
        "schema_version": "SB3_COMPATIBILITY_RECEIPT_V1",
        "status": "QUALIFIED",
        "learner_execution": "NOT_RUN_PROHIBITED_BY_ENVIRONMENT_QUALIFICATION_GATE",
        "checks": [
            "gymnasium_env_checker",
            "observation_space_dtype_shape",
            "action_space_dtype_shape",
            "reset_step_contract",
            "terminated_truncated_contract",
            "deterministic_seeded_replay",
            "dummy_vec_env_smoke",
        ],
        "diagnostic_warnings": [
            "observation Box is intentionally unbounded because feature ranges are contract-specific",
            "alternative render modes are not checked through gymnasium.make because this package uses from_spec",
        ],
        "environment_id": reset_info["environment_id"],
        "trajectory_root": first_root,
        "versions": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "gymnasium": gymnasium.__version__,
            "stable_baselines3": stable_baselines3.__version__,
        },
        "performance": {
            "native_current_observation_ns_per_call": native_call_ns,
            "native_to_numpy_observation_ns_per_call": numpy_copy_ns,
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
    receipt_path = root / "sb3_compatibility_receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    matrix_path = root / "qualification_matrix.json"
    if not matrix_path.exists():
        matrix_path = root / "joint_qualification_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    for item in matrix["items"]:
        if item["name"] in {"PYO3_BRIDGE", "GYMNASIUM_CONTRACT", "SB3_ENV_COMPATIBILITY"}:
            item["status"] = "QUALIFIED"
            item["reason_code"] = "PYTHON_QUALIFICATION_RECEIPT_PASS"
            item["receipts"] = ["sb3_compatibility_receipt.json"]
    matrix_path.write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
