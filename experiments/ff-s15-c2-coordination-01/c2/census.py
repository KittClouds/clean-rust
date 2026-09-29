"""The C2a complementarity census: do the four locked surfaces find different safe actions? Pure functions of integer ppm arrays."""
from __future__ import annotations

from itertools import combinations

import numpy as np

from .common import ACTIONS, DECISIONS, PRIMARY, SURFACES, fit

ACT, ASK, ABSTAIN = fit.ACT, fit.ASK, fit.ABSTAIN


def surface_sets(arrays: dict, thresholds: dict, truth_decision: np.ndarray, truth_action: np.ndarray) -> dict:
    """Boolean row sets for one surface at one operating point. `thresholds` is C1's {'abstain','ask','act'} ppm-or-None."""
    v = fit.views(arrays["dec"], arrays["act"])
    n = len(truth_decision)
    t_act, t_abs = thresholds.get("act"), thresholds.get("abstain")
    qualifies = np.zeros(n, dtype=bool) if t_act is None else (v["dec_top"] == ACT) & (v["dec_ppm"] >= t_act) & (v["act_ppm"] >= t_act)
    right = (truth_decision == ACT) & (v["act_top"] == truth_action)
    raw_act = v["dec_top"] == ACT
    return {
        "Q": qualifies, "C": qualifies & right, "Hm": qualifies & ~right,
        "raw_act": raw_act, "raw_correct": raw_act & right, "raw_harm": raw_act & ~right, "act_top": v["act_top"], "dec_top": v["dec_top"],
        "veto": np.zeros(n, dtype=bool) if t_abs is None else (v["dec_top"] == ABSTAIN) & (v["dec_ppm"] >= t_abs),
    }


def count(mask: np.ndarray) -> int:
    return int(mask.sum())


def pair(a: dict, b: dict) -> dict:
    both_q = a["Q"] & b["Q"]
    union_c = a["C"] | b["C"]
    both_raw = a["raw_act"] & b["raw_act"]
    return {
        "qualified": {
            "A_qualifies": count(a["Q"]), "B_qualifies": count(b["Q"]), "both_qualify": count(both_q), "both_same_action": count(both_q & (a["act_top"] == b["act_top"])),
            "both_correct": count(a["C"] & b["C"]), "both_harmful": count(a["Hm"] & b["Hm"]),
            "correct_only_A": count(a["C"] & ~b["C"]), "correct_only_B": count(b["C"] & ~a["C"]),
            "harmful_only_A": count(a["Hm"] & ~b["Hm"]), "harmful_only_B": count(b["Hm"] & ~a["Hm"]),
            "union_correct": count(union_c), "jaccard_correct": count(a["C"] & b["C"]) / count(union_c) if count(union_c) else None,
        },
        "raw": {
            "both_say_act": count(both_raw), "same_action": count(both_raw & (a["act_top"] == b["act_top"])),
            "both_correct": count(a["raw_correct"] & b["raw_correct"]), "both_harmful": count(a["raw_harm"] & b["raw_harm"]),
            "A_act_B_abstain": count(a["raw_act"] & (b["dec_top"] == ABSTAIN)), "A_act_B_ask": count(a["raw_act"] & (b["dec_top"] == ASK)),
            "A_act_B_act_other_action": count(both_raw & (a["act_top"] != b["act_top"])),
        },
    }


def group(sets: dict, truth_decision: np.ndarray, families: np.ndarray, primary: str = PRIMARY) -> dict:
    """Union/intersection of safe actions, oracle headroom, pessimistic harm, veto census and per-family headroom."""
    names = list(sets)
    routers = [s for s in names if sets[s]["Q"].any()]
    union_c = np.zeros_like(sets[primary]["C"])
    union_q = np.zeros_like(union_c)
    union_hm = np.zeros_like(union_c)
    inter_c = np.ones_like(union_c)
    for s in names:
        union_c |= sets[s]["C"]
        union_q |= sets[s]["Q"]
        union_hm |= sets[s]["Hm"]
        inter_c &= sets[s]["C"]
    primary_c = sets[primary]["C"]
    true_act = int((truth_decision == ACT).sum())
    out = {
        "surfaces_with_an_act_rule": routers, "true_act_rows": true_act, "primary_correct": count(primary_c), "primary_executed": count(sets[primary]["Q"]),
        "union_correct": count(union_c), "intersection_correct": count(inter_c), "union_executed": count(union_q), "rows_with_a_harmful_qualifier": count(union_hm),
        "oracle_headroom": count(union_c) / count(primary_c) - 1 if count(primary_c) else None,
        "pessimistic_union_harm_rate": count(union_hm) / count(union_q) if count(union_q) else None,
        "primary_correct_share_of_true_act": count(primary_c) / true_act, "union_correct_share_of_true_act": count(union_c) / true_act,
        "extra_correct_not_found_by_primary": count(union_c & ~primary_c),
    }
    prime_q = sets[primary]["Q"]
    veto = {"primary_executed": count(prime_q), "primary_correct": count(primary_c), "primary_harmful": count(sets[primary]["Hm"])}
    any_veto = np.zeros_like(prime_q)
    for s in names:
        if s == primary:
            continue
        v = sets[s]["veto"]
        any_veto |= v
        veto[s] = {"vetoes_correct": count(primary_c & v), "vetoes_harmful": count(sets[primary]["Hm"] & v), "abstain_rule_fires": count(v)}
    veto["any_other_vetoes_correct"] = count(primary_c & any_veto)
    veto["any_other_vetoes_harmful"] = count(sets[primary]["Hm"] & any_veto)
    out["veto_census"] = veto
    per_family = {}
    for f in sorted(set(families.tolist()), key=lambda x: int(x[1:])):
        m = families == f
        p, u = count(primary_c & m), count(union_c & m)
        per_family[str(f)] = {"rows": count(m), "true_act": int(((truth_decision == ACT) & m).sum()), "primary_correct": p, "union_correct": u, "headroom": (u / p - 1) if p else None}
    out["per_family"] = per_family
    return out


def census(cal: dict, tag: str) -> dict:
    """Everything for one alpha tag."""
    sets = {s: surface_sets(cal["surfaces"][s], cal["thresholds"][s][tag]["thresholds_ppm"], cal["truth_decision"], cal["truth_action"]) for s in SURFACES}
    pairs = {f"{a}|{b}": pair(sets[a], sets[b]) for a, b in combinations(SURFACES, 2)}
    return {"alpha_tag": tag, "per_surface": {s: {"qualifies": count(x["Q"]), "correct": count(x["C"]), "harmful": count(x["Hm"]), "raw_act": count(x["raw_act"]),
                                                  "raw_correct": count(x["raw_correct"]), "raw_harm": count(x["raw_harm"])} for s, x in sets.items()},
            "pairs": pairs, "group": group(sets, cal["truth_decision"], cal["family"])}


# ---- post hoc, exploratory: added after the planned census had been read, and labelled as such wherever it is reported

def harmful_anatomy(cal: dict, tag: str, primary: str = PRIMARY) -> dict:
    """What the other surfaces say on the rows where the primary's qualified ACT is harmful: are its errors shared?"""
    truth_decision, truth_action = cal["truth_decision"], cal["truth_action"]
    sets = {s: surface_sets(cal["surfaces"][s], cal["thresholds"][s][tag]["thresholds_ppm"], truth_decision, truth_action) for s in SURFACES}
    harm = sets[primary]["Hm"]
    out = {"tag": tag, "primary_harmful": count(harm), "truth_of_those_rows": {DECISIONS[d]: count((truth_decision == d) & harm) for d in range(3)}, "others": {}}
    for s in SURFACES:
        if s == primary:
            continue
        top = sets[s]["dec_top"][harm]
        abstain_p = cal["surfaces"][s]["dec"][harm][:, ABSTAIN] / 1_000_000
        out["others"][s] = {
            "says": {DECISIONS[c]: int((top == c).sum()) for c in range(3)}, "p_abstain_median": float(np.median(abstain_p)) if len(abstain_p) else None,
            "p_abstain_max": float(abstain_p.max()) if len(abstain_p) else None, "also_qualifies_harmfully": count(sets[s]["Hm"] & harm),
        }
    return out


def single_surface_frontier(cal: dict, alphas, surface: str = PRIMARY) -> list:
    """The one-surface frontier with the ACT rule refit on CAL at intermediate alphas (CAL is in-sample here). Shows what moving along the frontier buys with no coordination."""
    truth_decision, truth_action = cal["truth_decision"], cal["truth_action"]
    dec, act = cal["surfaces"][surface]["dec"], cal["surfaces"][surface]["act"]
    v = fit.views(dec, act)
    true_act = int((truth_decision == ACT).sum())
    rows = []
    for alpha in alphas:
        threshold = fit.fit_thresholds(dec, act, truth_decision, truth_action, alpha)["act"]["threshold_ppm"]
        disposition, target = fit.simulate(v, {"abstain": None, "ask": None, "act": threshold})
        o = fit.outcomes(disposition, target, truth_decision, truth_action)
        rows.append({"alpha": alpha, "t_act_ppm": threshold, "correct_act_share_of_true_act": o["correct_executed"] / true_act, "cal_harm_rate": o["harm_rate"], "executed": o["executed"]})
    return rows
