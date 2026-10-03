"""Independent-source balanced loss; consistency/variance functions are frozen imports."""
from __future__ import annotations

import torch
from torch.nn import functional as F
from p3_contract import GLOBAL_GROUPS, CANDIDATE_GROUPS
from p2_objective import pair_components, variance_loss
from graft.objective import action_loss


def balanced_bce(logits, y, prevalence):
    if not 0 < prevalence < 1:
        raise ValueError("Balanced source requires both TRAIN classes")
    # softplus implements log-sigmoid without probability underflow or prevalence clipping.
    return .5 * (y / prevalence * F.softplus(-logits)
                 + (1 - y) / (1 - prevalence) * F.softplus(logits))


def source_losses(output, batch, prevalences, selection=False):
    result = {"GLOBAL": {}, "CANDIDATE": {}}
    for scope, groups in (("GLOBAL", GLOBAL_GROUPS), ("CANDIDATE", CANDIDATE_GROUPS)):
        prefix = scope.lower() if scope == "GLOBAL" else "candidate"
        logits = output[prefix + "_logits"]
        labels, available = batch[prefix + "_y"], batch[prefix + "_available"]
        if scope == "CANDIDATE":
            available = available & batch["candidate_mask"][:, :, None]
        for sid, heads in groups.items():
            values = []
            for index in heads:
                if selection and scope == "GLOBAL" and index == 5:
                    continue  # count proxy cannot vote a second time in selection
                mask = available[..., index]
                if not mask.any():
                    raise ValueError("Frozen source has no batch supervision: " + sid)
                x, y = logits[..., index][mask], labels[..., index][mask]
                loss = (F.smooth_l1_loss(x, y) if scope == "GLOBAL" and index == 5
                        else balanced_bce(x, y, prevalences[sid]).mean())
                values.append(loss)
            result[scope][sid] = torch.stack(values).mean()
    return result


def objective(output, batch, reference_std, prevalences, renderer=None):
    groups = source_losses(output, batch, prevalences)
    S = torch.stack(list(groups["GLOBAL"].values())).mean()
    E = torch.stack(list(groups["CANDIDATE"].values())).mean()
    A = action_loss(output, batch)
    zero = S * 0 + E * 0 + A * 0
    ps = pe = pa = zero
    if renderer is not None:
        parts = pair_components(*renderer)
        ps, pe, pa = (parts[k].mean() for k in ("pair_S", "pair_E", "pair_A"))
    pair = ps + pe + pa
    var = variance_loss(output["s"], reference_std)
    total = S + E + .5 * A + .25 * pair + .05 * var
    values = {"S": S, "E": E, "A": A, "CF": zero, "pair": pair,
              "pair_S": ps, "pair_E": pe, "pair_A": pa, "var": var}
    return total, {k: float(v.detach()) for k, v in values.items()}
