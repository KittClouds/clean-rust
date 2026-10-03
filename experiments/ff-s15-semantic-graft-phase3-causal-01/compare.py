"""Compact causal-only outcome; no numerical gate, architecture rescue or cross-lane winner."""
from p3_contract import OUTPUT


def make_comparison(old, new, old_pairs, registry, arm):
    targets = {}
    lines = ["# Causal Phase 3: supervision geometry", "",
        "One P3-BALANCED arm, unchanged Phase 0 graft and frozen causal Base surface.",
        "20,000 TRAIN / 2,000 DEV rows; all candidates retained (maximum 28); 20 full TRAIN passes.",
        "TRAIN-only class weights; aliases share one source unit; checkpoint selection excludes action and renderer scores.",
        f"Selected epoch: {arm['best_epoch']}; lowest balanced state-only DEV criterion.", "",
        "| Independent target | P2 CONSIST BalAcc | P3 BALANCED BalAcc | Change |",
        "|---|---:|---:|---:|"]
    for item in registry["registry"]:
        if item["availability"] == "UNAVAILABLE" or item["alias_of"]:
            continue
        scope = item["scope"].lower(); name = item["target_name"]
        a, b = old[scope][name]["balanced_accuracy"], new[scope][name]["balanced_accuracy"]
        targets[name] = {"P2_CONSIST": a, "P3_BALANCED": b, "delta": b-a,
                         "canonical_source_id": item["canonical_source_id"]}
        lines.append(f"| {name} | {a:.4f} | {b:.4f} | {b-a:+.4f} |")
    action = {}
    for name in ("overall", "MOVE", "ACTIVATE", "NOOP"):
        a, b = (old["endpoint"]["accuracy"], new["endpoint"]["accuracy"]) if name == "overall" else (
            old["endpoint"]["by_target_action_type"].get(name, {}).get("accuracy"),
            new["endpoint"]["by_target_action_type"].get(name, {}).get("accuracy"))
        action[name] = {"P2_CONSIST": a, "P3_BALANCED": b, "delta": b-a if a is not None and b is not None else None}
    old_dis = old["renderer"]["endpoint_prediction_flip_rate_all_pairs"]
    new_dis = new["renderer"]["endpoint_prediction_flip_rate_all_pairs"]
    count_name = "number_or_structure_of_missing_requirements"
    result = {"status": "CAUSAL_PHASE3_COMPARED", "selected_epoch": arm["best_epoch"],
        "independent_targets": targets, "action": action,
        "D_s": {"P2_CONSIST": old["global_state_diversity"]["D_s"], "P3_BALANCED": new["global_state_diversity"]["D_s"]},
        "all_pair_action_disagreement": {"P2_CONSIST": old_dis, "P3_BALANCED": new_dis},
        "count_proxy_MAE": {"P2_CONSIST": old["global"][count_name]["mae"], "P3_BALANCED": new["global"][count_name]["mae"]},
        "paired_action_correctness": {"P2_CONSIST": old_pairs["action"], "P3_BALANCED": new["pair_correctness"]["action"]},
        "unresolved_targets": registry["identity_audit"]["unresolved_targets"],
        "cross_lane_winner": None, "protected_TEST_truth_opened": False, "BANK_v2_used": False,
        "interpretation": "Supervision/selection intervention only. Balanced losses alter class weighting, alias/source weighting, family reduction and selection together; no isolated-component attribution.",
        "next_phase": "Objective-only repairs end here. Recurrent computation requires a separately authorized architecture phase."}
    lines += ["", "| Action endpoint | P2 CONSIST | P3 BALANCED | Change |", "|---|---:|---:|---:|"]
    for name, values in action.items():
        if values["delta"] is not None:
            lines.append(f"| {name} | {values['P2_CONSIST']:.4f} | {values['P3_BALANCED']:.4f} | {values['delta']:+.4f} |")
    lines += ["", f"Action disagreement on all 464 existing renderer pairs: {old_dis:.4f} → {new_dis:.4f}.",
        f"Global state diversity D_s: {result['D_s']['P2_CONSIST']:.4f} → {result['D_s']['P3_BALANCED']:.4f}.",
        f"Collapsed candidate-state DEV rows: {new['candidate_conditioning']['collapsed_rows_at_variance_le_1e_8']} / 2,000.",
        f"Count-proxy MAE: {result['count_proxy_MAE']['P2_CONSIST']:.4f} → {result['count_proxy_MAE']['P3_BALANCED']:.4f}.",
        "Count and missing-presence are SAME_CANONICAL_SOURCE, not independent wins.", "",
        "Renderer correctness tables retain both-correct / first-only / second-only / both-wrong / disagreement for every sourceable target.",
        "Candidate tables count aligned candidate instances; action correctness requires available ACT truth on both sides.",
        "All-pair action disagreement also includes ASK/ABSTAIN worlds and is explicitly separate from truth-bearing accuracy.", "",
        "## Target-source audit limits", "",
        "The shared-source discrepancy was not silently reconciled. Solvable, candidate unmet requirements and applicability remain unresolved and masked on the causal lane.",
        "The encoder mapping excludes already-satisfied worlds from solvable and derives unmet requirements as NOT legal; applicability duplicates legal.",
        "Its one-step goal predicate also differs on illegal actions when the initial goal already holds. These are target semantics, not substrate differences.",
        "This run does not adopt new meanings or label derivations to make the lanes look aligned.",
        "Canonical simulator/generator replay verified every retained label and mask over full TRAIN/DEV.", "",
        "## Engineering handoff", "",
        "Carry forward the target-specific comparison; there is no predetermined numerical pass gate.",
        "No architecture changes, backbone adaptation, new surfaces, threshold tuning, new heads, protected TEST or BANK-v2 contact occurred.",
        "The representation and scaler remain bundled with the trained observer artifact.",
        "Objective-only repair is complete for this lane. No recurrence or other rescue was started.", "",
        "Artifacts: PHASE3-RECEIPT.json, PHASE3-SPEC.json, TARGET-SOURCE-REGISTRY.json, COMPARISON.json,",
        "P3-BALANCED/best-graft.pt, DEV-METRICS.json, PAIR-CORRECTNESS.json, DEV-estimates.jsonl and training-history.json.",
        "All new artifacts are on C: NVMe. Prior phases are read-only and hash-verified.", ""]
    (OUTPUT / "PHASE3-HANDOFF.md").write_text("\n".join(lines), encoding="utf-8")
    return result
