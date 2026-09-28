"""Score the available sealed v0.4 factorial OOD cells with the LFM head."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import torch


ROOT = Path(__file__).resolve().parents[2]
V05 = ROOT / "experiments" / "jev-frozen-scaling-v05"
RUN = Path(r"D:\codex-runs\jev-lfm-variable-v07")
MODEL = "lfm2.5-1.2b-base"
sys.path.insert(0, str(V05))
import train_v05 as base  # noqa: E402


CELLS = {
    "ontology_id_world_id": RUN / "features" / "ood" / "ontology-id-world-id" / f"{MODEL}-features.pt",
    "ontology_id_world_ood": RUN / "features" / "ood" / "ontology-id-world-ood" / f"{MODEL}-features.pt",
    "ontology_ood_world_ood": RUN / "features" / "ood" / "ontology-ood-world-ood" / f"{MODEL}-features.pt",
}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--head", required=True)
    args = parser.parse_args()
    result = {
        "protocol": "jev-lfm-architecture-variable/v0.7-true-ood",
        "model_name": MODEL,
        "head_scale": 100000,
        "backbone_frozen": True,
        "novelty_receipt": r"D:\codex-runs\jev-frozen-saturation-v04\ood\ood-novelty-audit.json",
        "cells": {},
    }
    for cell, path in CELLS.items():
        cache = torch.load(path, map_location="cpu", weights_only=False)
        key = f"mean_full@{cache['layer_count']}"
        state = cache["features"]["state"][key].to(args.device)
        candidates = cache["features"]["candidate"]["name_definition"][key].to(args.device)
        head = base.probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(args.device)
        head.load_state_dict(torch.load(args.head, map_location=args.device, weights_only=True)); head.eval()
        groups = [item for item in cache["groups"] if item["kind"] in {"choice", "independent"}]
        rows = base.fast_score_groups(head, groups, state, candidates, "name_definition", args.device)
        result["cells"][cell] = {
            "feature_cache": str(path),
            "groups": len(groups),
            "metrics": base.probe.metric_summary(rows),
        }
    result["cells"]["ontology_ood_world_id"] = {
        "status": "unavailable",
        "reason": "sealed v0.4 artifact provides metadata but no episode file for this cell; no synthetic replacement was created",
    }
    out = RUN / "reports" / "lfm-ood.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
