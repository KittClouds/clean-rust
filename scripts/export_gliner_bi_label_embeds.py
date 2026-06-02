from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

import torch
from torch import nn
from torch.utils.data import DataLoader

try:
    from onnxruntime.quantization import QuantType, quantize_dynamic
except Exception:  # pragma: no cover - optional local tool dependency
    QuantType = None
    quantize_dynamic = None

from gliner.model import BiEncoderSpanGLiNER


DEFAULT_MODEL = "knowledgator/gliner-bi-base-v2.0"
DEFAULT_OUTPUT_DIR = Path("gliner-bi-base-v2.0-onnx")
ONNX_NAME = "model_label_embeds.onnx"
QUANTIZED_NAME = "model_label_embeds_quantized.onnx"
EMBEDDINGS_NAME = "labels_embeddings.json"


COMMON_LABELS = [
    "Ability",
    "Algorithm",
    "Alliance",
    "Artifact",
    "Attribute",
    "Benchmark",
    "Character",
    "Claim",
    "Concept",
    "Court",
    "Creature",
    "Dataset",
    "Department",
    "Emotion",
    "Enemy",
    "Error",
    "Event",
    "Executive",
    "Faction",
    "Function",
    "Goal",
    "Institution",
    "Initiative",
    "Item",
    "Jurisdiction",
    "Landmark",
    "Library",
    "Location",
    "Member",
    "Method",
    "Metric",
    "Module",
    "NPC",
    "Object",
    "Organization",
    "Other",
    "Paper",
    "Party",
    "Person",
    "Place",
    "Product",
    "Rank",
    "Region",
    "Relationship",
    "Researcher",
    "Risk",
    "Role",
    "Ruling",
    "Spell",
    "Species",
    "State",
    "Statute",
    "Theory",
    "Weapon",
    "Monster",
    "Nonhuman",
    "Denizen",
    "Date",
    "FilePath",
    "CliFlag",
    "LogLevel",
]


class LabelEmbedsWrapper(nn.Module):
    def __init__(self, core: nn.Module):
        super().__init__()
        self.core = core

    def forward(
        self,
        input_ids,
        attention_mask,
        words_mask,
        text_lengths,
        span_idx,
        span_mask,
        labels_embeds,
    ):
        out = self.core(
            input_ids=input_ids,
            attention_mask=attention_mask,
            words_mask=words_mask,
            text_lengths=text_lengths,
            span_idx=span_idx,
            span_mask=span_mask,
            labels_embeds=labels_embeds,
        )
        return out.logits


def build_dummy_batch(model: BiEncoderSpanGLiNER) -> dict[str, torch.Tensor]:
    tokens, _, _ = model.prepare_inputs(["ONNX export dummy input for GLiNER bi-encoder."])
    input_x = model.prepare_base_input(tokens)
    collator = model.data_collator_class(
        model.config,
        data_processor=model.data_processor,
        return_tokens=False,
        return_entities=False,
        return_id_to_classes=False,
        prepare_labels=False,
    )

    def collate_fn(batch):
        return collator(batch, entity_types=COMMON_LABELS)

    loader = DataLoader(input_x, batch_size=1, shuffle=False, collate_fn=collate_fn)
    batch = next(iter(loader))
    return {key: value.to("cpu") if isinstance(value, torch.Tensor) else value for key, value in batch.items()}


def write_embeddings(
    model_dir: Path,
    model: BiEncoderSpanGLiNER,
    labels: list[str],
    batch_size: int,
) -> torch.Tensor:
    try:
        labels_embeds = model.encode_labels(labels, batch_size=batch_size)
    except TypeError:
        labels_embeds = model.encode_labels(labels)
    labels_embeds = labels_embeds.detach().to("cpu").float().contiguous()
    rows = [
        {
            "label": label,
            "embedding": labels_embeds[index].tolist(),
        }
        for index, label in enumerate(labels)
    ]
    payload = {
        "input_name": "labels_embeds",
        "hidden_size": labels_embeds.shape[1],
        "labels": rows,
    }
    (model_dir / EMBEDDINGS_NAME).write_text(
        json.dumps(payload, separators=(",", ":")), encoding="utf-8"
    )
    return labels_embeds


def load_labels(label_files: list[Path], inline_labels: list[str]) -> list[str]:
    labels: list[str] = []

    def push(label: str) -> None:
        clean = label.strip()
        if clean and clean not in labels:
            labels.append(clean)

    for label in COMMON_LABELS:
        push(label)
    for label in inline_labels:
        for part in label.split(","):
            push(part)
    for path in label_files:
        payload = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            raw = json.loads(payload)
            if not isinstance(raw, list):
                raise ValueError(f"{path} must be a JSON list of labels")
            for label in raw:
                push(str(label))
        else:
            for line in payload.splitlines():
                for part in line.split(","):
                    push(part)
    return labels


def copy_label_tokenizer_fallback(model_dir: Path) -> None:
    labels_dir = model_dir / "labels_tokenizer"
    labels_tokenizer = labels_dir / "tokenizer.json"
    text_tokenizer = model_dir / "tokenizer.json"
    if labels_tokenizer.exists() or not text_tokenizer.exists():
        return
    labels_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(text_tokenizer, labels_tokenizer)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a GLiNER-BI ONNX bundle with precomputed label embeddings."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--label", action="append", default=[])
    parser.add_argument("--label-file", type=Path, action="append", default=[])
    parser.add_argument("--label-batch-size", type=int, default=8)
    parser.add_argument("--opset", type=int, default=18)
    parser.add_argument("--no-quantize", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_dir = args.output_dir
    model_dir.mkdir(parents=True, exist_ok=True)
    labels = load_labels(args.label_file, args.label)

    model = BiEncoderSpanGLiNER.from_pretrained(args.model, load_tokenizer=True)
    model.eval()
    model.save_pretrained(str(model_dir))
    copy_label_tokenizer_fallback(model_dir)
    core = model.model.to("cpu").eval()

    batch = build_dummy_batch(model)
    labels_embeds = write_embeddings(model_dir, model, labels, args.label_batch_size)

    input_names = [
        "input_ids",
        "attention_mask",
        "words_mask",
        "text_lengths",
        "span_idx",
        "span_mask",
        "labels_embeds",
    ]
    output_names = ["logits"]
    inputs = tuple(labels_embeds if name == "labels_embeds" else batch[name] for name in input_names)
    dynamic_axes = {
        "input_ids": {0: "batch_size", 1: "sequence_length"},
        "attention_mask": {0: "batch_size", 1: "sequence_length"},
        "words_mask": {0: "batch_size", 1: "sequence_length"},
        "text_lengths": {0: "batch_size", 1: "value"},
        "span_idx": {0: "batch_size", 1: "num_spans", 2: "idx"},
        "span_mask": {0: "batch_size", 1: "num_spans"},
        "labels_embeds": {0: "num_labels", 1: "hidden_size"},
        "logits": {0: "batch_size", 1: "num_words", 2: "max_width", 3: "num_labels"},
    }

    onnx_path = model_dir / ONNX_NAME
    torch.onnx.export(
        LabelEmbedsWrapper(core),
        inputs,
        f=str(onnx_path),
        input_names=input_names,
        output_names=output_names,
        dynamic_axes=dynamic_axes,
        opset_version=args.opset,
        dynamo=False,
    )

    if quantize_dynamic is not None and not args.no_quantize:
        quantize_dynamic(
            model_input=str(onnx_path),
            model_output=str(model_dir / QUANTIZED_NAME),
            weight_type=QuantType.QUInt8,
        )

    metadata = {
        "source_model": args.model,
        "onnx": ONNX_NAME,
        "quantized_onnx": None if args.no_quantize else QUANTIZED_NAME,
        "label_count": len(labels),
        "labels_embeddings": EMBEDDINGS_NAME,
    }
    (model_dir / "phoenix_export.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )

    print(f"wrote {onnx_path}")
    print(f"wrote {model_dir / EMBEDDINGS_NAME}")
    if not args.no_quantize and quantize_dynamic is not None:
        print(f"wrote {model_dir / QUANTIZED_NAME}")


if __name__ == "__main__":
    main()
