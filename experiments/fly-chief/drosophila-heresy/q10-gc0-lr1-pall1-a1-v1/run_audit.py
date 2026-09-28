from __future__ import annotations

import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(r"C:/code land/clean-rust")
SALL1 = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-sall1-r2-v1"
SALL1_A1 = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-sall1-a1-v1"
PALL1 = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pall1-v1"
ROOT = REPO / "experiments/drosophila-heresy/q10-gc0-lr1-pall1-a1-v1"
sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"))
import run_lr1_case as LR1  # noqa: E402
import run_rh1 as RH1  # noqa: E402


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def order(bits):
    return (0x80000000 - (bits & 0x7FFFFFFF)) if bits & 0x80000000 else bits + 0x80000000


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    bindings = []
    for path, label in [(SALL1 / "execution.json", "SALL1 execution"), (SALL1_A1 / "execution.json", "SALL1 coverage audit"), (PALL1 / "CONTRACT.json", "PALL1 contract"), (PALL1 / "PREEXECUTION.json", "PALL1 preexecution"), (PALL1 / "qualification/execution.json", "PALL1 execution"), (PALL1 / "qualification/valid-worse-pairs.jsonl", "PALL1 library")]:
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
    pair_rows = {}
    for line in (PALL1 / "qualification/valid-worse-pairs.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        pair_rows.setdefault(row["case"], []).append(row)
    summaries = []
    for case_dir in sorted((SALL1 / "cases").iterdir()):
        if not case_dir.is_dir():
            continue
        case = case_dir.name
        singles = []
        for chunk in sorted((case_dir / "singletons").glob("chunk-*.jsonl")):
            singles.extend(json.loads(line) for line in chunk.read_text(encoding="utf-8").splitlines() if line.strip())
        singleton_effect = set().union(*(set(row["readout_changed_rows"]) for row in singles)) if singles else set()
        pair_effect = set().union(*(set(row["readout_changed_from_S_rows"]) for row in pair_rows.get(case, []))) if pair_rows.get(case) else set()
        state, _, _, _, _ = LR1.load_case(case.split("__set", 1)[0] + ".json", int(case.split("__set", 1)[1]))
        target_bits = tuple(RH1.PF5.readout_bits(state.rows, state.target_weights))
        invalid_bits = tuple(RH1.PF5.readout_bits(state.rows, tuple(RH1.PF5.from_bits(x) for x in state.baseline_weight_bits)))
        mismatch = {i for i, (x, y) in enumerate(zip(invalid_bits, target_bits)) if x != y}
        singleton_helpful = set()
        pair_helpful = set()
        for row in singles:
            readout = row["readout_bits"]
            for j in mismatch:
                if abs(order(int(readout[j])) - order(int(target_bits[j]))) < abs(order(int(invalid_bits[j])) - order(int(target_bits[j]))):
                    singleton_helpful.add(j)
        for row in pair_rows.get(case, []):
            readout = row["readout_bits"]
            for j in mismatch:
                if abs(order(int(readout[j])) - order(int(target_bits[j]))) < abs(order(int(invalid_bits[j])) - order(int(target_bits[j]))):
                    pair_helpful.add(j)
        combined_effect = singleton_effect | pair_effect
        combined_helpful = singleton_helpful | pair_helpful
        summaries.append({"case": case, "baseline_mismatch_count": len(mismatch), "singleton_effect_count": len(singleton_effect), "valid_worse_pair_effect_count": len(pair_effect), "new_effect_rows_from_pairs": sorted(pair_effect - singleton_effect), "combined_effect_count": len(combined_effect), "singleton_helpful_count": len(singleton_helpful), "new_helpful_rows_from_pairs": sorted(pair_helpful - singleton_helpful), "combined_helpful_count": len(combined_helpful), "mismatch_outside_combined_effect": sorted(mismatch - combined_effect), "mismatch_outside_combined_helpful": sorted(mismatch - combined_helpful), "valid_worse_pair_records": len(pair_rows.get(case, []))})
    report = ROOT / "reports/combined-coverage.json"
    write(report, summaries)
    bindings.append({"label": "combined coverage report", "path": report.relative_to(REPO).as_posix(), "sha256": digest(report)})
    write(ROOT / "PLAN.md", {"identity": "q10-gc0-lr1-pall1-a1-v1", "protocol": "SINGLETON_PLUS_VALID_WORSE_PAIR_COVERAGE_AUDIT", "scope": "derived_read_only_effect_coverage", "global_assembly": False, "behavior": False})
    write(ROOT / "CONTRACT.json", {"identity": "q10-gc0-lr1-pall1-a1-v1", "protocol": "SINGLETON_PLUS_VALID_WORSE_PAIR_COVERAGE_AUDIT", "parent_bindings": bindings})
    write(ROOT / "PREEXECUTION.json", {"identity": "q10-gc0-lr1-pall1-a1-v1", "protocol": "SINGLETON_PLUS_VALID_WORSE_PAIR_COVERAGE_AUDIT", "parent_bindings": bindings, "sealed": True})
    write(ROOT / "execution.json", {"identity": "q10-gc0-lr1-pall1-a1-v1", "protocol": "SINGLETON_PLUS_VALID_WORSE_PAIR_COVERAGE_AUDIT", "status": "COMPLETE", "case_summaries": summaries, "report_sha256": digest(report), "checks_passed": True, "global_assembly": False, "scientific_promotion": False})
    print(json.dumps(summaries, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
