"""C0 records for the ASK observers and the ASK-bearing policies."""
from __future__ import annotations

import numpy as np

from .common import ACTIONS, LABELS, LAYER, PRIMITIVES, c1policy, canon, model, sha256_bytes


def cmp(signal, op, value):
    return {"cmp": {"signal": signal, "op": op, "value": value}}


def contract(kind: str) -> dict:
    name = "bank_should_ask" if kind == "linear" else "bank_should_ask_mlp"
    return model.seal({
        "schema": "S15_DECISION_CONTRACT_V1", "name": name, "version": 1, "decision_type": "CHOICE", "question": name,
        "candidate_schema": {"kind": "LABELS", "labels": list(LABELS)}, "output_schema": {"kind": "SIMPLEX", "labels": list(LABELS), "scale_ppm": 1_000_000},
        "abstention_allowed": False, "unknown_allowed": False, "cost_class": "T1_LINEAR" if kind == "linear" else "T2_MLP", "authority_class": "ESCALATION_ONLY",
    })


def bundle(identity: dict, contract_record: dict, surface: str, kind: str, weights: dict, scaler: dict, dimensions: int, extra_sources: list) -> dict:
    arms = identity["surfaces"][surface]
    sources = {arms["model_sha256"], identity["lock_sha256"], identity["extraction-seal.json"], *extra_sources}
    sources |= {identity["primitives"][p] for p in PRIMITIVES[surface]}
    blob = b"".join(np.ascontiguousarray(weights[k], "<f4").tobytes() for k in sorted(weights))
    return model.seal({
        "schema": "S15_OBSERVER_BUNDLE_V1", "name": f"bank_{surface}_should_ask_{kind}", "bundle_version": 1,
        "backbone": {"model_id": identity["backbone"]["name"], "revision": "9d2be55"},
        "representation": {"layer": LAYER[surface], "surface": surface, "dimensions": dimensions},
        "normalization": {"center_hash": "sha256:" + sha256_bytes(np.ascontiguousarray(scaler["mean"], "<f4").tobytes()), "scale_hash": "sha256:" + sha256_bytes(np.ascontiguousarray(scaler["scale"], "<f4").tobytes())},
        "head": {"architecture": "linear" if kind == "linear" else "mlp256", "weights_hash": "sha256:" + sha256_bytes(blob), "class_order": list(LABELS)},
        "calibration": {"method": "NONE", "parameters_hash": "sha256:" + sha256_bytes(b"s15-ask-calibration-none-v1")},
        "decision_contract_id": contract_record["contract_id"], "training_identity": "bank_v1_train_ask_seed_20260929",
        "source_hashes": sorted("sha256:" + s for s in sources),
    })


def _costs(cost_class_units: dict) -> dict:
    return {"backbone_units": 20, "cost_class_units": cost_class_units,
            "label_units": {"DIRECT": 0, "USE_OBSERVER": 0, "USE_OBSERVER_SET": 0, "USE_LARGER_MODEL": 300, "USE_REASONER": 3000, "ASK_HUMAN": 10000, "ABSTAIN": 0}}


def ask_rule(alias: str, label: str, threshold) -> dict:
    if threshold is None:  # omitted rule: keep the policy valid with a rule that can never be TRUE (its fact is never supplied)
        return {"rule_id": "R0-never", "when": cmp("obs.ask_never_supplied", "eq", True), "then": "USE_LARGER_MODEL", "reason": "NEVER_FIRES", "confidence_signal": None}
    signal = f"{alias}.p.{label}"
    return {"rule_id": "R0-ask", "when": cmp(signal, "ge", threshold), "then": "ASK_HUMAN", "reason": "ASK_OBSERVER", "confidence_signal": signal}


def ask_only_policy(name: str, alias: str, bundle_record: dict, label: str, threshold, cost_class: str) -> dict:
    """One observer, one rule: ask when its P(<label>) reaches the threshold; otherwise leave the case unresolved (USE_LARGER_MODEL)."""
    return model.seal({
        "schema": "S15_RUNTIME_POLICY_V1", "name": name, "policy_revision": 1, "actions": sorted(ACTIONS),
        "observers": [{"alias": alias, "bundle_id": bundle_record["bundle_id"]}], "escalation_rules": [ask_rule(alias, label, threshold)],
        "authority_rules": [{"rule_id": "A1-allow-granted", "when": {"all": [cmp("authority.granted", "eq", True)]}, "effect": "ALLOW", "reason_code": "GRANTED", "declared_neural_inputs": []}],
        "default_escalation": "USE_LARGER_MODEL", "on_incomplete_evidence": "ASK_HUMAN", "on_require_escalation": "ASK_HUMAN", "default_authority": "DENY",
        "costs": _costs({cost_class: 1}),
    })


def combined_policy(surface: str, tag: str, c1_thresholds: dict, c1_bundles: dict, ask_bundle: dict, ask_threshold, cost_class: str) -> dict:
    """The C1 controller (frozen thresholds) with the ASK rule placed first."""
    base = c1policy.build(surface, tag, c1_thresholds, c1_bundles)
    body = dict(base)
    body["name"] = f"ask_{surface}_{tag}"
    body["observers"] = sorted(base["observers"] + [{"alias": "ask", "bundle_id": ask_bundle["bundle_id"]}], key=lambda e: e["alias"])
    rules = [r for r in base["escalation_rules"] if r["rule_id"] != "R0-never"]
    body["escalation_rules"] = [ask_rule("ask", "SHOULD_ASK", ask_threshold)] + rules
    body["costs"] = _costs({"T1_LINEAR": 1, "T2_MLP": 3})
    return model.seal(canon.without(body, "policy_id") | {"schema": "S15_RUNTIME_POLICY_V1"})


def vector(world_id: str, entries: dict, source: str) -> dict:
    """entries: bundle_id -> ppm list."""
    listed = [{"bundle_id": b, "probabilities_ppm": [int(v) for v in ppm]} for b, ppm in entries.items()]
    return model.seal({"schema": "S15_DECISION_VECTOR_V1", "observation_id": world_id.replace(":", "-").replace("@", "_at_"), "producer": {"kind": "PRERECORDED", "source": source},
                       "entries": sorted(listed, key=lambda e: e["bundle_id"])})
