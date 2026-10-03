from __future__ import annotations

import json

import numpy as np
import torch

from .contracts import CANDIDATE_TARGETS, GLOBAL_TARGETS
from .model import forward_batch


def rank_average(x):
    order = np.argsort(x, kind="stable")
    rank = np.empty(len(x), np.float64)
    i = 0
    while i < len(order):
        j = i + 1
        while j < len(order) and x[order[i]] == x[order[j]]:
            j += 1
        rank[order[i:j]] = (i + j - 1) / 2 + 1
        i = j
    return rank


def measurements(y, p, kind):
    y, p = np.asarray(y, np.float64), np.asarray(p, np.float64)
    if not len(y):
        return {"available": False, "n": 0}
    if kind == "count":
        rounded = np.maximum(0, np.floor(p + 0.5))
        rho = None
        if len(y) > 1 and np.std(y) > 0 and np.std(p) > 0:
            rho = float(np.corrcoef(rank_average(y), rank_average(p))[0, 1])
        return {"available": True, "n": len(y), "mae": float(np.abs(p - y).mean()),
                "exact_count_accuracy": float((rounded == y).mean()), "spearman": rho,
                "calibration_by_true_count": {
                    str(int(v)): {"n": int((y == v).sum()), "mean_prediction": float(p[y == v].mean()),
                                  "mae": float(np.abs(p[y == v] - v).mean())}
                    for v in sorted(set(y))}}
    pred = p >= 0.5
    recalls = [float(pred[y == v].mean()) if v == 1 else float((~pred[y == v]).mean())
               for v in (0, 1) if np.any(y == v)]
    tp = int(np.sum(pred & (y == 1)))
    fp = int(np.sum(pred & (y == 0)))
    fn = int(np.sum(~pred & (y == 1)))
    positives, negatives = int(np.sum(y == 1)), int(np.sum(y == 0))
    auc = None
    if positives and negatives:
        auc = float((rank_average(p)[y == 1].sum() - positives * (positives + 1) / 2) / (positives * negatives))
    calibration = []
    for lo in np.arange(0, 1, 0.1):
        m = (p >= lo) & (p < lo + 0.1 if lo < 0.89 else p <= 1)
        if m.any():
            calibration.append({"lo": float(lo), "n": int(m.sum()),
                                "mean_probability": float(p[m].mean()), "positive_rate": float(y[m].mean())})
    return {"available": True, "n": len(y), "positive_count": positives, "negative_count": negatives,
            "accuracy": float((pred == y).mean()),
            "balanced_accuracy": float(np.mean(recalls)) if positives and negatives else None,
            "f1": 2 * tp / max(2 * tp + fp + fn, 1), "brier": float(np.square(p - y).mean()),
            "auroc": auc, "threshold": 0.5, "calibration": calibration}


def grouped_bootstrap(values, groups, draws=1000, seed=20261001):
    """Bootstrap scalar per-world metrics; all paired renderers resample together."""
    table = {}
    for value, group in zip(values, groups):
        table.setdefault(group, []).append(float(value))
    means = np.asarray([np.mean(v) for _g, v in sorted(table.items())])
    if not len(means):
        return {"n_groups": 0, "interval": None}
    rng = np.random.default_rng(seed)
    samples = np.empty(draws, np.float64)
    for i in range(draws):
        samples[i] = means[rng.integers(0, len(means), len(means))].mean()
    return {"n_groups": len(means), "point_world_mean": float(means.mean()),
            "interval": np.quantile(samples, (0.025, 0.975)).tolist(),
            "draws": draws, "seed": seed, "unit": "canonical world; all paired rows grouped"}


@torch.no_grad()
def predictions(model, data, device, batch_size=64):
    model.eval()
    rows = []
    for start in range(0, len(data), batch_size):
        indices = np.arange(start, min(start + batch_size, len(data)))
        batch = data.batch(indices, device)
        output = forward_batch(model, batch)
        g = output["global_logits"].cpu().numpy()
        c = torch.sigmoid(output["candidate_logits"]).cpu().numpy()
        for b, index in enumerate(indices):
            count = int(batch["candidate_mask"][b].sum())
            gy = batch["global_y"][b].cpu().numpy()
            gm = batch["global_available"][b].cpu().numpy()
            cp = c[b, :count]
            gp = 1 / (1 + np.exp(-np.clip(g[b], -60, 60)))
            gp[5] = g[b, 5]
            rows.append({"world_id": data.rows[index]["world_id"], "group_id": data.rows[index]["group_id"],
                         "renderer": data.rows[index]["renderer"], "global_p": gp.tolist(),
                         "global_y": gy.tolist(), "global_available": gm.tolist(),
                         "candidate_p": cp.tolist(), "candidate_y": batch["candidate_y"][b, :count].cpu().tolist(),
                         "candidate_available": batch["candidate_available"][b, :count].cpu().tolist(),
                         "candidate_actions": data.rows[index]["candidate_actions"],
                         "action_predicted": int(output["action_logits"][b, :count].argmax()),
                         "action_target": int(batch["action_target"][b]),
                         "action_available": bool(batch["action_available"][b])})
    return rows


def metrics_for_rows(rows, config):
    report = {"row_count": len(rows), "world_groups": len({r["group_id"] for r in rows}),
              "global": {}, "candidate": {}}
    for branch, targets in (("global", GLOBAL_TARGETS), ("candidate", CANDIDATE_TARGETS)):
        for i, target in enumerate(targets):
            kind = "count" if branch == "global" and i == 5 else "binary"
            y, p, losses, groups = [], [], [], []
            for row in rows:
                if branch == "global":
                    if not row["global_available"][i]:
                        continue
                    ry, rp = [row["global_y"][i]], [row["global_p"][i]]
                else:
                    available = np.asarray(row["candidate_available"], bool)[:, i]
                    if not available.any():
                        continue
                    ry = np.asarray(row["candidate_y"])[:, i][available].tolist()
                    rp = np.asarray(row["candidate_p"])[:, i][available].tolist()
                y.extend(ry); p.extend(rp)
                loss = np.abs(np.asarray(rp) - ry).mean() if kind == "count" else np.mean((np.asarray(rp) >= .5) == ry)
                losses.append(loss); groups.append(row["group_id"])
            m = measurements(y, p, kind)
            m["grouped_bootstrap_primary"] = grouped_bootstrap(losses, groups, config["evaluation"]["bootstrap_replicates"], config["evaluation"]["bootstrap_seed"])
            m["bootstrap_metric"] = "world_mean_MAE" if kind == "count" else "world_mean_accuracy"
            report[branch][target] = m
    return report


def evaluate(model, data, device, config):
    rows = predictions(model, data, device, config["training"]["batch_size"])
    report = metrics_for_rows(rows, config)
    report["by_renderer"] = {
        family: metrics_for_rows([r for r in rows if r["renderer"] == family], config)
        for family in sorted({r["renderer"] for r in rows})
    }
    paired = {}
    for row in rows:
        paired.setdefault(row["group_id"], []).append(row)
    deltas = []
    for variants in paired.values():
        if len(variants) > 1:
            reference = variants[0]
            for row in variants[1:]:
                mask = np.asarray(row["global_available"], bool)
                deltas.append(float(np.mean(np.abs(np.asarray(row["global_p"])[mask] - np.asarray(reference["global_p"])[mask]))))
    report["paired_renderer_global_prediction_change"] = {
        "pairs": len(deltas), "mean_absolute_change": float(np.mean(deltas)) if deltas else None,
        "note": "diagnostic magnitude; count and probability heads have different units",
    }
    report["held_renderers_present"] = sorted(set(config["evaluation"]["held_renderers"]) & set(report["by_renderer"]))
    endpoints = [r for r in rows if r["action_available"]]
    report["action_endpoint"] = {"eligible": len(endpoints),
                                 "accuracy": float(np.mean([r["action_predicted"] == r["action_target"] for r in endpoints])) if endpoints else None,
                                 "scope": "Canonical eligible ACT actions only; not epistemic-state definition"}
    report["renderer_state_invariance"] = state_pair_evaluation(model, data, device)
    report["candidate_support_contrast"] = {"eligible_pairs": 0, "status": "UNAVAILABLE_NO_CANONICAL_SUPPORT_PAIRS"}
    return report, rows


@torch.no_grad()
def state_pair_evaluation(model, data, device):
    from .objective import renderer_loss
    total, count = 0.0, 0
    pairs = data.extras["renderer_pairs"]
    for start in range(0, len(pairs), 32):
        chunk = pairs[start:start+32]
        left, right = data.batch(chunk[:, 0], device), data.batch(chunk[:, 1], device)
        loss = renderer_loss(forward_batch(model, left), forward_batch(model, right), left["candidate_mask"], right["candidate_mask"])
        total += float(loss) * len(chunk); count += len(chunk)
    return {"pairs": count, "mean_squared_state_invariance_loss": total / count if count else None,
            "scope": "Within-fabric meaning-preserving pairs, identity-aligned candidates; no inter-fabric coordinate comparison"}


def runtime_envelopes(rows, artifact_sha256, representation_id, abi):
    """Runtime export excludes labels and unavailable heads; slots are not named dimensions."""
    if not artifact_sha256 or not representation_id:
        raise ValueError("attached trained artifact and representation identity required")
    for row in rows:
        global_estimates = {}
        candidate_estimates = []
        for i, target in enumerate(abi["global"]):
            if not target["available"]:
                continue
            raw = row["global_p"][i]
            value = max(0, int(np.floor(raw + .5))) if target["kind"] == "count" else float(raw)
            global_estimates["estimate.semantic." + target["name"]] = {
                "value": value, "raw_diagnostic": raw, "provenance_class": "MODEL_ESTIMATE",
                "runtime_availability": "AVAILABLE", "target_meaning": target["meaning"],
            }
        for j, action in enumerate(row["candidate_actions"]):
            estimates = {"estimate.candidate." + target["name"]: {
                "value": row["candidate_p"][j][i], "provenance_class": "MODEL_ESTIMATE",
                "runtime_availability": "AVAILABLE", "target_meaning": target["meaning"],
            } for i, target in enumerate(abi["candidate"]) if target["available"]}
            candidate_estimates.append({"candidate": action, "estimates": estimates})
        envelope = {"world_id": row["world_id"], "graft_artifact_sha256": artifact_sha256,
               "representation_id": representation_id, "semantic_estimates": global_estimates,
               "candidate_estimates": candidate_estimates,
               "unavailable_global_targets": [t["name"] for t in abi["global"] if not t["available"]],
               "unavailable_candidate_targets": [t["name"] for t in abi["candidate"] if not t["available"]]}
        if "action_predicted" in row:
            envelope["estimate.action.candidate_index"] = {
                "value": row["action_predicted"], "provenance_class": "MODEL_ESTIMATE",
                "runtime_availability": "AVAILABLE", "scope": "Endpoint prediction, not transport or System1.5 authorization"}
        yield envelope
