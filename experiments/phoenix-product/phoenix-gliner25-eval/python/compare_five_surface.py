"""Enforce Python-to-Rust parity for the five GLiNER2.5 feature surfaces."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def feature_map(receipt: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["feature"]: row for row in receipt["features"]}


def python_mentions(row: dict[str, Any]) -> list[dict[str, Any]]:
    entities = row["value"]["result"]["entities"]
    return sorted(
        ({"field": field, **mention} for field, values in entities.items() for mention in values),
        key=lambda value: (value["start"], value["end"], value["field"]),
    )


def rust_mentions(row: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(row["value"], key=lambda value: (
        value["char_start"], value["char_end"], value["field"]
    ))


def mention_parity(python: list[dict[str, Any]], rust: list[dict[str, Any]]) -> tuple[bool, float]:
    if len(python) != len(rust):
        return False, float("inf")
    exact = True
    maximum = 0.0
    for expected, observed in zip(python, rust):
        exact &= (
            expected["field"] == observed["field"]
            and expected["text"] == observed["text"]
            and expected["start"] == observed["char_start"]
            and expected["end"] == observed["char_end"]
        )
        maximum = max(maximum, abs(expected["confidence"] - observed["score"]))
    return exact, maximum


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path)
    parser.add_argument("--rust", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    python_receipt = json.loads(args.python.read_text(encoding="utf-8"))
    rust_receipt = json.loads(args.rust.read_text(encoding="utf-8"))
    py = feature_map(python_receipt)
    rs = feature_map(rust_receipt)
    required = {
        "long_context", "unlimited_span_candidate", "span_attributes",
        "constrained_classification", "joint_information_extraction",
    }
    names_exact = set(py) == required and set(rs) == required
    statuses_observed = all(py[name]["status"] == rs[name]["status"] == "observed" for name in required)

    feature_gates: dict[str, Any] = {}
    exact, delta = mention_parity(python_mentions(py["long_context"]), rust_mentions(rs["long_context"]))
    feature_gates["long_context"] = {"structure_exact": exact, "max_probability_delta": delta}

    wide_exact = True
    wide_delta = 0.0
    py_attempts = py["unlimited_span_candidate"]["value"]["attempts"]
    rs_attempts = rs["unlimited_span_candidate"]["value"]
    if len(py_attempts) != len(rs_attempts):
        wide_exact = False
        wide_delta = float("inf")
    else:
        for expected, observed in zip(py_attempts, rs_attempts):
            expected_mentions = sorted(
                ({"field": field, **mention} for field, values in expected["result"]["entities"].items() for mention in values),
                key=lambda value: (value["start"], value["end"], value["field"]),
            )
            actual_mentions = sorted(observed["mentions"], key=lambda value: (
                value["char_start"], value["char_end"], value["field"]
            ))
            same, attempt_delta = mention_parity(expected_mentions, actual_mentions)
            wide_exact &= same and expected["text"] == observed["text"]
            wide_delta = max(wide_delta, attempt_delta)
    feature_gates["unlimited_span_candidate"] = {
        "structure_exact": wide_exact, "max_probability_delta": wide_delta,
    }

    py_attr = python_mentions(py["span_attributes"])
    rs_attr = rust_mentions(rs["span_attributes"])
    attr_exact, attr_delta = mention_parity(py_attr, rs_attr)
    attribute_delta = 0.0
    if attr_exact:
        for expected, observed in zip(py_attr, rs_attr):
            expected_value = expected["sentiment"]
            observed_value = observed["sentiment"]
            attr_exact &= expected_value["label"] == observed_value["label"]
            attribute_delta = max(
                attribute_delta,
                abs(expected_value["confidence"] - observed_value["confidence"]),
            )
    feature_gates["span_attributes"] = {
        "structure_exact": attr_exact,
        "max_probability_delta": max(attr_delta, attribute_delta),
    }

    py_cls = py["constrained_classification"]["value"]
    rs_cls = rs["constrained_classification"]["value"]
    cls_exact = py_cls["_meta"]["feasible"] == rs_cls["meta"]["feasible"]
    cls_exact &= py_cls["_meta"]["exact"] == rs_cls["meta"]["exact"]
    cls_delta = 0.0
    for task, expected in ((name, value) for name, value in py_cls.items() if name != "_meta"):
        observed = rs_cls["tasks"].get(task)
        cls_exact &= observed is not None and expected["value"] == observed["value"]
        if observed is None:
            cls_delta = float("inf")
            continue
        for label, probability in expected["probabilities"].items():
            cls_delta = max(cls_delta, abs(probability - observed["probabilities"][label]))
    objective_delta = abs(py_cls["_meta"]["objective"] - rs_cls["meta"]["objective"])
    feature_gates["constrained_classification"] = {
        "structure_exact": cls_exact,
        "max_probability_delta": cls_delta,
        "objective_delta": objective_delta,
    }

    py_joint = py["joint_information_extraction"]["value"]["result"]
    rs_joint = rs["joint_information_extraction"]["value"]
    joint_exact = len(py_joint["entities"]) == len(rs_joint["entities"])
    joint_exact &= len(py_joint["relations"]) == len(rs_joint["relations"])
    joint_delta = 0.0
    for expected, observed in zip(py_joint["entities"], rs_joint["entities"]):
        joint_exact &= all(expected[key] == observed[key] for key in ("id", "type", "text", "start", "end"))
        joint_delta = max(joint_delta, abs(expected["confidence"] - observed["confidence"]))
    for expected, observed in zip(py_joint["relations"], rs_joint["relations"]):
        joint_exact &= all(expected[key] == observed[key] for key in ("type", "head", "tail"))
        joint_delta = max(joint_delta, abs(expected["confidence"] - observed["confidence"]))
    feature_gates["joint_information_extraction"] = {
        "structure_exact": joint_exact,
        "max_probability_delta": joint_delta,
    }

    max_probability_delta = max(row["max_probability_delta"] for row in feature_gates.values())
    all_structures_exact = all(row["structure_exact"] for row in feature_gates.values())
    no_publications = python_receipt.get("graph_publications") == rust_receipt.get("graph_publications") == 0
    passed = (
        names_exact and statuses_observed and all_structures_exact and no_publications
        and max_probability_delta <= 1e-5 and objective_delta <= 1e-4
    )
    receipt = {
        "contract": "phoenix-gliner25-five-surface-parity-v1",
        "passed": passed,
        "thresholds": {"max_probability_delta": 1e-5, "max_objective_delta": 1e-4},
        "summary": {
            "feature_names_exact": names_exact,
            "statuses_observed": statuses_observed,
            "all_structures_exact": all_structures_exact,
            "max_probability_delta": max_probability_delta,
            "classification_objective_delta": objective_delta,
            "graph_publications": 0 if no_publications else "mismatch",
        },
        "features": feature_gates,
        "lineage": {
            "python_receipt_sha256": digest(args.python),
            "rust_receipt_sha256": digest(args.rust),
            "onnx_manifest_sha256": digest(args.manifest),
        },
    }
    args.output.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    print(json.dumps(receipt, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
