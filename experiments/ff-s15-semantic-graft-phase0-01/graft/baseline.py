"""TRAIN-only frequency control: global priors and candidate action-type priors."""
from __future__ import annotations

import copy

import numpy as np

from .contracts import ACTION_TYPES


def prior_model(train):
    arrays = train.arrays
    g = np.zeros(6, np.float64)
    for i in range(6):
        mask = arrays["global_available"][:, i]
        if mask.any():
            g[i] = arrays["global_y"][mask, i].mean()
    c = np.zeros((len(ACTION_TYPES), 7), np.float64)
    types = arrays["actions"][:, 0]
    for i in range(7):
        mask = arrays["candidate_available"][:, i]
        fallback = arrays["candidate_y"][mask, i].mean() if mask.any() else 0
        for action_type in range(len(ACTION_TYPES)):
            m = mask & (types == action_type)
            c[action_type, i] = arrays["candidate_y"][m, i].mean() if m.any() else fallback
    return {"name": "B0_TRAIN_FREQUENCY_ACTION_TYPE", "global_prior": g.tolist(),
            "action_type_prior": c.tolist(), "inputs": "action type only; no H, DEV labels, or world identities"}


def prior_predictions(rows, artifact):
    out = []
    for row in rows:
        item = copy.deepcopy(row)
        item["global_p"] = artifact["global_prior"]
        item["candidate_p"] = [artifact["action_type_prior"][ACTION_TYPES.index(a["type"])]
                               for a in row["candidate_actions"]]
        out.append(item)
    return out
