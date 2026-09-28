from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
BANK = ROOT / "bank" / "construction-01" / "scored-bank-a14"
SOURCE = BANK / "vault" / "task-source-fixtures-final-v3.json"
CHECKS = BANK / "vault" / "candidate-check-labels-final-v3.json"
FRAMES = BANK / "observer-frames.json"
TRUTH = BANK / "vault" / "frame-truth-index.json"
OUTPUT = BANK / "vault" / "nuisance-baselines-a17-v1.json"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def balanced_accuracy(labels: list[bool], predictions: list[bool]) -> float:
    positive = [index for index, label in enumerate(labels) if label]
    negative = [index for index, label in enumerate(labels) if not label]
    if not positive or not negative:
        return 0.0
    sensitivity = sum(predictions[index] for index in positive) / len(positive)
    specificity = sum(not predictions[index] for index in negative) / len(negative)
    return round((sensitivity + specificity) / 2, 4)


def lofo_category_baseline(rows: list[dict[str, Any]], field: str, label_key: str) -> dict[str, Any]:
    families = sorted({row["family"] for row in rows})
    all_labels: list[bool] = []
    all_predictions: list[bool] = []
    folds = []
    for heldout in families:
        train = [row for row in rows if row["family"] != heldout]
        test = [row for row in rows if row["family"] == heldout]
        counts: dict[str, Counter[bool]] = defaultdict(Counter)
        global_counts = Counter(row[label_key] for row in train)
        default = global_counts[True] > global_counts[False]
        for row in train:
            counts[str(row[field] if field in row else row["value"])][row[label_key]] += 1
        labels = [row[label_key] for row in test]
        predictions = [
            (counts[str(row[field])][True] > counts[str(row[field])][False])
            if str(row[field]) in counts else default
            for row in test
        ]
        all_labels.extend(labels)
        all_predictions.extend(predictions)
        folds.append({
            "heldout_family": heldout,
            "test_rows": len(test),
            "balanced_accuracy": balanced_accuracy(labels, predictions),
            "accuracy": round(sum(a == b for a, b in zip(labels, predictions, strict=True)) / len(labels), 4) if labels else None,
        })
    return {
        "split": "leave-one-task-family-out",
        "rows": len(all_labels),
        "balanced_accuracy": balanced_accuracy(all_labels, all_predictions),
        "accuracy": round(sum(a == b for a, b in zip(all_labels, all_predictions, strict=True)) / len(all_labels), 4),
        "majority_baseline_accuracy": round(max(sum(all_labels), len(all_labels) - sum(all_labels)) / len(all_labels), 4),
        "folds": folds,
    }


def lexical_tokens(frame: dict[str, Any], channel_names: set[str]) -> list[str]:
    text: list[str] = []
    if "E_t" in channel_names:
        text.append(frame["task_prompt"])
    if "E_c" in channel_names:
        for option in frame["action_options"]:
            text.extend((option["summary"], option["diff_excerpt"]))
    if "E_x" in channel_names:
        text.append(frame["evidence"][0]["content"])
    if "E_r" in channel_names:
        text.append(frame["evidence"][1]["content"])
    words = re.findall(r"[a-z0-9_]+", " ".join(text).lower())
    return words + [f"{left}__{right}" for left, right in zip(words, words[1:])]


def train_nb(rows: list[dict[str, Any]]) -> tuple[dict[bool, Counter[str]], Counter[bool], Counter[bool]]:
    token_counts: dict[bool, Counter[str]] = {False: Counter(), True: Counter()}
    totals: Counter[bool] = Counter()
    docs: Counter[bool] = Counter()
    for row in rows:
        label = row["valid"]
        docs[label] += 1
        token_counts[label].update(row["tokens"])
        totals[label] += len(row["tokens"])
    return token_counts, totals, docs


def nb_log_odds(
    tokens: list[str], fitted: tuple[dict[bool, Counter[str]], Counter[bool], Counter[bool]]
) -> float:
    token_counts, totals, docs = fitted
    vocabulary = set(token_counts[False]) | set(token_counts[True])
    if not vocabulary or not docs[False] or not docs[True]:
        return 0.0
    alpha = 1.0
    score = math.log((docs[True] + alpha) / (docs[False] + alpha))
    denominator_pos = totals[True] + alpha * (len(vocabulary) + 1)
    denominator_neg = totals[False] + alpha * (len(vocabulary) + 1)
    token_freq = Counter(token for token in tokens if token in vocabulary)
    for token, count in token_freq.items():
        pos = math.log((token_counts[True][token] + alpha) / denominator_pos)
        neg = math.log((token_counts[False][token] + alpha) / denominator_neg)
        score += count * (pos - neg)
    return score


def lexical_lofo(
    rows_by_task: dict[str, dict[str, Any]], candidate_rows: list[dict[str, Any]],
    channel_names: set[str],
) -> dict[str, Any]:
    families = sorted({row["family"] for row in candidate_rows})
    all_labels: list[bool] = []
    all_predictions: list[bool] = []
    selected_actions = 0
    completed_action_tasks = 0
    correct_action_tasks = 0
    abstention_tasks = 0
    correct_abstentions = 0
    for heldout in families:
        train = [row for row in candidate_rows if row["family"] != heldout]
        test = [row for row in candidate_rows if row["family"] == heldout]
        model = train_nb(train)
        predictions: dict[str, list[tuple[float, dict[str, Any]]]] = defaultdict(list)
        for row in test:
            score = nb_log_odds(row["tokens"], model)
            prediction = score > 0.0
            all_labels.append(row["valid"])
            all_predictions.append(prediction)
            predictions[row["task_id"]].append((score, row))
        for task_id, choices in predictions.items():
            choices.sort(key=lambda item: (-item[0], item[1]["position"]))
            top_score, top = choices[0]
            has_valid = any(item["valid"] for _, item in choices)
            if has_valid:
                completed_action_tasks += 1
                if top_score > 0.0:
                    selected_actions += 1
                    correct_action_tasks += int(top["valid"])
            else:
                abstention_tasks += 1
                correct_abstentions += int(top_score <= 0.0)
    task_count = completed_action_tasks + abstention_tasks
    return {
        "split": "leave-one-task-family-out",
        "channels": sorted(channel_names),
        "candidate_binary_balanced_accuracy": balanced_accuracy(all_labels, all_predictions),
        "candidate_binary_accuracy": round(sum(a == b for a, b in zip(all_labels, all_predictions, strict=True)) / len(all_labels), 4),
        "candidate_majority_accuracy": round(max(sum(all_labels), len(all_labels) - sum(all_labels)) / len(all_labels), 4),
        "action_tasks": completed_action_tasks,
        "selected_action_tasks": selected_actions,
        "correct_top_action_tasks": correct_action_tasks,
        "abstention_tasks": abstention_tasks,
        "correct_abstentions": correct_abstentions,
        "task_completion": round((correct_action_tasks + correct_abstentions) / task_count, 4) if task_count else None,
        "task_count": task_count,
    }


def verify_nuisance_lock() -> None:
    lock_path = ROOT / "bank" / "construction-01" / "nuisance-audit-lock-a17-v1.json"
    if not lock_path.is_file():
        raise SystemExit("A17 nuisance audit lock is missing")
    lock = read_json(lock_path)
    if lock.get("state") != "FROZEN_BEFORE_A17_NUISANCE_AUDIT" or lock.get("model_contact_authorized") is not False:
        raise SystemExit("A17 nuisance audit lock state is invalid")
    if lock.get("audit_sha256") != sha256(Path(__file__).read_bytes()):
        raise SystemExit("A17 nuisance audit script drifted after lock")
    for item in lock["files"]:
        path = ROOT / Path(item["path"])
        if not path.is_file() or sha256(path.read_bytes()) != item["sha256"]:
            raise SystemExit(f"A17 nuisance audit input drift: {item['path']}")


def main() -> None:
    verify_nuisance_lock()
    if OUTPUT.exists():
        raise SystemExit("refusing to overwrite nuisance baseline audit")
    source = read_json(SOURCE)
    raw_checks = read_json(CHECKS)
    frames = read_json(FRAMES)["frames"]
    truth = read_json(TRUTH)
    full: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    for frame, label in zip(frames, truth, strict=True):
        if label["condition"] == "full_frame":
            full[label["task_id"]] = (frame, label)
    task_by_id = {task["task_id"]: task for task in source["tasks_hidden"]}
    label_by_task: dict[str, set[int]] = {
        task_id: {int(value) for value in task["expected_valid_action_ids_hidden"]}
        for task_id, task in task_by_id.items()
    }
    candidate_rows: list[dict[str, Any]] = []
    task_rows: list[dict[str, Any]] = []
    pure_value_report: dict[str, Any] = {}
    fields = (
        "action_id", "position", "patch_sha256", "task_id", "family_code", "repository_code", "candidate_bytes",
        "candidate_32byte_bin", "evidence_count", "execution_bytes", "execution_word_count",
        "execution_status_signature", "task_prompt_bytes", "task_prompt_word_count", "task_variant",
    )
    feature_rows: dict[str, list[dict[str, Any]]] = {field: [] for field in fields}
    frame_by_task: dict[str, dict[str, Any]] = {}
    for task_id, (frame, entry) in full.items():
        frame_by_task[task_id] = frame
        task = task_by_id[task_id]
        task_label = task["direct_decision_hidden"] == "ACT"
        task_features = {
            "task_id": task_id,
            "family": task["family_name_hidden"],
            "repository_id": task["repository_id_hidden"],
            "family_code": frame["task_family"],
            "repository_code": frame["repository_id"],
            "direct_action": task_label,
            "task_prompt_bytes": len(frame["task_prompt"].encode("utf-8")),
            "task_prompt_word_count": len(re.findall(r"\w+", frame["task_prompt"])),
            "evidence_count": len(frame["evidence"]),
            "task_variant": frame["task_variant"],
        }
        task_rows.append(task_features)
        execution = frame["evidence"][0]["content"]
        status_terms = ("failed", "failure", "error", "assertion", "observed", "reference", "passed", "expected")
        status_signature = "+".join(term for term in status_terms if term in execution.lower()) or "none"
        for position, option in enumerate(frame["action_options"]):
            action_id = int(option["action"]["id"])
            candidate_text = option["summary"] + "\n" + option["diff_excerpt"]
            candidate_row = {
                "task_id": task_id,
                "family": task["family_name_hidden"],
                "valid": action_id in label_by_task[task_id],
                "action_id": action_id,
                "position": position,
                "patch_sha256": option["patch_sha256"],
                "candidate_bytes": len(candidate_text.encode("utf-8")),
                "candidate_32byte_bin": len(candidate_text.encode("utf-8")) // 32,
                "family_code": frame["task_family"],
                "repository_code": frame["repository_id"],
                "evidence_count": len(frame["evidence"]),
                "execution_bytes": len(execution.encode("utf-8")),
                "execution_word_count": len(re.findall(r"\w+", execution)),
                "execution_status_signature": status_signature,
                "task_prompt_bytes": task_features["task_prompt_bytes"],
                "task_prompt_word_count": task_features["task_prompt_word_count"],
                "task_variant": frame["task_variant"],
                "frame": frame,
            }
            candidate_rows.append(candidate_row)
            for field in fields:
                feature_rows[field].append({
                    "family": candidate_row["family"],
                    "value": candidate_row[field],
                    "valid": candidate_row["valid"],
                })

    for field, rows in feature_rows.items():
        categories: dict[str, Counter[bool]] = defaultdict(Counter)
        for row in rows:
            categories[str(row["value"])][row["valid"]] += 1
        pure = [
            {"value": value, "rows": sum(counts.values()), "label": next(iter(counts))}
            for value, counts in categories.items() if len(counts) == 1 and sum(counts.values()) >= 2
        ]
        pure_value_report[field] = {
            "repeated_values": sum(sum(counts.values()) >= 2 for counts in categories.values()),
            "repeated_single_label_values": pure,
            "leave_one_family_out": lofo_category_baseline(rows, field, "valid"),
        }

    task_feature_report = {
        field: lofo_category_baseline(task_rows, field, "direct_action")
        for field in ("repository_code", "family_code", "task_prompt_bytes", "task_prompt_word_count", "evidence_count", "task_variant")
    }
    lexical_rows_by_channels: dict[str, list[dict[str, Any]]] = {}
    for channel_set in (
        {"E_c"}, {"E_t", "E_c"}, {"E_c", "E_x"}, {"E_c", "E_r"}, {"E_t", "E_c", "E_x", "E_r"},
    ):
        key = "+".join(sorted(channel_set))
        rows = []
        for candidate in candidate_rows:
            option = next(
                item for item in candidate["frame"]["action_options"]
                if int(item["action"]["id"]) == candidate["action_id"]
            )
            # Use the option-specific candidate text together with only the selected task channels.
            frame = candidate["frame"]
            subset = dict(frame)
            subset["action_options"] = [option]
            rows.append({
                "task_id": candidate["task_id"],
                "family": candidate["family"],
                "valid": candidate["valid"],
                "position": candidate["position"],
                "tokens": lexical_tokens(subset, channel_set),
            })
        lexical_rows_by_channels[key] = rows
    lexical_results = {
        key: lexical_lofo(
            {task_id: task_rows for task_id, task_rows in task_by_id.items()},
            rows,
            set(key.split("+")),
        )
        for key, rows in lexical_rows_by_channels.items()
    }

    result = {
        "schema_version": 1,
        "state": "A17_NUISANCE_BASELINE_AUDIT_COMPLETE_NO_MODEL_CONTACT",
        "model_contact_authorized": False,
        "task_count": len(full),
        "candidate_rows": len(candidate_rows),
        "input_hashes": {
            "final_task_source_sha256": sha256(SOURCE.read_bytes()),
            "derived_candidate_labels_sha256": sha256(CHECKS.read_bytes()),
            "observer_frames_sha256": sha256(FRAMES.read_bytes()),
            "truth_index_sha256": sha256(TRUTH.read_bytes()),
        },
        "categorical_nuisance_feature_audits": pure_value_report,
        "task_level_family_grouped_audits": task_feature_report,
        "lexical_naive_bayes_leave_one_family_out": lexical_results,
        "interpretation_boundary": "descriptive construction diagnostics; no model outputs or tuning",
    }
    OUTPUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": result["state"], "tasks": len(full), "candidate_rows": len(candidate_rows),
        "lexical_conditions": len(lexical_results), "output": str(OUTPUT),
    }, indent=2))


if __name__ == "__main__":
    main()
