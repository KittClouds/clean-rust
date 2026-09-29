"""Rebuilds the Rung 0 NLI head outputs on DEV from cached features (no LM, no TEST rows) and reads the true NLI label of each DEV row."""
from __future__ import annotations

import json

import numpy as np

from .common import BANK, DEV_ROWS, NLI_LABELS, SWEEP, c1obs, rung0


def compute(surface: str) -> np.ndarray:
    """float64 softmax over (ENTAILED, CONTRADICTED, UNKNOWN), DEV rows only."""
    x = c1obs._features(surface).astype(np.float64)
    h = rung0.load_head(surface, "nli")
    z = (x - h["mean"].astype(np.float64)) / h["scale"].astype(np.float64)
    logits = z @ h["weight"].astype(np.float64).T + h["bias"].astype(np.float64)
    e = np.exp(logits - logits.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


def reconstruction_gate(surface: str, probabilities: np.ndarray) -> dict:
    """Recomputed top NLI labels must equal the sealed Rung 0 predictions on every DEV row; confidence within 1e-5."""
    sealed = []
    with (SWEEP / "predictions" / f"{surface}.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            if index >= DEV_ROWS:
                break
            sealed.append(json.loads(line))
    top = probabilities.argmax(axis=1)
    matches = sum(NLI_LABELS[top[i]] == sealed[i]["nli"] for i in range(DEV_ROWS))
    worst = max(abs(float(probabilities[i, top[i]]) - sealed[i]["nli_confidence"]) for i in range(DEV_ROWS))
    result = {"label_matches": matches, "rows": DEV_ROWS, "max_confidence_difference": worst}
    if sealed[0]["split"] != "DEV" or matches != DEV_ROWS or worst >= 1e-5:
        raise RuntimeError(f"NLI reconstruction gate failed for {surface}: {result}")
    return result


def true_nli_codes(expected_ids: list) -> np.ndarray:
    """True NLI label per DEV row: 0 ENTAILED, 1 CONTRADICTED, 2 UNKNOWN, -1 no label. Row order is checked against C1's DEV ids."""
    codes = np.full(DEV_ROWS, -1, dtype=np.int8)
    with (BANK / "inputs" / "DEV.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            row = json.loads(line)
            if row["world_id"] != expected_ids[index]:
                raise RuntimeError(f"DEV row {index} does not line up with C1's rows")
            label = row["labels"].get("nli")
            if label is not None:
                codes[index] = NLI_LABELS.index(label)
    if index + 1 != DEV_ROWS:
        raise RuntimeError("DEV row count mismatch")
    return codes
