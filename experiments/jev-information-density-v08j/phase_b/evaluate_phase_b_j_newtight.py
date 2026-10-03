"""Post-training NewTight and collateral evaluator for v0.8J.

This script runs only after the direct evaluator has sealed training and
written the evaluation-unlock receipt.  It never loads the LFM backbone; it
scores terminal frozen-head checkpoints against the sealed v0.8G evaluation
features and materialized evaluation bodies.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-b-v01")
V08G = Path(r"D:\codex-runs\jev-information-density-v08g")
CONTRACT = CODE / "phase-b-v01-contract.json"
UNLOCK = RUN / "reports/evaluation-unlock.json"
V08G_RECEIPT = V08G / "feature-cache/extraction-receipt.json"
V08G_MATERIALIZATION = V08G / "materialized-inputs/materialization-receipt.json"
V08G_FEATURES = V08G / "feature-cache/lfm-v08g-features.pt"
V08G_EVAL = V08G / "materialized-inputs/new_tight_eval-groups.jsonl"
V08G_MANIFEST = V08G / "v08g-run-manifest.json"
PROBE = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
V08G_TRAIN = ROOT / "experiments/jev-information-density-v08g/train_v08g.py"
V08G_ANALYZE = ROOT / "experiments/jev-information-density-v08g/analyze_v08g.py"
J_DIRECT = CODE / "evaluate_phase_b_j_direct.py"
OUT = RUN / "reports"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("J00", "J10", "J01", "J11")
FEATURE_KEY = "mean_full@16"
PROFILE = "name_definition"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def add_ood_axes(rows: list[dict[str, Any]], groups: dict[str, list[dict[str, Any]]]) -> None:
    ontology_seen = {row.get("family_ids", {}).get("ontology_family")
                     for bank in groups.values() for row in bank}
    world_seen = {row.get("family_ids", {}).get("world_or_topology_family")
                  for bank in groups.values() for row in bank}
    for row in rows:
        families = row.get("family_ids", {})
        axes: list[str] = []
        if families.get("ontology_family") not in (None, *ontology_seen):
            axes.append("ontology_family")
        if families.get("world_or_topology_family") not in (None, *world_seen):
            axes.append("world_or_topology_family")
        row["held_out_axes"] = axes


def load_frozen_inputs(v08g_train: Any) -> dict[str, Any]:
    unlock = read_json(UNLOCK)
    contract = read_json(CONTRACT)
    require(unlock["status"] == "EVALUATION_UNLOCKED_AFTER_TRAINING_SEAL", "training unlock missing")
    require(unlock["contract_sha256"] == sha256_file(CONTRACT), "J contract drifted")
    require(sha256_file(V08G_FEATURES) == read_json(V08G_RECEIPT)["cache"]["sha256"], "NewTight feature cache drift")
    materialization = read_json(V08G_MATERIALIZATION)
    eval_spec = materialization["group_files"]["new_tight_eval"]
    require(sha256_file(V08G_EVAL) == eval_spec["sha256"], "NewTight group bank drift")
    require(eval_spec["group_count"] == 83328, "NewTight group count drift")
    v08g_receipt = read_json(V08G_RECEIPT)
    require(v08g_receipt["model"]["revision"] == contract["model"]["revision"], "LFM revision mismatch")
    require(v08g_receipt["path"]["batch_size"] == 1 and v08g_receipt["path"]["padding"] is False,
            "NewTight cache was not produced by the exact-input path")
    v08g_data = v08g_train.load_run_data()
    evaluation = v08g_data["evaluation"]
    require(len(evaluation) == 83328, "loaded NewTight count drift")
    add_ood_axes(evaluation, v08g_data["groups"])
    return {"contract": contract, "unlock": unlock, "materialization": materialization,
            "v08g_receipt": v08g_receipt, "v08g_data": v08g_data}


def load_head(direct: Any, path: Path) -> torch.nn.Module:
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    head = direct.load_head(direct.load_module("jev_v08j_probe_newtight", PROBE), path, DEVICE)
    head.eval()
    return head


def summarize_view(analyze: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "all": analyze.summarize(rows),
        "by_view": {view: analyze.summarize([row for row in rows if row.get("view") == view])
                    for view in sorted({row.get("view") for row in rows})},
        "by_probability_source": {
            source: analyze.summarize([row for row in rows if row.get("probability_source") == source])
            for source in sorted({row.get("probability_source") for row in rows})
        },
    }


def group_report(analyze: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "typed": summarize_view(analyze, rows),
        "ood": analyze.ood_report(rows),
        "hard_siblings": analyze.hard_sibling_report(rows),
        "candidate_cardinality": analyze.candidate_cardinality_report(rows),
        "candidate_order_invariance": analyze.invariance_report(rows),
        "intervention": analyze.intervention_report(rows),
    }


def score_terminal(run_dir: Path, direct: Any, v08g_train: Any, analyze: Any,
                   evaluation: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    checkpoint = run_dir / "checkpoint-epoch-3.pt"
    require(checkpoint.is_file(), f"missing terminal checkpoint: {checkpoint}")
    head = load_head(direct, checkpoint)
    state = cache["features"]["state"][FEATURE_KEY].to(DEVICE)
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(DEVICE)
    rows = v08g_train.score_groups(head, evaluation, state, candidates, PROFILE, DEVICE, batch_size=4096)
    report = group_report(analyze, rows)
    report["row_count"] = len(rows)
    report["checkpoint_sha256"] = sha256_file(checkpoint)
    return report


def score_binding(run_dir: Path, direct: Any, v08g_train: Any, analyze: Any,
                  binding: list[dict[str, Any]], cache: dict[str, Any]) -> dict[str, Any]:
    checkpoint = run_dir / "checkpoint-epoch-3.pt"
    head = load_head(direct, checkpoint)
    state = cache["features"]["state"][FEATURE_KEY].to(DEVICE)
    candidates = cache["features"]["candidate"]["opaque_definition"][FEATURE_KEY].to(DEVICE)
    rows = v08g_train.score_groups(head, binding, state, candidates, "opaque_definition", DEVICE, batch_size=4096)
    path = run_dir / "j-binding-terminal-predictions.jsonl"
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return analyze.binding_report(path)


def paired_effects(summaries: dict[str, Any], metric_paths: list[tuple[str, ...]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for view, metric in metric_paths:
        key = f"{view}/{metric}"
        per_seed = []
        for seed_index in range(3):
            values = []
            for arm in ARMS:
                value = summaries[f"seed-{seed_index + 1}/{arm}"]["newtight"]["typed"]["by_view"].get(view, {}).get(metric)
                values.append(value)
            per_seed.append({"seed": SEEDS[seed_index], "J00": values[0], "J10": values[1],
                             "J01": values[2], "J11": values[3],
                             "J10_minus_J00": values[1] - values[0] if None not in (values[0], values[1]) else None,
                             "J01_minus_J00": values[2] - values[0] if None not in (values[0], values[2]) else None,
                             "J11_minus_J10": values[3] - values[1] if None not in (values[1], values[3]) else None,
                             "J11_minus_J01": values[3] - values[2] if None not in (values[2], values[3]) else None})
        output[key] = {"per_seed": per_seed, "no_composite_score": True}
    return output


def main() -> int:
    direct = load_module("jev_v08j_direct_newtight", J_DIRECT)
    v08g_train = load_module("jev_v08j_v08g_train", V08G_TRAIN)
    analyze = load_module("jev_v08j_v08g_analyze", V08G_ANALYZE)
    frozen = load_frozen_inputs(v08g_train)
    cache = frozen["v08g_data"]["cache"]
    binding_cache = frozen["v08g_data"]["binding_cache"]
    binding_groups = frozen["v08g_data"]["binding_groups"]

    summaries: dict[str, Any] = {}
    binding_reports: dict[str, Any] = {}
    for seed_index in range(3):
        for arm in ARMS:
            key = f"seed-{seed_index + 1}/{arm}"
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            print(f"scoring {key} on NewTight", flush=True)
            summaries[key] = {"newtight": score_terminal(run_dir, direct, v08g_train, analyze,
                                                           frozen["v08g_data"]["evaluation"], cache)}
            print(f"scoring {key} on binding", flush=True)
            binding_reports[key] = score_binding(run_dir, direct, v08g_train, analyze,
                                                 binding_groups, binding_cache)

    metric_paths = [(view, metric) for view in ("choice", "independent_applicability", "ordinal_score")
                    for metric in ("accuracy", "nll", "brier", "posterior_l1", "ece_soft", "ordinal_rps", "ordinal_adjacent", "expected_rank_spearman")]
    effects = paired_effects(summaries, metric_paths)
    behavior = {
        "protocol": "jev-information-density/v0.8j-phase-b-v01",
        "status": "POST_TRAINING_COLLATERAL_EVALUATION_COMPLETE",
        "primary_direct_panel": "reports/direct-contrast-by-arm-seed-epoch.json",
        "secondary": "NewTight typed panels, schema binding, intervention geometry",
        "model": {"repo_id": frozen["contract"]["model"]["repo_id"],
                  "revision": frozen["contract"]["model"]["revision"], "backbone_frozen": True},
        "terminal_runs": 12,
        "epochs_scored": [3],
        "device": DEVICE,
        "no_composite_score": True,
        "phoenix_access": False,
    }
    reports = {
        "newtight-capability-vector.json": summaries,
        "newtight-paired-effects.json": effects,
        "schema-binding.json": binding_reports,
        "intervention-analysis.json": {key: value["newtight"]["intervention"] for key, value in summaries.items()},
        "hard-sibling-analysis.json": {key: value["newtight"]["hard_siblings"] for key, value in summaries.items()},
        "ood-transfer-analysis.json": {key: value["newtight"]["ood"] for key, value in summaries.items()},
        "v08j-collateral-behavior-map.json": behavior,
    }
    written: dict[str, Any] = {}
    for name, payload in reports.items():
        path = OUT / name
        write_json(path, payload)
        written[name] = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    integrity = {
        "status": "PASS",
        "protocol": behavior["protocol"],
        "contract_sha256": sha256_file(CONTRACT),
        "evaluation_unlock_sha256": sha256_file(UNLOCK),
        "newtight_group_sha256": sha256_file(V08G_EVAL),
        "newtight_feature_cache_sha256": sha256_file(V08G_FEATURES),
        "v08g_materialization_sha256": sha256_file(V08G_MATERIALIZATION),
        "terminal_run_count": len(summaries),
        "reports": written,
        "backbone_frozen": True,
        "phoenix_access": False,
        "evaluation_after_training_seal": True,
    }
    write_json(OUT / "collateral-evaluation-integrity.json", integrity)
    print(json.dumps({"status": behavior["status"], "reports": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
