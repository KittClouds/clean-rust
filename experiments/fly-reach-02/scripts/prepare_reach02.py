"""Prepare fresh REACH-02 qualification and measured inputs."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE_PREP = ROOT.parent / "fly-pheno-00" / "qualification" / "prepare_contract.py"
ANATOMY, GRAPHS, BANKS, MANIFESTS = ROOT / "inputs/anatomy", ROOT / "inputs/null-graphs", ROOT / "inputs/banks", ROOT / "manifests"
SIDES = ("L", "R")
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
Q_BLOCKS = tuple(range(72000, 72004))
MEASURED_BLOCKS = tuple(range(82000, 82012))
GRAPH_SEEDS = tuple(range(83000, 83008))
Q_RESPONSE_SEED, Q_LARGE_RESPONSE_SEED = 76000, 77000
MEASURED_RESPONSE_SEED, MEASURED_LARGE_RESPONSE_SEED = 86000, 87000
PRETRAIN_TRIALS, CUES, DELAY_STEPS = 8192, 4, 12


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
    spec = importlib.util.spec_from_file_location("reach02_prepare_lineage", SOURCE_PREP)
    if spec is None or spec.loader is None: raise RuntimeError("cannot load preparation lineage")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    module.ROOT, module.ANATOMY, module.GRAPHS = ROOT, ANATOMY, GRAPHS
    module.MANIFESTS, module.SIDES, module.SUBSTRATES, module.GRAPH_SEEDS = MANIFESTS, SIDES, SUBSTRATES, GRAPH_SEEDS
    return module


def schedule(lineage: Any, seed: int) -> tuple[list[bool], list[list[int]]]:
    rng = lineage.SplitMix64(seed)
    labels = [i % 2 == 0 for i in range(CUES)]
    order = list(range(CUES)); rng.shuffle(order); labels = [labels[i] for i in order]
    rows: list[list[int]] = []
    for _ in range(PRETRAIN_TRIALS):
        row = [rng.index(CUES)]; row.extend(CUES + rng.index(32) for _ in range(DELAY_STEPS)); rows.append(row)
    return labels, rows


def draws(lineage: Any, seed: int, count: int) -> list[list[int]]:
    rng = lineage.SplitMix64(seed); return [[rng.next() for _ in range(16)] for _ in range(count)]


def make_blocks(lineage: Any, blocks: tuple[int, ...], namespace: int) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for block in blocks:
        task_seed = block + namespace
        labels, rows = schedule(lineage, task_seed ^ 0x545241494E)
        result[str(block)] = {"task_seed": task_seed, "labels": labels, "schedule": rows, "cue_count": CUES}
    return result


def manifest_files(patterns: list[str]) -> list[dict[str, Any]]:
    entries = []
    for pattern in patterns:
        for path in sorted(ROOT.glob(pattern)):
            entries.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size})
    return entries


def main() -> None:
    for path in (ANATOMY, GRAPHS, BANKS, MANIFESTS): path.mkdir(parents=True, exist_ok=True)
    lineage = load_lineage(); side_data = {side: lineage.read_nodes(side) for side in SIDES}; lineage.prepare_null_graphs(side_data)
    write_json(BANKS / "qualification-training.json", {"schema": "FLY-REACH-02-qualification-training-v1", "qualification_only": True, "cues": CUES, "pretraining_trials": PRETRAIN_TRIALS, "delay_steps": DELAY_STEPS, "blocks": make_blocks(lineage, Q_BLOCKS, 100000)})
    write_json(BANKS / "measured-training.json", {"schema": "FLY-REACH-02-measured-training-v1", "qualification_only": False, "cues": CUES, "pretraining_trials": PRETRAIN_TRIALS, "delay_steps": DELAY_STEPS, "blocks": make_blocks(lineage, MEASURED_BLOCKS, 100000)})
    for prefix, seed, large_seed in (("qualification", Q_RESPONSE_SEED, Q_LARGE_RESPONSE_SEED), ("measured", MEASURED_RESPONSE_SEED, MEASURED_LARGE_RESPONSE_SEED)):
        for name, draw_seed, count in (("competence", seed, 256), ("large", large_seed, 4096)):
            write_json(BANKS / f"{prefix}-{name}.json", {"schema": f"FLY-REACH-02-{prefix}-{name}-bank-v1", "seed_namespace": f"reach02-{prefix}-{name}", "seed": draw_seed, "n_eval": count, "draw_shape": [count, 16], "training_never_reads": True, "response_draws_u64": draws(lineage, draw_seed, count)})
    write_json(MANIFESTS / "REACH02-MANIFEST.json", {
        "schema": "FLY-REACH-02-manifest-v1", "study_id": "FLY-REACH-02", "purpose": "eligibility sign origin and cancellation",
        "substrates": list(SUBSTRATES), "sides": list(SIDES), "qualification_blocks": list(Q_BLOCKS), "measured_blocks": list(MEASURED_BLOCKS), "graph_seeds": list(GRAPH_SEEDS),
        "primary_task": "four_cue", "pretraining_trials": PRETRAIN_TRIALS, "threshold": 0.25,
        "stable_inversion_rule": {"min_observations": 128, "max_sign_agreement": 0.20, "qualification_only": True, "mask_per_substrate_side": True},
        "qualification_banks": manifest_files(["inputs/banks/qualification-*.json"]), "measured_banks": manifest_files(["inputs/banks/measured-*.json"]),
        "arms": ["native", "sign_ref_native_mag", "stable_inversion_flip", "reference_direction_native_support", "weight_oracle"],
        "diagnostics": ["local_cancellation", "local_sign_agreement", "aggregate_sign_stability", "stage_cosines", "delivery_clip"],
        "no_lesions": True, "no_biological_promotion": True, "no_pheno_reseal": True,
        "source_files": manifest_files(["inputs/anatomy/*.tsv", "source/*"]), "null_files": manifest_files(["inputs/null-graphs/g*/edges-*.tsv"]),
    })
    print(json.dumps({"study": "FLY-REACH-02", "qualification_blocks": len(Q_BLOCKS), "measured_blocks": len(MEASURED_BLOCKS), "graphs": len(GRAPH_SEEDS)}, sort_keys=True))


if __name__ == "__main__": main()
