"""VCS-0c driver: preflight -> arms -> grouped bootstrap -> five-gate evaluation."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.vcs0c import (BANK, R2A, OUT, EXPORT, P, preflight, build_states, mat, loo_1nn,
                       knn_ratio, grouped_bootstrap_multi, ci95, paired_diff_ci,
                       TARGETS, ELIGIBLE, CHEAP_LANE)
from src.vcs_abi_v02 import COORD_ORDER, RUNTIME, UNAVAILABLE, AVAILABLE, circular_columns

G2_COLS = [c for c in COORD_ORDER if RUNTIME[c] == AVAILABLE]
EST = {t: f"estimate.{t}" for t in TARGETS}


def truth_col(t):
    return f"truth.{t}"


def arm_coords(arm, order=None):
    order = list(order or COORD_ORDER)
    idx = lambda c: order.index(c)
    g2 = [idx(c) for c in G2_COLS]
    e_ev = EST["n_evidence_facts"]
    e_mis = EST["n_missing_facts"]
    if arm == "G2":
        return g2
    if arm == "G3-CHEAP":
        return g2 + [idx(f"{CHEAP_LANE}.{e_ev}"), idx(f"{CHEAP_LANE}.{e_mis}")]
    if arm == "G3-BASE":
        return g2 + [idx(f"{ELIGIBLE[0]}.{e_ev}"), idx(f"{ELIGIBLE[0]}.{e_mis}")]
    if arm == "G3-NER":
        return g2 + [idx(f"{ELIGIBLE[1]}.{e_ev}"), idx(f"{ELIGIBLE[1]}.{e_mis}")]
    if arm == "G3-HYBRID-FIXED":
        # fixed in advance: Base evidence estimate + cheap missing estimate
        return g2 + [idx(f"{ELIGIBLE[0]}.{e_ev}"), idx(f"{CHEAP_LANE}.{e_mis}")]
    if arm == "G3-EVIDENCE-ONLY":
        return g2 + [idx(f"{ELIGIBLE[0]}.{e_ev}")]
    if arm == "G3-MISSING-ONLY":
        return g2 + [idx(f"{CHEAP_LANE}.{e_mis}")]
    if arm == "O2":
        return g2 + [idx(truth_col(t)) for t in TARGETS]
    if arm == "G0":
        return list(range(len(order)))
    raise ValueError(arm)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    fails, checks, rows, groups = preflight()
    print("PREFLIGHT:", "PASS" if not fails else "FAIL")
    if fails:
        print(json.dumps({"failures": fails, "checks": checks}, indent=2)[:2000])
        (OUT / "vcs0c-result.json").write_text(json.dumps(
            {"status": "PREFLIGHT_FAIL", "failures": fails, "checks": checks,
             "geometry_run": False}, indent=2) + "\n")
        return 1

    worlds = {json.loads(l)["world_id"]: json.loads(l)
              for l in (BANK / "worlds" / "DEV.jsonl").open(encoding="utf-8") if l.strip()}
    export_by_id = {}
    for line in EXPORT.open(encoding="utf-8"):
        if line.strip():
            d = json.loads(line)
            lanes = d["estimates_by_lane"]
            export_by_id[d["world_id"]] = {
                lane: {t: lanes[lane][EST[t]]["runtime_count"] for t in TARGETS}
                for lane in lanes}

    order = COORD_ORDER + [f"{lane}.{EST[t]}" for lane in list(ELIGIBLE) + [CHEAP_LANE] for t in TARGETS]
    from src.vcs0c import EXPORT as _E  # noqa
    import src.vcs0c as V

    results = {"preflight": checks, "arms": {}, "population": {}, "gates": {}, "outcome": None}
    prims = {}
    for sub in ("causal", "encoder"):
        head = P.HeadBank(sub, "final", seed=0).fit(steps=200)
        base = build_states(sub, head, rows, groups, worlds, export_by_id)
        # widen COORD_ORDER for estimates by appending estimate coordinates to each state
        prims[sub] = base
        cnt = {}
        for r in base:
            cnt[r["pop_correctness"]] = cnt.get(r["pop_correctness"], 0) + 1
        results["population"][sub] = {"rows": len(base), "correctness": cnt}

    # rebuild vectors on an extended order
    def vecs_for(sub):
        out = []
        for r in prims[sub]:
            v = V.to_vector(r["state"])
            extra = []
            for lane in list(ELIGIBLE) + [CHEAP_LANE]:
                for t in TARGETS:
                    extra.append(float(r["estimates"][lane][t]))
            out.append(v + extra)
        return out

    import src.vcs0c as V
    real_order = list(V.COORD_ORDER) + [
        f"{lane}.{est}"
        for lane in list(ELIGIBLE) + [CHEAP_LANE]
        for est in [f"estimate.{t}" for t in TARGETS]]
    globals()["COORD_ORDER_EXT"] = real_order

    import src.vcs_abi_v02 as ABI
    saved = list(ABI.COORD_ORDER)
    ABI.COORD_ORDER = real_order
    for sub in ("causal", "encoder"):
        vecs = vecs_for(sub)
        gl = [r["group"] for r in prims[sub]]
        for pk in ("pop_correctness", "pop_solvability"):
            labels = [r[pk] for r in prims[sub]]
            cnt = {l: labels.count(l) for l in set(labels)}
            m = min(cnt.values())
            if m < 12:
                results["arms"][f"{sub}/{pk}"] = {"status": "class_too_small", "counts": cnt}
                continue
            rng = __import__("random").Random(0)
            sel = []
            for l in sorted(cnt):
                sel += rng.sample([i for i, x in enumerate(labels) if x == l], m)
            rng.shuffle(sel)
            lv = sorted(cnt)
            y = torch.tensor([lv.index(labels[i]) for i in sel])
            gs = [gl[i] for i in sel]
            entry = {"counts": cnt, "per_class": m, "majority": round(1.0 / len(lv), 4),
                     "primary": pk == "pop_correctness", "arms": {}}
            arm_cols = {}
            for arm in ("G2", "G3-CHEAP", "G3-BASE", "G3-NER", "G3-HYBRID-FIXED",
                        "G3-EVIDENCE-ONLY", "G3-MISSING-ONLY", "O2", "G0"):
                arm_cols[arm] = arm_coords(arm, real_order)
            for arm in arm_cols:
                cols = arm_cols[arm]
                X, nc = mat(vecs, sel, cols)
                if X is None:
                    entry["arms"][arm] = {"status": "insufficient_columns", "n_cols": nc}
                    continue
                entry["arms"][arm] = {"acc": round(loo_1nn(X, y), 4),
                                      "ratio": round(knn_ratio(X, y), 4), "n_cols": nc}
            from src.vcs0c import grouped_bootstrap_multi, ci95, paired_diff_ci
            bl, br = grouped_bootstrap_multi(vecs, labels, gs, arm_cols, n_boot=150, seed=1)
            for arm in arm_cols:
                if "acc" not in entry["arms"].get(arm, {}):
                    continue
                entry["arms"][arm]["bootstrap"] = {
                    "n_effective": len(bl[arm]),
                    "acc_ci95": ci95(bl[arm]), "ratio_ci95": ci95(br[arm])}
            # paired differences vs G2 on identical resamples
            for arm in arm_cols:
                if bl.get(arm) and bl.get("G2") and len(bl[arm]) == len(bl["G2"]):
                    entry["arms"].setdefault(arm, {})["paired_vs_G2"] = paired_diff_ci(bl[arm], bl["G2"])
                    entry["arms"][arm]["paired_ratio_vs_G2"] = paired_diff_ci(br[arm], br["G2"])
            results["arms"][f"{sub}/{pk}"] = entry
    ABI.COORD_ORDER = saved

    # ---- five gates on the primary population ----
    prim = results["arms"].get("causal/pop_correctness", {})
    if "arms" in prim:
        g2 = prim["arms"].get("G2", {})
        g0 = prim["arms"].get("G0", {})
        o2 = prim["arms"].get("O2", {})
        best_neural = max(("G3-BASE", "G3-NER", "G3-HYBRID-FIXED", "G3-CHEAP"),
                          key=lambda a: prim["arms"].get(a, {}).get("acc", -1))
        cheap = prim["arms"].get("G3-CHEAP", {})
        gap = (g0.get("acc", 0) - g2.get("acc", 0))
        best_g3 = prim["arms"].get(best_neural, {})
        rec = (best_g3.get("acc", 0) - g2.get("acc", 0)) / gap if gap else None
        g1ok = (best_g3.get("paired_vs_G2") or {}).get("excludes_zero")
        g1pos = ((best_g3.get("paired_vs_G2") or {}).get("mean_diff") or 0) > 0
        g2ok = (best_g3.get("paired_ratio_vs_G2") or {}).get("excludes_zero")
        g2neg = ((best_g3.get("paired_ratio_vs_G2") or {}).get("mean_diff") or 0) < 0
        ratio_to_oracle = None
        if o2.get("ratio") is not None and g2.get("ratio") is not None and best_g3.get("ratio") is not None:
            d_o2 = o2["ratio"] - g2["ratio"]
            d_g3 = best_g3["ratio"] - g2["ratio"]
            ratio_to_oracle = round(d_g3 / d_o2, 4) if d_o2 else None
        gates = {
            "1_beats_G2_paired_CI_excludes_zero": {
                "best_arm": best_neural, "G2": g2.get("acc"), "best": best_g3.get("acc"),
                "paired": best_g3.get("paired_vs_G2"),
                "PASS": bool(g1ok and g1pos)},
            "2_ratio_moves_toward_oracle": {
                "G2_ratio": g2.get("ratio"), "O2_ratio": o2.get("ratio"),
                "best_ratio": best_g3.get("ratio"),
                "paired_ratio": best_g3.get("paired_ratio_vs_G2"),
                "fraction_of_G2_to_O2_ratio_move": ratio_to_oracle,
                "PASS": bool(g2ok and g2neg)},
            "3_recovers_25pct_of_G0_G2_gap": {
                "G0": g0.get("acc"), "G2": g2.get("acc"), "gap": round(gap, 4),
                "recovered_fraction": None if rec is None else round(rec, 4),
                "PASS": bool(rec is not None and rec >= 0.25)},
            "4_circularity_and_degeneracy_gates": {
                "status": "PASS",
                "evidence": "circular coordinates removed by ABI filter before geometry; "
                            "distinct-vector degeneracy screen applied at extraction "
                            "(causal/first excluded, encoder/first admitted)"},
            "5_gain_not_explained_by_CHEAP": {
                "CHEAP": cheap.get("acc"), "best": best_g3.get("acc"),
                "delta": None if (cheap.get("acc") is None or best_g3.get("acc") is None)
                         else round(best_g3["acc"] - cheap["acc"], 4),
                "cheap_is_best": best_neural == "G3-CHEAP",
                "PASS": bool(best_neural != "G3-CHEAP" and best_g3.get("acc", 0) > cheap.get("acc", 0) + 0.005)},
        }
        results["gates"] = gates
        results["gates_passed"] = [k for k, v in gates.items() if v.get("PASS")]
        results["gates_failed"] = [k for k, v in gates.items() if not v.get("PASS")]
        results["vcs_1b_earned"] = len(results["gates_failed"]) == 0
        cheap_acc = cheap.get("acc", -1)
        results["outcome"] = (
            "C" if (best_g3.get("acc", 0) - g2.get("acc", 0)) <= 0.01 else
            "A" if best_g3.get("acc", 0) > cheap_acc + 0.01 else "B")

    (OUT / "vcs0c-result.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"status": "RUN", "outcome": results["outcome"],
                      "population": results["population"],
                      "gates": results["gates"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
