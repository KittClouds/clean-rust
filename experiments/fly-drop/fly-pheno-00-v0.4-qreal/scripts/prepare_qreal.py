"""Prepare fresh QREAL graph, task, and evaluator inputs."""
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
BLOCK_SEEDS = tuple(range(42000, 42012))
GRAPH_SEEDS = tuple(range(43000, 43008))
RESPONSE_SEED = 46000
LARGE_RESPONSE_SEED = 47000
N_EVAL = 256
N_LARGE_EVAL = 4096
PRETRAIN_TRIALS = 8192
DELAY_STEPS = 12
TASKS = {"four_cue": 4, "two_cue_sanity": 2}

def sha(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""): h.update(b)
    return h.hexdigest()

def write_json(p: pathlib.Path, v: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n", encoding="utf-8")

def load_lineage() -> Any:
    spec = importlib.util.spec_from_file_location("pheno_prepare_lineage_qreal", SOURCE_PREP)
    if spec is None or spec.loader is None: raise RuntimeError("cannot load preparation lineage")
    module = importlib.util.module_from_spec(spec); sys.modules[spec.name] = module; spec.loader.exec_module(module)
    module.ROOT, module.ANATOMY, module.GRAPHS = ROOT, ANATOMY, GRAPHS
    module.MANIFESTS, module.SIDES, module.SUBSTRATES, module.GRAPH_SEEDS = MANIFESTS, SIDES, SUBSTRATES, GRAPH_SEEDS
    return module

def schedule(lineage: Any, seed: int, cues: int) -> tuple[list[bool], list[list[int]]]:
    rng = lineage.SplitMix64(seed); labels = [i % 2 == 0 for i in range(cues)]; order = list(range(cues)); rng.shuffle(order); labels = [labels[i] for i in order]
    rows = []
    for _ in range(PRETRAIN_TRIALS):
        row = [rng.index(cues)]; row.extend(cues + rng.index(32) for _ in range(DELAY_STEPS)); rows.append(row)
    return labels, rows

def draws(lineage: Any, seed: int, n: int) -> list[list[int]]:
    rng = lineage.SplitMix64(seed); return [[rng.next() for _ in range(16)] for _ in range(n)]

def prepare_banks(lineage: Any) -> None:
    blocks: dict[str, dict[str, Any]] = {}
    for task_index, (task, cues) in enumerate(TASKS.items(), start=1):
        blocks[task] = {}
        for block in BLOCK_SEEDS:
            seed = block + task_index * 100000; labels, rows = schedule(lineage, seed ^ 0x545241494E, cues)
            blocks[task][str(block)] = {"task_seed": seed, "labels": labels, "schedule": rows, "cue_count": cues}
    write_json(BANKS / "training.json", {"schema":"FLY-PHENO-00-v0.4-QREAL-training-bank-v1", "qualification_only":True, "tasks":TASKS, "pretraining_trials":PRETRAIN_TRIALS, "delay_steps":DELAY_STEPS, "blocks":blocks})
    for name, seed, n in (("competence.json", RESPONSE_SEED, N_EVAL), ("evaluator-large.json", LARGE_RESPONSE_SEED, N_LARGE_EVAL)):
        write_json(BANKS / name, {"schema":f"FLY-PHENO-00-v0.4-QREAL-{name[:-5]}-bank-v1", "seed_namespace":f"qreal-{name[:-5]}", "seed":seed, "n_eval":n, "draw_shape":[n,16], "training_never_reads":True, "response_draws_u64":draws(lineage, seed, n)})

def write_manifest() -> None:
    files = lambda pats: [{"path":str(p.relative_to(ROOT)).replace("\\", "/"), "sha256":sha(p), "bytes":p.stat().st_size} for pat in pats for p in sorted(ROOT.glob(pat))]
    write_json(MANIFESTS / "QREAL-MANIFEST.json", {"schema":"FLY-PHENO-00-v0.4-QREAL-manifest-v1", "study_id":"FLY-PHENO-00-v0.4-QREAL", "purpose":"representation, weight-space, native-learning, and evaluator-ceiling qualification", "primary_task":"four_cue", "sanity_task":"two_cue_sanity", "substrates":list(SUBSTRATES), "sides":list(SIDES), "learner_task_blocks":list(BLOCK_SEEDS), "graph_seeds":list(GRAPH_SEEDS), "response_seed":RESPONSE_SEED, "large_response_seed":LARGE_RESPONSE_SEED, "pretraining_trials":PRETRAIN_TRIALS, "competence_threshold":0.25, "support_requirement":0.80, "oracle_support_requirement":0.80, "oracle_margin_report_only":0.20, "native_optimizer":"existing Sim adaptive rule", "weight_oracle":"bounded deterministic gradient optimizer over KC->MB weights only", "no_lesions":True, "no_recovery_comparison":True, "source_files":files(["inputs/anatomy/*.tsv"]), "null_files":files(["inputs/null-graphs/g*/edges-*.tsv"]), "bank_files":files(["inputs/banks/*.json"])})

def main() -> None:
    for p in (ANATOMY, GRAPHS, BANKS, MANIFESTS): p.mkdir(parents=True, exist_ok=True)
    lineage = load_lineage(); side_data = {s:lineage.read_nodes(s) for s in SIDES}; lineage.prepare_null_graphs(side_data); prepare_banks(lineage); write_manifest(); print(json.dumps({"study":"FLY-PHENO-00-v0.4-QREAL","tasks":TASKS,"blocks":len(BLOCK_SEEDS),"graphs":len(GRAPH_SEEDS)}, sort_keys=True))

if __name__ == "__main__": main()
