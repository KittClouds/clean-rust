"""Causal-only engineering comparison; report tradeoffs without an accuracy gate."""
from __future__ import annotations

import json
from p2_contract import OUTPUT,PHASE1_OUTPUT,default_config,state_hash


def snapshot(report):
    return {"global":{k:{key:m.get(key) for key in ("accuracy","balanced_accuracy","macro_f1","mae","exact_count_accuracy")}
                      for k,m in report["global"].items() if m.get("available")},
            "candidate":{k:{key:m.get(key) for key in ("accuracy","balanced_accuracy","macro_f1")}
                         for k,m in report["candidate"].items() if m.get("available")},
            "action":report["endpoint"],"renderer":report["renderer"],
            "candidate_conditioning":report["candidate_conditioning"],
            "D_s":report.get("global_state_diversity",{}).get("D_s"),
            "TRAIN_D_s":report.get("TRAIN_global_state_diversity",{}).get("D_s")}


def make_comparison(results,prior_receipt):
    import torch
    from graft.model import model_for_substrate
    prior=json.loads((PHASE1_OUTPUT/"DEV-METRICS.json").read_text())
    base,consist=(results[arm][1] for arm in ("P2-BASE","P2-CONSIST"))
    changes={}
    for branch in ("global","candidate"):
        changes[branch]={}
        for name,metric in base[branch].items():
            if not metric.get("available"):continue
            other=consist[branch][name]
            changes[branch][name]={key:other[key]-metric[key]
                for key in ("accuracy","balanced_accuracy","macro_f1","mae","exact_count_accuracy")
                if metric.get(key) is not None and other.get(key) is not None}
    baseline_action=base["endpoint"]["accuracy"]
    new_action=consist["endpoint"]["accuracy"]
    base_move=base["endpoint"]["by_target_action_type"]["MOVE"]["accuracy"]
    new_move=consist["endpoint"]["by_target_action_type"]["MOVE"]["accuracy"]
    base_dis=base["renderer"]["endpoint_prediction_flip_rate_all_pairs"]
    new_dis=consist["renderer"]["endpoint_prediction_flip_rate_all_pairs"]
    phase1_model=model_for_substrate(default_config(),"causal_base")
    phase1_model.load_state_dict(torch.load(PHASE1_OUTPUT/"best-graft.pt",map_location="cpu",weights_only=True)["state_dict"])
    exact_phase1_replay=state_hash(phase1_model)==results["P2-BASE"][0]["learned_state_sha256"]
    summary={"status":"CAUSAL_PHASE2_COMPARED_NO_NUMERICAL_EXIT_GATE",
             "Phase1":snapshot(prior),"P2-BASE":snapshot(base),"P2-CONSIST":snapshot(consist),
             "target_changes_CONSIST_minus_BASE":changes,
             "action_accuracy_delta":new_action-baseline_action,
             "MOVE_accuracy_delta":new_move-base_move,
             "renderer_action_disagreement_delta":new_dis-base_dis,
             "global_diversity_D_s_delta":consist["global_state_diversity"]["D_s"]-base["global_state_diversity"]["D_s"],
             "baseline_replays_Phase1_selected_state_bit_exact":exact_phase1_replay,
             "same_initialization":results["P2-BASE"][0]["initial_state_sha256"]==results["P2-CONSIST"][0]["initial_state_sha256"],
             "baseline_selected_epoch":results["P2-BASE"][0]["best_epoch"],
             "consistency_selected_epoch":results["P2-CONSIST"][0]["best_epoch"],
             "interpretation_scope":"Bundled objective intervention including changed S/E/A weights; not attribution to pair or variance in isolation",
             "missing_count_scope":"0/1 annotation count and presence share the same current annotation; not independent semantic evidence",
             "protected_TEST_truth_opened":False,"BANK_v2_used":False,"cross_lane_winner":None}
    reference=json.loads((OUTPUT/"VARIANCE-REFERENCE.json").read_text())
    lines=["# Causal Phase 2: prediction consistency without latent matching", "",
           "Both arms train the unchanged Phase 0 causal Base graft from the identical untrained initialization.",
           "20,000 TRAIN rows / 2,000 DEV rows, 20 full TRAIN passes per arm. Exhaustive candidates retained at measured m_cap=28.",
           "Phase 1 truncated zero candidates. Phase 0/1 artifacts remain unchanged.","",
           "| Measure | P2-BASE | P2-CONSIST | Change |", "|---|---:|---:|---:|",
           f"| Action accuracy (925 ACT endpoints) | {baseline_action:.4f} | {new_action:.4f} | {new_action-baseline_action:+.4f} |",
           f"| MOVE accuracy (369 endpoints) | {base_move:.4f} | {new_move:.4f} | {new_move-base_move:+.4f} |",
           f"| Action renderer disagreement (464 pairs) | {base_dis:.4f} | {new_dis:.4f} | {new_dis-base_dis:+.4f} |",
           f"| DEV global state diversity D_s | {base['global_state_diversity']['D_s']:.4f} | {consist['global_state_diversity']['D_s']:.4f} | {summary['global_diversity_D_s_delta']:+.4f} |",
           "",f"The untrained full-TRAIN reference D_s is {reference['D_s']:.6f}; each coordinate's floor is half its own reference std.",
           f"Selected checkpoints: BASE epoch {summary['baseline_selected_epoch']}, CONSIST epoch {summary['consistency_selected_epoch']}.",
           f"Exact selected-state replay of prior Phase 1: {exact_phase1_replay}.","",
           "## Typed state retention", "",
           "| Target | BASE balanced accuracy | CONSIST balanced accuracy | Change |",
           "|---|---:|---:|---:|"]
    for branch in ("global","candidate"):
        for name,item in changes[branch].items():
            if "balanced_accuracy" in item:
                b=base[branch][name]["balanced_accuracy"];c=consist[branch][name]["balanced_accuracy"]
                lines.append(f"| {name} | {b:.4f} | {c:.4f} | {c-b:+.4f} |")
    lines += ["", "## Renderer disagreements remain separate", "",
              "| State target | BASE flips | CONSIST flips |", "|---|---:|---:|"]
    for branch in ("global","candidate"):
        for name,m in base["renderer"][branch].items():
            if m["decision_flip_rate"] is not None:
                other=consist["renderer"][branch][name]
                lines.append(f"| {name} | {m['decision_flip_rate']:.4f} | {other['decision_flip_rate']:.4f} |")
    lines += ["", "## Candidate states and count proxy", "",
              f"Collapsed DEV candidate-state rows: BASE {base['candidate_conditioning']['collapsed_rows_at_variance_le_1e_8']}, CONSIST {consist['candidate_conditioning']['collapsed_rows_at_variance_le_1e_8']}, out of 2,000 each.",
              f"Within-world coordinate variance: BASE {base['candidate_conditioning']['mean_within_world_coordinate_variance']:.6f}, CONSIST {consist['candidate_conditioning']['mean_within_world_coordinate_variance']:.6f}.",
              f"Count-proxy MAE: BASE {base['global']['number_or_structure_of_missing_requirements']['mae']:.4f}, CONSIST {consist['global']['number_or_structure_of_missing_requirements']['mae']:.4f}.",
              "Count scoring is unchanged raw regression MAE and rounded nonnegative exact count. JS uses its frozen 0/1 support only.", "",
              "## Engineering interpretation", "",
              ("Action renderer instability improved." if new_dis<base_dis else "Action renderer instability did not improve."),
              ("MOVE accuracy improved." if new_move>base_move else "MOVE accuracy did not improve."),
              "Read target-specific losses and retention above; there is no aggregate success gate or causal/encoder winner.",
              "The intervention changes candidate/action weighting as well as the invariance formulation. It does not identify the effect of each component separately.",
              "No recurrent refinement, extra heads, larger MLPs, new extraction, covariance penalty or backbone adaptation was introduced.", "",
              "## Scope and supervision limits", "",
              "Candidate support/counterevidence/unmet requirements/applicability/dependency, requestability and unrestricted solvability remain unavailable. CF remains inactive. Candidate legality is simulator truth, not evidence-supported authorization.",
              "The count is a restricted 0/1 missing-annotation proxy; its current identity with missing presence is not independent evidence.",
              "Renderer statistics use the existing paired population only; S7/S8/S9 are absent, so no held-renderer or protected-TEST claim is made.",
              "All new outputs are on C: NVMe. Full checkpoint histories, runtime estimates, state diversity, per-target metrics and artifact hashes are retained.","",
              "## Handoff artifacts", "",
              "- PHASE2-RECEIPT.json and COMPARISON.json: frozen completion and paired comparison.",
              "- P2-BASE/best-graft.pt and P2-CONSIST/best-graft.pt: selected trained objects with embedded TRAIN normalization.",
              "- Each arm's DEV-METRICS.json, DEV-estimates.jsonl and training-history.json: typed metrics, runtime envelopes and optimization curves.",
              "- VARIANCE-REFERENCE.json, TRAIN-untrained-sigma.npy and PHASE0-INITIALIZATION.pt: exact anti-collapse reference and shared initialization.",""]
    (OUTPUT/"PHASE2-HANDOFF.md").write_text("\n".join(lines),encoding="utf-8")
    return summary
