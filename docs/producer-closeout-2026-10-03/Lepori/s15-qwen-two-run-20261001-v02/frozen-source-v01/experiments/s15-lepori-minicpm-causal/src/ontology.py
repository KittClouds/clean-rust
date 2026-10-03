"""Target ontology for the Lepori causal lane.

Sourceability is a property of the SHARED BANK-v1 truth contract and the shared executable
simulator, NOT of a substrate. This file therefore restates the same 13 targets, the same
independent canonical sources, and the same alias map as every other lane. It is re-verified
numerically on this lane's population in src/gate.py rather than assumed.

Inherited lesson: 13 heads resolve to 6 INDEPENDENT CANONICAL SOURCES. Aliases exist for ABI
compatibility and must never receive a second unit of training weight.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Target:
    name: str
    kind: str                 # "global" | "candidate"
    d_out: int
    ontology: str
    canonical_source: str
    availability: str         # AVAILABLE | PARTIAL | UNAVAILABLE
    source_id: str | None
    alias_of: str | None = None
    partial_channels: tuple = ()
    degrade: str = ""
    note: str = ""


GLOBAL = [
    Target("solvable", "global", 1,
           "a plan from initial_state to goal exists",
           "sim.shortest_plan(initial_state, available_actions, goal, max_depth=5) is not None "
           "AND NOT sim.goal_satisfied(initial_state, goal)",
           "AVAILABLE", "SRC-SOLVABILITY"),
    Target("goal_satisfied", "global", 1,
           "the initial state already satisfies the goal",
           "sim.goal_satisfied(initial_state, goal)", "AVAILABLE", "SRC-GOAL-SATISFIED"),
    Target("missing_information_present", "global", 1,
           "the world records at least one missing information requirement",
           "len(world.missing_information) > 0", "AVAILABLE", "SRC-MISSING-INFO-PANEL"),
    Target("contradiction_present", "global", 1,
           "the world records at least one contradiction",
           "len(world.contradictions) > 0", "AVAILABLE", "SRC-CONTRADICTION-PANEL"),
    Target("requestable_information_present", "global", 1,
           "information is available but has not yet been requested",
           "none: BANK-v1 records no field distinguishing unrequested from unrequestable "
           "information", "UNAVAILABLE", None,
           degrade="left unavailable; no proxy manufactured"),
    Target("number_or_structure_of_missing_requirements", "global", 6,
           "how many requirements are missing, and their structure",
           "channel 0 = len(world.missing_information); channels 1-5 = structural detail",
           "PARTIAL", "SRC-MISSING-INFO-PANEL",
           alias_of="missing_information_present", partial_channels=(0,),
           note="BANK-v1 supplies 0/1 only, verified on this lane's population, so channel 0 is "
                "bit-identical to missing_information_present and is NOT an independent source"),
]

CANDIDATE = [
    Target("candidate_legal", "candidate", 1,
           "the candidate action is legal in the initial state",
           "canonical action key in sim.legal_actions(initial_state, available_actions)",
           "AVAILABLE", "SRC-CANDIDATE-LEGALITY"),
    Target("candidate_applicable", "candidate", 1,
           "the candidate action may be taken",
           "IDENTICAL EXPRESSION to candidate_legal", "PARTIAL", "SRC-CANDIDATE-LEGALITY",
           alias_of="candidate_legal",
           note="one canonical source, two heads; agreement is a consistency check, never "
                "independent evidence"),
    Target("candidate_has_unmet_requirements", "candidate", 1,
           "the candidate action has an unmet precondition",
           "NOT candidate_legal (deterministic complement)", "PARTIAL", "SRC-CANDIDATE-LEGALITY",
           alias_of="candidate_legal",
           note="deterministic complement of the same source"),
    Target("candidate_satisfies_goal", "candidate", 1,
           "applying the candidate reaches the goal",
           "sim.goal_satisfied(sim.apply_action(initial_state, a) when legal else "
           "initial_state, goal)", "AVAILABLE", "SRC-CANDIDATE-SATISFIES-GOAL"),
    Target("candidate_supported", "candidate", 1,
           "world facts support the candidate",
           "none: BANK-v1 records no support field", "UNAVAILABLE", None,
           degrade="left unavailable; this is what keeps L_CF dormant"),
    Target("candidate_has_counterevidence", "candidate", 1,
           "world facts count against the candidate",
           "none: BANK-v1 records no counterevidence field", "UNAVAILABLE", None,
           degrade="left unavailable"),
    Target("candidate_requires_missing_information", "candidate", 1,
           "the candidate needs information the world does not record",
           "none: BANK-v1 records no mapping from candidate to missing_information",
           "UNAVAILABLE", None, degrade="left unavailable"),
]

ALL_TARGETS = GLOBAL + CANDIDATE
BY_NAME = {t.name: t for t in ALL_TARGETS}

ACTION_ENDPOINT = Target("selected_action_index", "endpoint", 1,
                        "index of the canonical selected action within available_actions",
                        "world.selected_action matched against the canonical available_actions "
                        "ordering; -1 when selected_action is None",
                        "PARTIAL", "SRC-ACTION-ENDPOINT",
                        note="defined only where a canonical action exists; abstention worlds are "
                             "masked out of the loss and of every metric, never defaulted")

# independent source groups. weighting runs over THESE, not over head count.
GLOBAL_GROUPS = {
    "SRC-SOLVABILITY": ["solvable"],
    "SRC-GOAL-SATISFIED": ["goal_satisfied"],
    "SRC-MISSING-INFO-PANEL": ["missing_information_present",
                               "number_or_structure_of_missing_requirements"],
    "SRC-CONTRADICTION-PANEL": ["contradiction_present"],
}
CAND_GROUPS = {
    "SRC-CANDIDATE-LEGALITY": ["candidate_legal", "candidate_applicable",
                               "candidate_has_unmet_requirements"],
    "SRC-CANDIDATE-SATISFIES-GOAL": ["candidate_satisfies_goal"],
}
ALIAS = {t.name: t.alias_of for t in ALL_TARGETS if t.alias_of}
COUNT_TARGET = "number_or_structure_of_missing_requirements"

SOURCE_SEMANTICS = {
    "SRC-SOLVABILITY": "whether a plan to the goal exists from the initial state",
    "SRC-GOAL-SATISFIED": "whether the initial state already satisfies the goal",
    "SRC-MISSING-INFO-PANEL": "whether any missing information is recorded, and how many "
                              "requirements are missing",
    "SRC-CONTRADICTION-PANEL": "whether any contradiction is recorded",
    "SRC-CANDIDATE-LEGALITY": "whether a candidate action is legal in the initial state",
    "SRC-CANDIDATE-SATISFIES-GOAL": "whether applying a candidate reaches the goal",
    "SRC-ACTION-ENDPOINT": "which canonical action was selected",
}


def n_independent_sources() -> int:
    return len(GLOBAL_GROUPS) + len(CAND_GROUPS)


def registry() -> list[dict]:
    return [{"target_name": t.name, "scope": t.kind.upper(), "d_out": t.d_out,
             "canonical_source_id": t.source_id, "canonical_source": t.canonical_source,
             "source_semantics": SOURCE_SEMANTICS.get(t.source_id, "n/a"),
             "availability": t.availability, "alias_of": t.alias_of,
             "partial_channels": list(t.partial_channels), "note": t.note} for t in ALL_TARGETS]
