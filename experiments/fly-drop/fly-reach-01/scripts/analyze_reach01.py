from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from collections import defaultdict
from statistics import median

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/REACH01-RUN1"
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
BLOCKS = tuple(range(62000, 62012))
ARMS = ("native", "sign_ref_native_mag", "mag_ref_native_sign", "reference_direction_native_support", "reference_direction_full_support", "weight_oracle")
NON_ORACLE = ARMS[:-1]
CHECKPOINTS = (0, 512, 1024, 2048, 4096, 8192)
THRESHOLD = 0.25


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(message: str) -> None:
    raise SystemExit(f"INTEGRITY_FAIL: {message}")


def read_jsonl(path: pathlib.Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def mean(rows: list[dict], field: str) -> float:
    return sum(float(row[field]) for row in rows) / len(rows)


def summarize(rows: list[dict], field: str) -> dict[str, float]:
    values = [float(row[field]) for row in rows]
    return {
        "mean": sum(values) / len(values),
        "median": median(values),
        "min": min(values),
        "max": max(values),
        "competence_rate": sum(value <= THRESHOLD for value in values) / len(values),
    }


def main() -> None:
    contract_path = ROOT / "manifests/REACH01-CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if sha(contract_path) != (ROOT / "manifests/REACH01-CONTRACT.sha256").read_text().split()[0]: fail("contract sidecar mismatch")
    if contract["status"] != "SEALED_ENGINEERING_ONLY": fail("contract status changed")
    for entry in contract["input_hashes"]:
        if sha(ROOT / entry["path"]) != entry["sha256"]: fail(f"input hash mismatch: {entry['path']}")

    outcomes = read_jsonl(RUN / "outcomes.jsonl")
    diagnostics = read_jsonl(RUN / "diagnostics.jsonl")
    trajectories = read_jsonl(RUN / "trajectories.jsonl")
    expected_outcomes = {
        (substrate, side, block, arm, checkpoint)
        for substrate in SUBSTRATES for side in SIDES for block in BLOCKS
        for arm in ARMS for checkpoint in ((0, 8192) if arm == "weight_oracle" else CHECKPOINTS)
    }
    got_outcomes = {(row["substrate"], row["side"], int(row["block"]), row["arm"], int(row["checkpoint"])) for row in outcomes}
    if len(outcomes) != len(expected_outcomes) or got_outcomes != expected_outcomes:
        fail(f"outcome coverage rows={len(outcomes)} expected={len(expected_outcomes)} missing={len(expected_outcomes - got_outcomes)} extra={len(got_outcomes - expected_outcomes)}")
    expected_diagnostics = {(substrate, side, block, arm) for substrate in SUBSTRATES for side in SIDES for block in BLOCKS for arm in ARMS}
    got_diagnostics = {(row["substrate"], row["side"], int(row["block"]), row["arm"]) for row in diagnostics}
    if len(diagnostics) != len(expected_diagnostics) or got_diagnostics != expected_diagnostics: fail("diagnostic coverage")
    expected_trajectories = {(substrate, side, block, checkpoint) for substrate in SUBSTRATES for side in SIDES for block in BLOCKS for checkpoint in CHECKPOINTS[1:]}
    got_trajectories = {(row["substrate"], row["side"], int(row["block"]), int(row["checkpoint"])) for row in trajectories}
    if len(trajectories) != len(expected_trajectories) or got_trajectories != expected_trajectories: fail("trajectory coverage")

    for row in outcomes:
        for field in ("loss_256", "loss_large", "oracle_large", "excess_large"):
            if not float(row[field]) == float(row[field]): fail(f"nonfinite outcome {field}")
        if not (0.0 <= float(row["loss_256"]) <= 1.0 and 0.0 <= float(row["loss_large"]) <= 1.0): fail("loss outside [0,1]")
        if bool(row["competent"]) != (float(row["loss_256"]) <= THRESHOLD): fail("competence flag mismatch")
        if not row["finite"]: fail("legal computation reported nonfinite state")
    diagnostic_fields = [
        "eligibility_cosine_mean", "modulation_cosine_mean", "aggregation_cosine_mean", "delivered_cosine_mean",
        "native_reference_norm_ratio_mean", "native_support_fraction_mean", "reference_mass_on_native_support_mean",
        "sign_agreement_mean", "magnitude_pearson_mean", "bound_clip_fraction", "cumulative_delivered_l2",
    ]
    for row in diagnostics:
        for field in diagnostic_fields:
            if not float(row[field]) == float(row[field]): fail(f"nonfinite diagnostic {field}")
        for field in ("native_support_fraction_mean", "reference_mass_on_native_support_mean", "sign_agreement_mean", "bound_clip_fraction"):
            if not 0.0 <= float(row[field]) <= 1.0: fail(f"diagnostic range {field}")
    for row in trajectories:
        for field in ("eligibility_cosine", "modulation_cosine", "aggregation_cosine", "delivered_cosine", "native_support_fraction", "reference_mass_on_native_support", "sign_agreement", "magnitude_pearson"):
            if not float(row[field]) == float(row[field]): fail(f"nonfinite trajectory {field}")

    endpoint = [row for row in outcomes if int(row["checkpoint"]) == 8192]
    by_arm_substrate: dict[str, dict[str, dict]] = defaultdict(dict)
    for arm in ARMS:
        for substrate in SUBSTRATES:
            cell = [row for row in endpoint if row["arm"] == arm and row["substrate"] == substrate]
            by_arm_substrate[arm][substrate] = {
                "loss_256": summarize(cell, "loss_256"),
                "loss_large": summarize(cell, "loss_large"),
                "excess_large": summarize(cell, "excess_large"),
            }
    arm_means = {}
    for arm in ARMS:
        cell = [row for row in endpoint if row["arm"] == arm]
        arm_means[arm] = {
            "loss_256": summarize(cell, "loss_256"),
            "loss_large": summarize(cell, "loss_large"),
            "excess_large": summarize(cell, "excess_large"),
        }
    native_diag = [row for row in diagnostics if row["arm"] == "native"]
    stage_fields = ["eligibility_cosine_mean", "modulation_cosine_mean", "aggregation_cosine_mean", "delivered_cosine_mean", "native_reference_norm_ratio_mean", "native_support_fraction_mean", "reference_mass_on_native_support_mean", "sign_agreement_mean", "magnitude_pearson_mean", "bound_clip_fraction", "cumulative_delivered_l2"]
    stage_summary = {field: summarize(native_diag, field) for field in stage_fields}
    trajectory_summary = {
        str(checkpoint): {field: mean([row for row in trajectories if int(row["checkpoint"]) == checkpoint], field) for field in ("eligibility_cosine", "modulation_cosine", "aggregation_cosine", "delivered_cosine", "native_support_fraction", "reference_mass_on_native_support", "sign_agreement", "magnitude_pearson")}
        for checkpoint in CHECKPOINTS[1:]
    }
    improvement = {arm: arm_means["native"]["loss_large"]["mean"] - arm_means[arm]["loss_large"]["mean"] for arm in ARMS}
    oracle_pass = arm_means["weight_oracle"]["loss_large"]["mean"] < THRESHOLD
    if arm_means["sign_ref_native_mag"]["loss_large"]["mean"] < arm_means["native"]["loss_large"]["mean"] and arm_means["sign_ref_native_mag"]["loss_large"]["mean"] <= arm_means["reference_direction_native_support"]["loss_large"]["mean"]:
        interpretation = "Sign coordination is the leading counterfactual defect within native support."
    elif arm_means["mag_ref_native_sign"]["loss_large"]["mean"] < arm_means["native"]["loss_large"]["mean"] and arm_means["mag_ref_native_sign"]["loss_large"]["mean"] <= arm_means["reference_direction_native_support"]["loss_large"]["mean"]:
        interpretation = "Magnitude allocation is the leading counterfactual defect within native support."
    elif arm_means["reference_direction_native_support"]["loss_large"]["mean"] < arm_means["native"]["loss_large"]["mean"]:
        interpretation = "Reference direction on native support improves the endpoint; native direction is the dominant shortfall."
    else:
        interpretation = "The simple sign, magnitude, and support counterfactuals do not isolate a single direction failure."
    disposition = "DIRECTION_FAILURE_ANATOMY_PARTIAL_WITH_EVALUATOR_FLOOR" if oracle_pass and arm_means["reference_direction_full_support"]["loss_large"]["mean"] < arm_means["native"]["loss_large"]["mean"] else "DIRECTION_FAILURE_ANATOMY_UNRESOLVED"
    result = {
        "schema": "FLY-REACH-01-analysis-v1", "status": "INTEGRITY_PASS", "disposition": disposition, "interpretation": interpretation,
        "arm_means": arm_means, "by_arm_substrate": by_arm_substrate, "counterfactual_improvement_vs_native": improvement,
        "native_stage_summary": stage_summary, "native_trajectory_summary": trajectory_summary,
        "oracle_large_mean_below_threshold": oracle_pass, "threshold": THRESHOLD,
        "no_biological_promotion": True, "pheno_reseal_authorized": False,
    }
    (RUN / "integrity-receipt.json").write_text(json.dumps({"schema": "FLY-REACH-01-integrity-v1", "status": "INTEGRITY_PASS", "outcome_rows": len(outcomes), "diagnostic_rows": len(diagnostics), "trajectory_rows": len(trajectories), "missing_cells": 0, "duplicate_cells": 0}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "reach01-analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (RUN / "reach01-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["arm", "loss256_mean", "loss256_competence_rate", "losslarge_mean", "excess_large_mean", "improvement_vs_native"])
        for arm in ARMS:
            stats = arm_means[arm]
            writer.writerow([arm, f"{stats['loss_256']['mean']:.9f}", f"{stats['loss_256']['competence_rate']:.6f}", f"{stats['loss_large']['mean']:.9f}", f"{stats['excess_large']['mean']:.9f}", f"{improvement[arm]:.9f}"])
    lines = [
        "# FLY-REACH-01 — Direction Failure Anatomy", "", f"Disposition: **{disposition}**", "", interpretation, "",
        "This is a sealed engineering-only follow-up to FLY-REACH-00. It does not reopen PHENO, promote a biological mechanism, or make a claim about what a fly should learn.", "",
        "## Primary endpoint", "", "The primary readout is the floor-relative large-bank loss and excess above the same-cell 128-step weight-oracle loss. The old 0.25 gate is retained descriptively; the evaluator floor is reported explicitly.", "",
        "| arm | large-bank loss | excess above oracle | 256-bank competence rate |", "|---|---:|---:|---:|",
    ]
    for arm in ARMS:
        stats = arm_means[arm]
        lines.append(f"| {arm} | {stats['loss_large']['mean']:.6f} | {stats['excess_large']['mean']:.6f} | {stats['loss_256']['competence_rate']:.1%} |")
    lines += ["", "## Native stage anatomy", "", f"- eligibility cosine: {stage_summary['eligibility_cosine_mean']['mean']:.6f}", f"- modulation cosine: {stage_summary['modulation_cosine_mean']['mean']:.6f}", f"- aggregation/native cosine: {stage_summary['aggregation_cosine_mean']['mean']:.6f}", f"- delivered cosine: {stage_summary['delivered_cosine_mean']['mean']:.6f}", f"- native support fraction: {stage_summary['native_support_fraction_mean']['mean']:.3%}", f"- reference mass on native support: {stage_summary['reference_mass_on_native_support_mean']['mean']:.3%}", f"- sign agreement on native support: {stage_summary['sign_agreement_mean']['mean']:.3%}", f"- magnitude Pearson correlation: {stage_summary['magnitude_pearson_mean']['mean']:.6f}", "", "All findings are bounded to this host, task, evaluator, and engineering counterfactuals. No biological promotion and no PHENO reseal are authorized."]
    (RUN / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "INTEGRITY_PASS", "disposition": disposition, "interpretation": interpretation}, sort_keys=True))


if __name__ == "__main__":
    main()
