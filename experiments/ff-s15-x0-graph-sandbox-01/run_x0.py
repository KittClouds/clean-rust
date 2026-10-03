"""X0/X2/X4 sandbox driver.

  python run_x0.py clean   # experiments 1 and 2 on full DEV (plus flat baselines trained on TRAIN) -> results/x0-clean.json
  python run_x0.py noise   # experiment 3, seeded 5,000-world DEV subsample                    -> results/x0-noise.json
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from xg import bank, build, control, flat  # noqa: E402

RES = ROOT / "results"


def norm_key(pred, args):
    return (pred, tuple(sorted(args)) if pred == "CONNECTED" else tuple(args))


def cand_keys(view, cands):
    out = set()
    for c in cands:
        a = view.pats.get(c)
        if a:
            out.add(norm_key(a["pred"], a["args"]))
    return out


def has_dup_alias(r):
    seen = Counter(x for e in r["entities"] for x in set(e.get("aliases", [])))
    return any(v > 1 for v in seen.values())


def signature(r):
    """Post hoc: what structural signature (if any) does this label have in the record?"""
    lc = bank.label_class(r)
    if lc == "ABSTAIN/INSUFFICIENT_EVIDENCE":
        if r["missing_information"]:
            return "missing fact removed"
        if r["goal"]["pred"] not in ("AT", "STATE"):
            return "goal outside action closure"
        if has_dup_alias(r):
            return "duplicated alias"
        return "no signature"
    if lc == "ASK":
        return "missing fact removed"
    return lc


def summarize(by_class):
    """3-way decision metrics from {label class: {decision: n}}."""
    tot = sum(sum(c.values()) for c in by_class.values())
    lab = lambda c: c.split("/")[0]  # noqa: E731
    agree = sum(n for lc, c in by_class.items() for d, n in c.items() if lab(lc) == d)
    ask_pred = sum(c.get("ASK", 0) for c in by_class.values())
    ask_hit = by_class.get("ASK", {}).get("ASK", 0)
    ask_lab = sum(by_class.get("ASK", {}).values())
    act_lab = sum(sum(c.values()) for lc, c in by_class.items() if lab(lc) == "ACT")
    act_ok = sum(c.get("ACT", 0) for lc, c in by_class.items() if lab(lc) == "ACT")
    non_lab = tot - act_lab
    non_ok = sum(n for lc, c in by_class.items() if lab(lc) != "ACT" for d, n in c.items() if d != "ACT")
    return {"decision_accuracy": agree / tot, "ask_recall": ask_hit / ask_lab, "ask_precision": ask_hit / ask_pred if ask_pred else None,
            "act_labelled_acted": act_ok / act_lab, "nonact_labelled_not_acted": non_ok / non_lab}


def clean(limit=None):
    dev = bank.load("DEV", limit)
    n = len(dev)
    systems = {"graph_path": (False, False), "graph_path_slots": (True, False), "graph_path_slots_alias": (True, True)}
    conf = {k: defaultdict(Counter) for k in systems}
    sig_conf = {k: defaultdict(Counter) for k in systems}
    act = {k: Counter() for k in systems}
    phys = {k: Counter() for k in systems}
    ask_ident = []
    ask_rel = Counter()
    reason_ok = Counter()
    slot_missing_by_label = Counter()
    for r in dev:
        G = build.build_graph(r)
        v = control.View(G)
        lc, sg = bank.label_class(r), signature(r)
        for name, (comp, amb) in systems.items():
            d = control.decide(G, hi=0.5, completeness=comp, ambiguity=amb, view=v)
            conf[name][lc][d["decision"]] += 1
            sig_conf[name][sg][d["decision"]] += 1
            if d["decision"] == "ACT" and r["decision"] == "ACT":
                if (d["action"] or {}).get("type") == "NOOP":
                    act[name]["noop_ok" if bank.sim.goal_satisfied(r["initial_state"], r["goal"]) else "noop_bad"] += 1
                else:
                    act[name]["ok" if bank.first_action_ok(r, d["action"]) else "bad"] += 1
            if d["reason"] not in ("CONFLICTING_EVIDENCE", "UNKNOWN_ENTITY", "OUT_OF_SCOPE", "AMBIGUOUS_REFERENCE") and d["decision"] != "ASK" or d["ask_kind"] == "missing":
                oc = bank.sim.oracle(r["initial_state"], r["available_actions"], r["goal"])
                phys[name][f"oracle_{oc['decision']}|controller_{'ACT' if d['decision'] == 'ACT' else 'not_ACT'}"] += 1
            if name == "graph_path_slots_alias" and r["decision"] == "ABSTAIN" and d["decision"] == "ABSTAIN":
                reason_ok[(r["abstain_reason"], d["reason"])] += 1
            if name == "graph_path_slots_alias" and r["decision"] == "ASK":
                plan = bank.sim.shortest_plan(r["initial_state"], r["available_actions"], r["goal"])
                needed = not (plan is not None or bank.sim.goal_satisfied(r["initial_state"], r["goal"]))
                ask_rel["removed fact on the goal path" if needed else "removed fact not needed for the goal"] += 1
                if d["decision"] == "ASK":
                    m = r["missing_information"][0]
                    if d["ask_kind"] == "slot":
                        keys = set()
                        for c in d["candidates"]:
                            if c.startswith("slot:"):
                                _s, kind, ent = c.split(":")
                                keys.add(("AT" if kind == "AT" else "STATE" if kind == "STATE" else "LINK", ent))
                            else:
                                a = v.pats[c]
                                keys.add(norm_key("CONNECTED", a["args"]))
                        mk = norm_key(m["pred"], m["args"])
                        hit = (mk in keys) or (m["pred"] in ("AT", "STATE") and (m["pred"], m["args"][0]) in keys) or (m["pred"] == "CONNECTED" and any(("LINK", x) in keys for x in m["args"]))
                    else:
                        keys = cand_keys(v, d["candidates"])
                        hit = norm_key(m["pred"], m["args"]) in keys
                    ask_ident.append({"hit": bool(hit), "size": len(keys), "kind": m["pred"], "ask_kind": d["ask_kind"]})
    blocked_by_label = defaultdict(Counter)
    alias_by_label = defaultdict(Counter)
    for r in dev:
        lc = bank.label_class(r)
        blocked_by_label[lc][str(min(sum(1 for f in r["initial_state"] if f["pred"] == "BLOCKED"), 2))] += 1
        alias_by_label[lc][str(has_dup_alias(r))] += 1
    # flat baselines
    train = bank.load("TRAIN", 20000)
    cls = {c: i for i, c in enumerate(flat.CLASSES)}
    ymap = lambda r: cls[r["decision"]]  # noqa: E731
    ytr = np.array([ymap(r) for r in train])
    lcs = [bank.label_class(r) for r in dev]
    flat_conf = {}
    for name, plus in (("flat", False), ("flat+", True)):
        Xtr = np.array([flat.features(r, plus) for r in train])
        Xdv = np.array([flat.features(r, plus) for r in dev])
        tree = flat.Tree(depth=10, min_leaf=20).fit(Xtr, ytr)
        pred = [flat.CLASSES[tree.predict_one(x)] for x in Xdv]
        by = defaultdict(Counter)
        for lc_i, p in zip(lcs, pred):
            by[lc_i][p] += 1
        flat_conf[name] = by
    allc = {**{k: conf[k] for k in systems}, **flat_conf}
    out = {
        "n_dev": n,
        "summary": {k: summarize(c) for k, c in allc.items()},
        "by_label_class": {k: {lc: dict(c) for lc, c in v.items()} for k, v in allc.items()},
        "graph_by_signature": {k: {sg: dict(c) for sg, c in v.items()} for k, v in sig_conf.items()},
        "abstain_reason_names": {f"{a}|{b}": c for (a, b), c in reason_ok.items()},
        "act_actions": {k: dict(v) for k, v in act.items()},
        "physics_agreement": {k: dict(v) for k, v in phys.items()},
        "ask_label_relevance": dict(ask_rel),
        "ask_identifiability": {"n": len(ask_ident), "hit": sum(x["hit"] for x in ask_ident), "mean_candidates": float(np.mean([x["size"] for x in ask_ident])) if ask_ident else None,
                                "by_missing_kind": {k: {"n": sum(1 for x in ask_ident if x["kind"] == k), "hit": sum(1 for x in ask_ident if x["kind"] == k and x["hit"]),
                                                        "mean_candidates": float(np.mean([x["size"] for x in ask_ident if x["kind"] == k])) if any(x["kind"] == k for x in ask_ident) else None} for k in ("AT", "STATE", "CONNECTED")}},
        "blocked_count_by_label_(0,1,2+)": {k: dict(v) for k, v in blocked_by_label.items()},
        "duplicated_alias_by_label": {k: dict(v) for k, v in alias_by_label.items()},
        "graph_digest_sample": build.build_graph(dev[0]).digest(),
    }
    RES.mkdir(exist_ok=True)
    (RES / "x0-clean.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="ascii", newline="\n")
    for k, v in out["summary"].items():
        print(k, {a: (round(b, 3) if b is not None else None) for a, b in v.items()})
    print(out["act_actions"], out["ask_label_relevance"], out["ask_identifiability"]["n"], out["ask_identifiability"]["hit"])


def clip(x):
    return max(0.0, min(1.0, x))


def make_producer(sigma, halluc, salt):
    def prod(record, patterns):
        rng = random.Random(int.from_bytes(hashlib.sha256(f"{salt}|{sigma}|{record['world_id']}".encode()).digest()[:8], "big"))
        fw = {f["id"]: clip(0.8 + sigma * rng.gauss(0, 1)) for f in record["initial_state"]}
        held = {build.pat_id(*build._fact_pattern(f)) for f in record["initial_state"] if build._fact_pattern(f)}
        ph = {pid: clip(0.35 + sigma * rng.gauss(0, 1)) for pid in sorted(patterns) if pid not in held and rng.random() < halluc}
        return fw, ph
    return prod


def outcome(r, d):
    """(useful, harmful, acted) for one decision in the true world."""
    if d["decision"] != "ACT":
        return 0, 0, 0
    lc = bank.label_class(r)
    noop = (d["action"] or {}).get("type") == "NOOP"
    if lc == "ACT/goal_already":
        good = noop
    elif lc == "ACT/plan":
        good = (not noop) and bank.first_action_ok(r, d["action"])
    else:
        good = False
    return int(good), int(not good), 1


def reveal(G, candidates):
    """One round of oracle answers: every fact behind an asked pattern or slot is confirmed (all its supports go to 1.0); hallucinated supports on it go to 0."""
    for c in candidates:
        for e in list(G.into(c, "SUPPORTS")):
            src = e["src"]
            if G.nodes[src]["pred"] == "PHANTOM":
                for x in G.out(src, "SUPPORTS"):
                    x["weight"] = 0.0
            else:
                for x in G.out(src, "SUPPORTS"):
                    x["weight"] = 1.0
    return G


def frontier_gap(defer_pt, hard_pts):
    """defer harm minus the HARD lower-envelope harm interpolated at the DEFER point's coverage (negative: DEFER is better)."""
    pts = sorted(hard_pts)
    env, best = [], 1e9
    for c, h in sorted(pts, key=lambda t: (-t[0], t[1])):  # from high coverage down: envelope of min harm at >= coverage
        best = min(best, h)
        env.append((c, best))
    env.sort()
    c0 = defer_pt[0]
    if c0 <= env[0][0]:
        return defer_pt[1] - env[0][1], "below the swept range"
    if c0 >= env[-1][0]:
        return defer_pt[1] - env[-1][1], "above the swept range"
    for (c1, h1), (c2, h2) in zip(env, env[1:]):
        if c1 <= c0 <= c2:
            t = 0 if c2 == c1 else (c0 - c1) / (c2 - c1)
            return defer_pt[1] - (h1 + t * (h2 - h1)), "interpolated"
    return None, "n/a"


def noise(n=5000):
    dev = bank.load("DEV")
    rng = random.Random(20260930)
    sample = rng.sample(dev, n)
    # keep worlds the clean controller already gets right, so the sweep measures noise and not BANK's label conventions
    keep = []
    for r in sample:
        d = control.decide(build.build_graph(r), hi=0.5, completeness=True, ambiguity=True)
        lc = bank.label_class(r)
        ok = d["decision"] == r["decision"] and (d["decision"] != "ACT" or outcome(r, d)[0] == 1)
        if ok:
            keep.append(r)
    act_lab = sum(1 for r in keep if bank.label_class(r).startswith("ACT"))
    taus = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    defers = [(0.3, 0.7), (0.4, 0.6), (0.2, 0.8)]
    out = {"sample": n, "kept": len(keep), "act_labelled_kept": act_lab, "halluc_per_unsupported_pattern": 0.02, "sigmas": {}}
    for sigma in (0.0, 0.1, 0.2, 0.3):
        prod = make_producer(sigma, 0.02, "x0")
        cfgs = {("hard", t): (t, None, True) for t in taus}
        cfgs.update({("asym", lo, hi): (hi, lo, False) for lo, hi in defers})
        cfgs.update({("defer", lo, hi): (hi, lo, True) for lo, hi in defers})
        tally = {k: Counter() for k in cfgs}
        after = {(lo, hi): Counter() for lo, hi in defers}
        for r in keep:
            G = build.build_graph(r, prod, "noisy")
            v = control.View(G)
            for k, (hi, lo, ver) in cfgs.items():
                d = control.decide(G, hi=hi, lo=lo, completeness=True, ambiguity=True, verify=ver, view=v)
                u, h, a = outcome(r, d)
                t = tally[k]
                t["useful"] += u
                t["harm"] += h
                t["acted"] += a
                t[d["decision"]] += 1
                if k[0] == "defer":
                    key = (k[1], k[2])
                    if d["decision"] == "ASK" and d["candidates"]:
                        G2 = reveal(build.build_graph(r, prod, "noisy"), d["candidates"])
                        d2 = control.decide(G2, hi=hi, lo=lo, completeness=True, ambiguity=True, verify=True)
                        u2, h2, a2 = outcome(r, d2)
                        after[key]["asked_worlds"] += 1
                        after[key]["questions"] += len(d["candidates"])
                        after[key]["useful"] += u2
                        after[key]["harm"] += h2
                        after[key]["still_not_act"] += 1 - a2
                    else:
                        after[key]["useful"] += u
                        after[key]["harm"] += h
        rows = {}
        for k, t in tally.items():
            rows["|".join(str(x) for x in k)] = {"coverage": t["useful"] / act_lab, "harm_rate": t["harm"] / len(keep), "harmful_acts": t["harm"], "useful_acts": t["useful"], "ask": t["ASK"], "abstain": t["ABSTAIN"], "act": t["ACT"]}
        hard_pts = [(rows[f"hard|{t}"]["coverage"], rows[f"hard|{t}"]["harm_rate"]) for t in taus]
        gaps = {}
        for lo, hi in defers:
            row = rows[f"defer|{lo}|{hi}"]
            g, how = frontier_gap((row["coverage"], row["harm_rate"]), hard_pts)
            gaps[f"{lo}|{hi}"] = {"harm_minus_hard_frontier": g, "how": how}
        recover = {f"{lo}|{hi}": {"coverage_after_one_round": after[(lo, hi)]["useful"] / act_lab, "harm_rate_after_one_round": after[(lo, hi)]["harm"] / len(keep), "asked_worlds": after[(lo, hi)]["asked_worlds"],
                                  "mean_questions_per_asked_world": (after[(lo, hi)]["questions"] / after[(lo, hi)]["asked_worlds"]) if after[(lo, hi)]["asked_worlds"] else None} for lo, hi in defers}
        out["sigmas"][str(sigma)] = {"points": rows, "defer_vs_hard_frontier": gaps, "one_round_oracle_answers": recover}
        print(sigma, {k: (round(v["coverage"], 3), round(v["harm_rate"], 4)) for k, v in rows.items()})
        print("   gaps", {k: (round(v["harm_minus_hard_frontier"], 4), v["how"]) for k, v in gaps.items()})
        print("   recover", {k: (round(v["coverage_after_one_round"], 3), round(v["harm_rate_after_one_round"], 4), v["mean_questions_per_asked_world"] and round(v["mean_questions_per_asked_world"], 1)) for k, v in recover.items()})
    RES.mkdir(exist_ok=True)
    (RES / "x0-noise.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="ascii", newline="\n")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "clean"
    if mode == "clean":
        clean(int(sys.argv[2]) if len(sys.argv) > 2 else None)
    elif mode == "noise":
        noise(int(sys.argv[2]) if len(sys.argv) > 2 else 5000)
    else:
        raise SystemExit("usage: run_x0.py clean|noise")
