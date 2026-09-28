from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
RUN_ID = "e012-20260926-frame-decomposition-01"
RUN = ROOT / "artifacts/runs" / RUN_ID
AUTHORIZER = ROOT / "inputs/authority/e011-authorize.exe"
MIN_APP = 850
MAX_ABST = 150


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"refusing to overwrite scoring artifact: {path}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def accepted(output: object, frame: dict) -> tuple[bool, str]:
    if not isinstance(output, dict):
        return False, "invalid-output"
    choice = output.get("action_choice")
    app = output.get("applicability_milli")
    abst = output.get("abstention_milli")
    if type(app) is not int or type(abst) is not int:
        return False, "invalid-scores"
    if choice is None:
        return False, "explicit-abstention"
    ids = {row["action"]["id"] for row in frame["action_options"]}
    if type(choice) is not int or choice not in ids:
        return False, "unknown-action"
    if abst > MAX_ABST:
        return False, "abstention-threshold"
    if app < MIN_APP:
        return False, "applicability-threshold"
    return True, "accepted"


def elapsed(record: dict) -> float:
    try:
        return float(record.get("elapsed_ms", 0.0))
    except (TypeError, ValueError):
        return 0.0


def tokens(record: dict) -> tuple[int, int]:
    usage = record.get("usage") or {}
    return int(usage.get("prompt_tokens", 0) or 0), int(usage.get("completion_tokens", 0) or 0)


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 3)


def lane_summary(rows: list[dict]) -> dict:
    n = len(rows)
    selected = sum(row["accepted"] for row in rows)
    correct = sum(row["accepted"] and row["completed"] for row in rows)
    complete = sum(row["completed"] for row in rows)
    time_values = [row["route_latency_ms"] for row in rows]
    prompt = sum(row["prompt_tokens"] for row in rows)
    generated = sum(row["generated_tokens"] for row in rows)
    return {
        "tasks": n,
        "direct_coverage": {"numerator": selected, "denominator": n, "rate": selected / n if n else None},
        "direct_precision": {"numerator": correct, "denominator": selected, "rate": correct / selected if selected else None},
        "task_completion": {"numerator": complete, "denominator": n, "rate": complete / n if n else None},
        "wrong_legal_actions": sum(row["accepted"] and not row["completed"] for row in rows),
        "abstentions_or_rejections": n - selected,
        "small_calls": sum(row["small_calls"] for row in rows),
        "large_calls": sum(row["large_calls"] for row in rows),
        "input_tokens": prompt,
        "generated_tokens": generated,
        "total_tokens": prompt + generated,
        "route_time_ms": {
            "p50": percentile(time_values, 0.50),
            "p95": percentile(time_values, 0.95),
            "total": round(sum(time_values), 3),
        },
        "observer_time_ms": {
            "small": round(sum(row["small_elapsed_ms"] for row in rows), 3),
            "large": round(sum(row["large_elapsed_ms"] for row in rows), 3),
        },
    }


def normalize_for_authority(output: object) -> dict:
    if isinstance(output, dict):
        choice = output.get("action_choice")
        app = output.get("applicability_milli")
        abst = output.get("abstention_milli")
        if (
            (choice is None or (type(choice) is int and 0 <= choice <= 65535))
            and type(app) is int and type(abst) is int
            and 0 <= app <= 1000 and 0 <= abst <= 1000
        ):
            return {"action_choice": choice, "applicability_milli": app, "abstention_milli": abst}
    return {"action_choice": None, "applicability_milli": 0, "abstention_milli": 1000}


def authorize(sample: dict, binding: dict, outcomes: dict, record: dict, selected_role: str, lane: str, input_dir: Path) -> dict:
    frame = sample["frame"]
    normalized = normalize_for_authority(record.get("normalized_output"))
    choice = normalized["action_choice"]
    eligible, _reason = accepted(normalized, frame)
    authorized_choice = choice if eligible else None
    completed = bool(outcomes.get(authorized_choice, {}).get("task_candidate_passed", False)) if authorized_choice is not None else False
    ordered = [
        {
            "producer_ordinal": index,
            "action": option["action"],
            "summary": option["summary"],
            "diff_excerpt": option["diff_excerpt"],
            "patch_sha256": option["patch_sha256"],
        }
        for index, option in enumerate(frame["action_options"])
    ]
    if [row["action"]["id"] for row in ordered] != binding["ordered_action_ids"]:
        raise RuntimeError(f"producer-order receipt differs for {sample['sample_id']}")
    sample_id = sample["sample_id"]
    ledger = RUN / "action-ledgers" / lane / f"{sample_id}.bin"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / f"{lane}--{sample_id}.json"
    output_path = RUN / "authorization" / lane / f"{sample_id}.json"
    payload = {
        "task_id": f"{lane}-{sample_id}",
        "frame_digest_hex": binding["frame_digest_hex"],
        "request_id_hex": binding["request_id_hex"],
        "response_request_id_hex": binding["request_id_hex"],
        "request_receipt_digest_hex": binding["receipt_digest_hex"],
        "response_receipt_digest_hex": binding["receipt_digest_hex"],
        "presentation_receipt_hex": binding["receipt_hex"],
        "action_ledger_path": str(ledger),
        "ordered_options": ordered,
        "observer_output": normalized,
        "thresholds": {"minimum_applicability_milli": MIN_APP, "maximum_abstention_milli": MAX_ABST},
        "completion_check_passed": completed,
    }
    write_new(input_path, payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(AUTHORIZER), str(input_path), str(output_path)], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"E011 authority failed for {sample_id}/{lane}: {proc.stderr.strip()}")
    auth = read_json(output_path)
    if not auth["presentation_verified"] or not auth["replay_state_identical"]:
        raise RuntimeError(f"presentation/replay invariant failed for {sample_id}/{lane}")
    if auth["illegal_commits"] != 0 or auth["duplicate_action_effects"] != 0:
        raise RuntimeError(f"action authority invariant failed for {sample_id}/{lane}")
    if auth["action_choice"] != authorized_choice or auth["completion_check_passed"] != completed:
        raise RuntimeError(f"authority result differs from typed proposal for {sample_id}/{lane}")
    return auth, normalized, completed


def main() -> None:
    lock = read_json(RUN / "frozen-input-lock.json")
    seal = read_json(RUN / "pre-model-seal.json")
    if lock.get("state") != "FROZEN_BEFORE_MODEL_CONTACT" or seal.get("state") != "SEALED_BEFORE_MODEL_CONTACT":
        raise SystemExit("E012 frozen input lock or pre-model seal is invalid")
    if seal.get("frozen_input_lock_sha256") != sha256((RUN / "frozen-input-lock.json").read_bytes()):
        raise SystemExit("E012 pre-model seal hash mismatch")

    frame_lock = read_json(RUN / "inputs/full-frame-lock.json")
    binding_lock = read_json(RUN / "inputs/presentation-bindings.json")
    labels = read_json(RUN / "vault/evaluation-labels.json")
    samples = frame_lock["frames"]
    bindings = {row["sample_id"]: row for row in binding_lock["bindings"]}
    truth = {row["sample_id"]: row for row in labels["tasks"]}
    sample_ids = {row["sample_id"] for row in samples}
    if len(samples) != 48 or sample_ids != set(bindings) or sample_ids != set(truth):
        raise RuntimeError("scoring inputs do not align at 48 paired samples")

    records: dict[str, dict[str, dict]] = {"small": {}, "large": {}}
    for role in ("small", "large"):
        for sample in samples:
            sample_id = sample["sample_id"]
            path = RUN / "outputs" / role / f"{sample_id}.json"
            if not path.is_file():
                raise RuntimeError(f"missing raw observer response: {role}/{sample_id}")
            record = read_json(path)
            if (
                record.get("run_id") != RUN_ID or record.get("role") != role
                or record.get("sample_id") != sample_id
                or record.get("frame_sha256") != sample["frame_sha256"]
            ):
                raise RuntimeError(f"observer response identity mismatch: {role}/{sample_id}")
            records[role][sample_id] = record

    auth_input_dir = RUN / "vault/authorization-inputs"
    auth_input_dir.mkdir(parents=True, exist_ok=False)
    lanes = {"small_only": [], "large_only": [], "hybrid": []}
    invariant_counts = Counter()
    details = []
    for sample in samples:
        sample_id = sample["sample_id"]
        frame = sample["frame"]
        binding = bindings[sample_id]
        action_outcomes = {row["action_id"]: row for row in truth[sample_id]["candidate_outcomes"]}
        output = {role: records[role][sample_id] for role in ("small", "large")}
        small_ok, small_reason = accepted(output["small"].get("normalized_output"), frame)
        large_ok, large_reason = accepted(output["large"].get("normalized_output"), frame)
        source = {
            "small_only": "small",
            "large_only": "large",
            "hybrid": "small" if small_ok else "large",
        }
        task_detail = {
            "sample_id": sample_id,
            "task_id": sample["task_id"],
            "pair_id": truth[sample_id]["pair_id"],
            "repository": frame["repository_id"],
            "family": frame["task_family"],
            "stratum": truth[sample_id]["stratum"],
            "small_eligibility": {"accepted": small_ok, "reason": small_reason},
            "large_eligibility": {"accepted": large_ok, "reason": large_reason},
            "hybrid_selected_role": source["hybrid"],
            "lanes": {},
        }
        for lane, role in source.items():
            raw = output[role]
            auth, normalized, candidate_passed = authorize(
                sample, binding, action_outcomes, raw, role, lane, auth_input_dir
            )
            prompt_tokens, generated_tokens = tokens(raw)
            small_used = int(lane in ("small_only", "hybrid"))
            large_used = int(lane == "large_only" or (lane == "hybrid" and role == "large"))
            if lane == "hybrid":
                prompt_tokens, generated_tokens = tokens(output["small"])
                if large_used:
                    extra_prompt, extra_generated = tokens(output["large"])
                    prompt_tokens += extra_prompt
                    generated_tokens += extra_generated
            small_time = elapsed(output["small"]) if small_used else 0.0
            large_time = elapsed(output["large"]) if large_used else 0.0
            row = {
                "sample_id": sample_id,
                "task_id": sample["task_id"],
                "pair_id": truth[sample_id]["pair_id"],
                "repository": frame["repository_id"],
                "family": frame["task_family"],
                "stratum": truth[sample_id]["stratum"],
                "accepted": auth["action_choice"] is not None,
                "completed": auth["final_state"] == "DONE",
                "wrong_legal_action": auth["action_choice"] is not None and not candidate_passed,
                "selected_role": role,
                "small_calls": small_used,
                "large_calls": large_used,
                "prompt_tokens": prompt_tokens,
                "generated_tokens": generated_tokens,
                "small_elapsed_ms": small_time,
                "large_elapsed_ms": large_time,
                "route_latency_ms": small_time + large_time if lane == "hybrid" else elapsed(raw),
                "action_choice": auth["action_choice"],
                "selected_patch_sha256": auth["selected_patch_sha256"],
                "applicability_milli": normalized["applicability_milli"],
                "abstention_milli": normalized["abstention_milli"],
                "normalization_error": raw.get("normalization_error"),
                "finish_reason": raw.get("finish_reason"),
                "presentation_verified": auth["presentation_verified"],
                "replay_state_identical": auth["replay_state_identical"],
                "replay_identity": auth["replay_identity"],
                "illegal_commits": auth["illegal_commits"],
                "duplicate_action_effects": auth["duplicate_action_effects"],
                "unique_action_effects": auth["unique_action_effects"],
                "idempotent_action_reuse": auth["idempotent_action_reuse"],
            }
            lanes[lane].append(row)
            task_detail["lanes"][lane] = row
            invariant_counts["authorization_cases"] += 1
            invariant_counts["presentation_rejections"] += int(not auth["presentation_verified"])
            invariant_counts["replay_mismatches"] += int(not auth["replay_state_identical"])
            invariant_counts["illegal_commits"] += auth["illegal_commits"]
            invariant_counts["duplicate_action_effects"] += auth["duplicate_action_effects"]
            invariant_counts["unique_action_effects"] += auth["unique_action_effects"]
        details.append(task_detail)

    lane_reports = {name: lane_summary(rows) for name, rows in lanes.items()}
    stratified: dict[str, dict] = {}
    for field in ("repository", "family", "stratum"):
        stratified[field] = {}
        for lane_name, lane_rows in lanes.items():
            groups: dict[str, list[dict]] = defaultdict(list)
            for row in lane_rows:
                groups[str(row[field])].append(row)
            stratified[field][lane_name] = {
                key: lane_summary(value) for key, value in sorted(groups.items())
            }

    output_hashes = {}
    for role in ("small", "large"):
        digest = hashlib.sha256()
        for path in sorted((RUN / "outputs" / role).glob("*.json")):
            digest.update(path.name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        output_hashes[role] = digest.hexdigest()

    report = {
        "schema_version": 1,
        "state": "FULL_FRAME_BASELINE_SCORED",
        "run_id": RUN_ID,
        "frozen_input_lock_sha256": sha256((RUN / "frozen-input-lock.json").read_bytes()),
        "sample_count": len(samples),
        "paired_task_count": len({row["pair_id"] for row in details}),
        "repository_count": len({row["repository"] for row in details}),
        "task_family_count": len({row["family"] for row in details}),
        "bundle_ids": {
            role: records[role][samples[0]["sample_id"]]["bundle_id"]
            for role in ("small", "large")
        },
        "thresholds_milli": {"minimum_applicability": MIN_APP, "maximum_abstention": MAX_ABST},
        "lanes": lane_reports,
        "stratified": stratified,
        "admission_gate": {
            "small_direct_actions": lane_reports["small_only"]["direct_coverage"]["numerator"],
            "small_wrong_accepted_actions": lane_reports["small_only"]["wrong_legal_actions"],
            "passed": (
                lane_reports["small_only"]["direct_coverage"]["numerator"] > 0
                and lane_reports["small_only"]["wrong_legal_actions"] == 0
            ),
            "criterion": "at least one small direct action and zero wrong accepted small actions",
        },
        "authority_invariants": dict(invariant_counts),
        "physical_observer_calls": {"small": len(samples), "large": len(samples)},
        "shadow_replay_large_calls_if_routed": lane_reports["hybrid"]["large_calls"],
        "output_tree_sha256": output_hashes,
        "limitations": [
            "The full-frame baseline is a 48-sample paired synthetic coding bank, not a broad repository benchmark.",
            "Both models were queried on all samples for paired comparison; hybrid calls and costs are replayed from frozen outputs.",
            "Timing is local serial HTTP elapsed time; completion labels come from frozen executable candidate checks.",
        ],
        "tasks": details,
    }
    write_new(RUN / "reports/full-frame-baseline-report.json", report)
    lines = [
        "# E012 full-frame baseline",
        "",
        f"Run: {RUN_ID}",
        "",
        f"Samples: {len(samples)} in {report['paired_task_count']} paired items; "
        f"{report['repository_count']} repositories and {report['task_family_count']} task families.",
        "",
        "| Lane | Completion | Direct coverage | Direct precision | Wrong legal actions | Large calls | Total tokens |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for lane, label in (
        ("small_only", "Small only"),
        ("large_only", "Large only"),
        ("hybrid", "Small then large on abstention"),
    ):
        value = lane_reports[lane]
        comp, coverage, precision = value["task_completion"], value["direct_coverage"], value["direct_precision"]
        lines.append(
            f"| {label} | {comp['numerator']}/{comp['denominator']} | "
            f"{coverage['numerator']}/{coverage['denominator']} | "
            f"{precision['numerator']}/{precision['denominator']} | "
            f"{value['wrong_legal_actions']} | {value['large_calls']} | {value['total_tokens']} |"
        )
    lines.extend(["", "## Per-repository lanes", "", "| Repository | Small completion | Small coverage / precision | Large completion | Hybrid completion | Hybrid large calls |", "|---|---:|---:|---:|---:|---:|"])
    small_by_repo = stratified["repository"]["small_only"]
    large_by_repo = stratified["repository"]["large_only"]
    hybrid_by_repo = stratified["repository"]["hybrid"]
    for repository in sorted(small_by_repo):
        small, large, hybrid = small_by_repo[repository], large_by_repo[repository], hybrid_by_repo[repository]
        small_comp = small["task_completion"]
        small_cov, small_prec = small["direct_coverage"], small["direct_precision"]
        large_comp, hybrid_comp = large["task_completion"], hybrid["task_completion"]
        lines.append(
            f"| {repository} | {small_comp['numerator']}/{small_comp['denominator']} | "
            f"{small_cov['numerator']}/{small_cov['denominator']} / "
            f"{small_prec['numerator']}/{small_prec['denominator']} | "
            f"{large_comp['numerator']}/{large_comp['denominator']} | "
            f"{hybrid_comp['numerator']}/{hybrid_comp['denominator']} | {hybrid['large_calls']} |"
        )
    lines.extend([
        "",
        "Both observer bundles were queried on all samples for paired comparison. Hybrid resource totals replay the frozen outputs and count a large call only when the small output failed the locked acceptance rule.",
        "",
        "See the JSON report for task, family, repository, and stratum breakdowns, token totals, elapsed time, receipts, and replay invariants.",
        "",
    ])
    write_new(RUN / "reports/full-frame-baseline-report.md", "\n".join(lines))


if __name__ == "__main__":
    main()
