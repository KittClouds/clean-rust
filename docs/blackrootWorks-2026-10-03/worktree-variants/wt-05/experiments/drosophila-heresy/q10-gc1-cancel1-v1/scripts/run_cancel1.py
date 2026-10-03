"""Q10-GC1-CANCEL1 bounded replacement (uses RQ1 runtime)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
RQ1 = REPO / "experiments/drosophila-heresy/q10-gc1-rq1-v1/scripts"
F2 = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0 = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(RQ1))
sys.path.insert(0, str(F2))
sys.path.insert(0, str(GC0))
sys.dont_write_bytecode = True
import run_rq1 as RQ  # noqa: E402
import run_rh1 as RH1  # noqa: E402

PROTOCOL = "Q10-GC1-CANCEL1"
IDENTITY = "q10-gc1-cancel1-v1"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"


def require(c: bool, m: str) -> None:
    if not c:
        raise RuntimeError(m)


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def atomic_write(p: Path, v: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    t = p.with_suffix(p.suffix + ".tmp")
    t.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(t, p)


def qkey(s):
    return (int(s["mismatch_count"]), int(s["total_ulp_distance"]), float(s["residual_l2"]), float(s["maximum_absolute_residual"]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    contract = read_json(ROOT / "CONTRACT.json")
    pre = read_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "CANCEL1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "CANCEL1 pre drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "CANCEL1 plan drift")
    require(contract["sealed_runner_sha256"] == digest(Path(__file__)), "CANCEL1 runner drift")
    before = {}
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        h = digest(p)
        require(h == str(e["sha256"]).upper(), f"CANCEL1 parent drift: {e['label']}")
        before[str(e["path"])] = h
    if EXECUTION.exists() and not a.force:
        raise SystemExit("CANCEL1 receipt exists")
    pf5c = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    gates = pf5c["geometry"]["final_da2_gates"]
    thr = {"axis_normalized_error": float(gates["axis_normalized_abs"]), "norm_normalized_error": float(gates["norm_normalized_abs"]), "cue_linear_normalized_error": float(gates["cue_linear_normalized_abs"])}
    par8 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json")
    receipts = sorted(par8["endpoint_set_results"], key=lambda r: (r["endpoint"], r["set_index"]))
    invalid = [r for r in receipts if not bool(r["best_search"]["final_geometry_pass"])]
    require(len(invalid) == 8, f"CANCEL1 invalid cohort drift: {len(invalid)}")
    tasks = {(str(r["endpoint"]), int(r["set_index"])) for r in invalid}
    _, states, _ = RH1.load_runtime(tasks)
    pals: dict[tuple[str, int], dict[int, dict]] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        k = (str(g["identity"][0]), int(g["identity"][1]))
        if k not in tasks:
            continue
        pals.setdefault(k, {})[int(g["identity"][2])] = g
    # Stage A preflight counts (frozen before replay)
    preflight_singles = 0
    per_case_alts: dict[tuple[str, int], list[tuple[int, str, str]]] = {}
    for rec in invalid:
        k = (str(rec["endpoint"]), int(rec["set_index"]))
        base_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_search"]["selected_candidates"]}
        alts = []
        for gi, cur in base_sel.items():
            for cand in pals[k][gi]["palette"]:
                ident = str(cand["candidate_identity"])
                if ident == cur:
                    continue
                alts.append((gi, cur, ident))
        # deterministic order
        alts.sort(key=lambda x: (x[0], x[2]))
        per_case_alts[k] = alts
        preflight_singles += len(alts)
    require(preflight_singles <= 6406, f"CANCEL1 single domain exceeds bound: {preflight_singles}")
    # Stage A replay
    singles_results = []
    alias_count = 0
    seen_single_weights: dict[str, str] = {}
    # need S and V reference per case
    for rec in invalid:
        k = (str(rec["endpoint"]), int(rec["set_index"]))
        st = states[k]
        groups = pals[k]
        s_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_search"]["selected_candidates"]}
        v_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_valid"]["selected_candidates"]}
        s_res, _ = RQ.materialize(st, groups, s_sel)
        v_res, _ = RQ.materialize(st, groups, v_sel)
        v_key = qkey(v_res["score"])
        s_n = int(s_res["score"]["mismatch_count"])
        v_n = int(v_res["score"]["mismatch_count"])
        # S signed geometry for shortlist opposition
        s_geo = s_res["geometry"]
        s_axis = (float(s_geo["final_axis"]) - float(s_geo["target_axis"])) / max(abs(float(s_geo["target_axis"])), 1.0e-12)
        # qL_S vector: need W-T per row; recompute from weight bits
        import struct as _st
        def _f(r): return _st.unpack("<f", _st.pack("<I", r & 0xFFFFFFFF))[0]
        W = tuple(RH1.PF5.from_bits(x) for x in s_res["weight_bits"])
        T = tuple(st.target_weights)
        qL_S = tuple(sum(W[i] - T[i] for i in row) for row in st.rows)
        case_singles = []
        for (gi, cur, alt) in per_case_alts[k]:
            sel = dict(s_sel)
            sel[gi] = alt
            r, cached = RQ.materialize(st, groups, sel)
            if r["weight_hash"] in seen_single_weights:
                alias_count += 1
            else:
                seen_single_weights[r["weight_hash"]] = f"{k[0]}#set{k[1]}/single/{gi}/{alt}"
            # gate ratios
            ratios = {gk: float(r["geometry"][gk]) / thr[gk] for gk in thr}
            max_ratio = max(ratios.values())
            excess = sum(max(0.0, v - 1.0) for v in ratios.values())
            # damaged vs baseline: need baseline-exact rows mismatched in r
            # compute via readout vs target/baseline? Use score + RQ internals? Recompute quickly:
            base_out = RQ.replay(st.rows, st.baseline_weight_bits)
            tgt_out = RQ.replay(st.rows, st.target_weight_bits)
            actual = tuple(int(x) for x in r["readout"])
            damaged = sum(1 for bb, tt, ss in zip(base_out, tgt_out, actual) if bb == tt and ss != tt)
            # axis change + linear opposition
            g = r["geometry"]
            s_ax = (float(g["final_axis"]) - float(g["target_axis"])) / max(abs(float(g["target_axis"])), 1.0e-12)
            d_axis = s_ax - s_axis
            # qL_rec
            Wr = tuple(RH1.PF5.from_bits(x) for x in r["weight_bits"])
            qL_r = tuple(sum(Wr[i] - T[i] for i in row) for row in st.rows)
            d_lin = tuple(a - b for a, b in zip(qL_r, qL_S))
            dot = math.fsum(a * b for a, b in zip(d_lin, qL_S))
            opp = -dot  # positive means change opposes S debt
            def sgn(x):
                return 1 if x > 0 else (-1 if x < 0 else 0)
            bucket_key = (gi, sgn(d_axis), sgn(opp))
            # outcome vs V
            w_ne_tb = tuple(r["weight_bits"]) != tuple(int(x) for x in st.target_weight_bits) and tuple(r["weight_bits"]) != tuple(int(x) for x in st.baseline_weight_bits)
            if tuple(actual) == tuple(tgt_out) and bool(r["final_pass"]) and w_ne_tb:
                outcome = "EXACT_ALTERNATIVE"
            elif bool(r["final_pass"]) and w_ne_tb and qkey(r["score"]) < v_key:
                outcome = "VALID_ADVANTAGE_PRESERVED"
            elif bool(r["final_pass"]) and w_ne_tb and qkey(r["score"]) == v_key:
                outcome = "VALID_TIE_NON_SUCCESS"
            elif bool(r["final_pass"]):
                outcome = "VALID_WORSE_NON_SUCCESS"
            elif qkey(r["score"]) < qkey(s_res["score"]):
                outcome = "INVALID_IMPROVEMENT_NON_SUCCESS"
            else:
                outcome = "INVALID_OTHER_NON_SUCCESS"
            denom = v_n - s_n
            gap = None
            if denom > 0:
                gap = (v_n - int(r["score"]["mismatch_count"])) / denom
            case_singles.append({"group": gi, "from": cur, "to": alt, "score": r["score"], "geometry": r["geometry"], "ratios": ratios, "max_ratio": max_ratio, "excess": excess, "damaged": damaged, "d_axis": d_axis, "opp": opp, "bucket": list(bucket_key), "outcome": outcome, "final_pass": bool(r["final_pass"]), "weight_hash": r["weight_hash"], "gap_retention": gap})
            singles_results.append({"endpoint": k[0], "set_index": k[1], "group": gi, "from": cur, "to": alt, "outcome": outcome, "final_pass": bool(r["final_pass"]), "mismatch": int(r["score"]["mismatch_count"]), "v_mismatch": v_n, "s_mismatch": s_n, "gap_retention": gap, "weight_hash": r["weight_hash"]})
        # Stage B shortlist: frozen rule
        # 1) up to 16 geometry-repair sorted by max_ratio, excess, Q
        by_geo = sorted(case_singles, key=lambda x: (x["max_ratio"], x["excess"], (x["score"]["mismatch_count"], x["score"]["total_ulp_distance"], x["score"]["residual_l2"], x["score"]["maximum_absolute_residual"])))
        short: list[dict] = []
        seen_keys = set()
        for x in by_geo[:16]:
            key2 = (x["group"], x["to"])
            if key2 not in seen_keys:
                seen_keys.add(key2)
                short.append(x)
        # 2) up to 8 collateral-repair sorted by damaged, Q, excess
        by_col = sorted([x for x in case_singles if (x["group"], x["to"]) not in seen_keys], key=lambda x: (x["damaged"], x["score"]["mismatch_count"], x["score"]["total_ulp_distance"], x["excess"]))
        for x in by_col[:8]:
            key2 = (x["group"], x["to"])
            if key2 not in seen_keys:
                seen_keys.add(key2)
                short.append(x)
        # 3) round-robin fill to 32 across buckets
        buckets: dict[tuple, list[dict]] = {}
        for x in case_singles:
            if (x["group"], x["to"]) in seen_keys:
                continue
            buckets.setdefault(tuple(x["bucket"]), []).append(x)
        for lst in buckets.values():
            lst.sort(key=lambda x: (x["group"], x["to"]))
        order_buckets = sorted(buckets.keys())
        idx = 0
        while len(short) < 32 and buckets:
            progressed = False
            for bk in order_buckets:
                lst = buckets.get(bk, [])
                if idx < len(lst):
                    x = lst[idx]
                    key2 = (x["group"], x["to"])
                    if key2 not in seen_keys:
                        seen_keys.add(key2)
                        short.append(x)
                        progressed = True
                    if len(short) >= 32:
                        break
            idx += 1
            if not progressed:
                break
        # pairs among shortlist
        pair_results = []
        n_pairs = 0
        for i in range(len(short)):
            for j in range(i + 1, len(short)):
                a1, a2 = short[i], short[j]
                if a1["group"] == a2["group"]:
                    continue
                sel = dict(s_sel)
                sel[a1["group"]] = a1["to"]
                sel[a2["group"]] = a2["to"]
                r, _ = RQ.materialize(st, groups, sel)
                n_pairs += 1
                actual = tuple(int(x) for x in r["readout"])
                w_ne_tb = tuple(r["weight_bits"]) != tuple(int(x) for x in st.target_weight_bits) and tuple(r["weight_bits"]) != tuple(int(x) for x in st.baseline_weight_bits)
                if tuple(actual) == tuple(tgt_out) and bool(r["final_pass"]) and w_ne_tb:
                    outcome = "EXACT_ALTERNATIVE"
                elif bool(r["final_pass"]) and w_ne_tb and qkey(r["score"]) < v_key:
                    outcome = "VALID_ADVANTAGE_PRESERVED"
                else:
                    outcome = "PAIR_NON_SUCCESS"
                denom = v_n - s_n
                gap = (v_n - int(r["score"]["mismatch_count"])) / denom if denom > 0 else None
                pair_results.append({"groups": [a1["group"], a2["group"]], "outcome": outcome, "mismatch": int(r["score"]["mismatch_count"]), "gap": gap, "weight_hash": r["weight_hash"]})
        # store per-case pair summary into singles_results? keep separate list via contract? append summary records
        singles_results.append({"endpoint": k[0], "set_index": k[1], "group": "__PAIR_SCREEN__", "from": f"shortlist={len(short)}", "to": f"pairs={n_pairs}", "outcome": f"PAIRS_{sum(1 for p in pair_results if p['outcome']=='VALID_ADVANTAGE_PRESERVED')}_VALID_ADVANTAGE", "final_pass": False, "mismatch": -1, "v_mismatch": v_n, "s_mismatch": s_n, "gap_retention": None, "weight_hash": f"pairs={n_pairs}"})
        # attach detailed pairs to a sidecar? to bound size, keep counts + successes only
        for p in pair_results:
            if p["outcome"] in ("VALID_ADVANTAGE_PRESERVED", "EXACT_ALTERNATIVE"):
                singles_results.append({"endpoint": k[0], "set_index": k[1], "group": f"pair_{p['groups'][0]}_{p['groups'][1]}", "from": "S", "to": "pair", "outcome": p["outcome"], "final_pass": True, "mismatch": p["mismatch"], "v_mismatch": v_n, "s_mismatch": s_n, "gap_retention": p["gap"], "weight_hash": p["weight_hash"]})
    # outcomes tally
    from collections import Counter
    tally = dict(Counter(x["outcome"] for x in singles_results if not str(x["group"]).startswith("pair_") and x["group"] != "__PAIR_SCREEN__"))
    for e in contract["parent_bindings"]:
        require(digest(REPO / str(e["path"])) == before[str(e["path"])], f"CANCEL1 parent changed: {e['label']}")
    out = {"protocol": PROTOCOL, "identity": IDENTITY, "scope": "singles + screened pairs around 8 invalid S; S never updated", "sources": before, "parents_unchanged": True, "preflight_singles": preflight_singles, "executed_singles": sum(1 for x in singles_results if isinstance(x.get("group"), int)), "single_alias_dedup": alias_count, "unique_single_weights": len(seen_single_weights), "tally": tally, "results": singles_results, "checks_passed": True}
    atomic_write(EXECUTION, out)
    n_adv = sum(1 for x in singles_results if x.get("outcome") == "VALID_ADVANTAGE_PRESERVED")
    n_exact = sum(1 for x in singles_results if x.get("outcome") == "EXACT_ALTERNATIVE")
    summ = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "CANCEL1_SCREEN_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": {"preflight_singles": preflight_singles, "valid_advantage": n_adv, "exact": n_exact}, "gate": {"s_frozen": True, "domain_bounded": True, "parents_unchanged": True, "behavioral_probe": False}, "interpretation": "Bounded replacement around invalid search states; negatives are domain-bounded, not infeasibility."}
    atomic_write(SUMMARY, summ)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join([f"# {PROTOCOL} result", "", f"Preflight singles: **{preflight_singles}**; valid-advantage: **{n_adv}**; exact: **{n_exact}**.", "", "Screened-pair domain only; no palette or assembly rejection.", ""]), encoding="utf-8", newline="\n")
    stat = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summ["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    atomic_write(STATUS, stat)
    print(f"CANCEL1 complete: singles={preflight_singles} advantage={n_adv} exact={n_exact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
