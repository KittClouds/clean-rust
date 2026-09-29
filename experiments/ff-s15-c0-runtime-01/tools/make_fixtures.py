"""Builds fixtures/: contracts, observer bundles, a runtime policy and 14 prerecorded cases.

  python tools/make_fixtures.py            write fixtures (content-derived ids, canonical bytes)
  python tools/make_fixtures.py --check    fail if the committed fixtures differ from a fresh build

The observers here are FIXTURES: prerecorded outputs of imaginary heads, so C0 can be tested with
no model at all. Their bundle hashes are hashes of fixture strings, not of real weights. C1 replaces
them with bundles bound to the real Rung 0 observers.

Cases are chosen so that all seven escalation tiers and every authority outcome are reached.
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s15 import canon, model  # noqa: E402

OUT = ROOT / "fixtures"
PPM = 1_000_000
ESC = model.ESCALATION_LABELS


def h(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("ascii")).hexdigest()


def contract(name, decision_type, labels, cost_class, authority_class, abstention=False, supplied=False, independent=False):
    record = {
        "schema": "S15_DECISION_CONTRACT_V1", "name": name, "version": 1, "decision_type": decision_type, "question": name,
        "candidate_schema": {"kind": "OBSERVATION_SUPPLIED"} if supplied else {"kind": "LABELS", "labels": labels},
        "output_schema": {"kind": "INDEPENDENT" if independent else "SIMPLEX", "labels": labels, "scale_ppm": PPM},
        "abstention_allowed": abstention, "unknown_allowed": "UNKNOWN" in labels, "cost_class": cost_class, "authority_class": authority_class,
    }
    return model.seal(record)


def bundle(name, contract_record, surface, layer, dimensions, architecture):
    record = {
        "schema": "S15_OBSERVER_BUNDLE_V1", "name": name, "bundle_version": 1,
        "backbone": {"model_id": "prerecorded-fixture", "revision": "fixture-0"},
        "representation": {"layer": layer, "surface": surface, "dimensions": dimensions},
        "normalization": {"center_hash": h(f"fixture:{name}:center"), "scale_hash": h(f"fixture:{name}:scale")},
        "head": {"architecture": architecture, "weights_hash": h(f"fixture:{name}:weights"), "class_order": contract_record["output_schema"]["labels"]},
        "calibration": {"method": "NONE", "parameters_hash": h(f"fixture:{name}:calibration")},
        "decision_contract_id": contract_record["contract_id"], "training_identity": f"fixture:{name}",
        "source_hashes": sorted([h(f"fixture:{name}:source-a"), h(f"fixture:{name}:source-b")]),
    }
    return model.seal(record)


def build():
    contracts = {
        "next_action": contract("next_action", "CHOICE", ["search", "read", "edit", "test", "ask"], "T1_LINEAR", "PROPOSES_ACTION"),
        "applicable": contract("applicable", "APPLICABILITY", ["YES", "NO", "UNKNOWN"], "T1_LINEAR", "ADVISORY", supplied=True),
        "abstain": contract("abstain", "ABSTENTION", ["NONE", "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "AMBIGUOUS_REFERENCE", "UNKNOWN_ENTITY"], "T1_LINEAR", "ESCALATION_ONLY", abstention=True),
        "risk": contract("risk", "ORDINAL", ["low", "medium", "high"], "T2_MLP", "ADVISORY"),
        "entities": contract("entities", "MULTI_CHOICE", ["function", "file", "test", "error"], "T1_LINEAR", "ADVISORY", independent=True),
        "should_think": contract("should_think", "ESCALATION", list(ESC), "T2_MLP", "ESCALATION_ONLY"),
    }
    bundles = {
        "router_a": bundle("router_a", contracts["next_action"], "middle_plus_final", "mid_final", 2048, "linear"),
        "router_b": bundle("router_b", contracts["next_action"], "final_plus_mean", "final_mean", 2048, "linear"),
        "applicability": bundle("applicability", contracts["applicable"], "layer_m4_final", "m4", 1024, "linear"),
        "abstain": bundle("abstain", contracts["abstain"], "full_mean", "mean", 1024, "linear"),
        "risk": bundle("risk", contracts["risk"], "final_plus_mean", "final_mean", 2048, "mlp256"),
        "entities": bundle("entities", contracts["entities"], "final_only", "final", 1024, "linear"),
    }
    granted_is_true = {"cmp": {"signal": "authority.granted", "op": "eq", "value": True}}
    cmp = lambda signal, op, value: {"cmp": {"signal": signal, "op": op, "value": value}}  # noqa: E731
    policy = model.seal({
        "schema": "S15_RUNTIME_POLICY_V1", "name": "fixture_policy", "policy_revision": 1,
        "actions": ["search", "read", "edit", "test"],
        "observers": sorted(
            [{"alias": a, "bundle_id": bundles[b]["bundle_id"]} for a, b in
             [("router", "router_a"), ("router_b", "router_b"), ("applic", "applicability"), ("abstain", "abstain"), ("risk", "risk"), ("entities", "entities")]],
            key=lambda e: e["alias"]),
        "escalation_rules": [
            {"rule_id": "E1-direct-cache", "when": cmp("obs.cache_hit", "eq", True), "then": "DIRECT", "reason": "CACHE_HIT",
             "confidence_signal": None, "propose": {"literal": "read"}},
            {"rule_id": "E2-abstain", "when": cmp("abstain.p.NONE", "lt", 500000), "then": "ABSTAIN", "reason": "ABSTAIN_OBSERVER",
             "confidence_signal": "abstain.top_ppm"},
            {"rule_id": "E3-ask", "when": {"all": [cmp("router.top_label", "eq", "ask"), cmp("router.top_ppm", "ge", 600000)]}, "then": "ASK_HUMAN",
             "reason": "ROUTER_SAYS_ASK", "confidence_signal": "router.top_ppm"},
            {"rule_id": "E4-disagree", "when": {"disagree": ["router", "router_b"]}, "then": "USE_LARGER_MODEL", "reason": "OBSERVERS_DISAGREE",
             "confidence_signal": None},
            {"rule_id": "E5-high-risk", "when": cmp("risk.top_label", "eq", "high"), "then": "USE_REASONER", "reason": "HIGH_RISK",
             "confidence_signal": "risk.top_ppm"},
            {"rule_id": "E6-confident", "when": {"all": [cmp("router.top_ppm", "ge", 850000), cmp("applic.p.YES", "ge", 800000), cmp("abstain.p.NONE", "ge", 800000)]},
             "then": "USE_OBSERVER", "reason": "CONFIDENT_SINGLE_OBSERVER", "confidence_signal": "router.top_ppm", "propose": {"from": "router"}},
            {"rule_id": "E7-agree", "when": {"all": [{"agree": ["router", "router_b"]}, cmp("router.top_ppm", "ge", 600000), cmp("applic.p.YES", "ge", 600000)]},
             "then": "USE_OBSERVER_SET", "reason": "OBSERVERS_AGREE", "confidence_signal": "router.top_ppm", "propose": {"from": "router"}},
        ],
        "authority_rules": [
            {"rule_id": "A1-edit-needs-green-tests", "when": {"all": [cmp("action.name", "eq", "edit"), cmp("authority.flag.tests_green", "ne", True)]},
             "effect": "REQUIRE_ESCALATION", "reason_code": "EDIT_NEEDS_GREEN_TESTS", "declared_neural_inputs": []},
            {"rule_id": "A2-medium-risk-edit", "when": {"all": [cmp("action.name", "eq", "edit"), cmp("risk.top_label", "eq", "medium")]},
             "effect": "REQUIRE_ESCALATION", "reason_code": "MEDIUM_RISK_EDIT", "declared_neural_inputs": ["risk.top_label"]},
            {"rule_id": "A3-allow-granted", "when": {"all": [granted_is_true]}, "effect": "ALLOW", "reason_code": "GRANTED", "declared_neural_inputs": []},
        ],
        "default_escalation": "USE_LARGER_MODEL", "on_incomplete_evidence": "ASK_HUMAN", "on_require_escalation": "ASK_HUMAN", "default_authority": "DENY",
        "costs": {
            "backbone_units": 20, "cost_class_units": {"T1_LINEAR": 1, "T2_MLP": 3},
            "label_units": {"DIRECT": 0, "USE_OBSERVER": 0, "USE_OBSERVER_SET": 0, "USE_LARGER_MODEL": 300, "USE_REASONER": 3000, "ASK_HUMAN": 10000, "ABSTAIN": 0},
        },
    })

    w = canon.quantize_weights
    base = {"router": w([92, 3, 2, 2, 1]), "router_b": w([88, 5, 3, 2, 2]), "applic": w([92, 5, 3]), "abstain": w([95, 2, 1, 1, 1]),
            "risk": w([80, 15, 5]), "entities": [900000, 100000, 700000, 50000]}

    def case(name, facts=None, granted=(), forbidden=(), flags=None, replace=None, drop=(), candidate="search", entries=True):
        outputs = {**base, **(replace or {})}
        for alias in drop:
            outputs.pop(alias)
        bundle_of = {"router": "router_a", "router_b": "router_b", "applic": "applicability", "abstain": "abstain", "risk": "risk", "entities": "entities"}
        vector_entries = []
        for alias in sorted(outputs if entries else []):
            entry = {"bundle_id": bundles[bundle_of[alias]]["bundle_id"], "probabilities_ppm": outputs[alias]}
            if alias == "applic":
                entry["candidate"] = candidate
            vector_entries.append(entry)
        observation = {
            "schema": "S15_OBSERVATION_V1", "observation_id": name, "state_hash": h(f"state:{name}"), "actor": "fixture-agent",
            "facts": {"cache_hit": False, "task_kind": "code_change", **(facts or {})},
            "authority_state": {"granted_actions": sorted(granted), "forbidden_actions": sorted(forbidden), "flags": flags or {}},
        }
        vector = model.seal({
            "schema": "S15_DECISION_VECTOR_V1", "observation_id": name, "producer": {"kind": "PRERECORDED", "source": "ff-s15-c0-runtime-01 fixtures"},
            "entries": sorted(vector_entries, key=lambda e: e["bundle_id"]),
        })
        return name, observation, vector

    edit = {"router": w([2, 3, 90, 3, 2]), "router_b": w([3, 3, 85, 5, 4])}
    cases = [
        case("c01-direct-cache", facts={"cache_hit": True}, granted=["read"], entries=False),
        case("c02-confident-observer", granted=["search", "read"]),
        case("c03-set-agreement", granted=["search"], replace={"router": w([70, 10, 10, 5, 5]), "router_b": w([65, 15, 10, 5, 5]), "applic": w([70, 20, 10]), "abstain": w([85, 5, 4, 3, 3])}),
        case("c04-disagreement", granted=["search", "edit"], replace={"router": w([80, 5, 10, 3, 2]), "router_b": w([5, 5, 80, 5, 5])}),
        case("c05-high-risk", granted=["search"], replace={"risk": w([5, 15, 80])}),
        case("c06-ask", granted=["search"], replace={"router": w([3, 2, 2, 3, 90])}),
        case("c07-abstain", granted=["search"], replace={"abstain": w([30, 40, 10, 10, 10])}),
        case("c08-confident-but-not-granted", granted=[]),
        case("c09-forbidden-edit", granted=["edit"], forbidden=["edit"], flags={"tests_green": True}, replace=edit),
        case("c10-edit-needs-green-tests", granted=["edit"], flags={"tests_green": False}, replace=edit),
        case("c11-incomplete-evidence", granted=["search"], replace={"router": w([70, 10, 10, 5, 5])}, drop=["router_b"]),
        case("c12-medium-risk-edit", granted=["edit"], flags={"tests_green": True}, replace={**edit, "risk": w([10, 80, 10])}),
        case("c13-unknown-applicability", granted=["search"], replace={"applic": w([10, 10, 80])}),
        case("c14-edit-allowed", granted=["edit"], flags={"tests_green": True}, replace={**edit, "risk": w([90, 8, 2])}),
    ]
    return contracts, bundles, policy, cases


def files() -> dict[str, bytes]:
    contracts, bundles, policy, cases = build()
    out: dict[str, bytes] = {"policy.json": canon.canonical_bytes(policy)}
    for name, record in contracts.items():
        out[f"contracts/{name}.json"] = canon.canonical_bytes(record)
    for name, record in bundles.items():
        out[f"bundles/{name}.json"] = canon.canonical_bytes(record)
    for name, observation, vector in cases:
        out[f"cases/{name}/observation.json"] = canon.canonical_bytes(observation)
        out[f"cases/{name}/vector.json"] = canon.canonical_bytes(vector)
    return out


def main() -> int:
    generated = files()
    if "--check" in sys.argv:
        stale = [n for n, data in generated.items() if not (OUT / n).exists() or (OUT / n).read_bytes() != data]
        if stale:
            print("fixtures out of date:", stale[:5], "...")
            return 1
        print(f"{len(generated)} fixture files match the builder")
        return 0
    keep = {p: (OUT / p).read_bytes() for p in ("GOLDEN.sha256",) if (OUT / p).exists()}
    expected = {p.relative_to(OUT).as_posix(): p.read_bytes() for p in OUT.glob("cases/*/expected-receipt.json")} if OUT.exists() else {}
    if OUT.exists():
        shutil.rmtree(OUT)
    for name, data in generated.items():
        path = OUT / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    for name, data in {**keep, **expected}.items():  # golden receipts survive a rebuild until re-approved
        (OUT / name).write_bytes(data)
    print(f"wrote {len(generated)} fixture files to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
