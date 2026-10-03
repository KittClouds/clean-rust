from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from collections import Counter

REPO = pathlib.Path(r"C:/code land/clean-rust")
SALL1 = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-sall1-r2-v1"
ROOT = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-sall1-a1-v1"
LR1_SCRIPTS = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"
sys.path.insert(0, str(LR1_SCRIPTS))
import run_lr1_case as LR1  # noqa: E402


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def order(bits: int) -> int:
    return (0x80000000 - (bits & 0x7FFFFFFF)) if bits & 0x80000000 else bits + 0x80000000


def write(path: pathlib.Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    execution = json.loads((SALL1 / "execution.json").read_text(encoding="utf-8"))
    if execution.get("status") != "COMPLETE" or int(execution.get("materialized_records", -1)) != 3696:
        raise RuntimeError("SALL1 is not complete")
    bindings = []
    for path, label in [(SALL1 / "CONTRACT.json", "SALL1 contract"), (SALL1 / "PREEXECUTION.json", "SALL1 preexecution"), (SALL1 / "execution.json", "SALL1 execution"), (SALL1 / "source-manifest.json", "SALL1 source manifest"), (SALL1 / "output-shards.json", "SALL1 output shards")]:
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
    rows_out = []
    summaries = []
    for case_dir in sorted((SALL1 / "cases").iterdir()):
        if not case_dir.is_dir():
            continue
        case = case_dir.name
        singleton_dir = case_dir / "singletons"
        complete = json.loads((singleton_dir / "COMPLETE.json").read_text(encoding="utf-8"))
        rows = []
        for chunk in sorted(singleton_dir.glob("chunk-*.jsonl")):
            marker = singleton_dir / f"{chunk.stem}.COMPLETE.json"
            rows.extend(json.loads(line) for line in chunk.read_text(encoding="utf-8").splitlines() if line.strip())
            bindings.append({"label": f"SALL1 {case} {chunk.name}", "path": chunk.relative_to(REPO).as_posix(), "sha256": digest(chunk)})
            bindings.append({"label": f"SALL1 {case} {marker.name}", "path": marker.relative_to(REPO).as_posix(), "sha256": digest(marker)})
        rows.sort(key=lambda row: int(row["domain_index"]))
        if len(rows) != int(complete["count"]):
            raise RuntimeError(f"row count drift {case}")
        state, _, _, _, _ = LR1.load_case(case.split("__set", 1)[0] + ".json", int(case.split("__set", 1)[1]))
        target_bits = tuple(LR1.RH1.PF5.readout_bits(state.rows, state.target_weights))
        invalid_bits = tuple(LR1.RH1.PF5.readout_bits(state.rows, tuple(LR1.RH1.PF5.from_bits(x) for x in state.baseline_weight_bits)))
        mismatch = {i for i, (left, right) in enumerate(zip(invalid_bits, target_bits)) if left != right}
        changed_union = set()
        helpful_union = set()
        exact_union = set()
        physical_union = set()
        invalid_changed_outside_support = set()
        final_pass = 0
        for row in rows:
            changed = set(int(i) for i in row["readout_changed_rows"])
            support = set(int(i) for i in row["physical_support_rows"])
            if not changed <= support:
                invalid_changed_outside_support |= changed - support
            changed_union |= changed
            physical_union |= support
            readout = [int(x) for x in row["readout_bits"]]
            for j in mismatch:
                before = abs(order(int(invalid_bits[j])) - order(int(target_bits[j])))
                after = abs(order(readout[j]) - order(int(target_bits[j])))
                if after < before:
                    helpful_union.add(j)
                if readout[j] == target_bits[j]:
                    exact_union.add(j)
            final_pass += int(bool(row["final_pass"]))
            rows_out.append({"case": case, "domain_index": int(row["domain_index"]), "group": int(row["group"]), "readout_changed_rows": sorted(changed), "physical_support_rows": sorted(support), "score": row["score"], "final_pass": bool(row["final_pass"])})
        summaries.append({
            "case": case,
            "singleton_records": len(rows),
            "baseline_mismatch_count": len(mismatch),
            "physical_support_union_count": len(physical_union),
            "changed_effect_union_count": len(changed_union),
            "useful_authority_union_count": len(helpful_union),
            "exact_repair_union_count": len(exact_union),
            "baseline_mismatch_outside_physical_support": sorted(mismatch - physical_union),
            "baseline_mismatch_outside_changed_effect_union": sorted(mismatch - changed_union),
            "baseline_mismatch_outside_useful_authority_union": sorted(mismatch - helpful_union),
            "baseline_mismatch_outside_exact_repair_union": sorted(mismatch - exact_union),
            "changed_rows_outside_declared_physical_support": sorted(invalid_changed_outside_support),
            "final_geometry_pass_count": final_pass,
        })
    report_text = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows_out)
    (ROOT / "reports" / "singleton-row-effects.jsonl").write_text(report_text, encoding="utf-8", newline="\n")
    bindings.append({"label": "SALL1 row-effect audit", "path": (ROOT / "reports" / "singleton-row-effects.jsonl").relative_to(REPO).as_posix(), "sha256": digest(ROOT / "reports" / "singleton-row-effects.jsonl")})
    write(ROOT / "PLAN.md", {"identity": "q10-gc0-lr1-sall1-a1-v1", "protocol": "SALL1_SINGLETON_EFFECT_COVERAGE_AUDIT", "scope": "derived_read_only_singleton_coverage", "primary": "compare invalid-S mismatch rows with union of rows changed by all 3696 singleton actions", "no_pair_materialization": True, "no_global_assembly": True})
    write(ROOT / "CONTRACT.json", {"identity": "q10-gc0-lr1-sall1-a1-v1", "protocol": "SALL1_SINGLETON_EFFECT_COVERAGE_AUDIT", "parent_bindings": bindings, "expected_records": 3696})
    write(ROOT / "PREEXECUTION.json", {"identity": "q10-gc0-lr1-sall1-a1-v1", "protocol": "SALL1_SINGLETON_EFFECT_COVERAGE_AUDIT", "parent_bindings": bindings, "sealed": True})
    write(ROOT / "execution.json", {"identity": "q10-gc0-lr1-sall1-a1-v1", "protocol": "SALL1_SINGLETON_EFFECT_COVERAGE_AUDIT", "status": "COMPLETE", "parent_sall1_records": 3696, "case_summaries": summaries, "row_effect_report_sha256": digest(ROOT / "reports" / "singleton-row-effects.jsonl"), "checks_passed": all(not s["baseline_mismatch_outside_physical_support"] and not s["changed_rows_outside_declared_physical_support"] for s in summaries), "pair_materialization": False, "global_assembly": False, "scientific_promotion": False})
    print(json.dumps({"identity": "q10-gc0-lr1-sall1-a1-v1", "case_summaries": summaries}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
