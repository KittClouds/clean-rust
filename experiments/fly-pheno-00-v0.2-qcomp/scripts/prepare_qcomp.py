"""Prepare the fresh, qualification-only QCOMP namespace.

This script imports only the input construction helpers from the sealed PHENO
preparation lineage. It writes a new task bank, new response bank, and new
directed degree-preserving null graphs under this qualification identity. It
does not read any measured outcome artifact.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import pathlib
import shutil
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
BLOCK_SEEDS = tuple(range(22000, 22012))
GRAPH_SEEDS = tuple(range(23000, 23008))
RESPONSE_SEED = 26000
PRETRAIN_TRIALS = 8192
HORIZONS = (512, 1024, 2048, 4096, 8192)
COMPETENCE_THRESHOLD = 0.25
COMPETENCE_RATE_REQUIREMENT = 0.80
N_EVAL = 256


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def import_lineage() -> Any:
    spec = importlib.util.spec_from_file_location("pheno_prepare_lineage", SOURCE_PREP)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load preparation lineage")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.ROOT = ROOT
    module.ANATOMY = ANATOMY
    module.GRAPHS = GRAPHS
    module.BANKS = BANKS
    module.MANIFESTS = MANIFESTS
    module.SIDES = SIDES
    module.SUBSTRATES = SUBSTRATES
    module.BLOCK_SEEDS = BLOCK_SEEDS
    module.GRAPH_SEEDS = GRAPH_SEEDS
    module.PRETRAIN_TRIALS = PRETRAIN_TRIALS
    module.N_EVAL = N_EVAL
    module.DELAY_STEPS = 12
    module.CUES = 16
    return module


def write_qcomp_manifest(graph_manifest: dict[str, Any], bank_manifest: dict[str, Any]) -> None:
    source_files = []
    for path in sorted(ANATOMY.glob("*.tsv")):
        source_files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    null_files = []
    for path in sorted(GRAPHS.glob("g*/edges-*.tsv")):
        null_files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    bank_files = []
    for name in ("training.json", "competence.json"):
        path = BANKS / name
        bank_files.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256_file(path), "bytes": path.stat().st_size})
    manifest = {
        "schema": "FLY-PHENO-00-v0.2-QCOMP-manifest-v1",
        "study_id": "FLY-PHENO-00-v0.2-QCOMP",
        "purpose": "qualification-only competence frontier; no lesions or recovery comparisons",
        "source_lineage": "DH08A source inputs only; measured RUN1 outcomes are not read",
        "substrates": list(SUBSTRATES), "sides": list(SIDES),
        "learner_task_blocks": list(BLOCK_SEEDS),
        "graph_seeds": list(GRAPH_SEEDS),
        "response_seed": RESPONSE_SEED,
        "horizons": list(HORIZONS),
        "pretraining_trials": PRETRAIN_TRIALS,
        "competence_threshold": COMPETENCE_THRESHOLD,
        "competence_rate_requirement": COMPETENCE_RATE_REQUIREMENT,
        "n_eval": N_EVAL,
        "graph_manifest_sha256": sha256_file(MANIFESTS / "NULL-GRAPH-MANIFEST.json"),
        "bank_manifest": bank_manifest,
        "source_files": source_files,
        "null_files": null_files,
        "bank_files": bank_files,
        "no_measured_execution": True,
        "no_lesion_outcomes": True,
        "no_adaptive_frozen_comparison": True,
    }
    write_json(MANIFESTS / "QCOMP-MANIFEST.json", manifest)


def main() -> None:
    MANIFESTS.mkdir(parents=True, exist_ok=True)
    BANKS.mkdir(parents=True, exist_ok=True)
    GRAPHS.mkdir(parents=True, exist_ok=True)
    lineage = import_lineage()
    side_data = {side: lineage.read_nodes(side) for side in SIDES}
    graph_manifest = lineage.prepare_null_graphs(side_data)
    bank_manifest = lineage.prepare_banks()
    # The lineage writer uses its own schema names; make the fresh namespace explicit.
    training = json.loads((BANKS / "training.json").read_text(encoding="utf-8"))
    training["schema"] = "FLY-PHENO-00-v0.2-QCOMP-training-bank-v1"
    training["qualification_only"] = True
    training["seed_namespace"] = "qcomp-task-block"
    (BANKS / "training.json").write_text(json.dumps(training, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    competence = json.loads((BANKS / "competence.json").read_text(encoding="utf-8"))
    competence["schema"] = "FLY-PHENO-00-v0.2-QCOMP-competence-bank-v1"
    competence["seed"] = RESPONSE_SEED
    competence["seed_namespace"] = "qcomp-competence-response"
    competence["response_draws_u64"] = lineage.make_response_draws(RESPONSE_SEED)
    (BANKS / "competence.json").write_text(json.dumps(competence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    bank_manifest = {"training": {"path": "inputs/banks/training.json", "sha256": sha256_file(BANKS / "training.json")}, "competence": {"path": "inputs/banks/competence.json", "sha256": sha256_file(BANKS / "competence.json")}, "n_eval": N_EVAL}
    write_qcomp_manifest(graph_manifest, bank_manifest)
    print(json.dumps({"study": "FLY-PHENO-00-v0.2-QCOMP", "graphs": len(GRAPH_SEEDS), "blocks": len(BLOCK_SEEDS), "horizons": list(HORIZONS), "manifest": str(MANIFESTS / "QCOMP-MANIFEST.json")}, sort_keys=True))


if __name__ == "__main__":
    main()
