"""Run v0.7 binding and open-world diagnostics with explicit paths."""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
V06 = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
MODEL = "lfm2.5-1.2b-base"
sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


def js(left: list[float], right: list[float]) -> float:
    midpoint = [(a + b) / 2.0 for a, b in zip(left, right)]
    return 0.5 * sum(
        a * math.log(max(1e-8, a) / max(1e-8, m))
        + b * math.log(max(1e-8, b) / max(1e-8, m))
        for a, b, m in zip(left, right, midpoint)
    )


def accuracy(rows: list[dict[str, Any]]) -> float:
    return sum(
        int(max(range(len(row["prediction"])), key=row["prediction"].__getitem__)
            == max(range(len(row["gold"])), key=row["gold"].__getitem__))
        for row in rows
    ) / max(1, len(rows))


def load_cache(path: Path) -> dict[str, Any]:
    return torch.load(path, map_location="cpu", weights_only=False)


def load_head(cache: dict[str, Any], path: Path, device: str) -> nn.Module:
    head = base.probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(device)
    head.load_state_dict(torch.load(path, map_location=device, weights_only=True))
    for parameter in head.parameters():
        parameter.requires_grad_(False)
    return head


def binding(args: argparse.Namespace) -> dict[str, Any]:
    cache = load_cache(Path(args.binding_cache))
    key = f"mean_full@{cache['layer_count']}"
    state = cache["features"]["state"][key].to(args.device)
    candidates = cache["features"]["candidate"]["opaque_definition"][key].to(args.device)
    head = load_head(cache, Path(args.head), args.device)
    groups = [group for group in cache["groups"] if group["kind"] == "choice"]
    rows = base.fast_score_groups(head, groups, state, candidates, "opaque_definition", args.device)
    ordinary = [row for row in rows if row["episode_id"].startswith("v06-binding-ordinary-")]
    adversarial = [row for row in rows if row["episode_id"].startswith("v06-binding-adversarial-")]
    left = {row["group_id"].replace("v06-binding-ordinary-", ""): row for row in ordinary}
    right = {row["group_id"].replace("v06-binding-adversarial-", ""): row for row in adversarial}
    pairs = [(left[key], right[key]) for key in sorted(left.keys() & right.keys())]
    drift = [sum(abs(a - b) for a, b in zip(first["prediction"], second["prediction"])) for first, second in pairs]
    jss = [js(first["prediction"], second["prediction"]) for first, second in pairs]
    flips = sum(
        max(range(len(first["prediction"])), key=first["prediction"].__getitem__)
        != max(range(len(second["prediction"])), key=second["prediction"].__getitem__)
        for first, second in pairs
    )
    result = {
        "protocol": "jev-lfm-architecture-variable/v0.7-B",
        "model_name": MODEL,
        "head_scale": 100000,
        "backbone_frozen": True,
        "ordinary": {"count": len(ordinary), "accuracy": accuracy(ordinary)},
        "adversarial": {"count": len(adversarial), "accuracy": accuracy(adversarial)},
        "paired": {
            "count": len(pairs),
            "mean_l1_drift": sum(drift) / max(1, len(drift)),
            "mean_js_divergence": sum(jss) / max(1, len(jss)),
            "argmax_flip_rate": flips / max(1, len(pairs)),
        },
        "binding_decomposition": {
            "ordinary_vs_adversarial_definition_reassignment": "exposed definition is gold authority",
            "identity_changed_definition_unchanged": "not separately materialized in v0.6 bank",
            "identity_unchanged_definition_changed": "represented by ordinary/adversarial pair",
            "both_changed_consistently": "not separately materialized in v0.6 bank",
            "both_changed_contradictorily": "represented by ordinary/adversarial pair",
        },
    }
    out = RUN / "reports" / "lfm-contradictory-binding.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return result


class OutsideHead(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.net = nn.Sequential(nn.Linear(hidden_dim * 3, 64), nn.GELU(), nn.Linear(64, 1))

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
    result = {}
    for path in paths:
        for episode in read_jsonl(path):
            for target in episode.get("gold_targets", []):
                other = float((target.get("target") or {}).get("other_probability") or 0.0)
                if other > 1e-12:
                    result[f"{episode['identity']['episode_id']}|{target['query_id']}"] = other
    return result


def open_groups(cache: dict[str, Any], split: str, others: dict[str, float]) -> list[dict[str, Any]]:
    return [
        group for group in cache["groups"]
        if group["split"] == split and group["open_world"] and group["kind"] == "choice"
        and f"{group['episode_id']}|{group['query_id']}" in others
    ]


def tensor_batch(groups, state, candidates, profile, device):
    width = max(len(group["candidate_indices"][profile]) for group in groups)
    indices, state_ids, lengths = [], [], []
    for group in groups:
        ids = list(group["candidate_indices"][profile])
        lengths.append(len(ids)); state_ids.append(group["state_idx"])
        indices.append(ids + [0] * (width - len(ids)))
    index_tensor = torch.tensor(indices, dtype=torch.long, device=device)
    state_tensor = state[torch.tensor(state_ids, dtype=torch.long, device=device)]
    candidate_tensor = candidates[index_tensor]
    mask = torch.tensor([[i < length for i in range(width)] for length in lengths], dtype=torch.bool, device=device)
    return state_tensor, candidate_tensor, mask


def open_score(head, outside, groups, state, candidates, others, device, profile):
    rows = []
    head.eval(); outside.eval()
    with torch.inference_mode():
        for start in range(0, len(groups), 1024):
            chunk = groups[start:start + 1024]
            s, c, mask = tensor_batch(chunk, state, candidates, profile, device)
            logits = torch.cat((head(s, c), outside(s, c).unsqueeze(1)), dim=1)
            probabilities = F.softmax(logits, dim=1)
            for row, group in enumerate(chunk):
                length = int(mask[row].sum())
                gold = list(group["gold"]) + [others[f"{group['episode_id']}|{group['query_id']}"]]
                prediction = probabilities[row, :length + 1].cpu().tolist()
                rows.append({"gold": gold, "prediction": prediction, "other_gold": gold[-1], "other_prediction": prediction[-1], "explicit_gold_mass": sum(gold[:-1]), "explicit_prediction_mass": sum(prediction[:-1])})
    return rows


def open_metrics(rows):
    count = max(1, len(rows)); nll = brier = outside_brier = mass_error = 0.0
    baseline_outside = baseline_mass = 0.0
    for row in rows:
        for gold, prediction in zip(row["gold"], row["prediction"]):
            nll -= gold * math.log(max(1e-8, prediction)); brier += (prediction - gold) ** 2
        outside_brier += (row["other_prediction"] - row["other_gold"]) ** 2
        mass_error += abs(row["explicit_prediction_mass"] - row["explicit_gold_mass"])
        baseline_outside += row["other_gold"] ** 2; baseline_mass += row["other_gold"]
    return {"count": len(rows), "nll": nll / count, "brier": brier / count, "outside_brier": outside_brier / count, "explicit_mass_absolute_error": mass_error / count, "fixed_closed_world_baseline": {"outside_brier_if_other_is_forced_zero": baseline_outside / count, "explicit_mass_absolute_error_if_renormalized": baseline_mass / count}}


def open_world(args: argparse.Namespace) -> dict[str, Any]:
    cache = load_cache(Path(args.open_world_cache)); key = f"mean_full@{cache['layer_count']}"; profile = "name_definition"
    state = cache["features"]["state"][key].to(args.device); candidates = cache["features"]["candidate"][profile][key].to(args.device)
    head = load_head(cache, Path(args.head), args.device)
    banks = V06 / "banks" / "s250k"
    others = other_map([banks / name for name in ("train.jsonl", "dev.jsonl", "test.jsonl", "external-eval.jsonl")])
    train = open_groups(cache, "train", others); dev = open_groups(cache, "dev", others); test = open_groups(cache, "test", others)
    outside = OutsideHead(cache["hidden_dim"]).to(args.device)
    optimizer = torch.optim.AdamW(outside.parameters(), lr=2e-3, weight_decay=0.01)
    for epoch in range(3):
        order = list(range(len(train))); random.Random(args.seed + epoch).shuffle(order)
        for start in range(0, len(order), 256):
            chunk = [train[index] for index in order[start:start + 256]]
            s, c, mask = tensor_batch(chunk, state, candidates, profile, args.device)
            with torch.no_grad(): fixed = head(s, c)
            logits = torch.cat((fixed, outside(s, c).unsqueeze(1)), dim=1)
            target = torch.zeros_like(logits)
            for row, group in enumerate(chunk):
                length = int(mask[row].sum()); target[row, :length] = torch.tensor(group["gold"], device=args.device)
                target[row, length] = others[f"{group['episode_id']}|{group['query_id']}"]
            optimizer.zero_grad(set_to_none=True); loss = -(target * F.log_softmax(logits, dim=1)).sum(dim=1).mean(); loss.backward(); optimizer.step()
    result = {
        "protocol": "jev-lfm-architecture-variable/v0.7-O", "model_name": MODEL, "head_scale": 100000,
        "backbone_frozen": True, "outside_head_parameters": sum(p.numel() for p in outside.parameters()),
        "train_groups": len(train), "dev": open_metrics(open_score(head, outside, dev, state, candidates, others, args.device, profile)),
        "test": open_metrics(open_score(head, outside, test, state, candidates, others, args.device, profile)),
    }
    out = RUN / "reports" / "lfm-open-world.json"; out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True); return result


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("mode", choices=("binding", "open-world")); parser.add_argument("--head", required=True); parser.add_argument("--device", default="cuda"); parser.add_argument("--seed", type=int, default=20260927)
    parser.add_argument("--binding-cache", default=str(RUN / "features" / "binding" / f"{MODEL}-features.pt")); parser.add_argument("--open-world-cache", default=str(RUN / "features" / "open-world" / f"{MODEL}-features.pt")); args = parser.parse_args()
    if args.mode == "binding": binding(args)
    else: open_world(args)


if __name__ == "__main__": main()
