"""Trains the dedicated SHOULD_ASK heads on TRAIN with the Rung 0 recipe, and runs them on DEV features with numpy (float64)."""
from __future__ import annotations

import json

import numpy as np

from .common import (BATCH, BANK, DEV_START, DEV_STOP, EPOCHS, HIDDEN, LEARNING_RATE, PRIMITIVES, SEED, SWEEP, TRAIN_ROWS, WEIGHT_DECAY, canon, rung0, sha256_file)


def load_train_labels() -> tuple:
    """SHOULD_ASK per TRAIN row (bool), plus the TRAIN file's hash checked against the sweep's source lock."""
    with (SWEEP / "rowmap.jsonl").open(encoding="utf-8") as source:
        row_ids = []
        for index, line in enumerate(source):
            if index >= TRAIN_ROWS:
                break
            meta = json.loads(line)
            if meta["split"] != "TRAIN" or meta["idx"] != index:
                raise RuntimeError("TRAIN rows are not a contiguous prefix of the cache")
            row_ids.append(meta["row_id"])
    labels = np.zeros(TRAIN_ROWS, dtype=bool)
    path = BANK / "inputs" / "TRAIN.jsonl"
    with path.open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            row = json.loads(line)
            if row["world_id"] != row_ids[index]:
                raise RuntimeError(f"TRAIN row {index} does not line up with the cache rowmap")
            labels[index] = row["labels"]["policy"]["decision"] == "ASK"
    if index + 1 != TRAIN_ROWS:
        raise RuntimeError("TRAIN row count mismatch")
    lock = json.loads((SWEEP / "source-lock.json").read_text(encoding="utf-8"))
    expected = next(f["sha256"] for f in lock["files"] if f["split"] == "TRAIN")
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError("TRAIN.jsonl does not match the sweep's source lock")
    return labels, actual


def features(surface: str, start: int, stop: int) -> np.ndarray:
    def part(name):
        return np.array(np.load(SWEEP / "features" / f"{name}.npy", mmap_mode="r", allow_pickle=False)[start:stop], dtype=np.float32)  # a copy: mmap views are read-only

    if surface == "middle_plus_final":
        return np.concatenate((part("middle_final"), part("final_token")), axis=1)
    if surface == "final_plus_mean":
        return np.concatenate((part("final_token"), part("full_mean")), axis=1)
    return part(PRIMITIVES[surface][0])


def train_head(surface: str, kind: str, labels: np.ndarray) -> dict:
    """AdamW, 8 epochs, batch 2048, lr 1e-3, wd 1e-4, seed 20260929, unweighted BCE. Returns float32 weights and the loss curve."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F

    scaler = rung0.load_head(surface, "decision")  # the surface's train-only Rung 0 standardization
    x = features(surface, 0, TRAIN_ROWS)
    x -= scaler["mean"]
    x /= scaler["scale"]
    device = "cuda:0"
    xt = torch.from_numpy(np.ascontiguousarray(x)).to(device)
    yt = torch.as_tensor(labels, dtype=torch.float32, device=device)
    del x
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    dim = xt.shape[1]
    net = (nn.Linear(dim, 1) if kind == "linear" else nn.Sequential(nn.Linear(dim, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, 1))).to(device)
    prior = float(labels.mean())  # preregistration addendum 1: start the output bias at the TRAIN prior logit; the fixed budget cannot reach it from zero
    with torch.no_grad():
        (net.bias if kind == "linear" else net[2].bias).fill_(float(np.log(prior / (1.0 - prior))))
    optimizer = torch.optim.AdamW(net.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY, foreach=False)
    losses = []
    for epoch in range(EPOCHS):
        order = np.random.default_rng(SEED + epoch).permutation(TRAIN_ROWS)
        total, steps = 0.0, 0
        for begin in range(0, TRAIN_ROWS, BATCH):
            ids = torch.as_tensor(order[begin:begin + BATCH], dtype=torch.long, device=device)
            loss = F.binary_cross_entropy_with_logits(net(xt.index_select(0, ids)).squeeze(1), yt.index_select(0, ids))
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            total += float(loss.detach().cpu())
            steps += 1
        losses.append(total / steps)
    with torch.no_grad():
        probe = torch.sigmoid(net(xt[:2000]).squeeze(1)).double().cpu().numpy()
    if kind == "linear":
        weights = {"w": net.weight.detach().cpu().numpy()[0], "b": net.bias.detach().cpu().numpy()}
    else:
        weights = {"w1": net[0].weight.detach().cpu().numpy().T.copy(), "b1": net[0].bias.detach().cpu().numpy(), "w2": net[2].weight.detach().cpu().numpy()[0], "b2": net[2].bias.detach().cpu().numpy()}
    del xt, yt, net, optimizer
    torch.cuda.empty_cache()
    return {"weights": {k: np.ascontiguousarray(v, "<f4") for k, v in weights.items()}, "epoch_losses": losses, "torch_probe": probe}


def probabilities(weights: dict, kind: str, surface: str, start: int, stop: int) -> np.ndarray:
    """P(SHOULD_ASK) in float64 with numpy, for rows [start, stop) of the cache."""
    scaler = rung0.load_head(surface, "decision")
    z = (features(surface, start, stop).astype(np.float64) - scaler["mean"].astype(np.float64)) / scaler["scale"].astype(np.float64)
    if kind == "linear":
        logit = z @ weights["w"].astype(np.float64) + float(weights["b"][0])
    else:
        hidden = np.maximum(z @ weights["w1"].astype(np.float64) + weights["b1"].astype(np.float64), 0.0)
        logit = hidden @ weights["w2"].astype(np.float64) + float(weights["b2"][0])
    return 1.0 / (1.0 + np.exp(-np.clip(logit, -60, 60)))


def quantize(p: np.ndarray) -> np.ndarray:
    """[P(DO_NOT_ASK), P(SHOULD_ASK)] as integer ppm summing to exactly 1,000,000."""
    return np.array([canon.quantize_probabilities([1.0 - float(v), float(v)]) for v in p], dtype=np.int32)


def dev_probabilities(weights: dict, kind: str, surface: str) -> np.ndarray:
    return probabilities(weights, kind, surface, DEV_START, DEV_STOP)
