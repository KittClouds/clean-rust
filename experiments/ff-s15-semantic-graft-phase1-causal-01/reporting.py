"""Target-separated DEV metrics and bounded diagnostics; no fitted auxiliary probes."""
from __future__ import annotations

import json
import math
import numpy as np
import torch

from contract import default_config, pad_candidates
from graft.contracts import CANDIDATE_TARGETS, GLOBAL_TARGETS
from graft.evaluate import measurements, predictions, metrics_for_rows, runtime_envelopes
from graft.model import forward_batch
from graft.objective import shared_objective, renderer_loss


def binary_details(y, p):
    y, p = np.asarray(y, int), np.asarray(p, float)
    result = measurements(y, p, "binary")
    if not len(y):
        return result
    pred = p >= .5
    matrix = [[int(((y == truth) & (pred == value)).sum()) for value in (0, 1)]
              for truth in (0, 1)]
    class_f1 = []
    for value in (0, 1):
        tp = matrix[value][value]
        fp, fn = matrix[1-value][value], matrix[value][1-value]
        class_f1.append(2 * tp / max(1, 2 * tp + fp + fn))
    result.update({"macro_f1": float(np.mean(class_f1)), "confusion_truth_by_prediction": matrix,
                   "class_support": {"0": int((y == 0).sum()), "1": int((y == 1).sum())},
                   "observed_majority_accuracy": float(max((y == 0).sum(), (y == 1).sum()) / len(y))})
    return result


def per_target(rows):
    result = {"global": {}, "candidate": {}}
    for branch, names in (("global", GLOBAL_TARGETS), ("candidate", CANDIDATE_TARGETS)):
        for i, name in enumerate(names):
            y, p = [], []
            for row in rows:
                if branch == "global":
                    if row["global_available"][i]:
                        y.append(row["global_y"][i]); p.append(row["global_p"][i])
                else:
                    mask = np.asarray(row["candidate_available"], bool)[:, i]
                    y.extend(np.asarray(row["candidate_y"])[mask, i].tolist())
                    p.extend(np.asarray(row["candidate_p"])[mask, i].tolist())
            if branch == "global" and i == 5:
                item = measurements(y, p, "count")
                item["class_support"] = {str(int(v)): y.count(v) for v in sorted(set(y))}
                item["scope"] = "Restricted 0/1 missing-annotation count; not full missing requirements"
            else:
                item = binary_details(y, p)
            result[branch][name] = item
    return result


def endpoint_metrics(rows, baseline_index=None):
    eligible = [r for r in rows if r["action_available"]]
    successes = [int((r["action_predicted"] if baseline_index is None else baseline_index(r)) == r["action_target"])
                 for r in eligible]
    by_type = {}
    for row, correct in zip(eligible, successes):
        key = row["candidate_actions"][row["action_target"]]["type"]
        by_type.setdefault(key, []).append(correct)
    return {"eligible": len(eligible), "correct": sum(successes),
            "accuracy": float(np.mean(successes)) if successes else None,
            "by_target_action_type": {k: {"n": len(v), "accuracy": float(np.mean(v))}
                                      for k, v in sorted(by_type.items())},
            "excluded_ASK_ABSTAIN_or_out_of_schema": len(rows) - len(eligible),
            "scope": "Canonical ACT candidate endpoint; not definition of epistemic state"}


@torch.no_grad()
def exact_loss(model, data, device, batch_size=128):
    model.eval()
    sums = {key: 0.0 for key in ("S", "E", "A", "R")}
    counts = {key: 0 for key in sums}
    cfg = default_config()
    for start in range(0, len(data), batch_size):
        b = pad_candidates(data.batch(np.arange(start, min(start+batch_size, len(data))), device))
        _, detail = shared_objective(forward_batch(model, b), b, cfg)
        n = len(b["H"])
        for key, eligible in (("S", n), ("E", n), ("A", detail["active"]["action_rows"])):
            sums[key] += detail[key] * eligible
            counts[key] += eligible
    pairs = data.extras["renderer_pairs"]
    for start in range(0, len(pairs), batch_size):
        chunk = pairs[start:start+batch_size]
        left, right = (pad_candidates(data.batch(chunk[:, side], device)) for side in (0, 1))
        value = renderer_loss(forward_batch(model, left), forward_batch(model, right),
                              left["candidate_mask"], right["candidate_mask"])
        sums["R"] += float(value) * len(chunk)
        counts["R"] += len(chunk)
    components = {k: sums[k] / counts[k] if counts[k] else 0.0 for k in sums}
    components["CF"] = 0.0
    total = sum(cfg["loss"]["lambda_"+k]*v for k,v in components.items())
    if not math.isfinite(total):
        raise ValueError("nonfinite exact evaluation loss")
    return {"total": total, "components": components, "denominators": counts}


@torch.no_grad()
def conditioning(model, data, device):
    model.eval()
    variance, distances = [], []
    delta2, delta1 = [], []
    for start in range(0, len(data), 128):
        b = pad_candidates(data.batch(np.arange(start, min(start+128,len(data))), device))
        out = forward_batch(model, b)
        mask = b["candidate_mask"]
        e = out["e"]
        n = mask.sum(-1)
        mean = e.sum(1) / n[:, None]
        ss = ((e-mean[:,None]).square().sum(-1)*mask).sum(-1)
        var = ss / (n*e.shape[-1])
        # Mean squared distance over all unordered distinct candidate pairs.
        d2 = 2*ss / (n-1)
        variance.extend(var.cpu().tolist()); distances.extend(torch.sqrt(d2).cpu().tolist())
        logits = torch.sigmoid(out["candidate_logits"])
        std = torch.sqrt((((logits-(logits*mask[:,:,None]).sum(1)[:,None]/n[:,None,None]).square())*mask[:,:,None]).sum(1)/n[:,None])
        delta1.extend(std[:,0].cpu().tolist()); delta2.extend(std[:,1].cpu().tolist())
    return {"world_rows": len(variance), "mean_within_world_coordinate_variance": float(np.mean(variance)),
            "median_within_world_coordinate_variance": float(np.median(variance)),
            "mean_pairwise_rms_state_distance": float(np.mean(distances)),
            "collapsed_rows_at_variance_le_1e_8": int(np.sum(np.asarray(variance) <= 1e-8)),
            "candidate_legal_mean_within_world_probability_std": float(np.mean(delta1)),
            "candidate_satisfies_goal_mean_within_world_probability_std": float(np.mean(delta2)),
            "scope": "Candidate conditioning sanity check; variation alone is not epistemic correctness"}


@torch.no_grad()
def renderer_diagnostic(model, data, device):
    model.eval()
    pairs = data.extras["renderer_pairs"]
    global_delta, global_flip, cand_delta, cand_flip = [], [], [], []
    semantic_ss, epistemic_ss = [], []
    endpoint_flips = []
    for start in range(0,len(pairs),64):
        chunk = pairs[start:start+64]
        l,r = (pad_candidates(data.batch(chunk[:,i],device)) for i in (0,1))
        lo,ro = forward_batch(model,l),forward_batch(model,r)
        gp,gq = torch.sigmoid(lo["global_logits"]),torch.sigmoid(ro["global_logits"])
        gp[:,5],gq[:,5] = lo["global_logits"][:,5],ro["global_logits"][:,5]
        cp,cq = torch.sigmoid(lo["candidate_logits"]),torch.sigmoid(ro["candidate_logits"])
        mask = l["candidate_mask"]
        global_delta.extend(torch.abs(gp-gq).cpu().tolist())
        global_flip.extend(((gp>=.5)!=(gq>=.5)).cpu().tolist())
        cand_delta.extend(torch.abs(cp-cq)[mask].cpu().tolist())
        cand_flip.extend(((cp>=.5)!=(cq>=.5))[mask].cpu().tolist())
        semantic_ss.extend((lo["s"]-ro["s"]).square().sum(-1).cpu().tolist())
        epistemic_ss.extend((((lo["e"]-ro["e"]).square().sum(-1)*mask).sum(-1)/mask.sum(-1)).cpu().tolist())
        endpoint_flips.extend((lo["action_logits"].argmax(-1)!=ro["action_logits"].argmax(-1)).cpu().tolist())
    g,c = np.asarray(global_delta),np.asarray(cand_delta)
    gf,cf = np.asarray(global_flip),np.asarray(cand_flip)
    return {"pairs": len(pairs),
            "global": {name: {"mean_absolute_prediction_change": float(g[:,i].mean()),
                              "decision_flip_rate": float(gf[:,i].mean()) if i != 5 else None}
                       for i,name in enumerate(GLOBAL_TARGETS) if i in (1,2,3,5)},
            "candidate": {name: {"mean_absolute_probability_change": float(c[:,i].mean()),
                                 "decision_flip_rate": float(cf[:,i].mean())}
                          for i,name in enumerate(CANDIDATE_TARGETS) if i < 2},
            "semantic_squared_displacement": float(np.mean(semantic_ss)),
            "candidate_mean_squared_displacement": float(np.mean(epistemic_ss)),
            "endpoint_prediction_flip_rate_all_pairs": float(np.mean(endpoint_flips)),
            "scope": "Existing Phase 0 meaning-preserving pairs only; no held S7/S8/S9 coverage"}


def complete_report(model, data, device, prior, initial=None):
    from graft.baseline import prior_predictions
    cfg = default_config()
    rows = predictions(model, data, device, 128)
    report = metrics_for_rows(rows, cfg)
    detail = per_target(rows)
    for branch in ("global","candidate"):
        for name,item in detail[branch].items():
            report[branch][name].update(item)
    report["by_renderer"] = {family: per_target([r for r in rows if r["renderer"]==family])
                             for family in sorted({r["renderer"] for r in rows})}
    report["endpoint"] = endpoint_metrics(rows)
    report["B0_TRAIN_frequency_action_type"] = per_target(prior_predictions(rows,prior))
    # Actual majority candidate priors and global majority; no extra fitted probe.
    flat = prior["candidate_majority"]
    majority = {"global_prior": prior["global_prior"],
                "action_type_prior": [flat for _ in prior["action_type_prior"]]}
    report["B0_TRAIN_majority"] = per_target(prior_predictions(rows, majority))
    train_endpoint_index = prior["endpoint_index_mode"]
    report["endpoint_trivial_first_candidate"] = endpoint_metrics(rows, lambda r: 0)
    report["endpoint_TRAIN_index_mode"] = endpoint_metrics(rows, lambda r: train_endpoint_index if train_endpoint_index<len(r["candidate_actions"]) else 0)
    report["candidate_conditioning"] = conditioning(model,data,device)
    report["renderer"] = renderer_diagnostic(model,data,device)
    report["semantic_separability"] = {"method": "Already-trained typed decoder of s; no new probe",
                                       "DEV_sourceable_global_metrics": detail["global"]}
    report["held_renderers_present"] = []
    report["canonical_world_groups"] = len({r["group_id"] for r in rows})
    if initial is not None:
        report["untrained_reference"] = initial
    return report,rows
