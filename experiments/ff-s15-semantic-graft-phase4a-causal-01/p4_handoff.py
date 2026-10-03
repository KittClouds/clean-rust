"""Compact lane-local interpretation and human-readable Phase 4A handoff."""
from __future__ import annotations

import json
from pathlib import Path

from p4_contract import write_json


def _metric(report, scope, name, key="balanced_accuracy"):
    item = report[scope].get(name, {})
    return item.get(key) if item.get("available", True) else None


def _delta(a, b):
    if a is None or b is None:
        return None
    return float(b - a)


def make_handoff(output: Path, reports: dict, curve: dict, arm: dict):
    zero, final = reports["0"], reports["4"]
    action0, action4 = zero["endpoint"], final["endpoint"]
    acc0, acc4 = action0.get("accuracy"), action4.get("accuracy")
    move0 = action0.get("by_target_action_type", {}).get("MOVE", {}).get("accuracy")
    move4 = action4.get("by_target_action_type", {}).get("MOVE", {}).get("accuracy")
    action_delta, move_delta = _delta(acc0, acc4), _delta(move0, move4)

    semantic_rows, candidate_rows = [], []
    for name in sorted(set(zero["global"]) | set(final["global"])):
        a, b = _metric(zero, "global", name), _metric(final, "global", name)
        if a is not None or b is not None:
            semantic_rows.append({"target": name, "Z0_balanced_accuracy": a,
                                  "Z4_balanced_accuracy": b, "delta": _delta(a, b)})
    for name in sorted(set(zero["candidate"]) | set(final["candidate"])):
        a, b = _metric(zero, "candidate", name), _metric(final, "candidate", name)
        if a is not None or b is not None:
            candidate_rows.append({"target": name, "Z0_balanced_accuracy": a,
                                   "Z4_balanced_accuracy": b, "delta": _delta(a, b)})

    if action_delta is not None and action_delta > 0:
        disposition = "ACTION_ENDPOINT_IMPROVED"
    elif action_delta is not None and action_delta < 0:
        disposition = "ACTION_ENDPOINT_REGRESSED"
    else:
        disposition = "ACTION_ENDPOINT_UNCHANGED_OR_UNAVAILABLE"
    any_state_gain = any(row["delta"] is not None and row["delta"] > 0
                         for row in semantic_rows + candidate_rows)
    any_state_loss = any(row["delta"] is not None and row["delta"] < 0
                         for row in semantic_rows + candidate_rows)
    if disposition == "ACTION_ENDPOINT_IMPROVED" and any_state_loss:
        interpretation = "ACTION_GAIN_WITH_STATE_TRADEOFF"
    elif disposition == "ACTION_ENDPOINT_IMPROVED":
        interpretation = "ITERATIVE_COMPUTATION_IMPROVED_ACTION"
    elif any_state_gain:
        interpretation = "STATE_MOTION_WITHOUT_ACTION_GAIN"
    elif disposition == "ACTION_ENDPOINT_REGRESSED":
        interpretation = "RECURRENT_CONSTRUCTION_REGRESSED_ACTION"
    else:
        interpretation = "NO_OBSERVED_ENDPOINT_OR_STATE_GAIN"

    result = {"schema": "frozen-fabrique.semantic-graft-phase4a-causal-handoff/v1",
        "disposition": interpretation, "action_endpoint": {
            "Z0_accuracy": acc0, "Z4_accuracy": acc4, "Z4_minus_Z0": action_delta,
            "MOVE_Z0_accuracy": move0, "MOVE_Z4_accuracy": move4,
            "MOVE_Z4_minus_Z0": move_delta,
            "by_type_Z0": action0.get("by_target_action_type", {}),
            "by_type_Z4": action4.get("by_target_action_type", {})},
        "global_targets": semantic_rows, "candidate_targets": candidate_rows,
        "depth_curve_sha256_bound_in_arm_receipt": arm["depth_curve_sha256"],
        "update_magnitude": curve["update_magnitude"],
        "latency": curve["inference_latency"],
        "renderer_correctness": {"Z0": curve["depths"]["0"]["renderer_correctness"],
                                 "Z4": curve["depths"]["4"]["renderer_correctness"]},
        "scope": "Descriptive causal-lane outcome only; no cross-lane comparison or promotion threshold"}
    write_json(output / "PHASE4A-HANDOFF.json", result)

    def fmt(value):
        return "n/a" if value is None else f"{value:.4f}"

    lines = ["# System 1.5 Semantic Graft — Causal Phase 4A", "",
        f"**Disposition:** `{interpretation}`", "",
        "The causal lane ran one shared-weight T=4 recurrent arm over the frozen P2-CONSIST graft. "
        "P3-BALANCED remained a separate reference. No protected TEST truth or BANK-v2 was used.", "",
        "## Action endpoint", "",
        "| Measure | Z0 / P2-CONSIST | Z4 / R4 | Change |", "|---|---:|---:|---:|",
        f"| Overall accuracy | {fmt(acc0)} | {fmt(acc4)} | {fmt(action_delta)} |",
        f"| MOVE accuracy | {fmt(move0)} | {fmt(move4)} | {fmt(move_delta)} |"]
    action_types = sorted(set(action0.get("by_target_action_type", {})) |
                          set(action4.get("by_target_action_type", {})) | {"MOVE", "ACTIVATE", "NOOP"})
    for kind in action_types:
        a = action0.get("by_target_action_type", {}).get(kind, {}).get("accuracy")
        b = action4.get("by_target_action_type", {}).get(kind, {}).get("accuracy")
        lines.append(f"| {kind} | {fmt(a)} | {fmt(b)} | {fmt(_delta(a, b))} |")
    lines += ["", "## State targets", "", "Balanced accuracy by target; aliases and unavailable sources retain the frozen Phase 2 semantics.", "",
        "| Scope | Target | Z0 | Z1 | Z2 | Z3 | Z4 | Z4 − Z0 |", "|---|---|---:|---:|---:|---:|---:|---:|"]
    for scope, key in (("global", "global"), ("candidate", "candidate")):
        names = sorted(set().union(*(set(reports[str(t)][scope]) for t in range(5))))
        for name in names:
            values = [_metric(reports[str(t)], scope, name) for t in range(5)]
            if not any(value is not None for value in values):
                continue
            lines.append("| " + " | ".join([key, name] + [fmt(v) for v in values] +
                [fmt(_delta(values[0], values[4]))]) + " |")
    lines += ["", "## State and renderer diagnostics", "",
        f"- D_s by depth: " + ", ".join(f"Z{t}={curve['depths'][str(t)]['D_s']:.6g}" for t in range(5)),
        f"- Candidate conditioning at Z4: `{json.dumps(curve['depths']['4']['candidate_conditioning'], sort_keys=True)}`",
        "- Renderer paired correctness decompositions are recorded separately for Z0 and Z4 in `DEPTH-CURVE.json`.",
        f"- Update RMS: `{json.dumps(curve['update_magnitude'], sort_keys=True)}`", "",
        "## Cost", "",
        f"- Trainable recurrent/output parameters: {arm['trainable_recurrent_parameters']:,}",
        f"- Training time: {arm['training_seconds']:.1f} seconds", 
        f"- Peak allocated GPU memory: {arm['peak_GPU_allocated_bytes']:,} bytes",
        f"- Inference timings: `{json.dumps(curve['inference_latency'], sort_keys=True)}`", "",
        "## Interpretation", "",
        "This is a lane-local engineering result with no fixed numerical promotion threshold. "
        "Use the depth curve and per-target changes above to distinguish useful computation from state motion. "
        "It does not establish a causal-versus-encoder winner.", ""]
    (output / "PHASE4A-HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    return result
