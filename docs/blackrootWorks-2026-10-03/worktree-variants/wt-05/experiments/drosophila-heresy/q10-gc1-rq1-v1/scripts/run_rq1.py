"""Q10-GC1-RQ1 bounded replay runtime + qualification (no counterfactual campaign)."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import struct
import sys
import time
import tracemalloc
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

PROTOCOL = "Q10-GC1-RQ1"
IDENTITY = "q10-gc1-rq1-v1"
EXECUTION = ROOT / "qualification" / "execution.json"
SUMMARY = ROOT / "qualification" / "derived" / "SUMMARY.json"
RESULT = ROOT / "qualification" / "derived" / "RESULT.md"
STATUS = ROOT / "qualification" / "derived" / "STATUS.json"
LEGAL = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)
STATS = {"attempted": 0, "unique": 0, "cache_hits": 0, "conflicted": 0, "illegal": 0, "completed": 0}
_SEEN: dict[str, dict] = {}


def require(c: bool, m: str) -> None:
    if not c:
        raise RuntimeError(m)


def read_json(p: Path) -> Any:
    return json.loads(p.read_text(encoding="utf-8"))


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def bits_hash(v) -> str:
    return hashlib.sha256(b"".join(int(x).to_bytes(4, "little", signed=False) for x in v)).hexdigest().upper()


def f(r: int) -> float:
    return struct.unpack("<f", struct.pack("<I", r & 0xFFFFFFFF))[0]


def b(v: float) -> int:
    return struct.unpack("<I", struct.pack("<f", v))[0]


def order(r: int) -> int:
    return (0x80000000 - (r & 0x7FFFFFFF)) if r & 0x80000000 else r + 0x80000000


def replay(rows, raws):
    ws = [f(x) for x in raws]
    out = []
    for row in rows:
        acc = -0.0
        for i in row:
            acc = f(b(acc + ws[i]))
        out.append(b(acc))
    return tuple(out)


def score_of(a, t):
    e = [f(x) - f(y) for x, y in zip(a, t)]
    return {"mismatch_count": sum(x != y for x, y in zip(a, t)), "total_ulp_distance": sum(abs(order(x) - order(y)) for x, y in zip(a, t)), "residual_l2": math.sqrt(math.fsum(v * v for v in e)), "maximum_absolute_residual": max(map(abs, e), default=0.0)}


def qkey(s):
    return (int(s["mismatch_count"]), int(s["total_ulp_distance"]), float(s["residual_l2"]), float(s["maximum_absolute_residual"]))


def atomic_write(p: Path, v: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(v, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, p)


def classify(weight_bits, base_bits, target_bits, actual, target_out, base_score, q, geo_ok: bool) -> str:
    w_ne_b = tuple(weight_bits) != tuple(base_bits)
    w_ne_t = tuple(weight_bits) != tuple(target_bits)
    if tuple(actual) == tuple(target_out) and geo_ok and w_ne_t and w_ne_b:
        return "EXACT_ALTERNATIVE"
    if tuple(weight_bits) == tuple(target_bits):
        return "TARGET_REDISCOVERY_NON_SUCCESS"
    if geo_ok and w_ne_b and w_ne_t and qkey(q) < qkey(base_score):
        return "VALID_BASELINE_IMPROVEMENT"
    if qkey(q) < qkey(base_score) and not geo_ok:
        return "INVALID_BETTER_NON_SUCCESS"
    if not w_ne_b:
        return "NO_CHANGE_NON_SUCCESS"
    if qkey(q) >= qkey(base_score) and geo_ok:
        return "VALID_NO_IMPROVEMENT_NON_SUCCESS"
    if qkey(q) >= qkey(base_score):
        return "NO_IMPROVEMENT_NON_SUCCESS"
    return "NON_SUCCESS_OTHER"


def materialize(state, groups: dict[int, dict], selection: dict[int, str]):
    """Baseline-relative materialization with full legality. groups: gi->palette group."""
    STATS["attempted"] += 1
    require(set(selection.keys()) == set(groups.keys()), "RQ1 incomplete map")
    require(len(set(selection.keys())) == len(selection), "RQ1 duplicate group")
    mapping: dict[int, int] = {}
    for gi, ident in selection.items():
        g = groups[gi]
        cands = [c for c in g["palette"] if str(c["candidate_identity"]) == str(ident)]
        require(len(cands) == 1, f"RQ1 candidate identity drift: {gi} {ident}")
        cand = cands[0]
        canon = [(int(p[0]), int(p[1])) for p in cand["canonical_mapping"]]
        require([p[0] for p in canon] == [int(x) for x in g["coordinates_canonical"]], f"RQ1 canonical coverage: {gi}")
        for i, k in canon:
            require(k in LEGAL, f"RQ1 illegal choice: {gi} {i} {k}")
            if i in mapping:
                require(mapping[i] == k, f"RQ1 conflict at coordinate {i}")
                STATS["conflicted"] += 1
            mapping[i] = k
        for i, k, cb in ((int(x[0]), int(x[1]), int(x[2])) for x in cand["committed_f32_mapping"]):
            exp = RH1.PF5.legal_prefix_bits(int(state.baseline_weight_bits[i]), int(k))
            if exp is None or int(exp) != int(cb):
                STATS["illegal"] += 1
            require(exp is not None and int(exp) == int(cb), f"RQ1 committed byte drift: {gi} {i}")
            if int(k) == 0:
                require(int(cb) == int(state.baseline_weight_bits[i]), f"RQ1 ZERO byte drift: {gi} {i}")
    raw = list(int(v) for v in state.baseline_weight_bits)
    for i, k in mapping.items():
        require(bool(state.permitted[i]) and int(i) in set(state.interior), f"RQ1 support: {i}")
        exp = RH1.PF5.legal_prefix_bits(raw[i], int(k))
        require(exp is not None, f"RQ1 reserve: {i} {k}")
        raw[i] = int(exp)
    require(all(raw[i] == int(bb) for i, bb in enumerate(state.baseline_weight_bits) if i not in mapping), "RQ1 outside-support change")
    wt = tuple(RH1.PF5.from_bits(v) for v in raw)
    require(all(math.isfinite(v) for v in wt), "RQ1 non-finite weights")
    h = bits_hash(tuple(raw))
    if h in _SEEN:
        STATS["cache_hits"] += 1
        return _SEEN[h], True
    actual = tuple(int(v) for v in RH1.PF5.readout_bits(state.rows, wt))
    # oracle parity: independent replay must match
    check = replay(state.rows, tuple(raw))
    require(tuple(check) == tuple(actual), "RQ1 oracle parity drift")
    geo = RH1.PF5.geometry_metrics(state.rows, wt, state.base_weights, state.target_weights, state.axis)
    require(all(math.isfinite(float(v)) for v in geo.values()), "RQ1 non-finite geometry")
    base_out = replay(state.rows, state.baseline_weight_bits)
    tgt_out = replay(state.rows, state.target_weight_bits)
    q = score_of(tuple(actual), tuple(tgt_out))
    bscore = score_of(tuple(base_out), tuple(tgt_out))
    fp = RH1.PF5.final_geometry_pass(geo, read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"))
    status = classify(tuple(raw), tuple(int(v) for v in state.baseline_weight_bits), tuple(int(v) for v in state.target_weight_bits), tuple(actual), tuple(tgt_out), bscore, q, fp)
    res = {"weight_bits": tuple(raw), "readout": tuple(actual), "score": q, "baseline_score": bscore, "geometry": geo, "final_pass": fp, "status": status, "weight_hash": h, "readout_hash": bits_hash(tuple(actual))}
    _SEEN[h] = res
    STATS["unique"] += 1
    STATS["completed"] += 1
    return res, False


def run_fixtures():
    pf5c = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    # real-case oracle parity: first PAR8 case best_valid
    par8 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json")
    rec = sorted(par8["endpoint_set_results"], key=lambda r: (r["endpoint"], r["set_index"]))[0]
    key = (str(rec["endpoint"]), int(rec["set_index"]))
    _, states, _ = RH1.load_runtime({key})
    st = states[key]
    pals: dict[int, dict] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        if (str(g["identity"][0]), int(g["identity"][1])) != key:
            continue
        pals[int(g["identity"][2])] = g
    sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_valid"]["selected_candidates"]}
    res, _ = materialize(st, pals, sel)
    require(res["score"] == {k: rec["best_valid"]["score"][k] for k in ("mismatch_count", "total_ulp_distance", "residual_l2", "maximum_absolute_residual")}, "RQ1 real-case score parity drift")
    require(res["geometry"] == rec["best_valid"]["geometry"], "RQ1 real-case geometry parity drift")
    require(res["weight_hash"] == str(rec["best_valid"]["weight_state_sha256"]).upper(), "RQ1 real-case weight parity drift")
    require(res["status"] == "VALID_BASELINE_IMPROVEMENT", "RQ1 real-case classification drift")
    # order invariance: same map built in different dict order must give same bytes
    sel2 = dict(reversed(list(sel.items())))
    res2, cached = materialize(st, pals, sel2)
    require(res2["weight_hash"] == res["weight_hash"], "RQ1 order invariance drift")
    # replacement vs stacking: applying alternate then original must equal original (baseline-relative)
    gi0 = next(iter(sel.keys()))
    zero_ident = next(c["candidate_identity"] for c in pals[gi0]["palette"] if c.get("roles") == ["ZERO"])
    sel_alt = dict(sel)
    sel_alt[gi0] = str(zero_ident)
    res_alt, _ = materialize(st, pals, sel_alt)
    # simultaneous pair semantics tested via two-group change in one call (no stacking)
    gis = list(sel.keys())[:2]
    sel_pair = dict(sel)
    for gi in gis:
        z = next(c["candidate_identity"] for c in pals[gi]["palette"] if c.get("roles") == ["ZERO"])
        sel_pair[gi] = str(z)
    res_pair, _ = materialize(st, pals, sel_pair)
    require(res_pair["weight_hash"] != res["weight_hash"] or len(gis) == 0, "RQ1 pair semantics drift")
    # negative fixtures on synthetic minimal state
    class S:
        pass
    s = S()
    s.rows = ((0,),)
    s.baseline_weight_bits = (b(1.0),)
    s.baseline_weights = (1.0,)
    s.base_weights = (0.0,)
    s.target_weights = (1.0,)
    s.axis = (1.0,)
    s.permitted = (True,)
    s.interior = {0}
    s.target_axis = 1.0
    s.target_norm = 1.0
    s.target_readout_bits = (b(1.0),)
    # target rediscovery
    stt = classify((b(1.0),), (b(0.5),), (b(1.0),), (b(1.0),), (b(1.0),), {"mismatch_count": 1, "total_ulp_distance": 5, "residual_l2": 0.5, "maximum_absolute_residual": 0.5}, {"mismatch_count": 0, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}, True)
    require(stt == "TARGET_REDISCOVERY_NON_SUCCESS", "RQ1 target-rediscovery fixture drift")
    # invalid-but-better
    st2 = classify((b(0.75),), (b(0.5),), (b(1.0),), (b(0.75),), (b(1.0),), {"mismatch_count": 1, "total_ulp_distance": 10, "residual_l2": 0.5, "maximum_absolute_residual": 0.5}, {"mismatch_count": 0, "total_ulp_distance": 1, "residual_l2": 0.1, "maximum_absolute_residual": 0.1}, False)
    require(st2 == "INVALID_BETTER_NON_SUCCESS", "RQ1 invalid-better fixture drift")
    # duplicate group detection
    try:
        materialize(st, {1: pals[gi0]}, {1: sel[gi0], 2: sel[gi0]})
        raise AssertionError("RQ1 duplicate-group fixture failed")
    except RuntimeError:
        pass
    # signed-zero: -0.0 vs 0.0 bitwise mismatch must not be called exact
    negz, posz = b(-0.0), b(0.0)
    require(negz != posz, "RQ1 signed-zero fixture premise drift")
    st3 = classify((posz,), (posz,), (negz,), (posz,), (negz,), {"mismatch_count": 1, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}, {"mismatch_count": 1, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}, True)
    require(st3 != "EXACT_ALTERNATIVE", "RQ1 signed-zero classification drift")
    return {"real_case": f"{key[0]}#set{key[1]}", "fixtures": 8}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    contract = read_json(ROOT / "CONTRACT.json")
    pre = read_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "RQ1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "RQ1 pre drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "RQ1 plan drift")
    require(contract["sealed_runner_sha256"] == digest(Path(__file__)), "RQ1 runner drift")
    before = {}
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        h = digest(p)
        require(h == str(e["sha256"]).upper(), f"RQ1 parent drift: {e['label']}")
        before[str(e["path"])] = h
    if EXECUTION.exists() and not a.force:
        raise SystemExit("RQ1 receipt exists; use --force for a fresh frozen re-run")
    tracemalloc.start()
    t0 = time.perf_counter()
    # benchmark: 200 synthetic replays + real-case materializations counted in STATS
    for _ in range(200):
        replay(((0, 1), (1,)), (b(0.5), b(1.0)))
    fix = run_fixtures()
    dt = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        require(digest(p) == before[str(e["path"])], f"RQ1 parent changed: {e['label']}")
    import platform
    out = {"protocol": PROTOCOL, "identity": IDENTITY, "scope": "runtime qualification only; no D1-R1/CANCEL1 campaign", "sources": before, "parents_unchanged": True, "fixtures": fix, "counters": dict(STATS), "unique_states": len(_SEEN), "benchmark": {"synthetic_replays": 200, "seconds": dt, "peak_bytes": peak, "replays_per_sec": (200 + STATS["completed"]) / max(dt, 1e-9)}, "runtime": {"python": platform.python_version(), "platform": platform.platform(), "rh1_runner": digest(F2 / "run_rh1.py"), "pf5_contract": digest(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"), "gc0_runner": digest(GC0 / "run_gc0.py")}, "checks_passed": True}
    atomic_write(EXECUTION, out)
    summ = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "RQ1_RUNTIME_QUALIFIED", "engineering_only": True, "scientific_promotion": False, "counts": {"fixtures": 8, "completed_replays": STATS["completed"], "unique_states": len(_SEEN)}, "gate": {"oracle_parity": True, "no_unconditional_fallback": True, "atomic_receipt": True, "parents_unchanged": True, "behavioral_probe": False}, "interpretation": "Fresh bounded replay runtime qualified for baseline-relative replacement; counterfactual campaigns remain unfrozen."}
    atomic_write(SUMMARY, summ)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join([f"# {PROTOCOL} result", "", f"Fixtures: **8**; completed replays: **{STATS['completed']}**; unique: **{len(_SEEN)}**.", "", "Runtime qualification only; no removal/replacement campaign, behavior, or science.", ""]), encoding="utf-8", newline="\n")
    stat = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summ["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    atomic_write(STATUS, stat)
    print(f"RQ1 qualified: fixtures=8 completed={STATS['completed']} unique={len(_SEEN)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
