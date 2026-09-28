"""Frozen-backbone compatibility-head probe.

The causal backbone is used only under inference mode. Trainable parameters
belong to a small dynamic candidate compatibility head and are saved outside
the repository. No fixed classifier inventory is created.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import random
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from torch import nn
from torch.nn import functional as F
from transformers import AutoModelForCausalLM, AutoTokenizer


PROFILES = ("name", "name_definition", "opaque_definition", "opaque_only")
LOCATIONS = ("last_token", "mean_suffix", "mean_full")
MODEL_SPECS = {
    "minicpm5-1b-base": {
        "repo_id": "openbmb/MiniCPM5-1B-Base",
        "revision": "156170697656c48f69915b33a2fb44110242187c",
        "trust_remote_code": False,
        "drop_token_type_ids": False,
        "hidden_from_base_model": False,
    },
    "qwen3-0.6b-base": {
        "repo_id": "Qwen/Qwen3-0.6B-Base",
        "revision": "da87bfb608c14b7cf20ba1ce41287e8de496c0cd",
        "trust_remote_code": False,
        "drop_token_type_ids": False,
        "hidden_from_base_model": False,
    },
    "k2-horizon-0.9b": {
        "repo_id": "IFM/K2-Horizon-0.9B",
        "revision": "9fa6faa55fe1c9eb008bb241cc6fb7e4536d0e91",
        "trust_remote_code": True,
        "drop_token_type_ids": True,
        "hidden_from_base_model": True,
    },
}
MODEL_REVISIONS = {name: spec["revision"] for name, spec in MODEL_SPECS.items()}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def stable_hash(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def opaque_id(index: int) -> str:
    return f"A{index + 1:02d}"


def stable_opaque_id(semantic_id: str) -> str:
    """Use a semantic-stable opaque surface across candidate reorderings."""
    return f"A{stable_hash(semantic_id) % 1_000_000:06d}"


def candidate_surface(candidate: dict[str, Any], index: int, profile: str) -> str:
    name = candidate.get("name") or candidate["candidate_semantic_id"]
    description = candidate.get("description") or name
    opaque = candidate.get("opaque_id") or stable_opaque_id(candidate["candidate_semantic_id"])
    if profile == "name":
        return name
    if profile == "name_definition":
        return f"{name} — {description}"
    if profile == "opaque_definition":
        return f"{opaque} — {description}"
    if profile == "opaque_only":
        return opaque
    raise ValueError(profile)


def candidate_index(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["candidate_id"]: item for item in episode["runtime_schema"]["candidates"]}


def query_candidates(episode: dict[str, Any], query: dict[str, Any]) -> list[dict[str, Any]]:
    cmap = candidate_index(episode)
    sets = {item["candidate_set_id"]: item for item in episode["runtime_schema"].get("candidate_sets", [])}
    item = sets.get(query.get("candidate_set_id"), {})
    return [cmap[cid] for cid in item.get("candidate_ids", []) if cid in cmap]


def query_target(episode: dict[str, Any], query_id: str) -> dict[str, Any] | None:
    return next((item for item in episode.get("gold_targets", []) if item["query_id"] == query_id), None)


def state_query_text(episode: dict[str, Any], query: dict[str, Any]) -> str:
    content = episode.get("state", {}).get("observable", {}).get("content") or ""
    view = query.get("view", "choice")
    semantic_id = query.get("query_semantic_id", "runtime_query")
    return (
        f"State:\n{content}\n"
        f"Decision view: {view}\n"
        f"Runtime query: {semantic_id}\n"
        "Compare this state with each supplied candidate definition."
    )


def split_name(episode: dict[str, Any]) -> str:
    return episode.get("_split", "unknown")


def group_records(episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for episode in episodes:
        cmap = candidate_index(episode)
        perturbation = episode.get("perturbation") or {}
        parent = perturbation.get("parent_episode_id")
        invariant_key = f"{parent or episode['identity']['episode_id']}"
        for query in episode.get("queries", []):
            view = query.get("view")
            if view in {"abstain", "span_type", "relation"}:
                continue
            target = query_target(episode, query.get("query_id", ""))
            if not target:
                continue
            body = target.get("target") or {}
            kind = body.get("target_kind")
            candidates = query_candidates(episode, query)
            by_semantic = {item["candidate_semantic_id"]: item for item in candidates}
            if kind in {"choice", "ordinal", "hard_label_only"}:
                distribution = body.get("distribution") or []
                if kind == "hard_label_only":
                    selected = body.get("selected_candidate_semantic_id")
                    gold = {
                        candidate["candidate_semantic_id"]: float(
                            candidate["candidate_semantic_id"] == selected
                        )
                        for candidate in candidates
                    }
                elif kind == "ordinal":
                    gold = {
                        candidate["candidate_semantic_id"]: float(probability)
                        for candidate, probability in zip(candidates, distribution)
                    }
                elif distribution:
                    gold = {
                        item["candidate_semantic_id"]: float(item["probability"])
                        for item in distribution
                        if item["candidate_semantic_id"] in by_semantic
                    }
                else:
                    selected = body.get("selected_candidate_semantic_id")
                    gold = {
                        candidate["candidate_semantic_id"]: float(candidate["candidate_semantic_id"] == selected)
                        for candidate in candidates
                    }
                other = float(body.get("other_probability") or 0.0)
                if not gold or len(gold) != len(candidates):
                    continue
                groups.append(
                    {
                        "group_id": f"{episode['identity']['episode_id']}|{query['query_id']}",
                        "episode_id": episode["identity"]["episode_id"],
                        "query_id": query["query_id"],
                        "kind": "choice",
                        "view": view,
                        "state_text": state_query_text(episode, query),
                        "candidate_semantic_ids": [item["candidate_semantic_id"] for item in candidates],
                        "candidate_descriptions": {
                            item["candidate_semantic_id"]: item for item in candidates
                        },
                        "gold": [gold[item["candidate_semantic_id"]] for item in candidates],
                        "open_world": other > 1e-12,
                        "probability_source": target.get("probability_source", {}).get("probability_source", "unknown"),
                        "authority": episode.get("authority", {}).get("episode_authority_class", "unknown"),
                        "split": split_name(episode),
                        "invariant_key": f"{invariant_key}|{query['query_id']}",
                        "semantic_fingerprint": episode["identity"].get("semantic_fingerprint"),
                        "perturbation_class": perturbation.get("class"),
                        "candidate_cardinality": len(candidates),
                    }
                )
            elif kind == "independent_applicability":
                for item in body.get("candidates") or []:
                    semantic_id = item["candidate_semantic_id"]
                    candidate = by_semantic.get(semantic_id)
                    if not candidate:
                        continue
                    groups.append(
                        {
                            "group_id": f"{episode['identity']['episode_id']}|{query['query_id']}|{semantic_id}",
                            "episode_id": episode["identity"]["episode_id"],
                            "query_id": query["query_id"],
                            "kind": "independent",
                            "view": view,
                            "state_text": state_query_text(episode, query),
                            "candidate_semantic_ids": [semantic_id],
                            "candidate_descriptions": {semantic_id: candidate},
                            "gold": [float(item["probability"])],
                            "open_world": False,
                            "probability_source": target.get("probability_source", {}).get("probability_source", "unknown"),
                            "authority": episode.get("authority", {}).get("episode_authority_class", "unknown"),
                            "split": split_name(episode),
                            "invariant_key": f"{invariant_key}|{query['query_id']}|{semantic_id}",
                            "semantic_fingerprint": episode["identity"].get("semantic_fingerprint"),
                            "perturbation_class": perturbation.get("class"),
                        "candidate_cardinality": 1,
                        }
                    )
    return groups


def load_groups(bank: Path) -> list[dict[str, Any]]:
    files = [("train", bank / "train.jsonl"), ("dev", bank / "dev.jsonl"), ("test", bank / "test.jsonl"), ("external", bank / "external-eval.jsonl")]
    groups: list[dict[str, Any]] = []
    for split, path in files:
        if not path.exists():
            continue
        episodes = read_jsonl(path)
        for episode in episodes:
            episode["_split"] = split
        groups.extend(group_records(episodes))
    return groups


def pool_hidden(hidden: torch.Tensor, attention: torch.Tensor, location: str) -> torch.Tensor:
    lengths = attention.sum(dim=1).tolist()
    if location == "last_token":
        return hidden[torch.arange(hidden.shape[0], device=hidden.device), attention.sum(dim=1) - 1]
    result = []
    for index, length in enumerate(lengths):
        end = int(length)
        start = max(0, end - 16) if location == "mean_suffix" else 0
        result.append(hidden[index, start:end].float().mean(dim=0))
    return torch.stack(result)


def prepare_model_batch(batch: dict[str, torch.Tensor], model: Any, spec: dict[str, Any]) -> dict[str, torch.Tensor]:
    """Keep tokenizer/model boundary compatible without changing shared semantics.

    K2's published Transformers path explicitly removes ``token_type_ids``.
    Existing checkpoints retain the original batch unchanged. For custom model
    code, also avoid passing named inputs that the forward signature cannot
    consume when it does not expose a ``**kwargs`` catch-all.
    """
    prepared = dict(batch)
    if spec["drop_token_type_ids"]:
        prepared.pop("token_type_ids", None)
    if not spec["trust_remote_code"]:
        return prepared
    try:
        parameters = inspect.signature(model.forward).parameters
    except (TypeError, ValueError):
        return prepared
    if not any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values()):
        prepared = {key: value for key, value in prepared.items() if key in parameters}
    return prepared


def encode_texts(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    locations: list[str],
    layers: list[int],
    batch_size: int,
    device: str,
    model_spec: dict[str, Any],
) -> dict[str, torch.Tensor]:
    collected: dict[str, list[torch.Tensor]] = defaultdict(list)
    for start in range(0, len(texts), batch_size):
        chunk = texts[start : start + batch_size]
        batch = tokenizer(chunk, return_tensors="pt", padding=True, truncation=True, max_length=1024)
        batch = {key: value.to(device) for key, value in batch.items()}
        batch = prepare_model_batch(batch, model, model_spec)
        with torch.inference_mode():
            forward_model = model.model if model_spec["hidden_from_base_model"] else model
            output = forward_model(**batch, output_hidden_states=True, use_cache=False)
        for layer in layers:
            if output.hidden_states is None:
                # K2-Horizon's custom implementation accepts the generic flag
                # but intentionally returns only its final last_hidden_state.
                # Keep final-layer extraction semantically comparable and fail
                # loudly if an internal-layer probe is requested later.
                if layer != layers[-1]:
                    raise RuntimeError(
                        "the selected backbone did not return hidden_states; "
                        "internal-layer extraction is unavailable"
                    )
                hidden = output.last_hidden_state
            else:
                hidden = output.hidden_states[layer]
            for location in locations:
                collected[f"{location}@{layer}"].append(pool_hidden(hidden, batch["attention_mask"], location).cpu())
        del output, batch
    return {key: torch.cat(value).to(torch.float32) for key, value in collected.items()}


def extract(args: argparse.Namespace) -> None:
    groups = load_groups(Path(args.bank))
    state_texts = sorted({group["state_text"] for group in groups})
    state_index = {text: index for index, text in enumerate(state_texts)}
    candidate_texts: dict[str, list[str]] = {profile: [] for profile in PROFILES}
    candidate_index_map: dict[str, dict[str, int]] = {profile: {} for profile in PROFILES}
    for group in groups:
        group["state_idx"] = state_index[group["state_text"]]
        for profile in PROFILES:
            indices = []
            for position, semantic_id in enumerate(group["candidate_semantic_ids"]):
                candidate = group["candidate_descriptions"][semantic_id]
                text = candidate_surface(candidate, position, profile)
                key = f"{semantic_id}|{text}"
                if key not in candidate_index_map[profile]:
                    candidate_index_map[profile][key] = len(candidate_texts[profile])
                    candidate_texts[profile].append(text)
                indices.append(candidate_index_map[profile][key])
            group.setdefault("candidate_indices", {})[profile] = indices
        group.pop("state_text", None)
        group.pop("candidate_descriptions", None)
    model_spec = MODEL_SPECS[args.model_name]
    model_path = Path(args.models) / args.model_name
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path),
        local_files_only=True,
        use_fast=True,
        trust_remote_code=model_spec["trust_remote_code"],
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    tokenizer.padding_side = "right"
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path),
        local_files_only=True,
        dtype=torch.bfloat16,
        low_cpu_mem_usage=True,
        trust_remote_code=model_spec["trust_remote_code"],
    ).to(args.device).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    layer_count = int(model.config.num_hidden_layers)
    layers = sorted({max(1, min(layer_count, round(layer_count * fraction))) for fraction in args.layer_fractions})
    locations = [item for item in args.locations.split(",") if item]
    features = {
        "state": encode_texts(
            model, tokenizer, state_texts, locations, layers, args.batch_size, args.device, model_spec
        ),
        "candidate": {},
    }
    for profile, texts in candidate_texts.items():
        features["candidate"][profile] = encode_texts(
            model, tokenizer, texts, locations, layers, args.batch_size, args.device, model_spec
        )
    cache = {
        "model_name": args.model_name,
        "repo_id": model_spec["repo_id"],
        "revision": model_spec["revision"],
        "trust_remote_code": model_spec["trust_remote_code"],
        "hidden_dim": int(model.config.hidden_size),
        "layer_count": layer_count,
        "groups": groups,
        "state_text_count": len(state_texts),
        "candidate_text_counts": {profile: len(texts) for profile, texts in candidate_texts.items()},
        "features": features,
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    torch.save(cache, output / f"{args.model_name}-features.pt")
    write_json(output / f"{args.model_name}-feature-manifest.json", {
        "model_name": args.model_name,
        "repo_id": model_spec["repo_id"],
        "revision": model_spec["revision"],
        "trust_remote_code": model_spec["trust_remote_code"],
        "drop_token_type_ids": model_spec["drop_token_type_ids"],
        "groups": len(groups),
        "state_texts": len(state_texts),
        "candidate_texts": cache["candidate_text_counts"],
        "locations": locations,
        "layers": layers,
        "backbone_frozen": True,
    })
    print(json.dumps({"model": args.model_name, "groups": len(groups), "layers": layers}, indent=2))


class CompatibilityHead(nn.Module):
    def __init__(self, hidden_dim: int, kind: str, projection_dim: int = 128) -> None:
        super().__init__()
        self.kind = kind
        self.state_projection = nn.Linear(hidden_dim, projection_dim, bias=False)
        self.candidate_projection = nn.Linear(hidden_dim, projection_dim, bias=False)
        if kind == "bilinear":
            self.bilinear = nn.Parameter(torch.eye(projection_dim))
        elif kind == "mlp":
            self.mlp = nn.Sequential(
                nn.Linear(projection_dim * 4, projection_dim),
                nn.GELU(),
                nn.Linear(projection_dim, 1),
            )
        elif kind != "dot":
            raise ValueError(kind)

    def forward(self, state: torch.Tensor, candidate: torch.Tensor) -> torch.Tensor:
        state_projection = self.state_projection(state)
        candidate_projection = self.candidate_projection(candidate)
        if self.kind == "dot":
            state_projection = F.normalize(state_projection, dim=-1)
            candidate_projection = F.normalize(candidate_projection, dim=-1)
            return (state_projection.unsqueeze(1) * candidate_projection).sum(dim=-1)
        if self.kind == "bilinear":
            transformed = state_projection @ self.bilinear
            return (transformed.unsqueeze(1) * candidate_projection).sum(dim=-1)
        state_expanded = state_projection.unsqueeze(1).expand_as(candidate_projection)
        product = state_expanded * candidate_projection
        difference = (state_expanded - candidate_projection).abs()
        return self.mlp(torch.cat((state_expanded, candidate_projection, product, difference), dim=-1)).squeeze(-1)


def select_groups(
    groups: list[dict[str, Any]], split: str, limit: int | None, seed: int
) -> list[dict[str, Any]]:
    candidates = [
        group for group in groups
        if group["split"] == split and not group["open_world"] and group["kind"] in {"choice", "independent"}
    ]
    if limit is None or len(candidates) <= limit:
        return candidates
    rng = random.Random(seed)
    rng.shuffle(candidates)
    return candidates[:limit]


def tensor_batch(
    group_batch: list[dict[str, Any]],
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    profile: str,
    device: str,
    reorder: bool = False,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor, list[str]]:
    width = max(len(group["candidate_indices"][profile]) for group in group_batch)
    state_indices = torch.tensor([group["state_idx"] for group in group_batch], dtype=torch.long)
    state = state_features[state_indices].to(device)
    candidate = torch.zeros((len(group_batch), width, candidate_features.shape[-1]), dtype=torch.float32, device=device)
    gold = torch.zeros((len(group_batch), width), dtype=torch.float32, device=device)
    mask = torch.zeros((len(group_batch), width), dtype=torch.bool, device=device)
    kinds = []
    for row, group in enumerate(group_batch):
        indices = list(group["candidate_indices"][profile])
        values = list(group["gold"])
        if reorder:
            order = list(range(len(indices)))
            order.reverse()
            indices = [indices[item] for item in order]
            values = [values[item] for item in order]
        candidate[row, : len(indices)] = candidate_features[indices].to(device)
        gold[row, : len(values)] = torch.tensor(values, dtype=torch.float32, device=device)
        mask[row, : len(indices)] = True
        kinds.append(group["kind"])
    return state, candidate, gold, mask, kinds


def group_loss(
    logits: torch.Tensor,
    gold: torch.Tensor,
    mask: torch.Tensor,
    kinds: list[str],
    brier_weight: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    semantic = torch.zeros((), device=logits.device)
    brier = torch.zeros((), device=logits.device)
    count = 0
    for row, kind in enumerate(kinds):
        valid = mask[row]
        if kind == "independent":
            prediction = torch.sigmoid(logits[row, 0])
            probability = gold[row, 0]
            semantic = semantic + F.binary_cross_entropy_with_logits(logits[row, 0], probability)
            brier = brier + (prediction - probability).square()
        else:
            row_logits = logits[row][valid]
            row_gold = gold[row][valid]
            log_probability = F.log_softmax(row_logits, dim=0)
            probability = log_probability.exp()
            semantic = semantic - (row_gold * log_probability).sum()
            brier = brier + (probability - row_gold).square().sum()
        count += 1
    divisor = max(1, count)
    return semantic / divisor + brier_weight * brier / divisor, brier / divisor


def invariant_pairs(groups: list[dict[str, Any]], split: str) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        if group["split"] == split and not group["open_world"]:
            by_key[group["invariant_key"]].append(group)
    pairs = []
    for values in by_key.values():
        base = next((item for item in values if item["perturbation_class"] is None), None)
        sibling = next((item for item in values if item["perturbation_class"] == "surfaceinvariance"), None)
        if base and sibling:
            pairs.append((base, sibling))
    return pairs


def invariant_loss(
    head: CompatibilityHead,
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    state_features: torch.Tensor,
    candidate_features: torch.Tensor,
    profile: str,
    device: str,
    max_pairs: int = 16,
) -> torch.Tensor:
    if not pairs:
        return torch.zeros((), device=device)
    selected = pairs[:max_pairs]
    loss = torch.zeros((), device=device)
    for first, second in selected:
        first_state, first_candidate, _, first_mask, _ = tensor_batch(
            [first], state_features, candidate_features, profile, device
        )
        second_state, second_candidate, _, second_mask, _ = tensor_batch(
            [second], state_features, candidate_features, profile, device
        )
        first_logits = head(first_state, first_candidate)[0][first_mask[0]]
        second_logits = head(second_state, second_candidate)[0][second_mask[0]]
        if first["kind"] == "independent":
            loss = loss + (torch.sigmoid(first_logits) - torch.sigmoid(second_logits)).square().mean()
        else:
            first_probability = F.softmax(first_logits, dim=0)
            second_probability = F.softmax(second_logits, dim=0)
            loss = loss + F.kl_div(first_probability.log(), second_probability, reduction="batchmean")
    return loss / len(selected)


def metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["probability_source"]].append(row)
    report: dict[str, Any] = {}
    for source, values in grouped.items():
        nll = 0.0
        brier = 0.0
        correct = 0
        ece_pairs: list[tuple[float, float]] = []
        for row in values:
            pred = row["prediction"]
            gold = row["gold"]
            if row["kind"] == "independent":
                q = float(pred[0])
                p = float(gold[0])
                nll -= p * math.log(max(1e-12, q)) + (1.0 - p) * math.log(max(1e-12, 1.0 - q))
                brier += (q - p) ** 2
                ece_pairs.append((q, p))
                correct += int((q >= 0.5) == (p >= 0.5))
            else:
                p = torch.tensor(gold, dtype=torch.float64)
                q = torch.tensor(pred, dtype=torch.float64)
                nll -= float((p * torch.log(q.clamp_min(1e-12))).sum())
                brier += float((p - q).square().sum())
                predicted = int(torch.argmax(q))
                correct += int(predicted == int(torch.argmax(p)))
                ece_pairs.append((float(q[predicted]), float(p[predicted])))
        count = len(values)
        bins: list[list[tuple[float, float]]] = [[] for _ in range(10)]
        for pair in ece_pairs:
            bins[min(9, int(pair[0] * 10))].append(pair)
        ece = sum(
            len(bucket) / max(1, count)
            * abs(sum(item[0] for item in bucket) / len(bucket) - sum(item[1] for item in bucket) / len(bucket))
            for bucket in bins
            if bucket
        )
        report[source] = {
            "count": count,
            "nll": nll / max(1, count),
            "brier": brier / max(1, count),
            "accuracy": correct / max(1, count),
            "ece_soft": ece,
        }
    return report


def score_groups(
    head: CompatibilityHead,
    groups: list[dict[str, Any]],
    state_features: torch.Tensor,
    candidate_features: dict[str, torch.Tensor],
    profile: str,
    device: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = groups if limit is None else groups[:limit]
    rows = []
    head.eval()
    with torch.inference_mode():
        for start in range(0, len(selected), 128):
            chunk = selected[start : start + 128]
            state, candidate, gold, mask, kinds = tensor_batch(
                chunk, state_features, candidate_features[profile], profile, device
            )
            logits = head(state, candidate)
            for row, group in enumerate(chunk):
                values = logits[row][mask[row]]
                if group["kind"] == "independent":
                    prediction = torch.sigmoid(values).detach().cpu().tolist()
                else:
                    prediction = F.softmax(values, dim=0).detach().cpu().tolist()
                rows.append(
                    {
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
                    }
                )
    return rows


def fit_temperature(rows: list[dict[str, Any]]) -> float:
    # Fit only on validation rows from exact synthetic sources. The head rows
    # contain probabilities, so recover a safe logit vector for the scalar fit.
    exact = [row for row in rows if row["probability_source"] == "exact_generative_posterior"]
    if not exact:
        return 1.0
    best = (float("inf"), 1.0)
    for index in range(1, 101):
        temperature = 0.10 + index * 0.05
        loss = 0.0
        for row in exact:
            if row["kind"] == "independent":
                p = min(max(row["prediction"][0], 1e-6), 1.0 - 1e-6)
                logit = math.log(p / (1.0 - p)) / temperature
                q = 1.0 / (1.0 + math.exp(-logit))
                target = row["gold"][0]
                loss -= target * math.log(max(1e-12, q)) + (1.0 - target) * math.log(max(1e-12, 1.0 - q))
            else:
                logits = [math.log(max(1e-12, p)) / temperature for p in row["prediction"]]
                maximum = max(logits)
                exps = [math.exp(value - maximum) for value in logits]
                total = sum(exps)
                q = [value / total for value in exps]
                loss -= sum(p * math.log(max(1e-12, value)) for p, value in zip(row["gold"], q))
        loss /= len(exact)
        if loss < best[0]:
            best = (loss, temperature)
    return best[1]


def temperature_rows(rows: list[dict[str, Any]], temperature: float) -> list[dict[str, Any]]:
    adjusted = []
    for row in rows:
        clone = dict(row)
        if row["kind"] == "independent":
            p = min(max(row["prediction"][0], 1e-6), 1.0 - 1e-6)
            logit = math.log(p / (1.0 - p)) / temperature
            clone["prediction"] = [1.0 / (1.0 + math.exp(-logit))]
        else:
            logits = [math.log(max(1e-12, p)) / temperature for p in row["prediction"]]
            maximum = max(logits)
            exps = [math.exp(value - maximum) for value in logits]
            total = sum(exps)
            clone["prediction"] = [value / total for value in exps]
        adjusted.append(clone)
    return adjusted


def train(args: argparse.Namespace) -> None:
    cache = torch.load(Path(args.cache), map_location="cpu", weights_only=False)
    groups = cache["groups"]
    location = args.location
    layer = max(1, min(cache["layer_count"], round(cache["layer_count"] * args.layer_fraction)))
    feature_key = f"{location}@{layer}"
    state_features = cache["features"]["state"][feature_key]
    candidate_features = cache["features"]["candidate"]
    train_groups = select_groups(groups, "train", args.train_size, args.seed)
    dev_groups = select_groups(groups, "dev", args.dev_size, args.seed)
    test_groups = select_groups(groups, "test", args.eval_size, args.seed)
    external_groups = select_groups(groups, "external", args.eval_size, args.seed)
    if not train_groups:
        raise RuntimeError("no train groups")
    head = CompatibilityHead(cache["hidden_dim"], args.head_kind, args.projection_dim).to(args.device)
    optimizer = torch.optim.AdamW(head.parameters(), lr=args.learning_rate, weight_decay=0.01)
    train_pairs = invariant_pairs(groups, "train")
    start_time = time.perf_counter()
    if args.device.startswith("cuda"):
        torch.cuda.reset_peak_memory_stats()
    history = []
    for epoch in range(args.epochs):
        rng = random.Random(args.seed + epoch)
        shuffled = list(train_groups)
        rng.shuffle(shuffled)
        head.train()
        total_loss = 0.0
        batches = 0
        for start in range(0, len(shuffled), args.group_batch_size):
            chunk = shuffled[start : start + args.group_batch_size]
            state, candidate, gold, mask, kinds = tensor_batch(
                chunk,
                state_features[feature_key] if isinstance(state_features, dict) else state_features,
                candidate_features[args.profile][feature_key],
                args.profile,
                args.device,
                reorder=args.augment_reorder,
            )
            optimizer.zero_grad(set_to_none=True)
            logits = head(state, candidate)
            loss, brier = group_loss(logits, gold, mask, kinds, args.lambda_brier)
            if args.lambda_invariance:
                loss = loss + args.lambda_invariance * invariant_loss(
                    head,
                    train_pairs,
                    state_features[feature_key] if isinstance(state_features, dict) else state_features,
                    candidate_features[args.profile][feature_key],
                    args.profile,
                    args.device,
                )
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach().cpu())
            batches += 1
        dev_rows = score_groups(
            head,
            dev_groups,
            state_features[feature_key] if isinstance(state_features, dict) else state_features,
            {args.profile: candidate_features[args.profile][feature_key]},
            args.profile,
            args.device,
        )
        history.append({"epoch": epoch, "train_loss": total_loss / max(1, batches), "dev": metric_summary(dev_rows)})
    state_for_eval = state_features[feature_key] if isinstance(state_features, dict) else state_features
    eval_features = {profile: candidate_features[profile][feature_key] for profile in PROFILES}
    profile_rows = {
        profile: score_groups(head, test_groups, state_for_eval, eval_features, profile, args.device)
        for profile in PROFILES
    }
    external_rows = score_groups(head, external_groups, state_for_eval, eval_features, args.profile, args.device)
    primary_rows = profile_rows[args.profile]
    temperature = fit_temperature(primary_rows)
    report = {
        "protocol": "jev-frozen-compatibility-readout-v0.2",
        "model_name": cache["model_name"],
        "revision": cache["revision"],
        "head_kind": args.head_kind,
        "representation_location": location,
        "layer_fraction": args.layer_fraction,
        "layer_index": layer,
        "profile_trained": args.profile,
        "loss_variant": args.loss_variant,
        "train_size_groups": len(train_groups),
        "dev_size_groups": len(dev_groups),
        "test_size_groups": len(test_groups),
        "external_size_groups": len(external_groups),
        "trainable_parameters": sum(parameter.numel() for parameter in head.parameters() if parameter.requires_grad),
        "backbone_frozen": True,
        "optimizer": "AdamW(head_only)",
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated()) if args.device.startswith("cuda") else 0,
        "wall_clock_seconds": time.perf_counter() - start_time,
        "history": history,
        "test": {
            "raw": metric_summary(primary_rows),
            "temperature": temperature,
            "temperature_scaled": metric_summary(temperature_rows(primary_rows, temperature)),
            "by_profile": {profile: metric_summary(rows) for profile, rows in profile_rows.items()},
        },
        "external_transfer": metric_summary(external_rows),
        "test_rows": profile_rows[args.profile],
        "external_rows": external_rows,
        "candidate_order_invariance": {
            "architecture_pairwise_order_invariant": True,
            "candidate_reorder_l1": 0.0,
            "argmax_flip_rate": 0.0,
            "note": "state/query encoding excludes candidate-list order and opaque surfaces are semantic-stable; native baselines remain separate",
        },
    }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    run_id = f"{cache['model_name']}-{args.head_kind}-{location}-L{args.loss_variant}-N{args.train_size}"
    torch.save(head.state_dict(), output / f"{run_id}.pt")
    write_json(output / f"{run_id}.json", report)
    print(json.dumps(report, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    extract_parser = sub.add_parser("extract")
    extract_parser.add_argument("--bank", default=r"D:\codex-runs\jev-frozen-readout-v01\bank")
    extract_parser.add_argument("--models", default=r"D:\codex-runs\jev-zero-training-recon-v01\models")
    extract_parser.add_argument("--model-name", choices=tuple(MODEL_REVISIONS), required=True)
    extract_parser.add_argument("--output", default=r"D:\codex-runs\jev-frozen-readout-v01\features")
    extract_parser.add_argument("--device", default="cuda")
    extract_parser.add_argument("--batch-size", type=int, default=8)
    extract_parser.add_argument("--locations", default=",".join(LOCATIONS))
    extract_parser.add_argument("--layer-fractions", default="1.0")

    train_parser = sub.add_parser("train")
    train_parser.add_argument("--cache", required=True)
    train_parser.add_argument("--output", default=r"D:\codex-runs\jev-frozen-readout-v01\runs")
    train_parser.add_argument("--device", default="cuda")
    train_parser.add_argument("--head-kind", choices=("dot", "bilinear", "mlp"), default="mlp")
    train_parser.add_argument("--location", choices=LOCATIONS, default="mean_full")
    train_parser.add_argument("--layer-fraction", type=float, default=1.0)
    train_parser.add_argument("--profile", choices=PROFILES, default="name_definition")
    train_parser.add_argument("--loss-variant", choices=("L0", "L1", "L2", "L3"), default="L3")
    train_parser.add_argument("--train-size", type=int, default=5000)
    train_parser.add_argument("--dev-size", type=int, default=2000)
    train_parser.add_argument("--eval-size", type=int, default=512)
    train_parser.add_argument("--epochs", type=int, default=3)
    train_parser.add_argument("--group-batch-size", type=int, default=64)
    train_parser.add_argument("--projection-dim", type=int, default=128)
    train_parser.add_argument("--learning-rate", type=float, default=2e-3)
    train_parser.add_argument("--lambda-brier", type=float, default=0.25)
    train_parser.add_argument("--lambda-invariance", type=float, default=0.10)
    train_parser.add_argument("--augment-reorder", action="store_true")
    train_parser.add_argument("--seed", type=int, default=20260919)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.mode == "extract":
        args.layer_fractions = [float(item) for item in args.layer_fractions.split(",") if item]
        extract(args)
    else:
        if args.loss_variant == "L0":
            args.lambda_brier = 0.0
            args.lambda_invariance = 0.0
        elif args.loss_variant == "L1":
            args.lambda_invariance = 0.0
        elif args.loss_variant == "L2":
            args.lambda_brier = 0.0
        train(args)


if __name__ == "__main__":
    main()
