#!/usr/bin/env python3
"""Open sealed RUN1 outcomes only after the independent integrity receipt passes."""
from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_RUN = ROOT / "experiments" / "fly-drop-00" / "artifacts" / "run-FLY-DROP-00-RUN1"
MASK = (1 << 64) - 1

def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb", buffering=0) as f:
        while chunk := f.read(8 * 1024 * 1024): h.update(chunk)
    return h.hexdigest()

class SplitMix64:
    def __init__(self, seed): self.state = seed & MASK
    def next(self):
        self.state = (self.state + 0x9E3779B97F4A7C15) & MASK
        x = self.state
        x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
        x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
        return (x ^ (x >> 31)) & MASK
    def below(self, n):
        threshold = (1 << 64) % n
        while True:
            x = self.next()
            if x >= threshold: return x % n

def linear_percentile(values, p):
    xs = sorted(values)
    position = (len(xs) - 1) * p
    lo = math.floor(position); hi = math.ceil(position)
    if lo == hi: return xs[lo]
    return xs[lo] + (position - lo) * (xs[hi] - xs[lo])

def read_receipts(run):
    latest = {}
    for path in (run / "collection" / "fit-receipts").glob("*.json"):
        rec = json.loads(path.read_text(encoding="utf-8"))
        old = latest.get(rec["fit_id"])
        if old is None or rec["attempt"] > old[1]["attempt"]: latest[rec["fit_id"]] = (path, rec)
    return {k: v[1] for k, v in latest.items()}

def finite_loss(rec):
    x = rec.get("heldout_bce")
    return x if rec.get("status") == "complete" and isinstance(x, (int, float)) and math.isfinite(x) else None

def save_json(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with path.open("xb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())

def mean(xs): return sum(xs) / len(xs) if xs else None

def build_primary(manifest, receipts, contract):
    male = {}
    degree = {}
    for fit in manifest["fits"]:
        if fit["arm"] not in ("malecns", "degree"): continue
        rec = receipts[fit["fit_id"]]
        loss = finite_loss(rec)
        key = (int(fit["adapter_seed"]), int(fit["teacher_seed"]), int(fit["learner_seed"]))
        if fit["arm"] == "malecns": male[key] = loss
        elif fit["arm"] == "degree":
            graph = int(fit["graph_realization"])
            degree[(graph,) + key] = loss
    adapters = sorted({k[0] for k in male})
    teachers = sorted({k[1] for k in male})
    learners = sorted({k[2] for k in male})
    graphs = sorted({k[0] for k in degree})
    missing = []
    for a in adapters:
        for t in teachers:
            for l in learners:
                if male.get((a,t,l)) is None: missing.append(("malecns", a, t, l))
                for g in graphs:
                    if degree.get((g,a,t,l)) is None: missing.append(("degree", g,a,t,l))
    if missing:
        return {"status": "NOT_ESTIMABLE_NUMERICAL_FAILURE", "missing_primary_cells": len(missing),
                "missing_cell_examples": [list(x) for x in missing[:20]], "point_estimate_delta": None,
                "heldout_bce_definition": "MaleCNS minus mean over degree-shuffle realizations",
                "interpretation": "No cells were dropped or imputed; the primary contrast is unavailable because a required fit has a scientific numerical failure."}, None
    cell_delta = {}
    for a in adapters:
        for t in teachers:
            for l in learners:
                cell_delta[(a,t,l)] = male[(a,t,l)] - mean([degree[(g,a,t,l)] for g in graphs])
    point = mean(list(cell_delta.values()))
    rng = SplitMix64(contract["primary_analysis"]["bootstrap_seed"])
    reps = []
    for _ in range(contract["primary_analysis"]["bootstrap_replicates"]):
        a_draw = [adapters[rng.below(len(adapters))] for _ in adapters]
        g_draw = [graphs[rng.below(len(graphs))] for _ in graphs]
        t_draw = [teachers[rng.below(len(teachers))] for _ in teachers]
        l_draw = [learners[rng.below(len(learners))] for _ in learners]
        differences = []
        for a in a_draw:
            for t in t_draw:
                for l in l_draw:
                    degree_loss = mean([degree[(g,a,t,l)] for g in g_draw])
                    differences.append(male[(a,t,l)] - degree_loss)
        reps.append(mean(differences))
    lo = linear_percentile(reps, 0.025); hi = linear_percentile(reps, 0.975)
    overall_sign = 1 if point > 0 else (-1 if point < 0 else 0)
    levels = {}
    for axis, vals, idx in (("adapter_seed", adapters, 0), ("teacher_seed", teachers, 1), ("learner_seed", learners, 2)):
        per_level = []
        for value in vals:
            level_mean = mean([d for key, d in cell_delta.items() if key[idx] == value])
            sign = 1 if level_mean > 0 else (-1 if level_mean < 0 else 0)
            per_level.append({"level": value, "mean_delta": level_mean, "sign": sign,
                "agrees_with_overall_direction": None if overall_sign == 0 else sign == overall_sign})
        comparable = [x for x in per_level if x["agrees_with_overall_direction"] is not None]
        levels[axis] = {"levels": per_level, "direction_agreement_count": sum(x["agrees_with_overall_direction"] for x in comparable),
                        "level_count": len(comparable)}
    crossed = [{"adapter_seed": a, "teacher_seed": t, "learner_seed": l, "paired_delta": cell_delta[(a,t,l)]}
        for a in adapters for t in teachers for l in learners]
    graph_summaries = []
    for g in graphs:
        graph_diffs = [male[(a,t,l)] - degree[(g,a,t,l)] for a in adapters for t in teachers for l in learners]
        graph_summaries.append({"graph_realization": g, "mean_male_minus_this_shuffle": mean(graph_diffs)})
    primary = {"status": "ESTIMABLE", "estimand": "mean over adapter, teacher, learner of MaleCNS held-out BCE minus mean degree-shuffle held-out BCE over four graph realizations",
        "point_estimate_delta": point, "direction": "higher_loss_for_malecns" if point > 0 else ("lower_loss_for_malecns" if point < 0 else "zero"),
        "heldout_bce": {"male_mean": mean(list(male.values())), "degree_shuffle_mean": mean(list(degree.values()))},
        "bootstrap_95_percentile_ci": [lo, hi], "bootstrap_replicates": len(reps), "bootstrap_seed": contract["primary_analysis"]["bootstrap_seed"],
        "cross_factor_consistency": levels, "degree_realization_summaries": graph_summaries,
        "cell_count": len(cell_delta), "graph_realization_count": len(graphs), "missing_or_imputed_cells": 0,
        "scope": "bounded to this host, frozen 128D projections, and sealed synthetic task; no biological-function inference"}
    bootstrap = {"method": "independent resampling with replacement on adapter, degree graph, teacher, and learner axes; shared adapter/teacher/learner draws for both sides; percentile interpolation linear",
        "rng": "SplitMix64; each next adds 0x9e3779b97f4a7c15 then applies frozen finalizer; unbiased below-4 draws use rejection",
        "axis_draw_order": ["adapter", "degree_graph", "teacher", "learner"], "replicates": len(reps), "seed": contract["primary_analysis"]["bootstrap_seed"],
        "percentile_2_5": lo, "percentile_97_5": hi, "replicate_estimates": reps}
    return primary, {"crossed": crossed, "bootstrap": bootstrap}

def write_crossed(path, rows):
    with path.open("x", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["adapter_seed", "teacher_seed", "learner_seed", "paired_delta"])
        w.writeheader(); w.writerows(rows)

def secondary_controls(manifest, receipts):
    by_arm = defaultdict(list)
    for fit in manifest["fits"]:
        rec = receipts[fit["fit_id"]]
        by_arm[fit["arm"]].append(finite_loss(rec))
    identity = [x for x in by_arm.get("identity", []) if x is not None]
    arms = {}
    for arm, values in sorted(by_arm.items()):
        finite = [x for x in values if x is not None]
        arms[arm] = {"expected_fit_count": len(values), "finite_fit_count": len(finite), "numerical_or_missing_count": len(values)-len(finite),
                     "mean_heldout_bce": mean(finite), "sd_heldout_bce": (sum((x-mean(finite))**2 for x in finite)/(len(finite)-1))**0.5 if len(finite)>1 else None,
                     "descriptive_only": True}
    if len(identity) == len(by_arm.get("identity", [])) and identity:
        for arm, values in by_arm.items():
            finite = [x for x in values if x is not None]
            arms[arm]["difference_from_identity_mean_unpaired_descriptive"] = mean(finite) - mean(identity) if len(finite) == len(values) else None
    return {"status": "DESCRIPTIVE_SECONDARY_CONTROLS", "arms": arms,
        "warning": "These are arm-level descriptive means; no secondary contrast changes the primary endpoint or its inference."}

def trajectories(manifest, receipts):
    groups = defaultdict(lambda: [[] for _ in range(20)])
    accuracy = defaultdict(list)
    for fit in manifest["fits"]:
        rec = receipts[fit["fit_id"]]
        arm = fit["arm"]
        if rec.get("status") == "complete" and isinstance(rec.get("heldout_accuracy"), (int,float)):
            accuracy[arm].append(rec["heldout_accuracy"])
        for i, value in enumerate(rec.get("epoch_train_loss", [])):
            if isinstance(value, (int,float)) and math.isfinite(value): groups[arm][i].append(value)
    return {"status": "DESCRIPTIVE", "accuracy_mean_by_arm": {k: {"mean": mean(v), "n": len(v)} for k,v in sorted(accuracy.items())},
        "epoch_train_loss_by_arm": {arm: [{"epoch": i+1, "mean": mean(xs), "finite_fit_count": len(xs)} for i,xs in enumerate(rows)] for arm,rows in sorted(groups.items())}}

def exploratory_census(manifest, receipts, pretraining_manifest):
    operator_by_key = {}
    for op in pretraining_manifest["operators"]:
        key = (op["arm"], op.get("adapter_seed"), op.get("graph_seed"), op.get("control_seed"))
        operator_by_key[key] = op
    outcomes = defaultdict(list)
    for fit in manifest["fits"]:
        rec = receipts[fit["fit_id"]]
        outcomes[fit["operator_id"]].append(finite_loss(rec))
    rows = []
    for op in manifest["operators"]:
        vals = outcomes[op["operator_id"]]
        census = operator_by_key[(op["arm"], op.get("adapter_seed"), op.get("graph_realization"), op.get("control_seed"))]["census"]
        rows.append({"operator_id": op["operator_id"], "arm": op["arm"], "adapter_seed": op.get("adapter_seed"),
            "graph_realization": op.get("graph_realization"), "control_seed": op.get("control_seed"),
            "finite_fit_count": sum(x is not None for x in vals), "expected_fit_count": len(vals),
            "mean_heldout_bce_if_complete": mean(vals) if all(x is not None for x in vals) else None,
            "rank": census.get("rank"), "frobenius_norm": census.get("frobenius_norm"), "sigma_max": census.get("sigma_max"),
            "sigma_min": census.get("sigma_min"), "condition_number": census.get("condition_number"),
            "mean_row_entropy_nats": census.get("mean_row_entropy_nats"), "density": census.get("density"), "zero_rows": census.get("zero_rows")})
    return {"status": "EXPLORATORY_ONLY", "operator_rows": rows,
        "correlation_analysis": "not computed; joined operator/outcome table is provided for explicitly exploratory inspection after the primary result"}

def main():
    run = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_RUN
    integrity_path = run / "integrity-receipt.json"
    if not integrity_path.is_file(): raise RuntimeError("integrity receipt absent; outcomes remain locked")
    integrity = json.loads(integrity_path.read_text(encoding="utf-8"))
    if integrity.get("status") != "PASS": raise RuntimeError("integrity gate did not PASS; refusing analysis")
    if sha_file(integrity_path) != (run / "integrity-receipt.sha256").read_text().split()[0]:
        raise RuntimeError("integrity receipt sidecar mismatch")
    contract = json.loads((run / "run-contract.json").read_text(encoding="utf-8"))
    if contract["seal_sha256"] != integrity["seal_sha256"]: raise RuntimeError("integrity receipt seal mismatch")
    manifest = json.loads((run / "execution-manifest.json").read_text(encoding="utf-8"))
    receipts = read_receipts(run)
    if len(receipts) != 656: raise RuntimeError("receipt count changed after integrity PASS")
    analysis_dir = run / "analysis"
    analysis_dir.mkdir(exist_ok=False)

    primary, details = build_primary(manifest, receipts, contract)
    save_json(analysis_dir / "primary-contrast.json", primary)
    if details is not None:
        save_json(analysis_dir / "primary-bootstrap.json", details["bootstrap"])
        write_crossed(analysis_dir / "crossed-factor-summary.csv", details["crossed"])
    else:
        save_json(analysis_dir / "primary-bootstrap.json", {"status": "NOT_ESTIMABLE", "reason": primary["interpretation"]})
        with (analysis_dir / "crossed-factor-summary.csv").open("x", encoding="utf-8") as f: f.write("adapter_seed,teacher_seed,learner_seed,paired_delta\n")

    secondary = secondary_controls(manifest, receipts)
    save_json(analysis_dir / "secondary-controls.json", secondary)
    trajectory = trajectories(manifest, receipts)
    save_json(analysis_dir / "trajectory-summary.json", trajectory)
    pretraining = json.loads((ROOT / "experiments" / "fly-drop-00" / "artifacts" / "pretraining-manifest.json").read_text(encoding="utf-8"))
    exploratory = exploratory_census(manifest, receipts, pretraining)
    save_json(analysis_dir / "exploratory-operator-phenotype.json", exploratory)

    if primary["status"] == "ESTIMABLE":
        ci = primary["bootstrap_95_percentile_ci"]
        sign_summary = "; ".join(f"{axis}: {item['direction_agreement_count']}/{item['level_count']} levels agree" for axis,item in primary["cross_factor_consistency"].items())
        first = (f"# FLY-DROP-00-RUN1 results\n\n"
            f"**Primary contrast:** Δ = {primary['point_estimate_delta']:.8g} held-out BCE (MaleCNS minus mean degree shuffle); 95% multiway bootstrap CI [{ci[0]:.8g}, {ci[1]:.8g}].\n\n"
            f"**Direction:** {primary['direction']}. **Cross-factor consistency:** {sign_summary}.\n\n"
            f"Integrity PASS; {integrity['verified_fit_receipts']}/656 fits and {integrity['verified_total_optimizer_steps']:,} updates verified.\n\n")
    else:
        first = ("# FLY-DROP-00-RUN1 results\n\n"
            f"**Primary contrast:** not estimable without imputation; {primary['missing_primary_cells']} required MaleCNS/degree cells have scientific numerical failures.\n\n"
            f"Integrity PASS; {integrity['verified_fit_receipts']}/656 fits and {integrity['verified_total_optimizer_steps']:,} updates verified. Numerical failure is retained as an observed computational phenotype.\n\n")
    first += ("## Scope\n\nThis result concerns the frozen 128D projected MaleCNS segment-connection-table operator in this synthetic host task. It does not establish biological function or a mechanism. Jev was not part of RUN1.\n\n"
        "## Primary result and crossed factors\n\nSee primary-contrast.json, primary-bootstrap.json, and crossed-factor-summary.csv. The degree-shuffle graph realizations are summarized in the primary contrast file.\n\n"
        "## Secondary controls\n\nSee secondary-controls.json; these summaries are descriptive and do not replace the primary contrast.\n\n"
        "## Accuracy and training trajectories\n\nSee trajectory-summary.json.\n\n"
        "## Exploratory operator census join\n\nSee exploratory-operator-phenotype.json. This join is exploratory and was opened only after the primary and secondary outputs were written.\n")
    with (analysis_dir / "RESULTS.md").open("x", encoding="utf-8", newline="\n") as f:
        f.write(first); f.flush(); os.fsync(f.fileno())
    print("Analysis complete after integrity PASS; primary outputs written before secondary and exploratory summaries.")

if __name__ == "__main__": main()
