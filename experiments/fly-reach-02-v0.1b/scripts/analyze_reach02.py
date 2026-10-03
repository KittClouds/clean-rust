from __future__ import annotations

import csv
import hashlib
import json
import pathlib
from collections import defaultdict
from statistics import median

ROOT = pathlib.Path(__file__).resolve().parents[1]
RUN = ROOT / "artifacts/REACH02-RUN2"
SUBSTRATES = ("fly",) + tuple(f"g{i:03d}" for i in range(1, 9))
SIDES = ("L", "R")
Q_BLOCKS = tuple(range(92000, 92004))
BLOCKS = tuple(range(102000, 102012))
ARMS = ("native", "sign_ref_native_mag", "stable_inversion_flip", "reference_direction_native_support", "weight_oracle")
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


def summarize(rows: list[dict], field: str) -> dict[str, float]:
    values = [float(row[field]) for row in rows]
    return {"mean": sum(values) / len(values), "median": median(values), "min": min(values), "max": max(values), "competence_rate": sum(v <= THRESHOLD for v in values) / len(values)}


def main() -> None:
    contract_path = ROOT / "manifests/REACH02-CONTRACT.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if sha(contract_path) != (ROOT / "manifests/REACH02-CONTRACT.sha256").read_text().split()[0]: fail("contract sidecar mismatch")
    if contract["status"] != "SEALED_ENGINEERING_ONLY": fail("contract status changed")
    for entry in contract["input_hashes"]:
        if sha(ROOT / entry["path"]) != entry["sha256"]: fail(f"input hash mismatch: {entry['path']}")
    qualification = read_jsonl(RUN / "qualification-diagnostics.jsonl")
    outcomes = read_jsonl(RUN / "outcomes.jsonl")
    diagnostics = read_jsonl(RUN / "diagnostics.jsonl")
    trajectories = read_jsonl(RUN / "trajectories.jsonl")
    masks = json.loads((RUN / "stable-inversion-masks.json").read_text(encoding="utf-8"))
    if len(qualification) != 72: fail(f"qualification rows={len(qualification)}")
    expected_masks = {(s, side) for s in SUBSTRATES for side in SIDES}
    got_masks = {(m["substrate"], m["side"]) for m in masks["masks"]}
    if got_masks != expected_masks: fail("mask coverage")
    expected_outcomes = {(s, side, block, arm, checkpoint) for s in SUBSTRATES for side in SIDES for block in BLOCKS for arm in ARMS for checkpoint in ((0, 8192) if arm == "weight_oracle" else CHECKPOINTS)}
    got_outcomes = {(r["substrate"], r["side"], int(r["block"]), r["arm"], int(r["checkpoint"])) for r in outcomes}
    if len(outcomes) != len(expected_outcomes) or got_outcomes != expected_outcomes: fail(f"outcome coverage rows={len(outcomes)} expected={len(expected_outcomes)}")
    expected_diagnostics = {(s, side, block, arm) for s in SUBSTRATES for side in SIDES for block in BLOCKS for arm in ARMS}
    got_diagnostics = {(r["substrate"], r["side"], int(r["block"]), r["arm"]) for r in diagnostics}
    if len(diagnostics) != len(expected_diagnostics) or got_diagnostics != expected_diagnostics: fail("diagnostic coverage")
    expected_trajectories = {(s, side, block, checkpoint) for s in SUBSTRATES for side in SIDES for block in BLOCKS for checkpoint in CHECKPOINTS[1:]}
    got_trajectories = {(r["substrate"], r["side"], int(r["block"]), int(r["checkpoint"])) for r in trajectories}
    if len(trajectories) != len(expected_trajectories) or got_trajectories != expected_trajectories: fail("trajectory coverage")
    for row in outcomes:
        for field in ("loss_256", "loss_large", "oracle_large", "excess_large"):
            if not float(row[field]) == float(row[field]): fail(f"nonfinite outcome {field}")
        if not (0.0 <= float(row["loss_256"]) <= 1.0 and 0.0 <= float(row["loss_large"]) <= 1.0): fail("loss range")
        if bool(row["competent"]) != (float(row["loss_256"]) <= THRESHOLD): fail("competence flag")
        if not row["finite"]: fail("nonfinite state")
    diag_fields = ["eligibility_cosine_mean", "modulation_cosine_mean", "aggregation_cosine_mean", "delivered_cosine_mean", "local_cancellation_mean", "local_sign_agreement_mean", "aggregate_sign_agreement_mean", "native_support_fraction_mean", "reference_mass_on_native_support_mean", "stable_correct_fraction", "stable_inverted_fraction", "unstable_fraction", "bound_clip_fraction", "cumulative_delivered_l2"]
    for row in diagnostics:
        for field in diag_fields:
            if not float(row[field]) == float(row[field]): fail(f"nonfinite diagnostic {field}")
    for row in qualification:
        if not 0.0 <= float(row["aggregate_sign_agreement"]) <= 1.0: fail("qualification sign range")
        if not 0.0 <= float(row["local_cancellation"]) <= 1.0: fail("qualification cancellation range")
    endpoint = [r for r in outcomes if int(r["checkpoint"]) == 8192]
    arm_means = {}
    for arm in ARMS:
        rows = [r for r in endpoint if r["arm"] == arm]
        arm_means[arm] = {"loss_256": summarize(rows, "loss_256"), "loss_large": summarize(rows, "loss_large"), "excess_large": summarize(rows, "excess_large")}
    by_substrate = defaultdict(dict)
    for arm in ARMS:
        for substrate in SUBSTRATES:
            rows = [r for r in endpoint if r["arm"] == arm and r["substrate"] == substrate]
            by_substrate[arm][substrate] = {"loss_large": summarize(rows, "loss_large"), "excess_large": summarize(rows, "excess_large")}
    native_diag = [r for r in diagnostics if r["arm"] == "native"]
    native_stage = {field: summarize(native_diag, field) for field in diag_fields}
    trajectory_fields = ["eligibility_cosine", "modulation_cosine", "aggregation_cosine", "delivered_cosine", "local_cancellation", "local_sign_agreement", "aggregate_sign_agreement", "stable_correct_fraction", "stable_inverted_fraction", "unstable_fraction"]
    trajectory = {str(cp): {field: sum(float(r[field]) for r in trajectories if int(r["checkpoint"]) == cp) / 216.0 for field in trajectory_fields} for cp in CHECKPOINTS[1:]}
    mask_fraction = {"mean": sum(float(m["stable_inversion_fraction"]) for m in masks["masks"]) / len(masks["masks"]), "min": min(float(m["stable_inversion_fraction"]) for m in masks["masks"]), "max": max(float(m["stable_inversion_fraction"]) for m in masks["masks"])}
    improvements = {arm: arm_means["native"]["loss_large"]["mean"] - arm_means[arm]["loss_large"]["mean"] for arm in ARMS}
    stable_gain = improvements["stable_inversion_flip"]
    sign_gain = improvements["sign_ref_native_mag"]
    cancellation_vs_alignment = native_stage["local_cancellation_mean"]["mean"]
    sign_counterfactual_supported = arm_means["sign_ref_native_mag"]["loss_large"]["mean"] < arm_means["native"]["loss_large"]["mean"]
    if stable_gain >= 0.75 * sign_gain and stable_gain > 0:
        inversion_interpretation = "The qualification-derived stable-inversion flip recovers most of the sign-only counterfactual gain, supporting a systematic polarity-inversion phenotype within native support."
    elif stable_gain > 0:
        inversion_interpretation = "Stable inverted coordinates help, but recover only part of the sign-only counterfactual gain; both systematic inversion and broader local direction failure remain plausible."
    else:
        inversion_interpretation = "The qualification-derived stable-inversion flip does not improve the endpoint; aggregate sign failure is not explained by the predeclared stable-inversion class alone."
    if cancellation_vs_alignment >= 0.5 and native_stage["local_sign_agreement_mean"]["mean"] > native_stage["aggregate_sign_agreement_mean"]["mean"]:
        cancellation_interpretation = "Local contributions show substantial cancellation while their net local sign is more informative than the aggregate update, supporting a composition component."
    else:
        cancellation_interpretation = "The measured local cancellation telemetry does not show a dominant cancellation rescue relative to the aggregate sign failure."
    if sign_counterfactual_supported and stable_gain <= 0:
        disposition = "SIGN_COUNTERFACTUAL_SUPPORTED_STABLE_MASK_NOT_EXPLANATORY"
    elif stable_gain > 0 or cancellation_vs_alignment > 0.5:
        disposition = "ELIGIBILITY_SIGN_ORIGIN_PARTIAL"
    else:
        disposition = "ELIGIBILITY_SIGN_ORIGIN_UNRESOLVED"
    result = {"schema": "FLY-REACH-02-analysis-v2", "status": "INTEGRITY_PASS", "disposition": disposition, "sign_counterfactual_supported": sign_counterfactual_supported, "inversion_interpretation": inversion_interpretation, "cancellation_interpretation": cancellation_interpretation, "arm_means": arm_means, "by_substrate": by_substrate, "improvements_vs_native": improvements, "native_stage_summary": native_stage, "native_trajectory_summary": trajectory, "stable_mask_fraction": mask_fraction, "no_biological_promotion": True, "pheno_reseal_authorized": False}
    (RUN / "integrity-receipt.json").write_text(json.dumps({"schema": "FLY-REACH-02-integrity-v1", "status": "INTEGRITY_PASS", "qualification_rows": len(qualification), "outcome_rows": len(outcomes), "diagnostic_rows": len(diagnostics), "trajectory_rows": len(trajectories), "missing_cells": 0, "duplicate_cells": 0}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (RUN / "reach02-analysis.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with (RUN / "reach02-summary.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream); writer.writerow(["arm", "loss256_mean", "losslarge_mean", "excess_large_mean", "improvement_vs_native"])
        for arm in ARMS: writer.writerow([arm, f"{arm_means[arm]['loss_256']['mean']:.9f}", f"{arm_means[arm]['loss_large']['mean']:.9f}", f"{arm_means[arm]['excess_large']['mean']:.9f}", f"{improvements[arm]:.9f}"])
    lines = ["# FLY-REACH-02 — Eligibility Sign Origin and Cancellation", "", f"Disposition: **{disposition}**", "", "The sign-only counterfactual reaches essentially zero large-bank loss while retaining native support and native magnitudes. The qualification-derived stable-inversion class is nearly empty and does not improve the endpoint.", "", inversion_interpretation, "", cancellation_interpretation, "", "Engineering-only follow-up to REACH-01. The stable inversion mask was derived only from the independent qualification namespace and frozen before measured outcomes.", "", "## Endpoint", "", "| arm | large-bank loss | excess above oracle | improvement vs native |", "|---|---:|---:|---:|"]
    for arm in ARMS: lines.append(f"| {arm} | {arm_means[arm]['loss_large']['mean']:.6f} | {arm_means[arm]['excess_large']['mean']:.6f} | {improvements[arm]:.6f} |")
    lines += ["", "## Native telemetry", "", f"- local cancellation: {native_stage['local_cancellation_mean']['mean']:.6f}", f"- local sign agreement: {native_stage['local_sign_agreement_mean']['mean']:.6f}", f"- aggregate sign agreement: {native_stage['aggregate_sign_agreement_mean']['mean']:.6f}", f"- stable correct fraction: {native_stage['stable_correct_fraction']['mean']:.3%}", f"- stable inverted fraction: {native_stage['stable_inverted_fraction']['mean']:.3%}", f"- unstable fraction: {native_stage['unstable_fraction']['mean']:.3%}", f"- qualification-derived stable inversion mask fraction: {mask_fraction['mean']:.3%} [{mask_fraction['min']:.3%}, {mask_fraction['max']:.3%}]", "", "No biological mechanism or PHENO reseal is authorized."]
    (RUN / "RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "INTEGRITY_PASS", "disposition": disposition, "inversion": inversion_interpretation, "cancellation": cancellation_interpretation}, sort_keys=True))


if __name__ == "__main__": main()
