"""Fixed-vocabulary, deterministic stage policy evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from .authority import AuthorityState, utc
from .graph import SAFE
from .identity import require_id

REQUIRES = {
    "scientific_spec": "SEALED",
    "execution_spec": "SEALED",
    "predecessor_seal": "VERIFIED",
    "actor": "AUTHORIZED",
    "resource.gpu": "LEASED",
}
FORBIDS = frozenset({"truth_label_contact", "eval_panel_opened"})


def validate_policy(policy: dict) -> dict:
    if set(policy) != {"schema", "stage_id", "version", "requires", "forbids"}:
        raise ValueError("policy fields do not match schema")
    if policy["schema"] != "KAMMI_POLICY_V1":
        raise ValueError("unsupported policy schema")
    for key in ("stage_id", "version"):
        if not isinstance(policy[key], str) or not SAFE.fullmatch(policy[key]):
            raise ValueError(f"invalid policy {key}")
    requires, forbids = policy["requires"], policy["forbids"]
    if not isinstance(requires, dict) or not isinstance(forbids, dict):
        raise ValueError("policy predicates must be objects")
    for key, value in requires.items():
        if key not in REQUIRES or value != REQUIRES[key]:
            raise ValueError("unsupported required predicate")
    for key, value in forbids.items():
        if key not in FORBIDS or value is not True:
            raise ValueError("unsupported forbidden predicate")
    return policy


class PolicyState:
    def __init__(self) -> None:
        self.policies: dict[str, dict] = {}
        self.specs: dict[tuple[str, str, str], dict] = {}
        self.verified_seals: set[tuple[str, str, str]] = set()
        self.contacts: list[dict] = []
        self.exposures: list[dict] = []
        self.authorizations: dict[str, dict] = {}
        self.decisions: list[dict] = []

    def apply(self, kind: str, payload: dict, event_id: str) -> None:
        if kind == "PolicyRegistered":
            self.policies[payload["stage_id"]] = payload
        elif kind == "SpecBound":
            key = (payload["run_id"], payload["stage_id"], payload["spec_kind"])
            self.specs[key] = payload
        elif kind == "SealVerified":
            self.verified_seals.add((payload["run_id"], payload["stage_id"], payload["root"]))
        elif kind == "ContactRecorded":
            self.contacts.append(payload)
        elif kind == "ExposureOpened":
            self.exposures.append(payload)
        elif kind in ("PolicyEvaluated", "AuthorizationDenied"):
            self.decisions.append(payload)
        elif kind == "AuthorizationIssued":
            self.authorizations[event_id] = payload

    def current_policy_hash(self, stage_id: str) -> str | None:
        item = self.policies.get(stage_id)
        return item["policy_hash"] if item else None

    def authorization_valid(self, identity: str, actor_id: str, run_id: str,
                            stage_id: str, now: datetime | None = None) -> bool:
        issued = self.authorizations.get(identity)
        if issued is None:
            return False
        return (
            issued["actor_id"] == actor_id
            and issued["run_id"] == run_id
            and issued["stage_id"] == stage_id
            and issued["policy_hash"] == self.current_policy_hash(stage_id)
            and issued.get("spec_bindings", {}) == self.binding_snapshot(run_id, stage_id)
            and utc(issued["expires_utc"]) > (now or datetime.now(timezone.utc))
        )

    def binding_snapshot(self, run_id: str, stage_id: str) -> dict:
        return {kind: bound["artifact_id"] for (run, stage, kind), bound in self.specs.items()
                if run == run_id and stage == stage_id}


def evaluate(
    policy: dict, state: PolicyState, authority: AuthorityState,
    run_id: str, actor_id: str, stage_id: str,
    lease_valid: bool = False,
) -> tuple[str, list[dict], str | None]:
    validate_policy(policy)
    registered = state.policies.get(stage_id)
    if registered is None:
        return "DENIED", [{"predicate": "policy_registered", "pass": False}], None
    policy_hash = registered["policy_hash"]
    require_id(policy_hash)
    grant = authority.matching_grant(
        actor_id, "authorize_stage", run_id, stage_id, policy_hash
    )
    checks: list[dict] = [{"predicate": "scoped_actor_grant", "pass": grant is not None}]
    for predicate in sorted(policy["requires"]):
        if predicate == "scientific_spec":
            passed = (run_id, stage_id, "SCIENTIFIC") in state.specs
        elif predicate == "execution_spec":
            passed = (run_id, stage_id, "EXECUTION") in state.specs
        elif predicate == "predecessor_seal":
            passed = any(r == run_id and s == stage_id for r, s, _ in state.verified_seals)
        elif predicate == "actor":
            passed = grant is not None
        elif predicate == "resource.gpu":
            passed = lease_valid
        else:
            raise ValueError("unsupported predicate")
        checks.append({"predicate": predicate, "pass": passed})
    for predicate in sorted(policy["forbids"]):
        if predicate == "truth_label_contact":
            present = any(
                c["run_id"] == run_id and c["contact_class"] == "TRUTH_LABEL"
                for c in state.contacts
            )
        elif predicate == "eval_panel_opened":
            present = any(e["run_id"] == run_id for e in state.exposures)
        else:
            raise ValueError("unsupported predicate")
        checks.append({"predicate": predicate, "pass": not present})
    return ("AUTHORIZED" if all(c["pass"] for c in checks) else "DENIED", checks, grant)
