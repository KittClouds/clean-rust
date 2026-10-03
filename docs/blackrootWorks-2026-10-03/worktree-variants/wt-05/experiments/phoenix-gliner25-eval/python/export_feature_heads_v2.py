"""Export the two GLiNER2.5 neural heads required by the native feature decoder.

The upstream v1 Rust export contains the encoder, routed gather, boundary
candidate head, and classifier. Span attributes additionally require forced
scoring of caller-supplied spans, while joint IE requires the sparse relation
pair scorer. This script appends those heads without rewriting the 1.5 GB v1
export and records their contract in ``boundary_manifest.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
import torch.nn as nn
import onnx
from onnx import TensorProto, helper
from gliner2 import AutoExtractor

OPSET = 18
EXPLICIT_QUERY_CAP = 64
EXPLICIT_SPAN_CAP = 128
EXPLICIT_TIERS = ((8, 32), (16, 64), (EXPLICIT_QUERY_CAP, EXPLICIT_SPAN_CAP))
RELATION_TYPE_CAP = 32
RELATION_PAIR_CAP = 64


class ExplicitSpanScorer(nn.Module):
    def __init__(self, head: nn.Module):
        super().__init__()
        self.head = head

    def forward(
        self,
        text_states: torch.Tensor,
        text_mask: torch.Tensor,
        query_states: torch.Tensor,
        query_mask: torch.Tensor,
        span_indices: torch.Tensor,
    ) -> torch.Tensor:
        return self.head.score_explicit_spans(
            text_states,
            text_mask.bool(),
            query_states,
            query_mask.bool(),
            span_indices,
        )


class SparseRelationScorer(nn.Module):
    """Single-sample tensor-only form of ``SparseRelationScorer.forward``."""

    def __init__(self, scorer: nn.Module, bucket: int):
        super().__init__()
        self.bucket = bucket
        self.hidden_size = scorer.hidden_size
        self.mlp = scorer.mlp
        self.use_biaffine_content = scorer.use_biaffine_content
        if self.use_biaffine_content:
            self.head_content_projection = scorer.head_content_projection
            self.tail_content_projection = scorer.tail_content_projection
            self.relation_content_gate = scorer.relation_content_gate
            self.content_linear = scorer.content_linear

    def forward(
        self,
        text_states: torch.Tensor,      # [1, L, H]
        relation_states: torch.Tensor,  # [1, R, H|2H]
        pair_indices: torch.Tensor,     # [P, 5] = relation,h0,h1,t0,t1
        text_length: torch.Tensor,      # [1], true unpadded word count
    ) -> torch.Tensor:
        relation_index = pair_indices[:, 0]
        head_start = pair_indices[:, 1]
        head_end = pair_indices[:, 2]
        tail_start = pair_indices[:, 3]
        tail_end = pair_indices[:, 4]

        h_start = text_states[0, head_start]
        h_end = text_states[0, head_end - 1]
        t_start = text_states[0, tail_start]
        t_end = text_states[0, tail_end - 1]
        rel = relation_states[0, relation_index]

        delta = (tail_start - head_start).to(text_states.dtype)
        order = torch.sign(delta).unsqueeze(-1)
        distance = (
            delta.abs() / text_length[0].clamp_min(1).to(text_states.dtype)
        ).unsqueeze(-1)
        features = torch.cat(
            [h_start, h_end, t_start, t_end, rel, order, distance], dim=-1
        )
        score = self.mlp(features).squeeze(-1)

        if self.use_biaffine_content:
            prefix = torch.cat(
                (
                    text_states.new_zeros(1, 1, self.hidden_size),
                    text_states.float().cumsum(1).to(text_states.dtype),
                ),
                dim=1,
            )

            def pool(start: torch.Tensor, end: torch.Tensor) -> torch.Tensor:
                span_sum = prefix[0, end] - prefix[0, start]
                width = (end - start).clamp_min(1).unsqueeze(-1).to(span_sum.dtype)
                return span_sum / width

            head_content = self.head_content_projection(pool(head_start, head_end))
            tail_content = self.tail_content_projection(pool(tail_start, tail_end))
            gate = torch.sigmoid(self.relation_content_gate(rel))
            biaffine = (
                head_content * gate * tail_content
            ).sum(-1) / (self.hidden_size**0.5)
            linear = self.content_linear(
                torch.cat((head_content, tail_content, rel), dim=-1)
            ).squeeze(-1)
            score = score + biaffine + linear
        return score


def export_onnx(
    module: nn.Module,
    args: tuple,
    path: Path,
    input_names: list[str],
    output_names: list[str],
    dynamic_axes: dict,
) -> None:
    module.eval()
    with torch.no_grad():
        torch.onnx.export(
            module,
            args,
            str(path),
            input_names=input_names,
            output_names=output_names,
            dynamic_axes=dynamic_axes,
            opset_version=OPSET,
            dynamo=True,
        )
    # PyTorch exports the padding-query safety diagonal as EyeLike.  The
    # pinned CPU ONNX Runtime has no EyeLike kernel, even though the boundary
    # length is static for every bucket.  Materialise the two tiny boolean
    # diagonals so every exported head is loadable on the universal CPU path.
    model = onnx.load(str(path))
    eye_nodes = [node for node in model.graph.node if node.op_type == "EyeLike"]
    if eye_nodes:
        boundary_len = int(args[0].shape[1]) + 1
        values = [row == col for row in range(boundary_len) for col in range(boundary_len)]
        tensor = helper.make_tensor(
            "value",
            TensorProto.BOOL,
            [boundary_len, boundary_len],
            values,
        )
        replacements = {
            node.name: helper.make_node(
                "Constant", [], list(node.output), name=node.name, value=tensor
            )
            for node in eye_nodes
        }
        rewritten = [replacements.get(node.name, node) for node in model.graph.node]
        del model.graph.node[:]
        model.graph.node.extend(rewritten)
        onnx.checker.check_model(model)
        onnx.save(model, str(path))
    print(f"{path.name}: {path.stat().st_size / 1e6:.2f} MB")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--onnx-dir", required=True, type=Path)
    parser.add_argument("--only-missing", action="store_true")
    args = parser.parse_args()

    model = AutoExtractor.from_pretrained(args.model, local_files_only=True)
    model.eval()
    output = args.onnx_dir
    manifest_path = output / "boundary_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    buckets = tuple(int(value) for value in manifest["length_buckets"])
    hidden = int(manifest["hidden_size"])
    relation_dim = (
        2 * hidden
        if model.boundary_settings.directional_relation_states
        else hidden
    )

    for bucket in buckets:
        for queries, spans in EXPLICIT_TIERS:
            explicit_spans = torch.tensor(
                [
                    [index % max(1, bucket - 1), index % max(1, bucket - 1) + 1]
                    for index in range(spans)
                ],
                dtype=torch.long,
            ).view(1, 1, spans, 2).expand(1, queries, spans, 2)
            if (queries, spans) == (EXPLICIT_QUERY_CAP, EXPLICIT_SPAN_CAP):
                explicit_name = f"explicit_span_scorer_L{bucket}_fp32.onnx"
            else:
                explicit_name = (
                    f"explicit_span_scorer_Q{queries}_S{spans}_L{bucket}_fp32.onnx"
                )
            explicit_path = output / explicit_name
            if not args.only_missing or not explicit_path.exists():
                export_onnx(
                    ExplicitSpanScorer(model.boundary_head),
                    (
                        torch.randn(1, bucket, hidden),
                        torch.ones(1, bucket, dtype=torch.long),
                        torch.randn(1, queries, hidden),
                        torch.ones(1, queries, dtype=torch.long),
                        explicit_spans,
                    ),
                    explicit_path,
                    [
                        "text_states",
                        "text_mask",
                        "query_states",
                        "query_mask",
                        "span_indices",
                    ],
                    ["pair_logits"],
                    {},
                )
        relations, pairs = RELATION_TYPE_CAP, RELATION_PAIR_CAP
        relation_pairs = torch.tensor(
            [
                [index % relations, index, index + 1, index + 2, index + 3]
                for index in range(pairs)
            ],
            dtype=torch.long,
        )
        relation_path = output / f"relation_scorer_L{bucket}_fp32.onnx"
        if not args.only_missing or not relation_path.exists():
            export_onnx(
                SparseRelationScorer(model.relation_scorer, bucket),
                (
                    torch.randn(1, bucket, hidden),
                    torch.randn(1, relations, relation_dim),
                    relation_pairs,
                    torch.tensor([bucket], dtype=torch.long),
                ),
                relation_path,
                ["text_states", "relation_states", "pair_indices", "text_length"],
                ["relation_logits"],
                {},
            )

    settings = model.boundary_settings
    manifest.update(
        {
            "feature_heads_version": 2,
            "explicit_span_scorer": True,
            "explicit_query_cap": EXPLICIT_QUERY_CAP,
            "explicit_span_cap": EXPLICIT_SPAN_CAP,
            "explicit_tiers": [list(tier) for tier in EXPLICIT_TIERS],
            "sparse_relation_scorer": True,
            "relation_type_cap": RELATION_TYPE_CAP,
            "relation_score_pair_cap": RELATION_PAIR_CAP,
            "directional_relation_states": bool(settings.directional_relation_states),
            "relation_heads_per_type": int(settings.relation_heads_per_type),
            "relation_tails_per_type": int(settings.relation_tails_per_type),
            "relation_pair_cap": int(settings.relation_pair_cap),
            "relation_argument_proposal_threshold": float(
                settings.relation_argument_proposal_threshold
            ),
            "relation_temperature": float(settings.relation_temperature),
            "pair_temperature": float(settings.pair_temperature),
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("boundary_manifest.json upgraded to feature_heads_version=2")


if __name__ == "__main__":
    main()
