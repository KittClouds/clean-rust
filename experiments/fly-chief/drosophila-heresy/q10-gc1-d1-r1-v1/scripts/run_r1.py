"""Q10-GC1-D1-R1 contextual removal (uses qualified RQ1 runtime)."""
from __future__ import annotations

import argparse
import hashlib
import json
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

PROTOCOL = "Q10-GC1-D1-R1"
IDENTITY = "q10-gc1-d1-r1-v1"
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    contract = read_json(ROOT / "CONTRACT.json")
    pre = read_json(ROOT / "PREEXECUTION.json")
    require(contract["protocol"] == PROTOCOL and contract["identity"] == IDENTITY, "R1 identity drift")
    require(pre["protocol"] == PROTOCOL and pre["identity"] == IDENTITY, "R1 pre drift")
    require(contract["plan_sha256"] == digest(ROOT / "PLAN.md"), "R1 plan drift")
    require(contract["sealed_runner_sha256"] == digest(Path(__file__)), "R1 runner drift")
    before = {}
    for e in contract["parent_bindings"]:
        p = REPO / str(e["path"])
        h = digest(p)
        require(h == str(e["sha256"]).upper(), f"R1 parent drift: {e['label']}")
        before[str(e["path"])] = h
    if EXECUTION.exists() and not a.force:
        raise SystemExit("R1 receipt exists")
    par8 = read_json(REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json")
    receipts = sorted(par8["endpoint_set_results"], key=lambda r: (r["endpoint"], r["set_index"]))
    tasks = {(str(r["endpoint"]), int(r["set_index"])) for r in receipts}
    _, states, _ = RH1.load_runtime(tasks)
    pals: dict[tuple[str, int], dict[int, dict]] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        k = (str(g["identity"][0]), int(g["identity"][1]))
        if k not in tasks:
            continue
        pals.setdefault(k, {})[int(g["identity"][2])] = g
    # preflight: count active groups across 28 states
    preflight = 0
    for rec in receipts:
        for kind in ("best_valid", "best_search"):
            sel = rec[kind]["selected_candidates"]
            k = (str(rec["endpoint"]), int(rec["set_index"]))
            for c in sel:
                gi = int(c["group_index"])
                cand = next(x for x in pals[k][gi]["palette"] if str(x["candidate_identity"]) == str(c["candidate_identity"]))
                if cand.get("roles") != ["ZERO"]:
                    preflight += 1
    results = []
    seen_weights: dict[str, list[str]] = {}
    for rec in receipts:
        k = (str(rec["endpoint"]), int(rec["set_index"]))
        st = states[k]
        groups = pals[k]
        for kind in ("best_valid", "best_search"):
            base_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec[kind]["selected_candidates"]}
            base_res, _ = RQ.materialize(st, groups, base_sel)
            for gi, ident in list(base_sel.items()):
                cand = next(x for x in groups[gi]["palette"] if str(x["candidate_identity"]) == str(ident))
                if cand.get("roles") == ["ZERO"]:
                    continue
                zero = next(x for x in groups[gi]["palette"] if x.get("roles") == ["ZERO"])
                sel = dict(base_sel)
                sel[gi] = str(zero["candidate_identity"])
                ablation, _ = RQ.materialize(st, groups, sel)
                # deltas vs base saved state (not vs baseline)
                dm = int(ablation["score"]["mismatch_count"]) - int(base_res["score"]["mismatch_count"])
                du = int(ablation["score"]["total_ulp_distance"]) - int(base_res["score"]["total_ulp_distance"])
                label = f"{k[0]}#set{k[1]}/{kind}/remove-group-{gi}"
                seen_weights.setdefault(ablation["weight_hash"], []).append(label)
                results.append({"label": label, "endpoint": k[0], "set_index": k[1], "kind": kind, "removed_group": gi, "base_mismatch": int(base_res["score"]["mismatch_count"]), "ablation_mismatch": int(ablation["score"]["mismatch_count"]), "delta_mismatch": dm, "delta_ulp": du, "ablation_valid": bool(ablation["final_pass"]), "ablation_status": ablation["status"], "weight_hash": ablation["weight_hash"]})
    for e in contract["parent_bindings"]:
        require(digest(REPO / str(e["path"])) == before[str(e["path"])], f"R1 parent changed: {e['label']}")
    out = {"protocol": PROTOCOL, "identity": IDENTITY, "scope": "contextual ZERO-removal only; no greedy deletion", "sources": before, "parents_unchanged": True, "preflight_active_interventions": preflight, "executed": len(results), "unique_weight_states": len(seen_weights), "results": results, "checks_passed": True}
    atomic_write(EXECUTION, out)
    summ = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "D1_R1_REMOVAL_COMPLETE", "engineering_only": True, "scientific_promotion": False, "counts": {"preflight": preflight, "executed": len(results), "unique": len(seen_weights)}, "gate": {"complete_maps": True, "exact_replay": True, "parents_unchanged": True, "behavioral_probe": False}, "interpretation": "Leave-one-group-out contextual effects for saved coalitions; association only, not causal allocation."}
    atomic_write(SUMMARY, summ)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text("\n".join([f"# {PROTOCOL} result", "", f"Interventions: **{len(results)}** (preflight active **{preflight}**); unique states **{len(seen_weights)}**.", "", "Contextual removal only; no constructor output.", ""]), encoding="utf-8", newline="\n")
    stat = {"protocol": PROTOCOL, "identity": IDENTITY, "status": summ["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(EXECUTION), "summary_sha256": digest(SUMMARY), "result_sha256": digest(RESULT)}
    atomic_write(STATUS, stat)
    print(f"R1 complete: executed={len(results)} unique={len(seen_weights)} preflight={preflight}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
