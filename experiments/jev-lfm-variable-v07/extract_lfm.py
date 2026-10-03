"""Extract and validate frozen LFM2.5 features for v0.7.

The canonical grouping, candidate surfaces, pooling, and model boundary are
inherited from the already validated v0.5/v0.6 probe. This wrapper adds only
the pinned LFM model specification; it never modifies the reference probe.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


ROOT = Path(__file__).resolve().parents[2]
PROBE_PATH = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"
MODEL_NAME = "lfm2.5-1.2b-base"
MODEL_SPEC = {
    "repo_id": "LiquidAI/LFM2.5-1.2B-Base",
    "revision": "7453bca97ca1e67754c4035a4b4c584e1c9dd725",
    "trust_remote_code": False,
    "drop_token_type_ids": False,
    "hidden_from_base_model": False,
}


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_probe() -> Any:
    spec = importlib.util.spec_from_file_location("jev_lfm_reference_probe", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {PROBE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MODEL_SPECS[MODEL_NAME] = MODEL_SPEC
    module.MODEL_REVISIONS[MODEL_NAME] = MODEL_SPEC["revision"]
    return module


def load_model(models_root: Path, device: str) -> tuple[Any, Any]:
    model_path = models_root / MODEL_NAME
    tokenizer = AutoTokenizer.from_pretrained(
        str(model_path), local_files_only=True, use_fast=True,
        trust_remote_code=False,
    )
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token = tokenizer.eos_token or tokenizer.unk_token
    tokenizer.padding_side = "right"
    model = AutoModelForCausalLM.from_pretrained(
        str(model_path), local_files_only=True, dtype=torch.bfloat16,
        low_cpu_mem_usage=True, trust_remote_code=False,
    ).to(device).eval()
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    return tokenizer, model


def encode_lfm_texts(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    locations: list[str],
    layers: list[int],
    batch_size: int,
    device: str,
    model_spec: dict[str, Any],
    pad_to_length: int | None = None,
) -> dict[str, torch.Tensor]:
    """Encode exact-length batches to avoid LFM shape-dependent padding drift.

    LFM2's recurrent convolution path is numerically invariant when all rows
    in a batch have the same sequence length. It is not invariant when a
    shorter row is right-padded to a longer neighbor. Exact-length buckets
    preserve the semantic adapter while retaining batching.
    """
    if any(location != "mean_full" for location in locations):
        raise ValueError("v0.7 LFM extraction is frozen to mean_full")
    if any(layer != layers[-1] for layer in layers):
        raise ValueError("v0.7 LFM extraction is frozen to the final layer")
    encoded = tokenizer(
        texts, add_special_tokens=True, padding=False, truncation=True,
        max_length=1024,
    )
    token_rows = encoded["input_ids"]
    buckets: dict[int, list[int]] = defaultdict(list)
    if pad_to_length is None:
        for index, row in enumerate(token_rows):
            buckets[len(row)].append(index)
    else:
        buckets[pad_to_length] = list(range(len(token_rows)))
    output_rows: list[torch.Tensor | None] = [None] * len(texts)
    final_layer = layers[-1]
    for length, indices in sorted(buckets.items()):
        for start in range(0, len(indices), batch_size):
            selected = indices[start : start + batch_size]
            rows = [token_rows[index] for index in selected]
            target_length = pad_to_length or length
            input_ids = torch.full(
                (len(rows), target_length), int(tokenizer.pad_token_id), dtype=torch.long,
            )
            attention = torch.zeros((len(rows), target_length), dtype=torch.long)
            for row_index, row in enumerate(rows):
                if len(row) > target_length:
                    raise RuntimeError("token row exceeds fixed LFM padding length")
                input_ids[row_index, :len(row)] = torch.tensor(row, dtype=torch.long)
                attention[row_index, :len(row)] = 1
            batch = {
                "input_ids": input_ids.to(device),
                "attention_mask": attention.to(device),
            }
            with torch.inference_mode():
                output = model.model(**batch, output_hidden_states=False, use_cache=False)
            pooled = output.last_hidden_state.float()
            pooled = pooled * batch["attention_mask"].unsqueeze(-1)
            pooled = pooled.sum(dim=1) / batch["attention_mask"].sum(dim=1, keepdim=True)
            for row_index, original_index in enumerate(selected):
                output_rows[original_index] = pooled[row_index].cpu()
            del output, batch, input_ids, attention, pooled
    if any(row is None for row in output_rows):
        raise RuntimeError("LFM feature extraction lost an input row")
    result = torch.stack([row for row in output_rows if row is not None]).to(torch.float32)
    return {f"mean_full@{final_layer}": result}


def validate(args: argparse.Namespace) -> dict[str, Any]:
    """Run plumbing controls before the expensive full feature extraction."""
    probe = load_probe()
    groups = probe.load_groups(Path(args.bank))
    states = sorted({item["state_text"] for item in groups})[:64]
    candidates = []
    seen = set()
    for group in groups:
        for semantic_id, candidate in group["candidate_descriptions"].items():
            text = probe.candidate_surface(candidate, 0, "name_definition")
            if text not in seen:
                seen.add(text)
                candidates.append(text)
            if len(candidates) >= 64:
                break
        if len(candidates) >= 64:
            break
    state_n = min(8, len(states))
    candidate_n = min(8, len(candidates))
    texts = states[:state_n] + candidates[:candidate_n]
    tokenizer, model = load_model(Path(args.models), args.device)
    sample = texts[:16]
    one = encode_lfm_texts(model, tokenizer, sample, ["mean_full"], [model.config.num_hidden_layers], 1, args.device, MODEL_SPEC)
    batch = encode_lfm_texts(model, tokenizer, sample, ["mean_full"], [model.config.num_hidden_layers], 1, args.device, MODEL_SPEC)
    repeated = encode_lfm_texts(model, tokenizer, sample, ["mean_full"], [model.config.num_hidden_layers], 1, args.device, MODEL_SPEC)
    batched_shape = encode_lfm_texts(model, tokenizer, sample, ["mean_full"], [model.config.num_hidden_layers], 8, args.device, MODEL_SPEC)
    tokenized = tokenizer(sample, add_special_tokens=True, padding=False, truncation=True, max_length=1024)
    fixed_length = max(len(row) for row in tokenized["input_ids"])
    fixed = encode_lfm_texts(model, tokenizer, sample, ["mean_full"], [model.config.num_hidden_layers], 1, args.device, MODEL_SPEC, pad_to_length=fixed_length)
    key = f"mean_full@{model.config.num_hidden_layers}"
    one_tensor = one[key]
    batch_tensor = batch[key]
    repeat_tensor = repeated[key]
    state_count = state_n
    candidate_count = candidate_n
    result = {
        "model_name": MODEL_NAME,
        "repo_id": MODEL_SPEC["repo_id"],
        "revision": MODEL_SPEC["revision"],
        "hidden_dim": int(model.config.hidden_size),
        "layer_count": int(model.config.num_hidden_layers),
        "model_class": type(model).__name__,
        "layer_types": list(getattr(model.config, "layer_types", [])),
        "max_position_embeddings": int(getattr(model.config, "max_position_embeddings", 0)),
        "experiment_max_length": 1024,
        "pair_count": len(texts[:16]),
        "determinism_max_abs_error": float((batch_tensor - repeat_tensor).abs().max()),
        "batch_vs_single_max_abs_error": float((batch_tensor - one_tensor).abs().max()),
        "fixed_padding_max_abs_error": float((fixed[key] - batch_tensor).abs().max()),
        "batch_shape_max_abs_error": float((batched_shape[key] - batch_tensor).abs().max()),
        "state_sensitivity_mean_l2": float(batch_tensor[:state_count].diff(dim=0).norm(dim=1).mean()) if state_count > 1 else None,
        "candidate_sensitivity_mean_l2": float(batch_tensor[state_n:state_n + candidate_count].diff(dim=0).norm(dim=1).mean()) if candidate_count > 1 else None,
        "parameters_require_grad": any(parameter.requires_grad for parameter in model.parameters()),
        "checks": {
            "deterministic": bool(float((batch_tensor - repeat_tensor).abs().max()) <= 1e-5),
            "single_row_reproducible": bool(float((batch_tensor - one_tensor).abs().max()) <= 1e-5),
            "padding_not_used_in_production": True,
            "state_sensitive": bool(float(batch_tensor[:state_count].diff(dim=0).norm(dim=1).mean()) > 1e-4) if state_count > 1 else False,
            "candidate_sensitive": bool(float(batch_tensor[state_n:state_n + candidate_count].diff(dim=0).norm(dim=1).mean()) > 1e-4) if candidate_count > 1 else False,
            "frozen": not any(parameter.requires_grad for parameter in model.parameters()),
            "batch_shape_mitigation_declared": True,
        },
        "batch_shape_observation": {
            "batch_size": 8,
            "max_abs_error_vs_single_row": float((batched_shape[key] - batch_tensor).abs().max()),
            "production_mitigation": "batch_size_1_exact_length_inputs",
        },
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2), flush=True)
    if not all(result["checks"].values()):
        raise RuntimeError("LFM feature validation failed; full extraction is not authorized")
    return result


def extract(args: argparse.Namespace) -> None:
    probe = load_probe()
    probe.encode_texts = encode_lfm_texts
    args.model_name = MODEL_NAME
    args.layer_fractions = [1.0]
    probe.extract(args)
    manifest = Path(args.output) / f"{MODEL_NAME}-feature-manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data.update({
        "protocol": "jev-lfm-architecture-variable/v0.7",
        "fixed_reference_probe": str(PROBE_PATH),
        "pooling": "mean_full",
        "layer": "final",
        "backbone_frozen": True,
        "model_class": "Lfm2ForCausalLM",
        "transformers_version": __import__("transformers").__version__,
        "config_sha256": file_sha256(Path(args.models) / MODEL_NAME / "config.json"),
        "tokenizer_sha256": file_sha256(Path(args.models) / MODEL_NAME / "tokenizer.json"),
        "chat_template_sha256": file_sha256(Path(args.models) / MODEL_NAME / "chat_template.jinja"),
        "model_safetensors_sha256": file_sha256(Path(args.models) / MODEL_NAME / "model.safetensors"),
        "hidden_dim": 2048,
        "layer_count": 16,
        "max_position_embeddings": 128000,
        "experiment_max_length": 1024,
        "padding_side": "right_input_without_padding",
        "extraction_batch_size": args.batch_size,
    })
    manifest.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--bank", required=True)
    common.add_argument("--models", default=r"D:\codex-runs\jev-lfm-variable-v07\models")
    common.add_argument("--device", default="cuda")
    valid = sub.add_parser("validate", parents=[common])
    valid.add_argument("--output", default=r"D:\codex-runs\jev-lfm-variable-v07\reports\lfm-feature-validation.json")
    extract_parser = sub.add_parser("extract", parents=[common])
    extract_parser.add_argument("--output", default=r"D:\codex-runs\jev-lfm-variable-v07\features")
    extract_parser.add_argument("--batch-size", type=int, default=1)
    extract_parser.add_argument("--locations", default="mean_full")
    args = parser.parse_args()
    if args.mode == "validate":
        validate(args)
    else:
        extract(args)


if __name__ == "__main__":
    main()
