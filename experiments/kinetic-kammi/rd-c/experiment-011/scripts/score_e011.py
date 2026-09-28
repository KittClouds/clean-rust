from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011")
RUN_ID = "e011-20260925-causal-evidence-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
CONDITIONS = (
    "full-frame",
    "evidence-masked",
    "evidence-swapped",
    "repository-neutralized",
    "candidate-permuted",
)
ROLES = ("small", "large")
MIN_APP = 850
MAX_ABST = 150


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def mean(values: list[float]) -> float | None:
    return None if not values else round(sum(values) / len(values), 3)


def percent(numerator: int, denominator: int) -> str:
    return "n/a" if denominator == 0 else f"{100.0 * numerator / denominator:.1f}% ({numerator}/{denominator})"


def find_option_by_id(frame: dict, choice: object) -> dict | None:
    if type(choice) is not int:
        return None
    return next((option for option in frame["action_options"] if option["action"]["id"] == choice), None)


def load_baseline() -> tuple[dict[str, dict], dict[str, dict], dict[str, dict]]:
    source_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    source_frames = {item["frame"]["task_id"]: item["frame"] for item in source_lock["frames"]}
    labels = read_json(ROOT / "inputs/e010-heldout-sealed-labels.json")["tasks"]
    baseline: dict[str, dict] = {}
    for role in ROLES:
        directory = RUN / "full-frame-baseline" / role
        for task_id in source_frames:
            path = directory / f"{task_id}.json"
            if not path.is_file():
                raise RuntimeError(f"missing copied E010 baseline output: {path}")
            baseline[f"{role}:{task_id}"] = read_json(path)
    return source_frames, labels, baseline


def output_view(record: dict, frame: dict, labels_by_task: dict) -> dict:
    output = record.get("normalized_output")
    common = {
        "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
        "prompt_tokens": int(record.get("usage", {}).get("prompt_tokens", 0) or 0),
        "generated_tokens": int(record.get("usage", {}).get("completion_tokens", 0) or 0),
    }
    if not isinstance(output, dict):
        return {
            **common,
            "raw_patch": None,
            "raw_correct": False,
            "applicability_milli": None,
            "abstention_milli": None,
            "accepted": False,
            "decision": "invalid-output",
            "correct": False,
        }
    choice = output.get("action_choice")
    option = find_option_by_id(frame, choice)
    patch = option.get("patch_sha256") if option else None
    action_labels = labels_by_task["actions_by_patch_sha256"]
    raw_correct = bool(action_labels.get(patch, {}).get("expected_task_completion", False)) if patch else False
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    if type(app) is not int or type(abst) is not int:
        accepted, decision = False, "invalid-scores"
    elif choice is None:
        accepted, decision = False, "explicit-abstention"
    elif option is None:
        accepted, decision = False, "unknown-action"
    elif abst > MAX_ABST:
        accepted, decision = False, "abstention-threshold"
    elif app < MIN_APP:
        accepted, decision = False, "applicability-threshold"
    else:
        accepted, decision = True, "accepted"
    return {
        **common,
        "raw_patch": patch,
        "raw_correct": raw_correct,
        "applicability_milli": app if type(app) is int else None,
        "abstention_milli": abst if type(abst) is int else None,
        "accepted": accepted,
        "decision": decision,
        "correct": bool(accepted and raw_correct),
    }


def load_records(condition: str, source_frames: dict[str, dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    records: dict[str, dict] = {}
    frames = dict(source_frames)
    if condition == "full-frame":
        for role in ROLES:
            for task_id in source_frames:
                records[f"{role}:{task_id}"] = read_json(
                    RUN / "full-frame-baseline" / role / f"{task_id}.json"
                )
        return records, frames

    lock = read_json(RUN / f"frame-lock-{condition}.json")
    frames = {entry["pair_task_id"]: entry["frame"] for entry in lock["frames"]}
    for role in ROLES:
        directory = RUN / "outputs" / role / condition
        for path in directory.glob("*.json"):
            record = read_json(path)
            pair_id = record.get("pair_task_id")
            if not pair_id:
                raise RuntimeError(f"missing paired task ID in {path}")
            key = f"{role}:{pair_id}"
            if key in records:
                raise RuntimeError(f"duplicate paired output for {key}/{condition}")
            records[key] = record
    expected = len(source_frames) * len(ROLES)
    if len(records) != expected or len(frames) != len(source_frames):
        raise RuntimeError(f"{condition}: expected {expected} outputs and frames, got {len(records)} and {len(frames)}")
    return records, frames


def status(view: dict) -> str:
    if view["correct"]:
        return "correct"
    if view["accepted"]:
        return "wrong"
    return "relinquished"


def baseline_complementarity(
    repositories: dict[str, list[str]],
    source_frames: dict[str, dict],
    labels: dict[str, dict],
    baseline: dict[str, dict],
) -> dict:
    result: dict = {}
    for repository, task_ids in repositories.items():
        counts = Counter()
        for task_id in task_ids:
            frame = source_frames[task_id]
            small = output_view(baseline[f"small:{task_id}"], frame, labels[task_id])
            large = output_view(baseline[f"large:{task_id}"], frame, labels[task_id])
            large_wrong = large["accepted"] and not large["raw_correct"]
            small_relinquished_or_wrong = not small["accepted"] or not small["raw_correct"]
            counts["tasks"] += 1
            counts["large_wrong"] += int(large_wrong)
            counts["small_correct_given_large_wrong"] += int(large_wrong and small["correct"])
            counts["small_relinquished_or_wrong"] += int(small_relinquished_or_wrong)
            counts["large_correct_when_small_relinquished_or_wrong"] += int(
                small_relinquished_or_wrong and large["correct"]
            )
        result[repository] = {
            **dict(counts),
            "p_small_correct_given_large_wrong": {
                "numerator": counts["small_correct_given_large_wrong"],
                "denominator": counts["large_wrong"],
            },
            "p_large_correct_given_small_relinquished_or_wrong": {
                "numerator": counts["large_correct_when_small_relinquished_or_wrong"],
                "denominator": counts["small_relinquished_or_wrong"],
            },
        }
    return result


def paired_lane(
    condition: str,
    repository: str,
    task_ids: list[str],
    source_frames: dict[str, dict],
    condition_frames: dict[str, dict],
    labels: dict[str, dict],
    records: dict[str, dict],
    full_views: dict[str, dict[str, dict]],
) -> dict:
    n = len(task_ids)
    views: dict[str, dict[str, dict]] = {role: {} for role in ROLES}
    for role in ROLES:
        for task_id in task_ids:
            key = f"{role}:{task_id}"
            views[role][task_id] = output_view(records[key], condition_frames[task_id], labels[task_id])

    role_metrics: dict[str, dict] = {}
    role_transitions: dict[str, Counter] = {}
    for role in ROLES:
        counts = Counter()
        app_deltas: list[int] = []
        abst_deltas: list[int] = []
        transitions = Counter()
        for task_id in task_ids:
            current = views[role][task_id]
            full = full_views[role][task_id]
            counts["accepted"] += int(current["accepted"])
            counts["correct_accepted"] += int(current["correct"])
            counts["wrong_accepted"] += int(current["accepted"] and not current["raw_correct"])
            counts["raw_choice_correct"] += int(current["raw_correct"])
            counts["proposal_changed"] += int(current["raw_patch"] != full["raw_patch"])
            counts["threshold_acceptance_changed"] += int(current["accepted"] != full["accepted"])
            counts["baseline_correct_to_relinquished"] += int(full["correct"] and not current["accepted"])
            counts["baseline_wrong_commit_avoided"] += int(
                full["accepted"] and not full["raw_correct"] and not current["accepted"]
            )
            if current["applicability_milli"] is not None and full["applicability_milli"] is not None:
                app_deltas.append(current["applicability_milli"] - full["applicability_milli"])
            if current["abstention_milli"] is not None and full["abstention_milli"] is not None:
                abst_deltas.append(current["abstention_milli"] - full["abstention_milli"])
            transitions[f"{status(full)}_to_{status(current)}"] += 1
            counts["elapsed_ms_sum"] += current["elapsed_ms"]
            counts["prompt_tokens_sum"] += current["prompt_tokens"]
            counts["generated_tokens_sum"] += current["generated_tokens"]
        role_transitions[role] = transitions
        role_metrics[role] = {
            "tasks": n,
            "coverage": {
                "numerator": counts["accepted"],
                "denominator": n,
                "percent": round(100.0 * counts["accepted"] / n, 2) if n else None,
            },
            "direct_precision": {
                "numerator": counts["correct_accepted"],
                "denominator": counts["accepted"],
                "percent": round(100.0 * counts["correct_accepted"] / counts["accepted"], 2)
                if counts["accepted"] else None,
            },
            "wrong_accepted": counts["wrong_accepted"],
            "raw_choice_correct": counts["raw_choice_correct"],
            "proposal_changed_vs_full": counts["proposal_changed"],
            "threshold_acceptance_changed_vs_full": counts["threshold_acceptance_changed"],
            "baseline_correct_to_relinquished": counts["baseline_correct_to_relinquished"],
            "baseline_wrong_commit_avoided": counts["baseline_wrong_commit_avoided"],
            "mean_applicability_delta_milli_vs_full": mean(app_deltas),
            "mean_abstention_delta_milli_vs_full": mean(abst_deltas),
            "observer_elapsed_ms": round(counts["elapsed_ms_sum"], 3),
            "prompt_tokens": counts["prompt_tokens_sum"],
            "generated_tokens": counts["generated_tokens_sum"],
            "decision_reasons": dict(Counter(views[role][task]["decision"] for task in task_ids)),
        }

    routed = Counter()
    routed_tokens = 0
    routed_ms = 0.0
    for task_id in task_ids:
        small = views["small"][task_id]
        large = views["large"][task_id]
        routed_tokens += small["prompt_tokens"] + small["generated_tokens"]
        routed_ms += small["elapsed_ms"]
        if small["accepted"]:
            routed["small_selected"] += 1
            routed["hybrid_completions"] += int(small["correct"])
            routed["hybrid_wrong_commits"] += int(not small["raw_correct"])
        else:
            routed["large_calls_if_routed"] += 1
            routed_tokens += large["prompt_tokens"] + large["generated_tokens"]
            routed_ms += large["elapsed_ms"]
            routed["hybrid_completions"] += int(large["correct"])
            routed["hybrid_wrong_commits"] += int(large["accepted"] and not large["raw_correct"])
    routed["small_observer_calls"] = n
    routed["always_large_completions"] = sum(views["large"][task]["correct"] for task in task_ids)
    routed["small_direct_completions"] = sum(views["small"][task]["correct"] for task in task_ids)
    routed["large_calls_avoided_vs_always_large"] = n - routed["large_calls_if_routed"]
    routed["routed_observer_tokens"] = routed_tokens
    routed["routed_observer_elapsed_ms"] = round(routed_ms, 3)

    small_transitions = role_transitions["small"]
    if condition == "evidence-masked":
        direction = {
            "small_applicability_lower": sum(
                views["small"][task]["applicability_milli"] is not None
                and full_views["small"][task]["applicability_milli"] is not None
                and views["small"][task]["applicability_milli"] < full_views["small"][task]["applicability_milli"]
                for task in task_ids
            ),
            "small_abstention_higher": sum(
                views["small"][task]["abstention_milli"] is not None
                and full_views["small"][task]["abstention_milli"] is not None
                and views["small"][task]["abstention_milli"] > full_views["small"][task]["abstention_milli"]
                for task in task_ids
            ),
            "small_coverage_lower": small_transitions["correct_to_relinquished"]
            + small_transitions["wrong_to_relinquished"],
            "small_coverage_higher": small_transitions["relinquished_to_correct"]
            + small_transitions["relinquished_to_wrong"],
        }
    elif condition == "evidence-swapped":
        direction = {
            "small_proposal_changed": role_metrics["small"]["proposal_changed_vs_full"],
            "small_threshold_acceptance_changed": role_metrics["small"]["threshold_acceptance_changed_vs_full"],
            "small_correct_to_wrong": small_transitions["correct_to_wrong"],
            "small_correct_to_relinquished": small_transitions["correct_to_relinquished"],
            "small_wrong_to_correct": small_transitions["wrong_to_correct"],
            "small_wrong_to_relinquished": small_transitions["wrong_to_relinquished"],
        }
    elif condition == "repository-neutralized":
        direction = {
            "small_proposal_invariant": n - role_metrics["small"]["proposal_changed_vs_full"],
            "small_threshold_acceptance_invariant": n - role_metrics["small"]["threshold_acceptance_changed_vs_full"],
        }
    elif condition == "candidate-permuted":
        direction = {
            "small_semantic_proposal_invariant": n - role_metrics["small"]["proposal_changed_vs_full"],
            "small_threshold_acceptance_invariant": n - role_metrics["small"]["threshold_acceptance_changed_vs_full"],
        }
    else:
        direction = {}

    return {
        "repository": repository,
        "condition": condition,
        "n": n,
        "small": role_metrics["small"],
        "large": role_metrics["large"],
        "shadow_counterfactual_switchboard": dict(routed),
        "small_paired_transitions": dict(small_transitions),
        "large_paired_transitions": dict(role_transitions["large"]),
        "direction_diagnostics": direction,
    }


def render_report(result: dict) -> str:
    lines = [
        "# R&D-C / Experiment 011 — Causal Evidence Dependence",
        "",
        f"- Run: {result['run_id']}",
        f"- Classification: {result['classification']}",
        f"- Frozen thresholds: applicability >= {MIN_APP}/1000; abstention <= {MAX_ABST}/1000.",
        "- E010 labels were previously opened; E011 is a paired same-bank diagnostic, not independent held-out validation.",
        "- Interventions were shadow-only. E010 remains the execution, authority, and replay control.",
        "",
        "## E010 baseline reproduction",
        "",
        "| Repository | Tasks | Small coverage | Small precision | Hybrid | Always large | Large calls avoided |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["e010_full_frame_reproduction"]:
        precision = row["small_precision"]
        lines.append(
            f"| {row['repository']} | {row['tasks']} | {row['small_coverage']}/{row['tasks']} | "
            f"{precision['correct']}/{precision['accepted']} | {row['hybrid_completions']}/{row['tasks']} | "
            f"{row['always_large_completions']}/{row['tasks']} | {row['large_calls_avoided']} |"
        )

    lines.extend(["", "## E010 full-frame error complementarity", ""])
    lines.append("| Repository | P(small correct given large wrong) | P(large correct given small abstains or wrong) |")
    lines.append("| --- | ---: | ---: |")
    for repo, row in result["e010_error_complementarity"].items():
        small = row["p_small_correct_given_large_wrong"]
        large = row["p_large_correct_given_small_relinquished_or_wrong"]
        lines.append(
            f"| {repo} | {percent(small['numerator'], small['denominator'])} | "
            f"{percent(large['numerator'], large['denominator'])} |"
        )

    for condition in CONDITIONS[1:]:
        if condition not in result["conditions"]:
            continue
        rows = result["conditions"][condition]
        lines.extend(["", f"## {condition}", ""])
        lines.append(
            "| Repository | Tasks | Small coverage | Direct precision | Wrong small commits | "
            "Hybrid | Always large | Large calls avoided | Routed tokens | Routed observer ms | "
            "Mean delta applicability | Mean delta abstention |"
        )
        lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for row in rows:
            if row["repository"] == "POOLED_DESCRIPTIVE":
                continue
            small = row["small"]
            routed = row["shadow_counterfactual_switchboard"]
            precision = small["direct_precision"]
            lines.append(
                f"| {row['repository']} | {row['n']} | {small['coverage']['numerator']}/{row['n']} "
                f"({small['coverage']['percent']:.1f}%) | "
                f"{precision['numerator']}/{precision['denominator']} "
                f"({precision['percent'] if precision['percent'] is not None else 'n/a'}%) | "
                f"{small['wrong_accepted']} | {routed['hybrid_completions']}/{row['n']} | "
                f"{routed['always_large_completions']}/{row['n']} | "
                f"{routed['large_calls_avoided_vs_always_large']} | "
                f"{routed['routed_observer_tokens']} | {routed['routed_observer_elapsed_ms']:.3f} | "
                f"{small['mean_applicability_delta_milli_vs_full']} | "
                f"{small['mean_abstention_delta_milli_vs_full']} |"
            )
        lines.extend(
            [
                "",
                "Large-observer behavior by repository:",
                "",
                "| Repository | Coverage | Direct precision | Proposal changes vs full | Mean delta applicability | Mean delta abstention |",
                "| --- | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in rows:
            if row["repository"] == "POOLED_DESCRIPTIVE":
                continue
            large = row["large"]
            precision = large["direct_precision"]
            lines.append(
                f"| {row['repository']} | {large['coverage']['numerator']}/{row['n']} "
                f"({large['coverage']['percent']:.1f}%) | "
                f"{precision['numerator']}/{precision['denominator']} "
                f"({precision['percent'] if precision['percent'] is not None else 'n/a'}%) | "
                f"{large['proposal_changed_vs_full']} | "
                f"{large['mean_applicability_delta_milli_vs_full']} | "
                f"{large['mean_abstention_delta_milli_vs_full']} |"
            )
        lines.append("")
        lines.append("Small-observer paired diagnostics by repository:")
        for row in rows:
            if row["repository"] == "POOLED_DESCRIPTIVE":
                continue
            lines.append(f"- {row['repository']}: {json.dumps(row['direction_diagnostics'], sort_keys=True)}")
            lines.append(f"  State transitions: {json.dumps(row['small_paired_transitions'], sort_keys=True)}")
        lines.append("")
        lines.append("Completion and large-call figures replay the frozen routing rule over shadow proposals; no action ran in E011.")

    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Use repository rows as the transfer units and pooled totals only as descriptive summaries. Evidence masking leaves the task prompt and candidate diffs intact, so a stable proposal does not prove that evidence was ignored. Evidence swapping measures paired proposal and score changes under mismatched evidence; donor truth is not transferred to the recipient candidate set. Repository neutralization removes direct identity tokens and metadata but cannot erase every semantic clue in code or tests. Candidate permutation is scored by patch digest, so this lane isolates numeric IDs and ordering from action content.",
            "",
            "E011 is an interface-sensitivity diagnostic for the frozen switchboard. It does not establish a causal mechanism or a new cross-repository generalization result.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--allow-baseline-only", action="store_true")
    args = parser.parse_args()

    frozen_path = RUN / "frozen-input-lock.json"
    preseal_path = RUN / "pre-model-seal.json"
    frozen = read_json(frozen_path)
    preseal = read_json(preseal_path)
    if (
        preseal.get("state") != "SEALED_BEFORE_MODEL_CONTACT"
        or preseal.get("frozen_input_lock_sha256") != sha256(frozen_path.read_bytes())
    ):
        raise SystemExit("E011 pre-model seal does not match the frozen input lock")
    for relative, expected_hash in preseal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected_hash:
            raise SystemExit(f"frozen E011 code hash mismatch: {relative}")

    source_frames, labels, baseline = load_baseline()
    repositories: dict[str, list[str]] = defaultdict(list)
    for task_id, frame in source_frames.items():
        repositories[frame["repository_id"]].append(task_id)
    for task_ids in repositories.values():
        task_ids.sort()

    full_views = {
        role: {
            task_id: output_view(baseline[f"{role}:{task_id}"], source_frames[task_id], labels[task_id])
            for task_id in source_frames
        }
        for role in ROLES
    }
    expected = {
        "ripgrep": {"small": 8, "large": 8, "hybrid": 8},
        "turbovec": {"small": 5, "large": 5, "hybrid": 8},
    }
    baseline_rows = []
    for repository, task_ids in sorted(repositories.items()):
        small = [full_views["small"][task] for task in task_ids]
        large = [full_views["large"][task] for task in task_ids]
        hybrid = [s if s["accepted"] else l for s, l in zip(small, large, strict=True)]
        values = {
            "small": sum(item["correct"] for item in small),
            "large": sum(item["correct"] for item in large),
            "hybrid": sum(item["correct"] for item in hybrid),
        }
        if values != expected[repository]:
            raise RuntimeError(f"E010 baseline mismatch for {repository}: {values}")
        accepted = sum(item["accepted"] for item in small)
        baseline_rows.append(
            {
                "repository": repository,
                "tasks": len(task_ids),
                "small_coverage": accepted,
                "small_precision": {"correct": values["small"], "accepted": accepted},
                "always_large_completions": values["large"],
                "hybrid_completions": values["hybrid"],
                "large_calls_avoided": accepted,
            }
        )

    result = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "scored_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "same-bank diagnostic; treatment execution was shadow-only",
        "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        "e010_full_frame_reproduction": baseline_rows,
        "e010_error_complementarity": baseline_complementarity(repositories, source_frames, labels, baseline),
        "conditions": {},
    }

    treatment_dirs_exist = all(
        (RUN / "outputs" / role / condition).is_dir()
        for role in ROLES
        for condition in CONDITIONS[1:]
    )
    if not treatment_dirs_exist and not args.allow_baseline_only:
        raise SystemExit("treatment outputs are incomplete; use --allow-baseline-only only for a baseline audit")
    if treatment_dirs_exist:
        output_seal_path = RUN / "postrun-output-seal.json"
        output_seal = read_json(output_seal_path)
        if (
            output_seal.get("state") != "OUTPUTS_SEALED_BEFORE_SCORING"
            or output_seal.get("pre_model_seal_sha256") != sha256(preseal_path.read_bytes())
        ):
            raise SystemExit("E011 output seal is missing or does not match the pre-model seal")
        for role in ROLES:
            for condition in CONDITIONS[1:]:
                directory = RUN / "outputs" / role / condition
                records = sorted(directory.glob("*.json"))
                item = output_seal["output_tree_sha256"][role][condition]
                if len(records) != 16 or tree_hash(directory) != item["tree_sha256"]:
                    raise SystemExit(f"sealed output tree mismatch: {role}/{condition}")

    for condition in CONDITIONS:
        if condition != "full-frame" and not treatment_dirs_exist:
            continue
        records, condition_frames = load_records(condition, source_frames)
        condition_rows = []
        for repository, task_ids in sorted(repositories.items()):
            condition_rows.append(
                paired_lane(
                    condition, repository, task_ids, source_frames, condition_frames,
                    labels, records, full_views,
                )
            )
        condition_rows.append(
            paired_lane(
                condition, "POOLED_DESCRIPTIVE", sorted(source_frames), source_frames,
                condition_frames, labels, records, full_views,
            )
        )
        result["conditions"][condition] = condition_rows

    write_json(RUN / "score-e011.json", result)
    report = RUN / "experiment-011-report.md"
    report.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"report": str(report), "conditions": list(result["conditions"])}, indent=2))


if __name__ == "__main__":
    main()
