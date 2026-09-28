"""Emit model-facing Python traces for Rust decoder parity debugging."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from gliner2.classification import ClassificationSchema, Classifier
from gliner2.classification import constraints
from gliner2.classification.compiler import compile_schema
from gliner2.joint_ie import JointIE
from gliner2.joint_ie.compiler import compile_schema as compile_joint_schema


def record(batch, index: int = 0) -> dict:
    return {
        "input_ids": batch.input_ids[index].detach().cpu().tolist(),
        "attention_mask": batch.attention_mask[index].detach().cpu().tolist(),
        "schema_tokens": batch.schema_tokens_list[index],
        "schema_special_indices": batch.schema_special_indices[index],
        "task_types": batch.task_types[index],
        "text_tokens": batch.text_tokens[index],
        "start_mappings": batch.start_mappings[index],
        "end_mappings": batch.end_mappings[index],
    }


@torch.inference_mode()
def classification_trace(model_path: str) -> dict:
    text = "Delete the temporary archive"
    classifier = Classifier.from_pretrained(model_path, local_files_only=True)
    schema = (
        ClassificationSchema()
        .single("intent", ["read", "write", "delete"])
        .multi("effects", ["read_only", "create", "modify", "delete"], min_labels=1)
        .constrain(
            constraints.implies(("intent", "delete"), ("effects", "delete")),
            constraints.excludes(("intent", "read"), ("effects", "delete")),
        )
    )
    compiled = compile_schema(schema)
    batch = classifier.scorer.processor.collate_fn_inference([(text, compiled.build())])
    encoded = classifier.scorer.model.encoder(
        input_ids=batch.input_ids, attention_mask=batch.attention_mask
    ).last_hidden_state
    _, schema_embs = classifier.scorer.processor.extract_embeddings_from_batch(
        encoded, batch.input_ids, batch
    )
    logits = []
    for task_type, tokens, embeddings in zip(
        batch.task_types[0], batch.schema_tokens_list[0], schema_embs[0]
    ):
        if task_type != "classifications":
            continue
        values = classifier.scorer.model.classifier(
            torch.stack([torch.as_tensor(value) for value in embeddings[1:]])
        ).squeeze(-1)
        logits.append({
            "task": tokens[2],
            "labels": [tokens[index + 1] for index, token in enumerate(tokens[:-1]) if token == "[L]"],
            "logits": values.detach().float().cpu().tolist(),
        })
    return {"record": record(batch), "logits": logits}


@torch.inference_mode()
def joint_trace(model_path: str) -> dict:
    text = "Alice works for Acme in Paris. Bob joined Acme last year."
    joint = JointIE.from_pretrained(model_path, local_files_only=True)
    schema = (
        joint.create_schema()
        .entities(["person", "organization", "location"])
        .relation("works_for", "person", "organization", unique_head=True)
        .relation("located_in", "organization", "location")
        .no_self_loops()
    )
    compiled = compile_joint_schema(schema)
    batch = joint.scorer.processor.collate_fn_inference(
        [(text, compiled.build())], architecture="boundary"
    )
    core_batch = batch.to(joint.scorer.device)
    core = joint.scorer.model._encode_core(core_batch)
    spans = torch.tensor(
        [(0, 1), (3, 4), (5, 6), (7, 8), (9, 10)],
        dtype=torch.long,
        device=joint.scorer.device,
    )
    entity_query_ids = torch.tensor([0, 1, 2], dtype=torch.long, device=joint.scorer.device)
    entity_states = core["query_states"].index_select(1, entity_query_ids)
    entity_mask = core["query_mask"].index_select(1, entity_query_ids)
    dynamic_indices = spans.view(1, 1, len(spans), 2).expand(1, 3, len(spans), 2)
    dynamic_logits = joint.scorer.model.boundary_head.score_explicit_spans(
        core["text_states"], core["text_mask"], entity_states, entity_mask, dynamic_indices
    )[0]
    padded_states = torch.zeros(1, 64, entity_states.shape[-1], device=joint.scorer.device)
    padded_states[:, :3] = entity_states
    padded_mask = torch.zeros(1, 64, dtype=torch.bool, device=joint.scorer.device)
    padded_mask[:, :3] = True
    padded_indices = torch.zeros(1, 64, 128, 2, dtype=torch.long, device=joint.scorer.device)
    padded_indices[..., 1] = 1
    padded_indices[:, :, : len(spans)] = spans.view(1, 1, len(spans), 2)
    padded_logits = joint.scorer.model.boundary_head.score_explicit_spans(
        core["text_states"], core["text_mask"], padded_states, padded_mask, padded_indices
    )[0, :3, : len(spans)]
    scores = joint.scorer.score(text, compiled)
    mentions = [vars(value) for value in scores.mentions]
    edges = [vars(value) for value in scores.edges]
    return {
        "record": record(batch),
        "explicit_dynamic": dynamic_logits.detach().float().cpu().tolist(),
        "explicit_padded": padded_logits.detach().float().cpu().tolist(),
        "mentions": mentions,
        "edges": edges,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    payload = {
        "classification": classification_trace(args.model),
        "joint": joint_trace(args.model),
    }
    args.output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps(payload, indent=2, default=str))


if __name__ == "__main__":
    main()
