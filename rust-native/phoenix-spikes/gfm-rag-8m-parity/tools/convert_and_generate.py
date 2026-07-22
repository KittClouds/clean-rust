#!/usr/bin/env python3
"""One-time trusted PyTorch conversion and deterministic parity fixture generation."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import torch
import torch.nn.functional as F
from safetensors.torch import save_file

CHECKPOINT_REVISION = "4da9e4655d126a783ae2b795ab73b7c7a7c3f4ac"
UPSTREAM_REVISION = "57e3e28045fffff5411e2454a4323fbe4dff9b91"
CHECKPOINT_SHA256 = "578b1af29201beda2ef61af7fadbd7261a4964c3fcd1c68a22b90a62f6ff1247"
NODES = 32
RELATIONS = 8
DOCUMENTS = 11
DIM = 512


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_state(path: Path) -> dict[str, torch.Tensor]:
    if sha256(path) != CHECKPOINT_SHA256:
        raise RuntimeError("checkpoint file SHA-256 does not match the pinned artifact")
    payload = torch.load(path, map_location="cpu", weights_only=True)
    state = payload["model"]
    return {name: tensor.detach().contiguous() for name, tensor in state.items()}


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


def fixture_memberships() -> list[list[int]]:
    memberships: list[list[int]] = []
    for entity in range(NODES):
        docs = {(entity * 5 + 1) % DOCUMENTS}
        if entity % 2 == 0:
            docs.add((entity * 7 + 3) % DOCUMENTS)
        if entity % 5 == 0:
            docs.add((entity + 8) % DOCUMENTS)
        memberships.append(sorted(docs))
    return memberships


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
    generator = torch.Generator().manual_seed(0x50484F454E4958)
    question_raw = torch.randn(768, generator=generator)
    relations_raw = torch.randn(RELATIONS, 768, generator=generator)
    question = linear(question_raw, state, "question_mlp")
    relations = linear(relations_raw, state, "rel_mlp")
    offsets, sources, relation_ids = fixture_graph()
    memberships = fixture_memberships()
    frequency = torch.tensor([len(docs) for docs in memberships], dtype=torch.float32)
    start_mask = torch.zeros(NODES)
    start_mask[torch.tensor([0, 3, 7, 14, 23, 31])] = torch.tensor(
        [1.0, 0.75, 0.6, 0.9, 0.5, 0.8]
    )
    start_weights = start_mask / frequency
    boundary = start_weights[:, None] * question[None, :]
    hidden = boundary
    tensors: dict[str, torch.Tensor] = {
        "question_raw": question_raw,
        "relations_raw": relations_raw,
        "start_mask": start_mask,
        "entity_frequency": frequency,
        "question_projection": question,
        "relation_projection": relations,
        "boundary": boundary,
    }
    for layer in range(6):
        prefix = f"entity_model.layers.{layer}"
        relation_hidden = F.relu(linear(relations, state, f"{prefix}.relation_projection.0"))
        relation_hidden = linear(relation_hidden, state, f"{prefix}.relation_projection.2")
        summed = aggregate(hidden, relation_hidden, boundary, offsets, sources, relation_ids)
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
    scorer_hidden = F.relu(linear(torch.cat([hidden, node_query], dim=-1), state, "entity_model.mlp.0"))
    logits = linear(scorer_hidden, state, "entity_model.mlp.2").squeeze(-1)
    top20 = torch.topk(logits, 20).indices
    document_scores = torch.zeros(DOCUMENTS)
    for entity in top20.tolist():
        for document in memberships[entity]:
            document_scores[document] += 1.0 / len(memberships[entity])
    final_order = torch.tensor(
        sorted(range(DOCUMENTS), key=lambda doc: (-float(document_scores[doc]), doc)),
        dtype=torch.int64,
    )
    tensors.update(
        {
            "six_layer_hidden": hidden,
            "logits": logits,
            "top20": top20.to(torch.int64),
            "document_scores": document_scores,
            "final_order": final_order,
        }
    )
    metadata = {
        "schema": "phoenix.gfm.parity-fixture.v1",
        "checkpoint_revision": CHECKPOINT_REVISION,
        "upstream_revision": UPSTREAM_REVISION,
        "node_count": NODES,
        "relation_count": RELATIONS,
        "document_count": DOCUMENTS,
        "dst_offsets": offsets,
        "src_nodes": sources,
        "relation_ids": relation_ids,
        "entity_documents": memberships,
        "start_entities": [0, 3, 7, 14, 23, 31],
        "layer_norm_epsilon": 1e-5,
        "top_k": 20,
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
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    args.fixture_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(args.checkpoint)
    converted = args.output_dir / "gfm-rag-8m.safetensors"
    if converted.exists():
        raise RuntimeError(f"refusing to reconvert existing checkpoint: {converted}")
    save_file(
        state,
        converted,
        metadata={
            "checkpoint_revision": CHECKPOINT_REVISION,
            "upstream_revision": UPSTREAM_REVISION,
            "source_sha256": CHECKPOINT_SHA256,
        },
    )
    manifest = {
        "schema": "phoenix.gfm.checkpoint-manifest.v1",
        "checkpoint_repository": "rmanluo/GFM-RAG-8M",
        "checkpoint_revision": CHECKPOINT_REVISION,
        "upstream_repository": "RManLuo/gfm-rag",
        "upstream_revision": UPSTREAM_REVISION,
        "source_sha256": CHECKPOINT_SHA256,
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
    print(json.dumps({"converted": str(converted), "manifest": manifest}, indent=2))


if __name__ == "__main__":
    main()
