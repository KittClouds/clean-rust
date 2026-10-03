"""Gold action-sufficiency ladder. Uses canonical BANK truth only. No model, no training.

The question this exists to answer, before any mechanism is chosen:

    Is the action endpoint limited by the graft, or is the typed state not action-sufficient?

Action choice generally needs more than "is this candidate legal". It also needs something like
"does this candidate advance or satisfy the goal". The L1 MOVE 1-NN score is an estimator result,
not an information ceiling; see `gold_addendum.py` for the conditional determinism ceilings. Keep
these separate when interpreting the ladder: an estimator gap does not prove that a recurrent
action workspace cannot recover the relevant signal.

The ladder asks how well the action can be determined from progressively richer GOLD state:

    L0  nothing                       -> TRAIN index mode / majority type
    L1  + gold candidate_legal
    L2  + gold candidate_satisfies_goal
    L3  + global goal_satisfied, missing_information_present, contradiction_present
    L4  + exact transition / precondition fields BANK actually exposes

Estimators, both parameter-free so nothing is trained:
  * DETERMINISM: do any two DEV worlds with IDENTICAL gold state have different actions? If yes,
    no learner of any kind can exceed that agreement, because the label is not a function of the
    state. This is an information bound, not a modelling result.
  * 1-NN ceiling: nearest neighbour in gold-state space, TRAIN -> DEV.

Also audits what BANK exposes that the current ontology does not use, in particular
`optimal_next_actions`, which is a goal-relative action field the ontology has no head for.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import numpy as np

REPO = Path(r"C:\code land\clean-rust\experiments")
BANK = REPO / "ff-s15-bank-01" / "releases" / "BANK-v1"
OUT = Path(r"D:\codex-runs\encoder-contrast-01\lepori-causal-minicpm")
TYPES = ["ASK", "MOVE", "ACTIVATE", "NOOP", "INSPECT", "RELEASE"]


def key(a):
    return json.dumps({"a": a.get("type"), "g": a.get("args", {})}, sort_keys=True)


def load(split, limit=None):
    worlds = {}
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            if line.strip():
                w = json.loads(line)
                if "@" not in w["world_id"]:
                    worlds[w["world_id"]] = w
    return worlds


def featurise(w, sim, m_cap=28):
    """Gold-state feature levels, from canonical truth only. No learned component.

    L1  per-candidate legality
    L2  + per-candidate goal satisfaction after applying that candidate
    L3  + global goal_satisfied, missing_information_present, contradiction_present, n_legal, n_cand
    L4  + optimal_next_actions membership, action-type one-hot, and whether the selected action is
        the first candidate
    """
    cand = w.get("available_actions") or []
    st, av, goal = w["initial_state"], cand, w["goal"]
    gs = sim.goal_satisfied(st, goal)
    legal_keys = {key(x) for x in sim.legal_actions(st, av)}
    opt_keys = {key(x) for x in (w.get("optimal_next_actions") or [])}
    sel = w.get("selected_action")
    sel_key = key(sel) if sel is not None else None

    legal = np.zeros(m_cap, np.float32)
    sat = np.zeros(m_cap, np.float32)
    in_opt = np.zeros(m_cap, np.float32)
    type_oh = np.zeros(m_cap * len(TYPES), np.float32)
    for j, a in enumerate(cand[:m_cap]):
        k = key(a)
        is_legal = k in legal_keys
        legal[j] = float(is_legal)
        in_opt[j] = float(k in opt_keys)
        if is_legal:
            sat[j] = float(sim.goal_satisfied(sim.apply_action(st, a), goal))
        if a.get("type") in TYPES:
            type_oh[j * len(TYPES) + TYPES.index(a["type"])] = 1.0

    n_missing = len(w.get("missing_information") or [])
    glob = np.array([float(gs), float(n_missing > 0),
                     float(len(w.get("contradictions") or []) > 0),
                     float(len(legal_keys)), float(len(cand))], np.float32)
    first = np.array([1.0 if sel_key is not None else 0.0], np.float32)

    tgt_idx, tgt_type = -1, None
    for j, a in enumerate(cand):
        if key(a) == sel_key:
            tgt_idx, tgt_type = j, a.get("type")
            break

    return {
        "L1_legal": legal,
        "L2_legal_plus_sat": np.concatenate([legal, sat]),
        "L3_plus_global": np.concatenate([legal, sat, glob]),
        "L4_plus_transition": np.concatenate([legal, sat, glob, in_opt, type_oh, first]),
        "target_index": tgt_idx, "target_type": tgt_type, "n_cand": len(cand),
        "n_legal": int(len(legal_keys)), "n_opt": len(opt_keys),
        "sel_in_opt": (sel_key in opt_keys) if sel_key else None,
        "opt_is_singleton": len(opt_keys) == 1,
        "sel_is_first_candidate": (tgt_idx == 0) if tgt_idx >= 0 else None,
        "n_optimal_satisfying_goal": int(sum(
            1 for a in cand if key(a) in legal_keys
            and sim.goal_satisfied(sim.apply_action(st, a), goal))),
    }


def build(split, limit=None):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "bank_sim", REPO / "ff-s15-bank-01" / "src" / "simulator.py")
    sim = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sim)
    out = {}
    n = 0
    with (BANK / "worlds" / f"{split}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            w = json.loads(line)
            if "@" in w["world_id"]:
                continue
            n += 1
            if limit and n > limit:
                break
            out[w["world_id"]] = featurise(w, sim)
    return out


def main() -> int:
    tr = build("TRAIN", 20000)
    dv = build("DEV", 2000)

    # ---------- 0. the label itself: is the action pinned by the generator's own oracle?
    ep = [(v, f) for v, f in dv.items() if f["target_index"] >= 0]
    n_ep = len(ep)
    stats = {
        "endpoint_worlds": n_ep,
        "selected_action_in_optimal_next_actions": round(
            sum(1 for _, f in ep if f["sel_in_opt"]) / n_ep, 4),
        "optimal_next_actions_is_singleton": round(
            sum(1 for _, f in ep if f["opt_is_singleton"]) / n_ep, 4),
        "selected_action_is_first_candidate": round(
            sum(1 for _, f in ep if f["sel_is_first_candidate"]) / n_ep, 4),
        "target_type_histogram": dict(Counter(f["target_type"] for _, f in ep)),
        "mean_candidates": round(float(np.mean([f["n_cand"] for _, f in ep])), 3),
        "mean_legal": round(float(np.mean([f["n_legal"] for _, f in ep])), 3),
    }
    # is the action a deterministic function of the WORLD alone? compare worlds with identical
    # (legal, sat, glob) gold state
    print("gold state built. endpoint worlds:", n_ep)
    print("  selected_action in optimal_next_actions:",
          stats["selected_action_in_optimal_next_actions"])
    print("  optimal_next_actions singleton:        ",
          stats["optimal_next_actions_is_singleton"])
    print("  target types:", stats["target_type_histogram"])

    # ---------- determinism bound per level
    levels = ["L1_legal", "L2_legal_plus_sat", "L3_plus_global", "L4_plus_transition"]
    det = {}
    for lv in levels:
        groups: dict[bytes, Counter] = {}
        for _, f in ep:
            groups.setdefault(f[lv].tobytes(), Counter())[f["target_index"]] += 1
        agree = sum(max(c.values()) for c in groups.values())
        det[lv] = {"distinct_gold_states": len(groups),
                   "determinism_ceiling": round(agree / n_ep, 4),
                   "state_collisions": sum(1 for c in groups.values() if len(c) > 1)}

    # ---------- 1-NN ceiling, TRAIN -> DEV
    tr_ep = [(v, f) for v, f in tr.items() if f["target_index"] >= 0]
    Xtr = {lv: np.stack([f[lv] for _, f in tr_ep]) for lv in levels}
    ytr = np.array([f["target_index"] for _, f in tr_ep])
    Xdv = {lv: np.stack([f[lv] for _, f in ep]) for lv in levels}
    ydv = np.array([f["target_index"] for _, f in ep])
    ceiling = {}
    for lv in levels:
        d = ((Xdv[lv][:, None, :] - Xtr[lv][None, :, :]) ** 2).sum(-1)
        nn = d.argmin(1)
        ceiling[lv] = {"knn1_accuracy": round(float((ytr[nn] == ydv).mean()), 4),
                       "knn1_MOVE": None, "knn1_ACTIVATE": None, "knn1_NOOP": None}
        for t in ("MOVE", "ACTIVATE", "NOOP"):
            m = np.array([f["target_type"] == t for _, f in ep])
            if m.any():
                ceiling[lv][f"knn1_{t}"] = round(float((ytr[nn][m] == ydv[m]).mean()), 4)

    # ---------- trivial baselines
    mode_idx = int(np.bincount(ytr, minlength=29).argmax())
    type_mode = Counter(f["target_type"] for _, f in tr_ep).most_common(1)[0][0]
    triv = {"TRAIN_index_mode": mode_idx,
            "TRAIN_index_mode_acc": round(float((ydv == mode_idx).mean()), 4),
            "majority_type": type_mode,
            "majority_type_acc": round(
                float(np.mean([f["target_type"] == type_mode for _, f in ep])), 4),
            "first_candidate_acc": round(
                float(np.mean([f["target_index"] == 0 for _, f in ep])), 4),
            "uniform_chance": round(1.0 / float(np.mean([f["n_cand"] for _, f in ep])), 4)}

    ladder = {
        "question": "How well can the action be determined from progressively richer GOLD state? "
                    "Parameter-free; no model is trained.",
        "population": {"TRAIN_endpoint": len(tr_ep), "DEV_endpoint": n_ep,
                       "eval": "DEV endpoint worlds only"},
        "label_audit": stats,
        "determinism_bound": det,
        "knn1_ceiling": ceiling,
        "trivial_baselines": triv,
        "reading_guide": {
            "L1": "legal only",
            "L2": "+ candidate_satisfies_goal",
            "L3": "+ global goal_satisfied / missing_information / contradiction",
            "L4": "+ optimal_next_actions membership + action-type one-hot + counts",
            "determinism_ceiling": "no learner can exceed this; it is a property of the label",
        },
    }
    p = OUT / "gold-action-sufficiency.json"
    p.write_text(json.dumps(ladder, indent=2) + "\n")
    print("\nDETERMINISM CEILING (no learner can beat this)")
    for lv in levels:
        print(f"  {lv:22s} ceiling {det[lv]['determinism_ceiling']:.4f}  "
              f"distinct states {det[lv]['distinct_gold_states']:6d}  "
              f"collisions {det[lv]['state_collisions']}")
    print("\n1-NN CEILING (TRAIN -> DEV)")
    for lv in levels:
        c = ceiling[lv]
        print(f"  {lv:22s} overall {c['knn1_accuracy']:.4f}  MOVE {c['knn1_MOVE']}  "
              f"ACTIVATE {c['knn1_ACTIVATE']}  NOOP {c['knn1_NOOP']}")
    print("\nTRIVIAL", json.dumps(triv))
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
