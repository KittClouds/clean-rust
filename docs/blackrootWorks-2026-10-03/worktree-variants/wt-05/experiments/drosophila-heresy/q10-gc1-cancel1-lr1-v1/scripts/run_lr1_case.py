"""LR1 checkpointed case worker. One invocation: <=128 new records or <=10 min.

Stages: singles -> shortlist -> pairs. Chunks of 32 records. No --force.
Resume verifies existing chunks and fills only missing predetermined work.
Legacy selector arithmetic preserved verbatim (see lr1_adapter).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
import time
from pathlib import Path

WORKER = Path(__file__).resolve()
ROOT = WORKER.parents[1]
REPO = ROOT.parents[2]
sys.path.insert(0, str(WORKER.parent))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_rh1 as RH1  # noqa: E402

CHUNK = 32
HARD_MAX_RECORDS = 128
HARD_MAX_MINUTES = 10


def require(c: bool, m: str) -> None:
    if not c:
        raise RuntimeError(m)


def read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def sha_of_records(recs: list[dict]) -> str:
    return hashlib.sha256("\n".join(json.dumps(r, sort_keys=True) for r in recs).encode()).hexdigest().upper()


def sgn(x: float) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def write_exclusive(p: Path, text: str) -> None:
    if p.exists():
        raise RuntimeError(f"LR1 refuse overwrite: {p}")
    tmp = p.with_suffix(p.suffix + ".tmp")
    if tmp.exists():
        raise RuntimeError(f"LR1 orphan temp present, refusing: {tmp}")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    tmp.replace(p)


def case_dir(ep: str, si: int) -> Path:
    return ROOT / "cases" / f"{ep.replace('.json','')}__set{si}"


def check_parents() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        require(digest(p) == str(e["sha256"]).upper(), f"LR1 parent drift: {e['label']}")


def thr_of(pf5c) -> dict:
    g = pf5c["geometry"]["final_da2_gates"]
    return {"axis_normalized_error": float(g["axis_normalized_abs"]), "norm_normalized_error": float(g["norm_normalized_abs"]), "cue_linear_normalized_error": float(g["cue_linear_normalized_abs"])}


def weight_bits_of(st, groups, sel: list[tuple[int, str]]):
    raw = list(int(v) for v in st.baseline_weight_bits)
    mp: dict[int, int] = {}
    for gi, ident in sel:
        cand = next(c for c in groups[gi]["palette"] if str(c["candidate_identity"]) == str(ident))
        for p in cand["canonical_mapping"]:
            mp[int(p[0])] = int(p[1])
    for i, k in mp.items():
        raw[i] = int(RH1.PF5.legal_prefix_bits(raw[i], int(k)))
    return tuple(raw)


def load_case(ep: str, si: int):
    check_parents()
    pf5c = read_json(REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json")
    par8 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json")
    rec = next(r for r in par8["endpoint_set_results"] if str(r["endpoint"]) == ep and int(r["set_index"]) == si)
    require(not bool(rec["best_search"]["final_geometry_pass"]), "LR1 case is not an invalid-S case")
    _, states, _ = RH1.load_runtime({(ep, si)})
    st = states[(ep, si)]
    groups: dict[int, dict] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        if (str(g["identity"][0]), int(g["identity"][1])) == (ep, si):
            groups[int(g["identity"][2])] = g
    dom = read_json(ROOT / "inventory" / "singles-domain" / f"{ep.replace('.json','')}__set{si}.json")
    return st, groups, rec, dom, pf5c


def read_chunks(d: Path) -> dict[int, dict]:
    done: dict[int, dict] = {}
    for f in sorted(d.glob("chunk-*.jsonl")):
        comp = d / (f.stem + ".COMPLETE.json")
        require(comp.exists(), f"LR1 chunk without completion marker: {f}")
        c = read_json(comp)
        rows = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
        require(sha_of_records(rows) == c["sha256"] and len(rows) == c["count"], f"LR1 chunk checksum drift: {f}")
        for r in rows:
            require(int(r["domain_index"]) not in done, f"LR1 duplicated domain id: {f}")
            done[int(r["domain_index"])] = r
    return done


def publish_chunk(d: Path, buf: list[dict]) -> None:
    n = len(list(d.glob("chunk-*.jsonl")))
    p = d / f"chunk-{n:04d}.jsonl"
    if p.exists():
        raise RuntimeError(f"LR1 refuse overwrite chunk: {p}")
    tmp = p.with_suffix(".jsonl.tmp")
    if tmp.exists():
        raise RuntimeError(f"LR1 orphan temp: {tmp}")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in buf), encoding="utf-8", newline="\n")
    tmp.replace(p)
    write_exclusive(d / f"chunk-{n:04d}.COMPLETE.json", json.dumps({"count": len(buf), "sha256": sha_of_records(buf)}, indent=2, sort_keys=True) + "\n")


def signed_features(st, s_ax: float, qL_S: tuple, T: tuple, r_raw) -> tuple[float, float, list[int], int]:
    Wr = tuple(RH1.PF5.from_bits(x) for x in r_raw)
    qL_r = tuple(math.fsum(Wr[i] - T[i] for i in row) for row in st.rows)
    d_lin = tuple(a - b for a, b in zip(qL_r, qL_S))
    dot = math.fsum(a * b for a, b in zip(d_lin, qL_S))
    return dot, qL_r, d_lin, 0


def stage_singles(ep: str, si: int, max_records: int, max_minutes: float) -> int:
    t0 = time.perf_counter()
    st, groups, rec, dom, pf5c = load_case(ep, si)
    thr = thr_of(pf5c)
    d = case_dir(ep, si) / "singles"
    d.mkdir(parents=True, exist_ok=True)
    if (d / "COMPLETE.json").exists():
        print(f"singles already COMPLETE for {ep} set {si}")
        return 0
    s_sel = [(int(c["group_index"]), str(c["candidate_identity"])) for c in rec["best_search"]["selected_candidates"]]
    v_sel = [(int(c["group_index"]), str(c["candidate_identity"])) for c in rec["best_valid"]["selected_candidates"]]
    ctx = hashlib.sha256(f"{ep}|{si}".encode()).hexdigest().upper()
    cache = A.ContextCache()
    s_res, _ = A.materialize(st, groups, s_sel, ctx, cache, pf5c)
    v_res, _ = A.materialize(st, groups, v_sel, ctx, cache, pf5c)
    v_key = A.qkey(v_res["score"])
    tgt_hash = A.bits_hash(tuple(A.replay(st.rows, st.target_weight_bits)))
    T = tuple(st.target_weights)
    s_geo = s_res["geometry"]
    s_ax = (float(s_geo["final_axis"]) - float(s_geo["target_axis"])) / max(abs(float(s_geo["target_axis"])), 1.0e-12)
    s_raw = weight_bits_of(st, groups, s_sel)
    s_W = tuple(RH1.PF5.from_bits(x) for x in s_raw)
    qL_S = tuple(math.fsum(s_W[i] - T[i] for i in row) for row in st.rows)
    s_n = int(s_res["score"]["mismatch_count"])
    v_n = int(v_res["score"]["mismatch_count"])
    done = read_chunks(d)
    pending = [i for i in range(len(dom)) if i not in done]
    made = 0
    buf: list[dict] = []
    for i in pending:
        if made >= max_records:
            break
        if (time.perf_counter() - t0) / 60 >= max_minutes:
            break
        alt = dom[i]
        sel = [(g, ident) if g != int(alt["group"]) else (g, str(alt["to"])) for g, ident in s_sel]
        res, reused = A.materialize(st, groups, sel, ctx, cache, pf5c)
        r_raw = weight_bits_of(st, groups, sel)
        _, _, _, _ = signed_features(st, s_ax, qL_S, T, r_raw)
        Wr = tuple(RH1.PF5.from_bits(x) for x in r_raw)
        qL_r = tuple(math.fsum(Wr[i] - T[i] for i in row) for row in st.rows)
        d_lin = tuple(a - b2 for a, b2 in zip(qL_r, qL_S))
        dot = math.fsum(a * b2 for a, b2 in zip(d_lin, qL_S))
        opp = -dot
        g = res["geometry"]
        r_ax = (float(g["final_axis"]) - float(g["target_axis"])) / max(abs(float(g["target_axis"])), 1.0e-12)
        d_axis = r_ax - s_ax
        bucket = [int(alt["group"]), sgn(d_axis), sgn(opp)]
        ratios = {k: float(g[k]) / thr[k] for k in thr}
        outcome = A.classify_record(res, res["readout_hash"] == tgt_hash, v_key)
        gap = ((v_n - int(res["score"]["mismatch_count"])) / (v_n - s_n)) if (v_n - s_n) > 0 else None
        rec_out = {"domain_index": i, "group": int(alt["group"]), "from": str(alt["from"]), "to": str(alt["to"]),
                   "score": res["score"], "geometry": g, "ratios": ratios,
                   "max_ratio": max(ratios.values()), "excess": sum(max(0.0, v - 1.0) for v in ratios.values()),
                   "damaged": res["damaged"], "fixed": res["fixed"],
                   "final_pass": res["final_pass"], "outcome": outcome,
                   "weight_hash": res["weight_bits_hash"], "readout_hash": res["readout_hash"],
                   "d_axis": d_axis, "opp": opp, "bucket": bucket, "gap_retention": gap,
                   "reused_cache": reused}
        buf.append(rec_out)
        done[i] = rec_out
        made += 1
        if len(buf) == CHUNK:
            publish_chunk(d, buf)
            buf = []
            print(f"singles {ep} set {si}: {len(done)}/{len(dom)}", flush=True)
    if buf:
        publish_chunk(d, buf)
        print(f"singles {ep} set {si}: {len(done)}/{len(dom)}", flush=True)
    if len(done) == len(dom):
        all_rows = [done[i] for i in range(len(dom))]
        write_exclusive(d / "COMPLETE.json", json.dumps({"count": len(dom), "sha256": sha_of_records(all_rows)}, indent=2, sort_keys=True) + "\n")
        print(f"singles {ep} set {si}: COMPLETE {len(dom)}", flush=True)
    return made


def stage_shortlist(ep: str, si: int) -> int:
    check_parents()
    d = case_dir(ep, si) / "singles"
    require((d / "COMPLETE.json").exists(), "singles not complete")
    done = read_chunks(d)
    dom = read_json(ROOT / "inventory" / "singles-domain" / f"{ep.replace('.json','')}__set{si}.json")
    require(len(done) == len(dom), "singles coverage incomplete")
    singles = [done[i] for i in range(len(dom))]
    short, prov = A.shortlist_legacy(singles)
    pairs = A.pair_domain(short)
    cdir = case_dir(ep, si)
    cdir.mkdir(parents=True, exist_ok=True)
    sp = cdir / "shortlist.json"
    if not sp.exists():
        write_exclusive(sp, json.dumps({"shortlist": [{"group": x["group"], "from": x["from"], "to": x["to"], "domain_index": x["domain_index"]} for x in short], "provenance": prov}, indent=2, sort_keys=True) + "\n")
    pp = cdir / "pairs-domain.json"
    plist = [{"pair_index": n, "a": {"group": a["group"], "to": a["to"], "domain_index": a["domain_index"]}, "b": {"group": b["group"], "to": b["to"], "domain_index": b["domain_index"]}} for n, (a, b) in enumerate(pairs)]
    if not pp.exists():
        write_exclusive(pp, json.dumps(plist, indent=1, sort_keys=True) + "\n")
    print(f"shortlist {ep} set {si}: short={len(short)} pairs={len(plist)}", flush=True)
    return len(plist)


def stage_pairs(ep: str, si: int, max_records: int, max_minutes: float) -> int:
    t0 = time.perf_counter()
    st, groups, rec, _, pf5c = load_case(ep, si)
    cdir = case_dir(ep, si)
    require((cdir / "shortlist.json").exists() and (cdir / "pairs-domain.json").exists(), "shortlist/pairs-domain missing")
    d = cdir / "pairs"
    d.mkdir(parents=True, exist_ok=True)
    if (d / "COMPLETE.json").exists():
        print(f"pairs already COMPLETE for {ep} set {si}")
        return 0
    plist = read_json(cdir / "pairs-domain.json")
    s_sel = [(int(c["group_index"]), str(c["candidate_identity"])) for c in rec["best_search"]["selected_candidates"]]
    v_sel = [(int(c["group_index"]), str(c["candidate_identity"])) for c in rec["best_valid"]["selected_candidates"]]
    ctx = hashlib.sha256(f"{ep}|{si}".encode()).hexdigest().upper()
    cache = A.ContextCache()
    s_res, _ = A.materialize(st, groups, s_sel, ctx, cache, pf5c)
    v_res, _ = A.materialize(st, groups, v_sel, ctx, cache, pf5c)
    v_key = A.qkey(v_res["score"])
    tgt_hash = A.bits_hash(tuple(A.replay(st.rows, st.target_weight_bits)))
    s_n = int(s_res["score"]["mismatch_count"])
    v_n = int(v_res["score"]["mismatch_count"])
    done = read_chunks(d)
    pending = [p for p in plist if int(p["pair_index"]) not in done]
    made = 0
    buf: list[dict] = []
    for p in pending:
        if made >= max_records:
            break
        if (time.perf_counter() - t0) / 60 >= max_minutes:
            break
        a, b2 = p["a"], p["b"]
        require(int(a["group"]) != int(b2["group"]), "same-group pair in domain")
        sel = [(g, ident) if g not in (int(a["group"]), int(b2["group"])) else (g, str(a["to"]) if g == int(a["group"]) else str(b2["to"])) for g, ident in s_sel]
        res, reused = A.materialize(st, groups, sel, ctx, cache, pf5c)
        outcome = A.classify_record(res, res["readout_hash"] == tgt_hash, v_key)
        gap = ((v_n - int(res["score"]["mismatch_count"])) / (v_n - s_n)) if (v_n - s_n) > 0 else None
        rec_out = {"domain_index": int(p["pair_index"]), "a": a, "b": b2,
                   "score": res["score"], "geometry": res["geometry"],
                   "final_pass": res["final_pass"], "outcome": outcome,
                   "weight_hash": res["weight_bits_hash"], "readout_hash": res["readout_hash"],
                   "gap_retention": gap, "reused_cache": reused}
        buf.append(rec_out)
        done[int(p["pair_index"])] = rec_out
        made += 1
        if len(buf) == CHUNK:
            publish_chunk(d, buf)
            buf = []
            print(f"pairs {ep} set {si}: {len(done)}/{len(plist)}", flush=True)
    if buf:
        publish_chunk(d, buf)
        print(f"pairs {ep} set {si}: {len(done)}/{len(plist)}", flush=True)
    if len(done) == len(plist):
        all_rows = [done[int(p["pair_index"])] for p in plist]
        write_exclusive(d / "COMPLETE.json", json.dumps({"count": len(plist), "sha256": sha_of_records(all_rows)}, indent=2, sort_keys=True) + "\n")
        print(f"pairs {ep} set {si}: COMPLETE {len(plist)}", flush=True)
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True, help="endpoint|set_index")
    ap.add_argument("--stage", required=True, choices=["singles", "shortlist", "pairs"])
    ap.add_argument("--max-records", type=int, default=HARD_MAX_RECORDS)
    ap.add_argument("--max-minutes", type=float, default=HARD_MAX_MINUTES)
    a = ap.parse_args()
    require(a.max_records <= HARD_MAX_RECORDS and a.max_minutes <= HARD_MAX_MINUTES, "LR1 bound exceeded")
    ep, si = a.case.split("|")
    if a.stage == "singles":
        n = stage_singles(ep, int(si), a.max_records, a.max_minutes)
    elif a.stage == "shortlist":
        n = stage_shortlist(ep, int(si))
    else:
        n = stage_pairs(ep, int(si), a.max_records, a.max_minutes)
    print(f"LR1 worker done: stage={a.stage} new_records={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
