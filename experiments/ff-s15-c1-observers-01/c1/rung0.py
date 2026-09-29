"""Verifies the Rung 0 artifacts C1 depends on against the Rung 0 lock, and loads the saved heads."""
from __future__ import annotations

import json

import numpy as np

from .common import LOCK, LOCK_SHA256, PRIMITIVES, SURFACES, SWEEP, sha256_bytes, sha256_file


def verify(log=lambda *_: None) -> dict:
    """Raises unless every artifact C1 reads matches the lock. Returns the identity record used in bundles and reports."""
    lock_bytes = LOCK.read_bytes()
    if sha256_bytes(lock_bytes) != LOCK_SHA256:
        raise RuntimeError(f"Rung 0 lock changed: {sha256_bytes(lock_bytes)} != {LOCK_SHA256}")
    lock = json.loads(lock_bytes)
    locked = {a["path"].replace("\\", "/").rsplit("/", 1)[-1]: a["sha256"] for a in lock["artifacts"]}
    identity = {"lock_sha256": LOCK_SHA256, "backbone": lock["backbone"], "bank_manifest_sha256": lock["bank"]["manifest_sha256"], "rowmap_sha256": lock["bank"]["rowmap_sha256"]}
    for name, where in (("source-lock.json", SWEEP), ("extraction-seal.json", SWEEP / "features"), ("all-surfaces-prediction-seal.json", SWEEP)):
        actual = sha256_file(where / name)
        if actual != locked[name]:
            raise RuntimeError(f"{name} does not match the lock")
        identity[name] = actual
    if sha256_file(SWEEP / "rowmap.jsonl") != lock["bank"]["rowmap_sha256"]:
        raise RuntimeError("rowmap does not match the lock")
    seal = json.loads((SWEEP / "all-surfaces-prediction-seal.json").read_text(encoding="utf-8"))
    arms = {a["surface"]: a for a in seal["arms"]}
    locked_primitives = {p["name"]: p["sha256"] for p in lock["cached_primitives"]}
    needed = sorted({p for s in SURFACES for p in PRIMITIVES[s]})
    identity["primitives"] = {}
    for name in needed:
        actual = sha256_file(SWEEP / "features" / f"{name}.npy")
        if actual != locked_primitives[name]:
            raise RuntimeError(f"cached primitive {name} does not match the lock")
        identity["primitives"][name] = actual
        log("verified primitive", name)
    identity["surfaces"] = {}
    for surface in SURFACES:
        arm = arms[surface]
        record = {
            "model_sha256": sha256_file(SWEEP / "models" / f"{surface}.npz"), "fit_receipt_sha256": sha256_file(SWEEP / "models" / f"{surface}-fit.json"),
            "prediction_sha256": sha256_file(SWEEP / "predictions" / f"{surface}.jsonl"), "prediction_seal_sha256": sha256_file(SWEEP / "predictions" / f"{surface}-seal.json"),
        }
        for key, value in record.items():
            if value != arm[key]:
                raise RuntimeError(f"{surface}: {key} does not match the sealed sweep")
        identity["surfaces"][surface] = record
        log("verified surface", surface)
    return identity


def load_head(surface: str, head: str) -> dict:
    archive = np.load(SWEEP / "models" / f"{surface}.npz", allow_pickle=False)
    return {"mean": archive["mean"], "scale": archive["scale"], "weight": archive[f"{head}.weight"], "bias": archive[f"{head}.bias"]}
