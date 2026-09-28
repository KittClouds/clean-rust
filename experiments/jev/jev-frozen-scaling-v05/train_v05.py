"""Train the sealed v0.4 dynamic head on v0.5 scaling mixtures.

The backbone is never put in an optimizer.  This runner deliberately keeps
the v0.4 MLP and representation configuration unchanged; v0.5 varies only
the amount and source composition of supervision.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch
import torch.nn.functional as F


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"
RUN = Path(r"D:\codex-runs\jev-frozen-scaling-v05")
BANKS = RUN / "banks"
FEATURES = RUN / "features"
OUT = RUN / "head-runs"
V05_BATCH_SIZE = 256
CALIBRATION_SOURCES = {
    "exact_generative_posterior",
    "empirical_annotator_distribution",
    "elicited_subjective_probability",
    "adjudicated_distribution",
}


def load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("jev_readout_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


probe = load_probe()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def episode_ids(path: Path) -> set[str]:
    return {
        row["identity"]["episode_id"]
        for row in read_jsonl(path)
    }


def source_name(group: dict[str, Any]) -> str:
    episode = group["episode_id"]
    if episode.startswith("go-emotions-v05-"):
        return "go_emotions"
    if "chaos" in episode.lower():
        return "chaos_nli"
    if "massive" in episode.lower():
        return "massive"
    return "synthetic_control" if group["probability_source"] == "exact_generative_posterior" else "other_external"


def eligible(group: dict[str, Any]) -> bool:
    return (
        group["split"] == "train"
        and not group["open_world"]
        and group["kind"] in {"choice", "independent"}
    )


def stable_sample(groups: list[dict[str, Any]], count: int, seed: int) -> list[dict[str, Any]]:
    ordered = sorted(groups, key=lambda item: item["group_id"])
    if len(ordered) <= count:
        return ordered
    rng = random.Random(seed)
    chosen = ordered[:]
    rng.shuffle(chosen)
    return sorted(chosen[:count], key=lambda item: item["group_id"])


def fast_tensor_batch(
    group_batch: list[dict[str, Any]],
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    profile: str,
    device: str,
    reorder: bool = False,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, list[str], list[str]]:
    """Gather one batch with dense index tensors instead of row-wise copies."""
    width = max(len(group["candidate_indices"][profile]) for group in group_batch)
    state_indices = torch.tensor(
        [group["state_idx"] for group in group_batch],
        dtype=torch.long,
        device=state_features.device,
    )
    index_rows: list[list[int]] = []
    gold_rows: list[list[float]] = []
    lengths: list[int] = []
    kinds: list[str] = []
    sources: list[str] = []
    for group in group_batch:
        values = list(group["gold"])
        candidate_ids = list(group["candidate_indices"][profile])
        if reorder:
            candidate_ids.reverse()
            values.reverse()
        length = len(candidate_ids)
        index_rows.append(candidate_ids + [0] * (width - length))
        gold_rows.append(values + [0.0] * (width - length))
        lengths.append(length)
        kinds.append(group["kind"])
        sources.append(group["probability_source"])
    indices = torch.tensor(index_rows, dtype=torch.long, device=candidate_features.device)
    gold = torch.tensor(gold_rows, dtype=torch.float32, device=candidate_features.device)
    mask = torch.tensor(
        [[index < length for index in range(width)] for length in lengths],
        dtype=torch.bool,
        device=candidate_features.device,
    )
    state = state_features[state_indices].to(device)
    candidate = candidate_features[indices]
    return state, candidate, gold.to(device), mask.to(device), kinds, sources


def fast_score_groups(
    head: torch.nn.Module,
    groups: list[dict[str, Any]],
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    profile: str,
    device: str,
    batch_size: int = 1024,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    head.eval()
    with torch.inference_mode():
        for start in range(0, len(groups), batch_size):
            chunk = groups[start : start + batch_size]
            state, candidate, _gold, mask, _kinds, _sources = fast_tensor_batch(
                chunk, state_features, candidate_features, profile, device,
            )
            logits = head(state, candidate)
            for row, group in enumerate(chunk):
                values = logits[row][mask[row]]
                prediction = (
                    torch.sigmoid(values).detach().cpu().tolist()
                    if group["kind"] == "independent"
                    else torch.softmax(values, dim=0).detach().cpu().tolist()
                )
                rows.append({
                    "group_id": group["group_id"],
                    "episode_id": group["episode_id"],
                    "query_id": group["query_id"],
                    "kind": group["kind"],
                    "profile": profile,
                    "probability_source": group["probability_source"],
                    "authority": group["authority"],
                    "split": group["split"],
                    "candidate_cardinality": group["candidate_cardinality"],
                    "gold": group["gold"],
                    "prediction": prediction,
                    "semantic_fingerprint": group["semantic_fingerprint"],
                    "invariant_key": group["invariant_key"],
                    "perturbation_class": group["perturbation_class"],
                })
    return rows


def groups_for_scale(
    groups: list[dict[str, Any]], scale: int, seed: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    synthetic = [item for item in groups if eligible(item) and item["authority"] == "synthetic_control"]
    real = [item for item in groups if eligible(item) and item["authority"] != "synthetic_control"]
    if scale == 50_000:
        ids = episode_ids(BANKS / "s50k" / "train.jsonl")
        synthetic = [item for item in synthetic if item["episode_id"] in ids]
    elif scale != 100_000:
        raise ValueError(scale)
    return stable_sample(synthetic, len(synthetic), seed), stable_sample(real, len(real), seed + 1)


def mixture_groups(
    synthetic: list[dict[str, Any]], real: list[dict[str, Any]], mixture: str, seed: int
) -> list[dict[str, Any]]:
    if mixture == "S100":
        return synthetic
    if mixture == "S75_R25":
        synthetic_fraction = 0.75
    elif mixture == "S50_R50":
        synthetic_fraction = 0.50
    else:
        raise ValueError(mixture)
    target = len(synthetic)
    synthetic_count = round(target * synthetic_fraction)
    real_count = target - synthetic_count
    if real_count > len(real):
        raise RuntimeError(
            f"real lane too small for {mixture}: need {real_count}, have {len(real)}"
        )
    return stable_sample(synthetic, synthetic_count, seed) + stable_sample(real, real_count, seed + 17)


def v05_loss(
    logits: torch.Tensor,
    gold: torch.Tensor,
    mask: torch.Tensor,
    kinds: list[str],
    sources: list[str],
    brier_weight: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    semantic = torch.zeros((), device=logits.device)
    brier = torch.zeros((), device=logits.device)
    count = 0
    for row, kind in enumerate(kinds):
        valid = mask[row]
        source = sources[row]
        if kind == "independent":
            prediction = torch.sigmoid(logits[row, 0])
            probability = gold[row, 0]
            semantic = semantic + F.binary_cross_entropy_with_logits(logits[row, 0], probability)
            if source in CALIBRATION_SOURCES:
                brier = brier + (prediction - probability).square()
        else:
            row_logits = logits[row][valid]
            row_gold = gold[row][valid]
            log_probability = F.log_softmax(row_logits, dim=0)
            probability = log_probability.exp()
            semantic = semantic - (row_gold * log_probability).sum()
            if source in CALIBRATION_SOURCES:
                brier = brier + (probability - row_gold).square().sum()
        count += 1
    divisor = max(1, count)
    return semantic / divisor + brier_weight * brier / divisor, brier / divisor


def select_eval(groups: list[dict[str, Any]], split: str) -> list[dict[str, Any]]:
    return [
        group for group in groups
        if group["split"] == split
        and not group["open_world"]
        and group["kind"] in {"choice", "independent"}
    ]


def vectorized_invariant_loss(
    head: torch.nn.Module,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    profile: str,
    device: str,
    max_pairs: int = 16,
) -> torch.Tensor:
    """Compute the v0.4 invariant term in one compatibility launch.

    The reference implementation evaluates each side of every pair in a
    separate tiny batch.  Concatenating the same 2*16 rows preserves the loss
    exactly while avoiding thousands of small device launches at v0.5 scale.
    """
    if not pairs:
        return torch.zeros((), device=device)
    selected = pairs[:max_pairs]
    items = [item for pair in selected for item in pair]
    state, candidate, _, mask, kinds, _sources = fast_tensor_batch(
        items, state_features, candidate_features, profile, device,
    )
    logits = head(state, candidate)
    loss = torch.zeros((), device=device)
    for pair_index, (first, _second) in enumerate(selected):
        left = 2 * pair_index
        right = left + 1
        first_logits = logits[left][mask[left]]
        second_logits = logits[right][mask[right]]
        if kinds[left] == "independent":
            loss = loss + (
                torch.sigmoid(first_logits) - torch.sigmoid(second_logits)
            ).square().mean()
        else:
            first_probability = F.softmax(first_logits, dim=0)
            second_probability = F.softmax(second_logits, dim=0)
            loss = loss + F.kl_div(
                first_probability.log(), second_probability, reduction="batchmean"
            )
    return loss / len(selected)


def metric_by_source(rows: list[dict[str, Any]], include_dataset: bool = True) -> dict[str, Any]:
    summary = probe.metric_summary(rows)
    by_dataset: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_dataset.setdefault(source_name(row), []).append(row)
    for source in ("hard_label", "no_probability", "unknown"):
        if source in summary:
            summary[source] = {
                "count": summary[source]["count"],
                "accuracy": summary[source]["accuracy"],
                "calibration_defined": False,
                "note": "discrimination-only source; no probability truth is asserted",
            }
    for source, values in summary.items():
        if isinstance(values, dict) and source not in {"source_dataset"}:
            values.setdefault("calibration_defined", source in CALIBRATION_SOURCES)
    if include_dataset:
        summary["source_dataset"] = {
            name: metric_by_source(values, include_dataset=False)
            for name, values in sorted(by_dataset.items())
        }
    return summary


def train_one(
    cache: dict[str, Any],
    train_groups: list[dict[str, Any]],
    dev_groups: list[dict[str, Any]],
    test_groups: list[dict[str, Any]],
    external_groups: list[dict[str, Any]],
    args: argparse.Namespace,
    scale: int,
    mixture: str,
) -> dict[str, Any]:
    feature_key = f"{args.location}@{cache['layer_count']}"
    if args.device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    # Feature extraction is complete and immutable for this process.  Keep
    # candidate tensors resident on the device so each group batch only
    # gathers rows; the old probe copied the candidate table repeatedly.
    state = cache["features"]["state"][feature_key].to(args.device)
    candidate_features = cache["features"]["candidate"]
    profile_features = candidate_features[args.profile][feature_key].to(args.device)
    head = probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(args.device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=2e-3, weight_decay=0.01)
    pairs = probe.invariant_pairs(train_groups, "train")
    start_time = time.perf_counter()
    history: list[dict[str, Any]] = []
    for epoch in range(3):
        shuffled = list(train_groups)
        random.Random(args.seed + epoch).shuffle(shuffled)
        total_loss = 0.0
        total_brier = 0.0
        batches = 0
        head.train()
        for start in range(0, len(shuffled), V05_BATCH_SIZE):
            chunk = shuffled[start : start + V05_BATCH_SIZE]
            state_batch, candidate_batch, gold, mask, kinds, sources = fast_tensor_batch(
                chunk, state, profile_features, args.profile, args.device,
                reorder=True,
            )
            optimizer.zero_grad(set_to_none=True)
            logits = head(state_batch, candidate_batch)
            loss, brier = v05_loss(logits, gold, mask, kinds, sources, 0.25)
            loss = loss + 0.10 * vectorized_invariant_loss(
                head, pairs, state, profile_features, args.profile, args.device
            )
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            total_brier += float(brier.detach().cpu())
            batches += 1
        dev_rows = fast_score_groups(
            head, dev_groups[:1024], state, profile_features, args.profile, args.device,
        )
        history.append({
            "epoch": epoch,
            "train_loss": total_loss / max(1, batches),
            "train_brier": total_brier / max(1, batches),
            "dev": metric_by_source(dev_rows),
        })
    dev_rows = fast_score_groups(head, dev_groups, state, profile_features, args.profile, args.device)
    primary_rows = fast_score_groups(head, test_groups, state, profile_features, args.profile, args.device)
    external_rows = fast_score_groups(head, external_groups, state, profile_features, args.profile, args.device)
    temperature = probe.fit_temperature(dev_rows)
    run_id = f"{cache['model_name']}-s{scale // 1000}k-{mixture}"
    output_dir = OUT / cache["model_name"]
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(head.state_dict(), output_dir / f"{run_id}.pt")
    report = {
        "protocol": "jev-frozen-decision-surface-scaling/v0.5",
        "v04_boundary": {
            "sealed": True,
            "qlora_final_gate_modified": False,
            "v04_result": "unauthorized_for_all_three_backbones",
        },
        "model_name": cache["model_name"],
        "revision": cache["revision"],
        "head": {
            "kind": "mlp",
            "projection_dim": 128,
            "profile": args.profile,
            "loss": "v0.4_L3_source_typed",
            "trainable_parameters": sum(p.numel() for p in head.parameters() if p.requires_grad),
        },
        "scale": scale,
        "mixture": mixture,
        "train_groups": len(train_groups),
        "train_source_counts": dict(Counter(item["probability_source"] for item in train_groups)),
        "train_authority_counts": dict(Counter(item["authority"] for item in train_groups)),
        "dev_groups": len(dev_groups),
        "test_groups": len(test_groups),
        "external_groups": len(external_groups),
        "backbone_frozen": True,
        "optimizer": "AdamW(head_only)",
        "epochs": 3,
        "group_batch_size": V05_BATCH_SIZE,
        "wall_clock_seconds": time.perf_counter() - start_time,
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0,
        "history": history,
        "test": {
            "raw": metric_by_source(primary_rows),
            "temperature": temperature,
            "temperature_scaled": metric_by_source(probe.temperature_rows(primary_rows, temperature)),
        },
        "validation": {
            "raw": metric_by_source(dev_rows),
            "temperature_fit_scope": "dev_exact_generative_posterior_only",
        },
        "external_transfer": metric_by_source(external_rows),
        "cache": {
            "feature_key": feature_key,
            "state_feature_count": int(state.shape[0]),
            "profile_candidate_feature_count": int(profile_features.shape[0]),
        },
    }
    (output_dir / f"{run_id}.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--location", default="mean_full")
    parser.add_argument("--profile", default="name_definition")
    parser.add_argument("--seed", type=int, default=20260925)
    parser.add_argument("--scales", default="50000,100000")
    parser.add_argument("--mixtures", default="S100,S75_R25,S50_R50")
    args = parser.parse_args()
    cache_path = FEATURES / args.model_name / f"{args.model_name}-features.pt"
    cache = torch.load(cache_path, map_location="cpu", weights_only=False)
    groups = cache["groups"]
    dev_groups = select_eval(groups, "dev")
    test_groups = select_eval(groups, "test")
    external_groups = select_eval(groups, "external")
    reports = []
    for scale in (int(item) for item in args.scales.split(",") if item):
        synthetic, real = groups_for_scale(groups, scale, args.seed)
        for mixture in (item for item in args.mixtures.split(",") if item):
            selected = mixture_groups(synthetic, real, mixture, args.seed + scale)
            reports.append(train_one(
                cache, selected, dev_groups, test_groups, external_groups,
                args, scale, mixture,
            ))
            print(json.dumps({
                "model": args.model_name,
                "scale": scale,
                "mixture": mixture,
                "train_groups": len(selected),
                "wall_clock_seconds": reports[-1]["wall_clock_seconds"],
            }), flush=True)
    summary = OUT / args.model_name / "summary.json"
    summary.write_text(json.dumps({"runs": reports}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
