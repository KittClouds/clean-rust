"""The C1 controller as a C0 RuntimePolicy: fixed rule structure, fitted thresholds."""
from __future__ import annotations

from .common import ACTIONS, model


def _cmp(signal, op, value):
    return {"cmp": {"signal": signal, "op": op, "value": value}}


def build(surface: str, tag: str, thresholds: dict, bundles: dict) -> dict:
    """`thresholds`: abstain/ask/act -> ppm or None (rule omitted). `bundles`: '<surface>_<head>' -> sealed ObserverBundle."""
    dec_bundle, act_bundle = bundles[f"{surface}_decision"], bundles[f"{surface}_action_type"]
    rules = []
    if thresholds.get("abstain") is not None:
        rules.append({"rule_id": "R1-abstain", "when": {"all": [_cmp("dec.top_label", "eq", "ABSTAIN"), _cmp("dec.top_ppm", "ge", thresholds["abstain"])]},
                      "then": "ABSTAIN", "reason": "DECISION_ABSTAIN", "confidence_signal": "dec.top_ppm"})
    if thresholds.get("ask") is not None:
        rules.append({"rule_id": "R2-ask", "when": {"all": [_cmp("dec.top_label", "eq", "ASK"), _cmp("dec.top_ppm", "ge", thresholds["ask"])]},
                      "then": "ASK_HUMAN", "reason": "DECISION_ASK", "confidence_signal": "dec.top_ppm"})
    if thresholds.get("act") is not None:
        rules.append({"rule_id": "R3-act", "when": {"all": [_cmp("dec.top_label", "eq", "ACT"), _cmp("dec.top_ppm", "ge", thresholds["act"]), _cmp("act.top_ppm", "ge", thresholds["act"])]},
                      "then": "USE_OBSERVER", "reason": "CONFIDENT_ACT", "confidence_signal": "act.top_ppm", "propose": {"from": "act"}})
    if not rules:  # every rule was omitted: keep the policy valid with a rule that can never be TRUE (its fact is never supplied)
        rules.append({"rule_id": "R0-never", "when": _cmp("obs.c1_never_supplied", "eq", True), "then": "USE_LARGER_MODEL", "reason": "NEVER_FIRES", "confidence_signal": None})
    return model.seal({
        "schema": "S15_RUNTIME_POLICY_V1", "name": f"c1_{surface}_{tag}", "policy_revision": 1, "actions": sorted(ACTIONS),
        "observers": sorted([{"alias": "act", "bundle_id": act_bundle["bundle_id"]}, {"alias": "dec", "bundle_id": dec_bundle["bundle_id"]}], key=lambda e: e["alias"]),
        "escalation_rules": rules,
        "authority_rules": [{"rule_id": "A1-allow-granted", "when": {"all": [_cmp("authority.granted", "eq", True)]}, "effect": "ALLOW", "reason_code": "GRANTED", "declared_neural_inputs": []}],
        "default_escalation": "USE_LARGER_MODEL", "on_incomplete_evidence": "ASK_HUMAN", "on_require_escalation": "ASK_HUMAN", "default_authority": "DENY",
        "costs": {"backbone_units": 20, "cost_class_units": {"T1_LINEAR": 1},
                  "label_units": {"DIRECT": 0, "USE_OBSERVER": 0, "USE_OBSERVER_SET": 0, "USE_LARGER_MODEL": 300, "USE_REASONER": 3000, "ASK_HUMAN": 10000, "ABSTAIN": 0}},
    })
