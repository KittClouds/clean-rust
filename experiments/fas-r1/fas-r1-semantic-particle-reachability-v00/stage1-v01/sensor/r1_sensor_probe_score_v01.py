"""Score locked R1 Stage 1 predictions and apply the frozen rung gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import numpy as np

from r1_sensor_probe_data_v01 import ACTION_ORDER, CONDITION_BY_VARIANT, KIND_ORDER, SLOT_ORDER, read_jsonl
from r1_sensor_probe_fit_v01 import ARMS, CONDITIONS, EXECUTION_CONTRACT, SEEDS, balanced_accuracy, binary_f1, sha256_file, write_json_new


def load_predictions(root: Path, rung: str) -> tuple[dict[tuple[int, str], dict[str, Any]], str]:
    rung_dir = root / rung
    lock_path = rung_dir / "PREDICTION-LOCK.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if lock.get("rung") != rung or lock.get("fit_count") != 12 or len(lock.get("files", [])) != 48:
        # Four files are locked per fit; the execution matrix is 3 seeds x 4 arms.
        raise ValueError("rung prediction lock has the wrong fit/file count")
    files = {(int(item["seed"]), item["arm"], Path(item["file"]).name): item for item in lock["files"]}
    outputs: dict[tuple[int, str], dict[str, Any]] = {}
    for seed in SEEDS:
        for arm in ARMS:
            directory = rung_dir / f"seed-{seed}" / arm
            for filename in ("fit-receipt.json", "weights.pt", "normalizer.npz", "evaluation-predictions.npz"):
                item = files[(seed, arm, filename)]
                path = root / item["file"]
                digest, size = sha256_file(path)
                if digest != item["sha256"] or size != item["bytes"]:
                    raise ValueError(f"locked output changed: {item['file']}")
            pred = np.load(directory / "evaluation-predictions.npz", allow_pickle=False)
            fit = json.loads((directory / "fit-receipt.json").read_text(encoding="utf-8"))
            keys = pred["row_keys"].astype(str)
            if len(set(keys.tolist())) != len(keys):
                raise ValueError(f"duplicate prediction keys for {seed}/{arm}")
            outputs[(seed, arm)] = {
                "keys": keys, "families": pred["families"].astype(str), "conditions": pred["conditions"].astype(str),
                "logits": pred["logits"].astype(np.float64), "fit": fit,
            }
    return outputs, sha256_file(lock_path)[0]


def _condition(variant: str) -> str:
    return CONDITION_BY_VARIANT.get(variant, "not_applicable")


def semantic_labels(data_root: Path) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    target = {}
    family = {}
    condition = {}
    for record in read_jsonl(data_root / "private-probe-targets.jsonl"):
        if record["split"] != "evaluation":
            continue
        variant = record["public_task_id"].split("__", 1)[1]
        cond = _condition(variant)
        for ci, clause in enumerate(record["clauses"]):
            key = f"{record['public_task_id']}|{ci}"
            target[key] = KIND_ORDER.index(clause["kind"])
            family[key] = record["family_id"]
            condition[key] = cond
    return target, family, condition


def _condition_metrics(y: np.ndarray, logits: np.ndarray, condition: np.ndarray, classes: int) -> dict[str, float]:
    result = {}
    pred = logits.argmax(axis=1)
    for cond in CONDITIONS:
        mask = condition == cond
        if not mask.any():
            result[cond] = float("nan")
        else:
            result[cond] = balanced_accuracy(y[mask], pred[mask], classes)
    return result


def score_semantic(root: Path, data_root: Path, outputs: dict[tuple[int, str], dict[str, Any]], lock_hash: str) -> dict[str, Any]:
    labels, families, conditions = semantic_labels(data_root)
    results: dict[str, Any] = {}
    pass_all = True
    for seed in SEEDS:
        results[str(seed)] = {}
        arm_metrics = {}
        for arm in ARMS:
            record = outputs[(seed, arm)]
            keys = record["keys"]
            if set(keys.tolist()) != set(labels):
                raise ValueError(f"semantic prediction key coverage mismatch for seed={seed}, arm={arm}")
            y = np.asarray([labels[key] for key in keys], dtype=np.int64)
            cond = np.asarray([conditions[key] for key in keys], dtype=str)
            arm_metrics[arm] = _condition_metrics(y, record["logits"], cond, 6)
        for cond in CONDITIONS:
            real = arm_metrics["real"][cond]
            shuffled = arm_metrics["shuffled"][cond]
            gate = real >= 0.90 and real - shuffled >= 0.20
            pass_all &= gate
            results[str(seed)][cond] = {"balanced_accuracy": arm_metrics["real"][cond],
                                        "shuffled_balanced_accuracy": shuffled,
                                        "surface_balanced_accuracy": arm_metrics["surface"][cond],
                                        "template_only_balanced_accuracy": arm_metrics["template"][cond],
                                        "real_minus_shuffled": real - shuffled, "gate_pass": gate}
    status = "PASS" if pass_all else "R1_SENSOR_FAIL_SEMANTIC"
    result = {"schema": "R1_SENSOR_SEMANTIC_SCORE_V01", "status": status, "rung": "semantic",
              "prediction_lock_sha256": lock_hash, "seed_condition_scores": results,
              "evaluation_label_rows": len(labels), "evaluation_labels_opened_after_prediction_lock": True}
    write_json_new(root / "semantic" / "RUNG-SCORE.json", result)
    write_json_new(root / "semantic" / "RUNG-GATE.json", {"schema": "R1_SENSOR_RUNG_GATE_V01", "status": status,
                  "rung": "semantic", "score_sha256": sha256_file(root / "semantic" / "RUNG-SCORE.json")[0]})
    return result


def binding_truth(data_root: Path) -> tuple[dict[str, int], dict[str, str], dict[str, str]]:
    labels: dict[str, int] = {}
    families: dict[str, str] = {}
    conditions: dict[str, str] = {}
    for record in read_jsonl(data_root / "private-probe-targets.jsonl"):
        if record["split"] != "evaluation":
            continue
        variant = record["public_task_id"].split("__", 1)[1]
        cond = _condition(variant)
        for ci, clause in enumerate(record["clauses"]):
            for slot, candidate in clause["argument_slots"].items():
                slot_index = SLOT_ORDER.index(slot)
                candidate_count = 12 if slot.startswith("entity") else 4
                for candidate_index in range(candidate_count):
                    key = f"{record['public_task_id']}|{ci}|{slot_index}|{candidate_index}"
                    labels[key] = int(candidate_index == candidate)
                    families[key] = record["family_id"]
                    conditions[key] = cond
    return labels, families, conditions


def _f1_for_condition(record: dict[str, Any], labels: dict[str, int], cond_map: dict[str, str], threshold: float) -> tuple[float, float]:
    selected = [i for i, key in enumerate(record["keys"]) if key in labels and cond_map[key] in CONDITIONS]
    if not selected:
        return float("nan"), float("nan")
    keys = record["keys"][selected]
    y = np.asarray([labels[key] for key in keys], dtype=np.int64)
    logits = record["logits"][selected, 0]
    conditions = np.asarray([cond_map[key] for key in keys], dtype=str)
    f1s = {}
    top1 = {}
    for cond in CONDITIONS:
        rows = np.flatnonzero(conditions == cond)
        if rows.size == 0:
            f1s[cond] = float("nan")
            top1[cond] = float("nan")
            continue
        f1s[cond] = binary_f1(y[rows], logits[rows], threshold)
        groups: dict[str, list[int]] = {}
        for local_index in rows.tolist():
            parts = keys[local_index].split("|")
            groups.setdefault("|".join(parts[:3]), []).append(local_index)
        correct = total = 0
        for indices in groups.values():
            target_positions = [i for i in indices if y[i] == 1]
            if len(target_positions) != 1:
                raise ValueError("binding slot must have exactly one correct candidate")
            best = max(indices, key=lambda i: (logits[i], -int(keys[i].rsplit("|", 1)[1])))
            correct += int(best == target_positions[0])
            total += 1
        top1[cond] = correct / total
    return f1s, top1


def score_binding(root: Path, data_root: Path, outputs: dict[tuple[int, str], dict[str, Any]], lock_hash: str) -> dict[str, Any]:
    labels, families, conditions = binding_truth(data_root)
    results: dict[str, Any] = {}
    pass_all = True
    for seed in SEEDS:
        results[str(seed)] = {}
        values = {}
        for arm in ARMS:
            values[arm] = _f1_for_condition(outputs[(seed, arm)], labels, conditions,
                                             float(outputs[(seed, arm)]["fit"]["validation_threshold"]))
        for cond in CONDITIONS:
            real = values["real"][0][cond]
            shuffled = values["shuffled"][0][cond]
            surface = values["surface"][0][cond]
            gate = real >= 0.90 and real - shuffled >= 0.20 and real - surface >= 0.05
            pass_all &= gate
            results[str(seed)][cond] = {
                "micro_f1": real, "exact_slot_top1": values["real"][1][cond],
                "shuffled_micro_f1": shuffled, "surface_micro_f1": surface,
                "template_only_micro_f1": values["template"][0][cond],
                "real_minus_shuffled": real - shuffled, "real_minus_surface": real - surface,
                "gate_pass": gate,
            }
    status = "PASS" if pass_all else "R1_SENSOR_FAIL_BINDING"
    result = {"schema": "R1_SENSOR_BINDING_SCORE_V01", "status": status, "rung": "binding",
              "prediction_lock_sha256": lock_hash, "seed_condition_scores": results,
              "evaluable_candidate_rows": len(labels), "evaluation_labels_opened_after_prediction_lock": True}
    write_json_new(root / "binding" / "RUNG-SCORE.json", result)
    write_json_new(root / "binding" / "RUNG-GATE.json", {"schema": "R1_SENSOR_RUNG_GATE_V01", "status": status,
                  "rung": "binding", "score_sha256": sha256_file(root / "binding" / "RUNG-SCORE.json")[0]})
    return result


def _bootstrap_action_delta(seed: int, arm_logits: dict[str, np.ndarray],
                            eval_rows: list[dict[str, Any]], family_ids: np.ndarray) -> dict[str, Any]:
    y = np.asarray([ACTION_ORDER.index(row["target_sign"]) for row in eval_rows], dtype=np.int64)
    family = np.asarray([row["family_id"] for row in eval_rows], dtype=str)
    condition = np.asarray([row["condition"] for row in eval_rows], dtype=str)
    unique = np.asarray(sorted(set(family.tolist())), dtype=str)
    if set(unique.tolist()) != set(family_ids.tolist()):
        raise ValueError("action bootstrap family universe mismatch")
    family_index = {fam: i for i, fam in enumerate(unique.tolist())}
    family_rows = np.asarray([family_index[fam] for fam in family.tolist()], dtype=np.int32)
    condition_index = {cond: i for i, cond in enumerate(CONDITIONS)}
    condition_rows = np.asarray([condition_index[cond] for cond in condition.tolist()], dtype=np.int32)
    confusion: dict[str, np.ndarray] = {}
    for arm, logits in arm_logits.items():
        pred = logits.argmax(axis=1).astype(np.int64)
        table = np.zeros((len(unique), len(CONDITIONS), 3, 3), dtype=np.int64)
        np.add.at(table, (family_rows, condition_rows, y, pred), 1)
        confusion[arm] = table
    rng_seed = int.from_bytes(hashlib.sha256(f"R1-ACTION-FAMILY-BOOTSTRAP-v1|{seed}".encode()).digest()[:8], "little")
    rng = np.random.default_rng(rng_seed)
    draws: list[float] = []
    invalid = 0
    for _ in range(2000):
        multiplicity = np.bincount(rng.integers(0, len(unique), size=len(unique)), minlength=len(unique))
        arm_mean: dict[str, float] = {}
        valid_draw = True
        for arm, table in confusion.items():
            aggregate = np.einsum("f,fcij->cij", multiplicity, table, optimize=True)
            recalls = np.diagonal(aggregate, axis1=1, axis2=2) / aggregate.sum(axis=2)
            if not np.isfinite(recalls).all():
                valid_draw = False
                break
            arm_mean[arm] = float(np.mean(recalls))
        if not valid_draw:
            invalid += 1
            continue
        control = max(arm_mean["shuffled"], arm_mean["surface"])
        draws.append(arm_mean["real"] - control)
    if not draws:
        raise ValueError("no valid family-cluster bootstrap replicates")
    low, high = np.quantile(np.asarray(draws), [0.025, 0.975])
    return {"replicates": 2000, "valid_replicates": len(draws), "invalid_replicates": invalid,
            "real_minus_best_control_ci95": [float(low), float(high)], "lower_excludes_zero": bool(low > 0)}


def action_truth(data_root: Path) -> list[dict[str, Any]]:
    public = read_jsonl(data_root / "public-probe-tasks.jsonl")
    variants_by_task: dict[str, list[dict[str, Any]]] = {}
    for task in public:
        variants_by_task.setdefault(task["id"].split("__", 1)[0], []).append(task)
    rows = []
    for record in read_jsonl(data_root / "private-action-examples.jsonl"):
        if record["split"] != "evaluation":
            continue
        variants = variants_by_task[record["task_id"]]
        for task in variants:
            variant = task["id"].split("__", 1)[1]
            condition = CONDITION_BY_VARIANT[variant]
            rows.append({**record, "variant": variant, "condition": condition, "edit_kind": "role_change"})
    return rows


def score_action(root: Path, data_root: Path, outputs: dict[tuple[int, str], dict[str, Any]], lock_hash: str) -> dict[str, Any]:
    truth_rows = action_truth(data_root)
    by_key = {}
    for row in truth_rows:
        key = f"{row['variant']}|{row['task_id']}|{row['state_index']}|{row['edit_entity']}|{row['new_role']}"
        by_key[key] = row
    results: dict[str, Any] = {}
    pass_all = True
    for seed in SEEDS:
        arm_data = {arm: outputs[(seed, arm)] for arm in ARMS}
        keys = arm_data["real"]["keys"]
        if keys.tolist() != list(by_key):
            raise ValueError(f"action prediction key order/coverage mismatch for seed {seed}")
        for arm in ARMS[1:]:
            if not np.array_equal(keys, arm_data[arm]["keys"]):
                raise ValueError(f"action arm row order mismatch for seed {seed}/{arm}")
        y = np.asarray([ACTION_ORDER.index(by_key[key]["target_sign"]) for key in keys], dtype=np.int64)
        family = np.asarray([by_key[key]["family_id"] for key in keys], dtype=str)
        cond = np.asarray([by_key[key]["condition"] for key in keys], dtype=str)
        arm_metrics = {}
        for arm in ARMS:
            logits = arm_data[arm]["logits"]
            arm_metrics[arm] = _condition_metrics(y, logits, cond, 3)
        real_mean = float(np.mean(list(arm_metrics["real"].values())))
        control_means = {arm: float(np.mean(list(arm_metrics[arm].values()))) for arm in ("shuffled", "surface")}
        bootstrap = _bootstrap_action_delta(seed, {arm: arm_data[arm]["logits"] for arm in ("real", "shuffled", "surface")},
                                            truth_rows, np.unique(family))
        condition_gates = {condition: arm_metrics["real"][condition] >= 0.55 for condition in CONDITIONS}
        seed_gate = (real_mean >= 0.60 and all(condition_gates.values())
                     and all(real_mean - value >= 0.10 for value in control_means.values())
                     and bootstrap["lower_excludes_zero"])
        pass_all &= seed_gate
        diagnostics = action_diagnostics(keys, y, arm_data["real"]["logits"], by_key)
        results[str(seed)] = {
            "condition_balanced_accuracy": arm_metrics["real"],
            "shuffled_condition_balanced_accuracy": arm_metrics["shuffled"],
            "surface_condition_balanced_accuracy": arm_metrics["surface"],
            "template_only_condition_balanced_accuracy": arm_metrics["template"],
            "equal_weight_mean_balanced_accuracy": real_mean,
            "control_equal_weight_means": control_means,
            "real_minus_control_mean": {arm: real_mean - value for arm, value in control_means.items()},
            "family_cluster_bootstrap": bootstrap,
            "condition_gates": condition_gates, "seed_gate_pass": seed_gate,
            "difficulty_diagnostics": diagnostics,
        }
    status = "PASS" if pass_all else "R1_SENSOR_FAIL_ACTION_RELEVANCE"
    result = {"schema": "R1_SENSOR_ACTION_SCORE_V01", "status": status, "rung": "action",
              "prediction_lock_sha256": lock_hash, "seed_scores": results,
              "heldout_action_rows": len(truth_rows), "evaluation_labels_opened_after_prediction_lock": True}
    write_json_new(root / "action" / "RUNG-SCORE.json", result)
    write_json_new(root / "action" / "RUNG-GATE.json", {"schema": "R1_SENSOR_RUNG_GATE_V01", "status": status,
                  "rung": "action", "score_sha256": sha256_file(root / "action" / "RUNG-SCORE.json")[0]})
    return result


def action_diagnostics(keys: np.ndarray, y: np.ndarray, logits: np.ndarray, truth: dict[str, dict[str, Any]]) -> dict[str, Any]:
    pred = logits.argmax(axis=1)
    output: dict[str, Any] = {}
    fields = ("nearest_solution_hamming", "violations_before", "role_anonymous", "n", "edit_kind")
    decoded = [truth[key] for key in keys]
    for field in fields:
        groups: dict[str, list[int]] = {}
        for index, row in enumerate(decoded):
            groups.setdefault(str(row[field]), []).append(index)
        output[field] = {}
        for value, indices in groups.items():
            idx = np.asarray(indices, dtype=np.int64)
            try:
                score = balanced_accuracy(y[idx], pred[idx], 3)
            except ValueError:
                score = None
            output[field][value] = {"rows": int(idx.size), "balanced_accuracy": score}
    return output


def score(args: argparse.Namespace) -> int:
    outputs, lock_hash = load_predictions(args.output, args.rung)
    lock = json.loads((args.output / args.rung / "PREDICTION-LOCK.json").read_text(encoding="utf-8"))
    if args.source_lock is None or sha256_file(args.source_lock)[0] != lock["source_lock_sha256"]:
        raise ValueError("frozen source lock changed")
    source_lock = json.loads(args.source_lock.read_text(encoding="utf-8"))
    source_sidecar = args.source_lock.with_suffix(".sha256").read_text(encoding="ascii").split()[0].lower()
    if sha256_file(args.source_lock)[0] != source_sidecar:
        raise ValueError("probe execution manifest SHA-256 sidecar mismatch")
    if source_lock.get("execution_contract") != EXECUTION_CONTRACT:
        raise ValueError("score source execution contract mismatch")
    for rel, expected in source_lock["sources"].items():
        digest, _ = sha256_file(Path(__file__).parent / rel)
        if digest != expected:
            raise ValueError(f"scoring source drift: {rel}")
    row_audit_path = Path(source_lock["row_audit_receipt_path"])
    if sha256_file(row_audit_path)[0] != source_lock["row_audit_receipt_sha256"]:
        raise ValueError("pre-fit row audit receipt drift")
    if args.manifest is not None:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        if sha256_file(args.manifest)[0] != lock["manifest_sha256"]:
            raise ValueError("qualification manifest changed after fitting")
        key = "private_action_examples" if args.rung == "action" else "private_probe_targets"
        truth = manifest["prepared_inputs"][key]
        frozen_root = Path(manifest["prepared_inputs"]["root"]).resolve(strict=True)
        if args.data_root.resolve(strict=True) != frozen_root:
            raise ValueError("scorer data root differs from frozen qualification input root")
        digest, size = sha256_file(frozen_root / truth["path"])
        if digest != truth["sha256"] or size != truth["bytes"]:
            raise ValueError("held-out truth input drift")
    if args.rung == "semantic":
        result = score_semantic(args.output, args.data_root, outputs, lock_hash)
    elif args.rung == "binding":
        result = score_binding(args.output, args.data_root, outputs, lock_hash)
    else:
        result = score_action(args.output, args.data_root, outputs, lock_hash)
    print(json.dumps({"rung": args.rung, "status": result["status"], "score_sha256": sha256_file(args.output / args.rung / "RUNG-SCORE.json")[0]}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--source-lock", type=Path)
    parser.add_argument("--rung", choices=("semantic", "binding", "action"), required=True)
    args = parser.parse_args()
    try:
        return score(args)
    except Exception as error:
        print(f"R1_SENSOR_PROBE_SCORE_STOP: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
