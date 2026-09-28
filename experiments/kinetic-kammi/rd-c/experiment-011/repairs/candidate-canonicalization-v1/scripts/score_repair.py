from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(r"C:\rd-c\experiment-011\repairs\candidate-canonicalization-v1")
PARENT = Path(r"C:\rd-c\experiment-011")
RUN_ID = "e011-r1-20260925-candidate-canonicalization-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
MIN_APP = 850
MAX_ABST = 150


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def tree_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def decide(record: dict, entry: dict, labels: dict, base_frame: dict) -> dict:
    output = record.get("normalized_output")
    if not isinstance(output, dict):
        return {"accepted": False, "correct": False, "raw_correct": False, "mapped_ok": False, "reason": "invalid-output"}
    choice = output.get("action_choice")
    receipt = {row["canonical_action_id"]: row for row in entry["receipt_full_frame"]}
    mapping = receipt.get(choice) if type(choice) is int else None
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    mapped_id = record.get("mapped_original_action_id")
    mapped_patch = record.get("selected_patch_sha256")
    source_option = next(
        (option for option in base_frame["action_options"] if option["action"]["id"] == mapped_id),
        None,
    )
    mapped_ok = bool(
        mapping
        and source_option
        and source_option["patch_sha256"] == mapping["patch_sha256"] == mapped_patch
    )
    raw_correct = bool(
        mapping
        and labels["actions_by_patch_sha256"].get(mapping["patch_sha256"], {}).get("expected_task_completion", False)
    )
    if not mapping:
        reason = "explicit-abstention" if choice is None else "unknown-canonical-id"
    elif type(app) is not int or type(abst) is not int:
        reason = "invalid-scores"
    elif abst > MAX_ABST:
        reason = "abstention-threshold"
    elif app < MIN_APP:
        reason = "applicability-threshold"
    elif not mapped_ok:
        reason = "receipt-mapping-invalid"
    else:
        reason = "accepted"
    accepted = reason == "accepted"
    return {
        "accepted": accepted,
        "correct": bool(accepted and raw_correct),
        "raw_correct": raw_correct,
        "mapped_ok": mapped_ok,
        "patch_sha256": mapping["patch_sha256"] if mapping else None,
        "original_action_id": mapped_id,
        "canonical_action_id": choice,
        "applicability_milli": app,
        "abstention_milli": abst,
        "reason": reason,
        "elapsed_ms": float(record.get("elapsed_ms", 0.0)),
        "prompt_tokens": int(record.get("usage", {}).get("prompt_tokens", 0) or 0),
        "generated_tokens": int(record.get("usage", {}).get("completion_tokens", 0) or 0),
    }


def main() -> None:
    lock_path = RUN / "pre-model-input-lock.json"
    preseal_path = RUN / "pre-model-seal.json"
    output_seal_path = RUN / "postrun-output-seal.json"
    lock = read_json(lock_path)
    preseal = read_json(preseal_path)
    output_seal = read_json(output_seal_path)
    if (
        preseal.get("state") != "SEALED_BEFORE_MODEL_CONTACT"
        or preseal.get("input_lock_sha256") != sha256(lock_path.read_bytes())
        or output_seal.get("state") != "OUTPUTS_SEALED_BEFORE_SCORING"
        or output_seal.get("pre_model_seal_sha256") != sha256(preseal_path.read_bytes())
    ):
        raise SystemExit("repair pre-model or output seal mismatch")
    for relative, expected in preseal["code_sha256"].items():
        path = ROOT / relative
        if not path.is_file() or sha256(path.read_bytes()) != expected:
            raise SystemExit(f"repair code changed after sealing: {relative}")
    for role in ("small", "large"):
        directory = RUN / "outputs" / role
        if tree_hash(directory) != output_seal["outputs"][role]["tree_sha256"]:
            raise SystemExit(f"repair output tree changed: {role}")

    frame_lock = read_json(RUN / "canonical-frame-lock.json")
    labels = read_json(ROOT / "inputs/e010-heldout-sealed-labels.json")["tasks"]
    base_lock = read_json(ROOT / "inputs/e010-heldout-frame-lock.json")
    base_frames = {item["frame"]["task_id"]: item["frame"] for item in base_lock["frames"]}
    labels_by_repo: dict[str, list[dict]] = defaultdict(list)
    views: dict[str, dict[str, dict]] = {"small": {}, "large": {}}
    outputs = {role: {} for role in ("small", "large")}
    for entry in frame_lock["frames"]:
        task_id = entry["task_id"]
        base = base_frames[task_id]
        repository = base["repository_id"]
        for role in ("small", "large"):
            record = read_json(RUN / "outputs" / role / f"{task_id}.json")
            if record.get("http_status") != 200:
                raise RuntimeError(f"{role} observer call failed for {task_id}")
            decision = decide(record, entry, labels[task_id], base)
            views[role][task_id] = decision
            outputs[role][task_id] = record
            labels_by_repo[repository].append({"task_id": task_id})

    repositories: dict[str, list[str]] = defaultdict(list)
    for task_id, frame in base_frames.items():
        repositories[frame["repository_id"]].append(task_id)
    rows = []
    for repository, task_ids in sorted(repositories.items()):
        row = {"repository": repository, "tasks": len(task_ids)}
        for role in ("small", "large"):
            lane = [views[role][task] for task in task_ids]
            accepted = sum(item["accepted"] for item in lane)
            correct = sum(item["correct"] for item in lane)
            row[role] = {
                "coverage": {"accepted": accepted, "tasks": len(task_ids)},
                "direct_precision": {"correct": correct, "accepted": accepted},
                "wrong_accepted": sum(item["accepted"] and not item["raw_correct"] for item in lane),
                "mapping_failures": sum(not item["mapped_ok"] and item["canonical_action_id"] is not None for item in lane),
                "mapped_proposals": sum(item["mapped_ok"] for item in lane),
                "proposal_reasons": dict(Counter(item["reason"] for item in lane)),
                "tokens": sum(item["prompt_tokens"] + item["generated_tokens"] for item in lane),
                "observer_ms": round(sum(item["elapsed_ms"] for item in lane), 3),
            }
        hybrid = [
            views["small"][task] if views["small"][task]["accepted"] else views["large"][task]
            for task in task_ids
        ]
        row["hybrid"] = {
            "completions": sum(item["correct"] for item in hybrid),
            "tasks": len(task_ids),
            "large_calls": sum(not views["small"][task]["accepted"] for task in task_ids),
            "large_calls_avoided": sum(views["small"][task]["accepted"] for task in task_ids),
            "wrong_commits": sum(item["accepted"] and not item["raw_correct"] for item in hybrid),
            "routed_tokens": sum(
                views["small"][task]["prompt_tokens"] + views["small"][task]["generated_tokens"]
                + (
                    views["large"][task]["prompt_tokens"] + views["large"][task]["generated_tokens"]
                    if not views["small"][task]["accepted"] else 0
                )
                for task in task_ids
            ),
            "routed_observer_ms": round(sum(
                views["small"][task]["elapsed_ms"]
                + (views["large"][task]["elapsed_ms"] if not views["small"][task]["accepted"] else 0.0)
                for task in task_ids
            ), 3),
        }
        row["always_large_completions"] = sum(views["large"][task]["correct"] for task in task_ids)
        rows.append(row)

    pooled = {
        "repository": "POOLED_DESCRIPTIVE",
        "tasks": len(base_frames),
        "small_coverage": sum(row["small"]["coverage"]["accepted"] for row in rows),
        "small_correct": sum(row["small"]["direct_precision"]["correct"] for row in rows),
        "small_wrong_accepted": sum(row["small"]["wrong_accepted"] for row in rows),
        "large_completions": sum(row["always_large_completions"] for row in rows),
        "hybrid_completions": sum(row["hybrid"]["completions"] for row in rows),
        "large_calls_avoided": sum(row["hybrid"]["large_calls_avoided"] for row in rows),
        "mapping_failures": sum(row["small"]["mapping_failures"] + row["large"]["mapping_failures"] for row in rows),
        "routed_tokens": sum(row["hybrid"]["routed_tokens"] for row in rows),
        "routed_observer_ms": round(sum(row["hybrid"]["routed_observer_ms"] for row in rows), 3),
    }
    parent_score = read_json(PARENT / "artifacts/runs/e011-20260925-causal-evidence-01/score-e011.json")
    comparisons = {}
    for key in ("full-frame", "candidate-permuted"):
        comparisons[key] = []
        for parent_row in parent_score["conditions"][key]:
            if parent_row["repository"] == "POOLED_DESCRIPTIVE":
                continue
            comparisons[key].append(
                {
                    "repository": parent_row["repository"],
                    "hybrid_completions": parent_row["shadow_counterfactual_switchboard"]["hybrid_completions"],
                    "always_large_completions": parent_row["shadow_counterfactual_switchboard"]["always_large_completions"],
                    "small_coverage": parent_row["small"]["coverage"]["numerator"],
                    "small_direct_precision": parent_row["small"]["direct_precision"],
                    "large_calls_avoided": parent_row["shadow_counterfactual_switchboard"]["large_calls_avoided_vs_always_large"],
                    "wrong_small_actions": parent_row["small"]["wrong_accepted"],
                }
            )
    result = {
        "schema_version": 1,
        "run_id": RUN_ID,
        "scored_utc": datetime.now(timezone.utc).isoformat(),
        "classification": "same-bank repair validation; shadow-only; no independent generalization claim",
        "adapter_id": "candidate-canonicalization-v1",
        "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        "canonical_input_invariance": {
            "tasks": len(frame_lock["frames"]),
            "full_vs_permuted_canonical_frames_identical": True,
            "accepted_outputs_mapped_to_original_authority_ids": pooled["mapping_failures"] == 0,
            "mapping_failures": pooled["mapping_failures"],
        },
        "repositories": rows,
        "pooled_descriptive": pooled,
        "parent_e011_comparison": comparisons,
    }
    write_json(RUN / "repair-score.json", result)
    (RUN / "repair-report.md").write_text(render_report(result), encoding="utf-8")
    print(json.dumps({"report": str(RUN / "repair-report.md"), "pooled": pooled}, indent=2))


def render_report(result: dict) -> str:
    lines = [
        "# E011-R1 — Candidate Canonicalization Repair",
        "",
        f"- Run: {result['run_id']}",
        f"- Adapter: {result['adapter_id']}",
        "- Same E009 v5 weights, prompt, schema, thresholds, and authority; input adapter has a new bundle identity.",
        "- Same E010 task bank and already-opened labels; shadow-only repair validation.",
        "",
        "## Repository-level outcomes",
        "",
        "| Repository | Small coverage | Direct precision | Wrong small actions | Hybrid | Always large | Large calls avoided | Mapping failures |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in result["repositories"]:
        small = row["small"]
        lines.append(
            f"| {row['repository']} | {small['coverage']['accepted']}/{row['tasks']} | "
            f"{small['direct_precision']['correct']}/{small['direct_precision']['accepted']} | "
            f"{small['wrong_accepted']} | {row['hybrid']['completions']}/{row['tasks']} | "
            f"{row['always_large_completions']}/{row['tasks']} | {row['hybrid']['large_calls_avoided']} | "
            f"{row['small']['mapping_failures'] + row['large']['mapping_failures']} |"
        )
    pooled = result["pooled_descriptive"]
    lines.extend(
        [
            "",
            "## Pooled descriptive totals",
            "",
            f"Small coverage {pooled['small_coverage']}/{pooled['tasks']}; direct correct actions "
            f"{pooled['small_correct']}; wrong accepted small actions {pooled['small_wrong_accepted']}; "
            f"hybrid {pooled['hybrid_completions']}/{pooled['tasks']}; always large "
            f"{pooled['large_completions']}/{pooled['tasks']}; large calls avoided "
            f"{pooled['large_calls_avoided']}; mapping failures {pooled['mapping_failures']}; "
            f"routed observer tokens {pooled['routed_tokens']}; routed observer time "
            f"{pooled['routed_observer_ms']:.3f} ms.",
            "",
            "## Input invariance and authority mapping",
            "",
            "The pre-model audit canonicalized each full E010 frame and its paired E011 candidate-permuted frame through the Rust adapter. All 16 model-visible frames were identical across the two source forms. Output choices were receipted back to original E010 action IDs and patch digests; mapping failures are reported per repository.",
            "",
            "## Comparison with sealed E011",
            "",
            "| Repository | E010 full-frame hybrid / errors | E011 permuted hybrid / errors | E011-R1 canonical hybrid / errors |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    full = {row["repository"]: row for row in result["parent_e011_comparison"]["full-frame"]}
    perm = {row["repository"]: row for row in result["parent_e011_comparison"]["candidate-permuted"]}
    for row in result["repositories"]:
        repo = row["repository"]
        lines.append(
            f"| {repo} | {full[repo]['hybrid_completions']}/8, {full[repo]['wrong_small_actions']} | "
            f"{perm[repo]['hybrid_completions']}/8, {perm[repo]['wrong_small_actions']} | "
            f"{row['hybrid']['completions']}/8, {row['small']['wrong_accepted']} |"
        )
    lines.extend(
        [
            "",
            "This comparison diagnoses one deterministic adapter on the reused bank. It is not a new transfer test or a mechanism claim. The adapter changes the observer-visible representation and therefore has a separate versioned bundle identity.",
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    main()
