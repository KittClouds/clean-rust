"""Phase 4A canonical-candidate identity preflight; reads TRAIN/DEV only."""
from __future__ import annotations

from collections import Counter
import numpy as np
from p4_contract import P2_OUTPUT, sha_file, write_json


def audit_candidates(train, dev):
    p2_audit = __import__("json").loads((P2_OUTPUT / "CANDIDATE-AUDIT.json").read_text())
    if not p2_audit.get("retain_every_canonical_candidate"):
        raise ValueError("Phase 2 did not certify exhaustive canonical candidates")
    out = {"m_max": 28, "retain_every_canonical_candidate": True,
           "P2_candidate_audit_sha256": sha_file(P2_OUTPUT / "CANDIDATE-AUDIT.json"),
           "P2_Phase1_truncated_candidates": p2_audit.get("Phase1_truncated_candidates"),
           "populations": {}}
    for name, data in (("TRAIN", train), ("DEV", dev)):
        counts = np.diff(data.arrays["offsets"])
        histogram = Counter(map(int, counts))
        out["populations"][name] = {"rows": len(data), "maximum": int(counts.max()),
            "total_candidates": int(counts.sum()),
            "candidate_count_histogram": {str(k): v for k, v in sorted(histogram.items())},
            "aligned_renderer_pairs": int(len(data.extras["renderer_pairs"])),
            "offsets_sha256": sha_file(data.folder / "offsets.npy"),
            "actions_sha256": sha_file(data.folder / "actions.npy")}
        if int(counts.max()) != 28:
            raise ValueError(f"{name} canonical maximum is not exactly 28")
        if np.any(counts > 28):
            raise ValueError(f"{name} contains a candidate beyond the frozen 28-slot contract")
    out["maximum"] = max(v["maximum"] for v in out["populations"].values())
    out["truncated_candidates"] = 0
    if p2_audit.get("Phase1_truncated_candidates") != 0:
        raise ValueError("Phase 1 truncation audit does not support this carry-forward")
    out["truncated_candidates_in_Phase4A"] = 0
    out["status"] = "EXHAUSTIVE_28_VERIFIED"
    write_json(__import__("p4_contract").OUTPUT / "CANDIDATE-AUDIT.json", out)
    return out
