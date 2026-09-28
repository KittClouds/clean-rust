"""Post-training direct controlled-contrast evaluator for v0.8K."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Iterable

import torch


ROOT = Path(__file__).resolve().parents[3]
CODE = Path(__file__).resolve().parent
RUN = Path(r"D:\codex-runs\jev-information-density-v08k\phase-b-v01")
V08I_RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
CONTRACT = CODE / "phase-b-v01-contract.json"
AUTH = RUN / "preflight/model-contact-authorization.json"
FEATURES = RUN / "feature-cache/phase-b-train-features.pt"
FEATURE_RECEIPT = RUN / "feature-cache/extraction-receipt.json"
HELDOUT = V08I_RUN / "inputs/heldout-contrast-groups.jsonl"
EVAL_FEATURES = V08I_RUN / "feature-cache/phase-b-train-features.pt"
EVAL_FEATURE_RECEIPT = V08I_RUN / "feature-cache/extraction-receipt.json"
INPUTS_RECEIPT = V08I_RUN / "inputs/phase-b-inputs-receipt.json"
SEEDS = [20260927, 20260928, 20260929]
ARMS = ("K-DUP", "K-SHAM")
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper: {path}")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode())
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def load_head(probe: Any, checkpoint_path: Path, device: str) -> torch.nn.Module:
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
    head.load_state_dict(checkpoint["head_state"])
    head.eval()
    return head


def mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def winner(values: dict[str, float]) -> str:
    return max(values, key=lambda key: (values[key], key))


def candidate_map(row: dict[str, Any], field: str) -> dict[str, float]:
    ids = [str(value) for value in row["candidate_semantic_ids"]]
    values = row[field]
    require(len(ids) == len(values), f"candidate alignment error: {row.get('group_id')}")
    return dict(zip(ids, [float(value) for value in values]))


def conditional_locality(pairs: list[dict[str, Any]]) -> dict[str, Any]:
    buckets = {"all": [[], 0], "correct_direction": [[], 0], "strict_transition": [[], 0]}
    for pair in pairs:
        anchor, fact, sham = pair["anchor"], pair["fact_flip"], pair["sham"]
        pa = candidate_map(anchor, "prediction")
        pf = candidate_map(fact, "prediction")
        ps = candidate_map(sham, "prediction")
        ga = candidate_map(anchor, "gold")
        gf = candidate_map(fact, "gold")
        new_id = pair["new_id"]
        old_id = pair["old_id"]
        gold_delta = gf[new_id] - ga[new_id]
        fact_delta = pf[new_id] - pa[new_id]
        direction_ok = fact_delta * gold_delta > 0.0 if abs(gold_delta) > 1e-12 else abs(fact_delta) <= 1e-12
        strict_ok = winner(pa) == old_id and winner(pf) == new_id
        l1 = sum(abs(pa[key] - ps[key]) for key in pa)
        flip = int(winner(pa) != winner(ps))
        buckets["all"][0].append(l1)
        buckets["all"][1] += flip
        if direction_ok:
            buckets["correct_direction"][0].append(l1)
            buckets["correct_direction"][1] += flip
        if strict_ok:
            buckets["strict_transition"][0].append(l1)
            buckets["strict_transition"][1] += flip
    return {name: {"count": len(values), "mean_sham_l1": mean(values), "sham_map_flip_rate": flips / len(values) if values else None} for name, (values, flips) in buckets.items()}


def load_training_seal(probe: Any) -> dict[str, Any]:
    contract = read_json(CONTRACT)
    auth = read_json(AUTH)
    receipt = read_json(FEATURE_RECEIPT)
    summary = read_json(RUN / "reports/training-execution-summary.json")
    require(auth["status"] == "PASS" and auth["training_authorized"] is True, "training authorization absent")
    require(auth["contract_sha256"] == sha256_file(CONTRACT), "contract drift")
    require(receipt["objective_graph_sha256"] == contract["objective_graph_sha256"], "feature graph drift")
    require(sha256_file(FEATURES) == receipt["feature_cache"]["sha256"], "training feature cache drift")
    require(summary["status"] == "ALL_SCHEDULED_RUNS_COMPLETE_NO_EVALUATION", "training is not sealed")
    require(summary["evaluation_access"] is False and summary["phoenix_access"] is False, "training boundary crossed")
    require(len(summary["runs"]) == 6 and summary["checkpoint_count"] == 18, "K run count drift")
    runs: dict[tuple[int, str], dict[str, Any]] = {}
    checkpoint_hashes: dict[str, str] = {}
    telemetry_hashes: dict[str, str] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            report = read_json(run_dir / "run-report.json")
            require(report["status"] == "TRAINING_COMPLETE_NO_EVALUATION", f"run incomplete: {run_dir}")
            require(report["seed"] == seed and report["arm"] == arm, f"run identity drift: {run_dir}")
            require(report["evaluation_access"] is False and report["phoenix_access"] is False, f"run boundary drift: {run_dir}")
            require(report["primary_groups"] == 100000 and report["triplets"] == 5000 and report["auxiliary_events"] == 5000, f"run budget drift: {run_dir}")
            config = read_json(run_dir / "run-config.json")
            require(config["config_sha256"] == report["config_sha256"], f"config hash drift: {run_dir}")
            require(config["epochs"] == 3 and config["batch_size_groups"] == 256, f"training recipe drift: {run_dir}")
            for epoch in (1, 2, 3):
                path = run_dir / f"checkpoint-epoch-{epoch}.pt"
                checkpoint = torch.load(path, map_location="cpu", weights_only=True)
                require(checkpoint["epoch"] == epoch and checkpoint["config_sha256"] == report["config_sha256"], f"checkpoint drift: {path}")
                require(score_digest(checkpoint["head_state"]) == (report["terminal_head_sha256"] if epoch == 3 else score_digest(checkpoint["head_state"])), f"checkpoint state malformed: {path}")
                checkpoint_hashes[f"seed-{seed_index + 1}/{arm}/epoch-{epoch}"] = sha256_file(path)
            telemetry_hashes[f"seed-{seed_index + 1}/{arm}"] = sha256_file(run_dir / "training-events.jsonl")
            runs[(seed_index, arm)] = report
        require(runs[(seed_index, "K-DUP")]["initial_head_sha256"] == runs[(seed_index, "K-SHAM")]["initial_head_sha256"], f"paired init drift seed {seed}")
    seal = {"status": "TRAINING_SEALED_NO_EVALUATION", "protocol": contract["protocol"], "contract_sha256": sha256_file(CONTRACT), "run_count": 6, "checkpoint_count": 18, "checkpoint_sha256": checkpoint_hashes, "telemetry_sha256": telemetry_hashes, "evaluation_bodies_opened": False, "phoenix_access": False}
    write_json(RUN / "reports/training-seal-manifest.json", seal)
    unlock = {"status": "EVALUATION_UNLOCKED_AFTER_TRAINING_SEAL", "protocol": contract["protocol"], "contract_sha256": sha256_file(CONTRACT), "training_seal_sha256": sha256_file(RUN / "reports/training-seal-manifest.json"), "run_count": 6, "checkpoint_count": 18, "evaluation_bodies_opened_before_unlock": False, "evaluation_access": True, "phoenix_access": False}
    write_json(RUN / "reports/evaluation-unlock.json", unlock)
    return {"contract": contract, "runs": runs, "unlock": unlock}


def enrich(rows: list[dict[str, Any]], source_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        source = source_by_id[row["group_id"]]
        merged = dict(row)
        for key in ("contrast_anchor_id", "contrast_role", "contrast_family_id", "expected_old_winner_id", "expected_new_winner_id"):
            merged[key] = source[key]
        output.append(merged)
    return output


def main() -> int:
    probe = load_module("jev_v08k_probe_eval", ROOT / "experiments/jev-frozen-readout-v01/probe.py")
    scorer = load_module("jev_v08k_scorer", ROOT / "experiments/jev-information-density-v08g/train_v08g.py")
    analysis = load_module("jev_v08k_analysis", ROOT / "experiments/jev-information-density-v08i/phase_b/analyze_phase_b.py")
    sealed = load_training_seal(probe)

    input_receipt = read_json(INPUTS_RECEIPT)
    heldout_hash = input_receipt["input_tables"]["heldout_groups"]["sha256"]
    require(sha256_file(HELDOUT) == heldout_hash, "held-out source drift")
    eval_receipt = read_json(EVAL_FEATURE_RECEIPT)
    require(eval_receipt["model"]["revision"] == "7453bca97ca1e67754c4035a4b4c584e1c9dd725", "evaluation feature revision drift")
    require(sha256_file(EVAL_FEATURES) == eval_receipt["feature_cache"]["sha256"], "evaluation feature cache drift")
    heldout = read_jsonl(HELDOUT)
    require(len(heldout) == 6000 and len({row["group_id"] for row in heldout}) == 6000, "held-out count drift")
    source_by_id = {row["group_id"]: row for row in heldout}
    cache = torch.load(EVAL_FEATURES, map_location="cpu", weights_only=True)
    state = cache["features"]["state"][FEATURE_KEY].to(DEVICE)
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(DEVICE)
    direct: dict[str, Any] = {}
    for seed_index, seed in enumerate(SEEDS):
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
            for epoch in (1, 2, 3):
                checkpoint = torch.load(run_dir / f"checkpoint-epoch-{epoch}.pt", map_location="cpu", weights_only=True)
                head = probe.CompatibilityHead(2048, "mlp", 128).to(DEVICE)
                head.load_state_dict(checkpoint["head_state"])
                head.eval()
                scored = scorer.score_groups(head, heldout, state, candidates, PROFILE, DEVICE, batch_size=1024)
                enriched = enrich(scored, source_by_id)
                groups = analysis.collect_triplets(enriched)
                flat = [pair for family in sorted(groups) for pair in groups[family]]
                metrics = analysis.analyze_triplets(enriched)
                metrics["conditional_locality"] = conditional_locality(flat)
                metrics["family_counts"] = {family: len(groups[family]) for family in sorted(groups)}
                direct[f"seed-{seed_index + 1}/{arm}/epoch-{epoch}"] = {"seed": seed, "arm": arm, "epoch": epoch, "analysis": metrics}

    write_json(RUN / "reports/direct-contrast-by-arm-seed-epoch.json", direct)
    paired = {}
    for seed_index, seed in enumerate(SEEDS):
        for epoch in (1, 2, 3):
            dup = direct[f"seed-{seed_index + 1}/K-DUP/epoch-{epoch}"]["analysis"]
            sham = direct[f"seed-{seed_index + 1}/K-SHAM/epoch-{epoch}"]["analysis"]
            paired[f"seed-{seed_index + 1}/epoch-{epoch}"] = {"seed": seed, "epoch": epoch, "SHAM_minus_DUP": {"strict_transition": sham["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"] - dup["fact_flip"]["overall"]["map_response"]["strict_old_to_new_transition_rate"], "sham_l1": sham["sham_invariance"]["overall"]["mean_prediction_distribution_l1"] - dup["sham_invariance"]["overall"]["mean_prediction_distribution_l1"], "sham_map_flip": sham["sham_invariance"]["overall"]["map_flip_rate"] - dup["sham_invariance"]["overall"]["map_flip_rate"]}}
    terminal = {key: value for key, value in direct.items() if value["epoch"] == 3}
    write_json(RUN / "reports/paired-effects.json", {"protocol": sealed["contract"]["protocol"], "status": "COMPLETE", "by_seed_epoch": paired, "terminal_by_run": terminal})
    write_json(RUN / "reports/family-transfer.json", {"protocol": sealed["contract"]["protocol"], "status": "COMPLETE", "terminal_by_run": {key: value["analysis"]["fact_flip"]["by_family"] for key, value in terminal.items()}})
    write_json(RUN / "reports/post-training-direct-integrity.json", {"status": "POST_TRAINING_DIRECT_EVALUATION_COMPLETE", "protocol": sealed["contract"]["protocol"], "evaluation_unlock_sha256": sha256_file(RUN / "reports/evaluation-unlock.json"), "heldout_groups": 6000, "heldout_pairs": 2000, "runs_scored": 6, "epochs_scored": 3, "predictions_scored": 18, "heldout_source_sha256": heldout_hash, "phoenix_access": False})
    print(json.dumps({"status": "POST_TRAINING_DIRECT_EVALUATION_COMPLETE", "runs_scored": 6, "epochs_scored": 3}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
