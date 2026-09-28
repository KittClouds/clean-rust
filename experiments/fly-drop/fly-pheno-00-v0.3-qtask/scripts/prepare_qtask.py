"""Prepare the sealed, qualification-only task-difficulty ladder."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PREP = ROOT.parent / "fly-pheno-00" / "qualification" / "prepare_contract.py"
ANATOMY = ROOT / "inputs" / "anatomy"
GRAPHS = ROOT / "inputs" / "null-graphs"
BANKS = ROOT / "inputs" / "banks"
MANIFESTS = ROOT / "manifests"
SIDES = ("L", "R")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
BLOCK_SEEDS = tuple(range(32000, 32012))
GRAPH_SEEDS = tuple(range(33000, 33008))
RESPONSE_SEED = 36000
PRETRAIN_TRIALS = 8192
HORIZONS = (512, 1024, 2048, 4096, 8192)
RUNG_CUES = {"T1": 16, "T2": 12, "T3": 8, "T4": 4}
COMPETENCE_THRESHOLD = 0.25
MARGIN_THRESHOLD = 0.20
SUPPORT_REQUIREMENT = 0.80
N_EVAL = 256
DELAY_STEPS = 12


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_lineage() -> Any:
    spec = importlib.util.spec_from_file_location("pheno_prepare_lineage_qtask", SOURCE_PREP)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load preparation lineage")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.ROOT, module.ANATOMY, module.GRAPHS = ROOT, ANATOMY, GRAPHS
    module.MANIFESTS, module.SIDES = MANIFESTS, SIDES
    module.SUBSTRATES, module.GRAPH_SEEDS = SUBSTRATES, GRAPH_SEEDS
    module.ACCEPTED_SWAPS_PER_EDGE = 4
    return module


def make_schedule(lineage: Any, seed: int, cues: int) -> tuple[list[bool], list[list[int]]]:
    rng = lineage.SplitMix64(seed)
    labels = [index % 2 == 0 for index in range(cues)]
    order = list(range(cues))
    rng.shuffle(order)
    labels = [labels[index] for index in order]
    schedule: list[list[int]] = []
    for _ in range(PRETRAIN_TRIALS):
        row = [rng.index(cues)]
        row.extend(cues + rng.index(32) for _ in range(DELAY_STEPS))
        schedule.append(row)
    return labels, schedule


def make_response_draws(lineage: Any, seed: int) -> list[list[int]]:
    rng = lineage.SplitMix64(seed)
    return [[rng.next() for _ in range(max(RUNG_CUES.values()))] for _ in range(N_EVAL)]


def prepare_bank(lineage: Any) -> dict[str, Any]:
    blocks: dict[str, Any] = {}
    for rung_index, (rung, cues) in enumerate(RUNG_CUES.items(), start=1):
        rung_blocks: dict[str, Any] = {}
        for block in BLOCK_SEEDS:
            seed = block + rung_index * 100000
            labels, schedule = make_schedule(lineage, seed ^ 0x545241494E, cues)
            rung_blocks[str(block)] = {"task_seed": seed, "labels": labels, "schedule": schedule, "cue_count": cues}
        blocks[rung] = rung_blocks
    training = {
        "schema": "FLY-PHENO-00-v0.3-QTASK-training-bank-v1",
        "qualification_only": True,
        "difficulty_axis": "cue_count",
        "difficulty_order": ["T1", "T2", "T3", "T4"],
        "rung_cues": RUNG_CUES,
        "pretraining_trials": PRETRAIN_TRIALS,
        "delay_steps": DELAY_STEPS,
        "blocks": blocks,
    }
    write_json(BANKS / "training.json", training)
    competence = {
        "schema": "FLY-PHENO-00-v0.3-QTASK-competence-bank-v1",
        "bank": "competence", "seed_namespace": "qtask-competence-response", "seed": RESPONSE_SEED,
        "n_eval": N_EVAL, "draw_shape": [N_EVAL, max(RUNG_CUES.values())], "training_never_reads": True,
        "response_draws_u64": make_response_draws(lineage, RESPONSE_SEED),
    }
    write_json(BANKS / "competence.json", competence)
    return {"training": {"path": "inputs/banks/training.json", "sha256": sha(BANKS / "training.json")}, "competence": {"path": "inputs/banks/competence.json", "sha256": sha(BANKS / "competence.json")}, "n_eval": N_EVAL}


def write_manifest(bank_manifest: dict[str, Any]) -> None:
    source = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(ANATOMY.glob("*.tsv"))]
    nulls = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size} for p in sorted(GRAPHS.glob("g*/edges-*.tsv"))]
    banks = [{"path": str((BANKS / n).relative_to(ROOT)).replace("\\", "/"), "sha256": sha(BANKS / n), "bytes": (BANKS / n).stat().st_size} for n in ("training.json", "competence.json")]
    write_json(MANIFESTS / "QTASK-MANIFEST.json", {
        "schema": "FLY-PHENO-00-v0.3-QTASK-manifest-v1", "study_id": "FLY-PHENO-00-v0.3-QTASK",
        "purpose": "qualification-only selection of the hardest common stationary task rung",
        "difficulty_axis": "cue_count", "difficulty_order": list(RUNG_CUES), "rung_cues": RUNG_CUES,
        "substrates": list(SUBSTRATES), "sides": list(SIDES), "learner_task_blocks": list(BLOCK_SEEDS),
        "graph_seeds": list(GRAPH_SEEDS), "response_seed": RESPONSE_SEED, "horizons": list(HORIZONS),
        "pretraining_trials": PRETRAIN_TRIALS, "competence_threshold": COMPETENCE_THRESHOLD,
        "margin_threshold": MARGIN_THRESHOLD, "support_requirement": SUPPORT_REQUIREMENT,
        "null_graph_manifest_sha256": sha(MANIFESTS / "NULL-GRAPH-MANIFEST.json"), "bank_manifest": bank_manifest,
        "source_files": source, "null_files": nulls, "bank_files": banks,
        "no_lesions": True, "no_recovery_comparison": True,
    })


def main() -> None:
    for path in (ANATOMY, GRAPHS, BANKS, MANIFESTS): path.mkdir(parents=True, exist_ok=True)
    lineage = load_lineage()
    side_data = {side: lineage.read_nodes(side) for side in SIDES}
    lineage.prepare_null_graphs(side_data)
    bank_manifest = prepare_bank(lineage)
    write_manifest(bank_manifest)
    print(json.dumps({"study": "FLY-PHENO-00-v0.3-QTASK", "rungs": RUNG_CUES, "blocks": len(BLOCK_SEEDS), "graphs": len(GRAPH_SEEDS)}, sort_keys=True))


if __name__ == "__main__": main()
