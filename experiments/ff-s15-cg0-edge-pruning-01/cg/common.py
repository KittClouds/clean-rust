"""C-G0 shared setup: paths, constants copied from BANK/Lexi's run (and cross-checked), and the hash binding to her frozen artifacts."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(os.environ.get("CG0_LEXI_OUT", "D:/phoenix-target-overgraph/bank-v1-graph-surface-v2-20260929"))
LEXI_CODE = Path(os.environ.get("CG0_LEXI_CODE", "C:/Users/shuga/.codex/worktrees/bank-v1-surfaces/clean-rust/experiments/bank-v1-graph-surface-v2-20260929"))
BANK = ROOT.parent / "ff-s15-bank-01" / "releases" / "BANK-v1"
EVIDENCE = ROOT / "evidence"
RESULTS = ROOT / "results"

RUN_ID = "BANK-v1-GRAPH-SURFACE-V2-2026-09-29"
TASK, SURFACE, HEAD = "edge_existence", "middle_plus_final", "tiny_mlp"
HELD = ("S7", "S8", "S9")
TEST_SPLITS = ("TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT")
EPSILONS = (0.005, 0.01, 0.02, 0.05)
GATE_EPSILONS = (0.01, 0.02)
GAIN_BAR = 0.10
PERMUTATIONS, SEED = 200, 20260929

# Copied from BANK-v1 / Lexi's common.py and cross-checked against her module in `prepare`.
PREDICATES = ("AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED", "ENABLES", "BEFORE", "PART_OF", "OWNS")
ENTITY_TYPES = ("OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE")
TYPE_CODES = ENTITY_TYPES + ("UNKNOWN",)


def identifier_type(entity_id: str) -> str:
    prefix = entity_id.split("_", 1)[0].casefold()
    return {"obj": "OBJECT", "ag": "AGENT", "loc": "LOCATION", "sw": "SWITCH", "cont": "CONTAINER", "res": "RESOURCE"}.get(prefix, "UNKNOWN")


def type_code(entity_id: str) -> int:
    return TYPE_CODES.index(identifier_type(entity_id))


def pair_code(code_a: int, code_b: int) -> int:
    return code_a * len(TYPE_CODES) + code_b


def pair_name(code: int) -> str:
    return f"{TYPE_CODES[code // len(TYPE_CODES)]}->{TYPE_CODES[code % len(TYPE_CODES)]}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(8 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")


def verify_frozen_inputs(log=lambda *_: None, hash_features: bool = True) -> dict:
    """Every artifact the census consumes must match the hashes in Lexi's score receipt. Raises on any mismatch; returns the identity record."""
    results = read_json(OUT / "graph-readout-results.json")
    if results["run_id"] != RUN_ID:
        raise RuntimeError(f"unexpected run: {results['run_id']}")
    identity, problems = {"run_id": RUN_ID}, []

    def check(name, actual, expected):
        identity[name] = actual
        if actual != expected:
            problems.append(f"{name}: {actual} != {expected}")

    seal_path = OUT / "features" / "extraction-seal.json"
    check("extraction_seal_sha256", sha256_file(seal_path), results["extraction_seal_sha256"])
    seal = read_json(seal_path)
    check("scaler_seal_sha256", sha256_file(OUT / "scalers" / "scaler-seal.json"), results["scaler_seal_sha256"])
    check("graph_task_data_sha256", sha256_file(OUT / "graph-task-data-report.json"), results["graph_task_data_sha256"])
    check("spec_sha256", sha256_file(LEXI_CODE / "spec.json"), results["spec_sha256"])
    check("extractor_script_sha256", sha256_file(LEXI_CODE / "extract_local.py"), results["extractor_script_sha256"])
    check("readout_script_sha256", sha256_file(LEXI_CODE / "fit_graph.py"), results["readout_script_sha256"])
    check("metrics_script_sha256", sha256_file(LEXI_CODE / "graph_metrics.py"), results["metrics_script_sha256"])
    report = read_json(OUT / "graph-task-data-report.json")
    check("derivation_script_sha256", sha256_file(LEXI_CODE / "derive_graph_data.py"), report["derivation_script_sha256"])
    check("row_mentions_sha256", sha256_file(OUT / "row-mentions.jsonl"), seal["row_mentions_sha256"])
    check("rowmap_sha256", sha256_file(OUT / "rowmap.jsonl"), report["rowmap_sha256"])
    model = results["models"][TASK][SURFACE][HEAD]
    check("model_sha256", sha256_file(OUT / "models" / f"{TASK}-{SURFACE}-{HEAD}.pt"), model["model_sha256"])
    scaler_seal = read_json(OUT / "scalers" / "scaler-seal.json")
    entry = scaler_seal["files"].get(f"local-{SURFACE}.npz") if isinstance(scaler_seal["files"], dict) else None
    if entry is not None:
        check("local_scaler_sha256", sha256_file(OUT / "scalers" / f"local-{SURFACE}.npz"), entry["sha256"] if isinstance(entry, dict) else entry)
    if hash_features:
        for name in ("entity_middle_mean", "entity_final_mean"):
            check(f"{name}_sha256", sha256_file(OUT / "features" / f"{name}.npy"), seal["features"][name]["sha256"])
            log("verified", name)
    identity["selected_by_dev"] = results["selected_by_dev"][TASK]["local"]
    identity["lexi_sampled_pair_auc"] = {k: v["roc_auc"] for k, v in model["evaluations"].items()}
    if problems:
        raise RuntimeError("frozen input mismatch: " + "; ".join(problems))
    return identity
