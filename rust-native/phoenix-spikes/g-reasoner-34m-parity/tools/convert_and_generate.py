#!/usr/bin/env python3
"""One-time checkpoint conversion and deterministic graph-core parity fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors.torch import save_file

CHECKPOINT_REVISION = "a3a4ed2c62281e1c3e0551bd42f2072d9204674f"
UPSTREAM_REVISION = "57e3e28045fffff5411e2454a4323fbe4dff9b91"
SOURCE_SHA256 = "2f2a1a2d2f5725133428941b785f3898255666b06041b58420f75e60599d387d"
CONVERTED_SHA256 = "b62cc4a9bd186ea9f7549814d9641e3aebe7c849c510892c3b83aaee3ef8fa73"
NODES = 32
RELATIONS = 8
DIM = 1024
DOCUMENT_NODES = [node for node in range(NODES) if node not in {0, 3, 7, 14, 23, 31}]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(path: Path) -> dict[str, torch.Tensor]:
    if sha256(path) != SOURCE_SHA256:
        raise RuntimeError("checkpoint SHA-256 does not match the pinned artifact")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    return {name: value.detach().contiguous() for name, value in payload["model"].items()}


def linear(value: torch.Tensor, state: dict[str, torch.Tensor], prefix: str) -> torch.Tensor:
    return F.linear(value, state[f"{prefix}.weight"], state[f"{prefix}.bias"])


def fixture_graph() -> tuple[list[int], list[int], list[int]]:
    edges: set[tuple[int, int, int]] = set()
    for dst in range(NODES):
        edges.add(((dst * 7 + 3) % NODES, dst % RELATIONS, dst))
        edges.add(((dst * 11 + 5) % NODES, (dst * 3 + 1) % RELATIONS, dst))
        if dst % 3 == 0:
            edges.add(((dst + 17) % NODES, (dst + 4) % RELATIONS, dst))
    ordered = sorted(edges, key=lambda edge: (edge[2], edge[1], edge[0]))
    offsets = [0] * (NODES + 1)
    for _, _, dst in ordered:
        offsets[dst + 1] += 1
    for index in range(NODES):
        offsets[index + 1] += offsets[index]
    return offsets, [edge[0] for edge in ordered], [edge[1] for edge in ordered]


def aggregate(
    node_state: torch.Tensor,
    relation_state: torch.Tensor,
    boundary: torch.Tensor,
    offsets: list[int],
    sources: list[int],
    relation_ids: list[int],
) -> torch.Tensor:
    output = boundary.clone()
    for dst in range(NODES):
        for edge in range(offsets[dst], offsets[dst + 1]):
            output[dst] += node_state[sources[edge]] * relation_state[relation_ids[edge]]
    return output


def run_reference(state: dict[str, torch.Tensor]) -> tuple[dict[str, torch.Tensor], dict]:
    generator = torch.Generator().manual_seed(0x47524541534F4E)
    question_raw = F.normalize(torch.randn(DIM, generator=generator), dim=0)
    relations_raw = F.normalize(torch.randn(RELATIONS, DIM, generator=generator), dim=-1)
    entities_raw = F.normalize(torch.randn(NODES, DIM, generator=generator), dim=-1)
    question = linear(question_raw, state, "question_mlp")
    relations = linear(relations_raw, state, "rel_mlp")
    entities = linear(entities_raw, state, "ent_mlp")
    start_mask = torch.zeros(NODES)
    start_mask[torch.tensor([0, 3, 7, 14, 23, 31])] = torch.tensor(
        [1.0, 0.75, 0.6, 0.9, 0.5, 0.8]
    )
    start_boundary = start_mask[:, None] * question[None, :]
    early_fused = linear(
        F.relu(linear(torch.cat([start_boundary, entities], dim=-1), state, "early_fuse_mlp.0")),
        state,
        "early_fuse_mlp.2",
    )
    offsets, sources, relation_ids = fixture_graph()
    hidden = early_fused
    tensors: dict[str, torch.Tensor] = {
        "question_raw": question_raw,
        "relations_raw": relations_raw,
        "entities_raw": entities_raw,
        "start_mask": start_mask,
        "question_projection": question,
        "relation_projection": relations,
        "entity_projection": entities,
        "start_boundary": start_boundary,
        "early_fused": early_fused,
    }
    for layer in range(6):
        prefix = f"entity_model.layers.{layer}"
        relation_hidden = F.relu(linear(relations, state, f"{prefix}.relation_projection.0"))
        relation_hidden = linear(relation_hidden, state, f"{prefix}.relation_projection.2")
        summed = aggregate(hidden, relation_hidden, early_fused, offsets, sources, relation_ids)
        updated = linear(torch.cat([hidden, summed], dim=-1), state, f"{prefix}.linear")
        updated = F.layer_norm(
            updated,
            (DIM,),
            state[f"{prefix}.layer_norm.weight"],
            state[f"{prefix}.layer_norm.bias"],
            1e-5,
        )
        hidden = F.relu(updated) + hidden
        if layer == 0:
            tensors["layer0_relation_projection"] = relation_hidden
            tensors["layer0_aggregate"] = summed
            tensors["layer0_hidden"] = hidden
    node_query = question.expand(NODES, -1)
    prediction = F.relu(
        linear(torch.cat([hidden, node_query, entities], dim=-1), state, "predict_mlp.0")
    )
    logits = linear(prediction, state, "predict_mlp.2").squeeze(-1)
    typed_logits = logits[torch.tensor(DOCUMENT_NODES)]
    typed_topk_local = torch.topk(typed_logits, 20).indices
    typed_topk = torch.tensor(DOCUMENT_NODES, dtype=torch.int64)[typed_topk_local]
    typed_order = torch.tensor(
        sorted(DOCUMENT_NODES, key=lambda node: (-float(logits[node]), node)),
        dtype=torch.int64,
    )
    tensors.update(
        {
            "six_layer_hidden": hidden,
            "logits": logits,
            "document_topk": typed_topk,
            "document_order": typed_order,
        }
    )
    metadata = {
        "schema": "phoenix.g-reasoner.parity-fixture.v1",
        "checkpoint_revision": CHECKPOINT_REVISION,
        "upstream_revision": UPSTREAM_REVISION,
        "node_count": NODES,
        "relation_count": RELATIONS,
        "dst_offsets": offsets,
        "src_nodes": sources,
        "relation_ids": relation_ids,
        "document_nodes": DOCUMENT_NODES,
        "start_entities": [0, 3, 7, 14, 23, 31],
        "layer_norm_epsilon": 1e-5,
        "typed_top_k": 20,
    }
    return tensors, metadata


def tensor_manifest(state: dict[str, torch.Tensor]) -> list[dict]:
    result = []
    for name, tensor in sorted(state.items()):
        raw = tensor.numpy().tobytes(order="C")
        result.append(
            {
                "name": name,
                "shape": list(tensor.shape),
                "dtype": str(tensor.dtype).removeprefix("torch."),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.fixture_dir.mkdir(parents=True, exist_ok=True)
    state = load_state(args.checkpoint)
    converted = args.output_dir / "g-reasoner-34m.safetensors"
    if args.fixtures_only:
        if not converted.is_file() or sha256(converted) != CONVERTED_SHA256:
            raise RuntimeError("fixtures-only mode requires the verified converted checkpoint")
    else:
        if converted.exists():
            raise RuntimeError(f"refusing to reconvert existing checkpoint: {converted}")
        save_file(
            state,
            converted,
            metadata={
                "checkpoint_revision": CHECKPOINT_REVISION,
                "upstream_revision": UPSTREAM_REVISION,
                "source_sha256": SOURCE_SHA256,
            },
        )
    manifest = {
        "schema": "phoenix.g-reasoner.checkpoint-manifest.v1",
        "checkpoint_repository": "rmanluo/G-reasoner-34M",
        "checkpoint_revision": CHECKPOINT_REVISION,
        "upstream_repository": "RManLuo/gfm-rag",
        "upstream_revision": UPSTREAM_REVISION,
        "source_sha256": SOURCE_SHA256,
        "safetensors_sha256": sha256(converted),
        "parameter_count": sum(tensor.numel() for tensor in state.values()),
        "tensors": tensor_manifest(state),
    }
    (args.fixture_dir / "checkpoint-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    fixtures, metadata = run_reference(state)
    save_file(fixtures, args.fixture_dir / "core-parity.safetensors")
    (args.fixture_dir / "core-parity.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "converted": str(converted),
                "safetensors_sha256": manifest["safetensors_sha256"],
                "parameter_count": manifest["parameter_count"],
                "tensor_count": len(state),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
