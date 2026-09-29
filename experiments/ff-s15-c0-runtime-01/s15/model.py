"""Loading and verifying C0 records: schema, content-derived identity, cross-record compatibility.

Trust is checked, never assumed:

- every record is validated against its schema and its own id must equal the hash of its content,
  so changing any field makes it a different record (for an observer bundle: any compatibility
  field changes the bundle, exactly as the ABI rule says);
- a bundle must match its contract (same contract id, same class order);
- a policy may only name bundles that exist, and its rules are checked so that a neural output can
  propose but never own authority (see `verify_policy`).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import canon
from . import policy as pol
from . import schema as jschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIR = ROOT / "schemas"

ESCALATION_LABELS = ["DIRECT", "USE_OBSERVER", "USE_OBSERVER_SET", "USE_LARGER_MODEL", "USE_REASONER", "ASK_HUMAN", "ABSTAIN"]
PROCEED = ("DIRECT", "USE_OBSERVER", "USE_OBSERVER_SET")

# schema constant -> (schema file key, id field or None)
KINDS = {
    "S15_DECISION_CONTRACT_V1": ("decision-contract", "contract_id"),
    "S15_OBSERVER_BUNDLE_V1": ("observer-bundle", "bundle_id"),
    "S15_RUNTIME_POLICY_V1": ("runtime-policy", "policy_id"),
    "S15_DECISION_VECTOR_V1": ("decision-vector", "decision_vector_id"),
    "S15_RUNTIME_RECEIPT_V1": ("runtime-receipt", "receipt_id"),
    "S15_OBSERVATION_V1": ("observation-envelope", None),
    "S15_ESCALATION_DECISION_V1": ("escalation-decision", None),
    "S15_AUTHORITY_DECISION_V1": ("authority-decision", None),
}


class RecordError(ValueError):
    """A record that is malformed, tampered with, or incompatible with the records it names."""


_schemas: dict[str, dict] = {}


def schema_for(key: str) -> dict:
    if key not in _schemas:
        loaded = json.loads((SCHEMA_DIR / f"{key}.schema.json").read_text(encoding="utf-8"))
        jschema.check_schema(loaded)
        _schemas[key] = loaded
    return _schemas[key]


def check_record(record) -> str:
    """Validates schema and identity; returns the record's schema file key."""
    if not isinstance(record, dict) or record.get("schema") not in KINDS:
        raise RecordError("not a C0 record: missing or unknown schema")
    key, id_field = KINDS[record["schema"]]
    errors = jschema.validate(record, schema_for(key))
    if errors:
        raise RecordError(f"{record['schema']}: " + "; ".join(errors[:8]))
    if id_field:
        expected = canon.derive_id(key, canon.without(record, id_field))
        if record[id_field] != expected:
            raise RecordError(f"{record['schema']}: {id_field} does not match the record's content (expected {expected})")
    return key


def seal(record: dict) -> dict:
    """Returns the record with its content-derived id filled in."""
    key, id_field = KINDS[record["schema"]]
    sealed = dict(record)
    sealed[id_field] = canon.derive_id(key, canon.without(record, id_field))
    return sealed


def load_file(path: Path) -> dict:
    record = canon.loads_strict(Path(path).read_bytes())
    check_record(record)
    return record


def load_dir(path: Path, schema_const: str) -> list[dict]:
    records = []
    for file in sorted(Path(path).glob("*.json")):
        try:
            record = load_file(file)
        except (canon.CanonError, RecordError) as error:
            raise RecordError(f"{file.name}: {error}") from error
        if record["schema"] != schema_const:
            raise RecordError(f"{file.name}: expected {schema_const}, found {record['schema']}")
        records.append(record)
    return records


def _need(condition: bool, message: str) -> None:
    if not condition:
        raise RecordError(message)


def verify_contract(contract: dict) -> None:
    kind, candidates, output = contract["decision_type"], contract["candidate_schema"], contract["output_schema"]
    labels = output["labels"]
    name = contract["name"]
    if kind == "APPLICABILITY":
        _need(candidates["kind"] == "OBSERVATION_SUPPLIED", f"{name}: an applicability candidate is supplied by the observation")
        _need(output["kind"] == "SIMPLEX" and labels == ["YES", "NO", "UNKNOWN"], f"{name}: applicability answers exactly YES, NO, UNKNOWN")
    else:
        _need(candidates["kind"] == "LABELS" and candidates["labels"] == labels, f"{name}: candidate labels must equal output labels")
        _need(output["kind"] == ("INDEPENDENT" if kind == "MULTI_CHOICE" else "SIMPLEX"), f"{name}: {kind} needs a {'INDEPENDENT' if kind == 'MULTI_CHOICE' else 'SIMPLEX'} output")
    if kind == "ESCALATION":
        _need(labels == ESCALATION_LABELS, f"{name}: an escalation contract answers exactly the seven escalation labels")
        _need(contract["authority_class"] == "ESCALATION_ONLY", f"{name}: an escalation contract is ESCALATION_ONLY")
    if kind == "ABSTENTION":
        _need(contract["abstention_allowed"] is True, f"{name}: an abstention contract allows abstention")
    _need(contract["unknown_allowed"] == ("UNKNOWN" in labels), f"{name}: unknown_allowed must say whether UNKNOWN is a label")
    if contract["authority_class"] == "PROPOSES_ACTION":
        _need(kind == "CHOICE", f"{name}: only a CHOICE can propose an action")


def verify_bundle(bundle: dict, contract: dict) -> None:
    name = bundle["name"]
    _need(bundle["decision_contract_id"] == contract["contract_id"], f"{name}: bundle names a different contract")
    _need(bundle["head"]["class_order"] == contract["output_schema"]["labels"], f"{name}: class order differs from the contract's labels")
    _need(bundle["source_hashes"] == sorted(bundle["source_hashes"]), f"{name}: source_hashes must be sorted")


def verify_policy(policy: dict, contracts: dict[str, dict], bundles: dict[str, dict]) -> dict[str, dict]:
    """Checks the policy against the records it names. Returns alias -> DecisionContract."""
    observers: dict[str, dict] = {}
    for entry in policy["observers"]:
        alias, bundle_id = entry["alias"], entry["bundle_id"]
        _need(alias not in observers and alias not in pol.RESERVED, f"observer alias {alias!r} is duplicated or reserved")
        _need(bundle_id in bundles, f"observer {alias!r}: unknown bundle {bundle_id}")
        observers[alias] = contracts[bundles[bundle_id]["decision_contract_id"]]
    actions = set(policy["actions"])
    units = policy["costs"]["cost_class_units"]
    for alias, contract in observers.items():
        _need(contract["cost_class"] in units, f"costs: no units for cost class {contract['cost_class']} (used by {alias})")

    def wrap(fn, *args):
        try:
            return fn(*args)
        except pol.PolicyError as error:
            raise RecordError(str(error)) from error

    for rules, what in ((policy["escalation_rules"], "escalation"), (policy["authority_rules"], "authority")):
        ids = [rule["rule_id"] for rule in rules]
        _need(len(ids) == len(set(ids)), f"{what} rule ids must be unique")

    for rule in policy["escalation_rules"]:
        rid, then = rule["rule_id"], rule["then"]
        reads = wrap(pol.check_cond, rule["when"], observers, actions, "escalation")
        propose = rule.get("propose")
        if then in PROCEED:
            _need(propose is not None, f"{rid}: {then} must say what it proposes")
            if then == "DIRECT":
                _need("literal" in propose, f"{rid}: DIRECT proposes a literal action")
                _need(propose["literal"] in actions, f"{rid}: {propose['literal']!r} is not in the action catalogue")
                _need(not reads.aliases, f"{rid}: DIRECT is the no-model tier; its condition may not read observers")
                _need(rule["confidence_signal"] is None, f"{rid}: DIRECT has no observer confidence")
            else:
                _need("from" in propose, f"{rid}: {then} proposes from an observer")
                source = observers.get(propose["from"])
                _need(source is not None, f"{rid}: unknown observer {propose['from']!r}")
                _need(source["decision_type"] == "CHOICE" and source["authority_class"] == "PROPOSES_ACTION", f"{rid}: {propose['from']!r} cannot propose actions")
            if then == "USE_OBSERVER_SET":
                _need(reads.has_agree, f"{rid}: USE_OBSERVER_SET must depend on observers agreeing")
        else:
            _need(propose is None, f"{rid}: {then} proposes no action")
        if then == "ABSTAIN":
            _need(any(observers[a]["abstention_allowed"] for a in reads.aliases), f"{rid}: ABSTAIN must cite an observer whose contract allows abstention")
        if rule["confidence_signal"] is not None:
            sig = wrap(pol.parse_signal, rule["confidence_signal"], observers)
            _need(sig.neural and sig.vtype == "int", f"{rid}: confidence_signal must be an observer ppm signal")
    granted_is_true = {"cmp": {"signal": "authority.granted", "op": "eq", "value": True}}
    for rule in policy["authority_rules"]:
        rid = rule["rule_id"]
        reads = wrap(pol.check_cond, rule["when"], observers, actions, "authority")
        _need(rule["declared_neural_inputs"] == sorted(reads.neural_signals),
              f"{rid}: declared_neural_inputs must list exactly the observer signals the rule reads: {sorted(reads.neural_signals)}")
        if rule["effect"] == "ALLOW":
            _need(granted_is_true in pol.top_level_children(rule["when"]), f"{rid}: an ALLOW rule must require authority.granted == true as a top-level 'all' condition")
    return observers


@dataclass
class World:
    policy: dict
    contracts: dict[str, dict]
    bundles: dict[str, dict]
    observers: dict[str, dict]  # alias -> DecisionContract
    alias_bundle: dict[str, dict]  # alias -> ObserverBundle


def load_world(policy_path: Path, contracts_dir: Path, bundles_dir: Path) -> World:
    contracts: dict[str, dict] = {}
    for contract in load_dir(contracts_dir, "S15_DECISION_CONTRACT_V1"):
        verify_contract(contract)
        _need(contract["contract_id"] not in contracts, f"duplicate contract {contract['contract_id']}")
        contracts[contract["contract_id"]] = contract
    bundles: dict[str, dict] = {}
    for bundle in load_dir(bundles_dir, "S15_OBSERVER_BUNDLE_V1"):
        contract = contracts.get(bundle["decision_contract_id"])
        _need(contract is not None, f"{bundle['name']}: its contract {bundle['decision_contract_id']} is not in {contracts_dir}")
        verify_bundle(bundle, contract)
        _need(bundle["bundle_id"] not in bundles, f"duplicate bundle {bundle['bundle_id']}")
        bundles[bundle["bundle_id"]] = bundle
    try:
        policy = load_file(policy_path)
    except canon.CanonError as error:
        raise RecordError(f"{Path(policy_path).name}: {error}") from error
    _need(policy["schema"] == "S15_RUNTIME_POLICY_V1", "the policy file is not a RuntimePolicy")
    observers = verify_policy(policy, contracts, bundles)
    alias_bundle = {entry["alias"]: bundles[entry["bundle_id"]] for entry in policy["observers"]}
    return World(policy, contracts, bundles, observers, alias_bundle)
