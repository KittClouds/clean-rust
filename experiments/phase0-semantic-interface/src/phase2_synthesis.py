"""Phase 2 synthesis: compare P2-BASE against P2-CONSIST and answer the lane's question.

    Can the existing graft learn renderer-stable semantic and action state when invariance is
    enforced without directly rewarding latent collapse?

Both arms share one Phase 0 initialization and one exhaustive-candidate input contract, so the
only difference between them is the training objective.
"""
from __future__ import annotations

import json
from pathlib import Path

OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase2")
P1 = Path(r"D:\codex-runs\encoder-contrast-01\phase1\phase1-bidirectional-receipt.json")


def main() -> int:
    arms = {a: json.loads((OUT / a / f"phase2-{a}-receipt.json").read_text())
            for a in ("base", "consist")}
    pre = json.loads((OUT / "candidate-preflight.json").read_text())
    p1 = json.loads(P1.read_text())
    b, c = arms["base"], arms["consist"]
    bg, cg = b["per_target_dev_metrics"]["global"], c["per_target_dev_metrics"]["global"]
    bc, cc = b["per_target_dev_metrics"]["candidate"], c["per_target_dev_metrics"]["candidate"]
    be, ce = b["per_target_dev_metrics"]["endpoint"], c["per_target_dev_metrics"]["endpoint"]
    bd, cd = b["diagnostics"], c["diagnostics"]
    sig0 = c["variance_reference"]["mean_sigma0"]
    floor = 0.5 * sig0
    hb, hc = b["training_history"], c["training_history"]
    raw_var = hc[-1].get("L_var", 0.0)

    def g(d, k, f="balanced_accuracy"):
        return d[k].get(f)

    rec = {
        "abi": "phase2-semantic-interface/synthesis-v0.1",
        "lane": "bidirectional (Lepori)",
        "question": "Can the existing graft learn renderer-stable semantic and action state when "
                    "invariance is enforced without directly rewarding latent collapse?",
        "candidate_preflight": {
            "m_max_measured": pre["m_max"],
            "phase1_cap": pre["phase1_cap"],
            "phase1_lost_anything": pre["phase1_truncated_anything"],
            "rows_phase1_could_not_represent": pre["combined"]["rows_excluded_by_cap"],
            "candidates_never_reachable_in_phase1": pre["combined"]["candidates_never_reachable"],
            "mechanism": "data.build() DROPPED the whole row when len(available_actions) > 24, so "
                         "this was whole-row exclusion, not partial truncation",
            "phase2_contract": "m_cap=28, every canonical candidate retained, nothing truncated",
        },
        "controlled_comparison": {
            "shared_initialization": "phase0-init.pt (identical weights in both arms)",
            "shared_input_contract": "m_cap=28, 20,000 TRAIN / 2,000 DEV canonical",
            "shared_hyperparameters": "AdamW 3e-4 cosine, bs 64, 8 epochs, seed 0",
            "only_difference": "training objective",
            "tuned_from_DEV": False,
        },
        "headline": {
            "did_s_cease_collapsing": True,
            "D_s_base": bd["D_s"]["value"],
            "D_s_consist": cd["D_s"]["value"],
            "ratio_at_frozen_checkpoint": round(cd["D_s"]["value"] / bd["D_s"]["value"], 2),
            "D_s_consist_epoch8": hc[-1]["D_s"],
            "D_s_base_epoch8": hb[-1]["D_s"],
            "ratio_at_epoch8": round(hc[-1]["D_s"] / hb[-1]["D_s"], 2),
            "sigma0_untrained_reference": sig0,
            "variance_floor_target": round(floor, 6),
            "floor_cleared_by_epoch": next((r["epoch"] for r in hc
                                            if r["D_s"] >= floor), None),
            "did_any_global_target_rise_above_trivial": False,
            "did_action_endpoint_beat_chance": bool(
                ce.get("action_top1_accuracy", 0) > ce["chance"]),
        },
        "global_targets_balanced_accuracy": {
            k: {"base": g(bg, k), "consist": g(cg, k), "base_rate": bg[k].get("base_rate"),
                "consist_beats_base_rate": cg[k].get("beats_base_rate"),
                "consist_macro_f1": cg[k].get("macro_f1"),
                "consist_positive_f1": cg[k].get("positive_f1")}
            for k in cg if "balanced_accuracy" in cg[k]
        },
        "count_target": {
            k: {"base_mae": bg[k].get("mae"), "consist_mae": cg[k].get("mae"),
                "consist_exact_count": cg[k].get("exact_count_accuracy"),
                "trivial_exact_count": cg[k].get("trivial_exact_count"),
                "consist_beats_trivial": cg[k].get("beats_trivial")}
            for k in cg if "mae" in cg[k]
        },
        "candidate_targets_balanced_accuracy": {
            k: {"base": g(bc, k), "consist": g(cc, k), "base_rate": bc[k].get("base_rate"),
                "phase1_cap24_reference": p1["per_target_dev_metrics"]["candidate"]
                .get(k, {}).get("balanced_accuracy"),
                "consist_beats_base_rate": cc[k].get("beats_base_rate")}
            for k in cc if not k.startswith("_")
        },
        "action_endpoint": {
            "base_top1": be.get("action_top1_accuracy"),
            "consist_top1": ce.get("action_top1_accuracy"),
            "chance": ce["chance"],
            "coverage": ce["coverage"],
            "by_action_type_base": be.get("by_action_type"),
            "by_action_type_consist": ce.get("by_action_type"),
        },
        "renderer_stability": {
            "WARNING": "renderer stability is CONFOUNDED BY COLLAPSE in this comparison. A "
                       "degenerate constant model is perfectly renderer-stable for the wrong "
                       "reason. Read these numbers together with D_s, never alone.",
            "base": bd["renderer_disagreement"],
            "consist": cd["renderer_disagreement"],
            "reading": "S disagreement is 0.0 in both arms, but in both arms every global head "
                       "predicts a single class for all 2,000 DEV rows, so S stability is "
                       "vacuous rather than earned. E and A disagreement are HIGHER in CONSIST "
                       "precisely because its predictions are less collapsed.",
        },
        "candidate_conditioning": {
            "base": bd["candidate_conditioning"],
            "consist": cd["candidate_conditioning"],
            "reading": "conditioning survives in both arms; the ratio falls because CONSIST's e "
                       "is less extremely peaked per candidate",
        },
        "attribution": {
            "what_actually_moved_D_s": "REMOVING the raw latent term. L_var is numerically "
                                       f"negligible at its frozen weight: unweighted L_var="
                                       f"{raw_var}, weighted contribution 0.05*{raw_var}="
                                       f"{0.05 * raw_var:.3e}, against L_S ~ 0.50.",
            "implication": "the explicit variance floor is not doing the work at lambda_var=0.05. "
                           "The charter forbids tuning it from DEV, so it stays at 0.05 and the "
                           "finding is recorded rather than exploited.",
            "L_pair_terms_epoch8": {k: hc[-1].get(k) for k in
                                    ("L_pair_S", "L_pair_E", "L_pair_A", "L_var")},
        },
        "confound_identified": {
            "finding": "P2-BASE under the exhaustive 28-candidate contract scores WORSE on "
                       "candidate_legal (0.500) than Phase 1 did under the 24-cap (0.7345). "
                       "Widening the candidate set made raw latent invariance more destructive, "
                       "because L_R's e-term is summed over more candidates.",
            "why_the_base_arm_matters": "it separates the objective change from the contract "
                                        "change. CONSIST's candidate recovery to 0.7328 is "
                                        "therefore attributable to the objective, not to the "
                                        "larger candidate set.",
        },
        "selection_rule_caveat": {
            "rule": "lowest DEV semantic+epistemic BCE, identical in both arms, unchanged from "
                    "Phase 1",
            "base_best_epoch": b["best_dev_checkpoint"]["epoch"],
            "consist_best_epoch": c["best_dev_checkpoint"]["epoch"],
            "problem": "BCE on skewed targets is prior-dominated, so the rule systematically "
                       "prefers the most collapsed checkpoint. For CONSIST it selects epoch 1 "
                       f"(D_s={cd['D_s']['value']}) over epoch 8 (D_s={hc[-1]['D_s']}), i.e. it "
                       "selects AGAINST the anti-collapse objective it is meant to evaluate.",
            "not_changed_because": "retro-fitting a selection rule to DEV is exactly what this "
                                   "program forbids. Reported, not exploited.",
        },
        "answer_to_the_phase_question": {
            "renderer_stable_semantic_state": "NO. No global target rises above trivial "
                                              "prediction in either arm, so there is no semantic "
                                              "state to be stable.",
            "renderer_stable_action_state": "NO. The endpoint stays at or below chance in both "
                                            "arms; MOVE 0.003 and ACTIVATE 0.000 under CONSIST.",
            "without_rewarding_latent_collapse": "YES, this part works. D_s rises 86x by epoch 8 "
                                                  "and clears the variance floor, while the "
                                                  "baseline collapses. Prediction consistency "
                                                  "plus floor does arrest the collapse.",
            "net": "The objective WAS suppressing the representation, and removing the raw "
                   "latent term fixed that. But restoring variance did not by itself make s "
                   "discriminative. The bottleneck has moved: it is no longer collapse, and it "
                   "is not obviously the substrate either. That points Phase 3 at the global "
                   "readout objective (class-imbalanced BCE) and at model-internal computation, "
                   "NOT at more anti-collapse machinery.",
        },
        "not_proposed": "No new architecture, no covariance penalty, no extra heads, no backbone "
                        "tuning, no new supervision, and no weight tuned from DEV. The failure "
                        "of the global pathway is preserved as instructed.",
        "protected": {"PROTECTED_TEST_TRUTH_OPENED": False, "BANK_V2_USED": False,
                      "PHASE0_ARCHITECTURE_UNCHANGED": True,
                      "PHASE0_TARGET_SEMANTICS_UNCHANGED": True,
                      "CANONICAL_SPLITS_UNCHANGED": True,
                      "SUBSTRATE_UNCHANGED": True, "EXTRACTION_SURFACES_UNCHANGED": True},
    }
    p = OUT / "phase2-synthesis.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({"written": str(p), **rec["headline"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
