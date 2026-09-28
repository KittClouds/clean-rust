"""Q10-GC1-D1 saved-state failure anatomy (no new replay)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
F2 = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0 = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(F2))
sys.path.insert(0, str(GC0))
sys.dont_write_bytecode = True
import run_rh1 as RH1  # noqa: E402
import run_gc0 as GC0RUN  # noqa: E402

PROTOCOL = "Q10-GC1-D1"
IDENTITY = "q10-gc1-d1-v1"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"
LEGAL = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise RuntimeError(msg)


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def write_json(p: Path, v: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def bits_hash(vals) -> str:
    return hashlib.sha256(b"".join(int(v).to_bytes(4, "little", signed=False) for v in vals)).hexdigest().upper()


def f(raw: int) -> float:
    return struct.unpack("<f", struct.pack("<I", raw & 0xFFFFFFFF))[0]


def bits(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", v))[0]


def order(raw: int) -> int:
    return (0x80000000 - (raw & 0x7FFFFFFF)) if raw & 0x80000000 else raw + 0x80000000


def replay(rows, raw_weights):
    ws = [f(b) for b in raw_weights]
    out = []
    for row in rows:
        acc = -0.0
        for i in row:
            acc = f(bits(acc + ws[i]))
        out.append(bits(acc))
    return tuple(out)


def score_of(actual, target):
    errs = [f(a) - f(b) for a, b in zip(actual, target)]
    return {
        "mismatch_count": sum(a != b for a, b in zip(actual, target)),
        "total_ulp_distance": sum(abs(order(a) - order(b)) for a, b in zip(actual, target)),
        "residual_l2": math.sqrt(math.fsum(e * e for e in errs)),
        "maximum_absolute_residual": max(map(abs, errs), default=0.0),
    }


def qkey(s):
    return (int(s["mismatch_count"]), int(s["total_ulp_distance"]), float(s["residual_l2"]), float(s["maximum_absolute_residual"]))


def load_palettes(path: Path, tasks: set[tuple[str, int]]):
    pals: dict[tuple[str, int], dict[int, dict]] = {}
    n_entries = 0
    n_zero = 0
    for line in path.open(encoding="utf-8"):
        g = json.loads(line)
        ep, si = str(g["identity"][0]), int(g["identity"][1])
        if (ep, si) not in tasks:
            continue
        gi = int(g["identity"][2])
        require(gi not in pals.setdefault((ep, si), {}), "duplicate palette group")
        pals[(ep, si)][gi] = g
        n_entries += len(g["palette"])
        n_zero += sum(1 for c in g["palette"] if c.get("roles") == ["ZERO"])
    return pals, n_entries, n_zero


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="overwrite existing D1 receipt")
    a = ap.parse_args()
    contract = read_json(ROOT / "CONTRACT.json")
    pre = read_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "D1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "D1 pre identity drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "D1 plan drift")
    require(contract["sealed_runner_sha256"] == digest(Path(__file__)), "D1 runner drift")
    require(pre["plan_sha256"] == digest(ROOT / "PLAN.md"), "D1 pre plan drift")
    require(pre["contract_sha256"] == digest(ROOT / "CONTRACT.json"), "D1 pre contract drift")
    require(pre["runner_sha256"] == digest(Path(__file__)), "D1 pre runner drift")
    before: dict[str, str] = {}
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        h = digest(p)
        require(h == str(e["sha256"]).upper(), f"D1 parent drift: {e['label']}")
        before[str(e["path"])] = h
    if EXECUTION.exists() and not a.force:
        raise SystemExit("D1 receipt exists; use --force only for a fresh frozen re-run into an empty dir")
    par8_path = REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json"
    pal_path = REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
    pf5_contract = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    gates = pf5_contract["geometry"]["final_da2_gates"]
    thr = {"axis_normalized_error": float(gates["axis_normalized_abs"]), "norm_normalized_error": float(gates["norm_normalized_abs"]), "cue_linear_normalized_error": float(gates["cue_linear_normalized_abs"])}
    execution = read_json(par8_path)
    receipts = execution["endpoint_set_results"]
    require(len(receipts) == 14, "PAR8 case cardinality drift")
    tasks = {(str(r["endpoint"]), int(r["set_index"])) for r in receipts}
    require(len(tasks) == 14, "PAR8 task key drift")
    require(int(execution["counts"]["exact_evaluations"]) == 323648, "PAR8 eval count drift")
    pals, n_entries, n_zero = load_palettes(pal_path, tasks)
    require(sum(len(v) for v in pals.values()) == 801, f"D1 group count drift: {sum(len(v) for v in pals.values())}")
    # one preserved shortfall: parent reports 800 complete palettes + 1 shortfall; total entries 7207 incl 801 ZERO
    # verify against full-file counts via PF0? PF0 covers same 14 tasks.
    pf0 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-pf0-v1/qualification/execution.json")
    require(int(pf0["counts"]["raw_group_count"]) == 801 and int(pf0["counts"]["palette_count"]) == 7207, "PF0 library drift")
    _, states, _ = RH1.load_runtime(tasks)
    # coordinate ownership check per case (expect disjoint)
    overlap_report = {}
    for key in tasks:
        owner: dict[int, list[int]] = {}
        for gi, g in pals[key].items():
            for c in g["coordinates_canonical"]:
                owner.setdefault(int(c), []).append(int(gi))
        ov = {c: o for c, o in owner.items() if len(o) > 1}
        overlap_report[f"{key[0]}#set{key[1]}"] = len(ov)
    require(all(v == 0 for v in overlap_report.values()), f"D1 coordinate overlap drift: {overlap_report}")
    state_anatomy = []
    row_trans = []
    signed_geo = []
    group_sup = []
    bucket_res = []
    agg_base = agg_valid = agg_search = agg_fixed_v = agg_dmg_v = agg_fixed_s = agg_dmg_s = 0
    for rec in sorted(receipts, key=lambda r: (r["endpoint"], r["set_index"])):
        key = (str(rec["endpoint"]), int(rec["set_index"]))
        st = states[key]
        groups = pals[key]
        base_out = replay(st.rows, st.baseline_weight_bits)
        tgt_out = replay(st.rows, st.target_weight_bits)
        require(tuple(base_out) == tuple(st.baseline_readout_bits) and tuple(tgt_out) == tuple(st.target_readout_bits), f"D1 baseline/target replay drift: {key}")
        base_score = score_of(base_out, tgt_out)
        # physical support per row: rows whose indices appear in support_counts of selected coords? Use full support incidence.
        # Build coordinate->rows with nonzero support.
        coord_rows: dict[int, set[int]] = {}
        for ci in range(len(st.baseline_weight_bits)):
            try:
                sc = st.support_counts[ci]
            except Exception:
                sc = ()
            s = set()
            for row_index, cnt in sc:
                if cnt != 0:
                    s.add(int(row_index))
            if s:
                coord_rows[int(ci)] = s
        for kind in ("best_valid", "best_search"):
            item = rec[kind]
            chosen = item["selected_candidates"]
            require(len(chosen) == len({c["group_index"] for c in chosen}) == len(groups), f"D1 incomplete map: {key} {kind}")
            require({int(c["group_index"]) for c in chosen} == set(groups.keys()), f"D1 group coverage drift: {key} {kind}")
            mapping: dict[int, int] = {}
            active_groups = 0
            for ch in chosen:
                gi = int(ch["group_index"])
                g = groups[gi]
                cands = [c for c in g["palette"] if str(c["candidate_identity"]) == str(ch["candidate_identity"])]
                require(len(cands) == 1, f"D1 candidate identity drift: {key} {kind} {gi}")
                cand = cands[0]
                canon = [(int(p[0]), int(p[1])) for p in cand["canonical_mapping"]]
                require([p[0] for p in canon] == [int(x) for x in g["coordinates_canonical"]], f"D1 canonical coverage drift: {key} {kind} {gi}")
                require(RH1.CQ.state_identity(dict(canon)) == str(cand["candidate_identity"]), f"D1 candidate id recompute drift: {key} {kind} {gi}")
                if cand.get("roles") == ["ZERO"]:
                    require(all(k == 0 for _, k in canon), f"D1 ZERO prefix drift: {key} {kind} {gi}")
                else:
                    active_groups += 1
                for i, k in canon:
                    if i in mapping:
                        require(mapping[i] == k, f"D1 conflict: {key} {kind} {i}")
                    mapping[i] = k
                for i, k, b in (tuple((int(x[0]), int(x[1]), int(x[2]))) for x in cand["committed_f32_mapping"]):
                    exp = RH1.PF5.legal_prefix_bits(int(st.baseline_weight_bits[i]), int(k))
                    require(exp is not None and int(exp) == int(b), f"D1 committed byte drift: {key} {kind} {i}")
                    if int(k) == 0:
                        require(int(b) == int(st.baseline_weight_bits[i]), f"D1 ZERO byte drift: {key} {kind} {i}")
            require(item["canonical_mapping"] == [list(p) for p in sorted(mapping.items())], f"D1 receipt mapping drift: {key} {kind}")
            raw = list(int(v) for v in st.baseline_weight_bits)
            for i, k in mapping.items():
                require(k in LEGAL, f"D1 illegal choice: {key} {kind} {i} {k}")
                require(bool(st.permitted[i]) and int(i) in set(st.interior), f"D1 support drift: {key} {kind} {i}")
                exp = RH1.PF5.legal_prefix_bits(raw[i], int(k))
                require(exp is not None, f"D1 reserve drift: {key} {kind} {i}")
                raw[i] = int(exp)
            require(all(raw[i] == int(b) for i, b in enumerate(st.baseline_weight_bits) if i not in mapping), f"D1 outside-support drift: {key} {kind}")
            wt = tuple(RH1.PF5.from_bits(v) for v in raw)
            actual = replay(st.rows, tuple(raw))
            q = score_of(tuple(actual), tuple(tgt_out))
            require(q == {k: item["score"][k] for k in ("mismatch_count", "total_ulp_distance", "residual_l2", "maximum_absolute_residual")}, f"D1 score drift: {key} {kind}")
            geo = RH1.PF5.geometry_metrics(st.rows, wt, st.base_weights, st.target_weights, st.axis)
            require(geo == item["geometry"], f"D1 geometry drift: {key} {kind}")
            fp = RH1.PF5.final_geometry_pass(geo, pf5_contract)
            require(fp == bool(item["final_geometry_pass"]), f"D1 gate drift: {key} {kind}")
            require(bits_hash(tuple(raw)) == str(item["weight_state_sha256"]).upper(), f"D1 weight hash drift: {key} {kind}")
            require(bits_hash(tuple(actual)) == str(item["readout_sha256"]).upper(), f"D1 readout hash drift: {key} {kind}")
            # signed geometry with correct reference
            B = tuple(st.baseline_weights)
            O = tuple(st.base_weights)
            T = tuple(st.target_weights)
            W = wt
            a = tuple(st.axis)
            qA = math.fsum(ai * (wi - ti) for ai, wi, ti in zip(a, W, T))
            # H rows with multiplicities
            qL_vec = tuple(math.fsum(W[i] - T[i] for i in row) for row in st.rows)
            nW = math.sqrt(math.fsum((wi - oi) ** 2 for wi, oi in zip(W, O)))
            nT = math.sqrt(math.fsum((ti - oi) ** 2 for ti, oi in zip(T, O)))
            qN = nW - nT
            qS = (nW * nW) - (nT * nT)
            # normalizers
            ta = sum(1 for _ in [0])  # placeholder to keep structure
            axis_scale = max(abs(float(geo["target_axis"])), 1.0e-12)
            norm_scale = max(float(geo["target_norm"]), 1.0e-12)
            # raw signed debts
            s_axis = (float(geo["final_axis"]) - float(geo["target_axis"])) / axis_scale
            s_norm = (float(geo["final_norm"]) - float(geo["target_norm"])) / norm_scale
            # cue scale from PF5: norm(true_drive); recompute via target drive
            # use stored normalized error signless + raw L2 via qL vs target? qL is H(W-T); its L2 normalized:
            cue_l2 = math.sqrt(math.fsum(v * v for v in qL_vec))
            # target drive norm for scale: use geo ratios? recover scale = abs_err / norm_err
            # instead compute directly: true target drive norm from state if available else derive
            try:
                tdrive_norm = float(st.target_drive_norm) if hasattr(st, "target_drive_norm") else None
            except Exception:
                tdrive_norm = None
            if tdrive_norm is None:
                # derive from geometry: cue_linear_absolute_error / cue_linear_normalized_error
                ne = float(geo["cue_linear_normalized_error"])
                ae = float(geo["cue_linear_absolute_error"])
                tdrive_norm = (ae / ne) if ne > 0 else 1.0e-12
            # debt tuple as PAR8: (signed axis, signed norm, unsigned linear norm)
            debt = (s_axis, s_norm, float(geo["cue_linear_normalized_error"]))
            bucket = (round(debt[0] * 4096), round(debt[1] * 4096), round(debt[2] * 4096))
            fails = [k for k, t in thr.items() if float(geo[k]) > t]
            # row classes
            n_repaired = n_damaged = 0
            pers_wrong = exact_exact = 0
            ww_imp = ww_tie = ww_worse = 0
            for ri, (b_bit, t_bit, s_bit) in enumerate(zip(base_out, tgt_out, actual)):
                b_mis = b_bit != t_bit
                s_mis = s_bit != t_bit
                if b_mis and not s_mis:
                    n_repaired += 1
                    cls = "wrong-to-exact"
                elif b_mis and s_mis:
                    cls = "wrong-to-wrong"
                    # ULP split
                    bu = abs(order(b_bit) - order(t_bit))
                    su = abs(order(s_bit) - order(t_bit))
                    if su < bu:
                        ww_imp += 1
                    elif su == bu:
                        ww_tie += 1
                    else:
                        ww_worse += 1
                elif (not b_mis) and s_mis:
                    n_damaged += 1
                    cls = "exact-to-wrong"
                else:
                    exact_exact += 1
                    cls = "exact-to-exact"
                if kind == "best_valid":
                    # per-row record only for valid to bound size? spec wants each state; keep compact counts + damaged/repaired row lists
                    pass
            # reconciliation per state
            require(int(item["score"]["mismatch_count"]) == int(base_score["mismatch_count"]) - n_repaired + n_damaged, f"D1 reconciliation drift: {key} {kind}")
            # support degree stats: for damaged/repaired rows, count active groups covering row via selected coords
            sel_coords = set(mapping.keys())
            # group support rows from palettes
            # active group set
            active_gis = set()
            for ch in chosen:
                gi = int(ch["group_index"])
                cand = next(c for c in groups[gi]["palette"] if str(c["candidate_identity"]) == str(ch["candidate_identity"]))
                if cand.get("roles") != ["ZERO"]:
                    active_gis.add(gi)
            # row -> covering active groups count (physical support incidence)
            # Use palette physical_support_rows per group
            row_cover: dict[int, int] = {}
            for gi in active_gis:
                for r in groups[gi].get("physical_support_rows", []):
                    row_cover[int(r)] = row_cover.get(int(r), 0) + 1
            state_anatomy.append({"endpoint": key[0], "set_index": key[1], "kind": kind, "group_count": len(groups), "active_groups": len(active_gis), "changed_coordinates": sum(1 for i in mapping if raw[i] != int(st.baseline_weight_bits[i])), "baseline": base_score, "score": q, "final_geometry_pass": fp, "gate_failures": fails, "weight_state_sha256": bits_hash(tuple(raw)), "readout_sha256": bits_hash(tuple(actual)), "distinct_from_baseline": tuple(raw) != tuple(int(v) for v in st.baseline_weight_bits), "distinct_from_target": tuple(raw) != tuple(int(v) for v in st.target_weight_bits), "repaired": n_repaired, "damaged": n_damaged, "persistent_wrong": int(q["mismatch_count"]) - n_damaged, "exact_exact": exact_exact, "ww_imp": ww_imp, "ww_tie": ww_tie, "ww_worse": ww_worse})
            signed_geo.append({"endpoint": key[0], "set_index": key[1], "kind": kind, "qA": qA, "qN": qN, "qS": qS, "cue_L2": cue_l2, "signed_axis_norm": s_axis, "signed_norm_norm": s_norm, "linear_norm": float(geo["cue_linear_normalized_error"]), "gate_ratios": {k: float(geo[k]) / t for k, t in thr.items()}, "gate_failures": fails, "geometry": geo})
            bucket_res.append({"endpoint": key[0], "set_index": key[1], "kind": kind, "debt": list(debt), "bucket": list(bucket), "final_geometry_pass": fp, "active_groups": len(active_gis)})
            # group support summary per case/kind
            def deg(rowsel):
                ds = [row_cover.get(r, 0) for r in rowsel]
                return {"n": len(ds), "mean": (sum(ds) / len(ds)) if ds else 0.0, "zero_cover": sum(1 for d in ds if d == 0)}
            # recompute row sets for support stats
            rep_rows = [ri for ri, (bb, tt, ss) in enumerate(zip(base_out, tgt_out, actual)) if bb != tt and ss == tt]
            dmg_rows = [ri for ri, (bb, tt, ss) in enumerate(zip(base_out, tgt_out, actual)) if bb == tt and ss != tt]
            pw_rows = [ri for ri, (bb, tt, ss) in enumerate(zip(base_out, tgt_out, actual)) if bb != tt and ss != tt]
            ee_rows = [ri for ri, (bb, tt, ss) in enumerate(zip(base_out, tgt_out, actual)) if bb == tt and ss == tt]
            group_sup.append({"endpoint": key[0], "set_index": key[1], "kind": kind, "repaired_cover": deg(rep_rows), "damaged_cover": deg(dmg_rows), "persistent_wrong_cover": deg(pw_rows), "exact_exact_cover": deg(ee_rows), "palette_sizes": sorted(len(g["palette"]) for g in groups.values()), "support_sizes": sorted(len(g.get("physical_support_rows", [])) for g in groups.values())})
            if kind == "best_valid":
                agg_base += int(base_score["mismatch_count"])
                agg_valid += int(q["mismatch_count"])
                agg_fixed_v += n_repaired
                agg_dmg_v += n_damaged
            else:
                agg_search += int(q["mismatch_count"])
                agg_fixed_s += n_repaired
                agg_dmg_s += n_damaged
    require(agg_base == 3386 and agg_valid == 2454 and agg_fixed_v == 1050 and agg_dmg_v == 118, f"D1 aggregate drift: {agg_base} {agg_valid} {agg_fixed_v} {agg_dmg_v}")
    # after hashes
    after: dict[str, str] = {}
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        h = digest(p)
        require(h == before[str(e["path"])], f"D1 parent changed during run: {e['label']}")
        after[str(e["path"])] = h
    # workload inventory for RQ1/CANCEL1 preflight
    # count legal single replacements across 8 invalid search cases (upper bound only; no replay here)
    invalid_cases = [r for r in receipts if not bool(r["best_search"]["final_geometry_pass"])]
    require(len(invalid_cases) == 8, "D1 invalid cohort drift")
    # exact preflight counts available after palette load; report upper bound
    total_alts_upper = 6406
    out = {"protocol": PROTOCOL, "identity": IDENTITY, "scope": "saved-state anatomy only; no new replay or search", "cohort": {"endpoint_set_count": 14, "states": 28, "invalid_search_states": 8}, "sources": before, "parents_unchanged": True, "coordinate_overlap": overlap_report, "library": {"groups": 801, "entries_seen_in_cohort": n_entries, "zero_seen_in_cohort": n_zero, "pf0_groups": 801, "pf0_palettes": 7207}, "STATE_ANATOMY": state_anatomy, "SIGNED_GEOMETRY": signed_geo, "GROUP_SUPPORT": group_sup, "BUCKET_RESOLUTION": bucket_res, "reconciliation": {"baseline": agg_base, "valid": agg_valid, "search": agg_search, "fixed_valid": agg_fixed_v, "damaged_valid": agg_dmg_v, "fixed_search": agg_fixed_s, "damaged_search": agg_dmg_s, "identity_valid": f"{agg_base}-{agg_fixed_v}+{agg_dmg_v}={agg_valid}", "checks_passed": True}, "workload_prefetch": {"single_alternative_upper_all14": total_alts_upper, "invalid_cohort": len(invalid_cases), "note": "exact 8-case single counts and dedup require RQ1 frozen runtime; no replay executed here"}}
    write_json(EXECUTION, out)
    summ = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "D1_SAVED_STATE_ANATOMY_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": {"cases": 14, "states": 28, "baseline": agg_base, "valid": agg_valid, "fixed_valid": agg_fixed_v, "damaged_valid": agg_dmg_v}, "gate": {"reconstruction_complete": True, "reconciliation_pass": True, "parents_unchanged": True, "new_replay": False, "behavioral_probe": False}, "interpretation": "Saved valid/search states reconstructed; aggregate 3386->2454 with 1050 repaired and 118 damaged. Bucket audit and signed geometry retained per state. No causal attribution; no beam recommendation."}
    write_json(SUMMARY, summ)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join([f"# {PROTOCOL} result", "", f"Cases: **14**; states: **28**.", f"Baseline **{agg_base}** -> valid **{agg_valid}** (repaired **{agg_fixed_v}**, damaged **{agg_dmg_v}**).", f"Search total **{agg_search}**.", "", "Saved-state anatomy only; no new replay, search, behavior, or scientific promotion.", ""]), encoding="utf-8", newline="\n")
    stat = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summ["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    write_json(STATUS, stat)
    print(f"D1 complete: baseline={agg_base} valid={agg_valid} fixed={agg_fixed_v} damaged={agg_dmg_v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
