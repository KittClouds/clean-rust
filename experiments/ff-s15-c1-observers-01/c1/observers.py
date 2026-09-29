"""Rebuilds the Rung 0 heads' outputs on DEV from cached features (no language model, no TEST rows), and mints C0 records."""
from __future__ import annotations

import json

import numpy as np

from . import rung0
from .common import (ACTIONS, DECISIONS, DEV_ROWS, DEV_START, DEV_STOP, HEADS, LAYER, PRIMITIVES, SURFACES, SWEEP, canon, model, sha256_bytes)


def _features(surface: str) -> np.ndarray:
    def part(name):
        return np.asarray(np.load(SWEEP / "features" / f"{name}.npy", mmap_mode="r", allow_pickle=False)[DEV_START:DEV_STOP], dtype=np.float32)

    if surface == "middle_plus_final":
        return np.concatenate((part("middle_final"), part("final_token")), axis=1)
    if surface == "final_plus_mean":
        return np.concatenate((part("final_token"), part("full_mean")), axis=1)
    return part(PRIMITIVES[surface][0])


def compute(surface: str) -> dict:
    """float64 softmax probabilities per head, DEV rows only."""
    x = _features(surface).astype(np.float64)
    out = {}
    for head in HEADS:
        h = rung0.load_head(surface, head)
        z = (x - h["mean"].astype(np.float64)) / h["scale"].astype(np.float64)
        logits = z @ h["weight"].astype(np.float64).T + h["bias"].astype(np.float64)
        e = np.exp(logits - logits.max(axis=1, keepdims=True))
        out[head] = e / e.sum(axis=1, keepdims=True)
    return out


def reconstruction_gate(surface: str, probabilities: dict) -> dict:
    """Recomputed top labels must equal the sealed Rung 0 predictions on every DEV row; confidence within 1e-5."""
    sealed = []
    with (SWEEP / "predictions" / f"{surface}.jsonl").open(encoding="utf-8") as source:
        for index, line in enumerate(source):
            if index >= DEV_ROWS:
                break
            sealed.append(json.loads(line))
    result = {}
    for head, classes in HEADS.items():
        p = probabilities[head]
        top = p.argmax(axis=1)
        label_matches = sum(classes[top[i]] == sealed[i][head] for i in range(DEV_ROWS))
        worst = max(abs(float(p[i, top[i]]) - sealed[i][head + "_confidence"]) for i in range(DEV_ROWS))
        result[head] = {"label_matches": label_matches, "rows": DEV_ROWS, "max_confidence_difference": worst}
        if sealed[0]["split"] != "DEV" or label_matches != DEV_ROWS or worst >= 1e-5:
            raise RuntimeError(f"reconstruction gate failed for {surface}/{head}: {result[head]}")
    return result


def quantize(probabilities: np.ndarray) -> np.ndarray:
    return np.array([canon.quantize_probabilities([float(v) for v in row]) for row in probabilities], dtype=np.int32)


# ---- C0 records for the real observers

def contracts() -> dict:
    def contract(name, labels, authority_class):
        return model.seal({
            "schema": "S15_DECISION_CONTRACT_V1", "name": name, "version": 1, "decision_type": "CHOICE", "question": name,
            "candidate_schema": {"kind": "LABELS", "labels": list(labels)}, "output_schema": {"kind": "SIMPLEX", "labels": list(labels), "scale_ppm": 1_000_000},
            "abstention_allowed": name == "bank_decision", "unknown_allowed": False, "cost_class": "T1_LINEAR", "authority_class": authority_class,
        })

    return {"bank_decision": contract("bank_decision", DECISIONS, "ESCALATION_ONLY"), "bank_action_type": contract("bank_action_type", ACTIONS, "PROPOSES_ACTION")}


def bundles(identity: dict, contract_records: dict) -> dict:
    """One ObserverBundle per (surface, head), bound to the Rung 0 lock through its source hashes."""
    none_calibration = "sha256:" + sha256_bytes(b"s15-c1-calibration-none-v1")
    out = {}
    for surface in SURFACES:
        for head, labels in HEADS.items():
            h = rung0.load_head(surface, head)
            contract = contract_records[f"bank_{head}"]
            arms = identity["surfaces"][surface]
            sources = {arms["model_sha256"], arms["fit_receipt_sha256"], arms["prediction_seal_sha256"], identity["lock_sha256"], identity["extraction-seal.json"]}
            sources |= {identity["primitives"][p] for p in PRIMITIVES[surface]}
            weights = np.ascontiguousarray(h["weight"], "<f4").tobytes() + np.ascontiguousarray(h["bias"], "<f4").tobytes()
            out[f"{surface}_{head}"] = model.seal({
                "schema": "S15_OBSERVER_BUNDLE_V1", "name": f"bank_{surface}_{head}", "bundle_version": 1,
                "backbone": {"model_id": identity["backbone"]["name"], "revision": "9d2be55"},
                "representation": {"layer": LAYER[surface], "surface": surface, "dimensions": int(h["weight"].shape[1])},
                "normalization": {"center_hash": "sha256:" + sha256_bytes(np.ascontiguousarray(h["mean"], "<f4").tobytes()), "scale_hash": "sha256:" + sha256_bytes(np.ascontiguousarray(h["scale"], "<f4").tobytes())},
                "head": {"architecture": "linear", "weights_hash": "sha256:" + sha256_bytes(weights), "class_order": list(labels)},
                "calibration": {"method": "NONE", "parameters_hash": none_calibration},
                "decision_contract_id": contract["contract_id"], "training_identity": "bank_v1_train_seed_20260929",
                "source_hashes": sorted("sha256:" + s for s in sources),
            })
    return out
