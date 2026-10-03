"""Frozen-model Jev-like reconnaissance.

This is an evaluation-only adapter. It never calls a training API and never
mutates model weights. The canonical JSONL remains the semantic source of
truth; this program only records model readout scores and explicitly declared
normalizations.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


READOUTS = ("direct_next_token", "sequence_sum", "sequence_mean")
PROFILES = ("name", "name_definition", "opaque_definition", "opaque_only")
TEMPLATES = ("A", "B", "C")
SKIP_VIEWS = {"abstain", "span_type", "relation"}
MODEL_REVISIONS = {
    "minicpm5-1b-base": "156170697656c48f69915b33a2fb44110242187c",
    "qwen3-0.6b-base": "da87bfb608c14b7cf20ba1ce41287e8de496c0cd",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def stable_bucket(value: str) -> int:
    return int(hashlib.sha256(value.encode("utf-8")).hexdigest()[:8], 16)


def candidate_map(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        item["candidate_id"]: item
        for item in episode["runtime_schema"]["candidates"]
    }


def query_target(episode: dict[str, Any], query: dict[str, Any]) -> dict[str, Any] | None:
    for target in episode["gold_targets"]:
        if target["query_id"] == query["query_id"]:
            return target
    return None


def semantic_target(
    episode: dict[str, Any], query: dict[str, Any], target: dict[str, Any]
) -> tuple[str, list[str], dict[str, float], str] | None:
    """Return kind, candidate semantic keys, gold distribution, probability source."""
    body = target.get("target", {})
    kind = body.get("target_kind")
    source = target.get("probability_source", {}).get("probability_source", "unknown")
    if kind == "choice":
        distribution = body.get("distribution") or []
        if distribution:
            values = {
                item["candidate_semantic_id"]: float(item["probability"])
                for item in distribution
            }
            other_probability = body.get("other_probability") or 0.0
            if other_probability > 1e-12:
                values["__OTHER__"] = float(other_probability)
        else:
            candidate_ids = candidate_ids_for_query(episode, query)
            selected = body.get("selected_candidate_semantic_id")
            values = {
                item["candidate_semantic_id"]: float(item["candidate_semantic_id"] == selected)
                for item in candidate_ids
            }
        return kind, list(values), values, source
    if kind == "independent_applicability":
        values: dict[str, float] = {}
        for item in body.get("candidates", []):
            p = float(item["probability"])
            key = item["candidate_semantic_id"]
            values[key] = p
        if len(values) == 1:
            probability = next(iter(values.values()))
            values = {"True": probability, "False": 1.0 - probability}
        return kind, list(values), values, source
    if kind == "ordinal":
        candidate_ids = candidate_ids_for_query(episode, query)
        distribution = body.get("distribution", [])
        values = {
            candidate["candidate_semantic_id"]: float(probability)
            for candidate, probability in zip(candidate_ids, distribution)
        }
        return kind, list(values), values, source
    return None


def candidate_ids_for_query(
    episode: dict[str, Any], query: dict[str, Any]
) -> list[dict[str, Any]]:
    sets = {
        item["candidate_set_id"]: item
        for item in episode["runtime_schema"].get("candidate_sets", [])
    }
    cmap = candidate_map(episode)
    candidate_set = sets.get(query.get("candidate_set_id"), {})
    return [cmap[cid] for cid in candidate_set.get("candidate_ids", []) if cid in cmap]


def opaque_id(index: int) -> str:
    return f"A{index + 1:02d}"


def surface(candidate: dict[str, Any], index: int, profile: str) -> str:
    name = candidate.get("name") or candidate["candidate_semantic_id"]
    description = candidate.get("description") or name
    opaque = candidate.get("opaque_id") or opaque_id(index)
    if profile == "name":
        return name
    if profile == "name_definition":
        return f"{name} — {description}"
    if profile == "opaque_definition":
        return f"{opaque} — {description}"
    if profile == "opaque_only":
        return opaque
    raise ValueError(f"unknown profile {profile}")


def state_text(episode: dict[str, Any]) -> str:
    observable = episode.get("state", {}).get("observable", {})
    content = observable.get("content")
    if content:
        return str(content)
    return "\n".join(str(item.get("content", "")) for item in episode.get("evidence_items", []))


def make_prefix(
    episode: dict[str, Any],
    query: dict[str, Any],
    candidates: list[dict[str, Any]],
    profile: str,
    template: str,
) -> tuple[str, list[tuple[str, str, str]]]:
    """Return one shared prefix and (semantic_id, surface, continuation) jobs."""
    state = state_text(episode)
    view = query.get("view", "choice")
    presented = [surface(candidate, index, profile) for index, candidate in enumerate(candidates)]
    if view == "independent_applicability":
        candidate = candidates[0] if candidates else {"candidate_semantic_id": "unknown", "name": "unknown"}
        criterion = surface(candidate, 0, profile)
        if template == "B":
            prefix = f"Evidence:\n{state}\nCriterion: {criterion}\nCandidate: {criterion}\nCompatibility:"
        else:
            prefix = f"State:\n{state}\nProposition: {criterion}\nAnswer with True or False:\nAnswer:"
        return prefix, [(candidate["candidate_semantic_id"], criterion, "True"),
                        (candidate["candidate_semantic_id"], criterion, "False")]

    lines = "\n".join(f"{index + 1}. {item}" for index, item in enumerate(presented))
    if template == "A":
        prefix = f"State:\n{state}\nQuestion: Select the compatible candidate.\nOptions:\n{lines}\nAnswer:"
    elif template == "B":
        prefix = f"Evidence:\n{state}\nCriterion: Select the compatible candidate.\nCandidates:\n{lines}\nCompatibility:"
    else:
        prefix = f"State:\n{state}\nTask: choose the candidate whose definition matches the evidence.\nCandidates:\n{lines}\nDecision:"
    return prefix, [
        (candidate["candidate_semantic_id"], presented[index], presented[index])
        for index, candidate in enumerate(candidates)
    ]


def records_from_episodes(
    episodes: list[dict[str, Any]], max_queries: int
) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for episode in episodes:
        for query in episode.get("queries", []):
            if query.get("view") in SKIP_VIEWS:
                continue
            target = query_target(episode, query)
            if not target:
                continue
            normalized = semantic_target(episode, query, target)
            if not normalized:
                continue
            kind, _, gold, source = normalized
            candidates = candidate_ids_for_query(episode, query)
            if not candidates:
                continue
            groups[(source, kind)].append(
                {
                    "episode": episode,
                    "query": query,
                    "target": target,
                    "kind": kind,
                    "gold": gold,
                    "probability_source": source,
                    "candidates": candidates,
                }
            )
    selected: list[dict[str, Any]] = []
    keys = sorted(groups)
    cursor = 0
    while len(selected) < max_queries and keys:
        key = keys[cursor % len(keys)]
        if groups[key]:
            selected.append(groups[key].pop(0))
        keys = [item for item in keys if groups[item]]
        cursor += 1
    return selected


def encode_ids(tokenizer: Any, text: str) -> list[int]:
    ids = tokenizer(text, add_special_tokens=False)["input_ids"]
    return list(ids)


def completion_ids(tokenizer: Any, prefix: str, completion: str) -> tuple[list[int], list[int]]:
    prefix_ids = encode_ids(tokenizer, prefix)
    continuation = " " + completion
    cont_ids = encode_ids(tokenizer, continuation)
    full_ids = encode_ids(tokenizer, prefix + continuation)
    if full_ids[: len(prefix_ids)] != prefix_ids:
        prefix_ids = full_ids[: len(full_ids) - len(cont_ids)]
    return prefix_ids, cont_ids


def pad_tokenizer(tokenizer: Any) -> None:
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    tokenizer.padding_side = "right"


def score_direct(
    model: Any,
    tokenizer: Any,
    jobs: list[tuple[str, str]],
    batch_size: int,
    device: str,
) -> list[float]:
    results: list[float] = []
    for start in range(0, len(jobs), batch_size):
        chunk = jobs[start : start + batch_size]
        prefixes = [item[0] for item in chunk]
        token_ids = [completion_ids(tokenizer, prefix, completion)[1][0] for prefix, completion in chunk]
        batch = tokenizer(prefixes, return_tensors="pt", padding=True, add_special_tokens=False)
        batch = {key: value.to(device) for key, value in batch.items()}
        with torch.inference_mode():
            logits = model(**batch, use_cache=False).logits.float()
        lengths = batch["attention_mask"].sum(dim=1).tolist()
        for index, length in enumerate(lengths):
            results.append(float(logits[index, int(length) - 1, token_ids[index]].item()))
        del logits, batch
    return results


def score_sequences(
    model: Any,
    tokenizer: Any,
    jobs: list[tuple[str, str]],
    batch_size: int,
    device: str,
) -> list[tuple[float, float, list[int]]]:
    results: list[tuple[float, float, list[int]]] = []
    for start in range(0, len(jobs), batch_size):
        chunk = jobs[start : start + batch_size]
        full_ids: list[list[int]] = []
        prefix_lens: list[int] = []
        continuation_ids: list[list[int]] = []
        for prefix, completion in chunk:
            prefix_ids, cont_ids = completion_ids(tokenizer, prefix, completion)
            full_ids.append(prefix_ids + cont_ids)
            prefix_lens.append(len(prefix_ids))
            continuation_ids.append(cont_ids)
        max_len = max(len(item) for item in full_ids)
        pad = tokenizer.pad_token_id
        input_ids = torch.full((len(full_ids), max_len), pad, dtype=torch.long)
        attention = torch.zeros_like(input_ids)
        for index, ids in enumerate(full_ids):
            input_ids[index, : len(ids)] = torch.tensor(ids, dtype=torch.long)
            attention[index, : len(ids)] = 1
        batch = {"input_ids": input_ids.to(device), "attention_mask": attention.to(device)}
        with torch.inference_mode():
            logits = model(**batch, use_cache=False).logits.float()
        log_probs = torch.log_softmax(logits, dim=-1)
        for index, ids in enumerate(continuation_ids):
            start_index = prefix_lens[index]
            positions = torch.arange(start_index - 1, start_index - 1 + len(ids), device=device)
            labels = torch.tensor(ids, dtype=torch.long, device=device)
            values = log_probs[index, positions, labels]
            total = float(values.sum().item())
            mean = total / max(1, len(ids))
            results.append((total, mean, ids))
        del log_probs, logits, batch
    return results


def softmax(values: dict[str, float], temperature: float = 1.0) -> dict[str, float]:
    if not values:
        return {}
    keys = list(values)
    tensor = torch.tensor([values[key] for key in keys], dtype=torch.float64) / temperature
    probs = torch.softmax(tensor, dim=0).tolist()
    return {key: float(value) for key, value in zip(keys, probs)}


def aligned_prediction(
    scores: dict[str, float], kind: str, gold: dict[str, float], temperature: float = 1.0
) -> dict[str, float]:
    if kind == "independent_applicability":
        true_score = scores.get("True", 0.0)
        false_score = scores.get("False", 0.0)
        return softmax({"True": true_score, "False": false_score}, temperature)
    return softmax(
        {key: scores[key] for key in scores if key in gold or key != "__OTHER__"}, temperature
    )


def evaluate_model(
    model_path: Path,
    records: list[dict[str, Any]],
    profiles: list[str],
    templates: list[str],
    batch_size: int,
    device: str,
    do_reorder: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started = time.perf_counter()
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
        torch.cuda.reset_peak_memory_stats()
    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, use_fast=True)
    pad_tokenizer(tokenizer)
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path), local_files_only=True, dtype=torch.bfloat16, low_cpu_mem_usage=True
    ).to(device).eval()
    load_seconds = time.perf_counter() - started
    rows: list[dict[str, Any]] = []
    peak = 0
    for profile in profiles:
        for template in templates:
            for reordered in ([False, True] if do_reorder else [False]):
                for offset in range(0, len(records), 16):
                    chunk = records[offset : offset + 16]
                    direct_jobs: list[tuple[str, str]] = []
                    sequence_jobs: list[tuple[str, str]] = []
                    job_meta: list[dict[str, Any]] = []
                    for record in chunk:
                        candidates = list(record["candidates"])
                        if reordered:
                            candidates.reverse()
                        prefix, jobs = make_prefix(
                            record["episode"], record["query"], candidates, profile, template
                        )
                        for semantic_id, displayed, completion in jobs:
                            direct_jobs.append((prefix, completion))
                            sequence_jobs.append((prefix, completion))
                            job_meta.append(
                                {
                                    "record": record,
                                    "semantic_id": semantic_id,
                                    "displayed": displayed,
                                    "completion": completion,
                                    "prefix": prefix,
                                    "reordered": reordered,
                                }
                            )
                    if not direct_jobs:
                        continue
                    t0 = time.perf_counter()
                    direct_values = score_direct(model, tokenizer, direct_jobs, batch_size, device)
                    sequence_values = score_sequences(model, tokenizer, sequence_jobs, batch_size, device)
                    elapsed = time.perf_counter() - t0
                    grouped: dict[tuple[str, str], dict[str, Any]] = {}
                    for meta, direct, sequence in zip(job_meta, direct_values, sequence_values):
                        record = meta["record"]
                        key = (
                            record["episode"]["identity"]["episode_id"],
                            record["query"]["query_id"],
                        )
                        item = grouped.setdefault(
                            key,
                            {
                                "record": record,
                                "direct_scores": {},
                                "sequence_sum_scores": {},
                                "sequence_mean_scores": {},
                                "candidate_tokens": {},
                                "intervention": "candidate_reorder" if meta["reordered"] else "baseline",
                            },
                        )
                        score_key = (
                            meta["completion"]
                            if record["kind"] == "independent_applicability"
                            and meta["completion"] in {"True", "False"}
                            else meta["semantic_id"]
                        )
                        item["direct_scores"][score_key] = direct
                        item["sequence_sum_scores"][score_key] = sequence[0]
                        item["sequence_mean_scores"][score_key] = sequence[1]
                        item["candidate_tokens"][score_key] = {
                            "token_ids": sequence[2],
                            "token_count": len(sequence[2]),
                            "surface_length": len(meta["displayed"]),
                        }
                    for item in grouped.values():
                        record = item["record"]
                        gold = record["gold"]
                        kind = record["kind"]
                        row = {
                            "model": model_path.name,
                            "episode_id": record["episode"]["identity"]["episode_id"],
                            "query_id": record["query"]["query_id"],
                            "semantic_fingerprint": record["episode"]["identity"].get("semantic_fingerprint"),
                            "surface_renderer_id": record["episode"]["identity"].get("surface_renderer_id"),
                            "view": record["query"].get("view"),
                            "target_kind": kind,
                            "authority": record["episode"].get("authority", {}).get("episode_authority_class"),
                            "probability_source": record["probability_source"],
                            "profile": profile,
                            "template": template,
                            "intervention": item["intervention"],
                            "candidate_cardinality": len(record["candidates"]),
                            "gold_distribution": gold,
                            "direct_scores": item["direct_scores"],
                            "sequence_sum_scores": item["sequence_sum_scores"],
                            "sequence_mean_scores": item["sequence_mean_scores"],
                            "candidate_tokens": item["candidate_tokens"],
                            "elapsed_batch_seconds": elapsed,
                        }
                        row["direct_prediction"] = aligned_prediction(row["direct_scores"], kind, gold)
                        row["sequence_sum_prediction"] = aligned_prediction(row["sequence_sum_scores"], kind, gold)
                        row["sequence_mean_prediction"] = aligned_prediction(row["sequence_mean_scores"], kind, gold)
                        rows.append(row)
                    peak = max(peak, int(torch.cuda.max_memory_allocated()) if device.startswith("cuda") else 0)
    benchmark = benchmark_shared_state(model, tokenizer, records[0], device)
    result = {
        "model": model_path.name,
        "revision": MODEL_REVISIONS.get(model_path.name),
        "load_seconds": load_seconds,
        "records": len(records),
        "result_rows": len(rows),
        "profiles": profiles,
        "templates": templates,
        "batch_size": batch_size,
        "peak_cuda_memory_bytes": peak,
        "shared_state": benchmark,
    }
    del model, tokenizer
    if device.startswith("cuda"):
        torch.cuda.empty_cache()
    return result, rows


def benchmark_shared_state(model: Any, tokenizer: Any, record: dict[str, Any], device: str) -> dict[str, Any]:
    if not device.startswith("cuda"):
        return {"status": "not_run", "reason": "CUDA not selected"}
    candidates = record["candidates"][: min(4, len(record["candidates"]))]
    prefix, jobs = make_prefix(record["episode"], record["query"], candidates, "name_definition", "A")
    branches = [" " + completion for _, _, completion in jobs]
    try:
        full_ids = [encode_ids(tokenizer, prefix + branch) for branch in branches]
        t0 = time.perf_counter()
        fresh_logits: list[torch.Tensor] = []
        for ids in full_ids:
            input_ids = torch.tensor([ids], dtype=torch.long, device=device)
            with torch.inference_mode():
                fresh_logits.append(model(input_ids=input_ids, use_cache=False).logits[0, -1].float().cpu())
        fresh_seconds = time.perf_counter() - t0
        prefix_ids = torch.tensor([encode_ids(tokenizer, prefix)], dtype=torch.long, device=device)
        t1 = time.perf_counter()
        with torch.inference_mode():
            prefix_output = model(input_ids=prefix_ids, use_cache=True)
        prefix_seconds = time.perf_counter() - t1
        past = prefix_output.past_key_values
        cached_logits: list[torch.Tensor] = []
        t2 = time.perf_counter()
        for branch in branches:
            branch_ids = torch.tensor([encode_ids(tokenizer, branch)], dtype=torch.long, device=device)
            attention = torch.ones((1, prefix_ids.shape[1] + branch_ids.shape[1]), dtype=torch.long, device=device)
            with torch.inference_mode():
                output = model(input_ids=branch_ids, attention_mask=attention, past_key_values=copy.deepcopy(past), use_cache=True)
            cached_logits.append(output.logits[0, -1].float().cpu())
        branch_seconds = time.perf_counter() - t2
        max_diff = max(float(torch.max(torch.abs(a - b)).item()) for a, b in zip(fresh_logits, cached_logits))
        return {
            "status": "measured",
            "branches": len(branches),
            "fresh_seconds": fresh_seconds,
            "shared_prefix_prefill_seconds": prefix_seconds,
            "shared_branch_seconds": branch_seconds,
            "fresh_marginal_seconds": fresh_seconds / max(1, len(branches)),
            "shared_marginal_seconds": branch_seconds / max(1, len(branches)),
            "max_abs_logit_difference": max_diff,
            "numerically_equivalent_at_tolerance_1e-3": max_diff <= 1e-3,
        }
    except Exception as exc:  # API capability is itself an experimental result.
        return {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}


def metric_rows(rows: list[dict[str, Any]], prediction_key: str, source: str | None = None) -> dict[str, Any]:
    selected = [
        row for row in rows
        if row["intervention"] == "baseline"
        and prediction_key in row
        and (source is None or row["probability_source"] == source)
        and "__OTHER__" not in row["gold_distribution"]
    ]
    if not selected:
        return {"count": 0}
    nll = 0.0
    brier = 0.0
    correct = 0
    calibration_pairs: list[tuple[float, float]] = []
    for row in selected:
        gold = row["gold_distribution"]
        pred = row[prediction_key]
        if not pred or any(key not in pred for key in gold):
            continue
        nll -= sum(value * math.log(max(1e-12, pred[key])) for key, value in gold.items())
        keys = set(gold) | set(pred)
        brier += sum((pred.get(key, 0.0) - gold.get(key, 0.0)) ** 2 for key in keys)
        predicted_key = max(pred, key=pred.get)
        gold_key = max(gold, key=gold.get)
        correct += int(predicted_key == gold_key)
        confidence = pred[predicted_key]
        calibration_pairs.append((confidence, gold.get(predicted_key, 0.0)))
    count = len(calibration_pairs)
    if count == 0:
        return {"count": 0, "reason": "no rows with aligned prediction and gold support"}
    bins: list[list[tuple[float, float]]] = [[] for _ in range(10)]
    for pair in calibration_pairs:
        bins[min(9, int(pair[0] * 10))].append(pair)
    ece = 0.0
    for bucket in bins:
        if bucket:
            ece += len(bucket) / count * abs(
                sum(item[0] for item in bucket) / len(bucket)
                - sum(item[1] for item in bucket) / len(bucket)
            )
    return {
        "count": count,
        "nll": nll / count,
        "brier": brier / count,
        "accuracy": correct / count,
        "ece_soft": ece,
        "ece_definition": "confidence minus mean gold mass on predicted class, ten bins",
    }


def fit_temperature(rows: list[dict[str, Any]]) -> float:
    dev = [
        row for row in rows
        if row["intervention"] == "baseline"
        and row["probability_source"] == "exact_generative_posterior"
        and "__OTHER__" not in row["gold_distribution"]
        and row["direct_scores"]
        and stable_bucket(row["episode_id"]) % 5 != 0
    ]
    if not dev:
        return 1.0
    best = (float("inf"), 1.0)
    for index in range(1, 161):
        temperature = 0.10 + index * 0.05
        loss = 0.0
        for row in dev:
            pred = softmax(row["direct_scores"], temperature)
            loss -= sum(value * math.log(max(1e-12, pred.get(key, 1e-12))) for key, value in row["gold_distribution"].items())
        loss /= len(dev)
        if loss < best[0]:
            best = (loss, temperature)
    return best[1]


def schema_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for profile in sorted({row["profile"] for row in rows}):
        subset = [row for row in rows if row["profile"] == profile]
        result[profile] = {
            "rows": len(subset),
            "exact_world_direct": metric_rows(subset, "direct_prediction", "exact_generative_posterior"),
            "exact_world_sequence_mean": metric_rows(subset, "sequence_mean_prediction", "exact_generative_posterior"),
            "hard_label_direct": metric_rows(subset, "direct_prediction", "hard_label"),
        }
    return result


def perturbation_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = {}
    reordered = {}
    for row in rows:
        key = (row["episode_id"], row["query_id"], row["profile"], row["template"])
        (reordered if row["intervention"] == "candidate_reorder" else baseline)[key] = row
    drifts: list[float] = []
    for key, before in baseline.items():
        after = reordered.get(key)
        if not after:
            continue
        labels = set(before["direct_prediction"]) & set(after["direct_prediction"])
        drifts.append(sum(abs(before["direct_prediction"][label] - after["direct_prediction"][label]) for label in labels))
    return {
        "candidate_reorder": {
            "paired_rows": len(drifts),
            "mean_l1_drift": sum(drifts) / len(drifts) if drifts else None,
            "max_l1_drift": max(drifts) if drifts else None,
            "strict_target_invariant": True,
        },
        "surface_renderer_siblings": {"status": "coverage depends on eligible query views; causal readout excludes span/relation rows"},
        "evidence_removal": {"status": "not_available_in_current_recon_bank", "reason": "no verified recomputed sibling links selected"},
        "world_intervention": {"status": "not_available_in_current_recon_bank", "reason": "no verified recomputed sibling links selected"},
    }


def run(args: argparse.Namespace) -> None:
    output = Path(args.output)
    episodes = read_jsonl(Path(args.episodes))
    records = records_from_episodes(episodes, args.max_queries)
    profiles = [item for item in args.profiles.split(",") if item]
    templates = [item for item in args.templates.split(",") if item]
    all_rows: dict[str, list[dict[str, Any]]] = {}
    model_summaries: dict[str, Any] = {}
    model_root = Path(args.models)
    for model_name in args.model_names.split(","):
        model_path = model_root / model_name
        summary, rows = evaluate_model(
            model_path, records, profiles, templates, args.batch_size, args.device, args.candidate_reorder
        )
        all_rows[model_name] = rows
        model_summaries[model_name] = summary
        payload = {"summary": summary, "rows": rows}
        write_json(output / f"{model_name}-frozen.json", payload)
        write_json(output / f"{model_name.replace('-base', '')}-frozen.json", payload)
    schema = {name: schema_report(rows) for name, rows in all_rows.items()}
    perturbations = {name: perturbation_report(rows) for name, rows in all_rows.items()}
    calibration: dict[str, Any] = {}
    scaling: dict[str, Any] = {}
    failures: dict[str, Any] = {}
    for name, rows in all_rows.items():
        temperature = fit_temperature(rows)
        exact_raw = metric_rows(rows, "direct_prediction", "exact_generative_posterior")
        exact_seq = metric_rows(rows, "sequence_mean_prediction", "exact_generative_posterior")
        exact_temp_rows = []
        for row in rows:
            clone = dict(row)
            clone["direct_prediction"] = aligned_prediction(
                row["direct_scores"], row["target_kind"], row["gold_distribution"], temperature
            )
            exact_temp_rows.append(clone)
        calibration[name] = {
            "exact_generative_posterior": {
                "raw_direct": exact_raw,
                "raw_sequence_mean": exact_seq,
                "temperature": temperature,
                "temperature_scaled_direct": metric_rows(exact_temp_rows, "direct_prediction", "exact_generative_posterior"),
            },
            "by_probability_source": {
                source: {
                    "direct": metric_rows(rows, "direct_prediction", source),
                    "sequence_mean": metric_rows(rows, "sequence_mean_prediction", source),
                }
                for source in sorted({row["probability_source"] for row in rows})
            },
            "human_and_hard_sources_kept_separate": True,
            "human_disagreement_not_pooled_with_world_posterior": True,
        }
        cardinality: dict[str, Any] = {}
        for cardinality_value in sorted({row["candidate_cardinality"] for row in rows}):
            subset = [row for row in rows if row["candidate_cardinality"] == cardinality_value]
            cardinality[str(cardinality_value)] = {
                "rows": len(subset),
                "direct": metric_rows(subset, "direct_prediction"),
                "open_world_rows": sum("__OTHER__" in row["gold_distribution"] for row in subset),
            }
        scaling[name] = cardinality
        failures[name] = {
            "F1_lexical_tokenization": "inspect candidate_tokens and profile deltas",
            "F2_schema_binding": "compare schema-binding.json profiles",
            "F3_semantic_reasoning": "large exact-world residual after readout comparison",
            "F4_normalization": "compare direct versus sequence distributions",
            "F5_calibration_only": "compare raw versus one-temperature metrics",
            "F6_representation_invariance": "requires eligible renderer sibling rows",
            "F7_evidence_sensitivity": "not claimed; evidence siblings unavailable in this bank",
            "F8_shared_state": model_summaries[name]["shared_state"],
            "representative_episode_ids": [row["episode_id"] for row in rows[:10]],
        }
    comparison = {
        "protocol": "jev-zero-training-recon-v0.1",
        "training_performed": False,
        "phoenix_touched": False,
        "models": model_summaries,
        "query_records": len(records),
        "query_views": sorted({record["query"].get("view") for record in records}),
        "known_limits": [
            "Current bank has controlled candidate reorder but no selected recomputed evidence/world sibling bank.",
            "Open-world rows are reported separately because a native candidate readout lacks an implicit OTHER token.",
            "Span/relation rows are preserved in the corpus but excluded from causal-LM semantic metrics in this pass.",
        ],
    }
    write_json(output / "schema-binding.json", schema)
    write_json(output / "perturbation-response.json", perturbations)
    write_json(output / "calibration.json", calibration)
    write_json(output / "candidate-scaling.json", scaling)
    write_json(output / "shared-state-performance.json", {name: value["shared_state"] for name, value in model_summaries.items()})
    write_json(output / "failure-taxonomy.json", failures)
    write_json(output / "comparison-report.json", comparison)
    print(json.dumps(comparison, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", default=r"D:\codex-runs\jev-corpus-bridge-v01\pilot-episodes.jsonl")
    parser.add_argument("--models", default=r"D:\codex-runs\jev-zero-training-recon-v01\models")
    parser.add_argument("--output", default=r"D:\codex-runs\jev-zero-training-recon-v01\results")
    parser.add_argument("--model-names", default="minicpm5-1b-base,qwen3-0.6b-base")
    parser.add_argument("--max-queries", type=int, default=256)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--profiles", default="name,name_definition,opaque_definition,opaque_only")
    parser.add_argument("--templates", default="A")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--candidate-reorder", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
