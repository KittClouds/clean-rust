from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
BANK = ROOT / "bank/construction-01/scored-bank-a14"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def summary(rows: list[dict]) -> dict:
    accepted = [row for row in rows if row["small_accepted"]]
    complete = [row for row in rows if row["small_completed"]]
    return {
        "samples": len(rows),
        "small_accepted": len(accepted),
        "small_direct_correct": sum(row["small_completed"] for row in accepted),
        "small_direct_wrong": sum(not row["small_completed"] for row in accepted),
        "small_abstained_or_rejected": len(rows) - len(accepted),
        "large_completed": sum(row["large_completed"] for row in rows),
        "hybrid_completed": sum(row["hybrid_completed"] for row in rows),
        "small_direct_precision": (
            sum(row["small_completed"] for row in accepted) / len(accepted)
            if accepted else None
        ),
    }


def main() -> None:
    baseline_path = RUN / "reports/full-frame-baseline-report.json"
    baseline = read_json(baseline_path)
    eval_labels = read_json(RUN / "vault/evaluation-labels.json")
    frames = read_json(RUN / "inputs/full-frame-lock.json")
    source_labels = read_json(BANK / "vault/candidate-check-labels-final-v3.json")
    source_by_task: dict[str, dict[int, dict]] = defaultdict(dict)
    for row in source_labels["candidate_rows"]:
        source_by_task[row["task_id"]][row["action_id_hidden"]] = row

    truth_by_sample = {row["sample_id"]: row for row in eval_labels["tasks"]}
    frame_by_sample = {row["sample_id"]: row for row in frames["frames"]}
    rows = []
    label_differences = []
    output_audit = Counter()
    direct_errors = []
    for detail in baseline["tasks"]:
        sample_id = detail["sample_id"]
        truth = truth_by_sample[sample_id]
        frame_entry = frame_by_sample[sample_id]
        outcomes = {row["action_id"]: row for row in truth["candidate_outcomes"]}
        passed_ids = {action_id for action_id, row in outcomes.items() if row["task_candidate_passed"]}
        valid_ids = set(truth["expected_valid_action_ids"])
        if passed_ids != valid_ids:
            label_differences.append({
                "sample_id": sample_id,
                "test_passed_action_ids": sorted(passed_ids),
                "sealed_expected_valid_action_ids": sorted(valid_ids),
            })

        small = detail["lanes"]["small_only"]
        large = detail["lanes"]["large_only"]
        hybrid = detail["lanes"]["hybrid"]
        raw_small = read_json(RUN / "outputs/small" / f"{sample_id}.json")
        raw_large = read_json(RUN / "outputs/large" / f"{sample_id}.json")
        output_audit["small_http_200"] += int(raw_small.get("http_status") == 200)
        output_audit["large_http_200"] += int(raw_large.get("http_status") == 200)
        output_audit["small_normalization_errors"] += int(raw_small.get("normalization_error") is not None)
        output_audit["large_normalization_errors"] += int(raw_large.get("normalization_error") is not None)
        output_audit["presentation_verified"] += int(small["presentation_verified"] and large["presentation_verified"] and hybrid["presentation_verified"])
        output_audit["replay_identical"] += int(small["replay_state_identical"] and large["replay_state_identical"] and hybrid["replay_state_identical"])

        raw_choice = (raw_small.get("normalized_output") or {}).get("action_choice")
        option_index = next(
            (index for index, option in enumerate(frame_entry["frame"]["action_options"])
             if option["action"]["id"] == raw_choice),
            None,
        )
        source_row = source_by_task[truth["internal_task_id"]].get(raw_choice) if raw_choice is not None else None
        candidate_outcome = outcomes.get(raw_choice, {})
        row = {
            "sample_id": sample_id,
            "task_id": detail["task_id"],
            "pair_id": truth["pair_id"],
            "repository_id": detail["repository"],
            "repository": truth["repository"],
            "family": truth["family"],
            "stratum": truth["stratum"],
            "small_accepted": small["accepted"],
            "small_completed": small["completed"],
            "small_wrong_legal": small["wrong_legal_action"],
            "small_raw_choice": raw_choice,
            "small_applicability_milli": (raw_small.get("normalized_output") or {}).get("applicability_milli"),
            "small_abstention_milli": (raw_small.get("normalized_output") or {}).get("abstention_milli"),
            "small_candidate_position_zero_based": option_index,
            "small_candidate_role": source_row.get("candidate_role_hidden") if source_row else None,
            "small_choice_in_expected_valid_set": raw_choice in valid_ids if type(raw_choice) is int else False,
            "small_choice_passed_executable_checks": bool(candidate_outcome.get("task_candidate_passed", False)),
            "large_accepted": large["accepted"],
            "large_completed": large["completed"],
            "large_raw_choice": (raw_large.get("normalized_output") or {}).get("action_choice"),
            "hybrid_completed": hybrid["completed"],
            "hybrid_selected_role": detail["hybrid_selected_role"],
        }
        rows.append(row)
        if small["accepted"] and not small["completed"]:
            direct_errors.append(row)

    dimensions = {}
    for field in ("repository_id", "repository", "family", "stratum"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[str(row[field])].append(row)
        dimensions[field] = {key: summary(group) for key, group in sorted(groups.items())}

    accepted_small = [row for row in rows if row["small_accepted"]]
    score_bins = {
        "850-899": lambda value: value is not None and 850 <= value < 900,
        "900-949": lambda value: value is not None and 900 <= value < 950,
        "950-999": lambda value: value is not None and 950 <= value < 1000,
        "1000": lambda value: value == 1000,
    }
    by_score = {}
    for name, predicate in score_bins.items():
        group = [row for row in accepted_small if predicate(row["small_applicability_milli"])]
        by_score[name] = {
            "accepted": len(group),
            "completed": sum(row["small_completed"] for row in group),
            "wrong_legal": sum(row["small_wrong_legal"] for row in group),
            "precision": sum(row["small_completed"] for row in group) / len(group) if group else None,
        }

    by_position: dict[str, dict] = {}
    for position in range(4):
        group = [row for row in accepted_small if row["small_candidate_position_zero_based"] == position]
        by_position[str(position)] = {
            "accepted": len(group),
            "completed": sum(row["small_completed"] for row in group),
            "wrong_legal": sum(row["small_wrong_legal"] for row in group),
            "precision": sum(row["small_completed"] for row in group) / len(group) if group else None,
        }

    completion_matrix = Counter()
    for row in rows:
        completion_matrix[f"small_{'done' if row['small_completed'] else 'not_done'}__large_{'done' if row['large_completed'] else 'not_done'}"] += 1

    report = {
        "schema_version": 1,
        "state": "FULL_FRAME_BASELINE_AUTOPSY_COMPLETE",
        "run_id": RUN_ID,
        "baseline_report_sha256": sha256(baseline_path),
        "frozen_input_lock_sha256": baseline["frozen_input_lock_sha256"],
        "label_consistency": {
            "tasks_checked": len(rows),
            "passed_candidate_set_mismatches": label_differences,
            "mismatch_count": len(label_differences),
        },
        "raw_output_and_authority_audit": dict(output_audit),
        "pooled": summary(rows),
        "by": dimensions,
        "small_accepted_by_applicability": by_score,
        "small_accepted_by_candidate_position": by_position,
        "small_large_completion_matrix": dict(completion_matrix),
        "small_direct_errors": direct_errors,
        "admission_gate": baseline["admission_gate"],
        "interpretation": (
            "The frozen small observer does not meet the preregistered direct-action admission gate "
            "if executable checks and sealed valid-action sets agree and the response/authority audit is clean."
        ),
        "next_step_boundary": (
            "Do not run E012 channel interventions unless the label-consistency and output/authority audit "
            "reveal a repairable engineering defect. The failed action-region gate alone is not a reason to tune."
        ),
    }
    out = RUN / "reports/full-frame-baseline-autopsy-v1.json"
    if out.exists():
        raise SystemExit("refusing to replace the baseline autopsy")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "state": report["state"],
        "label_mismatches": len(label_differences),
        "small_accepted": len(accepted_small),
        "small_correct": sum(row["small_completed"] for row in accepted_small),
        "small_wrong": len(direct_errors),
        "small_wrong_action_in_expected_valid_set": sum(row["small_choice_in_expected_valid_set"] for row in direct_errors),
        "small_normalization_errors": output_audit["small_normalization_errors"],
        "large_normalization_errors": output_audit["large_normalization_errors"],
        "authority_cases_clean": output_audit["presentation_verified"] == 48 and output_audit["replay_identical"] == 48,
    }, indent=2))


if __name__ == "__main__":
    main()

