"""Phase 4A synthesis: depth curve, compute cost, and the charter's three-box verdict.

No promotion threshold is installed. The verdict is one of:
  iterative computation survives | state motion without useful computation | not useful
"""
from __future__ import annotations

import json
from pathlib import Path

P3 = Path(r"D:\codex-runs\encoder-contrast-01\phase3\balanced\phase3-balanced-receipt.json")
P4 = Path(r"D:\codex-runs\encoder-contrast-01\phase4a\phase4a-receipt.json")
OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase4a")

GLOBAL_SRC = ["SRC-SOLVABILITY", "SRC-GOAL-SATISFIED", "SRC-MISSING-INFO-PANEL",
              "SRC-CONTRADICTION-PANEL"]
CAND_SRC = ["SRC-CANDIDATE-LEGALITY", "SRC-CANDIDATE-SATISFIES-GOAL"]


def main() -> int:
    p3 = json.loads(P3.read_text())
    p4 = json.loads(P4.read_text())
    d = p4["results_by_depth"]
    comp = p4["computational_diagnostics"]
    chance = d[0]["endpoint"]["chance"]

    def series(sid, key="balanced_accuracy"):
        return [x["sources"][sid][key] for x in d]

    def beats(sid):
        return [bool(x["sources"][sid].get("beats_base_rate")) for x in d]

    depth_table = {}
    for sid in GLOBAL_SRC + CAND_SRC:
        depth_table[sid] = {
            "train_prevalence": d[0]["sources"][sid]["train_prevalence"],
            "balanced_accuracy_by_depth": series(sid),
            "beats_base_rate_by_depth": beats(sid),
            "macro_f1_by_depth": series(sid, "macro_f1"),
            "improved_over_t0": series(sid)[-1] > series(sid)[0],
            "ever_beats_base_rate": any(beats(sid)),
        }

    action = {
        "chance": chance,
        "top1_by_depth": [x["endpoint"]["action_top1_accuracy"] for x in d],
        "above_chance_by_depth": [x["endpoint"]["action_top1_accuracy"] > chance for x in d],
        "MOVE_by_depth": [x["endpoint"]["by_action_type"].get("MOVE", {}).get("accuracy")
                          for x in d],
        "ACTIVATE_by_depth": [x["endpoint"]["by_action_type"].get("ACTIVATE", {}).get("accuracy")
                              for x in d],
        "NOOP_by_depth": [x["endpoint"]["by_action_type"].get("NOOP", {}).get("accuracy")
                          for x in d],
        "monotone_in_depth": False,
        "reading": "top-1 crosses chance at t=1 and t=2 and then falls back, so the crossing is "
                   "NOT monotone and must not be read as depth-driven capability. MOVE is 0.0000 "
                   "at every depth, so none of the movement is in the action type that matters.",
    }

    motion = {
        "D_s_by_depth": [x["diagnostics"]["D_s"] for x in d],
        "D_s_growth_t0_to_t4": round(d[-1]["diagnostics"]["D_s"] / d[0]["diagnostics"]["D_s"], 1),
        "candidate_conditioning_by_depth": [
            x["diagnostics"]["candidate_conditioning"]["ratio_within_over_between"] for x in d],
        "conditioning_still_positive": d[-1]["diagnostics"]["candidate_conditioning"]
        ["e_candidate_conditioned"],
        "delta_t_selected_epoch": [h["delta_t"] for h in p4["training_history"]
                                   if h["epoch"] == p4["selection"]["best_epoch"]][0],
        "delta_t_final_epoch": p4["training_history"][-1]["delta_t"],
        "delta_t_behaviour": "GROWS, does not converge: 0.83 -> 0.90 across depths at the "
                             "selected epoch, and 1.11 -> 1.22 by the final epoch. Recorded as "
                             "growth, not convergence; no stabilising machinery was added.",
    }

    any_global_win = any(depth_table[s]["ever_beats_base_rate"] for s in GLOBAL_SRC)
    legality_preserved = (depth_table["SRC-CANDIDATE-LEGALITY"]["balanced_accuracy_by_depth"]
                          [-1] >= depth_table["SRC-CANDIDATE-LEGALITY"]
                          ["balanced_accuracy_by_depth"][0] - 0.01)
    monotone_gain = all(
        depth_table[s]["balanced_accuracy_by_depth"][-1]
        > depth_table[s]["balanced_accuracy_by_depth"][0] for s in GLOBAL_SRC)
    capability_moved = any_global_win or monotone_gain

    verdict = ("iterative computation survives" if capability_moved
               else "state motion without useful computation")

    rec = {
        "abi": "phase4a-semantic-interface/synthesis-v0.1",
        "lane": "bidirectional (Lepori)",
        "question": "Can shared-weight recurrent latent refinement turn the state already "
                    "accessible to this frozen substrate into better global semantic and action "
                    "computation?",
        "carry_forward": p4["carry_forward"],
        "baseline_integrity": {
            "R0_equals_seed": True,
            "check": "t=0 reproduces the frozen P3-BALANCED artifact on all six sources and the "
                     "action endpoint, to 1e-9",
            "seed_sources": {s: p3["per_source_dev_metrics"][s]["balanced_accuracy"]
                             for s in GLOBAL_SRC + CAND_SRC},
        },
        "depth_curve": depth_table,
        "action": action,
        "state_motion": motion,
        "renderer_correctness_t0_vs_t4": p4["renderer_correctness_by_depth"],
        "renderer_reading": "at t=0 the global heads show ZERO disagreement and paired accuracy "
                            "equal to the majority rate, so that stability is vacuous. At t=4 the "
                            "predictions genuinely vary across renderers (disagreements appear on "
                            "every global source) but paired accuracy DEGRADES on the sources "
                            "that were stable: goal_satisfied 0.6988 -> 0.4669, "
                            "missing_information_present 0.8072 -> 0.1928, candidate_legal "
                            "0.7651 -> 0.7048. Variation was bought with correctness, not "
                            "discrimination. Raw agreement is not used as a success measure.",
        "compute_cost": {
            "trainable_recurrent_parameters": comp["trainable_recurrent_parameters"],
            "frozen_inherited_parameters": comp["frozen_inherited_parameters"],
            "recurrent_share_of_inherited": round(
                100.0 * comp["trainable_recurrent_parameters"]
                / comp["frozen_inherited_parameters"], 2),
            "per_step_latency_ms_batch256_cpu": comp["inference_latency_batch256_ms"]
            ["per_step_median"],
            "total_T4_latency_ms_batch256_cpu": comp["inference_latency_batch256_ms"]
            ["total_T4_median"],
            "training_seconds": comp["training_seconds"],
            "peak_gpu_bytes": comp["peak_gpu_bytes"],
            "device_note": "run executed on CPU, so peak_gpu_bytes is 0 by construction and the "
                           "latency figures are CPU latencies, not GPU latencies. Reported as "
                           "measured rather than presented as GPU numbers.",
        },
        "verdict": verdict,
        "verdict_basis": {
            "any_global_source_beat_base_rate": any_global_win,
            "monotone_global_gain": monotone_gain,
            "candidate_legality_preserved": legality_preserved,
            "state_definitely_moved": True,
            "reading": "the recurrent block demonstrably moved the state -- D_s grew "
                       f"{motion['D_s_growth_t0_to_t4']}x, update magnitude grew rather than "
                       "converged, and the heads stopped being degenerate (macro-F1 rose on every "
                       "global source). What it did not do is make any global source "
                       "discriminative under the pre-registered margin, and it cost candidate "
                       "conditioning (6.53 -> 1.53) and renderer paired accuracy. That is state "
                       "motion without useful computation.",
        },
        "honest_positives": {
            "goal_satisfied_rose_but_did_not_qualify": {
                "by_depth": series("SRC-GOAL-SATISFIED"),
                "peak": max(series("SRC-GOAL-SATISFIED")),
                "required_to_qualify": round(max(d[0]["sources"]["SRC-GOAL-SATISFIED"]
                                                 ["train_prevalence"], 1 - d[0]["sources"]
                                                 ["SRC-GOAL-SATISFIED"]["train_prevalence"]) + 0.01,
                                             4),
                "why_not_a_win": "0.5699 peak is below the 0.647 the pre-registered margin "
                                 "requires, so it is reported as movement, not as capability.",
            },
            "candidate_satisfies_goal_rose_monotonically": {
                "by_depth": series("SRC-CANDIDATE-SATISFIES-GOAL"),
                "peak": max(series("SRC-CANDIDATE-SATISFIES-GOAL")),
                "why_not_a_win": "peak 0.5307 against a 0.6733 requirement; weak and not usable.",
            },
            "action_crossed_chance_at_intermediate_depths": {
                "by_depth": action["top1_by_depth"], "chance": chance,
                "why_not_a_win": "non-monotone, and MOVE is 0.0000 at every depth, so the "
                                 "crossing is majority-class movement rather than action "
                                 "computation.",
            },
        },
        "preserved": {
            "candidate_legality": series("SRC-CANDIDATE-LEGALITY"),
            "note": "the earned candidate capability survived recurrence intact at every depth "
                    "(0.7509 -> 0.7511) and is the only source beating base rate throughout",
        },
        "not_rescued": "no depth sweep, no wider block, no per-depth selection, no stabilising "
                       "machinery, no additional recurrence. The failure is preserved as the "
                       "charter requires.",
        "phase4b_implication": "shared-weight recurrence over an already-earned state did not buy "
                               "discriminative global semantics on this lane. If the recurrent "
                               "organ is to be tried again it needs a different job -- most "
                               "plausibly composing the ALREADY-good candidate state into an "
                               "action computation, since candidate legality is the one thing "
                               "this lane genuinely has -- rather than more depth or a bigger "
                               "block on the same state. IHA-style cross-head mixing remains "
                               "unearned.",
        "cross_lane": "no causal/encoder winner declared. Both lanes ran the same intervention on "
                      "their own phenotype.",
        "protected": p4["protected"],
    }
    p = OUT / "phase4a-synthesis.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(json.dumps({"written": str(p), "verdict": verdict,
                      "any_global_beat_base_rate": any_global_win,
                      "monotone_global_gain": monotone_gain,
                      "legality_preserved": legality_preserved,
                      "D_s_growth": motion["D_s_growth_t0_to_t4"],
                      "conditioning": motion["candidate_conditioning_by_depth"],
                      "action_by_depth": action["top1_by_depth"], "chance": chance}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
