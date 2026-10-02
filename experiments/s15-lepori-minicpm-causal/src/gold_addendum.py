"""Additions to the gold action-sufficiency audit, per review.

1. TYPE-CONDITIONAL DETERMINISM CEILINGS. The previously reported 0.7605 is the ceiling for the
   OVERALL endpoint, and the 0.3699 MOVE figure was a 1-NN result, not a MOVE-specific ceiling.
   Only a ceiling computed conditional on the true action being MOVE supports the claim that MOVE
   itself is capped. So the ceiling is now computed per target type, where the state grouping is
   done within that type only. That is a strictly stronger and more useful statement, because
   within a type the label varies while the ceiling is not diluted by NOOP agreement.

2. OPTIMAL-SET HIT RATE as permanent reporting infrastructure, alongside exact selected-action
   accuracy. `selected_action` lies inside the generator's own `optimal_next_actions` only 53.3%
   of the time, so the exact endpoint is a LOGGED-CHOICE IMITATION TARGET, not a synonym for
   "choose an optimal next action". A larger model could legitimately disagree more often with
   the recorded arbitrary choice while choosing an equally or more defensible action, and that
   must not be scored as regression. Exact accuracy is retained unchanged for lineage continuity.

   ExactSelectedActionAccuracy  = 1[a_hat == a_selected]      (unchanged, lineage)
   OptimalSetHitRate           = 1[a_hat in A*]               (new diagnostic)
   where A* is the world record's optimal_next_actions.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

import src.gold_sufficiency as G

OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
LEVELS = ["L1_legal", "L2_legal_plus_sat", "L3_plus_global", "L4_plus_transition"]
TYPES = ["MOVE", "ACTIVATE", "NOOP"]


def type_conditional_ceilings(ep):
    """Determinism ceiling computed WITHIN each target type.

    Grouping is restricted to worlds whose true action is of that type, so the numerator is the
    largest agreeing subset inside each group and the denominator is that type's own count. No
    learner of any kind can exceed this: worlds with identical gold state and the same true type
    but different chosen candidates are irreducible label ambiguity, not a modelling failure.
    """
    out = {}
    for t in TYPES:
        sub = [f for _, f in ep if f["target_type"] == t]
        if not sub:
            continue
        per_level = {}
        for lv in LEVELS:
            groups: dict[bytes, Counter] = {}
            for f in sub:
                groups.setdefault(f[lv].tobytes(), Counter())[f["target_index"]] += 1
            agree = sum(max(c.values()) for c in groups.values())
            per_level[lv] = {"ceiling": round(agree / len(sub), 4),
                             "distinct_states": len(groups),
                             "irreducible_ambiguous_groups": sum(1 for c in groups.values()
                                                                if len(c) > 1),
                             "n": len(sub)}
        out[t] = per_level
    return out


def knn_by_type(ep, tr_ep, lv):
    Xtr = np.stack([f[lv] for _, f in tr_ep])
    ytr = np.array([f["target_index"] for _, f in tr_ep])
    Xdv = np.stack([f[lv] for _, f in ep])
    ydv = np.array([f["target_index"] for _, f in ep])
    d = ((Xdv[:, None, :] - Xtr[None, :, :]) ** 2).sum(-1)
    nn = d.argmin(1)
    out = {}
    for t in TYPES:
        m = np.array([f["target_type"] == t for _, f in ep])
        if m.any():
            out[t] = {"knn1": round(float((ytr[nn][m] == ydv[m]).mean()), 4), "n": int(m.sum())}
    return out


def optimal_set_report(ep, dv_pred_index=None, predicted_by_world=None):
    """A* membership statistics on the endpoint population, plus hit rate if predictions given."""
    n = len(ep)
    rec = {
        "definition": "A* = world record's optimal_next_actions; a candidate is in A* when its "
                      "canonical action key matches one of them",
        "endpoint_worlds": n,
        "logged_action_in_A_star": round(sum(1 for _, f in ep if f["sel_in_opt"]) / n, 4),
        "A_star_is_singleton": round(sum(1 for _, f in ep if f["opt_is_singleton"]) / n, 4),
        "mean_A_star_size": round(float(np.mean([f["n_opt"] for _, f in ep])), 3),
        "logged_action_equals_only_A_star_member": round(
            sum(1 for _, f in ep if f["opt_is_singleton"] and f["sel_in_opt"]) / n, 4),
        "A_star_empty_but_action_logged": int(sum(1 for _, f in ep if f["n_opt"] == 0
                                                  and f["target_index"] >= 0)),
        "interpretation": "the exact endpoint is a LOGGED-CHOICE IMITATION TARGET, not a synonym "
                          "for choosing an optimal next action; both quantities must be reported",
    }
    if predicted_by_world is not None:
        hit = tot = 0
        for wid, f in ep:
            p = predicted_by_world.get(wid)
            if p is None or p < 0:
                continue
            tot += 1
            hit += int(p in f["opt_index_set"])
        rec["OptimalSetHitRate"] = round(hit / max(tot, 1), 4)
        rec["hit_rate_n"] = tot
    return rec


def main() -> int:
    tr = G.build("TRAIN", 20000)
    dv = G.build("DEV", 2000)
    tr_ep = [(v, f) for v, f in tr.items() if f["target_index"] >= 0]
    ep = [(v, f) for v, f in dv.items() if f["target_index"] >= 0]

    # per-type A* index sets, needed for the hit-rate diagnostic
    import src.data as D
    for wid, f in ep:
        pass
    for wid, f in tr_ep:
        pass

    ceil = type_conditional_ceilings(ep)
    knn = {lv: knn_by_type(ep, tr_ep, lv) for lv in LEVELS}
    opts = optimal_set_report(ep)

    print("TYPE-CONDITIONAL DETERMINISM CEILINGS (within-type grouping)")
    for t in TYPES:
        n = ceil[t]["L1_legal"]["n"]
        print(f"\n  {t}  n={n}")
        for lv in LEVELS:
            c = ceil[t][lv]
            k = knn[lv][t]
            print(f"    {lv:22s} ceiling {c['ceiling']:.4f}   knn1 {k['knn1']:.4f}   "
                  f"states {c['distinct_states']:5d}  ambiguous groups "
                  f"{c['irreducible_ambiguous_groups']}")

    print("\nOPTIMAL-SET REPORT")
    for k, v in opts.items():
        if k != "interpretation":
            print(f"  {k}: {v}")

    out = {"abi": "s15-lepori-minicpm/gold-sufficiency-addendum-v0.1",
           "why": "review correction: the 0.7605 figure is the OVERALL determinism ceiling and the "
                  "0.3699 MOVE figure was a 1-NN result, not a MOVE ceiling. Type-conditional "
                  "ceilings are now computed by grouping within each target type.",
           "type_conditional_determinism_ceilings": ceil,
           "type_conditional_knn1": knn,
           "optimal_set": opts,
           "reporting_contract": {
               "ExactSelectedActionAccuracy": "1[a_hat == a_selected]; unchanged, kept for "
                                              "lineage continuity across all lanes",
               "OptimalSetHitRate": "1[a_hat in A*]; new separate diagnostic, never a replacement",
               "why_both": "a larger substrate could disagree more with the recorded arbitrary "
                           "choice while choosing an equally or more defensible action; that must "
                           "not be scored as regression",
           }}
    p = OUT / "gold-sufficiency-addendum.json"
    p.write_text(json.dumps(out, indent=2) + "\n")
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
