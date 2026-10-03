"""Prepare fresh, engineering-only FLY-REACH-01 inputs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PREP = ROOT.parent / "fly-pheno-00" / "qualification" / "prepare_contract.py"
ANATOMY = ROOT / "inputs/anatomy"
GRAPHS = ROOT / "inputs/null-graphs"
BANKS = ROOT / "inputs/banks"
MANIFESTS = ROOT / "manifests"
SIDES = ("L", "R")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
BLOCKS = tuple(range(62000, 62012))
GRAPH_SEEDS = tuple(range(63000, 63008))
RESPONSE_SEED = 66000
LARGE_RESPONSE_SEED = 67000
PRETRAIN_TRIALS = 8192
CUES = 4
DELAY_STEPS = 12


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_lineage() -> Any:
    spec = importlib.util.spec_from_file_location("reach01_prepare_lineage", SOURCE_PREP)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load DH-08A preparation lineage")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    module.ANATOMY = ANATOMY
    module.GRAPHS = GRAPHS
    module.MANIFESTS = MANIFESTS
    module.SIDES = SIDES
    module.SUBSTRATES = SUBSTRATES
    module.GRAPH_SEEDS = GRAPH_SEEDS
    return module


def schedule(lineage: Any, seed: int) -> tuple[list[bool], list[list[int]]]:
    rng = lineage.SplitMix64(seed)
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


def draws(lineage: Any, seed: int, count: int) -> list[list[int]]:
    rng = lineage.SplitMix64(seed)
    return [[rng.next() for _ in range(16)] for _ in range(count)]


def prepare_banks(lineage: Any) -> None:
    blocks: dict[str, dict[str, Any]] = {}
    for block in BLOCKS:
        task_seed = block + 100000
        labels, rows = schedule(lineage, task_seed ^ 0x545241494E)
        blocks[str(block)] = {
            "task_seed": task_seed,
            "labels": labels,
            "schedule": rows,
            "cue_count": CUES,
        }
    write_json(
        BANKS / "training.json",
        {
            "schema": "FLY-REACH-01-training-bank-v1",
            "qualification_only": True,
            "cues": CUES,
            "pretraining_trials": PRETRAIN_TRIALS,
            "delay_steps": DELAY_STEPS,
            "blocks": blocks,
        },
    )
    for name, seed, count in (
        ("competence.json", RESPONSE_SEED, 256),
        ("evaluator-large.json", LARGE_RESPONSE_SEED, 4096),
    ):
        write_json(
            BANKS / name,
            {
                "schema": f"FLY-REACH-01-{name[:-5]}-bank-v1",
                "seed_namespace": f"reach01-{name[:-5]}",
                "seed": seed,
                "n_eval": count,
                "draw_shape": [count, 16],
                "training_never_reads": True,
                "response_draws_u64": draws(lineage, seed, count),
            },
        )


def manifest_files(patterns: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            entries.append(
                {
                    "path": str(path.relative_to(ROOT)).replace("\\", "/"),
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
            )
    return entries


def write_manifest() -> None:
    write_json(
        MANIFESTS / "REACH01-MANIFEST.json",
        {
            "schema": "FLY-REACH-01-manifest-v1",
            "study_id": "FLY-REACH-01",
            "purpose": "engineering-only anatomy of native adaptive direction failure",
            "substrates": list(SUBSTRATES),
            "sides": list(SIDES),
            "blocks": list(BLOCKS),
            "graph_seeds": list(GRAPH_SEEDS),
            "primary_task": "four_cue",
            "pretraining_trials": PRETRAIN_TRIALS,
            "threshold": 0.25,
            "reference_lr": 0.05,
            "oracle_lr": 0.5,
            "oracle_steps": 128,
            "checkpoints": [0, 512, 1024, 2048, 4096, 8192],
            "arms": [
                "native",
                "sign_ref_native_mag",
                "mag_ref_native_sign",
                "reference_direction_native_support",
                "reference_direction_full_support",
                "weight_oracle",
            ],
            "stage_diagnostics": [
                "eligibility",
                "modulation",
                "aggregation",
                "delivered",
                "cosine",
                "support_fraction",
                "reference_mass_on_native_support",
                "sign_agreement",
                "magnitude_pearson",
            ],
            "no_lesions": True,
            "no_biological_promotion": True,
            "no_pheno_reseal": True,
            "source_files": manifest_files(["inputs/anatomy/*.tsv"]),
            "null_files": manifest_files(["inputs/null-graphs/g*/edges-*.tsv"]),
            "bank_files": manifest_files(["inputs/banks/*.json"]),
        },
    )


def main() -> None:
    for path in (ANATOMY, GRAPHS, BANKS, MANIFESTS):
        path.mkdir(parents=True, exist_ok=True)
    lineage = load_lineage()
    side_data = {side: lineage.read_nodes(side) for side in SIDES}
    lineage.prepare_null_graphs(side_data)
    prepare_banks(lineage)
    write_manifest()
    print(json.dumps({"study": "FLY-REACH-01", "blocks": len(BLOCKS), "graphs": len(GRAPH_SEEDS), "cues": CUES}, sort_keys=True))


if __name__ == "__main__":
    main()
