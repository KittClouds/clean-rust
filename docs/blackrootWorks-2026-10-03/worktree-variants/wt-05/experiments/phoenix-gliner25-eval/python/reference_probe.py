"""CPU reference probes for the five GLiNER2.5 feature claims.

Outputs evidence only. Nothing in this script publishes to Phoenix topology.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import time
from pathlib import Path
from typing import Any, Callable

import gliner2
import torch
from gliner2 import AttributeGroup, AutoExtractor


def timed(name: str, operation: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        value = operation()
        return {
            "feature": name,
            "status": "observed",
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "value": make_jsonable(value),
        }
    except Exception as exc:  # each capability gets an independent receipt
        return {
            "feature": name,
            "status": "error",
            "elapsed_ms": (time.perf_counter() - started) * 1000.0,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def make_jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        try:
            return make_jsonable(value.to_dict())
        except TypeError:
            return make_jsonable(value.to_dict(include_text=True))
    if isinstance(value, dict):
        return {str(key): make_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return make_jsonable(vars(value))
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def validate_spans(text: str, value: Any) -> dict[str, int]:
    valid = 0
    invalid = 0

    def walk(node: Any) -> None:
        nonlocal valid, invalid
        if isinstance(node, dict):
            if {"text", "start", "end"}.issubset(node):
                start, end = node["start"], node["end"]
                if isinstance(start, int) and isinstance(end, int) and text[start:end] == node["text"]:
                    valid += 1
                else:
                    invalid += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, (list, tuple)):
            for child in node:
                walk(child)

    walk(make_jsonable(value))
    return {"valid": valid, "invalid": invalid}


def probe_base(model_path: str) -> tuple[list[dict[str, Any]], AutoExtractor]:
    model = AutoExtractor.from_pretrained(model_path, local_files_only=True)
    rows: list[dict[str, Any]] = []

    filler = " ".join(f"filler{i}" for i in range(900))
    long_text = filler + " OpenAI appointed Sam Altman in San Francisco on Tuesday."

    def long_context() -> Any:
        result = model.extract_entities_long(
            long_text,
            ["person", "organization", "location", "date"],
            chunk_size=384,
            chunk_overlap=64,
            include_spans=True,
            include_confidence=True,
        )
        return {"result": result, "span_check": validate_spans(long_text, result)}

    rows.append(timed("long_context", long_context))

    def long_span() -> Any:
        cases = [
            (
                "The operation was named Recover Every Surviving Archive From The Abandoned "
                "Underground Observatory Beneath New Rome Before Dawn.",
                {"operation_name": "The complete formal name of an operation"},
            ),
            (
                "The treaty titled Agreement for the Coordinated Recovery and Preservation of "
                "All Cultural Archives Lost During the Fall of New Rome was signed today.",
                {"treaty_title": "The complete formal title of a treaty"},
            ),
            (
                "Witnesses remembered The Night When Every Star Above New Rome Turned Crimson "
                "And The Sea Rose Against The City.",
                {"event_name": "The complete formal name of a historical event"},
            ),
        ]
        attempts: list[dict[str, Any]] = []
        lengths: list[int] = []
        invalid = 0
        valid = 0

        def collect(node: Any) -> None:
            if isinstance(node, dict):
                if isinstance(node.get("text"), str):
                    lengths.append(len(node["text"].split()))
                for child in node.values():
                    collect(child)
            elif isinstance(node, list):
                for child in node:
                    collect(child)

        for span_text, schema in cases:
            result = model.extract_entities(
                span_text,
                schema,
                threshold=0.25,
                include_spans=True,
                include_confidence=True,
            )
            payload = make_jsonable(result)
            collect(payload)
            checked = validate_spans(span_text, payload)
            valid += checked["valid"]
            invalid += checked["invalid"]
            attempts.append({"text": span_text, "result": payload, "span_check": checked})
        return {
            "attempts": attempts,
            "max_observed_span_words": max(lengths, default=0),
            "span_check": {"valid": valid, "invalid": invalid},
        }

    rows.append(timed("unlimited_span_candidate", long_span))

    attribute_text = "The new iPhone camera is excellent, but the battery life is disappointing."

    def attributes() -> Any:
        schema = (
            model.create_schema()
            .entities(["product"])
            .entity_attributes(
                {
                    "sentiment": AttributeGroup(
                        ["positive", "negative", "neutral"],
                        applies_to=["product"],
                        qualify_labels=True,
                    )
                }
            )
        )
        result = model.extract(
            attribute_text, schema, include_spans=True, include_confidence=True
        )
        return {"result": result, "span_check": validate_spans(attribute_text, result)}

    rows.append(timed("span_attributes", attributes))
    return rows, model


def probe_constraints(model_path: str) -> dict[str, Any]:
    from gliner2.classification import ClassificationSchema, Classifier
    from gliner2.classification import constraints as constraints

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
    result = classifier.classify("Delete the temporary archive", schema)
    payload = make_jsonable(result)
    del classifier
    gc.collect()
    return payload


def probe_joint_ie(model_path: str) -> dict[str, Any]:
    from gliner2.joint_ie import JointIE, JointIEConfig

    text = "Alice works for Acme in Paris. Bob joined Acme last year."
    joint = JointIE.from_pretrained(model_path, local_files_only=True)
    schema = (
        joint.create_schema()
        .entities(["person", "organization", "location"])
        .relation("works_for", "person", "organization", unique_head=True)
        .relation("located_in", "organization", "location")
        .no_self_loops()
    )
    result = joint.extract(text, schema, config=JointIEConfig(optimizer="beam", beam_size=32))
    payload = make_jsonable(result)
    receipt = {"result": payload, "span_check": validate_spans(text, payload)}
    del joint
    gc.collect()
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    model_config = Path(args.model) / "config.json"
    config_bytes = model_config.read_bytes()
    rows, model = probe_base(args.model)
    del model
    gc.collect()
    rows.append(timed("constrained_classification", lambda: probe_constraints(args.model)))
    rows.append(timed("joint_information_extraction", lambda: probe_joint_ie(args.model)))

    receipt = {
        "contract": "phoenix-gliner25-reference-probe-v1",
        "model": str(Path(args.model).resolve()),
        "model_config_sha256": hashlib.sha256(config_bytes).hexdigest(),
        "gliner2_version": getattr(gliner2, "__version__", "unknown"),
        "torch_version": torch.__version__,
        "python": platform.python_version(),
        "cuda_available": torch.cuda.is_available(),
        "graph_publications": 0,
        "features": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(receipt, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
