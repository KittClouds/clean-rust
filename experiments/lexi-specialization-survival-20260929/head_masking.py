"""Execution lock, sampling, frozen readouts, and shared metrics for head masking."""
from __future__ import annotations

import argparse
import collections
import gc
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from head_masking_protocol import (
    BATCH_SIZE, GRAPH_ROOT, GRAPH_SPEC, MAX_LENGTH, MODEL_INFO, OUTPUT_ROOT, R0_ROOT,
    PRIMITIVES, READOUT_HEADS, SURFACES, TEST_SPLITS,
    apply_readouts, cached_primitives, compare_global, configure_torch,
    load_mentions, load_readout, load_rows, load_sample, read_json, read_jsonl,
    readout_paths, sha256_file, span_token_indices, vector_surfaces,
    validate_lock, write_json, prepare,
)


def rankdata(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    sorted_values = values[order]
    start = 0
    while start < len(values):
        stop = start + 1
        while stop < len(values) and sorted_values[stop] == sorted_values[start]:
            stop += 1
        ranks[order[start:stop]] = 0.5 * (start + stop - 1) + 1.0
        start = stop
    return ranks


def rank_corr(left: np.ndarray, right: np.ndarray) -> float | None:
    if len(left) < 2:
        return None
    x, y = rankdata(left), rankdata(right)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def graph_model_and_scaler(torch):
    sys.path.insert(0, str(GRAPH_SPEC))
    from fit_graph import load_saved_head
    path = GRAPH_ROOT / "models" / "edge_existence-middle_plus_final-tiny_mlp.pt"
    scaler_path = GRAPH_ROOT / "scalers" / "local-middle_plus_final.npz"
    with np.load(scaler_path, allow_pickle=False) as archive:
        mean, scale = np.array(archive["mean"]), np.array(archive["scale"])
    if mean.shape != (2048,) or scale.shape != (2048,):
        raise RuntimeError("edge-existence scaler dimension mismatch")
    head = load_saved_head(torch, path, "edge_existence", "tiny_mlp", 2048)
    return head.eval(), mean.astype(np.float32), scale.astype(np.float32)


def local_feature_files(model_key: str) -> tuple[Path, Path]:
    root = MODEL_INFO[model_key]["local_features"]
    return root / "entity_middle_mean.npy", root / "entity_final_mean.npy"


def load_local_mmaps(model_key: str):
    mid_path, final_path = local_feature_files(model_key)
    middle = np.load(mid_path, mmap_mode="r", allow_pickle=False)
    final = np.load(final_path, mmap_mode="r", allow_pickle=False)
    if middle.shape != final.shape or middle.ndim != 2 or middle.shape[1] != 1024:
        raise RuntimeError(f"bad local cache shape for {model_key}")
    return middle, final


def pair_vectors_from_cache(model_key: str, pairs: list[dict]) -> np.ndarray:
    middle, final = load_local_mmaps(model_key)
    ids = sorted({int(pair["a_idx"]) for pair in pairs} |
                 {int(pair["b_idx"]) for pair in pairs})
    features = {
        index: np.concatenate((middle[index].astype(np.float32),
                               final[index].astype(np.float32)))
        for index in ids
    }
    return np.stack([
        np.concatenate((features[int(pair["a_idx"])], features[int(pair["b_idx"])]))
        for pair in pairs
    ]).astype(np.float32)


def score_edge_pairs(torch, model, pair_features: np.ndarray, mean: np.ndarray,
                     scale: np.ndarray) -> np.ndarray:
    if not len(pair_features):
        return np.empty(0, dtype=np.float32)
    a = (pair_features[:, :2048] - mean) / scale
    b = (pair_features[:, 2048:] - mean) / scale
    scores = []
    with torch.inference_mode():
        for start in range(0, len(a), 1024):
            at = torch.from_numpy(np.ascontiguousarray(a[start:start + 1024])).to("cuda:0")
            bt = torch.from_numpy(np.ascontiguousarray(b[start:start + 1024])).to("cuda:0")
            logits = model(at, bt, None)
            scores.extend((logits[:, 1] - logits[:, 0]).float().cpu().numpy().tolist())
    return np.asarray(scores, dtype=np.float32)


def compare_graph(baseline: np.ndarray, masked: np.ndarray, pairs: list[dict]) -> dict:
    families = np.asarray([pair["family"] for pair in pairs], dtype=object)
    held = np.isin(families, ("S7", "S8", "S9"))
    populations = {
        "all": np.ones(len(pairs), dtype=np.bool_),
        "held_renderers_S7_S8_S9": held,
        "other_renderers": ~held,
    }
    for split in TEST_SPLITS:
        populations[split] = np.asarray([pair["split"] == split for pair in pairs], dtype=np.bool_)
    result = {}
    for name, mask in populations.items():
        left, right = baseline[mask], masked[mask]
        if not len(left):
            result[name] = {"n": 0}
            continue
        result[name] = {
            "n": int(len(left)),
            "mean_abs_score_delta": float(np.mean(np.abs(right - left))),
            "p95_abs_score_delta": float(np.quantile(np.abs(right - left), 0.95)),
            "sign_flip_rate": float(np.mean((left >= 0) != (right >= 0))),
            "score_rank_correlation": rank_corr(left, right),
        }
    return result


def install_hooks(model, layers: list[int], q_heads: int, head_dim: int, holder: dict):
    handles = []
    for layer_id in layers:
        projection = model.layers[layer_id].self_attn.out_proj
        if projection.in_features != q_heads * head_dim:
            raise RuntimeError(f"unexpected attention output shape in layer {layer_id}")

        def hook(module, args, selected_layer=layer_id):
            condition = holder.get("condition")
            if condition is None or int(condition["layer"]) != selected_layer:
                return None
            value = args[0]
            if value.shape[-1] != q_heads * head_dim:
                raise RuntimeError(f"attention head axis changed in layer {selected_layer}")
            selected = condition["heads"]
            start, stop = min(selected) * head_dim, (max(selected) + 1) * head_dim
            if selected != list(range(min(selected), max(selected) + 1)):
                raise RuntimeError("mask group must be contiguous")
            masked_value = value.clone()
            masked_value[..., start:stop] = 0
            return (masked_value, *args[1:])

        handles.append(projection.register_forward_pre_hook(hook))
    return handles


def run_condition(torch, tokenizer, model, holder, condition: dict,
                  rows: dict[int, dict], global_rows: list[dict],
                  row_mentions: dict[int, list[dict]], needed_entities: set[int],
                  batch_size: int) -> tuple[dict[str, np.ndarray], dict[int, np.ndarray]]:
    global_pos = {int(item["idx"]): i for i, item in enumerate(global_rows)}
    global_primitives = {
        name: np.zeros((len(global_rows), 1024), dtype=np.float32) for name in PRIMITIVES
    }
    entity_sum = {entity_id: np.zeros(2048, dtype=np.float32) for entity_id in needed_entities}
    entity_count = collections.Counter()
    indexes = sorted(rows)
    holder["condition"] = None if condition["condition_id"] == "unmasked" else condition
    for offset in range(0, len(indexes), batch_size):
        batch_indices = indexes[offset:offset + batch_size]
        batch_rows = [rows[index] for index in batch_indices]
        encoded = tokenizer([row["input_text"] for row in batch_rows], padding=True,
                            truncation=False, add_special_tokens=True,
                            return_offsets_mapping=True, return_tensors="pt")
        if encoded["input_ids"].shape[1] > MAX_LENGTH:
            raise RuntimeError(f"sample text exceeds locked max length: {batch_rows[0]['world_id']}")
        offsets = encoded["offset_mapping"].cpu().numpy()
        ids = encoded["input_ids"].to("cuda:0")
        attention = encoded["attention_mask"].to("cuda:0")
        with torch.inference_mode():
            output = model(input_ids=ids, attention_mask=attention, output_hidden_states=True,
                           use_cache=False, return_dict=True)
        states = output.hidden_states
        if states is None or len(states) != 15:
            raise RuntimeError("expected the locked 14-layer hidden-state stack")
        vectors = vector_surfaces(states, attention, torch)
        for name in PRIMITIVES:
            target = global_primitives[name]
            source = vectors[name]
            for batch_pos, row_index in enumerate(batch_indices):
                position = global_pos.get(row_index)
                if position is not None:
                    target[position] = source[batch_pos]

        selected_rows = [i for i, row_index in enumerate(batch_indices)
                         if row_index in row_mentions]
        if selected_rows:
            middle_cpu = states[8].detach().float().cpu().numpy()
            final_cpu = states[-1].detach().float().cpu().numpy()
            for batch_pos in selected_rows:
                row_index = batch_indices[batch_pos]
                for mention in row_mentions[row_index]:
                    entity_id = int(mention["entity_index"])
                    for span in mention["spans"]:
                        token_ids = span_token_indices(offsets[batch_pos], span)
                        if not len(token_ids):
                            continue
                        entity_sum[entity_id][:1024] += middle_cpu[batch_pos, token_ids].mean(axis=0)
                        entity_sum[entity_id][1024:] += final_cpu[batch_pos, token_ids].mean(axis=0)
                        entity_count[entity_id] += 1
        del output, states, vectors, encoded, ids, attention

    holder["condition"] = None
    entity_features = {}
    for entity_id, vector in entity_sum.items():
        count = entity_count[entity_id]
        if count:
            vector /= count
        entity_features[entity_id] = vector
    return global_primitives, entity_features


def score_masked_pairs(torch, graph_head, entity_features: dict[int, np.ndarray],
                       pairs: list[dict], mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    zero = np.zeros(2048, dtype=np.float32)
    pair_features = np.stack([
        np.concatenate((
            entity_features.get(int(pair["a_idx"]), zero),
            entity_features.get(int(pair["b_idx"]), zero),
        ))
        for pair in pairs
    ]).astype(np.float32, copy=False)
    return score_edge_pairs(torch, graph_head, pair_features, mean, scale)


def verify_unmasked_parity(model_key: str, fresh: dict[str, np.ndarray],
                           cached: dict[str, np.ndarray], count: int = 8) -> dict:
    checks = {}
    for name in PRIMITIVES:
        delta = float(np.max(np.abs(fresh[name][:count] - cached[name][:count])))
        checks[name] = delta
        if not math.isfinite(delta) or delta > 2.5e-4:
            raise RuntimeError(f"{model_key} unmasked cache parity failed for {name}: {delta}")
    return checks


def summarize_model(torch, model_key: str, output: Path, lock: dict,
                    global_rows: list[dict], graph_pairs: list[dict]) -> None:
    info = MODEL_INFO[model_key]
    model_path = info["path"]
    feature_root = info["features"]
    row_indices = [int(row["idx"]) for row in global_rows]
    baseline_primitives = cached_primitives(feature_root, row_indices)
    paths = readout_paths(model_key)
    baseline_outputs = apply_readouts(baseline_primitives, paths)
    rowmap_path = R0_ROOT / "rowmap.jsonl"
    pair_rows = {int(pair["row_idx"]) for pair in graph_pairs}
    needed_row_indices = set(row_indices) | pair_rows
    rows, _ = load_rows(rowmap_path, global_rows, graph_pairs)
    needed_entities = {int(pair["a_idx"]) for pair in graph_pairs} | {
        int(pair["b_idx"]) for pair in graph_pairs
    }
    row_mentions = load_mentions(GRAPH_ROOT / "row-mentions.jsonl",
                                 pair_rows, needed_entities)

    graph_head, graph_mean, graph_scale = graph_model_and_scaler(torch)
    baseline_graph_scores = score_edge_pairs(
        torch, graph_head, pair_vectors_from_cache(model_key, graph_pairs),
        graph_mean, graph_scale
    )
    config = read_json(model_path / "config.json")
    full_layers = [i for i, kind in enumerate(config["layer_types"])
                   if kind == "full_attention"][-4:]
    q_heads = int(config.get("num_attention_heads", config.get("num_heads")))
    kv_heads = int(config.get("num_key_value_heads", q_heads))
    head_dim = int(config["hidden_size"]) // q_heads
    if kv_heads * (q_heads // kv_heads) != q_heads:
        raise RuntimeError("invalid GQA dimensions")
    holder = {"condition": None}

    print(json.dumps({"phase": "model_load", "model": model_key,
                      "path": str(model_path)}), flush=True)
    from transformers import AutoModel, AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(model_path, use_fast=True,
                                               local_files_only=True, trust_remote_code=False)
    if not tokenizer.is_fast or tokenizer.padding_side != "right":
        raise RuntimeError("locked tokenizer contract requires fast right-padding")
    model = AutoModel.from_pretrained(model_path, local_files_only=True,
                                      trust_remote_code=False, dtype=torch.float32).eval().to("cuda:0")
    handles = install_hooks(model, full_layers, q_heads, head_dim, holder)

    model_out = output / "results" / model_key
    model_out.mkdir(parents=True, exist_ok=True)
    fresh_unmasked = None
    parity = None
    condition_count = len(lock["conditions"])
    for condition_index, condition in enumerate(lock["conditions"], start=1):
        result_path = model_out / f"{condition['condition_id']}.json"
        if result_path.exists():
            saved = read_json(result_path)
            if saved.get("execution_lock_sha256") != lock["lock_sha256"]:
                raise RuntimeError(f"stale condition receipt: {result_path}")
            print(json.dumps({"phase": "skip_complete_condition", "model": model_key,
                              "condition": condition["condition_id"]}), flush=True)
            continue
        started = time.perf_counter()
        masked_primitives, masked_entities = run_condition(
            torch, tokenizer, model, holder, condition, rows, global_rows,
            row_mentions, needed_entities, BATCH_SIZE
        )
        if fresh_unmasked is None:
            fresh_unmasked, _ = run_condition(
                torch, tokenizer, model, holder,
                {"condition_id": "unmasked", "layer": -1, "heads": []},
                rows, global_rows, row_mentions, needed_entities, BATCH_SIZE
            )
            cached = cached_primitives(feature_root, row_indices)
            parity = verify_unmasked_parity(model_key, fresh_unmasked, cached)
        masked_outputs = apply_readouts(masked_primitives, paths)
        global_change = compare_global(baseline_outputs, masked_outputs, global_rows)
        masked_graph_scores = score_masked_pairs(
            torch, graph_head, masked_entities, graph_pairs, graph_mean, graph_scale
        )
        graph_change = compare_graph(baseline_graph_scores, masked_graph_scores, graph_pairs)
        missing_spans = sum(not np.any(masked_entities.get(entity_id, np.zeros(2048)))
                            for entity_id in needed_entities)
        record = {
            "schema": "phoenix.lexi-head-masking/condition-result-v1",
            "execution_lock_sha256": lock["lock_sha256"],
            "model": model_key,
            "condition": condition,
            "sample_counts": {
                "whole_row": len(global_rows),
                "graph_pairs": len(graph_pairs),
                "graph_entities_missing_spans": int(missing_spans),
            },
            "unmasked_cache_parity_max_abs": parity,
            "truth_fields_used": False,
            "global_readout_sensitivity": global_change,
            "edge_existence_sensitivity": graph_change,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(result_path, record)
        print(json.dumps({
            "phase": "condition_complete",
            "model": model_key,
            "condition": condition["condition_id"],
            "progress": f"{condition_index}/{condition_count}",
            "seconds": round(record["elapsed_seconds"], 1),
            "decision_flip": round(global_change.get("base_frozen", {}).get(
                "middle_plus_final", {}).get("all", {}).get("heads", {}).get(
                    "decision", {}).get("prediction_flip_rate", 0.0), 4),
            "edge_sign_flip": round(graph_change["all"]["sign_flip_rate"], 4),
        }, sort_keys=True), flush=True)
        del masked_primitives, masked_entities, masked_outputs
        gc.collect()
        torch.cuda.empty_cache()

    for handle in handles:
        handle.remove()
    del model, tokenizer, graph_head
    gc.collect()
    torch.cuda.empty_cache()
    complete = sorted(model_out.glob("layer-*.json"))
    if len(complete) == condition_count:
        manifest = {
            "schema": "phoenix.lexi-head-masking/model-complete-v1",
            "model": model_key,
            "execution_lock_sha256": lock["lock_sha256"],
            "conditions": [{"path": str(path.resolve()), "sha256": sha256_file(path)}
                           for path in complete],
            "status": "MASKING_COMPLETE_LABEL_BLIND",
        }
        write_json(model_out / "model-complete.json", manifest)


def aggregate_results(output: Path, lock: dict) -> None:
    all_records = []
    for model_key in MODEL_INFO:
        model_dir = output / "results" / model_key
        for condition in lock["conditions"]:
            path = model_dir / f"{condition['condition_id']}.json"
            if not path.is_file():
                raise RuntimeError(f"missing result {path}")
            record = read_json(path)
            if record.get("execution_lock_sha256") != lock["lock_sha256"]:
                raise RuntimeError(f"result lock mismatch: {path}")
            all_records.append(record)
    result = {
        "schema": "phoenix.lexi-head-masking/results-v1",
        "execution_lock_sha256": lock["lock_sha256"],
        "status": "COMPLETE_LABEL_BLIND_OPERATIONAL_ABLATION",
        "truth_fields_used": False,
        "model_count": len(MODEL_INFO),
        "condition_count_per_model": len(lock["conditions"]),
        "result_count": len(all_records),
        "results": all_records,
    }
    write_json(output / "HEAD-MASKING-RESULTS.json", result)
    lines = [
        "# Lexi attention-group masking",
        "",
        "Label-blind operational sensitivity of the locked readouts. The report measures output movement and prediction stability; it does not claim accuracy loss or a mechanistic explanation.",
        "",
        f"- Execution lock: {lock['lock_sha256']}",
        f"- Rows per model: {lock['sampling']['global_row_count']}",
        f"- Edge candidate pairs per model: {lock['sampling']['graph_pair_count']}",
        f"- Conditions per model: {len(lock['conditions'])}",
        "- No fitting, label read, retrieval, or authority change.",
        "",
        "| Model | Readout lane | Mask | Decision flips | Route tuple flips | NLI flips | Edge sign flips | Edge rank corr. |",
        "|---|---|---|---:|---:|---:|---:|---:|",
    ]
    for record in all_records:
        graph = record["edge_existence_sensitivity"]["all"]
        for lane, surface_metrics in record["global_readout_sensitivity"].items():
            decision = [
                v["all"]["heads"]["decision"].get("prediction_flip_rate")
                for name, v in surface_metrics.items() if name != "first_token"
            ]
            route = [
                v["all"].get("route_tuple_flip_rate")
                for name, v in surface_metrics.items() if name != "first_token"
            ]
            nli = [
                v["all"]["heads"]["nli"].get("prediction_flip_rate")
                for name, v in surface_metrics.items() if name != "first_token"
            ]
            dead = surface_metrics["first_token"]["all"]["heads"]["decision"].get(
                "prediction_flip_rate")
            lines.append(
                f"| {record['model']} | {lane} | {record['condition']['condition_id']} "
                f"| {np.mean(decision):.3f} (mean) | {np.mean(route):.3f} (mean) "
                f"| {np.mean(nli):.3f} (mean) | {graph.get('sign_flip_rate', float('nan')):.3f} "
                f"| {graph.get('score_rank_correlation')} |"
            )
            lines.append(
                f"|  |  | dead first-token control | {dead:.3f} | — | — | — | — |"
            )
    lines += [
        "",
        "Per-surface, per-readout, per-renderer, and per-test-split measurements are in HEAD-MASKING-RESULTS.json.",
        "This pass stops at layer and KV-sharing query-head groups. Individual-head tests are excluded.",
    ]
    (output / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(output: Path, model_keys: list[str] | None) -> None:
    lock = validate_lock(output)
    selected_rows, pairs = load_sample(lock)
    torch = configure_torch()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 is required")
    requested = model_keys or list(MODEL_INFO)
    unknown = set(requested) - set(MODEL_INFO)
    if unknown:
        raise ValueError(f"unknown model keys: {sorted(unknown)}")
    for model_key in requested:
        summarize_model(torch, model_key, output, lock, selected_rows, pairs)
    if set(requested) == set(MODEL_INFO):
        aggregate_results(output, lock)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare", "run", "summarize"))
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--models", nargs="*", choices=tuple(MODEL_INFO))
    args = parser.parse_args()
    if args.mode == "prepare":
        prepare(args.output)
    elif args.mode == "run":
        run(args.output, args.models)
    else:
        aggregate_results(args.output, validate_lock(args.output))


if __name__ == "__main__":
    main()
