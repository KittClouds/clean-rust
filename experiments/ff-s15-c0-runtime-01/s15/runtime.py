"""The C0 reference runtime: observer outputs in, decision and receipt out.

    observation + decision vector (prerecorded observer outputs) + policy + contracts + bundles
        -> escalation rules (first TRUE rule wins, else the policy default)
        -> if the chosen tier is allowed to act: deterministic authority
        -> disposition and receipt

Pure function of its inputs: no model, no clock, no randomness, no I/O. The same inputs and
contracts give the same receipt bytes. Neural outputs may propose an action and may estimate
confidence; only the deterministic authority stage can allow one, and it allows nothing that was
not granted by the authority state.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import canon, model
from . import policy as pol

RUNTIME_NAME = "s15-reference-runtime"
RUNTIME_VERSION = "c0.1"
_RESULT = {True: "TRUE", False: "FALSE", None: "UNKNOWN"}


class InputError(ValueError):
    """Inputs that do not belong together (wrong observation, unknown bundle, malformed output)."""


@dataclass
class Output:
    alias: str
    bundle: dict
    contract: dict
    probabilities: list
    candidate: str | None
    top_label: str | None
    top_ppm: int | None
    margin_ppm: int | None


def _top(probabilities: list, labels: list):
    order = sorted(range(len(probabilities)), key=lambda i: (-probabilities[i], i))
    best = order[0]
    second = probabilities[order[1]] if len(order) > 1 else 0
    return labels[best], probabilities[best], probabilities[best] - second


def build_outputs(world: model.World, observation: dict, vector: dict) -> dict:
    if vector["observation_id"] != observation["observation_id"]:
        raise InputError("the decision vector answers a different observation")
    in_policy = {bundle["bundle_id"]: alias for alias, bundle in world.alias_bundle.items()}
    seen: dict = {}
    for entry in vector["entries"]:
        bundle_id = entry["bundle_id"]
        if bundle_id not in in_policy:
            raise InputError(f"the decision vector carries an output for {bundle_id}, which the policy does not use")
        if bundle_id in seen:
            raise InputError(f"the decision vector carries two outputs for {bundle_id}")
        seen[bundle_id] = entry
    outputs: dict = {}
    for alias, bundle in world.alias_bundle.items():
        entry = seen.get(bundle["bundle_id"])
        if entry is None:
            outputs[alias] = None
            continue
        contract = world.observers[alias]
        labels, kind = contract["output_schema"]["labels"], contract["output_schema"]["kind"]
        probabilities = entry["probabilities_ppm"]
        if len(probabilities) != len(labels):
            raise InputError(f"{alias}: {len(probabilities)} probabilities for {len(labels)} labels")
        if kind == "SIMPLEX" and sum(probabilities) != 1_000_000:
            raise InputError(f"{alias}: probabilities sum to {sum(probabilities)}, not 1000000")
        supplied = contract["candidate_schema"]["kind"] == "OBSERVATION_SUPPLIED"
        if supplied != ("candidate" in entry):
            raise InputError(f"{alias}: candidate is {'required' if supplied else 'not allowed'} for this contract")
        top_label = top_ppm = margin = None
        if kind == "SIMPLEX":
            top_label, top_ppm, margin = _top(probabilities, labels)
        outputs[alias] = Output(alias, bundle, contract, list(probabilities), entry.get("candidate"), top_label, top_ppm, margin)
    return outputs


class Evaluation:
    """One run: lazily reads signals, remembers which observers were consulted."""

    def __init__(self, world: model.World, observation: dict, outputs: dict):
        self.world, self.observation, self.outputs = world, observation, outputs
        self.actions = set(world.policy["actions"])
        self.consulted: set = set()
        self.missing: set = set()
        self.rule_reads: set = set()
        self.neural_read: set = set()
        self.proposed: str | None = None
        self._parsed: dict = {}

    def sig(self, text: str) -> pol.Sig:
        if text not in self._parsed:
            self._parsed[text] = pol.parse_signal(text, self.world.observers)
        return self._parsed[text]

    def consult(self, alias: str):
        self.consulted.add(alias)
        self.rule_reads.add(alias)
        output = self.outputs[alias]
        if output is None:
            self.missing.add(alias)
        return output

    def value(self, text: str):
        sig = self.sig(text)
        state = self.observation["authority_state"]
        if sig.kind == "obs":
            return self.observation["facts"].get(sig.name, pol.MISSING)
        if sig.kind == "actor":
            return self.observation["actor"]
        if sig.kind == "action":
            return self.proposed if self.proposed is not None else pol.MISSING
        if sig.kind == "granted":
            return self.proposed in state["granted_actions"]
        if sig.kind == "forbidden":
            return self.proposed in state["forbidden_actions"]
        if sig.kind == "flag":
            return state["flags"].get(sig.name, False)
        output = self.consult(sig.alias)
        if output is None:
            return pol.MISSING
        self.neural_read.add(text)
        if sig.field == "top_label":
            return output.top_label
        if sig.field == "top_ppm":
            return output.top_ppm
        if sig.field == "margin_ppm":
            return output.margin_ppm
        return output.probabilities[output.contract["output_schema"]["labels"].index(sig.label)]

    def ev(self, cond: dict):
        """TRUE, FALSE or None (UNKNOWN)."""
        (kind, body), = cond.items()
        if kind == "all":
            unknown = False
            for child in body:
                result = self.ev(child)
                if result is False:
                    return False
                unknown = unknown or result is None
            return None if unknown else True
        if kind == "any":
            unknown = False
            for child in body:
                result = self.ev(child)
                if result is True:
                    return True
                unknown = unknown or result is None
            return None if unknown else False
        if kind == "not":
            result = self.ev(body)
            return None if result is None else not result
        if kind == "cmp":
            left = self.value(body["signal"])
            return None if left is pol.MISSING else pol.compare(body["op"], left, body["value"])
        tops = []
        for alias in body:  # agree / disagree consult every named observer
            output = self.consult(alias)
            tops.append(None if output is None else output.top_label)
        if None in tops:
            return None
        agree = len(set(tops)) == 1
        return agree if kind == "agree" else not agree


def _decision_of(choice, reason, confidence, signal, triggering, rule_id) -> dict:
    return {
        "schema": "S15_ESCALATION_DECISION_V1", "choice": choice, "reason": reason, "confidence_ppm": confidence,
        "confidence_signal": signal, "triggering_observers": sorted(triggering), "cost_estimate": 0, "rule_id": rule_id,
    }


def run(world: model.World, observation: dict, vector: dict) -> tuple[dict, bytes]:
    """Runs one observation through the policy. Returns the receipt and its canonical bytes."""
    if model.check_record(observation) != "observation-envelope":
        raise InputError("not an observation")
    if model.check_record(vector) != "decision-vector":
        raise InputError("not a decision vector")
    for key in observation["facts"]:
        if not canon._ASCII.fullmatch(key) or not pol._NAME.fullmatch(key):
            raise InputError(f"fact name {key!r} is not a valid name")
    for key in observation["authority_state"]["flags"]:
        if not pol._NAME.fullmatch(key):
            raise InputError(f"flag name {key!r} is not a valid name")
    policy = world.policy
    outputs = build_outputs(world, observation, vector)
    ev = Evaluation(world, observation, outputs)

    # --- escalation stage
    trace, matched = [], None
    for rule in policy["escalation_rules"]:
        ev.rule_reads = set()
        result = ev.ev(rule["when"])
        trace.append({"rule_id": rule["rule_id"], "result": _RESULT[result]})
        if result is True:
            matched = rule
            break
    proposal = None
    if matched is not None:
        choice = matched["then"]
        if choice in model.PROCEED:
            propose = matched["propose"]
            if "literal" in propose:
                proposal = propose["literal"]
            else:
                output = ev.consult(propose["from"])
                proposal = output.top_label if output is not None else None
        confidence = 0
        if matched["confidence_signal"] is not None:
            value = ev.value(matched["confidence_signal"])
            confidence = 0 if value is pol.MISSING else value
        escalation = _decision_of(choice, matched["reason"], confidence, matched["confidence_signal"], ev.rule_reads, matched["rule_id"])
    else:
        escalation = _decision_of(policy["default_escalation"], "NO_RULE_MATCHED", 0, None, [], None)
    if ev.missing:  # fail closed: an observer that was needed but had no output
        escalation = _decision_of(policy["on_incomplete_evidence"], "INCOMPLETE_EVIDENCE", 0, None, ev.missing, None)
        proposal = None

    # --- authority stage: only for a tier that is allowed to act
    authority, authority_trace = None, []
    if escalation["choice"] in model.PROCEED:
        assert proposal is not None, "a proceeding tier always has a proposal"
        ev.proposed, ev.neural_read = proposal, set()
        state = observation["authority_state"]
        effect, code, rule_id = None, None, None
        if proposal not in ev.actions:
            effect, code = "DENY", "ACTION_NOT_IN_CATALOG"
        elif proposal in state["forbidden_actions"]:
            effect, code = "DENY", "FORBIDDEN_BY_STATE"
        else:
            hit = None
            for rule in policy["authority_rules"]:
                ev.rule_reads = set()
                result = ev.ev(rule["when"])
                authority_trace.append({"rule_id": rule["rule_id"], "result": _RESULT[result]})
                if result is True:
                    hit = rule
                    break
            if ev.missing:
                effect, code = "REQUIRE_ESCALATION", "INCOMPLETE_EVIDENCE"
            elif hit is not None:
                effect, code, rule_id = hit["effect"], hit["reason_code"], hit["rule_id"]
            else:
                effect, code = policy["default_authority"], "NO_RULE_MATCHED"
        authority = {
            "schema": "S15_AUTHORITY_DECISION_V1", "effect": effect, "reason_code": code, "policy_id": policy["policy_id"],
            "policy_revision": policy["policy_revision"], "proposed_action": proposal, "actor": observation["actor"],
            "rule_id": rule_id, "neural_inputs_used": sorted(ev.neural_read),
        }

    # --- disposition: a tier that cannot act ends the run; a REQUIRE_ESCALATION hands over to the policy's label
    def stops_at(label: str) -> tuple[str, str | None]:
        disposition = {"ASK_HUMAN": "ASKED", "ABSTAIN": "ABSTAINED"}.get(label, "ESCALATED")
        return disposition, label if disposition == "ESCALATED" else None

    handed_to = None
    if authority is None:
        disposition, target = stops_at(escalation["choice"])
    elif authority["effect"] == "ALLOW":
        disposition, target = "EXECUTE_ALLOWED", proposal
    elif authority["effect"] == "DENY":
        disposition, target = "DENIED", None
    else:
        handed_to = policy["on_require_escalation"]
        disposition, target = stops_at(handed_to)

    # --- cost: the backbone runs once if any observer was consulted; plus each consulted head and the tier reached
    costs = policy["costs"]
    backbone = costs["backbone_units"] if ev.consulted else 0
    heads = sum(costs["cost_class_units"][world.observers[alias]["cost_class"]] for alias in sorted(ev.consulted))
    label = costs["label_units"][escalation["choice"]]
    if handed_to is not None:
        label += costs["label_units"][handed_to]
    total = backbone + heads + label
    escalation["cost_estimate"] = total

    observers = []
    for alias in sorted(outputs):
        out = outputs[alias]
        observers.append({
            "alias": alias, "bundle_id": world.alias_bundle[alias]["bundle_id"], "contract_id": world.observers[alias]["contract_id"],
            "present": out is not None, "consulted": alias in ev.consulted, "candidate": None if out is None else out.candidate,
            "probabilities_ppm": None if out is None else out.probabilities, "top_label": None if out is None else out.top_label,
            "top_ppm": None if out is None else out.top_ppm, "margin_ppm": None if out is None else out.margin_ppm,
        })

    disagreements = []
    for contract_id in sorted({o["contract_id"] for o in observers}):
        tops: dict = {}
        for o in observers:
            if o["contract_id"] == contract_id and o["present"] and o["top_label"] is not None:
                tops.setdefault(o["top_label"], []).append(o["alias"])
        if len(tops) > 1:
            disagreements.append({"contract_id": contract_id, "positions": [{"label": label_, "aliases": sorted(names)} for label_, names in sorted(tops.items())]})

    body = {
        "schema": "S15_RUNTIME_RECEIPT_V1",
        "runtime": {"name": RUNTIME_NAME, "version": RUNTIME_VERSION},
        "observation": {"observation_id": observation["observation_id"], "state_hash": observation["state_hash"], "actor": observation["actor"]},
        "inputs": {
            "policy_id": policy["policy_id"], "policy_revision": policy["policy_revision"], "decision_vector_id": vector["decision_vector_id"],
            "contract_ids": sorted({o["contract_id"] for o in observers}), "bundle_ids": sorted(o["bundle_id"] for o in observers),
        },
        "observers": observers, "disagreements": disagreements, "escalation_trace": trace, "escalation": escalation,
        "proposed_action": proposal, "authority": authority, "authority_trace": authority_trace,
        "disposition": disposition, "disposition_target": target,
        "cost": {"units": total, "backbone": backbone, "observers": heads, "label": label},
    }
    receipt = model.seal(body)
    model.check_record(receipt)
    model.check_record(receipt["escalation"])
    if receipt["authority"] is not None:
        model.check_record(receipt["authority"])
    return receipt, canon.canonical_bytes(receipt)


def replay(world: model.World, observation: dict, vector: dict, receipt_bytes: bytes) -> tuple[bool, str]:
    """Re-runs the inputs and compares bytes with a stored receipt."""
    _, fresh = run(world, observation, vector)
    if fresh == receipt_bytes:
        return True, "byte-identical"
    return False, f"receipt differs: stored {canon.sha256_id(receipt_bytes)} vs replayed {canon.sha256_id(fresh)}"
