"""ASK rung driver.

  python run_ask.py train     --head linear|mlp   train the dedicated heads on TRAIN, run them on DEV features (no labels of DEV used)
  python run_ask.py calibrate --head linear|mlp   CAL only: signal on CAL, fit ASK thresholds, write policies, freeze
  python run_ask.py score     --head linear|mlp   HOLD through the C0 runtime, criteria A1-A3, verdict (once per head)

The mlp head is only trained and scored if the preregistered condition holds (see PREREGISTRATION.md); `train --head mlp` checks it.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import shutil
import sys
import time
from pathlib import Path

import numpy as np

from ask import metrics, records, score, train
from ask.common import (ALPHAS, C1_EVIDENCE, C1_FREEZE, DEV_ROWS, EVIDENCE, HEADS, MATCHED_PRECISIONS, PREREGISTRATION, PRIMARY, PRIMARY_ALPHA, RESULTS, SURFACES, alpha_tag,
                        c0_source_sha256, c1fit, canon, head_dir, model, rung0, sha256_file, verify_c1_evidence, write_json)

REPORT_NAME = "ask-report.json"


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def _cal(truth):
    return ~truth["hold"]  # the only row selection the train and calibrate stages use


def mlp_warranted() -> tuple:
    """The preregistered rule: run the MLP iff the linear head is not USEFUL and its CAL AP (primary, dedicated) is at least 0.10."""
    report = head_dir("linear") / REPORT_NAME
    thresholds = head_dir("linear") / "thresholds.json"
    if not report.exists() or not thresholds.exists():
        return False, "the linear head has not been scored yet"
    verdict = json.loads(report.read_text(encoding="ascii"))["verdict"]
    cal_ap = json.loads(thresholds.read_text(encoding="ascii"))["cal_signal"][PRIMARY]["dedicated"]["ap"]
    if verdict == "USEFUL ASK OBSERVER":
        return False, "the linear head is already USEFUL"
    if cal_ap < 0.10:
        return False, f"the linear head shows no signal on CAL (AP {cal_ap:.3f} < 0.10)"
    return True, f"linear verdict {verdict!r}, CAL AP {cal_ap:.3f} >= 0.10"


def cmd_train(args) -> int:
    head = args.head
    if head == "mlp":
        ok, why = mlp_warranted()
        if not ok:
            print(f"the MLP is not warranted: {why}", file=sys.stderr)
            return 2
    verify_c1_evidence()
    d = head_dir(head)
    d.mkdir(parents=True, exist_ok=True)
    log("verifying Rung 0 artifacts")
    identity = rung0.verify(log)
    log("loading TRAIN labels")
    labels, train_sha = train.load_train_labels()
    log(f"TRAIN: {int(labels.sum())} SHOULD_ASK of {len(labels)} ({labels.mean():.4f})")
    contract = records.contract(head)
    contract_dir = d / "world" / "contracts"
    bundle_dir = d / "world" / "bundles"
    for src, dst in ((C1_EVIDENCE / "world" / "contracts", contract_dir), (C1_EVIDENCE / "world" / "bundles", bundle_dir)):
        dst.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.json"):
            shutil.copyfile(f, dst / f.name)
    (contract_dir / f"{contract['name']}.json").write_bytes(canon.canonical_bytes(contract))
    ppm, receipts = {}, {}
    for surface in SURFACES:
        log("training", head, surface)
        out = train.train_head(surface, head, labels)
        probe_np = train.probabilities(out["weights"], head, surface, 0, 2000)
        probe_gap = float(np.abs(probe_np - out["torch_probe"]).max())
        if probe_gap > 1e-4:
            raise RuntimeError(f"numpy inference does not reproduce the trained model for {surface}: {probe_gap}")
        weights_path = d / "weights" / f"{surface}.npz"
        weights_path.parent.mkdir(exist_ok=True)
        np.savez_compressed(weights_path, **out["weights"])
        ppm[surface] = train.quantize(train.dev_probabilities(out["weights"], head, surface))
        receipt = {"surface": surface, "head": head, "seed": 20260929, "epoch_losses": out["epoch_losses"], "train_rows": int(len(labels)), "train_positives": int(labels.sum()),
                   "train_file_sha256": train_sha, "weights_sha256": sha256_file(weights_path), "numpy_vs_torch_max_difference": probe_gap}
        write_json(d / "weights" / f"{surface}-fit.json", receipt)
        receipts[surface] = receipt
        scaler = rung0.load_head(surface, "decision")
        bundle = records.bundle(identity, contract, surface, head, out["weights"], scaler, int(scaler["mean"].shape[0]),
                                [receipt["weights_sha256"], sha256_file(d / "weights" / f"{surface}-fit.json"), train_sha])
        (bundle_dir / f"{bundle['name']}.json").write_bytes(canon.canonical_bytes(bundle))
        log(f"  {surface}: final epoch loss {out['epoch_losses'][-1]:.4f}")
    np.savez_compressed(d / "dev-ask-ppm.npz", **ppm)
    model.load_dir(contract_dir, "S15_DECISION_CONTRACT_V1")
    model.load_dir(bundle_dir, "S15_OBSERVER_BUNDLE_V1")
    write_json(d / "train.json", {"identity": identity, "train_file_sha256": train_sha, "receipts": receipts, "ppm_sha256": sha256_file(d / "dev-ask-ppm.npz")})
    log("trained")
    return 0


def _bundles(d: Path) -> dict:
    return {r["name"]: r for r in (canon.loads_strict(p.read_bytes()) for p in sorted((d / "world" / "bundles").glob("*.json")))}


def _sources(d: Path, bundles: dict, surface: str, head: str) -> dict:
    out = {bundles[f"bank_{surface}_should_ask_{head}"]["bundle_id"]: (str(d / "dev-ask-ppm.npz"), surface)}
    out[bundles[f"bank_{surface}_decision"]["bundle_id"]] = (str(C1_EVIDENCE / "dev-ppm.npz"), f"{surface}.decision")
    out[bundles[f"bank_{surface}_action_type"]["bundle_id"]] = (str(C1_EVIDENCE / "dev-ppm.npz"), f"{surface}.action_type")
    return out


def cmd_calibrate(args) -> int:
    head = args.head
    d = head_dir(head)
    freeze_path = d / "freeze.json"
    if freeze_path.exists():
        print("already frozen", file=sys.stderr)
        return 2
    verify_c1_evidence()
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    c1ppm = np.load(C1_EVIDENCE / "dev-ppm.npz", allow_pickle=False)
    askppm = np.load(d / "dev-ask-ppm.npz", allow_pickle=False)
    cal = _cal(truth)
    y = (truth["truth_decision"] == c1fit.ASK)[cal]
    bundles = _bundles(d)
    c1_thresholds = json.loads((C1_EVIDENCE / "thresholds.json").read_text(encoding="ascii"))["thresholds"]
    contract_name = records.contract(head)["name"]
    cost_class = "T1_LINEAR" if head == "linear" else "T2_MLP"
    cal_signal, thresholds, policy_hashes = {}, {}, {}
    (d / "world" / "policies").mkdir(parents=True, exist_ok=True)
    c1_bundles = {k.replace("bank_", "", 1): v for k, v in bundles.items() if k.endswith(("_decision", "_action_type"))}
    for surface in SURFACES:
        ded = askppm[surface][cal][:, 1]
        base = c1ppm[f"{surface}.decision"][cal][:, c1fit.ASK]
        cal_signal[surface] = {"dedicated": {"ap": metrics.average_precision(ded, y), "auroc": metrics.auroc(ded, y)}, "baseline": {"ap": metrics.average_precision(base, y), "auroc": metrics.auroc(base, y)},
                               "cal_rows": int(cal.sum()), "cal_ask_rows": int(y.sum())}
        thresholds[surface] = {}
        for alpha in ALPHAS:
            tag = alpha_tag(alpha)
            t_ded, t_base = metrics.fit_threshold(ded, y, alpha), metrics.fit_threshold(base, y, alpha)
            thresholds[surface][tag] = {"alpha": alpha, "dedicated": metrics.rule_outcomes(ded, y, t_ded), "baseline": metrics.rule_outcomes(base, y, t_base)}
            files = {
                f"{surface}-{tag}-dedicated": records.ask_only_policy(f"ask_only_{surface}_{tag}", "ask", bundles[f"bank_{surface}_should_ask_{head}"], "SHOULD_ASK", t_ded, cost_class),
                f"{surface}-{tag}-baseline": records.ask_only_policy(f"ask_base_{surface}_{tag}", "dec", bundles[f"bank_{surface}_decision"], "ASK", t_base, "T1_LINEAR"),
            }
            if abs(alpha - PRIMARY_ALPHA) < 1e-9:
                files[f"{surface}-{tag}-combined"] = records.combined_policy(surface, tag, {k: v for k, v in c1_thresholds[surface]["a05"]["thresholds_ppm"].items()}, c1_bundles,
                                                                             bundles[f"bank_{surface}_should_ask_{head}"], t_ded, cost_class)
            for name, record in files.items():
                path = d / "world" / "policies" / f"{name}.json"
                path.write_bytes(canon.canonical_bytes(record))
                model.load_world(path, d / "world" / "contracts", d / "world" / "bundles")
                policy_hashes[name] = sha256_file(path)
        primary_tag = alpha_tag(PRIMARY_ALPHA)
        print(f"{surface:18s} CAL AP dedicated={cal_signal[surface]['dedicated']['ap']:.3f} baseline={cal_signal[surface]['baseline']['ap']:.3f} | a50 T dedicated={thresholds[surface][primary_tag]['dedicated']['threshold_ppm']} "
              f"baseline={thresholds[surface][primary_tag]['baseline']['threshold_ppm']}")
    write_json(d / "thresholds.json", {"cal_signal": cal_signal, "thresholds": thresholds})
    write_json(freeze_path, {"head": head, "preregistration_sha256": sha256_file(PREREGISTRATION), "c0_source_sha256": c0_source_sha256(), "c1_freeze_sha256": sha256_file(C1_FREEZE),
                             "thresholds_sha256": sha256_file(d / "thresholds.json"), "ask_ppm_sha256": sha256_file(d / "dev-ask-ppm.npz"), "policy_sha256": policy_hashes,
                             "weights_sha256": {s: sha256_file(d / "weights" / f"{s}.npz") for s in SURFACES}})
    log("frozen; HOLD has not been scored")
    return 0


def _check_freeze(head: str) -> dict:
    d = head_dir(head)
    if not (d / "freeze.json").exists():
        raise SystemExit("no freeze record: run calibrate first")
    freeze = json.loads((d / "freeze.json").read_text(encoding="ascii"))
    current = {"preregistration_sha256": sha256_file(PREREGISTRATION), "c0_source_sha256": c0_source_sha256(), "c1_freeze_sha256": sha256_file(C1_FREEZE),
               "thresholds_sha256": sha256_file(d / "thresholds.json"), "ask_ppm_sha256": sha256_file(d / "dev-ask-ppm.npz")}
    for key, value in current.items():
        if freeze[key] != value:
            raise SystemExit(f"refusing to score: {key} changed since the freeze")
    for name, digest in freeze["policy_sha256"].items():
        if sha256_file(d / "world" / "policies" / f"{name}.json") != digest:
            raise SystemExit(f"refusing to score: policy {name} changed since the freeze")
    return freeze


def _outcome_counts(disposition, truth_ask):
    asked = disposition == c1fit.ASKED
    correct = int((asked & truth_ask).sum())
    return {"asks": int(asked.sum()), "correct_asks": correct, "precision": correct / int(asked.sum()) if asked.sum() else None, "recall": correct / int(truth_ask.sum())}


def cmd_score(args) -> int:
    head = args.head
    d = head_dir(head)
    if head == "mlp":
        ok, why = mlp_warranted()
        if not ok:
            raise SystemExit(f"the MLP is not warranted: {why}")
    freeze = _check_freeze(head)
    report_path = d / REPORT_NAME
    if report_path.exists() and not args.again:
        raise SystemExit("HOLD was already scored for this head; --again re-scores and records that fact")
    verify_c1_evidence()
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    c1ppm = np.load(C1_EVIDENCE / "dev-ppm.npz", allow_pickle=False)
    askppm = np.load(d / "dev-ask-ppm.npz", allow_pickle=False)
    fitted = json.loads((d / "thresholds.json").read_text(encoding="ascii"))
    bundles = _bundles(d)
    hold = np.flatnonzero(truth["hold"])
    truth_dec, truth_act = truth["truth_decision"][hold], truth["truth_action"][hold]
    y = truth_dec == c1fit.ASK
    contracts_dir, bundles_dir = str(d / "world" / "contracts"), str(d / "world" / "bundles")
    jobs = []
    for surface in SURFACES:
        sources = _sources(d, bundles, surface, head)
        for alpha in ALPHAS:
            tag = alpha_tag(alpha)
            for scorer in ("dedicated", "baseline"):
                name = f"{surface}-{tag}-{scorer}"
                jobs.append({"name": name, "policy": str(d / "world" / "policies" / f"{name}.json"), "contracts": contracts_dir, "bundles": bundles_dir, "sources": sources})
        name = f"{surface}-{alpha_tag(PRIMARY_ALPHA)}-combined"
        jobs.append({"name": name, "policy": str(d / "world" / "policies" / f"{name}.json"), "contracts": contracts_dir, "bundles": bundles_dir, "sources": sources})
        c1_policy = C1_EVIDENCE / "world" / "policies" / f"{surface}-a05.json"  # the C1 controller alone, with the same vectors, for a row-aligned comparison
        jobs.append({"name": f"{surface}-c1only", "policy": str(c1_policy), "contracts": str(C1_EVIDENCE / "world" / "contracts"), "bundles": str(C1_EVIDENCE / "world" / "bundles"), "sources": sources})
    log(f"scoring {len(hold)} HOLD rows x {len(jobs)} policies through the C0 runtime")
    workers = max(1, min(8, (os.cpu_count() or 2) - 1))
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        ran = {r["name"]: r for r in pool.map(score.run_policy, jobs)}
    log("runtime done")
    surfaces_out, per_surface_criteria = {}, {}
    for surface in SURFACES:
        ded = askppm[surface][hold][:, 1]
        base = c1ppm[f"{surface}.decision"][hold][:, c1fit.ASK]
        signal = {}
        for label, s in (("dedicated", ded), ("baseline", base)):
            signal[label] = {"ap": metrics.average_precision(s, y), "auroc": metrics.auroc(s, y),
                             "recall_at": {str(p): metrics.recall_at_precision(s, y, p) for p in MATCHED_PRECISIONS}}
        entry = {"signal": signal, "alphas": {}}
        for alpha in ALPHAS:
            tag = alpha_tag(alpha)
            row = {}
            for scorer, s in (("dedicated", ded), ("baseline", base)):
                t = fitted["thresholds"][surface][tag][scorer]["threshold_ppm"]
                sim = np.where((s >= t) if t is not None else np.zeros(len(s), dtype=bool), c1fit.ASKED, c1fit.ESCALATED).astype(np.int8)
                got = ran[f"{surface}-{tag}-{scorer}"]["disposition"]
                if not np.array_equal(got, sim):
                    raise SystemExit(f"C0 runtime and the numpy rule disagree for {surface} {tag} {scorer}")
                row[scorer] = {"threshold_ppm": t, "hold": _outcome_counts(got, y), "cal": fitted["thresholds"][surface][tag][scorer]}
            entry["alphas"][tag] = row
        v = c1fit.views(c1ppm[f"{surface}.decision"][hold], c1ppm[f"{surface}.action_type"][hold])
        c1_thr = json.loads((C1_EVIDENCE / "thresholds.json").read_text(encoding="ascii"))["thresholds"][surface]["a05"]["thresholds_ppm"]
        t_ask = fitted["thresholds"][surface][alpha_tag(PRIMARY_ALPHA)]["dedicated"]["threshold_ppm"]
        combined = ran[f"{surface}-{alpha_tag(PRIMARY_ALPHA)}-combined"]
        c1only = ran[f"{surface}-c1only"]
        c1_disp, c1_tgt = c1fit.simulate(v, c1_thr)
        if not (np.array_equal(c1only["disposition"], c1_disp) and np.array_equal(c1only["target"], c1_tgt)):
            raise SystemExit(f"C1 controller run differs from its numpy rules for {surface}")
        sim_disp, sim_tgt = c1_disp.copy(), c1_tgt.copy()
        if t_ask is not None:
            fire = askppm[surface][hold][:, 1] >= t_ask
            sim_disp[fire], sim_tgt[fire] = c1fit.ASKED, -1
        if not (np.array_equal(combined["disposition"], sim_disp) and np.array_equal(combined["target"], sim_tgt)):
            raise SystemExit(f"combined controller differs from its numpy rules for {surface}")
        entry["controller"] = {"combined": c1fit.outcomes(combined["disposition"], combined["target"], truth_dec, truth_act), "c1_only": c1fit.outcomes(c1only["disposition"], c1only["target"], truth_dec, truth_act),
                               "ask_threshold_ppm": t_ask, "combined_ask_outcomes": _outcome_counts(combined["disposition"], y), "c1_ask_outcomes": _outcome_counts(c1only["disposition"], y)}
        primary_rule = entry["alphas"][alpha_tag(PRIMARY_ALPHA)]["dedicated"]["hold"] | {"threshold_ppm": entry["alphas"][alpha_tag(PRIMARY_ALPHA)]["dedicated"]["threshold_ppm"]}
        entry["criteria"] = score.criteria(signal, primary_rule, {"combined": entry["controller"]["combined"], "c1": entry["controller"]["c1_only"]})
        per_surface_criteria[surface] = entry["criteria"]
        surfaces_out[surface] = entry
    report = {"schema": "ask-report/v1", "head": head, "rescored": bool(args.again), "primary_surface": PRIMARY, "primary_alpha": PRIMARY_ALPHA, "hold_rows": int(len(hold)), "hold_ask_rows": int(y.sum()),
              "verdict": score.verdict(per_surface_criteria[PRIMARY]), "criteria": per_surface_criteria, "freeze": freeze, "surfaces": surfaces_out,
              "runtime_integrity": {"all_runs_identical_on_repeat": all(r["repeat_identical"] for r in ran.values()), "numpy_matches_c0_on_every_row": True, "policies": len(jobs)}}
    write_json(report_path, report)
    RESULTS.mkdir(exist_ok=True)
    shutil.copyfile(report_path, RESULTS / f"ask-report-{head}.json")
    for name in ("freeze.json", "thresholds.json", "train.json"):
        shutil.copyfile(d / name, RESULTS / f"{name.split('.')[0]}-{head}.json")
    log("verdict:", report["verdict"], per_surface_criteria[PRIMARY])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("train", cmd_train), ("calibrate", cmd_calibrate), ("score", cmd_score)):
        p = sub.add_parser(name)
        p.add_argument("--head", choices=HEADS, required=True)
        if name == "score":
            p.add_argument("--again", action="store_true")
        p.set_defaults(fn=fn)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
