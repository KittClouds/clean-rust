"""Canonical latent-world schema for FF-S15-BANK-01. No model contact."""
from __future__ import annotations
SCHEMA_VERSION = "ff-s15-bank-schema-v1"
GENERATOR_VERSION = "ff-s15-bank-gen-v1"
RENDERER_VERSION = "ff-s15-bank-render-v1"
SIMULATOR_VERSION = "ff-s15-bank-sim-v1"

ENTITY_TYPES = ["OBJECT", "AGENT", "LOCATION", "SWITCH", "CONTAINER", "RESOURCE"]
PREDICATES = ["AT", "HAS", "CONNECTED", "REQUIRES", "STATE", "BLOCKED", "ENABLES", "BEFORE", "PART_OF", "OWNS"]
ACTIONS = ["MOVE", "ACTIVATE", "DEACTIVATE", "TAKE", "DROP", "TRANSFER", "OPEN", "CLOSE", "SELECT", "ASSIGN", "REQUEST", "VERIFY", "WAIT", "NOOP"]
DECISIONS = ["ACT", "ASK", "ABSTAIN"]
ABSTAIN_REASONS = ["INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "UNKNOWN_ENTITY", "UNKNOWN_TARGET", "MISSING_ARGUMENT", "NO_VALID_ACTION", "IMPOSSIBLE_GOAL", "AMBIGUOUS_REFERENCE", "MULTIPLE_UNRESOLVED_ACTIONS", "PRECONDITION_UNKNOWN", "OUT_OF_SCOPE", "GOAL_SATISFIED"]
SURFACE_FAMILIES = ["S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11"]
SPLITS = ["TRAIN", "DEV", "TEST-IID", "TEST-LEXICAL", "TEST-ENTITY", "TEST-TEMPLATE", "TEST-COMPOSITION", "TEST-DEPTH", "TEST-ABSTENTION", "TEST-JOINT"]
DIFFICULTY_KEYS = ["entity_count", "relation_count", "relevant_fact_count", "distractor_count", "relation_depth", "plan_depth", "alias_count", "coreference_depth", "negative_fact_count", "state_changes", "missing_fact_count", "contradiction_count", "candidate_action_count", "surface_complexity"]

REQUIRED_WORLD_KEYS = ["world_id", "generator_version", "seed", "entities", "relations", "initial_state", "goal", "available_actions", "legal_actions", "optimal_next_actions", "decision", "selected_action", "resulting_state", "abstain_reason", "missing_information", "contradictions", "evidence_facts", "irrelevant_facts", "difficulty", "surface_family", "split"]

def validate_world(w: dict) -> list[str]:
    errs = []
    for k in REQUIRED_WORLD_KEYS:
        if k not in w:
            errs.append(f"missing:{k}")
    if errs:
        return errs
    if w["decision"] not in DECISIONS:
        errs.append("bad:decision")
    if w["decision"] == "ABSTAIN" and w["abstain_reason"] not in ABSTAIN_REASONS:
        errs.append("bad:abstain_reason")
    if w["decision"] == "ACT" and not w["selected_action"]:
        errs.append("bad:selected_action")
    eids = {e["id"] for e in w["entities"]}
    for f in w["relations"] + w["initial_state"]:
        for a in f.get("args", []):
            if isinstance(a, str) and a.startswith(("e_", "obj_", "ag_", "loc_", "sw_", "cont_", "res_")):
                pass  # symbolic refs allowed; resolved loosely
    if not eids:
        errs.append("bad:entities")
    for k in DIFFICULTY_KEYS:
        if k not in w.get("difficulty", {}):
            errs.append(f"missing:difficulty.{k}")
    return errs
