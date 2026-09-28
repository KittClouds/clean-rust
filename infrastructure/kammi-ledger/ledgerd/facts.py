"""Small, centrally owned custody vocabulary for imported historical assertions.

Assertions describe what a cited artifact says. They never grant authorization.
"""

from __future__ import annotations

from .graph import SAFE
from .identity import require_id, typed_id

KINDS = frozenset({"ATTEMPT", "SUPERSESSION", "CONTACT", "EVIDENCE_ACCESS", "HEAD"})
VALUES = {
    "ATTEMPT": frozenset({"PASS", "STOP", "UNKNOWN"}),
    "SUPERSESSION": frozenset({"DECLARED"}),
    "CONTACT": frozenset({"YES", "NO_ATTESTED", "UNKNOWN"}),
    "EVIDENCE_ACCESS": frozenset({"YES", "NO_ATTESTED", "UNKNOWN"}),
    "HEAD": frozenset({"SEALED", "SUPERSEDED", "UNKNOWN"}),
}


def validated_fact(fact: dict, registered: set[str], runs: set[str]) -> dict:
    required = {"run_id", "kind", "subject", "object", "value", "evidence_artifact", "scope"}
    if set(fact) != required:
        raise ValueError("custody fact fields must match the central vocabulary")
    kind = fact["kind"]
    if kind not in KINDS or fact["value"] not in VALUES[kind]:
        raise ValueError("unsupported custody fact kind/value")
    if fact["run_id"] not in runs:
        raise ValueError("unknown run")
    for field in ("run_id", "subject", "object", "scope"):
        if not isinstance(fact[field], str) or not SAFE.fullmatch(fact[field]):
            raise ValueError(f"invalid {field}")
    evidence = require_id(fact["evidence_artifact"])
    if evidence not in registered:
        raise ValueError("fact evidence must be a registered artifact")
    return {**fact, "fact_id": typed_id("fact", fact)}
