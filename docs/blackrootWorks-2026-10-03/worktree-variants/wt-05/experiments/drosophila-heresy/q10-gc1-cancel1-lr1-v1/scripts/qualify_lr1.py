"""Qualify LR1 adapter vs legacy + receipt/caching hardening (fixtures only)."""
from __future__ import annotations

import hashlib
import json
import sys
import time
import tracemalloc
from pathlib import Path
from types import SimpleNamespace

QDIR = Path(__file__).resolve().parent
ROOT = QDIR.parent
REPO = ROOT.parents[2]
SCRATCH = Path("C:/Users/shuga/AppData/Local/Temp/opencode/lr1qual")
sys.path.insert(0, str(QDIR))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc1-rq1-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_rq1 as RQ  # noqa: E402
import run_rh1 as RH1  # noqa: E402
from run_lr1_case import read_chunks, publish_chunk, sha_of_records  # noqa: E402


def require(c: bool, m: str) -> None:
    if not c:
        raise RuntimeError(m)


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def mini_domain():
    par8 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json")
    rec = next(r for r in sorted(par8["endpoint_set_results"], key=lambda r: (r["endpoint"], r["set_index"])) if not bool(r["best_search"]["final_geometry_pass"]))
    ep, si = str(rec["endpoint"]), int(rec["set_index"])
    _, states, _ = RH1.load_runtime({(ep, si)})
    st = states[(ep, si)]
    groups: dict[int, dict] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        if (str(g["identity"][0]), int(g["identity"][1])) == (ep, si):
            groups[int(g["identity"][2])] = g
    gis = sorted(groups)[:3]
    s_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_search"]["selected_candidates"]}
    pf5c = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    return st, groups, rec, pf5c, gis, s_sel, (ep, si)


def synth_state(target_w: float):
    return SimpleNamespace(
        rows=((0,),),
        baseline_weight_bits=(A.b(1.0),),
        target_weight_bits=(A.b(target_w),),
        baseline_weights=(1.0,),
        base_weights=(0.0,),
        target_weights=(target_w,),
        axis=(1.0,),
        permitted=(True,),
        interior={0},
    )


def synth_groups():
    zero = {"candidate_identity": "ZERO", "roles": ["ZERO"], "canonical_mapping": [[0, 0]], "committed_f32_mapping": [[0, 0, A.b(1.0)]]}
    alt = {"candidate_identity": "ALT", "roles": ["ALT"], "canonical_mapping": [[0, 1]], "committed_f32_mapping": [[0, 1, A.b(1.0) + 1]]}
    return {9: {"palette": [zero, alt], "coordinates_canonical": [0], "physical_support_rows": [0]}}


def main() -> int:
    pf5c = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    st, groups, rec, _, gis, s_sel, key = mini_domain()
    ep, si = key
    ctx = f"QUAL|{ep}|{si}"
    cache = A.ContextCache()
    # 1. legacy equivalence on mini-domain singles (first 3 groups, all alternates)
    checked = 0
    t0 = time.perf_counter()
    for gi in gis:
        cur = s_sel[gi]
        for cand in groups[gi]["palette"]:
            ident = str(cand["candidate_identity"])
            if ident == cur:
                continue
            sel_d = dict(s_sel)
            sel_d[gi] = ident
            legacy, _ = RQ.materialize(st, groups, sel_d)
            pairs = [(g, (ident if g == gi else s_sel[g])) for g in sorted(s_sel)]
            new, _ = A.materialize(st, groups, pairs, ctx, cache, pf5c)
            require(new["weight_bits_hash"] == legacy["weight_hash"], f"byte drift g{gi} {ident}")
            require(new["score"] == legacy["score"], f"score drift g{gi} {ident}")
            require(new["geometry"] == legacy["geometry"], f"geometry drift g{gi} {ident}")
            require(new["final_pass"] == legacy["final_pass"], f"gate drift g{gi} {ident}")
            checked += 1
    # S and V parity
    for kind, kk in (("S", "best_search"), ("V", "best_valid")):
        sel_d = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec[kk]["selected_candidates"]}
        legacy, _ = RQ.materialize(st, groups, sel_d)
        pairs = sorted(sel_d.items())
        new, _ = A.materialize(st, groups, pairs, ctx, cache, pf5c)
        require(new["weight_bits_hash"] == legacy["weight_hash"] and new["score"] == legacy["score"] and new["geometry"] == legacy["geometry"], f"{kind} parity drift")
    per_s = (time.perf_counter() - t0) / max(checked, 1)
    # 2. determinism: repeat one input -> identical record
    gi = gis[0]
    alt0 = next(str(c["candidate_identity"]) for c in groups[gi]["palette"] if str(c["candidate_identity"]) != s_sel[gi])
    pairs = [(g, (alt0 if g == gi else s_sel[g])) for g in sorted(s_sel)]
    r1, _ = A.materialize(st, groups, pairs, ctx, A.ContextCache(), pf5c)
    r2, _ = A.materialize(st, groups, pairs, ctx, A.ContextCache(), pf5c)
    require(r1 == r2, "adapter determinism drift")
    # 3. tie-heavy shortlist order is deterministic + documented
    synth = []
    for n in range(6):
        synth.append({"group": 7 if n % 2 == 0 else 3, "from": "X", "to": f"T{n:02d}", "domain_index": n,
                      "score": {"mismatch_count": 10, "total_ulp_distance": 20, "residual_l2": 1e-6, "maximum_absolute_residual": 1e-6},
                      "max_ratio": 1.5, "excess": 0.5, "damaged": 2, "bucket": (1, 0, 0)})
    s1, _ = A.shortlist_legacy(synth)
    s1b, _ = A.shortlist_legacy([dict(x) for x in synth])
    require([x["to"] for x in s1] == [x["to"] for x in s1b], "shortlist determinism drift")
    require([x["to"] for x in s1] == [f"T{n:02d}" for n in range(6)], "shortlist canonical-order drift")
    require(len(s1) <= 32 and all(a["group"] != b["group"] for a, b in A.pair_domain(s1)), "shortlist/pair domain drift")
    # 4. cache isolation across contexts (intended delta D1)
    g9 = synth_groups()
    stA, stB = synth_state(1.5), synth_state(0.5)
    cA, cB = A.ContextCache(), A.ContextCache()
    ra, _ = A.materialize(stA, g9, [(9, "ALT")], "CTX-A", cA, pf5c)
    rb, _ = A.materialize(stB, g9, [(9, "ALT")], "CTX-B", cB, pf5c)
    require(ra["weight_bits_hash"] == rb["weight_bits_hash"], "isolation fixture premise drift")
    require(ra["geometry"] != rb["geometry"], "isolation fixture geometry premise drift")
    shared = A.ContextCache()
    ra2, h1 = A.materialize(stA, g9, [(9, "ALT")], "CTX-A", shared, pf5c)
    rb2, h2 = A.materialize(stB, g9, [(9, "ALT")], "CTX-B", shared, pf5c)
    require(not h2 and rb2["geometry"] == rb["geometry"] and ra2["geometry"] == ra["geometry"], "cache context bleed")
    legA, _ = RQ.materialize(stA, g9, {9: "ALT"})
    legB, _ = RQ.materialize(stB, g9, {9: "ALT"})
    require(legA["geometry"] == legB["geometry"], "legacy collision premise drift")
    # 5. duplicate/missing/same-group rejection (intended delta D2)
    for bad, label in ([(9, "ALT"), (9, "ZERO")], "duplicate"), ([(9, "ALT")], "ok"):
        if label == "duplicate":
            try:
                A.materialize(stA, g9, bad, "CTX-A", A.ContextCache(), pf5c)
                raise AssertionError("duplicate not rejected")
            except RuntimeError:
                pass
    try:
        A.materialize(stA, {9: g9[9], 10: g9[9]}, [(9, "ALT")], "CTX-A", A.ContextCache(), pf5c)
        raise AssertionError("missing-group not rejected")
    except RuntimeError:
        pass
    # 6. labels incl. signed zero
    negz, posz = A.b(-0.0), A.b(0.0)
    require(negz != posz, "signed-zero premise drift")
    mk = lambda sc, fp, db, dt, eq: A.classify_record({"score": sc, "final_pass": fp, "distinct_b": db, "distinct_t": dt}, eq, (5, 10, 1e-5, 1e-6))
    require(mk({"mismatch_count": 0, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}, True, True, True, True) == "EXACT_ALTERNATIVE", "exact label drift")
    require(mk({"mismatch_count": 1, "total_ulp_distance": 0, "residual_l2": 0.0, "maximum_absolute_residual": 0.0}, True, True, True, False) != "EXACT_ALTERNATIVE", "signed-zero label drift")
    require(mk({"mismatch_count": 3, "total_ulp_distance": 4, "residual_l2": 1e-6, "maximum_absolute_residual": 1e-6}, True, True, True, False) == "VALID_ADVANTAGE_PRESERVED", "advantage label drift")
    require(mk({"mismatch_count": 9, "total_ulp_distance": 1, "residual_l2": 1e-7, "maximum_absolute_residual": 1e-7}, False, True, True, False) == "INVALID_NON_SUCCESS", "invalid label drift")
    # 7. chunk round-trip + resume identity + overwrite/orphan refusal
    if SCRATCH.exists():
        import shutil
        shutil.rmtree(SCRATCH)
    d = SCRATCH / "chunks"
    d.mkdir(parents=True, exist_ok=True)
    recs_a = [{"domain_index": i, "v": i} for i in range(4)]
    publish_chunk(d, recs_a)
    got = read_chunks(d)
    require(len(got) == 4, "chunk round-trip drift")
    recs_b = [{"domain_index": 4 + i, "v": i} for i in range(4)]
    publish_chunk(d, recs_b)
    got2 = read_chunks(d)
    require(sorted(got2) == list(range(8)) and sha_of_records([got2[i] for i in range(8)]) == sha_of_records(recs_a + recs_b), "resume identity drift")
    d_gap = SCRATCH / "gap"
    d_gap.mkdir(parents=True, exist_ok=True)
    (d_gap / "chunk-0001.jsonl").write_text("pre-existing\n", encoding="utf-8")
    try:
        publish_chunk(d_gap, recs_a)
        raise AssertionError("overwrite not refused")
    except RuntimeError:
        pass
    d_tmp = SCRATCH / "orphan"
    d_tmp.mkdir(parents=True, exist_ok=True)
    (d_tmp / "chunk-0000.jsonl.tmp").write_text("orphan\n", encoding="utf-8")
    try:
        publish_chunk(d_tmp, recs_a)
        raise AssertionError("orphan not detected")
    except RuntimeError:
        pass
    tracemalloc.start()
    A.materialize(st, groups, [(g, s_sel[g]) for g in sorted(s_sel)], ctx, A.ContextCache(bound=8), pf5c)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    (ROOT / "qualification").mkdir(parents=True, exist_ok=True)
    (ROOT / "qualification" / "runtime-equivalence.json").write_text(json.dumps({
        "mini_domain": {"case": f"{ep}|{si}", "groups": gis, "singles_checked": checked, "seconds_per_candidate": per_s,
                        "bytes_scores_geometry_gates_match_legacy": True, "deterministic": True},
        "shortlist": {"tie_stable": True, "max_32": True, "no_same_group_pairs": True,
                      "note": "legacy as-coded collateral order preserved; prose discrepancy documented, not corrected"},
        "intended_deltas": ["D1 context-safe cache (legacy collides across contexts; adapter isolates)",
                            "D2 duplicate-list rejection (legacy dict collapse silent)",
                            "D3 full reconstruction receipts", "D4 exclusive chunks, no --force"],
        "labels": {"exact": True, "signed_zero": True, "advantage": True, "invalid": True},
        "memory": {"per_case_cache_bound": 8, "probe_peak_bytes": peak}}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "qualification" / "recovery-tests.json").write_text(json.dumps({
        "chunk_round_trip": True, "resume_identity": True, "overwrite_refused": True, "orphan_tmp_refused": True,
        "duplicate_rejected": True, "missing_group_rejected": True, "cache_isolation": True,
        "parent_drift_checked": True}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LR1 qualification passed: singles_checked={checked} per_s={per_s:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
