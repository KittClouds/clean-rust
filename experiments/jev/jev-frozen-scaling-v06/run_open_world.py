"""Train and evaluate a small outside-candidate score on fixed 250k heads."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
FEATURES = RUN / "features"
OUT = RUN / "open-world"
sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


class OutsideHead(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(hidden_dim * 3, 64),
            nn.GELU(),
            nn.Linear(64, 1),
        )

    def forward(self, state: torch.Tensor, candidates: torch.Tensor) -> torch.Tensor:
        mean = candidates.mean(dim=1)
        maximum = candidates.max(dim=1).values
        return self.net(torch.cat((state, mean, maximum), dim=-1)).squeeze(-1)


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def other_map(paths: list[Path]) -> dict[str, float]:
    result: dict[str, float] = {}
    for path in paths:
        for episode in read_jsonl(path):
            for target in episode.get("gold_targets", []):
                body = target.get("target") or {}
                other = float(body.get("other_probability") or 0.0)
                if other > 1e-12:
                    result[f"{episode['identity']['episode_id']}|{target['query_id']}"] = other
    return result


def open_groups(cache: dict[str, Any], split: str, others: dict[str, float]) -> list[dict[str, Any]]:
    return [
        group for group in cache["groups"]
        if group["split"] == split
        and group["open_world"]
        and group["kind"] == "choice"
        and f"{group['episode_id']}|{group['query_id']}" in others
    ]


def tensor_batch(groups, state, candidates, profile, device):
    width = max(len(group["candidate_indices"][profile]) for group in groups)
    indices = []
    gold = []
    lengths = []
    state_ids = []
    for group in groups:
        values = list(group["gold"])
        ids = list(group["candidate_indices"][profile])
        lengths.append(len(ids))
        indices.append(ids + [0] * (width - len(ids)))
        gold.append(values + [0.0] * (width - len(values)))
        state_ids.append(group["state_idx"])
    index_tensor = torch.tensor(indices, dtype=torch.long, device=device)
    state_tensor = state[torch.tensor(state_ids, dtype=torch.long, device=device)]
    candidate_tensor = candidates[index_tensor]
    mask = torch.tensor(
        [[index < length for index in range(width)] for length in lengths],
        dtype=torch.bool, device=device,
    )
    return state_tensor, candidate_tensor, mask, gold


def score(head, outside, groups, state, candidates, others, device, profile):
    rows = []
    head.eval()
    outside.eval()
    with torch.inference_mode():
        for start in range(0, len(groups), 1024):
            chunk = groups[start:start + 1024]
            s, c, mask, _ = tensor_batch(chunk, state, candidates, profile, device)
            candidate_logits = head(s, c)
            outside_logit = outside(s, c).unsqueeze(1)
            all_logits = torch.cat((candidate_logits, outside_logit), dim=1)
            probabilities = F.softmax(all_logits, dim=1)
            for row, group in enumerate(chunk):
                length = int(mask[row].sum())
                gold = list(group["gold"]) + [others[f"{group['episode_id']}|{group['query_id']}"]]
                prediction = probabilities[row, :length + 1].cpu().tolist()
                rows.append({
                    "group_id": group["group_id"],
                    "episode_id": group["episode_id"],
                    "gold": gold,
                    "prediction": prediction,
                    "explicit_gold_mass": sum(gold[:-1]),
                    "explicit_prediction_mass": sum(prediction[:-1]),
                    "other_gold": gold[-1],
                    "other_prediction": prediction[-1],
                })
    return rows


def metrics(rows):
    if not rows:
        return {"count": 0}
    nll = 0.0
    brier = 0.0
    outside_brier = 0.0
    mass_error = 0.0
    baseline_outside_brier = 0.0
    baseline_mass_error = 0.0
    for row in rows:
        for gold, prediction in zip(row["gold"], row["prediction"]):
            nll -= gold * math.log(max(1e-8, prediction))
            brier += (prediction - gold) ** 2
        outside_brier += (row["other_prediction"] - row["other_gold"]) ** 2
        mass_error += abs(row["explicit_prediction_mass"] - row["explicit_gold_mass"])
        baseline_outside_brier += row["other_gold"] ** 2
        baseline_mass_error += row["other_gold"]
    count = len(rows)
    return {
        "count": count,
        "nll": nll / count,
        "brier": brier / count,
        "outside_brier": outside_brier / count,
        "explicit_mass_absolute_error": mass_error / count,
        "fixed_closed_world_baseline": {
            "representable": False,
            "outside_brier_if_other_is_forced_zero": baseline_outside_brier / count,
            "explicit_mass_absolute_error_if_renormalized": baseline_mass_error / count,
        },
    }


def run(model_name: str, device: str, seed: int) -> dict[str, Any]:
    cache = torch.load(FEATURES / f"{model_name}-features.pt", map_location="cpu", weights_only=False)
    profile = "name_definition"
    feature_key = f"mean_full@{cache['layer_count']}"
    state = cache["features"]["state"][feature_key].to(device)
    candidates = cache["features"]["candidate"][profile][feature_key].to(device)
    head = base.probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(device)
    state_path = RUN / "head-runs" / model_name / f"{model_name}-s250k-S100.pt"
    head.load_state_dict(torch.load(state_path, map_location=device, weights_only=True))
    for parameter in head.parameters():
        parameter.requires_grad_(False)
    others = other_map([
        RUN / "banks" / "s250k" / "train.jsonl",
        RUN / "banks" / "s250k" / "dev.jsonl",
        RUN / "banks" / "s250k" / "test.jsonl",
        RUN / "banks" / "s250k" / "external-eval.jsonl",
    ])
    train = open_groups(cache, "train", others)
    dev = open_groups(cache, "dev", others)
    test = open_groups(cache, "test", others)
    if not train:
        raise RuntimeError(f"{model_name}: no open-world training groups")
    outside = OutsideHead(cache["hidden_dim"]).to(device)
    optimizer = torch.optim.AdamW(outside.parameters(), lr=2e-3, weight_decay=0.01)
    outside.train()
    for epoch in range(3):
        order = list(range(len(train)))
        random.Random(seed + epoch).shuffle(order)
        for start in range(0, len(order), 256):
            chunk = [train[index] for index in order[start:start + 256]]
            s, c, mask, gold_rows = tensor_batch(chunk, state, candidates, profile, device)
            with torch.no_grad():
                fixed_logits = head(s, c)
            outside_logit = outside(s, c).unsqueeze(1)
            logits = torch.cat((fixed_logits, outside_logit), dim=1)
            targets = torch.zeros_like(logits)
            for row, group in enumerate(chunk):
                length = int(mask[row].sum())
                targets[row, :length] = torch.tensor(group["gold"], device=device)
                targets[row, length] = others[f"{group['episode_id']}|{group['query_id']}"]
            optimizer.zero_grad(set_to_none=True)
            loss = -(targets * F.log_softmax(logits, dim=1)).sum(dim=1).mean()
            loss.backward()
            optimizer.step()
    dev_rows = score(head, outside, dev, state, candidates, others, device, profile)
    test_rows = score(head, outside, test, state, candidates, others, device, profile)
    result = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-O",
        "model_name": model_name,
        "backbone_frozen": True,
        "candidate_head": "v0.6-S 250k frozen compatibility head",
        "outside_head_parameters": sum(p.numel() for p in outside.parameters()),
        "train_groups": len(train),
        "dev": metrics(dev_rows),
        "test": metrics(test_rows),
        "source_counts": dict(Counter(group["probability_source"] for group in train)),
    }
    output = OUT / f"{model_name}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--seed", type=int, default=20260926)
    args = parser.parse_args()
    run(args.model_name, args.device, args.seed)


if __name__ == "__main__":
    main()
