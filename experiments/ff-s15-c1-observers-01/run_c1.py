"""C1 driver.

  python run_c1.py prepare     verify Rung 0 artifacts, rebuild DEV probabilities, mint C0 records (no HOLD numbers)
  python run_c1.py calibrate   fit thresholds on CAL rows only, write policies, freeze everything
  python run_c1.py score       score HOLD through the C0 runtime, apply the preregistered criteria (once)

`calibrate` indexes CAL rows only. `score` refuses to run unless the freeze record still matches the preregistration,
the C0 runtime and the fitted thresholds, and refuses a second scoring unless `--again` is given (which the report records).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from c1 import data, fit, observers, policy, records, rung0, score
from c1.common import (ALPHAS, EVIDENCE, HEADS, PREREGISTRATION, PRIMARY, PRIMARY_ALPHA, SURFACES, alpha_tag, c0_source_sha256, canon, model, sha256_file)

WORLD = EVIDENCE / "world"
FREEZE = EVIDENCE / "freeze.json"
REPORT = EVIDENCE / "c1-report.json"
SEED = 20260929


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="ascii", newline="\n")


def cmd_prepare(_args) -> int:
    EVIDENCE.mkdir(exist_ok=True)
    log("verifying Rung 0 artifacts against the lock")
    identity = rung0.verify(log)
    log("loading DEV rows")
    dev = data.load_dev()
    hold = data.hold_mask(dev["ids"], dev["world_hash"], dev["graph_hash"])
    log(f"split: {int(hold.sum())} HOLD rows, {int((~hold).sum())} CAL rows (only the split sizes are looked at)")
    arrays, gates = {}, {}
    for surface in SURFACES:
        log("rebuilding probabilities for", surface)
        probabilities = observers.compute(surface)
        gates[surface] = observers.reconstruction_gate(surface, probabilities)
        for head in HEADS:
            arrays[f"{surface}.{head}"] = observers.quantize(probabilities[head])
        log("  reconstruction gate passed:", {h: g["label_matches"] for h, g in gates[surface].items()})
    np.savez_compressed(EVIDENCE / "dev-ppm.npz", **arrays)
    np.savez_compressed(EVIDENCE / "dev-truth.npz", ids=np.array(dev["ids"]), world_hash=np.array(dev["world_hash"]), family=np.array(dev["family"]),
                        truth_decision=dev["truth_decision"], truth_action=dev["truth_action"], hold=hold)
    contract_records = observers.contracts()
    bundle_records = observers.bundles(identity, contract_records)
    records.write_records(WORLD / "contracts", contract_records)
    records.write_records(WORLD / "bundles", bundle_records)
    for path, kind in ((WORLD / "contracts", "S15_DECISION_CONTRACT_V1"), (WORLD / "bundles", "S15_OBSERVER_BUNDLE_V1")):
        model.load_dir(path, kind)
    write_json(EVIDENCE / "prepare.json", {"identity": identity, "reconstruction_gates": gates, "hold_rows": int(hold.sum()), "cal_rows": int((~hold).sum()),
                                           "ppm_sha256": sha256_file(EVIDENCE / "dev-ppm.npz"), "truth_sha256": sha256_file(EVIDENCE / "dev-truth.npz"),
                                           "bundle_ids": {k: v["bundle_id"] for k, v in bundle_records.items()}, "contract_ids": {k: v["contract_id"] for k, v in contract_records.items()}})
    log("prepared")
    return 0


def _load_arrays():
    return np.load(EVIDENCE / "dev-ppm.npz", allow_pickle=False), np.load(EVIDENCE / "dev-truth.npz", allow_pickle=False)


def cmd_calibrate(_args) -> int:
    if FREEZE.exists():
        print("already frozen; thresholds are not refit after freezing", file=sys.stderr)
        return 2
    ppm, truth = _load_arrays()
    cal = ~truth["hold"]  # the only row selection used in this function
    truth_dec, truth_act = truth["truth_decision"][cal], truth["truth_action"][cal]
    bundle_records = {p.stem: canon.loads_strict(p.read_bytes()) for p in sorted((WORLD / "bundles").glob("*.json"))}
    bundle_records = {k.replace("bank_", "", 1): v for k, v in bundle_records.items()}
    thresholds, cal_outcomes, policy_hashes = {}, {}, {}
    for surface in SURFACES:
        dec, act = ppm[f"{surface}.decision"][cal], ppm[f"{surface}.action_type"][cal]
        v = fit.views(dec, act)
        thresholds[surface], cal_outcomes[surface] = {}, {}
        for alpha in ALPHAS:
            tag = alpha_tag(alpha)
            fitted = fit.fit_thresholds(dec, act, truth_dec, truth_act, alpha)
            chosen = {name: detail["threshold_ppm"] for name, detail in fitted.items()}
            thresholds[surface][tag] = {"alpha": alpha, "thresholds_ppm": chosen, "fit": fitted}
            disposition, target = fit.simulate(v, chosen)
            cal_outcomes[surface][tag] = fit.outcomes(disposition, target, truth_dec, truth_act)
            record = policy.build(surface, tag, chosen, bundle_records)
            path = WORLD / "policies" / f"{surface}-{tag}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canon.canonical_bytes(record))
            model.load_world(path, WORLD / "contracts", WORLD / "bundles")  # the policy must load and verify
            policy_hashes[f"{surface}-{tag}"] = sha256_file(path)
            print(f"{surface:18s} {tag}  T_abstain={chosen['abstain']}  T_ask={chosen['ask']}  T_act={chosen['act']}  "
                  f"CAL coverage={cal_outcomes[surface][tag]['coverage']:.3f} harm={cal_outcomes[surface][tag]['harm_rate']}")
    write_json(EVIDENCE / "thresholds.json", {"thresholds": thresholds, "cal_outcomes": cal_outcomes})
    write_json(FREEZE, {
        "preregistration_sha256": sha256_file(PREREGISTRATION), "c0_source_sha256": c0_source_sha256(), "thresholds_sha256": sha256_file(EVIDENCE / "thresholds.json"),
        "ppm_sha256": sha256_file(EVIDENCE / "dev-ppm.npz"), "truth_sha256": sha256_file(EVIDENCE / "dev-truth.npz"), "policy_sha256": policy_hashes,
    })
    log("frozen; HOLD has not been scored")
    return 0


def _check_freeze() -> dict:
    if not FREEZE.exists():
        raise SystemExit("no freeze record: run calibrate first")
    freeze = json.loads(FREEZE.read_text(encoding="ascii"))
    current = {"preregistration_sha256": sha256_file(PREREGISTRATION), "c0_source_sha256": c0_source_sha256(), "thresholds_sha256": sha256_file(EVIDENCE / "thresholds.json"),
               "ppm_sha256": sha256_file(EVIDENCE / "dev-ppm.npz"), "truth_sha256": sha256_file(EVIDENCE / "dev-truth.npz")}
    for key, value in current.items():
        if freeze[key] != value:
            raise SystemExit(f"refusing to score: {key} changed since the freeze")
    for name, digest in freeze["policy_sha256"].items():
        if sha256_file(WORLD / "policies" / f"{name}.json") != digest:
            raise SystemExit(f"refusing to score: policy {name} changed since the freeze")
    return freeze


def cmd_score(args) -> int:
    freeze = _check_freeze()
    if REPORT.exists() and not args.again:
        raise SystemExit("HOLD was already scored; --again re-scores and records that fact")
    ppm, truth = _load_arrays()
    hold = np.flatnonzero(truth["hold"])
    truth_dec, truth_act, family = truth["truth_decision"][hold], truth["truth_action"][hold], truth["family"][hold]
    fitted = json.loads((EVIDENCE / "thresholds.json").read_text(encoding="ascii"))
    jobs = [{"surface": s, "tag": alpha_tag(a), "policy": str(WORLD / "policies" / f"{s}-{alpha_tag(a)}.json")} for s in SURFACES for a in ALPHAS]
    log(f"scoring {len(hold)} HOLD rows x {len(jobs)} policies through the C0 runtime")
    workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        ran = {(r["surface"], r["tag"]): r for r in pool.map(score.run_config, jobs)}
    log("runtime done")
    report_surfaces, per_surface_criteria = {}, {}
    for si, surface in enumerate(SURFACES):
        v = fit.views(ppm[f"{surface}.decision"][hold], ppm[f"{surface}.action_type"][hold])
        base = fit.outcomes(*fit.argmax_baseline(v), truth_dec, truth_act)
        entry = {"baseline_argmax": base, "alphas": {}}
        for ai, alpha in enumerate(ALPHAS):
            tag = alpha_tag(alpha)
            chosen = fitted["thresholds"][surface][tag]["thresholds_ppm"]
            ran_one = ran[(surface, tag)]
            sim_disposition, sim_target = fit.simulate(v, chosen)
            if not (np.array_equal(ran_one["disposition"], sim_disposition) and np.array_equal(ran_one["target"], sim_target)):
                raise SystemExit(f"C0 runtime and the numpy rules disagree for {surface} {tag}")
            hold_outcomes = fit.outcomes(ran_one["disposition"], ran_one["target"], truth_dec, truth_act)
            rng = np.random.default_rng([SEED, si, ai])
            permuted = fit.permuted_harm_rates(v, chosen["act"], truth_dec, truth_act, rng)
            entry["alphas"][tag] = {
                "alpha": alpha, "thresholds_ppm": chosen, "cal": fitted["cal_outcomes"][surface][tag], "hold": hold_outcomes, "runtime_repeat_identical": ran_one["repeat_identical"],
                "permutation_harm_rates": [round(float(x), 6) for x in permuted], "permutation_p05": float(np.percentile(permuted, 5)) if len(permuted) else None,
                "permutation_median": float(np.median(permuted)) if len(permuted) else None,
            }
            if abs(alpha - PRIMARY_ALPHA) < 1e-9:
                point = {"hold": hold_outcomes, "cal": fitted["cal_outcomes"][surface][tag], "baseline": base, "permutation_harm_rates": entry["alphas"][tag]["permutation_harm_rates"]}
                per_surface_criteria[surface] = score.criteria(PRIMARY_ALPHA, point)
                entry["criteria_at_primary_alpha"] = per_surface_criteria[surface]
                disposition, target = ran_one["disposition"], ran_one["target"]
                entry["primary_breakdown"] = {
                    "truth_decision_by_disposition": {d: {c: int(((truth_dec == di) & (disposition == ci)).sum()) for c, ci in (("executed", fit.EXECUTED), ("abstained", fit.ABSTAINED), ("asked", fit.ASKED), ("escalated", fit.ESCALATED))} for d, di in (("ACT", fit.ACT), ("ASK", fit.ASK), ("ABSTAIN", fit.ABSTAIN))},
                    "by_family": {str(f): fit.outcomes(disposition[family == f], target[family == f], truth_dec[family == f], truth_act[family == f]) for f in sorted(set(family.tolist()))},
                }
        report_surfaces[surface] = entry
    final = score.verdict(per_surface_criteria[PRIMARY], per_surface_criteria)
    report = {
        "schema": "c1-report/v1", "rescored": bool(args.again), "verdict": final, "primary_surface": PRIMARY, "primary_alpha": PRIMARY_ALPHA, "criteria": per_surface_criteria,
        "hold_rows": int(len(hold)), "freeze": freeze, "surfaces": report_surfaces,
        "runtime_integrity": {"all_runs_identical_on_repeat": all(r["repeat_identical"] for r in ran.values()), "numpy_matches_c0_on_every_row": True, "policies": len(jobs)},
    }
    write_json(REPORT, report)
    log("verdict:", final)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").set_defaults(fn=cmd_prepare)
    sub.add_parser("calibrate").set_defaults(fn=cmd_calibrate)
    scorer = sub.add_parser("score")
    scorer.add_argument("--again", action="store_true")
    scorer.set_defaults(fn=cmd_score)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
