"""Single frozen-backbone pass that pools BANK entity and goal mention spans."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

import numpy as np

from common import (HIDDEN, INPUT_SPECS, SEED, canonical_hash, exact_spans,
                    read_jsonl, sha256, write_json)

R0_PRIMITIVES = ("final_token", "full_mean", "first_token", "layer_m4_final", "middle_final")
ENTITY_FEATURES = ("final_mean", "final_last", "middle_mean", "m4_mean")


def source_inputs(bank_root: Path, r0_output: Path):
    manifest_path = bank_root / "manifests" / "release.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("release") != "BANK-v1" or manifest.get("terminal_truth_opened") is not False:
        raise RuntimeError("expected the full BANK-v1 source release")
    r0_lock_path = r0_output / "source-lock.json"
    r0_lock = json.loads(r0_lock_path.read_text(encoding="utf-8"))
    if r0_lock.get("release") != "BANK-v1" or r0_lock.get("bank_manifest_sha256") != sha256(manifest_path):
        raise RuntimeError("Rung-0 source lock does not match the supplied BANK-v1 release")
    rowmap_path = r0_output / "rowmap.jsonl"
    if sha256(rowmap_path) != r0_lock.get("rowmap_sha256"):
        raise RuntimeError("Rung-0 rowmap hash mismatch")
    paths = [(split, bank_root / rel) for split, rel in INPUT_SPECS]
    expected = {split: int(manifest["stats"][split]["input_rows"]) for split, _ in paths}
    source_files = []
    for split, path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        expected_hash = next((x["sha256"] for x in r0_lock["files"] if x["split"] == split), None)
        if sha256(path) != expected_hash:
            raise RuntimeError(f"source input changed after Rung 0: {split}")
        source_files.append({"split": split, "path": str(path.resolve()),
                             "bytes": path.stat().st_size, "sha256": expected_hash,
                             "rows_expected": expected[split]})
    return paths, expected, rowmap_path, {
        "release": "BANK-v1", "manifest_path": str(manifest_path.resolve()),
        "manifest_sha256": sha256(manifest_path), "r0_source_lock_sha256": sha256(r0_lock_path),
        "r0_rowmap_sha256": r0_lock["rowmap_sha256"], "files": source_files,
    }


def build_index(paths, expected, rowmap_path: Path, output: Path):
    index_path = output / "row-mentions.jsonl"
    rowmap_iter = iter(read_jsonl(rowmap_path))
    row_count = entity_count = goal_count = 0
    matched_by_family: dict[str, dict[str, int]] = {}
    missing_examples = []
    temporary = index_path.with_suffix(index_path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as dst:
        for split, path in paths:
            seen = 0
            for row in read_jsonl(path):
                rowmap = next(rowmap_iter)
                row_id = str(row["world_id"])
                if row_id != rowmap["row_id"] or rowmap["split"] != split or rowmap["idx"] != row_count:
                    raise RuntimeError(f"Rung-0 rowmap/input mismatch at row {row_count}")
                text = str(row.get("input_text") or "")
                goal_text_start = text.casefold().rfind("goal:")
                goal_text_start = goal_text_start if goal_text_start >= 0 else len(text)
                goal_args = [str(x) for x in (row.get("goal") or {}).get("args", [])]
                goal_arg_set = set(goal_args)
                family = str(row.get("surface_family") or rowmap.get("surface_family") or "")
                counts = matched_by_family.setdefault(family, {"bindings": 0, "matched": 0,
                    "lexical_context": 0, "symbolic_argument_id": 0, "goal_only_alias": 0,
                    "goal_args": 0, "goal_matched": 0})
                mentions = []
                lookup = {}
                for binding in row.get("bindings") or []:
                    entity_id = str(binding.get("entity_id", ""))
                    mention = str(binding.get("mention", ""))
                    alias_context = exact_spans(text, mention, 0, goal_text_start)
                    id_context = exact_spans(text, entity_id, 0, goal_text_start)
                    alias_anywhere = exact_spans(text, mention)
                    id_anywhere = exact_spans(text, entity_id)
                    if alias_context:
                        spans, alignment = alias_context, "LEXICAL_CONTEXT"
                    elif id_context:
                        spans, alignment = id_context, "SYMBOLIC_ARGUMENT_ID"
                    elif alias_anywhere:
                        spans, alignment = alias_anywhere, "GOAL_ONLY_ALIAS"
                    else:
                        spans, alignment = id_anywhere, "SYMBOLIC_ID_FALLBACK" if id_anywhere else "UNMATCHED"
                    goal_spans = []
                    if entity_id in goal_arg_set:
                        goal_spans = exact_spans(text, mention, goal_text_start)
                        if not goal_spans:
                            goal_spans = exact_spans(text, entity_id, goal_text_start)
                    record = {"entity_index": entity_count, "entity_id": entity_id,
                              "mention": mention, "spans": spans,
                              "matched": bool(spans), "alignment_kind": alignment,
                              "goal": entity_id in goal_arg_set,
                              "goal_spans": goal_spans}
                    mentions.append(record)
                    lookup[entity_id] = record
                    entity_count += 1
                    counts["bindings"] += 1
                    if spans:
                        counts["matched"] += 1
                    if alignment == "LEXICAL_CONTEXT":
                        counts["lexical_context"] += 1
                    elif alignment.startswith("SYMBOLIC"):
                        counts["symbolic_argument_id"] += 1
                    elif alignment == "GOAL_ONLY_ALIAS":
                        counts["goal_only_alias"] += 1
                    elif len(missing_examples) < 24:
                        missing_examples.append({"world_id": row_id, "family": family,
                                                 "entity_id": entity_id, "mention": mention})
                goals = []
                for slot, entity_id in enumerate(goal_args):
                    binding = lookup.get(entity_id)
                    spans = binding["goal_spans"] if binding else []
                    mention = binding["mention"] if binding else ""
                    goals.append({"goal_index": goal_count, "entity_id": entity_id,
                                  "mention": mention, "slot": slot, "spans": spans,
                                  "matched": bool(spans)})
                    goal_count += 1
                    counts["goal_args"] += 1
                    counts["goal_matched"] += int(bool(spans))
                record = {"row_idx": row_count, "world_id": row_id, "split": split,
                          "surface_family": family, "paired_world": rowmap.get("paired_world"),
                          "mentions": mentions, "goals": goals}
                dst.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
                row_count += 1
                seen += 1
            if seen != expected[split]:
                raise RuntimeError(f"{split} rows {seen} != BANK manifest {expected[split]}")
    try:
        next(rowmap_iter)
    except StopIteration:
        pass
    else:
        raise RuntimeError("Rung-0 rowmap has trailing records")
    temporary.replace(index_path)
    report = {"rows": row_count, "entity_bindings": entity_count, "goal_arguments": goal_count,
              "family_span_coverage": matched_by_family, "missing_span_examples": missing_examples,
              "row_mentions_sha256": sha256(index_path), "truth_joined": False}
    write_json(output / "preflight.json", report)
    return report


def configure_torch():
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    torch.use_deterministic_algorithms(True)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.deterministic = True
    return torch


def token_ranges(char_spans, offsets):
    out = []
    if not char_spans:
        return out
    starts = offsets[:, 0]
    ends = offsets[:, 1]
    active = ends > starts
    for start, stop in char_spans:
        positions = np.flatnonzero(active & (starts < stop) & (ends > start))
        if positions.size:
            out.append((int(positions[0]), int(positions[-1]) + 1))
    return out


def grouped_means(torch, values, owners, item_count):
    result = torch.zeros((item_count, values.shape[-1]), dtype=values.dtype, device=values.device)
    if not owners:
        return result
    owner_np = np.asarray(owners, dtype=np.int64)
    counts = np.bincount(owner_np, minlength=item_count)
    present = np.flatnonzero(counts)
    lengths = torch.as_tensor(counts[counts > 0], dtype=torch.long, device=values.device)
    grouped = torch.segment_reduce(values, "mean", lengths=lengths)
    result[torch.as_tensor(present, dtype=torch.long, device=values.device)] = grouped
    return result


def batch_spans(meta_rows, offsets):
    ent_ranges, ent_owners, ent_begin, ent_end = [], [], [], []
    goal_ranges, goal_owners, goal_begin, goal_end = [], [], [], []
    entity_start = int(meta_rows[0]["mentions"][0]["entity_index"]) if meta_rows and meta_rows[0]["mentions"] else None
    if entity_start is None:
        entity_start = next((int(m["entity_index"]) for r in meta_rows for m in r["mentions"]), 0)
    entity_indices = [int(m["entity_index"]) for row in meta_rows for m in row["mentions"]]
    goal_indices = [int(g["goal_index"]) for row in meta_rows for g in row["goals"]]
    entity_count = len(entity_indices)
    goal_count = len(goal_indices)
    entity_base = entity_indices[0] if entity_indices else 0
    goal_base = goal_indices[0] if goal_indices else 0
    for batch_row, row in enumerate(meta_rows):
        row_offsets = offsets[batch_row]
        for mention in row["mentions"]:
            owner = int(mention["entity_index"]) - entity_base
            ranges = token_ranges(mention["spans"], row_offsets)
            ent_begin.append(len(ent_ranges))
            for start, end in ranges:
                ent_ranges.append((batch_row, start, end))
                ent_owners.append(owner)
            ent_end.append(len(ent_ranges))
        for goal in row["goals"]:
            owner = int(goal["goal_index"]) - goal_base
            ranges = token_ranges(goal["spans"], row_offsets)
            goal_begin.append(len(goal_ranges))
            for start, end in ranges:
                goal_ranges.append((batch_row, start, end))
                goal_owners.append(owner)
            goal_end.append(len(goal_ranges))
    return (ent_ranges, ent_owners, entity_count, entity_base,
            goal_ranges, goal_owners, goal_count, goal_base)


def aggregate_layer(torch, state, ranges, owners, item_count, last=False):
    if not ranges:
        return torch.zeros((item_count, HIDDEN), dtype=state.dtype, device=state.device)
    range_array = np.asarray(ranges, dtype=np.int64)
    rows = torch.as_tensor(range_array[:, 0], dtype=torch.long, device=state.device)
    starts = torch.as_tensor(range_array[:, 1], dtype=torch.long, device=state.device)
    ends = torch.as_tensor(range_array[:, 2], dtype=torch.long, device=state.device)
    if last:
        span_vectors = state[rows, ends - 1]
    else:
        prefix = torch.cat((torch.zeros_like(state[:, :1, :]), state.cumsum(dim=1)), dim=1)
        span_vectors = (prefix[rows, ends] - prefix[rows, starts]) / (ends - starts).unsqueeze(-1)
    return grouped_means(torch, span_vectors, owners, item_count)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bank-root", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--r0-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--microbatch-size", type=int, default=16)
    parser.add_argument("--max-length", type=int, default=2048)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--rebuild-index", action="store_true")
    args = parser.parse_args()
    if args.batch_size < args.microbatch_size or args.microbatch_size < 1:
        raise ValueError("require batch-size >= microbatch-size >= 1")
    args.output.mkdir(parents=True, exist_ok=True)
    paths, expected, rowmap_path, sources = source_inputs(args.bank_root, args.r0_output)
    output_rowmap = args.output / "rowmap.jsonl"
    if not output_rowmap.exists():
        shutil.copyfile(rowmap_path, output_rowmap)
    if sha256(output_rowmap) != sources["r0_rowmap_sha256"]:
        raise RuntimeError("copied Rung-0 rowmap hash mismatch")
    mentions_path = args.output / "row-mentions.jsonl"
    if args.rebuild_index or not mentions_path.exists():
        preflight = build_index(paths, expected, rowmap_path, args.output)
    else:
        preflight = json.loads((args.output / "preflight.json").read_text(encoding="utf-8"))
        if sha256(mentions_path) != preflight.get("row_mentions_sha256"):
            raise RuntimeError("existing span index changed; preserve it and inspect before resuming")
    if args.prepare_only:
        print(json.dumps({"phase": "prepare_complete", **{k: preflight[k] for k in
                         ("rows", "entity_bindings", "goal_arguments", "row_mentions_sha256")}}), flush=True)
        return

    torch = configure_torch()
    import transformers
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA:0 required for the one-pass span extraction")
    device = torch.device("cuda:0")
    tokenizer = transformers.AutoTokenizer.from_pretrained(
        args.model, use_fast=True, local_files_only=True, trust_remote_code=False)
    if not tokenizer.is_fast or tokenizer.padding_side != "right":
        raise RuntimeError("fast tokenizer with right padding required for offset alignment")
    model = transformers.AutoModel.from_pretrained(
        args.model, local_files_only=True, trust_remote_code=False, dtype=torch.float32
    ).eval().to(device)
    layers = int(model.config.num_hidden_layers)
    hidden = int(model.config.hidden_size)
    if hidden != HIDDEN or layers != 14:
        raise RuntimeError(f"unexpected pinned 230M architecture: hidden={hidden}, layers={layers}")
    layer_map = {"final": layers, "midpoint_hidden_state_index": 1 + layers // 2,
                 "m4_hidden_state_index": layers - 3}
    source_contract = {**sources, "row_mentions_sha256": sha256(mentions_path),
                       "r0_feature_seal_sha256": sha256(args.r0_output / "features" / "extraction-seal.json")}
    model_contract = {"path": str(args.model.resolve()),
                      "config_sha256": sha256(args.model / "config.json"),
                      "weights_sha256": sha256(args.model / "model.safetensors"),
                      "tokenizer_sha256": sha256(args.model / "tokenizer.json"),
                      "hidden_size": hidden, "layers": layers}
    contract = {"spec_sha256": sha256(Path(__file__).with_name("spec.json")),
                "source": source_contract, "model": model_contract, "batch_size": args.batch_size,
                "microbatch_size": args.microbatch_size, "max_length": args.max_length,
                "dtype": "float32 extraction; little-endian float16 storage",
                "pooling": "per exact occurrence span, then equal-weight mean across occurrences",
                "layer_indices": layer_map, "seed": SEED}
    contract_hash = canonical_hash(contract)
    feature_dir = args.output / "features"
    feature_dir.mkdir(exist_ok=True)
    entity_total = int(preflight["entity_bindings"])
    goal_total = int(preflight["goal_arguments"])
    shapes = {"entity": entity_total, "goal": goal_total}
    arrays = {}
    for group, count in shapes.items():
        for name in ENTITY_FEATURES:
            path = feature_dir / f"{group}_{name}.npy"
            arrays[(group, name)] = path
    progress_path = feature_dir / "progress.json"
    if progress_path.exists():
        progress = json.loads(progress_path.read_text(encoding="utf-8"))
        if progress.get("contract_sha256") != contract_hash:
            raise RuntimeError("resume contract changed; use a new output directory")
        complete_rows = int(progress["complete_rows"])
        complete_entities = int(progress["complete_entities"])
        complete_goals = int(progress["complete_goals"])
        maps = {key: np.lib.format.open_memmap(path, mode="r+", dtype="<f2",
                                               shape=(shapes[key[0]], hidden))
                for key, path in arrays.items()}
    else:
        if any(path.exists() for path in arrays.values()):
            raise RuntimeError("feature files exist without a matching progress receipt")
        complete_rows = complete_entities = complete_goals = 0
        maps = {key: np.lib.format.open_memmap(path, mode="w+", dtype="<f2",
                                              shape=(shapes[key[0]], hidden))
                for key, path in arrays.items()}
        progress = {"contract_sha256": contract_hash, "complete_rows": 0,
                    "complete_entities": 0, "complete_goals": 0}
        write_json(progress_path, progress)

    mentions_iter = iter(read_jsonl(mentions_path))
    input_iter = (row for _, path in paths for row in read_jsonl(path))
    skipped = 0
    rows_batch, metas_batch = [], []
    started = time.perf_counter()

    def process(rows, metas):
        nonlocal complete_entities, complete_goals
        texts = [str(row.get("input_text") or "") for row in rows]
        encoded = tokenizer(texts, padding=True, truncation=False, add_special_tokens=True,
                            return_offsets_mapping=True, return_tensors="pt")
        if encoded["input_ids"].shape[1] > args.max_length:
            raise RuntimeError(f"input longer than max-length: {metas[0]['world_id']}")
        offsets_np = encoded["offset_mapping"].cpu().numpy()
        (entity_ranges, entity_owners, entity_n, entity_base,
         goal_ranges, goal_owners, goal_n, goal_base) = batch_spans(metas, offsets_np)
        ids = encoded["input_ids"].to(device)
        mask = encoded["attention_mask"].to(device)
        with torch.inference_mode():
            output = model(input_ids=ids, attention_mask=mask, output_hidden_states=True,
                           use_cache=False, return_dict=True)
        states = output.hidden_states
        if states is None or len(states) != layers + 1:
            raise RuntimeError("hidden-state stack unavailable")
        selected = {
            "final_mean": (states[-1], False),
            "final_last": (states[-1], True),
            "middle_mean": (states[layer_map["midpoint_hidden_state_index"]], False),
            "m4_mean": (states[layer_map["m4_hidden_state_index"]], False),
        }
        entity_stop = entity_base + entity_n
        goal_stop = goal_base + goal_n
        for name, (state, last) in selected.items():
            entity_values = aggregate_layer(torch, state, entity_ranges, entity_owners,
                                            entity_n, last=last)
            goal_values = aggregate_layer(torch, state, goal_ranges, goal_owners,
                                          goal_n, last=last)
            maps[("entity", name)][entity_base:entity_stop] = entity_values.detach().cpu().numpy().astype("<f2")
            maps[("goal", name)][goal_base:goal_stop] = goal_values.detach().cpu().numpy().astype("<f2")
        complete_entities = entity_stop
        complete_goals = goal_stop
        del output, states, ids, mask, encoded
        return complete_entities, complete_goals

    for row_idx, (row, meta) in enumerate(zip(input_iter, mentions_iter)):
        if row_idx != int(meta["row_idx"]) or str(row["world_id"]) != meta["world_id"]:
            raise RuntimeError(f"input/mention-index mismatch at row {row_idx}")
        if row_idx < complete_rows:
            skipped += 1
            continue
        rows_batch.append(row)
        metas_batch.append(meta)
        if len(rows_batch) >= args.batch_size:
            for start in range(0, len(rows_batch), args.microbatch_size):
                stop = min(start + args.microbatch_size, len(rows_batch))
                process(rows_batch[start:stop], metas_batch[start:stop])
            complete_rows = row_idx + 1
            rows_batch.clear()
            metas_batch.clear()
            for array in maps.values():
                array.flush()
            write_json(progress_path, {"contract_sha256": contract_hash,
                                      "complete_rows": complete_rows,
                                      "complete_entities": complete_entities,
                                      "complete_goals": complete_goals})
            if complete_rows % 4096 < args.batch_size:
                print(json.dumps({"phase": "extract", "rows": complete_rows,
                                  "total": preflight["rows"],
                                  "rows_per_second": round(complete_rows / max(time.perf_counter() - started, 1e-9), 2),
                                  "entities": complete_entities, "goal_vectors": complete_goals,
                                  "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device))}),
                      flush=True)
    if rows_batch:
        for start in range(0, len(rows_batch), args.microbatch_size):
            stop = min(start + args.microbatch_size, len(rows_batch))
            process(rows_batch[start:stop], metas_batch[start:stop])
        complete_rows = preflight["rows"]
    if complete_rows != preflight["rows"] or complete_entities != entity_total or complete_goals != goal_total:
        raise RuntimeError(f"incomplete extraction rows/entities/goals={complete_rows}/{complete_entities}/{complete_goals}")
    for array in maps.values():
        array.flush()
    del maps
    torch.cuda.synchronize(device)
    receipts = {}
    for key, path in arrays.items():
        receipts[f"{key[0]}_{key[1]}"] = {"path": str(path.resolve()), "sha256": sha256(path),
                                           "shape": [shapes[key[0]], hidden], "dtype": "float16-le"}
    receipt = {"schema": "phoenix.bank-v1-graph-local-extraction/v2",
               "run_id": "BANK-v1-GRAPH-SURFACE-V2-2026-09-29",
               "rows": preflight["rows"], "entity_bindings": entity_total,
               "goal_arguments": goal_total, "source": source_contract, "model": model_contract,
               "contract": contract, "contract_sha256": contract_hash,
               "layer_indices": layer_map, "features": receipts,
               "row_mentions_sha256": sha256(mentions_path),
               "truth_joined": False, "generation": False, "fine_tuning": False,
               "forward_passes_per_input": 1,
               "elapsed_seconds": time.perf_counter() - started,
               "gpu_peak_allocated_bytes": int(torch.cuda.max_memory_allocated(device)),
               "gpu_peak_reserved_bytes": int(torch.cuda.max_memory_reserved(device)),
               "runtime": {"torch": torch.__version__, "transformers": transformers.__version__,
                           "device": torch.cuda.get_device_name(device)}}
    write_json(feature_dir / "extraction-seal.json", receipt)
    progress_path.unlink(missing_ok=True)
    print(json.dumps({"phase": "extract_complete", "rows": complete_rows,
                      "entities": entity_total, "goal_vectors": goal_total,
                      "elapsed_seconds": receipt["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
