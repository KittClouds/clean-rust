"""Export and dynamically quantize the pinned Qwen embedding envelope."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import shutil
import time
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch
import torch.nn.functional as functional
from onnxruntime.quantization import QuantType, quantize_dynamic
from transformers import AutoModel, AutoTokenizer

QWEN_REPOSITORY = "Qwen/Qwen3-Embedding-0.6B"
QWEN_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
QWEN_WEIGHTS_SHA256 = (
    "0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd"
)
QUERY_INSTRUCTION = (
    "Instruct: Given a web search query, retrieve relevant passages that answer the query\n"
    "Query: "
)
SCHEMA = "phoenix.qwen-onnx-export/v1"


class EmbeddingEnvelope(torch.nn.Module):
    def __init__(self, model: torch.nn.Module) -> None:
        super().__init__()
        self.model = model

    def forward(
        self, input_ids: torch.Tensor, attention_mask: torch.Tensor
    ) -> torch.Tensor:
        hidden = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            use_cache=False,
            return_dict=True,
        ).last_hidden_state
        final_tokens = attention_mask.sum(dim=1) - 1
        rows = torch.arange(hidden.shape[0], device=hidden.device)
        pooled = hidden[rows, final_tokens]
        return functional.normalize(pooled.float(), p=2, dim=1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--query", default="Which document explains Ryan arriving in New Rome?")
    parser.add_argument("--opset", type=int, default=18)
    parser.add_argument("--int8", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=8 * 1024 * 1024) as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_source(source: Path) -> dict:
    manifest = json.loads((source / "artifact-manifest.json").read_text("utf-8"))
    if (
        manifest["schema"] != "phoenix.g-reasoner.qwen-artifacts.v1"
        or manifest["repository"] != QWEN_REPOSITORY
        or manifest["revision"] != QWEN_REVISION
    ):
        raise RuntimeError("Qwen source provenance does not match compiled pins")
    weights = source / "model.safetensors"
    if sha256(weights) != QWEN_WEIGHTS_SHA256:
        raise RuntimeError("Qwen source weights failed SHA-256 verification")
    return manifest


def load_model(source: Path) -> tuple[AutoTokenizer, EmbeddingEnvelope]:
    tokenizer = AutoTokenizer.from_pretrained(source, local_files_only=True)
    tokenizer.padding_side = "right"
    model = AutoModel.from_pretrained(
        source,
        local_files_only=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    )
    model.config.use_cache = False
    model.eval()
    return tokenizer, EmbeddingEnvelope(model).eval()


def inputs(tokenizer: AutoTokenizer, query: str) -> dict[str, torch.Tensor]:
    encoded = tokenizer(
        [QUERY_INSTRUCTION + query],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )
    return {
        "input_ids": encoded["input_ids"].to(torch.int64),
        "attention_mask": encoded["attention_mask"].to(torch.int64),
    }


def export_fp32(
    model: EmbeddingEnvelope,
    sample: dict[str, torch.Tensor],
    target: Path,
    opset: int,
) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        model,
        (sample["input_ids"], sample["attention_mask"]),
        str(target),
        input_names=["input_ids", "attention_mask"],
        output_names=["embedding"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "sequence"},
            "attention_mask": {0: "batch", 1: "sequence"},
            "embedding": {0: "batch"},
        },
        opset_version=opset,
        dynamo=False,
        external_data=True,
        do_constant_folding=True,
    )
    onnx.checker.check_model(target)


def consolidate_fp32(source: Path, target: Path) -> None:
    """Collapse Torch's per-tensor external files into one durable data file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    model = onnx.load_model(source, load_external_data=True)
    onnx.save_model(
        model,
        target,
        save_as_external_data=True,
        all_tensors_to_one_file=True,
        location="model.onnx.data",
        size_threshold=0,
        convert_attribute=False,
    )
    onnx.checker.check_model(target)


def quantize(fp32: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(
        model_input=fp32,
        model_output=target,
        per_channel=True,
        reduce_range=False,
        weight_type=QuantType.QInt8,
        use_external_data_format=True,
        extra_options={"MatMulConstBOnly": True},
    )
    onnx.checker.check_model(target)


def run_ort(model: Path, sample: dict[str, torch.Tensor]) -> tuple[np.ndarray, list[float]]:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    started = time.perf_counter()
    session = ort.InferenceSession(model, options, providers=["CPUExecutionProvider"])
    load_ms = (time.perf_counter() - started) * 1_000
    feed = {name: value.numpy() for name, value in sample.items()}
    timings = []
    output = None
    for _ in range(4):
        started = time.perf_counter()
        output = session.run(["embedding"], feed)[0]
        timings.append((time.perf_counter() - started) * 1_000)
    assert output is not None
    return output, [load_ms, *timings]


def compare(left: np.ndarray, right: np.ndarray) -> dict[str, float]:
    left_row = left.reshape(-1).astype(np.float64)
    right_row = right.reshape(-1).astype(np.float64)
    return {
        "maxAbs": float(np.max(np.abs(left_row - right_row))),
        "cosine": float(
            np.dot(left_row, right_row)
            / (np.linalg.norm(left_row) * np.linalg.norm(right_row))
        ),
    }


def artifacts(root: Path) -> list[dict]:
    output = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        output.append(
            {
                "file": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )
    return output


def main() -> None:
    args = parse_args()
    verify_source(args.source)
    args.output.mkdir(parents=True, exist_ok=True)
    tokenizer, model = load_model(args.source)
    sample = inputs(tokenizer, args.query)
    with torch.inference_mode():
        torch_reference = model(sample["input_ids"], sample["attention_mask"]).numpy()

    staging_root = args.output / ".staging"
    staging_fp32 = staging_root / "model.onnx"
    fp32 = args.output / "fp32" / "model.onnx"
    int8 = args.output / "int8" / "model.onnx"
    export_started = time.perf_counter()
    export_fp32(model, sample, staging_fp32, args.opset)
    del model
    gc.collect()
    consolidate_fp32(staging_fp32, fp32)
    shutil.rmtree(staging_root)
    export_seconds = time.perf_counter() - export_started
    fp32_output, fp32_timings = run_ort(fp32, sample)

    quantize_seconds = None
    int8_timings = None
    int8_parity = None
    if args.int8:
        quantize_started = time.perf_counter()
        quantize(fp32, int8)
        quantize_seconds = time.perf_counter() - quantize_started
        int8_output, int8_timings = run_ort(int8, sample)
        int8_parity = compare(torch_reference, int8_output)

    receipt = {
        "schema": SCHEMA,
        "repository": QWEN_REPOSITORY,
        "revision": QWEN_REVISION,
        "sourceWeightsSha256": QWEN_WEIGHTS_SHA256,
        "opset": args.opset,
        "query": args.query,
        "tokenCount": int(sample["input_ids"].shape[1]),
        "exportSeconds": export_seconds,
        "quantizeSeconds": quantize_seconds,
        "fp32TimingsMs": fp32_timings,
        "int8TimingsMs": int8_timings,
        "fp32Parity": compare(torch_reference, fp32_output),
        "int8Parity": int8_parity,
        "artifacts": artifacts(args.output),
    }
    receipt_path = args.output / "export-receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", "utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
