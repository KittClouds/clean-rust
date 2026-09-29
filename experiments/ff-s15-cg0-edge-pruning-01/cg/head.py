"""The frozen edge-existence observer (middle_plus_final / tiny_mlp), evaluated exactly as delivered but in cached-projection form.

Her head is Linear(4096 -> 128), GELU, Dropout, Linear(128 -> 2) over [a; b], the two scaler-normalised entity vectors. Its first layer is linear, so
  W1 [a; b] + c = W1a a + W1b b + c
and each entity's two 128-d projections can be computed once and reused for every pair it takes part in. That is mathematically the same head; the integrity gate
checks that it reproduces Lexi's sampled-pair AUC on all nine splits. Dropout is off (evaluation).
"""
from __future__ import annotations

import numpy as np

from .common import OUT, SURFACE, TASK, HEAD, read_json

DIM = 1024  # per surface half; middle_plus_final concatenates the middle-layer and final-layer mention means


class FrozenEdgeHead:
    def __init__(self, device: str | None = None):
        import torch

        self.torch = torch
        self.device = device or ("cuda:0" if torch.cuda.is_available() else "cpu")
        checkpoint = torch.load(OUT / "models" / f"{TASK}-{SURFACE}-{HEAD}.pt", map_location="cpu", weights_only=True)
        state = checkpoint["state_dict"]
        w1, b1 = state["mlp.0.weight"].double(), state["mlp.0.bias"].double()
        self.w1a, self.w1b, self.b1 = (w1[:, : 2 * DIM].to(self.device), w1[:, 2 * DIM:].to(self.device), b1.to(self.device))
        self.w2, self.b2 = state["mlp.3.weight"].double().to(self.device), state["mlp.3.bias"].double().to(self.device)
        scaler = np.load(OUT / "scalers" / f"local-{SURFACE}.npz", allow_pickle=False)
        self.mean, self.scale = scaler["mean"].astype(np.float32), scaler["scale"].astype(np.float32)
        self.middle = np.load(OUT / "features" / "entity_middle_mean.npy", mmap_mode="r", allow_pickle=False)
        self.final = np.load(OUT / "features" / "entity_final_mean.npy", mmap_mode="r", allow_pickle=False)

    def project(self, entity_index: np.ndarray, chunk: int = 32768) -> tuple:
        """Per-entity 128-d projections (as source, as target) for the given entity indexes, in float64."""
        torch = self.torch
        left, right = [], []
        for start in range(0, len(entity_index), chunk):
            idx = entity_index[start:start + chunk]
            order = np.argsort(idx, kind="stable")  # sorted reads from the memory map
            rows = np.concatenate((np.asarray(self.middle[idx[order]], dtype=np.float32), np.asarray(self.final[idx[order]], dtype=np.float32)), axis=1)
            rows = (rows - self.mean) / self.scale
            inverse = np.empty_like(order)
            inverse[order] = np.arange(len(order))
            x = torch.from_numpy(np.ascontiguousarray(rows[inverse])).to(self.device).double()
            left.append((x @ self.w1a.T).cpu().numpy())
            right.append((x @ self.w1b.T).cpu().numpy())
        return np.concatenate(left), np.concatenate(right)

    def score(self, a_index: np.ndarray, b_index: np.ndarray, batch: int = 262144) -> np.ndarray:
        """The head's score for each ordered pair (a, b): the class-1 (edge) logit, exactly the column her metric uses (`logits[:, 1]`)."""
        torch = self.torch
        unique, inverse = np.unique(np.concatenate((a_index, b_index)), return_inverse=True)
        pa, pb = self.project(unique)
        a_slot, b_slot = inverse[: len(a_index)], inverse[len(a_index):]
        out = np.empty(len(a_index), dtype=np.float64)
        pa_t, pb_t = torch.from_numpy(pa).to(self.device), torch.from_numpy(pb).to(self.device)
        for start in range(0, len(a_index), batch):
            sl = slice(start, start + batch)
            h = torch.nn.functional.gelu(pa_t[torch.from_numpy(a_slot[sl]).to(self.device)] + pb_t[torch.from_numpy(b_slot[sl]).to(self.device)] + self.b1)
            out[sl] = (h @ self.w2.T + self.b2)[:, 1].cpu().numpy()
        return out


def auc(scores: np.ndarray, labels: np.ndarray) -> float:
    """Mann-Whitney AUC with average ranks for ties."""
    order = np.argsort(scores, kind="stable")
    s = scores[order]
    ranks = np.empty(len(s))
    i = 0
    while i < len(s):
        j = i
        while j + 1 < len(s) and s[j + 1] == s[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2 + 1
        i = j + 1
    y = labels.astype(bool)
    positives, negatives = int(y.sum()), int((~y).sum())
    return float((ranks[y].sum() - positives * (positives + 1) / 2) / (positives * negatives))
