"""Train a separate MultiNLI control or bounded late-layer LoRA arm."""
from __future__ import annotations

import argparse
import array
import hashlib
import json
import mmap
import random
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from safetensors.torch import save_file
from transformers import AutoModel, AutoTokenizer


LABELS = {"entailment": 0, "neutral": 1, "contradiction": 2}
SEED = 20260929
SCHEDULE = (250, 500, 1000, 2000)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class JsonlMap:
    """Random-access JSONL backed by mmap and compact u64 line offsets."""

    def __init__(self, path: Path):
        self.file = path.open("rb")
        self.data = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.offsets = array.array("Q", [0])
        position = 0
        while True:
            end = self.data.find(b"\n", position)
            if end < 0:
                break
            self.offsets.append(end + 1)
            position = end + 1
        if position < len(self.data):
            self.offsets.append(len(self.data))

    def __len__(self) -> int:
        return len(self.offsets) - 1

    def __getitem__(self, index: int) -> dict:
        start, stop = self.offsets[index], self.offsets[index + 1]
        return json.loads(self.data[start:stop].strip())

    def close(self) -> None:
        self.data.close()
        self.file.close()


class LoRALinear(nn.Module):
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
        nn.init.kaiming_uniform_(self.a, a=np.sqrt(5))
        self.scale = alpha / rank

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        low_rank = F.linear(F.linear(x, self.a), self.b)
        return self.base(x) + low_rank * self.scale


def attach_lora(backbone, rank: int) -> list[tuple[int, str, LoRALinear]]:
    for parameter in backbone.parameters():
        parameter.requires_grad_(False)
    layer_types = backbone.config.layer_types
    selected = [i for i, kind in enumerate(layer_types) if kind == "full_attention"][-4:]
    adapted = []
    for index in selected:
        attention = backbone.layers[index].self_attn
        for name in ("q_proj", "v_proj"):
            layer = LoRALinear(getattr(attention, name), rank=rank)
            setattr(attention, name, layer)
            adapted.append((index, name, layer))
    if not adapted:
        raise RuntimeError("no attention projections found for late-layer LoRA")
    return adapted


def export_state_dict(backbone, lora_layers):
    """Merge adapters into ordinary LFM state keys for downstream BANK extraction."""
    if not lora_layers:
        return {key: value.detach().to(torch.bfloat16).cpu().contiguous()
                for key, value in backbone.state_dict().items()}
    wrapped = {f"layers.{index}.self_attn.{name}.": layer
               for index, name, layer in lora_layers}
    result = {}
    for key, value in backbone.state_dict().items():
        prefix = next((candidate for candidate in wrapped if key.startswith(candidate)), None)
        if prefix is None:
            result[key] = value.detach().to(torch.bfloat16).cpu().contiguous()
            continue
        suffix = key[len(prefix):]
        layer = wrapped[prefix]
        if suffix == "base.weight":
            merged = layer.base.weight.detach() + (layer.b.detach() @ layer.a.detach()) * layer.scale
            result[prefix + "weight"] = merged.to(torch.bfloat16).cpu().contiguous()
        elif suffix == "base.bias":
            result[prefix + "bias"] = value.detach().to(torch.bfloat16).cpu().contiguous()
        elif suffix in {"a", "b"}:
            continue
        else:
            raise RuntimeError(f"unexpected wrapped projection state key: {key}")
    return result


def prompt(row: dict) -> str:
    return f"Premise: {row['premise']}\nHypothesis: {row['hypothesis']}\nLabel:"


def evaluate(rows: list[dict], tokenizer, backbone, head, device: str,
             max_length: int, batch_size: int) -> dict:
    confusion = np.zeros((3, 3), dtype=np.int64)
    was_training = backbone.training
    backbone.eval()
    head.eval()
    with torch.inference_mode():
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            encoded = tokenizer([prompt(row) for row in batch], padding=True,
                                truncation=True, max_length=max_length,
                                return_tensors="pt")
            ids = encoded["input_ids"].to(device)
            mask = encoded["attention_mask"].to(device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                hidden = backbone(input_ids=ids, attention_mask=mask,
                                  use_cache=False, return_dict=True).last_hidden_state
                last = mask.sum(dim=1).long() - 1
                pooled = hidden[torch.arange(len(batch), device=device), last]
                logits = head(pooled.float())
            predicted = logits.argmax(dim=-1).cpu().numpy()
            actual = np.asarray([row["label_id"] for row in batch], dtype=np.int64)
            np.add.at(confusion, (actual, predicted), 1)
    precision = np.diag(confusion) / np.maximum(confusion.sum(axis=0), 1)
    recall = np.diag(confusion) / np.maximum(confusion.sum(axis=1), 1)
    f1 = 2 * precision * recall / np.maximum(precision + recall, 1e-12)
    backbone.train(was_training)
    head.train()
    return {"rows": len(rows), "accuracy": float(np.trace(confusion) / max(confusion.sum(), 1)),
            "macro_f1": float(f1.mean()), "per_label_f1": f1.tolist(),
            "confusion": confusion.tolist()}


def save_checkpoint(output: Path, step: int, head, lora_layers,
                    metadata: dict, backbone=None, tokenizer=None) -> Path:
    directory = output / "checkpoints" / f"step-{step:06d}"
    if directory.exists():
        raise RuntimeError(f"checkpoint already exists: {directory}")
    directory.mkdir(parents=True)
    save_file({key: value.detach().float().cpu().contiguous()
               for key, value in head.state_dict().items()}, str(directory / "task-head.safetensors"))
    adapter = {}
    for index, name, layer in lora_layers:
        adapter[f"layer{index}.{name}.a"] = layer.a.detach().float().cpu().contiguous()
        adapter[f"layer{index}.{name}.b"] = layer.b.detach().float().cpu().contiguous()
    if adapter:
        save_file(adapter, str(directory / "late-lora.safetensors"))
        if backbone is None or tokenizer is None:
            raise RuntimeError("LoRA checkpoint export requires backbone and tokenizer")
        merged_dir = directory / "backbone"
        backbone.save_pretrained(merged_dir, safe_serialization=True,
                                 state_dict=export_state_dict(backbone, lora_layers))
        tokenizer.save_pretrained(merged_dir)
        metadata["merged_backbone_files"] = [
            {"name": path.name, "sha256": sha256(path), "bytes": path.stat().st_size}
            for path in sorted(merged_dir.glob("*.safetensors"))
        ]
    receipt = {**metadata, "step": step, "task_head_sha256": sha256(directory / "task-head.safetensors"),
               "lora_layers": [{"layer": i, "projection": n} for i, n, _ in lora_layers]}
    if adapter:
        receipt["lora_sha256"] = sha256(directory / "late-lora.safetensors")
    (directory / "checkpoint.json").write_text(json.dumps(receipt, sort_keys=True,
                                                          indent=2) + "\n", encoding="utf-8")
    return directory


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=("frozen-head", "late-lora"), required=True)
    ap.add_argument("--prepared", type=Path, required=True)
    ap.add_argument("--model", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--max-steps", type=int, default=250)
    ap.add_argument("--microbatch-size", type=int, default=1)
    ap.add_argument("--gradient-accumulation", type=int, default=8)
    ap.add_argument("--max-length", type=int, default=512)
    ap.add_argument("--eval-batch-size", type=int, default=16)
    ap.add_argument("--lora-rank", type=int, default=8)
    args = ap.parse_args()
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA is required for the LFM specialization run")
    if args.max_steps < 1 or args.microbatch_size < 1 or args.gradient_accumulation < 1:
        raise ValueError("steps, microbatch, and accumulation must be positive")
    torch.manual_seed(SEED)
    torch.cuda.manual_seed_all(SEED)
    torch.backends.cuda.matmul.allow_tf32 = True
    device = "cuda:0"
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty arm output: {output}")

    train_path = args.prepared / "train.jsonl"
    train = JsonlMap(train_path)
    dev_matched = [json.loads(line) for line in
                   (args.prepared / "validation_matched.jsonl").read_text(encoding="utf-8").splitlines()]
    dev_mismatched = [json.loads(line) for line in
                      (args.prepared / "validation_mismatched.jsonl").read_text(encoding="utf-8").splitlines()]
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True, local_files_only=True)
    if tokenizer.pad_token_id is None:
        raise RuntimeError("tokenizer must provide a pad token")
    backbone = AutoModel.from_pretrained(args.model, local_files_only=True,
                                         dtype=torch.float32).to(device)
    backbone.config.use_cache = False
    lora_layers = []
    if args.mode == "late-lora":
        lora_layers = attach_lora(backbone, args.lora_rank)
        if hasattr(backbone, "gradient_checkpointing_enable"):
            backbone.gradient_checkpointing_enable(
                gradient_checkpointing_kwargs={"use_reentrant": False})
    else:
        for parameter in backbone.parameters():
            parameter.requires_grad_(False)
        backbone.eval()
    head = nn.Linear(backbone.config.hidden_size, 3, dtype=torch.float32, device=device)
    trainable = list(head.parameters()) + [p for _, _, module in lora_layers
                                           for p in (module.a, module.b)]
    parameter_groups = []
    adapter_parameters = [p for _, _, module in lora_layers for p in (module.a, module.b)]
    if adapter_parameters:
        parameter_groups.append({"params": adapter_parameters, "lr": 1e-4})
    parameter_groups.append({"params": head.parameters(), "lr": 1e-3})
    optimizer = torch.optim.AdamW(parameter_groups, weight_decay=0.01, fused=True)
    rng = random.Random(SEED)
    base_weight = args.model / "model.safetensors"
    source_lock = args.prepared / "source-lock.json"
    metadata = {
        "schema": "lexi-nli-specialist-checkpoint/v1", "arm": "NLI",
        "mode": args.mode, "seed": SEED, "base_model_path": str(args.model.resolve()),
        "base_weights_sha256": sha256(base_weight),
        "source_lock_sha256": sha256(source_lock),
        "train_jsonl_sha256": sha256(train_path), "train_rows": len(train),
        "validation_matched_rows": len(dev_matched),
        "validation_mismatched_rows": len(dev_mismatched),
        "optimizer": {"name": "AdamW", "head_lr": 1e-3,
                      "late_lora_lr": 1e-4 if lora_layers else None,
                      "weight_decay": 0.01,
                      "microbatch_size": args.microbatch_size,
                      "gradient_accumulation": args.gradient_accumulation},
        "lora": {"rank": args.lora_rank, "alpha": 16,
                 "selection": "q_proj and v_proj in last four full-attention blocks"},
        "max_length": args.max_length,
    }
    (output / "run-manifest.json").write_text(json.dumps(metadata, sort_keys=True,
                                                         indent=2) + "\n", encoding="utf-8")
    (output / "checkpoints").mkdir()
    (output / "metrics").mkdir()
    schedule = sorted(set(x for x in SCHEDULE if x <= args.max_steps) | {args.max_steps})
    backbone.train(args.mode == "late-lora")
    head.train()
    started = time.perf_counter()
    for step in range(1, args.max_steps + 1):
        optimizer.zero_grad(set_to_none=True)
        loss_sum = 0.0
        for _ in range(args.gradient_accumulation):
            rows = [train[rng.randrange(len(train))] for _ in range(args.microbatch_size)]
            encoded = tokenizer([prompt(row) for row in rows], padding=True, truncation=True,
                                max_length=args.max_length, return_tensors="pt")
            ids = encoded["input_ids"].to(device)
            mask = encoded["attention_mask"].to(device)
            labels = torch.tensor([row["label_id"] for row in rows], device=device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                if args.mode == "frozen-head":
                    with torch.no_grad():
                        hidden = backbone(input_ids=ids, attention_mask=mask,
                                          use_cache=False, return_dict=True).last_hidden_state
                else:
                    hidden = backbone(input_ids=ids, attention_mask=mask,
                                      use_cache=False, return_dict=True).last_hidden_state
                last = mask.sum(dim=1).long() - 1
                pooled = hidden[torch.arange(len(rows), device=device), last].float()
                logits = head(pooled)
                loss = F.cross_entropy(logits, labels)
            (loss / args.gradient_accumulation).backward()
            loss_sum += float(loss.detach())
        torch.nn.utils.clip_grad_norm_(trainable, 1.0)
        optimizer.step()
        if step == 1 or step % 25 == 0:
            print(json.dumps({"phase": "train", "mode": args.mode, "step": step,
                              "loss": loss_sum / args.gradient_accumulation,
                              "elapsed_seconds": time.perf_counter() - started,
                              "cuda_peak_bytes": torch.cuda.max_memory_allocated()}), flush=True)
        if step in schedule:
            metrics = {"step": step,
                       "validation_matched": evaluate(dev_matched, tokenizer, backbone, head,
                                                      device, args.max_length, args.eval_batch_size),
                       "validation_mismatched": evaluate(dev_mismatched, tokenizer, backbone, head,
                                                          device, args.max_length, args.eval_batch_size)}
            path = output / "metrics" / f"step-{step:06d}.json"
            path.write_text(json.dumps(metrics, sort_keys=True, indent=2) + "\n", encoding="utf-8")
            checkpoint = save_checkpoint(output, step, head, lora_layers, metadata,
                                         backbone, tokenizer)
            print(json.dumps({"phase": "checkpoint", "mode": args.mode, "step": step,
                              "path": str(checkpoint), "metrics": metrics}, sort_keys=True), flush=True)
    receipt = {"mode": args.mode, "steps": args.max_steps,
               "wall_seconds": time.perf_counter() - started}
    (output / "completion.json").write_text(json.dumps(receipt, sort_keys=True,
                                                        indent=2) + "\n", encoding="utf-8")
    train.close()
    print(json.dumps({"phase": "complete", **receipt}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
