"""Score paired ordinary/adversarial opaque-definition episodes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v06")
sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


def js_divergence(left: list[float], right: list[float]) -> float:
    def kl(a, b):
        return sum(x * __import__("math").log(max(1e-8, x / max(1e-8, y))) for x, y in zip(a, b))
    midpoint = [(a + b) / 2.0 for a, b in zip(left, right)]
    return 0.5 * (kl(left, midpoint) + kl(right, midpoint))


def accuracy(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    correct = 0
    for row in rows:
        prediction = max(range(len(row["prediction"])), key=row["prediction"].__getitem__)
        target = max(range(len(row["gold"])), key=row["gold"].__getitem__)
        correct += int(prediction == target)
    return correct / len(rows)


def run_model(model_name: str, device: str) -> dict[str, Any]:
    cache = torch.load(
        RUN / "binding-features" / f"{model_name}-features.pt",
        map_location="cpu", weights_only=False,
    )
    feature_key = f"mean_full@{cache['layer_count']}"
    state = cache["features"]["state"][feature_key].to(device)
    candidates = cache["features"]["candidate"]["opaque_definition"][feature_key].to(device)
    head = base.probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(device)
    head.load_state_dict(torch.load(
        RUN / "head-runs" / model_name / f"{model_name}-s250k-S100.pt",
        map_location=device, weights_only=True,
    ))
    groups = [group for group in cache["groups"] if group["kind"] == "choice"]
    rows = base.fast_score_groups(head, groups, state, candidates, "opaque_definition", device)
    ordinary = [row for row in rows if row["episode_id"].startswith("v06-binding-ordinary-")]
    adversarial = [row for row in rows if row["episode_id"].startswith("v06-binding-adversarial-")]
    left = {row["group_id"].replace("v06-binding-ordinary-", ""): row for row in ordinary}
    right = {row["group_id"].replace("v06-binding-adversarial-", ""): row for row in adversarial}
    pairs = [(left[key], right[key]) for key in sorted(left.keys() & right.keys())]
    drift = []
    js = []
    flips = 0
    for first, second in pairs:
        drift.append(sum(abs(a - b) for a, b in zip(first["prediction"], second["prediction"])))
        js.append(js_divergence(first["prediction"], second["prediction"]))
        flips += int(max(range(len(first["prediction"])), key=first["prediction"].__getitem__) != max(range(len(second["prediction"])), key=second["prediction"].__getitem__))
    result = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.6-B",
        "model_name": model_name,
        "backbone_frozen": True,
        "head_scale": 250000,
        "ordinary": {"count": len(ordinary), "accuracy": accuracy(ordinary)},
        "adversarial": {"count": len(adversarial), "accuracy": accuracy(adversarial)},
        "paired": {
            "count": len(pairs),
            "mean_l1_drift": sum(drift) / max(1, len(drift)),
            "mean_js_divergence": sum(js) / max(1, len(js)),
            "argmax_flip_rate": flips / max(1, len(pairs)),
        },
        "gold_rule": "exposed definition controls semantics; opaque token reassignment should not alter gold-aligned decisions",
    }
    out = RUN / "reports" / "contradictory-binding-v06.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if out.exists():
        existing = json.loads(out.read_text(encoding="utf-8"))
    existing[model_name] = result
    out.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cuda")
    args = parser.parse_args()
    run_model(args.model_name, args.device)


if __name__ == "__main__":
    main()
