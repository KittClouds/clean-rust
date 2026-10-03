"""Prepare the fresh REACH-03 qualification namespace only.

This creates task schedules and coordinate samples for qualification blocks. It
does not create a measured namespace, run identity, estimator fit, or result.
The source anatomy/null graphs are read from the protected REACH-02 lineage;
their hashes are recorded and no source artifact is copied or modified.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


STUDY = Path(__file__).resolve().parents[1]
REPO = STUDY.parents[1]
LINEAGE = REPO / "experiments" / "fly-reach-02-v0.1b"
ANATOMY = LINEAGE / "inputs" / "anatomy"
NULLS = LINEAGE / "inputs" / "null-graphs"
OUT = STUDY / "inputs" / "qualification"
MANIFESTS = STUDY / "manifests"
SIDES = ("L", "R")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
BLOCKS = (303000, 303001, 303002, 303003)
COORDINATE_SEED_BASE = 303100
CUES = 4
PRETRAIN_TRIALS = 8192
DELAY_STEPS = 12
COORDINATES_PER_CELL = 64


class SplitMix64:
    def __init__(self, seed: int):
        self.state = seed & ((1 << 64) - 1)

    def next(self) -> int:
        self.state = (self.state + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = self.state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        return (z ^ (z >> 31)) & ((1 << 64) - 1)

    def index(self, n: int) -> int:
        threshold = (-n) % n
        while True:
            value = self.next()
            if value >= threshold:
                return value % n

    def shuffle(self, values: list[int]) -> None:
        for i in range(len(values) - 1, 0, -1):
            j = self.index(i + 1)
            values[i], values[j] = values[j], values[i]


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def schedule(seed: int) -> tuple[list[bool], list[list[int]]]:
    rng = SplitMix64(seed)
    labels = [i % 2 == 0 for i in range(CUES)]
    order = list(range(CUES))
    rng.shuffle(order)
    labels = [labels[i] for i in order]
    rows: list[list[int]] = []
    for _ in range(PRETRAIN_TRIALS):
        row = [rng.index(CUES)]
        row.extend(CUES + rng.index(32) for _ in range(DELAY_STEPS))
        rows.append(row)
    return labels, rows


def node_kinds(side: str) -> list[tuple[int, int]]:
    counts = [0] * 5
    values: list[tuple[int, int]] = []
    with (ANATOMY / f"nodes-{side}.tsv").open(encoding="utf-8") as stream:
        next(stream)
        for line in stream:
            _body, kind_text, _nt = line.rstrip("\r\n").split("\t")
            kind = int(kind_text)
            values.append((kind, counts[kind]))
            counts[kind] += 1
    return values


def graph_edges(substrate: str, side: str, kinds: list[tuple[int, int]]) -> tuple[list[tuple[int, int, int]], list[Path]]:
    path = ANATOMY / f"edges-{side}.tsv" if substrate == "fly" else NULLS / substrate / f"edges-{side}.tsv"
    edges: list[tuple[int, int, int]] = []
    with path.open(encoding="utf-8") as stream:
        next(stream)
        for line in stream:
            pre_text, post_text, weight_text = line.rstrip("\r\n").split("\t")
            pre, post, weight = int(pre_text), int(post_text), int(weight_text)
            if kinds[pre][0] == 1 and kinds[post][0] == 2:
                edges.append((kinds[pre][1], kinds[post][1], weight))
    edges.sort(key=lambda value: (value[1], value[0]))
    return edges, [ANATOMY / f"nodes-{side}.tsv", path]


def main() -> None:
    if (STUDY / "inputs" / "measured").exists() or (STUDY / "runs" / "measured").exists() or (STUDY / "artifacts" / "measured").exists():
        raise SystemExit("measured namespace already exists; qualification preparation is closed")
    OUT.mkdir(parents=True, exist_ok=True)
    MANIFESTS.mkdir(parents=True, exist_ok=True)

    blocks: dict[str, object] = {}
    for block in BLOCKS:
        labels, rows = schedule(block ^ 0x545241494E)
        blocks[str(block)] = {
            "task_seed": block,
            "labels": labels,
            "schedule": rows,
            "cue_count": CUES,
            "pretraining_trials": PRETRAIN_TRIALS,
            "delay_steps": DELAY_STEPS,
        }
    training = {
        "schema": "FLY-REACH-03-qualification-training-v1",
        "qualification_only": True,
        "seed_namespace": "FLY-REACH-03-qualification-task-v1",
        "blocks": blocks,
    }
    training_path = OUT / "training.json"
    write_json(training_path, training)

    cells: list[dict[str, object]] = []
    cell_index = 0
    for substrate in SUBSTRATES:
        for side in SIDES:
            kinds = node_kinds(side)
            edges, source_paths = graph_edges(substrate, side, kinds)
            order = list(range(len(edges)))
            sampler = SplitMix64(COORDINATE_SEED_BASE + cell_index)
            sampler.shuffle(order)
            selected = sorted(order[: min(COORDINATES_PER_CELL, len(order))])
            cell_key = f"{substrate}:{side}"
            cells.append(
                {
                    "cell_key": cell_key,
                    "substrate": substrate,
                    "side": side,
                    "n_kc_mb_edges": len(edges),
                    "coordinates_per_cell": len(selected),
                    "coordinates": selected,
                    "inclusion_probability": min(1.0, COORDINATES_PER_CELL / len(edges)),
                    "sampling_seed": COORDINATE_SEED_BASE + cell_index,
                    "graph_id": cell_key,
                    "source_artifacts": [
                        {"path": str(path.relative_to(REPO)).replace("\\", "/"), "sha256": sha(path)}
                        for path in source_paths
                    ],
                }
            )
            cell_index += 1

    manifest = {
        "schema": "FLY-REACH-03-qualification-manifest-v1",
        "study_id": "FLY-REACH-03",
        "status": "QUALIFICATION_ONLY_PREPARED",
        "qualification_only": True,
        "measured_namespace_created": False,
        "seed_namespaces": {
            "task_blocks": list(BLOCKS),
            "coordinate_sampling": "FLY-REACH-03-coordinate-sampling-v1",
            "coordinate_seed_base": COORDINATE_SEED_BASE,
        },
        "task": {
            "training_path": str(training_path.relative_to(STUDY)).replace("\\", "/"),
            "training_sha256": sha(training_path),
            "pretraining_trials": PRETRAIN_TRIALS,
            "cues": CUES,
            "delay_steps": DELAY_STEPS,
        },
        "cells": cells,
        "cell_count": len(cells),
        "expected_native_cells": len(BLOCKS) * len(cells),
        "rows_per_native_cell": len(cells[0]["coordinates"]) * PRETRAIN_TRIALS,
        "expected_sampled_rows": len(BLOCKS) * sum(int(cell["coordinates_per_cell"]) for cell in cells) * PRETRAIN_TRIALS,
        "f4_physical_encoding": "deterministic_replay_descriptor_v1",
        "source_boundary": "REACH-02 input artifacts are hash-verified read-only lineage; no result artifacts are read",
        "next_gate": "qualification_collection_only",
    }
    manifest_path = MANIFESTS / "QUALIFICATION-MANIFEST.json"
    write_json(manifest_path, manifest)
    qualification_contract = {
        "schema": "FLY-REACH-03-qualification-contract-v0.1",
        "status": "QUALIFICATION_ONLY",
        "authoritative_math_contract_sha256": "6beb47c4784a7d6e37a91e45688dd86e50b15291a8f0dbf07c56c71aefbe47a7",
        "execution_contract": "EXECUTION-CONTRACT-v0.1.json",
        "execution_authorized": False,
        "measured_execution_authorized": False,
        "namespace": "FLY-REACH-03-qualification-v1",
        "blocks": list(BLOCKS),
        "substrates": list(SUBSTRATES),
        "sides": list(SIDES),
        "pretraining_trials": PRETRAIN_TRIALS,
        "coordinates_per_cell": COORDINATES_PER_CELL,
        "expected_sampled_rows": manifest["expected_sampled_rows"],
        "collection": {
            "native_only": True,
            "telemetry_on_off_fixture_required": True,
            "f4_reconstruction_required_before_estimator": True,
            "classifier_in_native_loop": False,
            "reference_sign_controller": False,
            "f4_physical_encoding": "deterministic_replay_descriptor_v1",
        },
        "estimator_qualification": {
            "row_thinning": "retain primary U* rows where per-stream row_index mod 256 == 0",
            "row_modulus": 256,
            "purpose": "bounded qualification calibration only; measured analysis uses its sealed full-row procedure",
            "feature_levels": ["F0", "F1", "F2", "F3a", "F3b"],
            "F4": "exact reconstruction invariant is audited separately; no learned F4 fit is permitted until an encoder is explicitly frozen",
            "model_family": "numpy_mlp_binary_classifier",
            "candidate_learning_rates": [0.0003, 0.001],
            "candidate_batch_sizes": [2048, 4096],
            "epochs": 200,
        },
        "allowed_outputs": [
            "finite status",
            "row counts",
            "inclusion probabilities",
            "F4 reconstruction receipt",
            "qualification estimator calibration",
            "runtime and memory diagnostics",
        ],
        "forbidden_outputs": [
            "measured cells",
            "measured estimator selection",
            "scientific fly-specific claim",
            "PHENO reseal",
        ],
        "failure": "stop and preserve qualification identity; no measured namespace creation",
    }
    qualification_contract_path = MANIFESTS / "QUALIFICATION-CONTRACT-v0.1.json"
    write_json(qualification_contract_path, qualification_contract)
    receipt = {
        "schema": "FLY-REACH-03-qualification-preparation-receipt-v1",
        "status": "PASS",
        "manifest": str(manifest_path.relative_to(REPO)).replace("\\", "/"),
        "manifest_sha256": sha(manifest_path),
        "qualification_contract": str(qualification_contract_path.relative_to(REPO)).replace("\\", "/"),
        "qualification_contract_sha256": sha(qualification_contract_path),
        "training_sha256": sha(training_path),
        "blocks": len(BLOCKS),
        "cells": len(cells),
        "expected_sampled_rows": manifest["expected_sampled_rows"],
        "measured_namespace_created": False,
        "estimators_fit": False,
        "scientific_execution_started": False,
    }
    write_json(STUDY / "artifacts/preimplementation/QUALIFICATION-PREPARATION-RECEIPT.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
