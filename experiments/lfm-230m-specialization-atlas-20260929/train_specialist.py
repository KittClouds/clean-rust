"""Fine-tune one independent LFM2.5-230M external-task specialization arm."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import time
from collections import Counter
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import save_file
from transformers import AutoModel, AutoTokenizer

SEED = 20260929
SCHEDULE = (250, 500, 1000, 2000)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def stable_seed(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "little")


class LoRALinear(nn.Module):
    """Frozen projection plus a small trainable low-rank update."""

    def __init__(self, base: nn.Linear, rank: int = 8, alpha: float = 16.0):
        super().__init__()
        self.base = base
        self.base.weight.requires_grad_(False)
        if self.base.bias is not None:
            self.base.bias.requires_grad_(False)
        self.a = nn.Parameter(torch.empty(rank, base.in_features, device=base.weight.device,
                                          dtype=base.weight.dtype))
        self.b = nn.Parameter(torch.zeros(base.out_features, rank, device=base.weight.device,
                                          dtype=base.weight.dtype))
        nn.init.kaiming_uniform_(self.a, a=math.sqrt(5))
        self.scale = alpha / rank

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.base(values) + F.linear(F.linear(values, self.a), self.b) * self.scale


def attach_lora(backbone, rank: int = 8):
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    selected = [i for i, kind in enumerate(backbone.config.layer_types)
                if kind == "full_attention"][-4:]
    adapted = []
    for index in selected:
        attention = backbone.layers[index].self_attn
        for name in ("q_proj", "v_proj"):
            module = LoRALinear(getattr(attention, name), rank=rank)
            setattr(attention, name, module)
            adapted.append((index, name, module))
    if not adapted:
        raise RuntimeError("no full-attention q/v projections found for late-layer LoRA")
    return adapted


def export_state_dict(backbone, lora_layers):
    """Export regular LFM keys, merging LoRA deltas so AutoModel can load the result."""
    if not lora_layers:
        return {key: value.detach().to(torch.bfloat16).cpu().contiguous()
                for key, value in backbone.state_dict().items()}
    modules = {f"layers.{index}.self_attn.{name}.": module
               for index, name, module in lora_layers}
    result = {}
    for key, value in backbone.state_dict().items():
        prefix = next((candidate for candidate in modules if key.startswith(candidate)), None)
        if prefix is None:
            result[key] = value.detach().to(torch.bfloat16).cpu().contiguous()
            continue
        suffix = key[len(prefix):]
        module = modules[prefix]
        if suffix == "base.weight":
            merged = module.base.weight.detach() + (module.b.detach() @ module.a.detach()) * module.scale
            result[prefix + "weight"] = merged.to(torch.bfloat16).cpu().contiguous()
        elif suffix == "base.bias":
            result[prefix + "bias"] = value.detach().to(torch.bfloat16).cpu().contiguous()
        elif suffix in {"a", "b"}:
            continue
        else:
            raise RuntimeError(f"unexpected wrapped projection state key: {key}")
    return result


def make_gliclass_prompt(row: dict, rng_seed: int) -> tuple[str, list[tuple[int, int, float]]]:
    positives = set(row["true_labels"])
    candidates = list(dict.fromkeys(row["all_labels"]))
    rng = random.Random(rng_seed ^ stable_seed(row["row_id"]))
    rng.shuffle(candidates)
    lines = ["Task: decide which candidate labels apply to the passage.", "Passage:", row["text"],
             "Candidates:"]
    spans = []
    length = sum(len(x) for x in lines) + len(lines) - 1
    for i, label in enumerate(candidates, 1):
        prefix = f"{i}. "
        line = prefix + label
        start = length + len(prefix)
        end = start + len(label)
        lines.append(line)
        spans.append((start, end, float(label in positives)))
        length += len(line) + 1
    return "\n".join(lines), spans


def encode_gliclass(rows: list[dict], tokenizer, max_length: int):
    encoded_rows = []
    for row in rows:
        prompt, spans = make_gliclass_prompt(row, SEED)
        # Preserve every candidate; shorten only the passage if the schema is long.
        passage = row["text"]
        for attempt in range(7):
            prompt, spans = make_gliclass_prompt({**row, "text": passage}, SEED)
            encoded = tokenizer(prompt, add_special_tokens=True, truncation=False,
                                return_offsets_mapping=True)
            if len(encoded["input_ids"]) <= max_length:
                break
            words = passage.split()
            keep = max(0, int(len(words) * (0.75 ** (attempt + 1))))
            passage = " ".join(words[:keep])
        else:
            raise RuntimeError(f"candidate schema exceeds max length for {row['row_id']}")
        positions = []
        for start, end, target in spans:
            matches = [i for i, (left, right) in enumerate(encoded["offset_mapping"])
                       if right > left and right > start and left < end]
            if not matches:
                raise RuntimeError(f"candidate token alignment failed in {row['row_id']}")
            positions.append((matches[-1], target))
        encoded_rows.append({"input_ids": encoded["input_ids"], "positions": positions,
                             "row_id": row["row_id"]})
    return encoded_rows


def ner_tag_space(rows: list[dict]) -> tuple[list[str], list[str]]:
    tags = {tag for row in rows for tag in row["ner_tags"]}
    tags.add("O")
    ordered = ["O"] + sorted(tag for tag in tags if tag != "O")
    types = sorted({tag[2:] for tag in ordered if tag.startswith(("B-", "I-"))})
    return ordered, types


def encode_openner(rows: list[dict], tokenizer, tag_names: list[str], types: list[str],
                   max_length: int):
    tag_to_id = {tag: i for i, tag in enumerate(tag_names)}
    prompt_words = ["Task:", "extract", "named", "entities.", "Types:",
                    *[f"{name}." for name in types], "Text:"]
    prefix_len = len(prompt_words)
    encoded_rows = []
    for row in rows:
        words = prompt_words + row["tokens"]
        enc = tokenizer(words, is_split_into_words=True, add_special_tokens=True,
                         truncation=True, max_length=max_length)
        word_ids = enc.word_ids()
        labels = [-100] * len(enc["input_ids"])
        source_word_indices = [-100] * len(enc["input_ids"])
        previous = None
        for token_i, word_i in enumerate(word_ids):
            if word_i is None or word_i < prefix_len or word_i == previous:
                previous = word_i
                continue
            source_i = word_i - prefix_len
            if source_i < len(row["ner_tags"]):
                tag = row["ner_tags"][source_i]
                if tag in tag_to_id:
                    labels[token_i] = tag_to_id[tag]
                    source_word_indices[token_i] = source_i
            previous = word_i
        encoded_rows.append({"input_ids": enc["input_ids"], "labels": labels,
                             "source_word_indices": source_word_indices,
                             "row_id": row["row_id"], "source": row["source"],
                             "tokens": row["tokens"], "gold_tags": row["ner_tags"]})
    return encoded_rows


def collate(encoded: list[dict], pad_id: int, arm: str):
    max_len = max(len(row["input_ids"]) for row in encoded)
    ids = torch.full((len(encoded), max_len), pad_id, dtype=torch.long)
    mask = torch.zeros((len(encoded), max_len), dtype=torch.long)
    for i, row in enumerate(encoded):
        n = len(row["input_ids"])
        ids[i, :n] = torch.tensor(row["input_ids"], dtype=torch.long)
        mask[i, :n] = 1
    result = {"input_ids": ids, "attention_mask": mask, "rows": encoded}
    if arm == "openner_en":
        labels = torch.full((len(encoded), max_len), -100, dtype=torch.long)
        for i, row in enumerate(encoded):
            labels[i, :len(row["labels"])] = torch.tensor(row["labels"], dtype=torch.long)
        result["labels"] = labels
    return result


def entity_spans(tags: list[str]) -> set[tuple[int, int, str]]:
    spans: set[tuple[int, int, str]] = set()
    active_type = None
    start = 0
    for i, tag in enumerate(tags + ["O"]):
        if tag == "O" or "-" not in tag:
            prefix, entity_type = "O", ""
        else:
            prefix, entity_type = tag.split("-", 1)
        if active_type is not None and (prefix != "I" or entity_type != active_type):
            spans.add((start, i, active_type))
            active_type = None
        if prefix == "B" or (prefix == "I" and active_type is None):
            active_type, start = entity_type, i
    return spans


def gliclass_metrics(predictions: list[tuple[list[float], list[float]]]):
    tp = fp = fn = exact = rows = 0
    for scores, targets in predictions:
        guessed = {i for i, score in enumerate(scores) if score >= 0.5}
        truth = {i for i, value in enumerate(targets) if value >= 0.5}
        tp += len(guessed & truth)
        fp += len(guessed - truth)
        fn += len(truth - guessed)
        exact += int(guessed == truth)
        rows += 1
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    return {"rows": rows, "candidate_tp": tp, "candidate_fp": fp, "candidate_fn": fn,
            "candidate_precision": precision, "candidate_recall": recall,
            "candidate_micro_f1": 2 * precision * recall / max(precision + recall, 1e-12),
            "exact_candidate_set_match": exact / max(rows, 1)}


def ner_metrics(records: list[dict]):
    tp = fp = fn = token_ok = token_n = 0
    per_source = {}
    for row in records:
        actual = entity_spans(row["gold_tags"])
        predicted = entity_spans(row["pred_tags"][:len(row["gold_tags"])])
        a = tp + len(actual & predicted)
        tp += len(actual & predicted)
        fp += len(predicted - actual)
        fn += len(actual - predicted)
        token_ok += sum(x == y for x, y in zip(row["gold_tags"], row["pred_tags"]))
        token_n += len(row["gold_tags"])
        item = per_source.setdefault(row["source"], {"tp": 0, "fp": 0, "fn": 0,
                                                       "rows": 0, "token_ok": 0, "token_n": 0})
        item["tp"] += len(actual & predicted)
        item["fp"] += len(predicted - actual)
        item["fn"] += len(actual - predicted)
        item["rows"] += 1
        item["token_ok"] += sum(x == y for x, y in zip(row["gold_tags"], row["pred_tags"]))
        item["token_n"] += len(row["gold_tags"])
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    for item in per_source.values():
        p = item["tp"] / max(item["tp"] + item["fp"], 1)
        r = item["tp"] / max(item["tp"] + item["fn"], 1)
        item["span_precision"] = p
        item["span_recall"] = r
        item["span_f1"] = 2 * p * r / max(p + r, 1e-12)
        item["token_accuracy"] = item["token_ok"] / max(item["token_n"], 1)
    return {"rows": len(records), "span_tp": tp, "span_fp": fp, "span_fn": fn,
            "span_precision": precision, "span_recall": recall,
            "span_f1": 2 * precision * recall / max(precision + recall, 1e-12),
            "token_accuracy": token_ok / max(token_n, 1), "per_source": per_source}


def save_checkpoint(output: Path, step: int, backbone, head, tokenizer, metadata: dict,
                    frozen_base: bool, lora_layers=()):
    checkpoint = output / "checkpoints" / f"step-{step:06d}"
    if checkpoint.exists():
        raise RuntimeError(f"refusing to overwrite checkpoint: {checkpoint}")
    checkpoint.mkdir(parents=True)
    if frozen_base:
        metadata["backbone_path"] = metadata["base_model_path"]
        metadata["backbone_sha256"] = metadata["base_weights_sha256"]
    else:
        backbone_dir = checkpoint / "backbone"
        backbone.save_pretrained(backbone_dir, safe_serialization=True,
                                 state_dict=export_state_dict(backbone, lora_layers))
        tokenizer.save_pretrained(backbone_dir)
        weight_files = sorted(backbone_dir.glob("*.safetensors"))
        metadata["backbone_files"] = [{"name": p.name, "sha256": sha256(p), "bytes": p.stat().st_size}
                                      for p in weight_files]
        metadata["backbone_mode"] = "late-layer-lora-merged" if lora_layers else "full-finetune"
        if lora_layers:
            adapter = {f"layer{index}.{name}.{suffix}": tensor.detach().float().cpu().contiguous()
                       for index, name, module in lora_layers
                       for suffix, tensor in (("a", module.a), ("b", module.b))}
            adapter_path = checkpoint / "late-lora.safetensors"
            save_file(adapter, str(adapter_path))
            metadata["lora"] = {
                "rank": int(lora_layers[0][2].a.shape[0]), "alpha": 16,
                "selection": "q_proj and v_proj in last four full-attention blocks",
                "adapter_sha256": sha256(adapter_path),
                "layers": [{"layer": i, "projection": n} for i, n, _ in lora_layers],
            }
    save_file({k: v.detach().float().cpu().contiguous() for k, v in head.state_dict().items()},
              str(checkpoint / "task-head.safetensors"))
    metadata["task_head_sha256"] = sha256(checkpoint / "task-head.safetensors")
    metadata["checkpoint_path"] = str(checkpoint.resolve())
    (checkpoint / "checkpoint.json").write_text(json.dumps(metadata, sort_keys=True,
                                                              indent=2) + "\n", encoding="utf-8")
    return checkpoint


def evaluate(arm: str, rows: list[dict], backbone, head, tokenizer, device: str,
             max_length: int, tag_names: list[str] | None, eval_batch_size: int = 8):
    was_training = backbone.training
    backbone.eval()
    head.eval()
    predictions = []
    ner_records = []
    batch_width = 1 if arm == "gliclass_logic" else eval_batch_size
    batches = [rows[i:i + batch_width] for i in range(0, len(rows), batch_width)]
    with torch.inference_mode():
        for batch_rows in batches:
            if arm == "gliclass_logic":
                encoded = encode_gliclass(batch_rows, tokenizer, max_length)
                batch = collate(encoded, tokenizer.pad_token_id, arm)
                ids = batch["input_ids"].to(device)
                mask = batch["attention_mask"].to(device)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    hidden = backbone(input_ids=ids, attention_mask=mask, use_cache=False,
                                      return_dict=True).last_hidden_state
                    positions = torch.tensor([pos for pos, _ in encoded[0]["positions"]],
                                             device=device, dtype=torch.long)
                    logits = head(hidden[0].index_select(0, positions)).squeeze(-1)
                scores = torch.sigmoid(logits.float()).cpu().tolist()
                targets = [target for _, target in encoded[0]["positions"]]
                predictions.append((scores, targets))
            else:
                encoded = encode_openner(batch_rows, tokenizer, tag_names or [],
                                         metadata_types(tag_names or []), max_length)
                batch = collate(encoded, tokenizer.pad_token_id, arm)
                ids = batch["input_ids"].to(device)
                mask = batch["attention_mask"].to(device)
                with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                    hidden = backbone(input_ids=ids, attention_mask=mask, use_cache=False,
                                      return_dict=True).last_hidden_state
                    logits = head(hidden)
                pred_ids = logits.argmax(dim=-1).cpu().tolist()
                for index, row in enumerate(batch_rows):
                    words_pred = ["O"] * len(row["ner_tags"])
                    for token_i, source_i in enumerate(encoded[index]["source_word_indices"]):
                        if 0 <= source_i < len(words_pred):
                            words_pred[source_i] = (tag_names or ["O"])[pred_ids[index][token_i]]
                    ner_records.append({"gold_tags": row["ner_tags"],
                                        "pred_tags": words_pred, "source": row["source"]})
    backbone.train(was_training)
    head.train()
    return (gliclass_metrics(predictions) if arm == "gliclass_logic" else ner_metrics(ner_records))


def metadata_types(tag_names: list[str]) -> list[str]:
    return sorted({tag[2:] for tag in tag_names if tag.startswith(("B-", "I-"))})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("gliclass_logic", "openner_en"), required=True)
    ap.add_argument("--prepared", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-steps", type=int, default=2000)
    ap.add_argument("--microbatch-size", type=int, default=1)
    ap.add_argument("--gradient-accumulation", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=1024)
    ap.add_argument("--eval-batch-size", type=int, default=8)
    ap.add_argument("--freeze-backbone", action="store_true")
    ap.add_argument("--late-lora", action="store_true")
    ap.add_argument("--lora-rank", type=int, default=8)
    args = ap.parse_args()
    if args.freeze_backbone and args.late_lora:
        raise ValueError("--freeze-backbone and --late-lora are mutually exclusive")
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the LFM specialization run")
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cuda.matmul.allow_tf32 = True
    device = "cuda:0"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"refusing to reuse non-empty arm output: {output}")

    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True, local_files_only=True)
    if not tokenizer.is_fast or tokenizer.pad_token_id is None:
        raise RuntimeError("fast tokenizer with padding token required")
    if args.arm == "gliclass_logic":
        train_rows = list(read_jsonl(args.prepared / "gliclass" / "train.jsonl"))
        dev_rows = list(read_jsonl(args.prepared / "gliclass" / "dev.jsonl"))
        test_rows = list(read_jsonl(args.prepared / "gliclass" / "test.jsonl"))
        task_metadata = {"train_rows": len(train_rows), "dev_rows": len(dev_rows),
                         "test_rows": len(test_rows), "label_schema": "per-row candidate labels"}
        tag_names = None
        seq_len = min(args.max_length, 1024)
    else:
        train_rows = list(read_jsonl(args.prepared / "openner" / "train.jsonl"))
        dev_rows = list(read_jsonl(args.prepared / "openner" / "dev.jsonl"))
        test_rows = list(read_jsonl(args.prepared / "openner" / "test.jsonl"))
        tag_names, types = ner_tag_space(train_rows)
        task_metadata = {"train_rows": len(train_rows), "dev_rows": len(dev_rows),
                         "test_rows": len(test_rows), "tag_names": tag_names, "types": types,
                         "tag_counts_train": dict(Counter(tag for row in train_rows
                                                           for tag in row["ner_tags"]))}
        seq_len = min(args.max_length, 512)

    backbone = AutoModel.from_pretrained(args.model, local_files_only=True,
                                         dtype=torch.float32).to(device)
    if hasattr(backbone, "gradient_checkpointing_enable"):
        backbone.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    backbone.config.use_cache = False
    if args.freeze_backbone:
        for parameter in backbone.parameters():
            parameter.requires_grad_(False)
    lora_layers = attach_lora(backbone, args.lora_rank) if args.late_lora else []
    head_size = 1 if args.arm == "gliclass_logic" else len(tag_names or [])
    head = nn.Linear(backbone.config.hidden_size, head_size).to(device=device, dtype=torch.float32)
    if args.freeze_backbone:
        optimizer = torch.optim.AdamW(head.parameters(), lr=1e-3, weight_decay=0.01,
                                     fused=True)
    elif args.late_lora:
        adapter_parameters = [p for _, _, module in lora_layers for p in (module.a, module.b)]
        optimizer = torch.optim.AdamW([
            {"params": adapter_parameters, "lr": 1e-4},
            {"params": head.parameters(), "lr": 1e-3},
        ], weight_decay=0.01, fused=True)
    else:
        optimizer = torch.optim.AdamW([
            {"params": backbone.parameters(), "lr": 2e-5},
            {"params": head.parameters(), "lr": 1e-3},
        ], weight_decay=0.01, fused=True)
    rng = np.random.default_rng(SEED)
    train_order = np.arange(len(train_rows))
    max_steps = args.max_steps
    if max_steps < 1 or args.microbatch_size < 1 or args.gradient_accumulation < 1:
        raise ValueError("steps, microbatch and accumulation must be positive")
    base_weights = args.model / "model.safetensors"
    base_meta = {
        "schema": "lfm-specialist-checkpoint/v1", "arm": args.arm,
        "step": 0, "seed": SEED, "base_model_path": str(args.model.resolve()),
        "base_weights_sha256": sha256(base_weights),
        "prepared_source_lock_sha256": sha256(args.prepared / "source-lock.json"),
        "frozen_backbone_control": args.freeze_backbone,
        "late_layer_lora": args.late_lora,
        "task": task_metadata, "max_length": seq_len,
        "optimizer": {"name": "AdamW",
                      "backbone_lr": 2e-5 if not (args.freeze_backbone or args.late_lora) else None,
                      "adapter_lr": 1e-4 if args.late_lora else None,
                      "head_lr": 1e-3, "weight_decay": 0.01,
                      "microbatch_size": args.microbatch_size,
                      "gradient_accumulation": args.gradient_accumulation},
    }
    manifest_path = output / "run-manifest.json"
    manifest_path.write_text(json.dumps(base_meta, sort_keys=True, indent=2) + "\n",
                             encoding="utf-8")
    schedule = sorted(set(x for x in SCHEDULE if x <= max_steps) | {max_steps})
    (output / "checkpoints").mkdir()
    (output / "metrics").mkdir()
    started = time.perf_counter()
    if not args.freeze_backbone:
        backbone.train()
    head.train()
    steps_done = 0
    losses = []
    while steps_done < max_steps:
        optimizer.zero_grad(set_to_none=True)
        accumulated = 0
        step_loss = 0.0
        for _ in range(args.gradient_accumulation):
            chosen = rng.choice(train_order, size=min(args.microbatch_size, len(train_order)),
                                replace=False)
            raw_rows = [train_rows[int(i)] for i in chosen]
            if args.arm == "gliclass_logic":
                encoded = encode_gliclass(raw_rows, tokenizer, seq_len)
            else:
                encoded = encode_openner(raw_rows, tokenizer, tag_names or [], types, seq_len)
            batch = collate(encoded, tokenizer.pad_token_id, args.arm)
            ids = batch["input_ids"].to(device)
            mask = batch["attention_mask"].to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                outputs = backbone(input_ids=ids, attention_mask=mask, use_cache=False,
                                   return_dict=True)
                hidden = outputs.last_hidden_state
                if args.arm == "gliclass_logic":
                    per_row = []
                    for i, item in enumerate(encoded):
                        positions = torch.tensor([p for p, _ in item["positions"]],
                                                 device=device, dtype=torch.long)
                        targets = torch.tensor([y for _, y in item["positions"]],
                                                device=device, dtype=torch.float32)
                        if positions.numel():
                            logits = head(hidden[i].index_select(0, positions)).squeeze(-1)
                            per_row.append(F.binary_cross_entropy_with_logits(
                                logits.float(), targets, reduction="mean"))
                    if not per_row:
                        continue
                    loss = torch.stack(per_row).mean()
                else:
                    logits = head(hidden)
                    loss = F.cross_entropy(logits.float().reshape(-1, head_size),
                                           batch["labels"].to(device).reshape(-1),
                                           ignore_index=-100)
            (loss / args.gradient_accumulation).backward()
            step_loss += float(loss.detach())
            accumulated += 1
            if args.arm == "gliclass_logic":
                del encoded
        if accumulated == 0:
            raise RuntimeError("optimizer step received no labeled items")
        torch.nn.utils.clip_grad_norm_([p for p in list(backbone.parameters()) + list(head.parameters())
                                        if p.requires_grad], 1.0)
        optimizer.step()
        steps_done += 1
        losses.append(step_loss / accumulated)
        if steps_done == 1 or steps_done % 25 == 0:
            print(json.dumps({"phase": "train", "arm": args.arm, "step": steps_done,
                              "loss": losses[-1], "elapsed_seconds": time.perf_counter() - started,
                              "cuda_peak_bytes": torch.cuda.max_memory_allocated()}), flush=True)
        if steps_done in schedule:
            metrics = {
                "step": steps_done,
                "dev": evaluate(args.arm, dev_rows, backbone, head, tokenizer, device,
                                seq_len, tag_names, args.eval_batch_size),
                "test": evaluate(args.arm, test_rows, backbone, head, tokenizer, device,
                                 seq_len, tag_names, args.eval_batch_size),
            }
            (output / "metrics" / f"step-{steps_done:06d}.json").write_text(
                json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            checkpoint_meta = {**base_meta, "step": steps_done,
                               "train_loss_recent_mean": float(np.mean(losses[-min(100, len(losses)):]))}
            checkpoint = save_checkpoint(output, steps_done, backbone, head, tokenizer,
                                          checkpoint_meta, args.freeze_backbone, lora_layers)
            print(json.dumps({"phase": "checkpoint", "arm": args.arm, "step": steps_done,
                              "path": str(checkpoint), "task_metrics": metrics},
                             sort_keys=True), flush=True)
    final_receipt = {"arm": args.arm, "steps": steps_done, "wall_seconds": time.perf_counter() - started,
                     "loss_first_100_mean": float(np.mean(losses[:min(100, len(losses))])),
                     "loss_last_100_mean": float(np.mean(losses[-min(100, len(losses)):]))}
    (output / "completion.json").write_text(json.dumps(final_receipt, sort_keys=True,
                                                        indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"phase": "complete", **final_receipt}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
