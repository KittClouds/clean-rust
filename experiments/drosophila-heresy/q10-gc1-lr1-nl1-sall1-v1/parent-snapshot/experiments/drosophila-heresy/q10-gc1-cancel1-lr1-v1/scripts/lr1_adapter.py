"""LR1 adapter: RQ1-equivalent oracle with hardened receipt/cache semantics.

Intended deltas vs legacy (documented, qualified, no candidate changes on
valid inputs):
  D1. Cache key includes the case context hash (endpoint/set/target/readout
      hashes); legacy RQ1 keyed result dicts by weight hash alone.
  D2. Selection inputs are validated as ordered pair lists BEFORE dict
      conversion: duplicate groups, missing groups, and same-group pairs are
      rejected with explicit labels instead of silent dict collapse.
  D3. Every evaluated record carries the full reconstruction tuple
      (case, stage, domain index, group ids, previous + replacement candidate
      ids, canonical map hash, weight/readout hashes, full Q, full geometry,
      gate flags, legality, distinctness, damaged/fixed counts, S/V
      comparisons, outcome, cache/attempt provenance).
  D4. No --force path; chunk files are exclusive and content-verified on
      resume; bounded per-case cache scope.

Arithmetic (readout order, negative-zero init, fsum expression order,
gate/threshold constants, sort keys incl. as-coded collateral order) is
copied verbatim from the sealed RQ1/CANCEL1-v1 sources.
"""
from __future__ import annotations

import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any

ADAPTER_DIR = Path(__file__).resolve().parent
LR1_ROOT = ADAPTER_DIR.parents[1]
REPO = LR1_ROOT.parents[2]
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"))
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"))
sys.dont_write_bytecode = True
import run_rh1 as RH1  # noqa: E402

LEGAL = (0, -1, 1, -2, 2, -4, 4, -8, 8, -16, 16)


def require(c: bool, m: str) -> None:
    if not c:
        raise RuntimeError(m)


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


class ContextCache:
    """Bounded per-case cache keyed by (context, weight-hash)."""

    def __init__(self, bound: int = 4096):
        self.bound = bound
        self._d: dict[tuple[str, str], dict] = {}
        self.hits = 0
        self.stores = 0

    def get(self, ctx: str, wh: str):
        v = self._d.get((ctx, wh))
        if v is not None:
            self.hits += 1
        return v

    def put(self, ctx: str, wh: str, v: dict) -> None:
        if (ctx, wh) not in self._d and len(self._d) >= self.bound:
            self._d.pop(next(iter(self._d)))
        self._d[(ctx, wh)] = v
        self.stores += 1


def validate_selection_list(pairs: list[tuple[int, str]], expected_groups: set[int]) -> dict[int, str]:
    seen: set[int] = set()
    for gi, _ in pairs:
        if gi in seen:
            raise RuntimeError(f"LR1 duplicate group record: {gi}")
        seen.add(gi)
    if seen != set(expected_groups):
        raise RuntimeError(f"LR1 group coverage drift: got {len(seen)} want {len(expected_groups)}")
    return {gi: ident for gi, ident in pairs}


def materialize(state, groups: dict[int, dict], pairs: list[tuple[int, str]], ctx: str, cache: ContextCache, pf5_contract: dict):
    """Baseline-relative materialization; returns (record, reused_bool)."""
    sel = validate_selection_list(pairs, set(groups.keys()))
    mapping: dict[int, int] = {}
    for gi, ident in pairs:
        g = groups[gi]
        cands = [c for c in g["palette"] if str(c["candidate_identity"]) == str(ident)]
        if len(cands) != 1:
            raise RuntimeError(f"LR1 candidate identity drift: {gi} {ident}")
        cand = cands[0]
        canon = [(int(p[0]), int(p[1])) for p in cand["canonical_mapping"]]
        if [p[0] for p in canon] != [int(x) for x in g["coordinates_canonical"]]:
            raise RuntimeError(f"LR1 canonical coverage: {gi}")
        for i, k in canon:
            if k not in LEGAL:
                raise RuntimeError(f"LR1 illegal choice: {gi} {i} {k}")
            if i in mapping and mapping[i] != k:
                raise RuntimeError(f"LR1 conflict at coordinate {i}")
            mapping[i] = k
        for i, k, cb in ((int(x[0]), int(x[1]), int(x[2])) for x in cand["committed_f32_mapping"]):
            exp = RH1.PF5.legal_prefix_bits(int(state.baseline_weight_bits[i]), int(k))
            if exp is None or int(exp) != int(cb):
                raise RuntimeError(f"LR1 committed byte drift: {gi} {i}")
            if int(k) == 0 and int(cb) != int(state.baseline_weight_bits[i]):
                raise RuntimeError(f"LR1 ZERO byte drift: {gi} {i}")
    raw = list(int(v) for v in state.baseline_weight_bits)
    for i, k in mapping.items():
        if not (bool(state.permitted[i]) and int(i) in set(state.interior)):
            raise RuntimeError(f"LR1 support: {i}")
        exp = RH1.PF5.legal_prefix_bits(raw[i], int(k))
        if exp is None:
            raise RuntimeError(f"LR1 reserve: {i} {k}")
        raw[i] = int(exp)
    if not all(raw[i] == int(bb) for i, bb in enumerate(state.baseline_weight_bits) if i not in mapping):
        raise RuntimeError("LR1 outside-support change")
    wt = tuple(RH1.PF5.from_bits(v) for v in raw)
    if not all(math.isfinite(v) for v in wt):
        raise RuntimeError("LR1 non-finite weights")
    wh = bits_hash(tuple(raw))
    hit = cache.get(ctx, wh)
    if hit is not None:
        return dict(hit), True
    actual = tuple(int(v) for v in RH1.PF5.readout_bits(state.rows, wt))
    if tuple(replay(state.rows, tuple(raw))) != tuple(actual):
        raise RuntimeError("LR1 oracle parity drift")
    geo = RH1.PF5.geometry_metrics(state.rows, wt, state.base_weights, state.target_weights, state.axis)
    if not all(math.isfinite(float(v)) for v in geo.values()):
        raise RuntimeError("LR1 non-finite geometry")
    base_out = replay(state.rows, state.baseline_weight_bits)
    tgt_out = replay(state.rows, state.target_weight_bits)
    q = score_of(tuple(actual), tuple(tgt_out))
    bscore = score_of(tuple(base_out), tuple(tgt_out))
    fp = RH1.PF5.final_geometry_pass(geo, pf5_contract)
    damaged = sum(1 for bb, tt, ss in zip(base_out, tgt_out, actual) if bb == tt and ss != tt)
    fixed = sum(1 for bb, tt, ss in zip(base_out, tgt_out, actual) if bb != tt and ss == tt)
    res = {"weight_bits_hash": wh, "readout_hash": bits_hash(tuple(actual)),
           "score": q, "baseline_score": bscore, "geometry": geo, "final_pass": bool(fp),
           "damaged": damaged, "fixed": fixed,
           "distinct_b": tuple(raw) != tuple(int(v) for v in state.baseline_weight_bits),
           "distinct_t": tuple(raw) != tuple(int(v) for v in state.target_weight_bits)}
    cache.put(ctx, wh, res)
    return res, False


def classify_record(res: dict, actual_eq_target: bool, v_key: tuple) -> str:
    if actual_eq_target and res["final_pass"] and res["distinct_t"] and res["distinct_b"]:
        return "EXACT_ALTERNATIVE"
    if res["final_pass"] and res["distinct_b"] and res["distinct_t"] and qkey(res["score"]) < v_key:
        return "VALID_ADVANTAGE_PRESERVED"
    if res["final_pass"] and res["distinct_b"] and res["distinct_t"] and qkey(res["score"]) == v_key:
        return "VALID_TIE_NON_SUCCESS"
    if res["final_pass"]:
        return "VALID_WORSE_NON_SUCCESS"
    return "INVALID_NON_SUCCESS"


def shortlist_legacy(singles: list[dict]) -> tuple[list[dict], dict]:
    """Verbatim legacy selector order (as-coded CANCEL1-v1), incl. the
    collateral sort (damaged, mismatch, ULP, excess) that differs from prose.
    Returns (shortlist<=32, provenance)."""
    by_geo = sorted(singles, key=lambda x: (x["max_ratio"], x["excess"], (x["score"]["mismatch_count"], x["score"]["total_ulp_distance"], x["score"]["residual_l2"], x["score"]["maximum_absolute_residual"])))
    short: list[dict] = []
    seen: set[tuple] = set()
    for x in by_geo[:16]:
        k = (x["group"], x["to"])
        if k not in seen:
            seen.add(k)
            short.append(x)
    by_col = sorted([x for x in singles if (x["group"], x["to"]) not in seen], key=lambda x: (x["damaged"], x["score"]["mismatch_count"], x["score"]["total_ulp_distance"], x["excess"]))
    for x in by_col[:8]:
        k = (x["group"], x["to"])
        if k not in seen:
            seen.add(k)
            short.append(x)
    buckets: dict[tuple, list[dict]] = {}
    for x in singles:
        if (x["group"], x["to"]) in seen:
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
                k = (x["group"], x["to"])
                if k not in seen:
                    seen.add(k)
                    short.append(x)
                    progressed = True
                if len(short) >= 32:
                    break
        idx += 1
        if not progressed:
            break
    return short, {"geo_slots": 16, "collateral_slots": 8, "fill": "round-robin (group, axis-sign, opposition-sign), canonical ties"}


def pair_domain(short: list[dict]) -> list[tuple[dict, dict]]:
    out = []
    for i in range(len(short)):
        for j in range(i + 1, len(short)):
            if short[i]["group"] == short[j]["group"]:
                continue
            out.append((short[i], short[j]))
    return out
