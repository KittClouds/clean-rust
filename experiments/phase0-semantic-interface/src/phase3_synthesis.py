"""Phase 3 synthesis: P3-BALANCED against the frozen Phase 2 CONSIST artifact, and an
explicit classification into Outcome A / B / C.

No numerical success gate is installed. The outcome is reported, and a failure is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

P2 = Path(r"D:\codex-runs\encoder-contrast-01\phase2\consist\phase2-consist-receipt.json")
P3 = Path(r"D:\codex-runs\encoder-contrast-01\phase3\balanced\phase3-balanced-receipt.json")
REG = Path(r"D:\codex-runs\encoder-contrast-01\phase3\target-source-registry.json")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase3")

GLOBAL_SRC = ["SRC-SOLVABILITY", "SRC-GOAL-SATISFIED", "SRC-MISSING-INFO-PANEL",
              "SRC-CONTRADICTION-PANEL"]
CAND_SRC = ["SRC-CANDIDATE-LEGALITY", "SRC-CANDIDATE-SATISFIES-GOAL"]


def main() -> int:
    p2 = json.loads(P2.read_text())
    p3 = json.loads(P3.read_text())
    reg = json.loads(REG.read_text())
    p2g, p2c = p2["per_target_dev_metrics"]["global"], p2["per_target_dev_metrics"]["candidate"]
    p2map = {"SRC-SOLVABILITY": p2g["solvable"]["balanced_accuracy"],
             "SRC-GOAL-SATISFIED": p2g["goal_satisfied"]["balanced_accuracy"],
             "SRC-MISSING-INFO-PANEL": p2g["missing_information_present"]["balanced_accuracy"],
             "SRC-CONTRADICTION-PANEL": p2g["contradiction_present"]["balanced_accuracy"],
             "SRC-CANDIDATE-LEGALITY": p2c["candidate_legal"]["balanced_accuracy"],
             "SRC-CANDIDATE-SATISFIES-GOAL": p2c["candidate_satisfies_goal"]["balanced_accuracy"]}
    src = p3["per_source_dev_metrics"]

    above = {s: src[s]["balanced_accuracy"] for s in GLOBAL_SRC
             if "balanced_accuracy" in src[s]}
    # "Materially above trivial" is decided by the PRE-REGISTERED margin already baked into the
    # metric (balanced accuracy must exceed max(pi, 1-pi) by more than 0.01), not by a threshold
    # chosen after seeing the numbers. contradiction_present scores 0.5202 while predicting
    # almost everything positive (accuracy 0.1855) and fails that margin; it is noise, not a rise.
    material = {s: v for s, v in above.items() if src[s]["beats_base_rate"]}
    cand_before, cand_after = p2map["SRC-CANDIDATE-LEGALITY"], \
        src["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"]
    e3 = p3["endpoint_metrics"]
    hist = p3["training_history"]

    dec = p3["diagnostics"]["renderer_correctness_decomposition"]
    vacuous = {k: v for k, v in dec["global"].items() if v["disagreement"] == 0}
    live = {k: v for k, v in dec["global"].items() if v["disagreement"] > 0}

    outcome = ("A" if material else
               "C" if cand_after < cand_before - 0.01 else "B")

    rec = {
        "abi": "phase3-semantic-interface/synthesis-v0.1",
        "lane": "bidirectional (Lepori)",
        "question": "When supervision and checkpoint selection are aligned with the balanced "
                    "semantic distinctions we actually care about, can the existing graft learn "
                    "stronger semantic/candidate state without changing its architecture?",
        "comparator": "frozen Phase 2 CONSIST artifact; not retrained",
        "target_source_identity": {
            "n_ontology_heads": reg["n_global_groups"] * 0 + len(reg["registry"]),
            "n_independent_sources": reg["n_global_groups"] + reg["n_candidate_groups"],
            "independent_global_groups": reg["independent_global_source_groups"],
            "independent_candidate_groups": reg["independent_candidate_source_groups"],
            "aliases_verified_numerically": {
                k: v for k, v in reg["identity_checks"].items()
                if isinstance(v, dict) and "mismatches_TRAIN" in v
            },
            "lane_discrepancy_resolved": "solvable and candidate_has_unmet_requirements are "
                                         "derived from the shared executable simulator and are "
                                         "AVAILABLE for every substrate. Any lane reporting "
                                         "them unavailable has a mapping discrepancy, not a "
                                         "substrate property. Resolved from the canonical source; "
                                         "no derivation invented, no meaning changed.",
            "left_unresolved": reg["identity_stop"]["targets_left_unresolved"],
        },
        "global_sources": {
            s: {"P2_balanced_accuracy": p2map[s],
                "P3_balanced_accuracy": src[s]["balanced_accuracy"],
                "P3_accuracy": src[s]["accuracy"],
                "P3_macro_f1": src[s]["macro_f1"],
                "P3_positive_f1": src[s]["positive_f1"],
                "P3_negative_f1": src[s]["negative_f1"],
                "P3_support_pos": src[s]["support_pos"],
                "P3_support_neg": src[s]["support_neg"],
                "train_prevalence": src[s]["train_prevalence"],
                "beats_base_rate": src[s]["beats_base_rate"]}
            for s in GLOBAL_SRC},
        "candidate_sources": {
            s: {"P2_balanced_accuracy": p2map[s],
                "P3_balanced_accuracy": src[s]["balanced_accuracy"],
                "P3_macro_f1": src[s]["macro_f1"],
                "train_prevalence": src[s]["train_prevalence"],
                "beats_base_rate": src[s]["beats_base_rate"]}
            for s in CAND_SRC},
        "aliases": {k: {"balanced_accuracy": v.get("balanced_accuracy"),
                        "SAME_CANONICAL_SOURCE": v.get("SAME_CANONICAL_SOURCE"),
                        "counted_as_independent_win": False}
                    for k, v in p3["alias_dev_metrics"].items()},
        "endpoint": {
            "P2_top1": p2["per_target_dev_metrics"]["endpoint"].get("action_top1_accuracy"),
            "P3_top1": e3.get("action_top1_accuracy"), "chance": e3["chance"],
            "by_action_type_P3": e3.get("by_action_type"),
            "by_action_type_P2": p2["per_target_dev_metrics"]["endpoint"].get("by_action_type"),
            "folded_into_state_score": False,
        },
        "renderer_correctness_decomposition": {
            "per_target": dec,
            "vacuous_stability": {
                "targets": sorted(vacuous), "finding":
                    "these global heads show ZERO disagreement across all 332 meaning-preserving "
                    "pairs, but their paired accuracy equals the majority-class rate. Perfect "
                    "renderer stability earned by predicting one class for everything. This is "
                    "exactly what the decomposition was added to expose.",
            },
            "live_instability": {
                "targets": sorted(live), "finding":
                    "the global heads that actually vary across renderers disagree on a large "
                    "fraction of pairs and score far BELOW trivial, so where there is real "
                    "variation the predictions are also unstable.",
            },
        },
        "state_diagnostics": {
            "D_s_P3_frozen_checkpoint": p3["diagnostics"]["D_s"]["value"],
            "D_s_P3_epoch8": hist[-1]["D_s"],
            "D_s_P2_frozen_checkpoint": p2["diagnostics"]["D_s"]["value"],
            "variance_floor_target": 0.0558,
            "candidate_conditioning": p3["diagnostics"]["candidate_conditioning"],
            "interpretation": "variance rules out collapse; it is not evidence of usefulness. "
                              "Phase 2 already established D_s>0 does not imply semantic "
                              "discrimination, and Phase 3 reproduces that at higher D_s.",
        },
        "selection_rule": {
            "new_criterion": "J_select = 0.5 J_S + 0.5 J_E, balanced DEV BCE, unique source "
                             "groups, aliases counted once, action and renderer excluded",
            "best_epoch": p3["selection_rule"]["best_epoch"],
            "J_select_trajectory": [h["J_select"] for h in hist],
            "J_S_trajectory": [h["J_S"] for h in hist],
            "J_E_trajectory": [h["J_E"] for h in hist],
            "key_finding": "the new rule STILL selects epoch 1. So the prior-dominated selection "
                           "rule was a real defect worth fixing, but it was NOT the cause of the "
                           "flat trajectory: J_S sits at ~0.696, which is ln(2), the balanced-BCE "
                           "value of a constant predictor, at every epoch.",
            "implication": "removing the prior-prediction attractor did not wake the global "
                           "pathway. The 0.500 balanced accuracy of Phases 1-2 was never a "
                           "class-imbalance artifact; it is genuine non-discrimination.",
        },
        "already_earned_capabilities": {
            "candidate_legality_before": cand_before,
            "candidate_legality_after": cand_after,
            "preserved_and_slightly_improved": bool(cand_after >= cand_before),
            "alias_heads_agree_exactly": all(
                abs(v.get("balanced_accuracy", 0)
                    - src["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy"]) < 1e-9
                for k, v in p3["alias_dev_metrics"].items()
                if k in ("candidate_applicable", "candidate_has_unmet_requirements")),
        },
        "outcome": outcome,
        "outcome_meaning": {
            "A": "encoder global semantic targets rise materially above trivial",
            "B": "encoder s remains diverse but global targets stay at 0.500 under balanced "
                 "supervision -> STOP LOSS SURGERY; proceed to recurrent model-internal "
                 "computation",
            "C": "balanced supervision harms already-earned capabilities without waking the "
                 "global state",
        }[outcome],
        "verdict": {
            "global_targets_rose_above_trivial": bool(material),
            "materiality_criterion": "balanced accuracy must exceed max(pi_TRAIN, 1-pi_TRAIN) by "
                                     "more than 0.01, the margin pre-registered in the metric "
                                     "code. Not a threshold chosen after seeing results.",
            "near_miss_not_counted": {
                s: {"balanced_accuracy": above[s], "accuracy": src[s]["accuracy"],
                    "beats_base_rate": src[s]["beats_base_rate"],
                    "why": "balanced accuracy 0.52 is reached only by predicting nearly one "
                           "class; ordinary accuracy 0.1855 is far below the 0.921 majority "
                           "rate. This is a degenerate operating point, not semantic learning."}
                for s, v in above.items() if not src[s]["beats_base_rate"] and v > 0.5},
            "detail": {k: v for k, v in above.items()},
            "candidate_capability_preserved": bool(cand_after >= cand_before),
            "endpoint_above_chance": bool(e3.get("action_top1_accuracy", 0) > e3["chance"]),
            "conclusion": "OUTCOME B. Balanced supervision geometry, unique-source weighting and "
                          "a correct selection rule together did NOT wake the global pathway, "
                          "while already-earned candidate legality was preserved and slightly "
                          "improved (0.7328 -> 0.7509). Per the Phase 3 charter this is the "
                          "signal to stop loss surgery: the one-pass global pathway has had its "
                          "fair shot under three successive objectives.",
        },
        "phase4_implication": "Phase 4 earns recurrent latent refinement H -> Z_0 -> ... -> Z_T "
                              "with shared weights, for this lane's job: turn richly contextual "
                              "candidate structure into a usable global state and an action "
                              "computation. Not more loss surgery, not a covariance penalty, not "
                              "substrate or interface changes.",
        "not_proposed": "No rescue tuning, no focal or class-weight sweep, no threshold tuning, "
                        "no covariance penalty, no recurrence in this phase, no backbone LoRA, "
                        "no BANK-v2, no protected TEST.",
        "protected": p3["protected"],
    }
    p = OUT / "phase3-synthesis.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({"written": str(p), "outcome": outcome,
                      "global_above_trivial": bool(material),
                      "detail": {k: v for k, v in above.items()},
                      "candidate_legality": [cand_before, cand_after],
                      "endpoint": [p2["per_target_dev_metrics"]["endpoint"]
                                   .get("action_top1_accuracy"),
                                   e3.get("action_top1_accuracy"), e3["chance"]],
                      "best_epoch": p3["selection_rule"]["best_epoch"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
