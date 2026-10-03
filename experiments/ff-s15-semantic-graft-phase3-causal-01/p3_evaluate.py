"""Balanced selection with exact source denominators; renderer correctness, not just agreement."""
from __future__ import annotations

import numpy as np
import torch
from p3_contract import GLOBAL_GROUPS, CANDIDATE_GROUPS, pad_candidates
from p3_objective import source_losses
from graft.model import forward_batch
from graft.contracts import GLOBAL_TARGETS, CANDIDATE_TARGETS


@torch.no_grad()
def selection_metric(model, data, device, prevalence):
    model.eval()
    sums, counts = {}, {}
    for start in range(0, len(data), 128):
        b = pad_candidates(data.batch(np.arange(start, min(start + 128, len(data))), device))
        losses = source_losses(forward_batch(model, b), b, prevalence, selection=True)
        for scope, groups in (("GLOBAL", GLOBAL_GROUPS), ("CANDIDATE", CANDIDATE_GROUPS)):
            for sid, heads in groups.items():
                mask = b[scope.lower() + "_available"][..., heads[0]]
                if scope == "CANDIDATE":
                    mask = mask & b["candidate_mask"]
                n = int(mask.sum())
                sums[sid] = sums.get(sid, 0.) + float(losses[scope][sid]) * n
                counts[sid] = counts.get(sid, 0) + n
    by_source = {sid: sums[sid] / counts[sid] for sid in sums}
    js = float(np.mean([by_source[sid] for sid in GLOBAL_GROUPS]))
    je = float(np.mean([by_source[sid] for sid in CANDIDATE_GROUPS]))
    return {"J_select": .5 * js + .5 * je, "J_S": js, "J_E": je,
            "by_source": by_source, "denominators": counts,
            "weight_prevalence": "frozen TRAIN only; no DEV-derived weights"}


def enrich_metrics(targets, registry):
    for item in registry["registry"]:
        branch = item["scope"].lower()
        metric = targets[branch][item["target_name"]]
        metric.update(canonical_source_id=item["canonical_source_id"],
                      TRAIN_prevalence=item["TRAIN_prevalence"], alias_of=item["alias_of"],
                      source_identity_status=item["source_identity_status"],
                      availability=item["availability"])
        matrix = metric.get("confusion_truth_by_prediction")
        if matrix:
            for value, name in ((0, "negative_class_f1"), (1, "positive_class_f1")):
                tp, fp, fn = matrix[value][value], matrix[1-value][value], matrix[value][1-value]
                metric[name] = 2 * tp / max(1, 2 * tp + fp + fn)
    return targets


def decomposition(left_pred, right_pred, left_truth, right_truth):
    lp, rp, ly, ry = map(np.asarray, (left_pred, right_pred, left_truth, right_truth))
    a, b = lp == ly, rp == ry
    n = len(a)
    counts = {"both_correct": int(np.sum(a & b)), "first_only_correct": int(np.sum(a & ~b)),
              "second_only_correct": int(np.sum(~a & b)), "both_wrong": int(np.sum(~a & ~b)),
              "prediction_disagreement": int(np.sum(lp != rp))}
    return {"n": n, **counts, "rates": {k: v / n if n else None for k, v in counts.items()}}


def pair_correctness(rows, pairs):
    result = {"pairs": len(pairs), "global": {}, "candidate": {}, "action": {}}
    for scope, names in (("global", GLOBAL_TARGETS), ("candidate", CANDIDATE_TARGETS)):
        for i, name in enumerate(names):
            lp, rp, ly, ry = [], [], [], []
            for left, right in pairs:
                a, b = rows[left], rows[right]
                if scope == "global":
                    if not (a["global_available"][i] and b["global_available"][i]):
                        continue
                    p, q = a["global_p"][i], b["global_p"][i]
                    pred = (max(0, np.floor(p + .5)), max(0, np.floor(q + .5))) if i == 5 else (p >= .5, q >= .5)
                    lp.append(pred[0]); rp.append(pred[1])
                    ly.append(a["global_y"][i]); ry.append(b["global_y"][i])
                else:
                    if a["candidate_actions"] != b["candidate_actions"]:
                        continue
                    am, bm = np.asarray(a["candidate_available"]), np.asarray(b["candidate_available"])
                    mask = am[:, i] & bm[:, i]
                    lp.extend((np.asarray(a["candidate_p"])[mask, i] >= .5).tolist())
                    rp.extend((np.asarray(b["candidate_p"])[mask, i] >= .5).tolist())
                    ly.extend(np.asarray(a["candidate_y"])[mask, i].tolist())
                    ry.extend(np.asarray(b["candidate_y"])[mask, i].tolist())
            if ly != ry:
                raise ValueError("Meaning-preserving pair has unequal canonical targets: " + name)
            result[scope][name] = decomposition(lp, rp, ly, ry)
    lp, rp, ly, ry = [], [], [], []
    for left, right in pairs:
        a, b = rows[left], rows[right]
        if a["candidate_actions"] != b["candidate_actions"]:
            continue
        if a["action_available"] and b["action_available"]:
            if a["action_target"] != b["action_target"]:
                raise ValueError("Aligned pair has unequal endpoint truth")
            lp.append(a["action_predicted"]); rp.append(b["action_predicted"])
            ly.append(a["action_target"]); ry.append(b["action_target"])
    result["action"] = decomposition(lp, rp, ly, ry)
    result["action"]["excluded_unavailable_endpoints"] = len(pairs) - len(ly)
    result["unit"] = "global/action: renderer pair; candidate: aligned candidate within pair"
    return result
