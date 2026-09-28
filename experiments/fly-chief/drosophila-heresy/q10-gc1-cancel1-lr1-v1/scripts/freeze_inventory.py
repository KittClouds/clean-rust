"""Freeze LR1 inventory/domains (no replay, no outcomes)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
sys.dont_write_bytecode = True


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest().upper()


def main() -> int:
    par8 = json.loads((REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json").read_text(encoding="utf-8"))
    receipts = sorted(par8["endpoint_set_results"], key=lambda r: (r["endpoint"], r["set_index"]))
    invalid = [r for r in receipts if not bool(r["best_search"]["final_geometry_pass"])]
    assert len(invalid) == 8, f"invalid cohort drift: {len(invalid)}"
    tasks = [(str(r["endpoint"]), int(r["set_index"])) for r in invalid]
    taskset = set(tasks)
    pals: dict[tuple[str, int], dict[int, dict]] = {}
    for line in (REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl").open(encoding="utf-8"):
        g = json.loads(line)
        k = (str(g["identity"][0]), int(g["identity"][1]))
        if k not in taskset:
            continue
        pals.setdefault(k, {})[int(g["identity"][2])] = g
    cases = []
    singles_total = 0
    for rec in invalid:
        k = (str(rec["endpoint"]), int(rec["set_index"]))
        groups = pals[k]
        s_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_search"]["selected_candidates"]}
        v_sel = {int(c["group_index"]): str(c["candidate_identity"]) for c in rec["best_valid"]["selected_candidates"]}
        assert set(s_sel) == set(groups) and set(v_sel) == set(groups), f"group coverage drift: {k}"
        alts = []
        for gi in sorted(s_sel):
            cur = s_sel[gi]
            idents = sorted(str(c["candidate_identity"]) for c in groups[gi]["palette"])
            assert len(idents) == len(set(idents)), f"dup identity: {k} {gi}"
            assert cur in idents, f"S identity missing: {k} {gi}"
            zeros = [c for c in groups[gi]["palette"] if c.get("roles") == ["ZERO"]]
            assert len(zeros) == 1, f"ZERO cardinality: {k} {gi}"
            for ident in idents:
                if ident != cur:
                    alts.append({"group": gi, "from": cur, "to": ident})
        alts.sort(key=lambda x: (x["group"], x["to"]))
        singles_total += len(alts)
        cases.append({
            "endpoint": k[0], "set_index": k[1],
            "group_count": len(groups),
            "single_count": len(alts),
            "pair_upper_bound": 496,
            "s_weight_hash": rec["best_search"]["weight_state_sha256"],
            "s_readout_hash": rec["best_search"]["readout_sha256"],
            "s_score": rec["best_search"]["score"],
            "v_weight_hash": rec["best_valid"]["weight_state_sha256"],
            "v_readout_hash": rec["best_valid"]["readout_sha256"],
            "v_score": rec["best_valid"]["score"],
        })
        out_dir = ROOT / "inventory" / "singles-domain"
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{k[0].replace('.json','')}__set{k[1]}.json").write_text(json.dumps(alts, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    assert singles_total == 3696, f"singles domain drift: {singles_total}"
    (ROOT / "inventory" / "cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    srcs = [
        "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json",
        "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl",
        "experiments/drosophila-heresy/q10-gc1-pf0-v1/qualification/execution.json",
        "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json",
        "experiments/drosophila-heresy/q10-gc1-cancel1-v1/PLAN.md",
        "experiments/drosophila-heresy/q10-gc1-cancel1-v1/CONTRACT.json",
        "experiments/drosophila-heresy/q10-gc1-cancel1-v1/scripts/run_cancel1.py",
        "experiments/drosophila-heresy/q10-gc1-rq1-v1/scripts/run_rq1.py",
        "experiments/drosophila-heresy/q10-gc1-rq1-v1/qualification/execution.json",
    ]
    (ROOT / "inventory" / "source-hashes.json").write_text(json.dumps({s: digest(REPO / s) for s in srcs}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"LR1 inventory frozen: cases=8 singles={singles_total} pairs<=3968")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
