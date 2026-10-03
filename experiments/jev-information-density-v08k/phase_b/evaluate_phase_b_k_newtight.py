"""Secondary NewTight/collateral evaluator for the two K arms."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
OUT = RUN / "reports"
CONTRACT = CODE / "phase-b-v01-contract.json"
UNLOCK = RUN / "reports/evaluation-unlock.json"
V08G = Path(r"D:\codex-runs\jev-information-density-v08g")
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("K-DUP", "K-SHAM")


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    direct = load_module("jev_v08k_direct_for_newtight", CODE / "evaluate_phase_b_k_direct.py")
    v08g_train = load_module("jev_v08k_v08g_train", ROOT / "experiments/jev-information-density-v08g/train_v08g.py")
    analyze = load_module("jev_v08k_v08g_analyze", ROOT / "experiments/jev-information-density-v08g/analyze_v08g.py")
    legacy = load_module("jev_v08k_legacy_newtight", ROOT / "experiments/jev-information-density-v08j/phase_b/evaluate_phase_b_j_newtight.py")
    legacy.RUN = RUN
    legacy.CONTRACT = CONTRACT
    legacy.UNLOCK = UNLOCK
    legacy.J_DIRECT = CODE / "evaluate_phase_b_k_direct.py"
    frozen = legacy.load_frozen_inputs(v08g_train)
    cache = frozen["v08g_data"]["cache"]
    binding_cache = frozen["v08g_data"]["binding_cache"]
    binding_groups = frozen["v08g_data"]["binding_groups"]
    summaries: dict[str, Any] = {}
    bindings: dict[str, Any] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            key = f"seed-{seed_index + 1}/{arm}"
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            summaries[key] = {"newtight": legacy.score_terminal(run_dir, direct, v08g_train, analyze, frozen["v08g_data"]["evaluation"], cache)}
            bindings[key] = legacy.score_binding(run_dir, direct, v08g_train, analyze, binding_groups, binding_cache)

    effects: dict[str, Any] = {}
    for view in ("choice", "independent_applicability", "ordinal_score"):
        for metric in ("accuracy", "nll", "brier", "posterior_l1", "ece_soft", "ordinal_rps", "ordinal_adjacent", "expected_rank_spearman"):
            rows = []
            for seed_index, seed in enumerate(SEEDS):
                dup = summaries[f"seed-{seed_index + 1}/K-DUP"]["newtight"]["typed"]["by_view"].get(view, {}).get(metric)
                sham = summaries[f"seed-{seed_index + 1}/K-SHAM"]["newtight"]["typed"]["by_view"].get(view, {}).get(metric)
                rows.append({"seed": seed, "K-DUP": dup, "K-SHAM": sham, "K-SHAM_minus_K-DUP": sham - dup if None not in (sham, dup) else None})
            effects[f"{view}/{metric}"] = {"per_seed": rows, "no_composite_score": True}

    reports = {
        "k-newtight-capability-vector.json": summaries,
        "k-newtight-paired-effects.json": effects,
        "k-schema-binding.json": bindings,
        "k-intervention-analysis.json": {key: value["newtight"]["intervention"] for key, value in summaries.items()},
        "k-hard-sibling-analysis.json": {key: value["newtight"]["hard_siblings"] for key, value in summaries.items()},
        "k-ood-transfer-analysis.json": {key: value["newtight"]["ood"] for key, value in summaries.items()},
    }
    written = {}
    for name, payload in reports.items():
        path = OUT / name
        write_json(path, payload)
        written[name] = {"path": str(path), "sha256": sha256_file(path), "bytes": path.stat().st_size}
    integrity = {"status": "PASS", "protocol": read_json(CONTRACT)["protocol"], "contract_sha256": sha256_file(CONTRACT), "evaluation_unlock_sha256": sha256_file(UNLOCK), "newtight_group_sha256": sha256_file(V08G / "materialized-inputs/new_tight_eval-groups.jsonl"), "terminal_run_count": 6, "reports": written, "backbone_frozen": True, "phoenix_access": False, "evaluation_after_training_seal": True}
    write_json(OUT / "k-collateral-evaluation-integrity.json", integrity)
    print(json.dumps({"status": "K_COLLATERAL_EVALUATION_COMPLETE", "reports": written}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
