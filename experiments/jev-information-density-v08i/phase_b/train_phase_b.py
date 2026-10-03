"""Paired frozen-head training for the v0.8I F100 versus S100 intervention."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE_B = Path(__file__).resolve().parent
CONTRACT_PATH = PHASE_B / "phase-b-v01-contract.json"
RUN = Path(r"D:\codex-runs\jev-information-density-v08i\phase-b-v01")
PHASE_A = Path(r"D:\codex-runs\jev-information-density-v08i\phase-a-v02-clean")
PHASE_A_MAT = PHASE_A / "materialized"
INPUTS = RUN / "inputs"
FEATURES_PATH = RUN / "feature-cache/phase-b-train-features.pt"
FEATURE_RECEIPT_PATH = RUN / "feature-cache/extraction-receipt.json"
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
EPOCHS = 3
BATCH_SIZE = 256
BRIER_WEIGHT = 0.25
INVARIANCE_WEIGHT = 0.10
SEEDS = [20260927, 20260928, 20260929]
SCHEDULE = [(0, "S100"), (0, "F100"), (1, "F100"), (1, "S100"), (2, "S100"), (2, "F100")]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            line = json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            stream.write(line)
            digest.update(line.encode("utf-8"))
    temp.replace(path)
    return digest.hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen helper: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_frozen_modules() -> tuple[Any, Any, Any, Any, Any]:
    probe = load_module("jev_phase_b_probe", ROOT / "experiments/jev-frozen-readout-v01/probe.py")
    trainer = load_module("jev_phase_b_v05_trainer", ROOT / "experiments/jev-frozen-scaling-v05/train_v05.py")
    v08g = load_module("jev_phase_b_v08g_reference", ROOT / "experiments/jev-information-density-v08g/train_v08g.py")
    v08g_analysis = load_module("jev_phase_b_v08g_analysis", ROOT / "experiments/jev-information-density-v08g/analyze_v08g.py")
    direct_analysis = load_module("jev_phase_b_direct_analysis", PHASE_B / "analyze_phase_b.py")
    return probe, trainer, v08g, v08g_analysis, direct_analysis


def verify_frozen_code(auth: dict[str, Any]) -> None:
    for relative, expected in auth["source_code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"frozen implementation drift: {relative}")


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode("utf-8"))
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def initialize_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temp)
    temp.replace(path)


def verify_authorization() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = read_json(CONTRACT_PATH)
    contract_hash = sha256_file(CONTRACT_PATH)
    auth_path = RUN / "preflight/model-contact-authorization.json"
    auth = read_json(auth_path)
    if auth.get("status") != "PASS" or auth.get("model_contact_authorized") is not True:
        raise RuntimeError("Phase-B model-contact authorization is absent")
    if auth.get("contract_sha256") != contract_hash:
        raise RuntimeError("Phase-B contract changed after preflight")
    verify_frozen_code(auth)
    for arm in ("S100", "F100"):
        bank_path = PHASE_A_MAT / f"{arm}-groups.jsonl"
        expected = contract["phase_a_seal"][f"{arm}_sha256"]
        if sha256_file(bank_path) != expected or auth["verified_phase_a_sha256"].get(f"{arm}_sha256") != expected:
            raise RuntimeError(f"sealed Phase-A {arm} bank hash changed before training")
    input_receipt = read_json(INPUTS / "phase-b-inputs-receipt.json")
    if input_receipt.get("contract_sha256") != contract_hash:
        raise RuntimeError("Phase-B inputs are bound to another contract")
    for item in input_receipt["input_tables"].values():
        if sha256_file(Path(item["path"])) != item["sha256"]:
            raise RuntimeError(f"Phase-B input changed: {item['path']}")
    feature_receipt = read_json(FEATURE_RECEIPT_PATH)
    if feature_receipt.get("status") != "FEATURE_EXTRACTION_COMPLETE":
        raise RuntimeError("frozen Phase-B features are incomplete")
    if feature_receipt.get("contract_sha256") != contract_hash:
        raise RuntimeError("feature cache contract binding mismatch")
    if feature_receipt["feature_cache"].get("sha256") != sha256_file(FEATURES_PATH):
        raise RuntimeError("Phase-B frozen feature cache hash mismatch")
    return contract, auth, {"inputs": input_receipt, "features": feature_receipt}


def load_data(probe: Any, v08g: Any, v08g_analysis: Any, direct_analysis: Any,
              device: str) -> dict[str, Any]:
    contract, auth, receipts = verify_authorization()
    contract_hash = sha256_file(CONTRACT_PATH)
    cache = torch.load(FEATURES_PATH, map_location="cpu", weights_only=True)
    if cache.get("revision") != contract["model"]["revision"] or cache.get("hidden_dim") != 2048:
        raise RuntimeError("Phase-B training features have the wrong backbone identity/shape")
    if cache.get("backbone_frozen") is not True or cache.get("layer_count") != 16:
        raise RuntimeError("Phase-B feature cache does not certify frozen final-layer features")
    state = cache["features"]["state"][FEATURE_KEY]
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY]
    if state.dtype != torch.float32 or candidates.dtype != torch.float32:
        raise RuntimeError("head feature tensors are not float32")

    groups = {
        "S100": read_jsonl(PHASE_A_MAT / "S100-groups.jsonl"),
        "F100": read_jsonl(PHASE_A_MAT / "F100-groups.jsonl"),
    }
    for arm, rows in groups.items():
        rows.sort(key=lambda row: row["group_id"])
        if len(rows) != 100_000 or len({row["group_id"] for row in rows}) != 100_000:
            raise RuntimeError(f"{arm} occurrence count or ID uniqueness drifted")
        if any(row.get("split") != "train" or row.get("open_world") for row in rows):
            raise RuntimeError(f"{arm} contains an unsupported training row")
        for row in rows:
            if int(row["state_idx"]) >= state.shape[0]:
                raise RuntimeError(f"{arm} state index out of feature-cache bounds")
            indices = row["candidate_indices"][PROFILE]
            if len(indices) != len(row["candidate_semantic_ids"]) or any(int(i) >= candidates.shape[0] for i in indices):
                raise RuntimeError(f"{arm} candidate index/alignment error: {row['group_id']}")

    direct_eval = read_jsonl(Path(receipts["inputs"]["input_tables"]["heldout_groups"]["path"]))
    if len(direct_eval) != 6_000:
        raise RuntimeError("held-out direct contrast rows changed after materialization")
    by_pair: dict[str, set[str]] = {}
    for row in direct_eval:
        by_pair.setdefault(row["contrast_anchor_id"], set()).add(row["contrast_role"])
        if int(row["state_idx"]) >= state.shape[0]:
            raise RuntimeError("held-out contrast state index outside feature cache")
        indices = row["candidate_indices"][PROFILE]
        if len(indices) != len(row["candidate_semantic_ids"]) or any(int(i) >= candidates.shape[0] for i in indices):
            raise RuntimeError("held-out contrast candidate index/alignment error")
    if len(by_pair) != 2_000 or any(roles != {"anchor", "fact_flip", "sham"} for roles in by_pair.values()):
        raise RuntimeError("held-out contrast triplet structure is incomplete")

    # Reuse only the sealed v0.8G evaluation materialization and matching,
    # revision-bound frozen feature caches; discard its old training arms.
    reference_data = v08g.load_run_data()
    evaluation = reference_data["evaluation"]
    legacy_groups = reference_data["legacy_groups"]
    legacy_cache = reference_data["legacy_cache"]
    binding_cache = reference_data["binding_cache"]
    binding_groups = reference_data["binding_groups"]
    reference_cache = reference_data["cache"]
    del reference_data["groups"]
    del reference_data

    # Verify the invariant constraints are identical across the matched arms.
    invariant_s = probe.invariant_pairs(groups["S100"], "train")
    invariant_f = probe.invariant_pairs(groups["F100"], "train")
    key = lambda pair: (pair[0]["group_id"], pair[1]["group_id"])
    if [key(pair) for pair in invariant_s] != [key(pair) for pair in invariant_f]:
        raise RuntimeError("S100/F100 L3 surface-invariance pair lists differ")

    return {
        "contract": contract, "contract_sha256": contract_hash, "authorization": auth,
        "input_receipt": receipts["inputs"], "feature_receipt": receipts["features"],
        "cache": cache, "groups": groups, "direct_evaluation": direct_eval,
        "reference_cache": reference_cache, "evaluation": evaluation,
        "legacy_cache": legacy_cache, "legacy_groups": legacy_groups,
        "binding_cache": binding_cache, "binding_groups": binding_groups,
        "v08g_analysis": v08g_analysis,
        "direct_analysis": direct_analysis,
        "invariant_pair_count": len(invariant_s),
    }


def append_prediction_file(path: Path, rows: list[dict[str, Any]]) -> str:
    return write_jsonl(path, rows)


def fit_one(data: dict[str, Any], probe: Any, trainer: Any, seed_index: int,
            arm: str, device: str) -> dict[str, Any]:
    seed = SEEDS[seed_index]
    run_name = f"seed-{seed_index + 1}/{arm}"
    run_dir = RUN / "runs" / f"seed-{seed_index + 1}" / arm
    run_dir.mkdir(parents=True, exist_ok=True)
    groups = data["groups"][arm]
    feature_sha = data["feature_receipt"]["feature_cache"]["sha256"]
    config = {
        "contract_sha256": data["contract_sha256"], "seed": seed, "arm": arm,
        "feature_cache_sha256": feature_sha,
        "train_groups_sha256": data["authorization"]["verified_phase_a_sha256"][f"{arm}_sha256"],
        "head": "dynamic_mlp_compatibility", "projection_width": 128,
        "candidate_profile": PROFILE, "loss": "L3_source_typed",
        "brier_weight": BRIER_WEIGHT, "invariance_weight": INVARIANCE_WEIGHT,
        "epochs": EPOCHS, "batch_size_groups": BATCH_SIZE,
        "optimizer": "AdamW", "learning_rate": 0.002, "weight_decay": 0.01,
        "scheduler": "none", "gradient_clipping": "none",
        "training_order": "sort group_id then random.Random(seed+zero_based_epoch).shuffle",
        "candidate_order_augmentation": "v0.8G fast_tensor_batch(reorder=True)",
        "invariant_pair_count": data["invariant_pair_count"],
    }
    config_hash = sha256_json(config)
    config_path = run_dir / "run-config.json"
    if config_path.exists() and read_json(config_path) != {**config, "config_sha256": config_hash}:
        raise RuntimeError(f"immutable run config drifted: {run_name}")
    if not config_path.exists():
        write_json(config_path, {**config, "config_sha256": config_hash})
    final_path = run_dir / "run-report.json"
    if final_path.exists():
        report = read_json(final_path)
        if report.get("config_sha256") != config_hash or report.get("status") != "COMPLETE":
            raise RuntimeError(f"existing run report does not match frozen config: {run_name}")
        return report

    cache = data["cache"]
    state = cache["features"]["state"][FEATURE_KEY].to(device)
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
    initialize_seed(seed)
    head = probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(device)
    initial_sha = score_digest(head.state_dict())
    counterpart = "F100" if arm == "S100" else "S100"
    counterpart_path = RUN / "runs" / f"seed-{seed_index + 1}" / counterpart / "run-report.json"
    if counterpart_path.exists() and read_json(counterpart_path).get("initial_head_sha256") != initial_sha:
        raise RuntimeError(f"paired initialization mismatch for seed {seed_index + 1}")
    optimizer = torch.optim.AdamW(head.parameters(), lr=0.002, weight_decay=0.01)
    pairs = probe.invariant_pairs(groups, "train")
    history: list[dict[str, Any]] = []
    next_epoch = 0
    latest = run_dir / "latest-checkpoint.pt"
    if latest.exists():
        saved = torch.load(latest, map_location=device, weights_only=False)
        if saved.get("config_sha256") != config_hash or saved.get("initial_head_sha256") != initial_sha:
            raise RuntimeError(f"checkpoint binding mismatch: {run_name}")
        head.load_state_dict(saved["head_state"])
        optimizer.load_state_dict(saved["optimizer_state"])
        history = saved["history"]
        next_epoch = int(saved["next_epoch"])
        if "torch_rng" in saved:
            torch.set_rng_state(saved["torch_rng"].cpu())
        if device.startswith("cuda") and saved.get("cuda_rng") is not None:
            torch.cuda.set_rng_state_all(saved["cuda_rng"])

    events = run_dir / "training-events.jsonl"
    start_all = time.perf_counter()
    append_event(events, {"event": "run_start_or_resume", "run": run_name, "seed": seed,
                          "next_epoch": next_epoch + 1, "groups": len(groups),
                          "initial_head_sha256": initial_sha, "config_sha256": config_hash,
                          "timestamp_unix": time.time()})
    for epoch in range(next_epoch, EPOCHS):
        epoch_start = time.perf_counter()
        shuffled = list(groups)
        random.Random(seed + epoch).shuffle(shuffled)
        head.train()
        totals: Counter[str] = Counter()
        step_count = 0
        append_event(events, {"event": "epoch_start", "run": run_name, "epoch": epoch + 1})
        for start in range(0, len(shuffled), BATCH_SIZE):
            step_start = time.perf_counter()
            batch = shuffled[start : start + BATCH_SIZE]
            state_batch, candidate_batch, gold, mask, kinds, sources = trainer.fast_tensor_batch(
                batch, state, candidates, PROFILE, device, reorder=True,
            )
            optimizer.zero_grad(set_to_none=True)
            logits = head(state_batch, candidate_batch)
            semantic_plus_brier, brier = trainer.v05_loss(logits, gold, mask, kinds, sources, BRIER_WEIGHT)
            invariance = trainer.vectorized_invariant_loss(
                head, pairs, state, candidates, PROFILE, device,
            )
            loss = semantic_plus_brier + INVARIANCE_WEIGHT * invariance
            loss.backward()
            grads = [parameter.grad.detach().norm(2) for parameter in head.parameters() if parameter.grad is not None]
            grad_norm = float(torch.linalg.vector_norm(torch.stack(grads), 2).detach().cpu()) if grads else 0.0
            optimizer.step()
            count = len(batch)
            totals["count"] += count
            totals["loss"] += float(loss.detach().cpu()) * count
            totals["semantic_plus_brier"] += float(semantic_plus_brier.detach().cpu()) * count
            totals["brier"] += float(brier.detach().cpu()) * count
            totals["invariance"] += float(invariance.detach().cpu()) * count
            step_count += 1
            append_event(events, {
                "event": "training_step", "run": run_name, "epoch": epoch + 1,
                "step": step_count, "steps_in_epoch": math.ceil(len(shuffled) / BATCH_SIZE),
                "groups": count, "examples_processed": start + count,
                "loss": float(loss.detach().cpu()),
                "semantic_plus_brier": float(semantic_plus_brier.detach().cpu()),
                "brier": float(brier.detach().cpu()), "invariance": float(invariance.detach().cpu()),
                "gradient_norm": grad_norm, "learning_rate": optimizer.param_groups[0]["lr"],
                "groups_per_second": count / max(1e-9, time.perf_counter() - step_start),
                "cuda_allocated_bytes": int(torch.cuda.memory_allocated()) if device.startswith("cuda") else 0,
                "cuda_reserved_bytes": int(torch.cuda.memory_reserved()) if device.startswith("cuda") else 0,
            })

        train_summary = {key: totals[key] / max(1, totals["count"])
                         for key in ("loss", "semantic_plus_brier", "brier", "invariance")}
        train_summary.update({"groups": totals["count"], "optimizer_steps": step_count})
        head.eval()
        direct_rows = data["direct_evaluation"]
        direct_predictions = data["reference_cache"]  # marker only; direct cache is Phase-B cache below
        del direct_predictions
        direct_scored = data["probe_score_groups"](
            head, direct_rows, state, candidates, PROFILE, device,
        )
        for source, prediction in zip(direct_rows, direct_scored):
            prediction.update({
                "contrast_anchor_id": source["contrast_anchor_id"],
                "contrast_role": source["contrast_role"],
                "contrast_family_id": source["contrast_family_id"],
                "expected_old_winner_id": source["expected_old_winner_id"],
                "expected_new_winner_id": source["expected_new_winner_id"],
            })
        direct_path = run_dir / f"heldout-contrast-epoch-{epoch + 1}.jsonl"
        direct_sha = write_jsonl(direct_path, direct_scored)

        newtight_scored = data["probe_score_groups"](
            head, data["evaluation"],
            data["reference_cache"]["features"]["state"][FEATURE_KEY].to(device),
            data["reference_cache"]["features"]["candidate"][PROFILE][FEATURE_KEY].to(device),
            PROFILE, device,
        )
        newtight_metrics = data["typed_metrics"](newtight_scored)
        intervention_metrics = data["v08g_analysis"].intervention_report(newtight_scored)
        opaque_candidates = data["reference_cache"]["features"]["candidate"]["opaque_definition"][FEATURE_KEY].to(device)
        opaque_scored = data["probe_score_groups"](
            head, data["evaluation"],
            data["reference_cache"]["features"]["state"][FEATURE_KEY].to(device),
            opaque_candidates, "opaque_definition", device,
        )
        name_by_id = {row["group_id"]: row for row in newtight_scored}
        aligned_binding = [(name_by_id[row["group_id"]], row)
                           for row in opaque_scored if row["group_id"] in name_by_id]
        binding_drift = data["v08g"].distribution_drift(aligned_binding)
        legacy_metrics: dict[str, Any] = {}
        legacy_state = data["legacy_cache"]["features"]["state"][FEATURE_KEY].to(device)
        legacy_candidates = data["legacy_cache"]["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
        for split, eval_groups in data["legacy_groups"].items():
            scored = data["probe_score_groups"](head, eval_groups, legacy_state, legacy_candidates, PROFILE, device)
            legacy_metrics[split] = data["typed_metrics"](scored)
        epoch_record = {
            "epoch": epoch + 1, "train": train_summary,
            "direct_contrast": {"prediction_path": str(direct_path), "prediction_sha256": direct_sha,
                                "pair_count": 2_000, "group_count": len(direct_scored),
                                "analysis": data["direct_analysis"].analyze_triplets(direct_scored)},
            "new_tight_eval": newtight_metrics,
            "new_tight_schema_binding": {"name_definition_vs_opaque_definition": binding_drift},
            "new_tight_intervention_geometry": intervention_metrics,
            "legacy": legacy_metrics,
            "wall_seconds": time.perf_counter() - epoch_start,
            "elapsed_total_seconds": time.perf_counter() - start_all,
        }
        history.append(epoch_record)
        write_json(run_dir / f"epoch-{epoch + 1}.json", epoch_record)
        atomic_checkpoint(run_dir / f"epoch-{epoch + 1}-head.pt", {"head_state": head.state_dict(),
                                                                    "epoch": epoch + 1,
                                                                    "config_sha256": config_hash})
        atomic_checkpoint(latest, {
            "config_sha256": config_hash, "initial_head_sha256": initial_sha,
            "head_state": head.state_dict(), "optimizer_state": optimizer.state_dict(),
            "history": history, "next_epoch": epoch + 1,
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if device.startswith("cuda") else None,
        })
        append_event(events, {"event": "evaluation_snapshot", "run": run_name,
                              "epoch": epoch + 1, "direct_contrast_sha256": direct_sha,
                              "direct_contrast": epoch_record["direct_contrast"]["analysis"],
                              "new_tight_eval": newtight_metrics,
                              "schema_binding": binding_drift,
                              "intervention_geometry": intervention_metrics,
                              "legacy": legacy_metrics})
        append_event(events, {"event": "checkpoint", "run": run_name, "epoch": epoch + 1,
                              "checkpoint_sha256": sha256_file(latest)})
        print(json.dumps({"run": run_name, "epoch": epoch + 1,
                          "train_loss": train_summary["loss"],
                          "direct_predictions": str(direct_path),
                          "newtight_source_counts": newtight_metrics,
                          "elapsed_seconds": round(epoch_record["elapsed_total_seconds"], 1)},
                         separators=(",", ":")), flush=True)

    if len(history) != EPOCHS:
        raise RuntimeError(f"incomplete epoch history: {run_name}")
    final_direct_path = run_dir / "heldout-contrast-epoch-3.jsonl"
    direct_final = read_jsonl(final_direct_path)
    newtight_final = data["probe_score_groups"](
        head, data["evaluation"],
        data["reference_cache"]["features"]["state"][FEATURE_KEY].to(device),
        data["reference_cache"]["features"]["candidate"][PROFILE][FEATURE_KEY].to(device),
        PROFILE, device,
    )
    legacy_state = data["legacy_cache"]["features"]["state"][FEATURE_KEY].to(device)
    legacy_candidates = data["legacy_cache"]["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
    dev_rows = data["probe_score_groups"](head, data["legacy_groups"]["dev"], legacy_state,
                                          legacy_candidates, PROFILE, device)
    temperature = probe.fit_temperature(dev_rows)
    legacy_report: dict[str, Any] = {}
    for split, eval_groups in data["legacy_groups"].items():
        scored = dev_rows if split == "dev" else data["probe_score_groups"](
            head, eval_groups, legacy_state, legacy_candidates, PROFILE, device,
        )
        legacy_report[split] = {
            "raw": data["typed_metrics"](scored),
            "temperature_scaled": data["typed_metrics"](probe.temperature_rows(scored, temperature)),
        }

    reference_cache = data["reference_cache"]
    all_profiles = data["profile_metrics"](
        head, data["evaluation"], reference_cache, device,
        ("name", "name_definition", "opaque_definition", "opaque_only"),
    )
    binding_cache = data["binding_cache"]
    binding_rows = data["probe_score_groups"](
        head, data["binding_groups"],
        binding_cache["features"]["state"][FEATURE_KEY].to(device),
        binding_cache["features"]["candidate"]["opaque_definition"][FEATURE_KEY].to(device),
        "opaque_definition", device,
    )
    head_path = run_dir / "head.pt"
    torch.save(head.state_dict(), head_path)
    write_jsonl(run_dir / "newtight-final-predictions.jsonl", newtight_final)
    write_jsonl(run_dir / "binding-final-predictions.jsonl", binding_rows)
    report = {
        "status": "COMPLETE", "protocol": data["contract"]["protocol"],
        "run": run_name, "arm": arm, "seed_index": seed_index + 1, "seed": seed,
        "config_sha256": config_hash, "initial_head_sha256": initial_sha,
        "head_sha256": sha256_file(head_path),
        "trainable_parameters": sum(parameter.numel() for parameter in head.parameters()),
        "training_occurrences": len(groups),
        "unique_training_group_ids": len({group["group_id"] for group in groups}),
        "invariant_pair_count": len(pairs), "epochs": EPOCHS, "history": history,
        "primary_direct_contrast": {
            "terminal_epoch": 3,
            "pair_count": 2_000,
            "family_counts": data["input_receipt"]["heldout_family_counts"],
            "prediction_path": str(final_direct_path),
            "prediction_sha256": sha256_file(final_direct_path),
            "analysis": "see post-hoc direct contrast report; no score-based tuning",
        },
        "secondary_newtight_eval": {
            "raw": data["typed_metrics"](newtight_final),
            "temperature_scaled": data["typed_metrics"](probe.temperature_rows(newtight_final, temperature)),
            "temperature": temperature,
            "temperature_fit_scope": "legacy_dev_exact_generative_posterior_only",
            "prediction_path": str(run_dir / "newtight-final-predictions.jsonl"),
        },
        "legacy_evaluation": legacy_report,
        "schema_profiles_newtight": all_profiles,
        "contradictory_binding": {
            "profile": "opaque_definition", "metrics": data["typed_metrics"](binding_rows),
            "prediction_path": str(run_dir / "binding-final-predictions.jsonl"),
        },
        "backbone_frozen": True,
        "phoenix_access": False,
        "runtime": {"elapsed_seconds": time.perf_counter() - start_all,
                    "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if device.startswith("cuda") else 0},
    }
    write_json(final_path, report)
    append_event(events, {"event": "run_complete", "run": run_name,
                          "report_sha256": sha256_file(final_path)})
    return report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--only-seed", type=int, choices=(1, 2, 3), default=None)
    args = parser.parse_args()
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    probe, trainer, v08g, v08g_analysis, direct_analysis = load_frozen_modules()
    data = load_data(probe, v08g, v08g_analysis, direct_analysis, args.device)
    data["probe_score_groups"] = v08g.score_groups
    data["typed_metrics"] = v08g.typed_metrics
    data["profile_metrics"] = v08g.profile_metrics
    data["v08g"] = v08g
    allowed_seed_index = None if args.only_seed is None else args.only_seed - 1
    completed = []
    for seed_index, arm in SCHEDULE:
        if allowed_seed_index is not None and seed_index != allowed_seed_index:
            continue
        report = fit_one(data, probe, trainer, seed_index, arm, args.device)
        completed.append({"seed": report["seed"], "arm": arm,
                          "report_sha256": sha256_file(RUN / "runs" / f"seed-{seed_index + 1}" / arm / "run-report.json")})
    summary_path = RUN / "reports/training-execution-summary.json"
    write_json(summary_path, {
        "status": "ALL_SCHEDULED_RUNS_COMPLETE" if allowed_seed_index is None else "SEED_SUBSET_COMPLETE",
        "contract_sha256": data["contract_sha256"], "schedule_results": completed,
        "configured_schedule": [[f"seed-{index + 1}", arm] for index, arm in SCHEDULE],
        "backbone_frozen": True, "phoenix_access": False,
    })
    print(json.dumps({"status": "TRAINING_COMPLETE", "runs_completed": len(completed),
                      "summary": str(summary_path)}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
