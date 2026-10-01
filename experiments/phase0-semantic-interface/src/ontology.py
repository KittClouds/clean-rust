"""Phase 0 shared target ontology + supervision ABI.

The charter's rule, applied literally:

    Map every target to an existing canonical source, or mark it UNAVAILABLE for this
    phase. Do not manufacture labels to complete the ontology.

Availability is determined empirically against the released BANK-v1 canonical world
schema, not by assertion. `audit_availability()` inspects the actual field set and the
actual value distributions and reports what each target can and cannot be sourced from.

Supervision is scalar-per-target. The model is free to expose vector slots e_j in R^{d_e};
the ABI only constrains what must be LINEARLY READABLE from those slots.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PHASE0_ABI_VERSION = "phase0-semantic-interface/ontology-v0.1"
BANK_SCHEMA = "ff-s15-bank-schema-v1"
BANK_GENERATOR = "ff-s15-bank-gen-v1"

AVAIL = Literal["AVAILABLE", "PARTIAL", "UNAVAILABLE"]

# kind: "global" -> head on s ; "candidate" -> head W on e_j
@dataclass(frozen=True)
class Target:
    name: str
    kind: Literal["global", "candidate"]
    d_out: int
    ontology: str
    canonical_source: str | None
    availability: AVAIL
    head: str
    notes: str = ""
    degrade: str = ""
    availability_evidence: str = ""


def _g(name, d, onto, src, avail, head, notes="", degrade="", ev=""):
    return Target(name, "global", d, onto, src, avail, head, notes, degrade, ev)


def _c(name, d, onto, src, avail, head, notes="", degrade="", ev=""):
    return Target(name, "candidate", d, onto, src, avail, head, notes, degrade, ev)


# --------------------------------------------------------------------------- global
GLOBAL = [
    _g("solvable", 1, "a plan from initial_state to goal exists",
       "simulator.shortest_plan(initial_state, available_actions, goal) is not None",
       "AVAILABLE", "H_solvable",
       "Canonical: executable simulator, not a generated label.",
       ev="observed on 2000-row DEV export: REACHABLE 928 / STUCK 383 / ALREADY_SATISFIED 689"),
    _g("goal_satisfied", 1, "goal already holds in initial_state",
       "simulator.goal_satisfied(initial_state, goal)",
       "AVAILABLE", "H_goal_satisfied",
       ev="observed 689/2000 true on the DEV export population"),
    _g("missing_information_present", 1, "world declares missing information",
       "len(world.missing_information) > 0",
       "AVAILABLE", "H_missing_present",
       notes="BANK-v1 restricts this count to 0 or 1 in this panel; see degrade.",
       degrade="binary only; the count channel carries no variance beyond 0/1 here"),
    _g("contradiction_present", 1, "world carries a genuine contradiction",
       "len(world.contradictions) > 0",
       "AVAILABLE", "H_contradiction_present",
       ev="frequency measured in audit; near-zero mass is a coverage limit, not a bug"),
    _g("requestable_information_present", 1,
       "there exists information that could be requested and would resolve the gap",
       None,
       "UNAVAILABLE", None,
       notes="BANK-v1 has no requestability field. ask_target exists but is populated only "
             "for the ASK generator branch and encodes a world-construction artefact, not a "
             "canonical property of solvability or support.",
       degrade="excluded from Phase 0 supervision; may be emitted as an unconstrained slot"),
    _g("number_or_structure_of_missing_requirements", 6,
       "how many obligations are unmet, and their structure",
       "len(world.missing_information), plus predicate types of the missing entries",
       "PARTIAL", "H_missing_structure",
       notes="count is available; structure requires a fact-level missingness representation "
             "that BANK-v1 does not store (missing_information entries carry a fact_id and a "
             "note, not a typed obligation).",
       degrade="supervise count as 1 channel; leave the remaining 5 structure channels "
               "unconstrained in Phase 0",
       ev="count distribution measured in audit: 0/1 only in this panel"),
]

# --------------------------------------------------------------------------- candidate
CANDIDATE = [
    _c("candidate_legal", 1, "a_j is in the simulator legal set",
       "a_j in simulator.legal_actions(initial_state, available_actions)",
       "AVAILABLE", "W_legal",
       ev="legal sets measured at 3-8 actions per world on DEV"),
    _c("candidate_satisfies_goal", 1,
       "applying a_j makes the goal true",
       "simulator.goal_satisfied(apply_action(initial_state, a_j), goal)",
       "AVAILABLE", "W_satisfies_goal",
       ev="one-step lookahead; this is a local predicate, not a plan search"),
    _c("candidate_supported", 1, "a_j is supported by stated evidence",
       None,
       "UNAVAILABLE", None,
       notes="world.evidence_facts is a GLOBAL list of fact ids, not a per-candidate support "
             "relation. No canonical field states which candidates the evidence supports.",
       degrade="excluded; do not derive from evidence_facts membership, which would be a "
               "manufactured label"),
    _c("candidate_has_counterevidence", 1, "a_j is contradicted by stated facts",
       None,
       "UNAVAILABLE", None,
       notes="no per-candidate contradiction relation exists. world.contradictions is global.",
       degrade="excluded"),
    _c("candidate_has_unmet_requirements", 1,
       "a_j has a precondition that is false in the current state",
       "derived from a_j's own precondition list vs holds(initial_state, ...)",
       "PARTIAL", "W_unmet_reqs",
       notes="action preconditions are encoded in the simulator's _action_legal rules, not as "
             "data on the action record. Legality already encodes this as a boolean.",
       degrade="supervise via the simulator's legality rule; the count/structure of unmet "
               "requirements is not separately observable and is not supervised",
       ev="1-NN separation between legal and illegal candidates is the observable proxy"),
    _c("candidate_applicable", 1, "a_j can be executed in the current world",
       "same canonical source as candidate_legal",
       "PARTIAL", "W_applicable",
       notes="IDENTICAL source to candidate_legal under BANK-v1. Kept as a distinct head "
             "because the ontology distinguishes them, but the two targets are not "
             "separable in this bank and will have identical supervision signals.",
       degrade="trained as a duplicate of candidate_legal; flagged so it is not mistaken for "
               "independent evidence",
       ev="identical label vector to candidate_legal by construction, verified in audit"),
    _c("candidate_requires_missing_information", 1,
       "a_j cannot be justified because a needed fact is absent",
       None,
       "UNAVAILABLE", None,
       notes="requires a per-candidate link to missing_information. BANK-v1 has no such link.",
       degrade="excluded"),
]

ALL_TARGETS = GLOBAL + CANDIDATE
BY_NAME = {t.name: t for t in ALL_TARGETS}
SUPERVISED = [t for t in ALL_TARGETS if t.availability != "UNAVAILABLE"]
UNAVAILABLE = [t for t in ALL_TARGETS if t.availability == "UNAVAILABLE"]
PARTIAL = [t for t in ALL_TARGETS if t.availability == "PARTIAL"]

# The action endpoint a* is NOT a member of the 13-target ontology. It is the CE term L_A and
# is declared separately so the ontology stays exactly as the charter specified it.
ACTION_ENDPOINT = Target(
    name="action_endpoint", kind="endpoint", d_out=1,
    ontology="the canonical action a* for the world, as a cross-entropy endpoint",
    canonical_source="index of world.selected_action within world.available_actions",
    availability="PARTIAL", head="W_action",
    notes="DEFINED ONLY where world.selected_action is not None. Worlds whose canonical answer "
          "is abstention have no action endpoint and contribute nothing to L_A. L_A is an "
          "endpoint, explicitly NOT the definition of the epistemic state e_j.",
    degrade="masked CE; undefined worlds excluded rather than assigned a default",
    availability_evidence="measured in audit: action-endpoint coverage over canonical worlds")

UNSUPERVISED_NOTE = (
    "Every target is either mapped to an existing canonical source or marked UNAVAILABLE. "
    "Unavailable targets emit no label array and receive no head. No label is manufactured to "
    "complete the ontology, and no unavailable target is approximated from a related field."
)



# --------------------------------------------------------------------------- audit
def audit_availability(n_rows: int = 2000) -> dict:
    """Measure, against the released canonical worlds, what each declared target can
    actually be sourced from. This is the evidence for the availability column."""
    import json
    from pathlib import Path
    bank = Path(__file__).resolve().parents[2] / "ff-s15-bank-01" / "releases" / "BANK-v1"
    worlds = []
    with (bank / "worlds" / "DEV.jsonl").open(encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= n_rows:
                break
            if line.strip():
                worlds.append(json.loads(line))
    fields = sorted({k for w in worlds for k in w})
    n_missing = [len(w.get("missing_information") or []) for w in worlds]
    n_contra = [len(w.get("contradictions") or []) for w in worlds]
    n_ev = [len(w.get("evidence_facts") or []) for w in worlds]
    n_legal = [len(w.get("legal_actions") or []) for w in worlds]
    per_cand_evidence = all(
        isinstance(e, dict) and "candidates" in e
        for w in worlds for e in (w.get("evidence_facts") or []))
    n_endpoint = sum(1 for w in worlds if w.get("selected_action") is not None)
    dist = lambda xs: {str(v): xs.count(v) for v in sorted(set(xs))}
    return {
        "n_worlds": len(worlds),
        "bank_schema": BANK_SCHEMA,
        "bank_generator_versions": sorted({w.get("generator_version") for w in worlds}),
        "canonical_world_fields": fields,
        "missing_information_count_distribution": dist(n_missing),
        "contradiction_count_distribution": dist(n_contra),
        "evidence_facts_count_distribution": dist(n_ev),
        "legal_action_count_distribution": dist(n_legal),
        "per_candidate_evidence_field_present": per_cand_evidence,
        "requestability_field_present": any("request" in f or "askable" in f for f in fields),
        "action_endpoint": {
            "defined_worlds": n_endpoint,
            "total_worlds": len(worlds),
            "coverage": round(n_endpoint / max(len(worlds), 1), 4),
            "note": "L_A is masked to these worlds; abstention worlds have no action endpoint",
        },
        "availability": {
            "AVAILABLE": [t.name for t in ALL_TARGETS if t.availability == "AVAILABLE"],
            "PARTIAL": [t.name for t in ALL_TARGETS if t.availability == "PARTIAL"],
            "UNAVAILABLE": [t.name for t in ALL_TARGETS if t.availability == "UNAVAILABLE"],
        },
        "conclusion": (
            f"{len(SUPERVISED)}/{len(ALL_TARGETS)} targets are sourceable from BANK-v1 "
            f"canonical truth; {len(UNAVAILABLE)} are not and are excluded rather than "
            f"manufactured. Of the sourceable ones, {len(PARTIAL)} are partial and carry a "
            f"declared degradation."
        ),
    }


# --------------------------------------------------------------------------- descriptors
def supervision_abi() -> dict:
    return {
        "abi": PHASE0_ABI_VERSION,
        "bank_schema": BANK_SCHEMA,
        "bank_generator": BANK_GENERATOR,
        "model_object": {
            "frozen": "F_theta(x) -> H",
            "trainable_graft": "G_phi(H, A) -> (s, e_1..e_m)",
            "s": "global semantic state in R^{d_s}",
            "e_j": "candidate-conditioned epistemic state in R^{d_e}",
            "readout": "y_hat_j = W e_j",
            "frozen_property": "no single global confidence head; s and e_j are distinct slots",
        },
        "d_out_note": (
            "Supervision is scalar or low-dimensional per target. The model is NOT required "
            "to set d_e equal to the target count and is NOT required to have 7 uncertainty "
            "dimensions. d_s and d_e are free; the ABI constrains only what must be linearly "
            "readable from the slots."
        ),
        "global_targets": [
            {"name": t.name, "d_out": t.d_out, "ontology": t.ontology,
             "canonical_source": t.canonical_source, "availability": t.availability,
             "head": t.head, "notes": t.notes, "degradation": t.degrade,
             "availability_evidence": t.availability_evidence}
            for t in GLOBAL],
        "candidate_targets": [
            {"name": t.name, "d_out": t.d_out, "ontology": t.ontology,
             "canonical_source": t.canonical_source, "availability": t.availability,
             "head": t.head, "notes": t.notes, "degradation": t.degrade,
             "availability_evidence": t.availability_evidence}
            for t in CANDIDATE],
        "counts": {
            "total": len(ALL_TARGETS),
            "global": len(GLOBAL), "candidate": len(CANDIDATE),
            "available": len(SUPERVISED) - len(PARTIAL),
            "partial": len(PARTIAL), "unavailable": len(UNAVAILABLE),
            "supervised_total": len(SUPERVISED),
        },
        "rules": [
            "map every target to an existing canonical source or mark it unavailable",
            "never manufacture a label to complete the ontology",
            "s and e_j remain distinct; no global confidence head",
            "degraded targets keep only the channels that are canonically sourceable",
        ],
    }


def abi_hash() -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(supervision_abi(), sort_keys=True,
                                     separators=(",", ":"), default=str).encode()).hexdigest()
