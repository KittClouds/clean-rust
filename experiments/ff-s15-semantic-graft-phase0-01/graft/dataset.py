from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import torch

from .contracts import canon_hash, sha_file, supervision_abi


class PackedBank:
    """Read-only memory mapped arrays; ragged candidates padded only per batch."""

    def __init__(self, folder: Path, substrate: str, config: dict, verify: bool = True):
        self.folder = folder
        self.manifest = json.loads((folder / "manifest.json").read_text())
        if self.manifest["config_sha256"] != canon_hash(config):
            raise ValueError("prepared dataset config identity mismatch")
        if self.manifest["supervision_abi_sha256"] != canon_hash(supervision_abi()):
            raise ValueError("prepared supervision ABI identity mismatch")
        if verify:
            for name, digest in self.manifest["files"].items():
                if sha_file(folder / name) != digest:
                    raise ValueError(f"dataset hash mismatch: {name}")
        self.H = np.load(folder / f"H_{substrate}.npy", mmap_mode="r", allow_pickle=False)
        self.arrays = {n: np.load(folder / f"{n}.npy", mmap_mode="r", allow_pickle=False)
                       for n in ("global_y", "global_available", "candidate_y", "candidate_available", "actions", "offsets")}
        with (folder / "rows.jsonl").open(encoding="utf-8") as src:
            self.rows = [json.loads(line) for line in src if line.strip()]
        if len(self.H) != len(self.rows) or len(self.arrays["offsets"]) != len(self.rows) + 1:
            raise ValueError("prepared data row counts disagree")
        if len({r["world_id"] for r in self.rows}) != len(self.rows):
            raise ValueError("duplicate prepared world_id")
        self.representation_id = self.manifest["representations"][substrate]["representation_id"]

    def __len__(self):
        return len(self.rows)

    def batch(self, indices, device="cpu") -> dict:
        ii = np.asarray(indices, dtype=np.int64)
        offsets = self.arrays["offsets"]
        lengths = offsets[ii + 1] - offsets[ii]
        maximum = int(lengths.max())
        n = len(ii)
        a = np.zeros((n, maximum, 5), np.int64)
        y = np.zeros((n, maximum, 7), np.float32)
        available = np.zeros((n, maximum, 7), np.bool_)
        mask = np.zeros((n, maximum), np.bool_)
        for b, i in enumerate(ii):
            start, end = int(offsets[i]), int(offsets[i + 1])
            count = end - start
            a[b, :count] = self.arrays["actions"][start:end]
            y[b, :count] = self.arrays["candidate_y"][start:end]
            available[b, :count] = self.arrays["candidate_available"][start:end]
            mask[b, :count] = True
        payload = {"H": np.asarray(self.H[ii]), "A": a, "candidate_mask": mask,
                   "global_y": np.asarray(self.arrays["global_y"][ii]),
                   "global_available": np.asarray(self.arrays["global_available"][ii]),
                   "candidate_y": y, "candidate_available": available}
        return {k: torch.from_numpy(v).to(device) for k, v in payload.items()}


def assert_disjoint(*populations: PackedBank):
    seen = set()
    for dataset in populations:
        groups = {r["group_id"] for r in dataset.rows}
        if groups & seen:
            raise ValueError("canonical worlds overlap data partitions")
        seen.update(groups)


def training_normalizer(dataset: PackedBank):
    count = len(dataset)
    total = np.zeros(dataset.H.shape[-1], np.float64)
    squares = np.zeros_like(total)
    for start in range(0, count, 256):
        x = np.asarray(dataset.H[start:start + 256], dtype=np.float64)
        total += x.sum(0)
        squares += np.square(x).sum(0)
    mean = total / count
    std = np.sqrt(np.maximum(0.0, squares / count - np.square(mean)))
    std[std < 1e-6] = 1.0
    return torch.from_numpy(mean.astype(np.float32)), torch.from_numpy(std.astype(np.float32))
