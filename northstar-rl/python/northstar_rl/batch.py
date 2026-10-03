from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ._northstar_rl import NativeEnvironmentBatch


class NorthstarBatch:
    """Thin NumPy shell over one batched Rust boundary crossing."""

    def __init__(self, config_path: str | Path, lane_count: int):
        if lane_count <= 0:
            raise ValueError("lane_count must be positive")
        self._native = NativeEnvironmentBatch.open(str(Path(config_path).resolve()), lane_count)
        self.lane_count = lane_count

    def reset_many(self, seeds: list[int]) -> tuple[np.ndarray, list[dict[str, Any]]]:
        if len(seeds) != self.lane_count:
            raise ValueError("seed count must equal lane_count")
        rows = self._native.reset_many(seeds)
        observations = np.ascontiguousarray([row[0] for row in rows], dtype=np.float32)
        infos = [
            {
                "episode_id": row[1],
                "source_row_id": row[2],
                "seed_ancestry": json.loads(row[3]),
            }
            for row in rows
        ]
        return observations, infos

    def step_many(
        self, actions: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[dict[str, Any]]]:
        values = np.asarray(actions, dtype=np.float32)
        if values.shape == (self.lane_count, 1):
            values = values[:, 0]
        if values.shape != (self.lane_count,) or not np.isfinite(values).all():
            raise ValueError("actions must be finite with shape (lanes,) or (lanes, 1)")
        rows = self._native.step_many(values.tolist())
        observations = np.ascontiguousarray([row[0] for row in rows], dtype=np.float32)
        rewards = np.asarray([row[1] for row in rows], dtype=np.float64)
        terminated = np.asarray([row[2] for row in rows], dtype=np.bool_)
        truncated = np.asarray([row[3] for row in rows], dtype=np.bool_)
        infos = [
            {
                "episode_id": row[4],
                "step_id": row[5],
                "source_row_id": row[6],
                "execution_receipt_id": row[7],
                "terminal_reason": row[8],
            }
            for row in rows
        ]
        return observations, rewards, terminated, truncated, infos
