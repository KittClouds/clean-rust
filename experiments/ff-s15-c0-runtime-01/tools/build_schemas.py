"""Generates schemas/*.schema.json for the C0 records from one source of truth.

  python tools/build_schemas.py            write the schema files
  python tools/build_schemas.py --check    fail if the committed files differ from the generated ones

The shared definitions (identifiers, hashes, ppm, labels) live here once, so they cannot drift
between record schemas. Only the JSON Schema subset in s15/schema.py is used.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIALECT = "https://json-schema.org/draft/2020-12/schema"

ESCALATION_LABELS = ["DIRECT", "USE_OBSERVER", "USE_OBSERVER_SET", "USE_LARGER_MODEL", "USE_REASONER", "ASK_HUMAN", "ABSTAIN"]
COST_CLASSES = ["T0_RULE", "T1_LINEAR", "T2_MLP", "T3_OBSERVER_SET", "T4_LATENT", "T5_SPECIALIST", "T6_REASONER", "T7_HUMAN"]
DECISION_TYPES = ["CHOICE", "MULTI_CHOICE", "APPLICABILITY", "ORDINAL", "ABSTENTION", "ESCALATION"]
DISPOSITIONS = ["EXECUTE_ALLOWED", "DENIED", "ESCALATED", "ASKED", "ABSTAINED"]

SHARED = {
    "ident": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]{0,63}$"},
    "name": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.-]{0,63}$"},
    "token": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_.+:-]{0,63}$"},
    "code": {"type": "string", "pattern": "^[A-Z][A-Z0-9_]{0,63}$"},
    "alias": {"type": "string", "pattern": "^[a-z][a-z0-9_]{0,31}$"},
    "signal": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_.]{0,127}$"},
    "sha256_id": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"},
    "text": {"type": "string", "pattern": "^[\\x20-\\x7e]{0,256}$"},
    "ppm": {"type": "integer", "minimum": 0, "maximum": 1000000},
    "units": {"type": "integer", "minimum": 0, "maximum": 1000000000000},
    "escalation_label": {"enum": ESCALATION_LABELS},
}
R = lambda name: {"$ref": f"#/$defs/{name}"}  # noqa: E731
NULLABLE = lambda name: {"oneOf": [R(name), {"type": "null"}]}  # noqa: E731


def record(title: str, schema_const: str, required_props: dict, optional_props: dict | None = None, uses: tuple = (), extra_defs: dict | None = None) -> dict:
    properties = {"schema": {"const": schema_const}, **required_props, **(optional_props or {})}
    defs = {name: SHARED[name] for name in uses}
    defs.update(extra_defs or {})
    return {
        "$schema": DIALECT,
        "$id": f"s15/{title}-v1",
        "title": title,
        "type": "object",
        "additionalProperties": False,
        "required": ["schema", *required_props],
        "properties": properties,
        "$defs": dict(sorted(defs.items())),
    }


def obj(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required if required is not None else list(properties), "properties": properties}


def labels(minimum: int = 2, maximum: int = 64) -> dict:
    return {"type": "array", "minItems": minimum, "maxItems": maximum, "uniqueItems": True, "items": R("ident")}


def build() -> dict[str, dict]:
    out: dict[str, dict] = {}

    out["decision-contract"] = record(
        "DecisionContract", "S15_DECISION_CONTRACT_V1",
        {
            "contract_id": R("sha256_id"), "name": R("ident"), "version": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "decision_type": {"enum": DECISION_TYPES}, "question": R("ident"),
            "candidate_schema": {"oneOf": [
                obj({"kind": {"const": "LABELS"}, "labels": labels()}),
                obj({"kind": {"const": "OBSERVATION_SUPPLIED"}}),
            ]},
            "output_schema": obj({"kind": {"enum": ["SIMPLEX", "INDEPENDENT"]}, "labels": labels(), "scale_ppm": {"const": 1000000}}),
            "abstention_allowed": {"type": "boolean"}, "unknown_allowed": {"type": "boolean"},
            "cost_class": {"enum": COST_CLASSES},
            # There is deliberately no value that says a neural component owns authority.
            "authority_class": {"enum": ["ADVISORY", "PROPOSES_ACTION", "ESCALATION_ONLY"]},
        },
        uses=("ident", "sha256_id"),
    )

    out["observer-bundle"] = record(
        "ObserverBundle", "S15_OBSERVER_BUNDLE_V1",
        {
            "bundle_id": R("sha256_id"), "name": R("ident"), "bundle_version": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "backbone": obj({"model_id": R("text"), "revision": R("text")}),
            "representation": obj({"layer": R("token"), "surface": R("token"), "dimensions": {"type": "integer", "minimum": 1, "maximum": 1000000}}),
            "normalization": obj({"center_hash": R("sha256_id"), "scale_hash": R("sha256_id")}),
            "head": obj({"architecture": R("token"), "weights_hash": R("sha256_id"), "class_order": labels()}),
            "calibration": obj({"method": {"enum": ["NONE", "TEMPERATURE", "PLATT", "ISOTONIC", "HISTOGRAM"]}, "parameters_hash": R("sha256_id")}),
            "decision_contract_id": R("sha256_id"), "training_identity": R("text"),
            "source_hashes": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("sha256_id")},
        },
        uses=("ident", "sha256_id", "text", "token"),
    )

    escalation_props = {
        "choice": R("escalation_label"), "reason": R("text"), "confidence_ppm": R("ppm"), "confidence_signal": NULLABLE("signal"),
        "triggering_observers": {"type": "array", "maxItems": 16, "uniqueItems": True, "items": R("alias")},
        "cost_estimate": R("units"), "rule_id": NULLABLE("name"),
    }
    out["escalation-decision"] = record(
        "EscalationDecision", "S15_ESCALATION_DECISION_V1", escalation_props, uses=("alias", "escalation_label", "name", "ppm", "signal", "text", "units"),
    )

    authority_props = {
        "effect": {"enum": ["ALLOW", "DENY", "REQUIRE_ESCALATION"]}, "reason_code": R("code"), "policy_id": R("sha256_id"),
        "policy_revision": {"type": "integer", "minimum": 1, "maximum": 1000000}, "proposed_action": R("ident"), "actor": R("name"),
        "rule_id": NULLABLE("name"),
        "neural_inputs_used": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("signal")},
    }
    out["authority-decision"] = record(
        "AuthorityDecision", "S15_AUTHORITY_DECISION_V1", authority_props, uses=("code", "ident", "name", "sha256_id", "signal"),
    )

    out["observation-envelope"] = record(
        "ObservationEnvelope", "S15_OBSERVATION_V1",
        {
            "observation_id": R("name"), "state_hash": R("sha256_id"), "actor": R("name"),
            "facts": {"type": "object", "additionalProperties": {"oneOf": [{"type": "integer"}, R("text"), {"type": "boolean"}]}},
            "authority_state": obj({
                "granted_actions": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("ident")},
                "forbidden_actions": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("ident")},
                "flags": {"type": "object", "additionalProperties": {"type": "boolean"}},
            }),
        },
        uses=("ident", "name", "sha256_id", "text"),
    )

    out["decision-vector"] = record(
        "DecisionVector", "S15_DECISION_VECTOR_V1",
        {
            "decision_vector_id": R("sha256_id"), "observation_id": R("name"),
            "producer": obj({"kind": {"enum": ["PRERECORDED", "LIVE"]}, "source": R("text")}),
            "entries": {"type": "array", "maxItems": 64, "items": obj(
                {"bundle_id": R("sha256_id"), "candidate": R("name"), "probabilities_ppm": {"type": "array", "minItems": 2, "maxItems": 64, "items": R("ppm")}},
                required=["bundle_id", "probabilities_ppm"],
            )},
        },
        uses=("name", "ppm", "sha256_id", "text"),
    )

    cond = {"oneOf": [
        obj({"all": {"type": "array", "minItems": 1, "maxItems": 16, "items": R("cond")}}),
        obj({"any": {"type": "array", "minItems": 1, "maxItems": 16, "items": R("cond")}}),
        obj({"not": R("cond")}),
        obj({"cmp": obj({"signal": R("signal"), "op": {"enum": ["eq", "ne", "lt", "le", "gt", "ge"]},
                         "value": {"oneOf": [{"type": "integer"}, R("text"), {"type": "boolean"}]}})}),
        obj({"agree": {"type": "array", "minItems": 2, "maxItems": 8, "uniqueItems": True, "items": R("alias")}}),
        obj({"disagree": {"type": "array", "minItems": 2, "maxItems": 8, "uniqueItems": True, "items": R("alias")}}),
    ]}
    propose = {"oneOf": [obj({"from": R("alias")}), obj({"literal": R("ident")})]}
    escalation_rule = obj(
        {"rule_id": R("name"), "when": R("cond"), "then": R("escalation_label"), "reason": R("text"),
         "confidence_signal": NULLABLE("signal"), "propose": propose},
        required=["rule_id", "when", "then", "reason", "confidence_signal"],
    )
    authority_rule = obj(
        {"rule_id": R("name"), "when": R("cond"), "effect": {"enum": ["ALLOW", "DENY", "REQUIRE_ESCALATION"]}, "reason_code": R("code"),
         "declared_neural_inputs": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("signal")}},
    )
    non_proceed = {"enum": ["USE_LARGER_MODEL", "USE_REASONER", "ASK_HUMAN", "ABSTAIN"]}
    out["runtime-policy"] = record(
        "RuntimePolicy", "S15_RUNTIME_POLICY_V1",
        {
            "policy_id": R("sha256_id"), "name": R("ident"), "policy_revision": {"type": "integer", "minimum": 1, "maximum": 1000000},
            "actions": {"type": "array", "minItems": 1, "maxItems": 64, "uniqueItems": True, "items": R("ident")},
            "observers": {"type": "array", "minItems": 1, "maxItems": 32, "items": obj({"alias": R("alias"), "bundle_id": R("sha256_id")})},
            "escalation_rules": {"type": "array", "maxItems": 64, "items": escalation_rule},
            "authority_rules": {"type": "array", "maxItems": 64, "items": authority_rule},
            # Defaults never act: a policy cannot default to a proceed label or to ALLOW.
            "default_escalation": non_proceed, "on_incomplete_evidence": non_proceed, "on_require_escalation": non_proceed,
            "default_authority": {"enum": ["DENY", "REQUIRE_ESCALATION"]},
            "costs": obj({
                "backbone_units": R("units"),
                "cost_class_units": {"type": "object", "additionalProperties": False, "properties": {c: R("units") for c in COST_CLASSES}},
                "label_units": obj({label: R("units") for label in ESCALATION_LABELS}),
            }),
        },
        uses=("alias", "code", "escalation_label", "ident", "name", "sha256_id", "signal", "text", "units"),
        extra_defs={"cond": cond},
    )

    observer_entry = obj({
        "alias": R("alias"), "bundle_id": R("sha256_id"), "contract_id": R("sha256_id"), "present": {"type": "boolean"}, "consulted": {"type": "boolean"},
        "candidate": {"oneOf": [R("name"), {"type": "null"}]},
        "probabilities_ppm": {"oneOf": [{"type": "array", "minItems": 2, "maxItems": 64, "items": R("ppm")}, {"type": "null"}]},
        "top_label": {"oneOf": [R("ident"), {"type": "null"}]}, "top_ppm": {"oneOf": [R("ppm"), {"type": "null"}]},
        "margin_ppm": {"oneOf": [R("ppm"), {"type": "null"}]},
    })
    trace_entry = obj({"rule_id": R("name"), "result": {"enum": ["TRUE", "FALSE", "UNKNOWN"]}})
    out["runtime-receipt"] = record(
        "RuntimeReceipt", "S15_RUNTIME_RECEIPT_V1",
        {
            "receipt_id": R("sha256_id"),
            "runtime": obj({"name": R("token"), "version": R("token")}),
            "observation": obj({"observation_id": R("name"), "state_hash": R("sha256_id"), "actor": R("name")}),
            "inputs": obj({
                "policy_id": R("sha256_id"), "policy_revision": {"type": "integer", "minimum": 1, "maximum": 1000000}, "decision_vector_id": R("sha256_id"),
                "contract_ids": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("sha256_id")},
                "bundle_ids": {"type": "array", "maxItems": 64, "uniqueItems": True, "items": R("sha256_id")},
            }),
            "observers": {"type": "array", "maxItems": 32, "items": observer_entry},
            "disagreements": {"type": "array", "maxItems": 32, "items": obj({
                "contract_id": R("sha256_id"),
                "positions": {"type": "array", "minItems": 2, "maxItems": 64, "items": obj({"label": R("ident"), "aliases": {"type": "array", "minItems": 1, "maxItems": 16, "items": R("alias")}})},
            })},
            "escalation_trace": {"type": "array", "maxItems": 64, "items": trace_entry},
            "escalation": {"$ref": "#/$defs/escalation_decision"},
            "proposed_action": {"oneOf": [R("ident"), {"type": "null"}]},
            "authority": {"oneOf": [{"$ref": "#/$defs/authority_decision"}, {"type": "null"}]},
            "authority_trace": {"type": "array", "maxItems": 64, "items": trace_entry},
            "disposition": {"enum": DISPOSITIONS},
            "disposition_target": {"oneOf": [R("ident"), {"type": "null"}]},
            "cost": obj({"units": R("units"), "backbone": R("units"), "observers": R("units"), "label": R("units")}),
        },
        uses=("alias", "code", "escalation_label", "ident", "name", "ppm", "sha256_id", "signal", "text", "token", "units"),
        extra_defs={
            "escalation_decision": {**obj({"schema": {"const": "S15_ESCALATION_DECISION_V1"}, **escalation_props}) },
            "authority_decision": {**obj({"schema": {"const": "S15_AUTHORITY_DECISION_V1"}, **authority_props}) },
        },
    )
    return out


def render(schema: dict) -> str:
    return json.dumps(schema, indent=2, sort_keys=False) + "\n"


def main() -> int:
    target = ROOT / "schemas"
    generated = {f"{name}.schema.json": render(schema) for name, schema in build().items()}
    if "--check" in sys.argv:
        stale = [name for name, text in generated.items() if not (target / name).exists() or (target / name).read_text(encoding="utf-8") != text]
        extra = sorted(p.name for p in target.glob("*.schema.json") if p.name not in generated)
        if stale or extra:
            print("schemas out of date:", stale, "unexpected:", extra)
            return 1
        print(f"{len(generated)} schemas match the generator")
        return 0
    target.mkdir(exist_ok=True)
    for name, text in generated.items():
        (target / name).write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {len(generated)} schemas to {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
