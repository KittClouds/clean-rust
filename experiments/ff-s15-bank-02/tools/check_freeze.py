"""Constitution verifier for BANK-v2: the freeze document and its machine-readable companion must agree with each other and with themselves.

  python tools/check_freeze.py            # check only
  python tools/check_freeze.py --seal     # check, and on success write the sha256 sidecar

Every check computes its predicate from the files; a check that cannot compute fails closed. Nothing here is a hardcoded True.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MD = ROOT / "BANK-V2-FREEZE.md"
OBJ = ROOT / "bank-v2-objects.json"
SIDE = ROOT / "bank-v2-objects.sha256"

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, predicate, detail: str = "") -> None:
    try:
        ok = bool(predicate())
        msg = detail if ok else (detail or "predicate false")
    except Exception as exc:  # fail closed
        ok, msg = False, f"could not compute: {exc!r}"
    RESULTS.append((name, ok, msg))


def _sim():
    os.environ["BANK2_SEALING"] = "1"
    sys.path.insert(0, str(ROOT / "src"))
    from bank2 import sim
    return sim


def _code_preconditions():
    sim = _sim()
    samples = {"MOVE": dict(agent="a", src="l0", dst="l1"), "TAKE": dict(agent="a", obj="o", source="l0", at="l0"), "DROP": dict(agent="a", obj="o", target="l0", at="l0"),
               "TRANSFER": {"from": "a", "to": "b", "obj": "o", "at": "l0"}, "OPEN": dict(agent="a", target="c", at="l0"), "CLOSE": dict(agent="a", target="c", at="l0"),
               "ACTIVATE": dict(agent="a", target="s", at="l0"), "DEACTIVATE": dict(agent="a", target="s", at="l0"), "WAIT": dict(agent="a")}
    free = []
    for t, args in samples.items():
        act = sim.Act(sim.make_action(t, **args), {})
        if not act.pre and not act.neg:
            free.append(t)
    return sorted(free)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


d = json.loads(OBJ.read_text(encoding="utf-8"))
md = MD.read_text(encoding="utf-8")

# ------------------------------------------------------------------ versions and lineage
check("json_version_is_0.7", lambda: d["version"] == "0.7" and d["supersedes_version"] == "0.6")
check("md_version_matches_json", lambda: f"constitution v{d['version']}" in md.splitlines()[0] and f"**Version:** {d['version']}" in md)
check("md_names_the_accepted_prior_hash", lambda: d["accepted_prior_versions"][-1]["sha256"] in md)
check("prior_versions_chain_is_well_formed", lambda: [v["version"] for v in d["accepted_prior_versions"]] == ["0.2", "0.3", "0.4", "0.5", "0.6"] and all(re.fullmatch(r"[0-9a-f]{64}", v["sha256"]) and v["accepted"] for v in d["accepted_prior_versions"]))
check("prior_hashes_are_distinct", lambda: len({v["sha256"] for v in d["accepted_prior_versions"]}) == len(d["accepted_prior_versions"]))


def lineage_ok():
    files = d["lineage_archive"]["files"]
    prior = {v["version"]: v["sha256"] for v in d["accepted_prior_versions"]}
    for ver, arch in files.items():
        if not (sha(ROOT / arch["objects"]) == arch["objects_sha256"] == prior[ver] and sha(ROOT / arch["freeze_md"]) == arch["freeze_md_sha256"]):
            return False
    return sorted(files) == ["0.5", "0.6"]


check("archived_prior_files_rehash_to_the_recorded_hashes", lineage_ok)

# ------------------------------------------------------------------ vocabulary and slots
OPS = [p["name"] for p in d["relation_vocabulary"]["operational_predicates"]]
check("six_operational_predicates", lambda: OPS == ["AT", "CONNECTED", "BLOCKED", "HOLDS", "CONTAINS", "STATE"])
FACT_LANG = OPS + ["REL"]
check("fact_language_is_the_seven_predicates", lambda: sorted(d["relation_vocabulary"]["canonical_fact_language"]["permitted_predicates"]) == sorted(FACT_LANG) and d["relation_vocabulary"]["canonical_fact_language"]["permitted_count"] == 7)
FORBIDDEN = {"SUPPORTS", "CONTRADICTS", "REQUIRES", "ACHIEVES", "CAUSES", "APPLICABLE_TO", "REQUESTABLE"}
check("forbidden_predicates_absent_from_fact_language", lambda: not (FORBIDDEN & set(FACT_LANG)))
slots = d["openness"]["slots"]
members = [m for s in slots.values() for m in s["members"]]
check("five_slots", lambda: len(slots) == 5 == d["openness"]["slot_count"])
check("every_predicate_in_exactly_one_slot", lambda: sorted(members) == sorted(FACT_LANG) and len(members) == len(set(members)))
check("open_slots_are_object_location_and_entity_attribute", lambda: sorted(k for k, s in slots.items() if s["openness"] == "OPEN") == ["entity_attribute", "object_location"])
check("only_object_location_is_disjunctive", lambda: [k for k, s in slots.items() if s["disjunctive"]] == ["object_location"])

# ------------------------------------------------------------------ requirement object (O11, ruling C)
qd = d["required_facts"]["query_derivation"]
check("query_is_requirement_objects", lambda: qd["method"] == "REQUIREMENT_OBJECTS_WITH_MINIMAL_SUPPORT_ALTERNATIVES" and qd["requirement_object"]["fields"] == ["requirement_id", "slot", "subject", "required", "support_alternatives"])
check("requirement_subject_covers_every_slot", lambda: set(qd["requirement_object"]["subject"]) == set(slots))
check("three_derived_fields_distinct", lambda: set(qd["derived_fields_never_collapsed"]) == {"required_requirements", "support_facts", "necessary_facts"})
check("four_counterfactual_checks", lambda: len(qd["counterfactual_deletion_gate"]["checks"]) == 4)
check("no_open_dependency_left_on_gates", lambda: all("open_dependency" not in g for g in d["seal_gates"]["gates"]))
check("O11_closed", lambda: [o["state"] for o in d["open_items"] if o["id"] == "O11"] == ["CLOSED_v0.6"])
check("only_O7_is_deferred", lambda: sorted(o["id"] for o in d["open_items"] if not o["state"].startswith("CLOSED") and not o["state"].startswith("DRAFTED")) == ["O7"])


def ruling_example():
    """The program owner's worked example, executed: one object-location obligation with three evidence forms."""
    alts = [frozenset({"AT(obj,r2)"}), frozenset({"HOLDS(a3,obj)", "AT(a3,r2)"}), frozenset({"CONTAINS(b4,obj)", "AT(b4,r2)"})]
    satisfied = lambda sup: any(a <= sup for a in alts)
    none_observed = set()
    m_size = sum(1 for r in [alts] if not satisfied(none_observed))
    one_route = {"AT(obj,r2)"}
    both = {"AT(obj,r2)", "HOLDS(a3,obj)", "AT(a3,r2)"}
    complete = [a for a in alts if a <= both]
    union = set().union(*complete)
    necessary = {f for f in both if not satisfied(both - {f})}
    return (m_size == 1                                  # one unresolved obligation, not three or five facts
            and satisfied(one_route)
            and not satisfied(both - union)              # test 1: delete every complete alternative
            and satisfied(both - {"AT(obj,r2)"})         # test 3: one member of a redundant proof is not irrelevance
            and necessary == set()                       # redundant proofs leave no individually necessary fact
            and {f for f in one_route if not satisfied(one_route - {f})} == {"AT(obj,r2)"})  # test 4: a lone proof's fact is necessary


check("ruling_example_behaves_as_ruled", ruling_example)

# ------------------------------------------------------------------ dispositions, reasons, algebra
DISP = [x["id"] for x in d["dispositions"]]
check("five_dispositions", lambda: DISP == ["EXECUTE", "NOOP", "ASK", "ESCALATE", "DECLINE_UNAVAILABLE"])
reasons = {r["id"]: r for r in d["reasons"]}
check("sixteen_unique_reasons", lambda: len(d["reasons"]) == 16 == len(reasons))
check("every_reason_has_one_disposition", lambda: all(r["disposition"] in DISP + ["NONE"] for r in reasons.values()))
FIELD_DISP = {"ASK", "ESCALATE", "DECLINE_UNAVAILABLE"}
check("reason_field_rule_matches_reason_table", lambda: all((r["disposition"] in FIELD_DISP) == r["in_reason_field"] for r in reasons.values()))
check("reason_field_rule_is_stated_in_json_and_md", lambda: "{ASK, ESCALATE, DECLINE_UNAVAILABLE}" in d["reason_field_rule"] and "`disposition ∈ {ASK, ESCALATE, DECLINE_UNAVAILABLE}`" in md)

order = d["decision_algebra"]["order"]
emitted: dict[str, set[str]] = {}
for line in order:
    step = line.split("_")[0]
    for rid in reasons:
        if re.search(rf"\b{rid}\b", line):
            emitted.setdefault(rid, set()).add(step)
    m = re.search(r"\{([A-Z_ |]+)\}", line)
    if m:
        for rid in re.split(r"\s*\|\s*", m.group(1).strip()):
            emitted.setdefault(rid, set()).add(step)
check("every_reason_value_is_emitted_by_an_algebra_step", lambda: {r for r, v in reasons.items() if v["in_reason_field"]} <= set(emitted), "unreachable: " + ", ".join(sorted({r for r, v in reasons.items() if v["in_reason_field"]} - set(emitted))))
check("no_algebra_step_emits_an_unknown_reason", lambda: all(r in reasons for r in emitted))
check("emitting_steps_in_json_match_the_algebra", lambda: all(emitted[r] == {x.strip() for x in reasons[r]["emitting_step"].split(" (")[0].split(",")} for r in reasons if reasons[r]["in_reason_field"]))
check("out_of_scope_precedes_the_plan_search", lambda: "1a" in emitted["OUT_OF_SCOPE"] and "5" not in emitted["OUT_OF_SCOPE"])
check("referential_rules_defined", lambda: set(d["decision_algebra"]["referential_rules"]) == {"AMBIGUOUS_REFERENCE", "UNKNOWN_ENTITY", "UNKNOWN_TARGET", "OUT_OF_SCOPE"})
fams = {f["id"]: f for f in d["missingness_taxonomy"]["families"]}
check("missingness_families_map_to_dispositions", lambda: [(fams[k]["disposition"], fams[k]["reason"]) for k in ("NECESSARY_MISSING_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE", "NECESSARY_MISSING_REQUESTABLE", "MULTIPLE_REQUIRED_MISSING")] == [("DECLINE_UNAVAILABLE", "NECESSARY_MISSING_UNAVAILABLE"), ("DECLINE_UNAVAILABLE", "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE"), ("ASK", "NECESSARY_MISSING_REQUESTABLE"), ("ESCALATE", "MULTIPLE_REQUIRED_MISSING")])


def taxonomy_total():
    def classify(n_nonreq: int, m: int):
        if m == 0:
            return "none"
        if n_nonreq > 0:
            return "MULTIPLE_REQUIRED_MISSING_UNAVAILABLE" if m >= 2 else "NECESSARY_MISSING_UNAVAILABLE"
        return "MULTIPLE_REQUIRED_MISSING" if m >= 2 else "NECESSARY_MISSING_REQUESTABLE"
    seen = {(n, m): classify(n, m) for m in range(0, 6) for n in range(0, m + 1)}
    return all(v in reasons or v == "none" for v in seen.values()) and len(set(seen.values())) == 5


check("missingness_partition_total_and_disjoint_over_a_grid", taxonomy_total)

# ------------------------------------------------------------------ gates
gates = d["seal_gates"]["gates"]
check("eighteen_gates_G01_to_G18", lambda: [g["id"] for g in gates] == [f"G{i:02d}" for i in range(1, 19)] and d["seal_gates"]["count"] == 18)
check("no_hardcoded_true_gate_allowed", lambda: d["seal_gates"]["hardcoded_true_allowed"] is False and d["seal_gates"]["fails_closed"] is True)
check("every_gate_id_appears_in_the_md_table", lambda: all(re.search(rf"\| {g['id']} \|", md) for g in gates))
check("every_reason_appears_in_the_md", lambda: all(f"`{r}`" in md for r in reasons if reasons[r]["in_reason_field"]))
check("G03_and_G12_carry_the_v0.7_checks", lambda: all(g.get("checks_extended_in") in ("0.6", "0.7") for g in gates if g["id"] in ("G03", "G12", "G17")) and all(g.get("checks_extended_in") == "0.7" for g in gates if g["id"] in ("G03", "G12")))

# ------------------------------------------------------------------ budgets, renderers, interventions, splits
b = d["budgets"]
check("renderer_families_8_plus_4", lambda: d["renderer_system"]["total_families"] == 12 == d["renderer_system"]["seen_families"] + d["renderer_system"]["held_families"] and len(d["renderer_system"]["seen_family_ids"]) == 8 and len(d["renderer_system"]["held_family_ids"]) == 4)
check("core_ood_splits_nine", lambda: len(b["core_ood_splits"]) == 9 == len(set(b["core_ood_splits"])))
check("canonical_budget_floor_725000", lambda: b["splits"]["TRAIN"] + b["splits"]["DEV"] + b["splits"]["TEST-IID"] + 9 * b["per_ood_split"] == b["total_canonical_worlds_floor"] == 725000)
check("rendered_rows_identity_800000", lambda: b["total_canonical_worlds_floor"] + 3 * b["per_ood_split"] == 800000)
check("paired_interventions_P1_to_P12", lambda: [p["id"] for p in d["paired_interventions"]] == [f"P{i}" for i in range(1, 13)])
check("collision_matrix_covers_every_split", lambda: {m["split"] for m in d["collision_policy"]["matrix"]} == set(b["core_ood_splits"]) | {"TEST-IID"})
check("external_rows_zero", lambda: d["external_policy"]["core_rows_imported"] == 0)
check("eight_structural_ecology_parameters", lambda: len(d["external_policy"]["structural_ecology_parameters"]["parameters"]) == 8 and len(set(d["external_policy"]["structural_ecology_parameters"]["parameters"])) == 8)
check("code_authorized_only_with_a_stated_condition", lambda: d["code_authorized"] is True and "v0.6 seal" in d["code_authorized_condition"])
cov = d["action_algebra"]["coverage_receipt"]
check("wait_is_the_only_exempt_action_and_only_for_the_illegal_cell", lambda: cov["precondition_free_actions"] == ["WAIT"] and cov["exempt_cells"] == {"WAIT": ["illegal"]})
check("the_code_agrees_the_only_precondition_free_action_is_wait", lambda: _code_preconditions() == ["WAIT"])
check("the_code_action_list_equals_the_freeze", lambda: list(_sim().ENV_ACTIONS) == d["action_namespace"]["ENVIRONMENT_ACTIONS"])
check("v0.7_conventions_declared", lambda: set(d["evaluator_conventions_v0_7"]) >= {"reports", "conflict", "uncertain", "observation_sufficiency", "step_1a_worlds", "time", "closed_available_set", "policy_declared_in_text"})

# ------------------------------------------------------------------ report
bad = [r for r in RESULTS if not r[1]]
for name, ok, msg in RESULTS:
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  -- {msg}"))
obj_hash, md_hash = sha(OBJ), sha(MD)
print(f"checks={len(RESULTS)} failed={len(bad)}")
print(f"bank-v2-objects.json sha256 {obj_hash}")
print(f"BANK-V2-FREEZE.md   sha256 {md_hash}")
if bad:
    print("FAIL")
    sys.exit(1)
if "--seal" in sys.argv:
    SIDE.write_text(f"{obj_hash}  bank-v2-objects.json\n{md_hash}  BANK-V2-FREEZE.md\n", encoding="ascii", newline="\n")
    print("sidecar written")
print("ALL_CHECKS_PASS")
