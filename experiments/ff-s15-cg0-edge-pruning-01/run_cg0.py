"""C-G0 driver.

  python run_cg0.py prepare   bind to Lexi's frozen artifacts, integrity gate on her sampled-pair AUCs, T0 table from TRAIN, score the full pair universe of DEV and TEST
  python run_cg0.py census    matched pruning frontiers, gate, noise band, transfer, geometry -> results/cg0-census.json

Frozen head, no training, no HOLD-style firewall needed (nothing is fitted except T0's table on TRAIN and thresholds on DEV). See PLAN.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

import numpy as np

from cg import frontier, head, universe
from cg.common import (BANK, EPSILONS, EVIDENCE, GAIN_BAR, GATE_EPSILONS, HELD, OUT, RESULTS, TEST_SPLITS, TYPE_CODES, pair_name, read_json, sha256_file, verify_frozen_inputs, write_json)


def log(*parts):
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def crosscheck_constants() -> None:
    """The constants copied into cg.common must equal Lexi's own (her module is imported read-only, only for this comparison)."""
    import importlib.util

    from cg import common

    spec = importlib.util.spec_from_file_location("lexi_common", common.LEXI_CODE / "common.py")
    lexi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lexi)
    if tuple(lexi.PREDICATES) != common.PREDICATES or tuple(lexi.ENTITY_TYPES) != common.ENTITY_TYPES:
        raise RuntimeError("predicate or entity-type constants differ from Lexi's")
    for eid in ("obj_0", "ag_1", "loc_9", "sw_2", "cont_3", "res_4", "e_unknown", "x", "e_out_of_scope"):
        if lexi.identifier_type(eid) != common.identifier_type(eid):
            raise RuntimeError(f"identifier_type differs for {eid}")


def integrity_gate(scorer: head.FrozenEdgeHead, identity: dict) -> dict:
    """Reproduce Lexi's per-split sampled-pair AUC with this implementation of her frozen head."""
    theirs = identity["lexi_sampled_pair_auc"]
    mine, worst = {}, 0.0
    for split in ("DEV", *TEST_SPLITS):
        a, b, y = [], [], []
        with (OUT / "task-examples" / "edge_existence" / f"{split}.jsonl").open(encoding="utf-8") as source:
            for line in source:
                r = json.loads(line)
                a.append(r["a_idx"]), b.append(r["b_idx"]), y.append(r["label"])
        scores = scorer.score(np.array(a, dtype=np.int64), np.array(b, dtype=np.int64))
        mine[split] = head.auc(scores, np.array(y))
        worst = max(worst, abs(mine[split] - theirs[split]))
        log(f"  {split}: mine {mine[split]:.6f} vs hers {theirs[split]:.6f}")
    if worst > 1e-5:
        raise RuntimeError(f"integrity gate failed: worst AUC difference {worst}")
    return {"mine": mine, "theirs": theirs, "worst_difference": worst}


def cmd_prepare(_args) -> int:
    EVIDENCE.mkdir(exist_ok=True)
    log("verifying frozen inputs (hashes, including the two 3.7 GB feature files)")
    identity = verify_frozen_inputs(log)
    crosscheck_constants()
    log("constants cross-checked against Lexi's module")
    scorer = head.FrozenEdgeHead()
    log("integrity gate: reproducing her sampled-pair AUC on DEV and eight TEST partitions")
    gate = integrity_gate(scorer, identity)
    log("loading rowmap and mentions")
    rowmap, mentions = universe.load_rowmap(), universe.load_mentions()
    log("T0: natural type-pair counts over the full pair universe of canonical TRAIN worlds")
    counts = universe.train_pair_counts(rowmap, mentions)
    write_json(EVIDENCE / "t0-train-counts.json", counts)
    stats = {}
    for split in ("DEV", *TEST_SPLITS):
        log("enumerating and scoring the full pair universe:", split)
        arrays = universe.enumerate_split(split, rowmap, mentions)
        arrays["score"] = scorer.score(arrays["a"].astype(np.int64), arrays["b"].astype(np.int64))
        np.savez_compressed(EVIDENCE / f"universe-{split}.npz", **{k: v for k, v in arrays.items() if k in ("label", "pair_type", "family", "score", "row")})
        stats[split] = {"pairs": int(len(arrays["label"])), "edges": int(arrays["label"].sum())}
        log(f"  {stats[split]}")
    write_json(EVIDENCE / "prepare.json", {"identity": identity, "integrity_gate": gate, "universe": stats, "evidence_sha256": {p.name: sha256_file(p) for p in sorted(EVIDENCE.glob("*.npz")) + [EVIDENCE / "t0-train-counts.json"]}})
    log("prepared")
    return 0


def _pool(splits):
    parts = [np.load(EVIDENCE / f"universe-{s}.npz") for s in splits]
    return {k: np.concatenate([p[k] for p in parts]) for k in ("label", "pair_type", "family", "score")}


def _subset(data, mask):
    return {k: v[mask] for k, v in data.items()}


def _view(data, rank, eps):
    """Frontier plus the arrays' basic counts."""
    return frontier.frontier(data["label"], data["pair_type"], data["score"], rank, eps)


def cmd_census(_args) -> int:
    counts = read_json(EVIDENCE / "t0-train-counts.json")
    prepare = read_json(EVIDENCE / "prepare.json")
    rank = frontier.t0_rank(counts["pairs"], counts["edges"])
    dev = _pool(["DEV"])
    test = _pool(TEST_SPLITS)
    held_codes = [int(h[1:]) for h in HELD]
    held_mask = np.isin(test["family"], held_codes)
    families = sorted(set(test["family"].tolist()))
    eps = EPSILONS
    out = {"schema": "cg0-census/v1", "epsilons": list(eps), "universe": prepare["universe"], "integrity_gate": prepare["integrity_gate"],
           "t0_type_pair_rates": {pair_name(c): {"pairs": counts["pairs"][c], "edges": counts["edges"][c], "rate": (counts["edges"][c] / counts["pairs"][c]) if counts["pairs"][c] else None}
                                  for c in range(len(counts["pairs"])) if counts["pairs"][c]}}
    populations = {"DEV": dev, "TEST_pooled": test, "TEST_in_family": _subset(test, ~held_mask), "TEST_held_S7_S8_S9": _subset(test, held_mask)}
    for f in families:
        populations[f"TEST_S{f}"] = _subset(test, test["family"] == f)
    out["frontier"] = {}
    for name, data in populations.items():
        log("frontier:", name, len(data["label"]), "pairs")
        out["frontier"][name] = {"pairs": int(len(data["label"])), "edges": int(data["label"].sum()), "by_epsilon": _view(data, rank, eps)}
    log("DEV-fitted thresholds applied to TEST populations")
    fitted = out["frontier"]["DEV"]["by_epsilon"]
    out["dev_fit_transfer"] = {}
    for e in eps:
        rec = {}
        for arm in ("T0", "T0+T1"):
            p = fitted[str(e)][arm]
            thr = p.get("threshold", float("-inf"))
            rec[arm] = {"fit_on_dev": {"k": p["k"], "pruned_share": p["pruned_share"], "edge_loss": p["edge_loss"]}}
            for name in ("TEST_pooled", "TEST_in_family", "TEST_held_S7_S8_S9", "TEST_S7", "TEST_S8", "TEST_S9"):
                d = populations[name]
                rec[arm][name] = frontier.apply_params(d["label"], d["pair_type"], d["score"], rank, p["k"], thr)
        out["dev_fit_transfer"][str(e)] = rec
    log(f"noise band on pooled TEST ({len(test['label'])} pairs)")
    out["noise_band_test_pooled"] = frontier.noise_band(test["label"], test["pair_type"], test["score"], rank, GATE_EPSILONS + (0.005, 0.05))
    out["within_pair_type_auc"] = {"TEST_pooled": frontier.within_pair_type_auc(test["label"], test["pair_type"], test["score"], head.auc),
                                   "TEST_held_S7_S8_S9": frontier.within_pair_type_auc(*[populations["TEST_held_S7_S8_S9"][k] for k in ("label", "pair_type", "score")], head.auc)}
    pooled_auc = head.auc(test["score"], test["label"])
    y = test["label"].astype(bool)
    q = [0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99]
    out["full_pair_pooled_auc_test"] = pooled_auc
    out["score_geometry_test_pooled"] = {"edges_quantiles": dict(zip(map(str, q), np.quantile(test["score"][y], q).tolist())), "non_edges_quantiles": dict(zip(map(str, q), np.quantile(test["score"][~y], q).tolist()))}
    out["gate"] = evaluate_gate(out)
    RESULTS.mkdir(exist_ok=True)
    write_json(RESULTS / "cg0-census.json", out)
    log("gate:", json.dumps(out["gate"], indent=1))
    return 0


def evaluate_gate(out: dict) -> dict:
    """The preregistered rule (PLAN.md): pooled TEST gain >= 10 points at eps 1% and 2%, positive on S7/S8/S9 individually at both, and above the noise band's 95th percentile at both."""
    pooled, noise = out["frontier"]["TEST_pooled"]["by_epsilon"], out["noise_band_test_pooled"]
    per_eps = {}
    for e in GATE_EPSILONS:
        held = {h: out["frontier"][f"TEST_{h}"]["by_epsilon"][str(e)]["gain"] for h in HELD}
        gain = pooled[str(e)]["gain"]
        per_eps[str(e)] = {"pooled_gain": gain, "meets_bar": bool(gain is not None and gain >= GAIN_BAR - 1e-12), "held_gains": held,
                           "held_all_positive": bool(all(g is not None and g > 0 for g in held.values())), "noise_p95": noise[str(e)]["p95"], "above_noise": bool(gain is not None and gain > noise[str(e)]["p95"])}
    passed = all(v["meets_bar"] and v["held_all_positive"] and v["above_noise"] for v in per_eps.values())
    return {"per_epsilon": per_eps, "advance_t1": bool(passed)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").set_defaults(fn=cmd_prepare)
    sub.add_parser("census").set_defaults(fn=cmd_census)
    args = parser.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
