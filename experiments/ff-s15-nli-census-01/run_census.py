"""NLI-UNKNOWN oracle-headroom census driver.

  python run_census.py prepare   verify Rung 0 hashes, rebuild the NLI head outputs on DEV (reconstruction gate), read true NLI labels
  python run_census.py census    CAL only: the sets, the conjunction search, the noise band, the perfect-NLI ceiling; writes results/census.json

No policy, no training, no HOLD. See PLAN.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from nli.common import (C1_EVIDENCE, EVIDENCE, NLI_SURFACE, PRIMARY, RESULTS, SURFACES, UNKNOWN, c1fit, c1obs, rung0, sha256_file, verify_c1_evidence, write_json)  # first: puts the ASK rung on sys.path
from ask import metrics as askm  # noqa: E402
from nli import census, heads  # noqa: E402


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def cmd_prepare(_args) -> int:
    verify_c1_evidence()
    EVIDENCE.mkdir(exist_ok=True)
    log("verifying Rung 0 artifacts")
    identity = rung0.verify(log)
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    ppm, gates = {}, {}
    for surface in SURFACES:
        log("rebuilding NLI outputs for", surface)
        p = heads.compute(surface)
        gates[surface] = heads.reconstruction_gate(surface, p)
        ppm[surface] = c1obs.quantize(p)
        log("  reconstruction gate passed:", gates[surface]["label_matches"], "of", gates[surface]["rows"])
    np.savez_compressed(EVIDENCE / "nli-ppm.npz", **ppm)
    codes = heads.true_nli_codes([str(i) for i in truth["ids"]])
    np.savez_compressed(EVIDENCE / "nli-truth.npz", codes=codes)
    write_json(EVIDENCE / "prepare.json", {"identity_lock_sha256": identity["lock_sha256"], "reconstruction_gates": gates, "nli_ppm_sha256": sha256_file(EVIDENCE / "nli-ppm.npz"),
                                           "nli_truth_sha256": sha256_file(EVIDENCE / "nli-truth.npz"), "true_nli_counts": {str(k): int((codes == k).sum()) for k in (-1, 0, 1, 2)}})
    log("prepared")
    return 0


def cmd_census(_args) -> int:
    verify_c1_evidence()
    truth = np.load(C1_EVIDENCE / "dev-truth.npz", allow_pickle=False)
    c1ppm = np.load(C1_EVIDENCE / "dev-ppm.npz", allow_pickle=False)
    nlippm = np.load(EVIDENCE / "nli-ppm.npz", allow_pickle=False)
    nli_true = np.load(EVIDENCE / "nli-truth.npz", allow_pickle=False)["codes"]
    cal = ~truth["hold"]  # the only row selection used below
    y = (truth["truth_decision"] == c1fit.ASK)[cal]
    truth_decision, true_nli = truth["truth_decision"][cal], nli_true[cal]
    ask = c1ppm[f"{PRIMARY}.decision"][cal][:, c1fit.ASK]
    unknown_or_missing = (true_nli == UNKNOWN) | (true_nli == -1)
    crosstab = {d: {str(k): int(((truth_decision == di) & (true_nli == k)).sum()) for k in (0, 1, 2, -1)} for d, di in (("ACT", c1fit.ACT), ("ASK", c1fit.ASK), ("ABSTAIN", c1fit.ABSTAIN))}
    ceiling = census.veto_ceiling(ask, unknown_or_missing, y)
    strict = census.veto_ceiling(ask, true_nli == UNKNOWN, y)
    out = {
        "schema": "nli-census/v1", "cal_rows": int(cal.sum()), "cal_ask_rows": int(y.sum()), "prevalence": float(y.mean()), "primary_ask_scorer": f"{PRIMARY} decision head P(ASK)", "primary_nli_head": NLI_SURFACE,
        "crosstab_truth_decision_by_true_nli": crosstab,
        "ask_alone": {"ap": askm.average_precision(ask, y), "auroc": askm.auroc(ask, y)},
        "true_nli_standalone": {"ask_rate_given_unknown": float(y[true_nli == UNKNOWN].mean()), "ask_rate_given_unknown_or_unlabelled": float(y[unknown_or_missing].mean()),
                                "ask_rate_given_entailed_or_contradicted": float(y[(true_nli == 0) | (true_nli == 1)].mean()) if ((true_nli == 0) | (true_nli == 1)).any() else None},
        "ceiling_perfect_nli_pass_through_unlabelled": ceiling, "ceiling_perfect_nli_strict_unknown_only": strict, "heads": {},
    }
    a_set = census.usable_set(ask, y)["mask"]  # post hoc, added after the ceiling was read: why is the perfect-NLI ceiling so low?
    a_fp = a_set & ~y
    out["a_false_positive_anatomy_post_hoc"] = {
        "false_positives": int(a_fp.sum()), "by_true_nli": {str(k): int((a_fp & (true_nli == k)).sum()) for k in (-1, 0, 1, 2)},
        "by_truth_decision": {d: int((a_fp & (truth_decision == di)).sum()) for d, di in (("ACT", c1fit.ACT), ("ABSTAIN", c1fit.ABSTAIN))},
        "removable_by_a_perfect_veto": int((a_fp & ((true_nli == 0) | (true_nli == 1))).sum()),
    }
    for surface in SURFACES:
        unk = nlippm[surface][cal][:, UNKNOWN]
        entry = {
            "standalone": {"ap": askm.average_precision(unk, y), "auroc": askm.auroc(unk, y)}, "union": census.union_view(ask, unk, y), "conjunction": census.best_conjunction(ask, unk, y),
            "noise": census.noise_band(ask, unk, y), "lift_table": census.lift_table(ask, unk, y),
        }
        out["heads"][surface] = entry
        c = entry["conjunction"]
        log(f"NLI head {surface:18s} standalone AP={entry['standalone']['ap']:.3f} | conjunction headroom={c['headroom']} (b={c['b']}) noise p95={entry['noise']['p95']:.3f}")
    primary = out["heads"][NLI_SURFACE]
    out["decision"] = census.decide({"union": primary["union"], "conjunction": primary["conjunction"], "noise": primary["noise"], "ceiling": ceiling})
    RESULTS.mkdir(exist_ok=True)
    write_json(RESULTS / "census.json", out)
    log("ceiling (perfect NLI veto) headroom:", ceiling.get("headroom"), "| decision:", out["decision"])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").set_defaults(fn=cmd_prepare)
    sub.add_parser("census").set_defaults(fn=cmd_census)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
