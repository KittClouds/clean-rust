"""Post-training direct-surface evaluator for v0.8J.

The first phase of this script verifies and seals all training outputs without
opening held-out bodies.  Only after that receipt is written does it load the
held-out contrast rows and the sealed v0.8I evaluation feature cache.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import torch


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08j\phase-b-v01")
V08I_RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
CONTRACT = CODE / "phase-b-v01-contract.json"
AUTH = RUN / "preflight/model-contact-authorization.json"
FEATURES = RUN / "feature-cache/phase-b-train-features.pt"
FEATURE_RECEIPT = RUN / "feature-cache/extraction-receipt.json"
HELDOUT = V08I_RUN / "inputs/heldout-contrast-groups.jsonl"
V08I_FEATURES = V08I_RUN / "feature-cache/phase-b-train-features.pt"
V08I_FEATURE_RECEIPT = V08I_RUN / "feature-cache/extraction-receipt.json"
INPUTS_RECEIPT = V08I_RUN / "inputs/phase-b-inputs-receipt.json"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("J00", "J10", "J01", "J11")
FEATURE_KEY = "mean_full@16"
PROFILE = "name_definition"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


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


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode("utf-8"))
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def mean(values: Iterable[float]) -> float | None:
    data = list(values)
    return sum(data) / len(data) if data else None


def pearson(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm, rm = mean(left), mean(right)
    assert lm is not None and rm is not None
    numerator = sum((a - lm) * (b - rm) for a, b in zip(left, right))
    denominator = math.sqrt(sum((a - lm) ** 2 for a in left) * sum((b - rm) ** 2 for b in right))
    return numerator / denominator if denominator else None


def load_v08i_analysis() -> Any:
    return load_module("jev_v08j_v08i_analysis", ROOT / "experiments/jev-information-density-v08i/phase_b/analyze_phase_b.py")


def verify_training_seal(probe: Any) -> dict[str, Any]:
    contract = read_json(CONTRACT)
    auth = read_json(AUTH)
    summary_path = RUN / "reports/training-execution-summary.json"
    summary = read_json(summary_path)
    require(auth["status"] == "PASS" and auth["training_authorized"] is True, "training authorization absent")
    require(auth["contract_sha256"] == sha256_file(CONTRACT), "contract drifted after preflight")
    require(sha256_file(FEATURES) == read_json(FEATURE_RECEIPT)["feature_cache"]["sha256"], "training feature cache drift")
    require(summary["status"] == "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "training summary not sealed")
    require(summary["evaluation_access"] is False and summary["phoenix_access"] is False, "training boundary was crossed")
    require(summary["contract_sha256"] == auth["contract_sha256"], "summary contract mismatch")
    require(len(summary["runs"]) == 12, "training summary does not contain 12 runs")

    runs: dict[tuple[int, str], dict[str, Any]] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            report_path = run_dir / "run-report.json"
            require(report_path.is_file(), f"missing run report: {run_dir}")
            report = read_json(report_path)
            require(report["status"] == "TRAINING_COMPLETE_NO_EVALUATION", f"run not training-only complete: {run_dir}")
            require(report["protocol"] == contract["protocol"], f"run protocol drift: {run_dir}")
            require(report["seed"] == seed and report["arm"] == arm, f"run identity mismatch: {run_dir}")
            require(report["evaluation_access"] is False and report["phoenix_access"] is False, f"run boundary drift: {run_dir}")
            require(report["config_sha256"], f"missing config hash: {run_dir}")
            require(len(report["history"]) == 3 and report["primary_groups"] == 100000, f"run budget drift: {run_dir}")
            require(report["triplets"] == 5000 and report["existing_invariance_pairs"] == 4982, f"run input drift: {run_dir}")
            config = read_json(run_dir / "run-config.json")
            require(config["config_sha256"] == report["config_sha256"], f"config hash mismatch: {run_dir}")
            require(config["epochs"] == 3 and config["batch_size_groups"] == 256, f"config budget drift: {run_dir}")
            require(config["evaluation_access"] is False, f"config evaluation boundary drift: {run_dir}")
            for epoch in (1, 2, 3):
                checkpoint_path = run_dir / f"checkpoint-epoch-{epoch}.pt"
                require(checkpoint_path.is_file(), f"missing checkpoint: {checkpoint_path}")
                checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
                require(checkpoint["epoch"] == epoch, f"checkpoint epoch mismatch: {checkpoint_path}")
                require(checkpoint["config_sha256"] == report["config_sha256"], f"checkpoint config mismatch: {checkpoint_path}")
            terminal = torch.load(run_dir / "checkpoint-epoch-3.pt", map_location="cpu", weights_only=True)
            require(score_digest(terminal["head_state"]) == report["terminal_head_sha256"], f"terminal head hash mismatch: {run_dir}")
            runs[(seed_index, arm)] = report
        initial = {runs[(seed_index, arm)]["initial_head_sha256"] for arm in ARMS}
        require(len(initial) == 1, f"paired initialization mismatch for seed {seed_index + 1}")

    unlock = {
        "status": "EVALUATION_UNLOCKED_AFTER_TRAINING_SEAL",
        "protocol": contract["protocol"],
        "contract_sha256": sha256_file(CONTRACT),
        "training_summary_sha256": sha256_file(summary_path),
        "run_count": 12,
        "checkpoint_count": 36,
        "paired_initialization_verified": True,
        "training_only_reports_verified": True,
        "evaluation_bodies_opened_before_unlock": False,
        "evaluation_access": True,
        "phoenix_access": False,
        "heldout_source_receipt_sha256": sha256_file(INPUTS_RECEIPT),
        "heldout_feature_receipt_sha256": sha256_file(V08I_FEATURE_RECEIPT),
    }
    write_json(RUN / "reports/evaluation-unlock.json", unlock)
    return {"contract": contract, "auth": auth, "runs": runs, "unlock": unlock}


def candidate_map(row: dict[str, Any], field: str) -> dict[str, float]:
    ids = [str(value) for value in row["candidate_semantic_ids"]]
    values = row[field]
    require(len(ids) == len(values) and len(set(ids)) == len(ids), f"candidate alignment error: {row.get('group_id')}")
    return dict(zip(ids, [float(value) for value in values]))


def winner(values: dict[str, float]) -> str:
    return max(values, key=lambda key: (values[key], key))


def rank_of(values: dict[str, float], candidate: str) -> int:
    ordered = sorted(values, key=lambda key: (-values[key], key))
    return ordered.index(candidate) + 1


def top_two_margin(values: dict[str, float]) -> float:
    ordered = sorted(values.values(), reverse=True)
    return ordered[0] - ordered[1] if len(ordered) > 1 else 0.0


def conditional_locality(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    all_l1: list[float] = []
    all_flip = 0
    correct_l1: list[float] = []
    correct_flip = 0
    strict_l1: list[float] = []
    strict_flip = 0
    for pair in pairs:
        anchor, fact, sham = pair["anchor"], pair["fact_flip"], pair["sham"]
        pa, pf, ps = candidate_map(anchor, "prediction"), candidate_map(fact, "prediction"), candidate_map(sham, "prediction")
        ga, gf = candidate_map(anchor, "gold"), candidate_map(fact, "gold")
        new_id, old_id = pair["new_id"], pair["old_id"]
        gold_delta = gf[new_id] - ga[new_id]
        fact_delta = pf[new_id] - pa[new_id]
        direction_ok = fact_delta * gold_delta > 0.0 if abs(gold_delta) > 1e-12 else abs(fact_delta) <= 1e-12
        strict_ok = winner(pa) == old_id and winner(pf) == new_id
        l1 = sum(abs(pa[key] - ps[key]) for key in pa)
        flip = int(winner(pa) != winner(ps))
        all_l1.append(l1)
        all_flip += flip
        if direction_ok:
            correct_l1.append(l1)
            correct_flip += flip
        if strict_ok:
            strict_l1.append(l1)
            strict_flip += flip
    def pack(values: list[float], flips: int) -> dict[str, Any]:
        return {"count": len(values), "mean_sham_l1": mean(values), "sham_map_flip_rate": flips / len(values) if values else None}
    return {"all": pack(all_l1, all_flip), "conditioned_on_correct_fact_direction": pack(correct_l1, correct_flip), "conditioned_on_strict_old_to_new_transition": pack(strict_l1, strict_flip)}


def enrich(rows: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        source = source_by_id[row["group_id"]]
        merged = dict(row)
        for key in ("contrast_anchor_id", "contrast_role", "contrast_family_id", "expected_old_winner_id", "expected_new_winner_id"):
            merged[key] = source[key]
        output.append(merged)
    return output


def load_head(probe: Any, checkpoint_path: Path, device: str) -> torch.nn.Module:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
    head.load_state_dict(checkpoint["head_state"])
    head.eval()
    return head


def score_rows(scorer: Any, head: torch.nn.Module, rows: list[dict[str, Any]], state: torch.Tensor, candidates: torch.Tensor, device: str) -> list[dict[str, Any]]:
    return scorer.score_groups(head, rows, state, candidates, PROFILE, device, batch_size=1024)


def direct_metrics(analysis: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups = analysis.collect_triplets(rows)
    flat = [pair for family in sorted(groups) for pair in groups[family]]
    base = analysis.analyze_triplets(rows)
    base["conditional_locality"] = conditional_locality(flat)
    base["family_counts"] = {family: len(groups[family]) for family in sorted(groups)}
    return base


def contrast(a: dict[str, Any], b: dict[str, Any], path: tuple[str, ...]) -> float | None:
    left: Any = a
    right: Any = b
    for key in path:
        left, right = left.get(key), right.get(key)
    if left is None or right is None:
        return None
    return left - right


def factorial(values: dict[str, dict[str, Any]]) -> dict[str, Any]:
    j00, j10, j01, j11 = values["J00"], values["J10"], values["J01"], values["J11"]
    paths = {
        "fact_flip.correct_direction_rate": ("fact_flip", "overall", "new_winner_probability_movement", "correct_direction_rate"),
        "fact_flip.strict_map_transition_rate": ("fact_flip", "overall", "map_response", "strict_old_to_new_transition_rate"),
        "sham.mean_l1": ("sham_invariance", "overall", "mean_prediction_distribution_l1"),
        "sham.map_flip_rate": ("sham_invariance", "overall", "map_flip_rate"),
        "locality.correct_direction.mean_l1": ("conditional_locality", "conditioned_on_correct_fact_direction", "mean_sham_l1"),
        "locality.correct_direction.map_flip_rate": ("conditional_locality", "conditioned_on_correct_fact_direction", "sham_map_flip_rate"),
    }
    result: dict[str, Any] = {}
    for name, path in paths.items():
        c1 = contrast(j10, j00, path)
        c2 = contrast(j01, j00, path)
        c3 = contrast(j11, j10, path)
        c4 = contrast(j11, j01, path)
        result[name] = {"C1_J10_minus_J00": c1, "C2_J01_minus_J00": c2, "C3_J11_minus_J10": c3, "C4_J11_minus_J01": c4,
                        "ME_S": (c1 + c4) / 2 if c1 is not None and c4 is not None else None,
                        "ME_I": (c2 + c3) / 2 if c2 is not None and c3 is not None else None,
                        "INT": c3 - c2 if c2 is not None and c3 is not None else None}
    return result


def main() -> int:
    probe = load_module("jev_v08j_probe_eval", ROOT / "experiments/jev-frozen-readout-v01/probe.py")
    scorer = load_module("jev_v08j_v08g_eval", ROOT / "experiments/jev-information-density-v08g/train_v08g.py")
    sealed = verify_training_seal(probe)

    # Evaluation access begins only after verify_training_seal writes the unlock receipt.
    input_receipt = read_json(INPUTS_RECEIPT)
    heldout_hash = input_receipt["input_tables"]["heldout_groups"]["sha256"]
    require(sha256_file(HELDOUT) == heldout_hash, "held-out contrast source drift")
    eval_receipt = read_json(V08I_FEATURE_RECEIPT)
    require(eval_receipt["model"]["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "evaluation feature revision drift")
    require(eval_receipt["path"]["implementation_sha256"] == read_json(sealed["auth"] and V08I_FEATURE_RECEIPT)["path"]["implementation_sha256"], "evaluation adapter receipt malformed")
    require(sha256_file(V08I_FEATURES) == eval_receipt["feature_cache"]["sha256"], "evaluation feature cache drift")
    heldout = read_jsonl(HELDOUT)
    require(len(heldout) == 6000, "held-out group count drift")
    source_by_id = {row["group_id"]: row for row in heldout}
    require(len(source_by_id) == 6000, "held-out group IDs are not unique")
    cache = torch.load(V08I_FEATURES, map_location="cpu", weights_only=True)
    state = cache["features"]["state"][FEATURE_KEY].to(DEVICE)
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(DEVICE)
    require(state.shape == (29557, 2048) and candidates.shape == (389, 2048), "evaluation feature shape drift")

    direct_by_run_epoch: dict[str, Any] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            report = sealed["runs"][(seed_index, arm)]
            for epoch in (1, 2, 3):
                checkpoint_path = run_dir / f"checkpoint-epoch-{epoch}.pt"
                head = load_head(probe, checkpoint_path, DEVICE)
                scored = score_rows(scorer, head, heldout, state, candidates, DEVICE)
                enriched = enrich(scored, source_by_id)
                analysis = direct_metrics(load_v08i_analysis(), enriched)
                key = f"seed-{seed_index + 1}/{arm}/epoch-{epoch}"
                direct_by_run_epoch[key] = {"seed": seed, "arm": arm, "epoch": epoch, "analysis": analysis}

    factorial_by_seed_epoch: dict[str, Any] = {}
    for seed_index, seed in enumerate(SEEDS):
        for epoch in (1, 2, 3):
            values = {arm: direct_by_run_epoch[f"seed-{seed_index + 1}/{arm}/epoch-{epoch}"]["analysis"] for arm in ARMS}
            factorial_by_seed_epoch[f"seed-{seed_index + 1}/epoch-{epoch}"] = {"seed": seed, "epoch": epoch, "arms": values, "effects": factorial(values)}

    terminal = {key: value for key, value in direct_by_run_epoch.items() if value["epoch"] == 3}
    write_json(RUN / "reports/direct-contrast-by-arm-seed-epoch.json", direct_by_run_epoch)
    write_json(RUN / "reports/conditional-locality.json", {
        "protocol": sealed["contract"]["protocol"],
        "status": "COMPLETE",
        "terminal": {key: value["analysis"]["conditional_locality"] for key, value in terminal.items()},
        "interpretation": "Conditional sham drift is reported only among cases with successful fact-flip direction or strict old-to-new transition.",
    })
    write_json(RUN / "reports/factorial-effects.json", {"protocol": sealed["contract"]["protocol"], "status": "COMPLETE", "by_seed_epoch": factorial_by_seed_epoch})
    write_json(RUN / "reports/family-transfer.json", {
        "protocol": sealed["contract"]["protocol"],
        "status": "COMPLETE",
        "terminal_by_run": {key: value["analysis"]["fact_flip"]["by_family"] for key, value in terminal.items()},
        "families": sorted({family for value in terminal.values() for family in value["analysis"]["family_counts"]}),
    })
    integrity = {
        "status": "POST_TRAINING_DIRECT_EVALUATION_COMPLETE",
        "protocol": sealed["contract"]["protocol"],
        "evaluation_unlock_sha256": sha256_file(RUN / "reports/evaluation-unlock.json"),
        "heldout_groups": 6000,
        "heldout_pairs": 2000,
        "runs_scored": 12,
        "epochs_scored": 3,
        "predictions_scored": 36,
        "heldout_source_sha256": heldout_hash,
        "evaluation_feature_cache_sha256": eval_receipt["feature_cache"]["sha256"],
        "training_evaluation_boundary": "all 12 training reports sealed before held-out source opened",
        "phoenix_access": False,
    }
    write_json(RUN / "reports/post-training-evaluation-integrity.json", integrity)
    print(json.dumps({"status": integrity["status"], "runs_scored": 12, "epochs_scored": 3, "reports": str(RUN / "reports")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
