#!/usr/bin/env python3
"""Read-only descriptive anatomy for the sealed E012 run.

Reads sealed inputs, labels, scored report, and raw observer outputs. Writes only to
this addendum directory. No model/API calls, fitting, threshold search, or mutations
of the E012 run are performed.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

EXPECTED_RUN = "e012-20260926-frame-decomposition-01"
RUN_DIR = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012\artifacts\runs\e012-20260926-frame-decomposition-01")
OUT_DIR = Path(r"C:\rd-c\selective-cognition-action-region-program\e012-readonly-anatomy-addendum")
INPUTS = (
    "frozen-input-lock.json",
    "inputs/full-frame-lock.json",
    "vault/evaluation-labels.json",
    "reports/full-frame-baseline-report.json",
    "reports/full-frame-baseline-autopsy-v1.json",
)

def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def file_hash(path: Path) -> str:
    return sha256(path.read_bytes())

def json_load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def file_manifest(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): file_hash(p)
            for p in sorted(root.rglob("*")) if p.is_file()}

def rate(n: int, d: int) -> float | None:
    return n / d if d else None

def pct(n: int, d: int) -> str:
    return "n/a" if not d else f"{100*n/d:.1f}%"

def get_lane(task: dict, role: str) -> dict:
    return task["lanes"][f"{role}_only"]

def correctness_record(task: dict, label: dict, frame: dict, raw: dict, role: str) -> dict:
    valid_ids = {int(x) for x in label["expected_valid_action_ids"]}
    output = raw.get("normalized_output") or {}
    choice = output.get("action_choice")
    choice = int(choice) if choice is not None else None
    options = frame.get("action_options", [])
    id_to_pos = {int(o["action"]["id"]): i for i, o in enumerate(options)}
    id_to_patch = {int(o["action"]["id"]): o["patch_sha256"] for o in options}
    accepted = bool(get_lane(task, role)["accepted"])
    chosen_valid = choice in valid_ids if choice is not None else False
    return {
        "choice": choice,
        "patch": id_to_patch.get(choice) if choice is not None else None,
        "position": id_to_pos.get(choice) if choice is not None else None,
        "accepted": accepted,
        "proposal_present": choice is not None,
        "proposal_correct": chosen_valid if choice is not None else None,
        "accepted_correct": chosen_valid if accepted and choice is not None else None,
        "accepted_wrong": bool(accepted and choice is not None and not chosen_valid),
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", type=Path, default=RUN_DIR)
    ap.add_argument("--out-dir", type=Path, default=OUT_DIR)
    args = ap.parse_args()
    run = args.run_dir.resolve()
    out = args.out_dir.resolve()
    if run == out or run in out.parents or out in run.parents:
        raise SystemExit("Refusing overlapping E012 and addendum paths")

    before_tree = file_manifest(run)
    missing = [rel for rel in INPUTS if not (run / rel).is_file()]
    if missing:
        raise SystemExit(f"Missing sealed sources: {missing}")
    source_hashes = {rel: file_hash(run / rel) for rel in INPUTS}
    lock = json_load(run / "frozen-input-lock.json")
    frame_lock = json_load(run / "inputs/full-frame-lock.json")
    labels_doc = json_load(run / "vault/evaluation-labels.json")
    scored = json_load(run / "reports/full-frame-baseline-report.json")
    autopsy = json_load(run / "reports/full-frame-baseline-autopsy-v1.json")
    if lock.get("run_id") != EXPECTED_RUN or scored.get("run_id") != EXPECTED_RUN:
        raise SystemExit("Unexpected E012 run identity")
    if scored.get("frozen_input_lock_sha256") != source_hashes["frozen-input-lock.json"]:
        raise SystemExit("E012 frozen input lock does not match scored report")
    if autopsy.get("baseline_report_sha256") != source_hashes["reports/full-frame-baseline-report.json"]:
        raise SystemExit("E012 autopsy does not bind the scored report")
    if frame_lock.get("frame_count") != 48 or labels_doc.get("task_count") != 48:
        raise SystemExit("Unexpected E012 sample count")

    frames = {x["sample_id"]: x["frame"] for x in frame_lock["frames"]}
    labels = {x["sample_id"]: x for x in labels_doc["tasks"]}
    tasks = {x["sample_id"]: x for x in scored["tasks"]}
    ids = set(frames)
    if ids != set(labels) or ids != set(tasks):
        raise SystemExit("Sample IDs differ among locked frame, labels, and report")

    raw_data: dict[str, dict[str, dict]] = {"small": {}, "large": {}}
    raw_hashes: dict[str, str] = {}
    for role in ("small", "large"):
        d = run / "outputs" / role
        raw_hashes[role] = sha256("".join(
            f"{p.name}:{file_hash(p)}\n" for p in sorted(d.glob("*.json"))
        ).encode())
        for sid in sorted(ids):
            p = d / f"{sid}.json"
            if not p.is_file():
                raise SystemExit(f"Missing {role} raw output for {sid}")
            x = json_load(p)
            if x.get("sample_id") != sid or x.get("role") != role:
                raise SystemExit(f"Raw output identity mismatch: {p}")
            raw_data[role][sid] = x

    rows: dict[str, dict[str, dict]] = {"small": {}, "large": {}}
    for sid in sorted(ids):
        for role in ("small", "large"):
            rows[role][sid] = correctness_record(
                tasks[sid], labels[sid], frames[sid], raw_data[role][sid], role)

    # A. Uniform candidate-choice baseline, reported both bank-wide and on
    # exactly the small observer's accepted subset. Empty valid sets are separate.
    candidate_ids = [sid for sid in sorted(ids) if labels[sid]["direct_decision"] == "ACT"]
    abstention_ids = [sid for sid in sorted(ids) if labels[sid]["direct_decision"] != "ACT"]
    def chance(sids: list[str]) -> dict:
        terms = []
        for sid in sids:
            k = len(frames[sid]["action_options"])
            v = len(set(map(int, labels[sid]["expected_valid_action_ids"])) &
                    {int(o["action"]["id"]) for o in frames[sid]["action_options"]})
            terms.append({"sample_id": sid, "valid": v, "offered": k, "chance": v / k if k else None})
        expected = sum(x["chance"] for x in terms if x["chance"] is not None)
        return {"n": len(terms), "expected_uniform_correct": expected,
                "expected_uniform_precision": rate(round(expected * 10**9), len(terms) * 10**9),
                "taskwise_valid_over_offered": terms}
    small_accepted_ids = [sid for sid in sorted(ids) if rows["small"][sid]["accepted"]]
    observed_correct_small_accepts = sum(bool(rows["small"][sid]["accepted_correct"]) for sid in small_accepted_ids)
    chance_all = chance(candidate_ids)
    chance_accepted = chance(small_accepted_ids)
    chance_accepted["observed_small_correct"] = observed_correct_small_accepts
    chance_accepted["observed_small_accepts"] = len(small_accepted_ids)
    chance_accepted["observed_small_precision"] = rate(observed_correct_small_accepts, len(small_accepted_ids))
    chance_accepted["precision_minus_uniform_expected"] = (
        chance_accepted["observed_small_precision"] - chance_accepted["expected_uniform_precision"]
        if chance_accepted["observed_small_precision"] is not None else None)
    # Exact reference tail under independent uniform candidate draws on these same tasks.
    probs = [x["chance"] for x in chance_accepted["taskwise_valid_over_offered"]]
    distribution = [1.0]
    for prob in probs:
        nxt = [0.0] * (len(distribution) + 1)
        for i, mass in enumerate(distribution):
            nxt[i] += mass * (1.0 - prob)
            nxt[i + 1] += mass * prob
        distribution = nxt
    chance_accepted["uniform_draw_reference_probability_at_least_observed_correct"] = sum(
        distribution[observed_correct_small_accepts:])
    chance_accepted["uniform_draw_reference_boundary"] = (
        "Exact Poisson-binomial tail under independent uniform choices; descriptive reference, not a promotion test.")

    # B. Candidate selection and pure-abstention tasks are reported separately.
    empty_split = {"candidate_selection_tasks": len(candidate_ids),
                   "pure_abstention_tasks": len(abstention_ids), "by_observer": {}}
    for role in ("small", "large"):
        empty_split["by_observer"][role] = {
            "candidate_tasks_accepted": sum(rows[role][sid]["accepted"] for sid in candidate_ids),
            "candidate_tasks_accepted_correct": sum(bool(rows[role][sid]["accepted_correct"]) for sid in candidate_ids),
            "candidate_tasks_accepted_wrong": sum(rows[role][sid]["accepted_wrong"] for sid in candidate_ids),
            "pure_abstention_tasks_accepted": sum(rows[role][sid]["accepted"] for sid in abstention_ids),
            "pure_abstention_false_accepts": sum(rows[role][sid]["accepted_wrong"] for sid in abstention_ids),
            "pure_abstention_correct_deferrals": sum(not rows[role][sid]["accepted"] for sid in abstention_ids),
        }

    # C. Descriptive accepted-action producer ordinal counts and error rate.
    position_bias: dict[str, dict] = {}
    for role in ("small", "large"):
        by_pos: dict[str, dict] = {}
        for sid in sorted(ids):
            rec = rows[role][sid]
            if rec["accepted"] and rec["position"] is not None:
                key = str(rec["position"])
                cell = by_pos.setdefault(key, {"accepted": 0, "correct": 0, "wrong": 0, "sample_ids": []})
                cell["accepted"] += 1
                cell["correct"] += int(bool(rec["accepted_correct"]))
                cell["wrong"] += int(rec["accepted_wrong"])
                cell["sample_ids"].append(sid)
        position_bias[role] = {"accepted_by_producer_ordinal_zero_based": by_pos,
                               "scope": "descriptive; no order policy is inferred"}

    # D. Pair responsiveness, only for pairs with the exact same ordered patch
    # sequence and a changed valid-patch set. All pairwise contrasts in a group
    # are retained; they are descriptive and not independent inferential units.
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for sid in sorted(ids):
        groups[labels[sid].get("pair_id", "")].append(sid)
    pair_summary = {"eligible_groups": 0, "eligible_contrasts": 0, "excluded_group_count": 0,
                    "observers": {}}
    contrasts = []
    for pair_id, group in sorted(groups.items()):
        if len(group) < 2:
            continue
        seqs = {sid: tuple(o["patch_sha256"] for o in frames[sid]["action_options"]) for sid in group}
        valid_patch_sets = {}
        for sid in group:
            valid_ids = set(map(int, labels[sid]["expected_valid_action_ids"]))
            valid_patch_sets[sid] = frozenset(o["patch_sha256"] for o in frames[sid]["action_options"]
                                                if int(o["action"]["id"]) in valid_ids)
        if len(set(seqs.values())) != 1 or len(set(valid_patch_sets.values())) < 2:
            pair_summary["excluded_group_count"] += 1
            continue
        pair_summary["eligible_groups"] += 1
        for i, left in enumerate(group):
            for right in group[i+1:]:
                if valid_patch_sets[left] == valid_patch_sets[right]:
                    continue
                pair_summary["eligible_contrasts"] += 1
                row = {"pair_id": pair_id, "left_sample": left, "right_sample": right,
                       "changed_valid_patch_sets": True, "patch_order_identical": True,
                       "left_valid_patch_count": len(valid_patch_sets[left]),
                       "right_valid_patch_count": len(valid_patch_sets[right]), "observers": {}}
                for role in ("small", "large"):
                    a, b = rows[role][left], rows[role][right]
                    ca, cb = a["patch"], b["patch"]
                    correct_a = ca in valid_patch_sets[left] if ca is not None else None
                    correct_b = cb in valid_patch_sets[right] if cb is not None else None
                    both_proposed = ca is not None and cb is not None
                    row["observers"][role] = {
                        "left_choice_patch": ca, "right_choice_patch": cb,
                        "left_accepted": a["accepted"], "right_accepted": b["accepted"],
                        "choice_changed": (ca != cb) if both_proposed else None,
                        "both_correct": bool(correct_a and correct_b),
                        "both_wrong": bool(correct_a is False and correct_b is False),
                        "one_correct": bool(correct_a != correct_b) if both_proposed else False,
                        "one_or_both_abstained": not both_proposed,
                    }
                contrasts.append(row)
    for role in ("small", "large"):
        items = [x["observers"][role] for x in contrasts]
        proposed = [x for x in items if not x["one_or_both_abstained"]]
        pair_summary["observers"][role] = {
            "both_correct_contrasts": sum(x["both_correct"] for x in items),
            "both_wrong_contrasts": sum(x["both_wrong"] for x in items),
            "exactly_one_correct_contrasts": sum(x["one_correct"] for x in items),
            "one_or_both_abstained_contrasts": sum(x["one_or_both_abstained"] for x in items),
            "both_proposed_choice_changed": sum(bool(x["choice_changed"]) for x in proposed),
            "both_proposed_contrasts": len(proposed),
        }
    pair_summary["contrast_details"] = contrasts
    pair_summary["interpretation_boundary"] = "Paired variants are descriptive response checks, not causal proof or independent samples."

    # E. Direct correctness overlap, plus the stricter wrong-accepted overlap.
    categories = collections.Counter()
    small_wrong = set()
    large_wrong = set()
    for sid in ids:
        s = rows["small"][sid]["accepted_correct"] is True
        l = rows["large"][sid]["accepted_correct"] is True
        categories["both_correct"] += int(s and l)
        categories["small_correct_only"] += int(s and not l)
        categories["large_correct_only"] += int(l and not s)
        categories["neither_accepted_correct"] += int(not s and not l)
        if rows["small"][sid]["accepted_wrong"]:
            small_wrong.add(sid)
        if rows["large"][sid]["accepted_wrong"]:
            large_wrong.add(sid)
    wrong_overlap = {"small_wrong_accepted": len(small_wrong), "large_wrong_accepted": len(large_wrong),
                     "both_wrong_accepted": len(small_wrong & large_wrong),
                     "small_only_wrong_accepted": len(small_wrong - large_wrong),
                     "large_only_wrong_accepted": len(large_wrong - small_wrong),
                     "small_wrong_sample_ids": sorted(small_wrong),
                     "large_wrong_sample_ids": sorted(large_wrong)}

    # The existing completion matrix is retained separately from semantic proposal correctness.
    completion_matrix = autopsy.get("small_large_completion_matrix", {})
    lane_completions = scored.get("lanes", {})
    outcomes = {"task_count": len(ids),
                "small_completed": lane_completions.get("small_only", {}).get("task_completion", {}).get("numerator"),
                "large_completed": lane_completions.get("large_only", {}).get("task_completion", {}).get("numerator"),
                "hybrid_completed": lane_completions.get("hybrid", {}).get("task_completion", {}).get("numerator"),
                "completion_matrix_from_sealed_autopsy": completion_matrix}

    result = {
        "schema_version": 1,
        "state": "E012_READONLY_ANATOMY_COMPLETE",
        "analysis_id": "e012-readonly-anatomy-addon-v1",
        "source_run_id": EXPECTED_RUN,
        "source_state": scored.get("state"),
        "no_model_contact": True,
        "no_fit_or_threshold_search": True,
        "source_hashes_sha256": source_hashes,
        "raw_output_tree_hashes_sha256": raw_hashes,
        "sample_count": len(ids),
        "diagnostics": {
            "A_chance_baseline": {"candidate_selection_tasks": chance_all,
                                  "small_accepted_subset": chance_accepted,
                                  "comparison_note": "Uniform random choice among offered candidates; descriptive expected precision, not a fitted baseline."},
            "B_empty_valid_set_split": empty_split,
            "C_producer_position_bias": position_bias,
            "D_pair_sensitivity": pair_summary,
            "E_small_large_error_overlap": {"accepted_proposal_correctness_partition": dict(categories),
                                            "wrong_acceptance_overlap": wrong_overlap,
                                            "task_completion_outcomes": outcomes},
            "F_fresh_positive_control": {"status": "DESIGN_ONLY_NOT_RUN",
                "reason": "Current stop boundary keeps model contact unauthorized.",
                "design_file": "E012-POSITIVE-CONTROL-DESIGN.md"},
        },
        "interpretation_boundary": [
            "This is post-outcome descriptive analysis of E012 only; no fitting, threshold selection, subgroup admission, or new capability claim.",
            "Candidate-choice chance assumes uniform choice over offered candidates and does not model an abstention strategy.",
            "Task completion and semantic proposal correctness are reported separately.",
            "Pair contrasts are not independent inferential units.",
        ],
    }
    # Verify no source bytes changed while reading.
    after_tree = file_manifest(run)
    if before_tree != after_tree:
        raise SystemExit("E012 tree changed during read-only analysis")
    out.mkdir(parents=True, exist_ok=True)
    (out / "E012-READONLY-ANATOMY-v1.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md = render_markdown(result)
    (out / "E012-READONLY-ANATOMY-v1.md").write_text(md, encoding="utf-8")
    sealed_addendum_files = (
        "analyze_e012_readonly.py",
        "E012-READONLY-ANATOMY-v1.json",
        "E012-READONLY-ANATOMY-v1.md",
        "E012-CLOSEOUT.md",
        "E012-POSITIVE-CONTROL-DESIGN.md",
    )
    manifest = {"analysis_id": result["analysis_id"], "source_run_id": EXPECTED_RUN,
                "state": "SEALED_READONLY_ADDENDUM_NO_MODEL_CONTACT",
                "model_contact_authorized": False,
                "source_tree_file_count": len(before_tree), "source_tree_sha256_by_path": before_tree,
                "source_hashes_sha256": source_hashes,
                "addendum_files_sha256": {name: file_hash(out / name) for name in sealed_addendum_files}}
    (out / "E012-READONLY-ANATOMY-SEAL-v1.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "samples": len(ids),
                      "addendum": str(out), "e012_tree_unchanged": True,
                      "seal": str(out / "E012-READONLY-ANATOMY-SEAL-v1.json")}, indent=2))

def render_markdown(r: dict) -> str:
    d = r["diagnostics"]
    a = d["A_chance_baseline"]
    b = d["B_empty_valid_set_split"]
    c = d["C_producer_position_bias"]
    p = d["D_pair_sensitivity"]
    e = d["E_small_large_error_overlap"]
    lines = ["# E012 Read-only Anatomy Addendum v1", "",
        f"State: `{r['state']}`  ", f"Source run: `{r['source_run_id']}`  ",
        "Model contact: **none**  ", "Fitting/threshold search: **none**  ",
        "E012 source run tree: verified unchanged after read.", "",
        "## A. Uniform candidate-choice baseline", "",
        f"Candidate-selection tasks: {a['candidate_selection_tasks']['n']}; expected uniform correct choices: "
        f"{a['candidate_selection_tasks']['expected_uniform_correct']:.2f} "
        f"({100*a['candidate_selection_tasks']['expected_uniform_precision']:.1f}% expected precision).",
        f"On the small observer's {a['small_accepted_subset']['observed_small_accepts']} accepted proposals, "
        f"observed correct: {a['small_accepted_subset']['observed_small_correct']} "
        f"({100*a['small_accepted_subset']['observed_small_precision']:.1f}%); "
        f"uniform-choice expected precision on those same tasks: "
        f"{100*a['small_accepted_subset']['expected_uniform_precision']:.1f}%. "
        f"Difference: {100*a['small_accepted_subset']['precision_minus_uniform_expected']:.1f} percentage points. "
        f"Under independent uniform choices on those exact tasks, P(at least 6 correct) = "
        f"{a['small_accepted_subset']['uniform_draw_reference_probability_at_least_observed_correct']:.3f}. "
        "This is a null-reference diagnostic, not an admission test; the sample is small.", "",
        "## B. Empty-valid-set split", "",
        f"Candidate-selection tasks: {b['candidate_selection_tasks']}; pure-abstention tasks: {b['pure_abstention_tasks']}.",
        "| Observer | Accepted on candidate tasks | Correct / wrong accepted | Accepted on pure-abstention tasks | Correct deferrals |",
        "|---|---:|---:|---:|---:|"]
    for role in ("small", "large"):
        x=b["by_observer"][role]
        lines.append(f"| {role} | {x['candidate_tasks_accepted']} | {x['candidate_tasks_accepted_correct']} / {x['candidate_tasks_accepted_wrong']} | {x['pure_abstention_tasks_accepted']} | {x['pure_abstention_correct_deferrals']} |")
    lines += ["", "## C. Accepted-action producer ordinal", "",
        "Descriptive counts by zero-based producer ordinal; no ordering policy is inferred.", ""]
    for role in ("small", "large"):
        lines.append(f"**{role}:** `{json.dumps(c[role]['accepted_by_producer_ordinal_zero_based'], sort_keys=True)}`")
    lines += ["", "## D. Pair sensitivity", "",
        f"Eligible fixed-patch-order groups: {p['eligible_groups']}; pairwise truth-changing contrasts: {p['eligible_contrasts']}.",
        "Each contrast changes the valid patch set while preserving the exact candidate patch sequence. Pair contrasts within a factorial group are dependent; results are descriptive.", ""]
    for role, x in p["observers"].items():
        lines.append(f"- **{role}:** both correct {x['both_correct_contrasts']}; both wrong {x['both_wrong_contrasts']}; exactly one correct {x['exactly_one_correct_contrasts']}; one or both abstained {x['one_or_both_abstained_contrasts']}; changed choice among both-proposed contrasts {x['both_proposed_choice_changed']}/{x['both_proposed_contrasts']}.")
    lines += ["", "## E. Small/large error overlap", "",
        "### Accepted proposal correctness", "",
        f"`{json.dumps(e['accepted_proposal_correctness_partition'], sort_keys=True)}`", "",
        "### Wrong accepted action overlap", "",
        f"`{json.dumps({k:v for k,v in e['wrong_acceptance_overlap'].items() if 'sample_ids' not in k}, sort_keys=True)}`", "",
        "### Task completion", "",
        f"`{json.dumps(e['task_completion_outcomes'], sort_keys=True)}`", "",
        "Proposal correctness and end-to-end task completion are distinct outcomes.", "",
        "## F. Fresh positive control", "",
        "**Designed, not run.** See `E012-POSITIVE-CONTROL-DESIGN.md`. Model contact remains unauthorized.", "",
        "## Source identities", "",
        "```json", json.dumps(r['source_hashes_sha256'], indent=2, sort_keys=True), "```", "",
        "## Boundaries", ""]
    lines.extend(f"- {x}" for x in r["interpretation_boundary"])
    return "\n".join(lines) + "\n"

if __name__ == "__main__":
    main()
