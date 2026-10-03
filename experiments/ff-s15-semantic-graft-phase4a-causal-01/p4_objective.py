"""Phase 4A deep supervision, using the frozen P2-CONSIST loss at each state depth."""
from __future__ import annotations

import torch
from p2_objective import objective as p2_objective


def recurrent_objective(outputs, batch, reference_std, renderer_outputs=None):
    if len(outputs) != 5:
        raise ValueError("T=4 requires state outputs Z0..Z4")
    renderer_by_depth = [None] * 5
    if renderer_outputs is not None:
        left, right, left_batch, right_batch = renderer_outputs
        for depth in range(1, 5):
            renderer_by_depth[depth] = (left[depth], right[depth], left_batch, right_batch)
    terms = [None]
    for depth in range(1, 5):
        value, detail = p2_objective("P2-CONSIST", outputs[depth], batch,
                                     reference_std, renderer_by_depth[depth])
        terms.append((value, detail))
    final = terms[4][0]
    intermediate = torch.stack([terms[t][0] for t in (1, 2, 3)]).mean()
    total = final + .25 * intermediate
    return total, {"L_final_Z4": float(final.detach()),
                   "L_intermediate_mean_Z1_Z3": float(intermediate.detach()),
                   "L_recurrent": float(total.detach()),
                   "depth_terms": {str(t): terms[t][1] for t in range(1, 5)}}
