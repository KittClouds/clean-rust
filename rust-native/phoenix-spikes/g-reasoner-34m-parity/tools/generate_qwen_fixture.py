#!/usr/bin/env python3
import json
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import AutoModel, AutoTokenizer

MODEL_DIR = Path(r"D:\phoenix-target-g-reasoner-34m\qwen")
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures"
REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"
INSTRUCTION = "Instruct: Given a web search query, retrieve relevant passages that answer the query\nQuery: "
QUERY = "How does relational graph reasoning work?"


def main() -> None:
    tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR, local_files_only=True)
    model = AutoModel.from_pretrained(
        MODEL_DIR,
        local_files_only=True,
        torch_dtype=torch.float32,
        attn_implementation="eager",
    ).eval()
    text = INSTRUCTION + QUERY
    encoded = tokenizer(text, return_tensors="pt", add_special_tokens=True)
    with torch.no_grad():
        hidden = model(**encoded).last_hidden_state
        pooled = hidden[0, encoded["attention_mask"][0].sum().item() - 1].float()
        embedding = torch.nn.functional.normalize(pooled, p=2, dim=0)
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    save_file({"query_embedding": embedding.contiguous()}, FIXTURE_DIR / "qwen-parity.safetensors")
    fixture = {
        "schema": "phoenix.g-reasoner.qwen-parity.v1",
        "revision": REVISION,
        "query": QUERY,
        "formatted_query": text,
        "token_ids": encoded["input_ids"][0].tolist(),
        "dimensions": embedding.numel(),
        "norm": torch.linalg.vector_norm(embedding).item(),
        "torch_dtype": "float32",
        "attention": "eager",
    }
    (FIXTURE_DIR / "qwen-parity.json").write_text(
        json.dumps(fixture, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(fixture, indent=2))


if __name__ == "__main__":
    main()
