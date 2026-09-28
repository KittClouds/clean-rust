import argparse
import json
import shutil
from pathlib import Path

import torch
from gliner import GLiNER


CARD_TEXT = "Ryan met Renesco in New Rome."
CARD_LABELS = [
    "Ryan: time-loop courier",
    "Renesco: barman at Jolie Wrangler",
    "New Rome: metropolis in Italy",
]


class LinkerExportWrapper(torch.nn.Module):
    def __init__(self, core, input_names):
        super().__init__()
        self.core = core
        self.input_names = input_names

    def forward(self, *args):
        out = self.core(**dict(zip(self.input_names, args)))
        return out.logits


def build_batch(model, text: str, labels: list[str]):
    tokens, _, _ = model.prepare_inputs([text])
    input_x = model.prepare_base_input(tokens)
    collator = model.data_collator_class(
        model.config,
        data_processor=model.data_processor,
        return_tokens=False,
        return_entities=False,
        return_id_to_classes=False,
        prepare_labels=False,
    )
    batch = collator(input_x, entity_types=labels)
    return {key: value.cpu() if isinstance(value, torch.Tensor) else value for key, value in batch.items()}


def copy_model_assets(src: Path, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    for name in (
        "added_tokens.json",
        "gliner_config.json",
        "merges.txt",
        "special_tokens_map.json",
        "tokenizer.json",
        "tokenizer_config.json",
        "vocab.json",
    ):
        path = src / name
        if path.exists():
            shutil.copy2(path, dst / name)
    labels_tokenizer = src / "labels_tokenizer" / "tokenizer.json"
    if labels_tokenizer.exists():
        out_dir = dst / "labels_tokenizer"
        out_dir.mkdir(exist_ok=True)
        shutil.copy2(labels_tokenizer, out_dir / "tokenizer.json")


def normalize_tokenizer_config(model_root: str):
    root = Path(model_root)
    if not root.exists():
        return
    path = root / "tokenizer_config.json"
    if not path.exists():
        return
    config = json.loads(path.read_text(encoding="utf-8"))
    if config.get("tokenizer_class") != "TokenizersBackend":
        return
    config["tokenizer_class"] = "PreTrainedTokenizerFast"
    if config.get("model_max_length", 0) > 1_000_000:
        config["model_max_length"] = 512
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Export GLiNER-Linker / BiEncoder GLiNER to ONNX.")
    parser.add_argument("--model-root", default="knowledgator/gliner-linker-base-v1.0")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--opset", type=int, default=18)
    parser.add_argument("--text", default=CARD_TEXT)
    parser.add_argument("--labels", default="|".join(CARD_LABELS))
    parser.add_argument("--quantize", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    labels = [value.strip() for value in args.labels.split("|") if value.strip()]
    normalize_tokenizer_config(args.model_root)
    model = GLiNER.from_pretrained(args.model_root, load_tokenizer=True, map_location="cpu")
    model.eval()
    batch = build_batch(model, args.text, labels)

    source_dir = Path(args.model_root)
    if source_dir.exists():
        copy_model_assets(source_dir, out_dir)
    else:
        model.save_pretrained(out_dir)

    input_names = [
        "input_ids",
        "attention_mask",
        "words_mask",
        "text_lengths",
    ]
    if "span_idx" in batch and "span_mask" in batch:
        input_names.extend(["span_idx", "span_mask"])
    input_names.extend(["labels_input_ids", "labels_attention_mask"])

    dynamic_axes = {
        "input_ids": {0: "batch_size", 1: "sequence_length"},
        "attention_mask": {0: "batch_size", 1: "sequence_length"},
        "words_mask": {0: "batch_size", 1: "sequence_length"},
        "text_lengths": {0: "batch_size", 1: "value"},
        "labels_input_ids": {0: "num_labels", 1: "label_length"},
        "labels_attention_mask": {0: "num_labels", 1: "label_length"},
        "logits": {0: "batch_size", 1: "num_words", 2: "num_labels", 3: "bio"},
    }
    if "span_idx" in input_names:
        dynamic_axes["span_idx"] = {0: "batch_size", 1: "num_spans", 2: "idx"}
        dynamic_axes["span_mask"] = {0: "batch_size", 1: "num_spans"}
        dynamic_axes["logits"] = {0: "batch_size", 1: "num_spans", 2: "num_labels"}

    onnx_path = out_dir / "model.onnx"
    torch.onnx.export(
        LinkerExportWrapper(model.model.to("cpu").eval(), input_names),
        tuple(batch[name] for name in input_names),
        f=str(onnx_path),
        input_names=input_names,
        output_names=["logits"],
        dynamic_axes=dynamic_axes,
        opset_version=args.opset,
        dynamo=False,
    )
    print(f"exported {onnx_path}")

    if args.quantize:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        quant_path = out_dir / "model_quantized.onnx"
        quantize_dynamic(str(onnx_path), str(quant_path), weight_type=QuantType.QUInt8)
        print(f"quantized {quant_path}")


if __name__ == "__main__":
    main()
