from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from ._northstar_rl import open_environment


class NorthstarEnv(gym.Env[np.ndarray, np.ndarray]):
    """Thin, allocation-conscious adapter over the authoritative Rust kernel."""

    metadata = {"render_modes": ["ansi"], "render_fps": 0}

    def __init__(self, config_path: str | Path, render_mode: str | None = None) -> None:
        super().__init__()
        if render_mode not in (None, "ansi"):
            raise ValueError("NorthstarEnv supports only render_mode='ansi'")
        self._config_path = str(Path(config_path).resolve())
        self._native = open_environment(self._config_path)
        self._seed = 0
        self.render_mode = render_mode
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=tuple(self._native.observation_shape()),
            dtype=np.float32,
        )
        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(1,),
            dtype=np.float32,
        )

    @classmethod
    def from_spec(cls, path: str | Path, render_mode: str | None = None) -> "NorthstarEnv":
        return cls(path, render_mode=render_mode)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        if seed is not None:
            if seed < 0:
                raise ValueError("seed must be non-negative")
            self._seed = int(seed)
        episode_id = None if options is None else options.get("episode_id")
        observation, actual_episode_id, source_row_id, ancestry_json = self._native.reset_episode(
            episode_id,
            self._seed,
        )
        return self._observation(observation), {
            "episode_id": actual_episode_id,
            "step_id": 0,
            "source_row_id": source_row_id,
            "environment_id": self._native.environment_id(),
            "seed_ancestry": json.loads(ancestry_json),
        }

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        value = np.asarray(action, dtype=np.float32)
        if value.shape != (1,):
            raise ValueError(f"action shape must be (1,), got {value.shape}")
        if not np.isfinite(value[0]) or value[0] < -1.0 or value[0] > 1.0:
            raise ValueError("action must be finite and in [-1, 1]")
        result = self._native.step(float(value[0]))
        observation, reward, terminated, truncated = result[:4]
        info = {
            "episode_id": result[4],
            "step_id": result[5],
            "source_row_id": result[6],
            "execution_receipt_id": result[7],
            "terminal_reason": result[8],
        }
        return self._observation(observation), float(reward), bool(terminated), bool(truncated), info

    def render(self) -> str | None:
        if self.render_mode == "ansi":
            return self._native.render()
        return None

    def close(self) -> None:
        if getattr(self, "_native", None) is not None:
            self._native.close_environment()

    def diagnostics(self) -> dict[str, Any]:
        return json.loads(self._native.diagnostics())

    def _observation(self, values: list[float]) -> np.ndarray:
        observation = np.asarray(values, dtype=np.float32).reshape(self.observation_space.shape)
        if not observation.flags.c_contiguous:
            observation = np.ascontiguousarray(observation)
        return observation
