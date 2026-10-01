"""Phase 3 step 0: target-source identity registry.

Builds a registry from the CANONICAL BANK-v1 truth that this lane's labels are derived from,
verifies every alias claim numerically rather than by name, and records the canonical derivation
of each target.

The point of the audit: whether a target exists is a property of the shared BANK truth contract
and the shared executable simulator, NOT of the substrate. Two lanes that disagree about
sourceability have a mapping bug somewhere, not a substrate difference.

Two targets with the same underlying label vector -- or with a deterministic function of it --
must share one canonical_source_id, so they can never receive two units of training weight.
"""
from __future__ import annotations

import json
from pathlib import Path

import torch

from src.data import build
from src.ontology import BY_NAME, ALL_TARGETS

OUT = Path(r"D:\codex-runs\encoder-contrast-01\phase3")
OUT.mkdir(parents=True, exist_ok=True)
M_CAP = 28
SUFFIX = "-p2"

# Canonical derivations, taken from the exact expressions in src/data.py::build. These are
# properties of the world record plus the shared executable simulator, identical for every
# substrate.
DERIVATION = {
    "solvable": "sim.shortest_plan(initial_state, available_actions, goal, max_depth=5) is not "
                "None AND NOT sim.goal_satisfied(initial_state, goal)",
    "goal_satisfied": "sim.goal_satisfied(initial_state, goal)",
    "missing_information_present": "len(world.missing_information) > 0",
    "contradiction_present": "len(world.contradictions) > 0",
    "requestable_information_present": "UNAVAILABLE: no canonical field; requires asking the "
                                      "simulator for information the world does not record",
    "number_or_structure_of_missing_requirements": "channel 0 = len(world.missing_information); "
                                                   "channels 1-5 = structural detail, UNAVAILABLE "
                                                   "in BANK-v1",
    "candidate_legal": "canonical action key in sim.legal_actions(initial_state, "
                       "available_actions)",
    "candidate_applicable": "IDENTICAL EXPRESSION to candidate_legal",
    "candidate_has_unmet_requirements": "NOT candidate_legal (deterministic complement)",
    "candidate_satisfies_goal": "sim.goal_satisfied(sim.apply_action(initial_state, a) when "
                                "legal else initial_state, goal)",
    "candidate_supported": "UNAVAILABLE: no canonical support field",
    "candidate_has_counterevidence": "UNAVAILABLE: no canonical counterevidence field",
    "candidate_requires_missing_information": "UNAVAILABLE: no canonical mapping from candidate "
                                              "to the world's missing_information records",
}

SOURCE_ID = {
    "solvable": "SRC-SOLVABILITY",
    "goal_satisfied": "SRC-GOAL-SATISFIED",
    "missing_information_present": "SRC-MISSING-INFO-PANEL",
    "contradiction_present": "SRC-CONTRADICTION-PANEL",
    "requestable_information_present": None,
    "number_or_structure_of_missing_requirements": "SRC-MISSING-INFO-PANEL",
    "candidate_legal": "SRC-CANDIDATE-LEGALITY",
    "candidate_applicable": "SRC-CANDIDATE-LEGALITY",
    "candidate_has_unmet_requirements": "SRC-CANDIDATE-LEGALITY",
    "candidate_satisfies_goal": "SRC-CANDIDATE-SATISFIES-GOAL",
    "candidate_supported": None,
    "candidate_has_counterevidence": None,
    "candidate_requires_missing_information": None,
}

ALIAS_OF = {
    "candidate_applicable": "candidate_legal",
    "candidate_has_unmet_requirements": "candidate_legal",
    "number_or_structure_of_missing_requirements": "missing_information_present",
}

SOURCE_SEMANTICS = {
    "SRC-SOLVABILITY": "whether a plan to the goal exists from the initial state",
    "SRC-GOAL-SATISFIED": "whether the initial state already satisfies the goal",
    "SRC-MISSING-INFO-PANEL": "whether the world records any missing information, and how many "
                              "requirements are missing (BANK-v1 supplies the 0/1 count only)",
    "SRC-CONTRADICTION-PANEL": "whether the world records any contradiction",
    "SRC-CANDIDATE-LEGALITY": "whether a candidate action is legal in the initial state",
    "SRC-CANDIDATE-SATISFIES-GOAL": "whether applying a candidate reaches the goal",
}


def main() -> int:
    tr = build("TRAIN", "encoder", 20000, prim_suffix=SUFFIX, m_cap=M_CAP)
    dv = build("DEV", "encoder", 2000, prim_suffix=SUFFIX, m_cap=M_CAP)
    g, c = tr["global_labels"], tr["cand_labels"]
    mt = tr["H"]["cand_mask"] > 0
    gd, cd = dv["global_labels"], dv["cand_labels"]
    mtd = dv["H"]["cand_mask"] > 0

    def eq(a, b, m=None):
        if m is None:
            return bool(torch.equal(a, b))
        return bool(torch.equal(a[m], b[m]))

    # ---- empirical verification of every alias / identity claim
    checks = {
        "candidate_applicable_equals_candidate_legal": {
            "TRAIN": eq(c["candidate_applicable"], c["candidate_legal"], mt),
            "DEV": eq(cd["candidate_applicable"], cd["candidate_legal"], mtd),
            "mismatches_TRAIN": int((c["candidate_applicable"][mt]
                                     != c["candidate_legal"][mt]).sum()),
        },
        "candidate_has_unmet_requirements_is_complement_of_legality": {
            "TRAIN": eq(c["candidate_has_unmet_requirements"],
                        1.0 - c["candidate_legal"], mt),
            "DEV": eq(cd["candidate_has_unmet_requirements"],
                      1.0 - cd["candidate_legal"], mtd),
            "mismatches_TRAIN": int((c["candidate_has_unmet_requirements"][mt]
                                     != (1.0 - c["candidate_legal"][mt])).sum()),
        },
        "missing_info_panel_equals_count_channel0": {
            "TRAIN": eq(g["missing_information_present"].reshape(-1),
                        g["number_or_structure_of_missing_requirements"][:, 0]),
            "DEV": eq(gd["missing_information_present"].reshape(-1),
                      gd["number_or_structure_of_missing_requirements"][:, 0]),
            "mismatches_TRAIN": int((g["missing_information_present"].reshape(-1)
                                     != g["number_or_structure_of_missing_requirements"][:, 0]
                                     ).sum()),
        },
        "count_channel_value_range_is_binary_only": {
            "min": float(g["number_or_structure_of_missing_requirements"][:, 0].min()),
            "max": float(g["number_or_structure_of_missing_requirements"][:, 0].max()),
            "note": "BANK-v1 supplies 0/1 only, so the count channel IS the binary panel and "
                    "carries no independent count information",
        },
        "structural_channels_all_unsupervised": bool(
            torch.isnan(g["number_or_structure_of_missing_requirements"][:, 1:]).all()),
        "solvable_is_not_just_goal_satisfied": {
            "identical": eq(g["solvable"], g["goal_satisfied"]),
            "TRAIN_prevalence_solvable": round(float(g["solvable"].mean()), 4),
            "TRAIN_prevalence_goal_satisfied": round(float(g["goal_satisfied"].mean()), 4),
        },
        "candidate_satisfies_goal_not_derived_from_legality": {
            "identical": eq(c["candidate_satisfies_goal"], c["candidate_legal"], mt),
            "TRAIN_prevalence": round(float(c["candidate_satisfies_goal"][mt].mean()), 4),
        },
    }

    # ---- prevalence per canonical source, TRAIN ONLY
    prev = {
        "SRC-SOLVABILITY": round(float(g["solvable"].mean()), 6),
        "SRC-GOAL-SATISFIED": round(float(g["goal_satisfied"].mean()), 6),
        "SRC-MISSING-INFO-PANEL": round(float(g["missing_information_present"].mean()), 6),
        "SRC-CONTRADICTION-PANEL": round(float(g["contradiction_present"].mean()), 6),
        "SRC-CANDIDATE-LEGALITY": round(float(c["candidate_legal"][mt].mean()), 6),
        "SRC-CANDIDATE-SATISFIES-GOAL": round(
            float(c["candidate_satisfies_goal"][mt].mean()), 6),
    }
    head_prev = {n: round(float((g[n][:, 0] if n in g else c[n][mt]).mean()), 6)
                 for n in list(g) + list(c)}

    # ---- registry
    reg = []
    for t in ALL_TARGETS:
        n = t.name
        sid = SOURCE_ID[n]
        partial = []
        if n == "number_or_structure_of_missing_requirements":
            partial = [0]
        reg.append({
            "target_name": n,
            "scope": t.kind.upper(),
            "canonical_source_id": sid,
            "canonical_source": DERIVATION[n],
            "source_semantics": SOURCE_SEMANTICS.get(sid, "n/a"),
            "availability": t.availability,
            "alias_of": ALIAS_OF.get(n),
            "partial_channels": partial,
            "train_prevalence": head_prev.get(n),
            "supervised": bool(sid is not None),
        })

    groups = {}
    for r in reg:
        if r["canonical_source_id"]:
            groups.setdefault(r["canonical_source_id"], []).append(r["target_name"])
    g_s = sorted(s for s, h in groups.items() if h[0] in g)
    g_e = sorted(s for s, h in groups.items() if h[0] in c)

    rec = {
        "abi": "phase3-semantic-interface/target-source-registry-v0.1",
        "lane": "bidirectional (Lepori)",
        "authority": "canonical BANK-v1 world records + the shared executable simulator. "
                     "Sourceability is NOT a substrate property.",
        "population": {"TRAIN_canonical": tr["n_rows"], "DEV_canonical": dv["n_rows"],
                       "m_cap": M_CAP, "prim_suffix": SUFFIX},
        "independent_global_source_groups": g_s,
        "independent_candidate_source_groups": g_e,
        "n_global_groups": len(g_s), "n_candidate_groups": len(g_e),
        "source_groups": groups,
        "train_prevalence_by_source": prev,
        "train_prevalence_by_head": head_prev,
        "identity_checks": checks,
        "registry": reg,
        "identity_stop": {
            "lane_mapping_disagreements_recorded": True,
            "note": "solvable and candidate_has_unmet_requirements are derived from the shared "
                    "simulator and are therefore AVAILABLE for every substrate. A lane that "
                    "reports them unavailable has a mapping discrepancy, not a substrate "
                    "difference. This lane resolved both from the canonical source and trains "
                    "them; no derivation was invented and no meaning was changed.",
            "targets_left_unresolved": [
                "requestable_information_present", "candidate_supported",
                "candidate_has_counterevidence", "candidate_requires_missing_information"],
            "why_unresolved": "BANK-v1 records no canonical field for any of them. Resolving "
                             "them would require inventing a derivation, which is forbidden. "
                             "They stay UNAVAILABLE for all lanes.",
        },
    }
    p = OUT / "target-source-registry.json"
    p.write_text(json.dumps(rec, indent=2) + "\n")
    print(f"global groups   {len(g_s)}: {g_s}")
    print(f"candidate groups {len(g_e)}: {g_e}")
    print("\nalias verification:")
    for k, v in checks.items():
        print(f"  {k}: {v}")
    print("\ntrain prevalence by source:")
    for k, v in prev.items():
        print(f"  {k:32s} {v}")
    print("\nregistry:")
    for r in reg:
        print(f"  {r['target_name']:46s} {r['scope']:9s} "
              f"{str(r['canonical_source_id']):30s} {r['availability']:12s} "
              f"alias_of={r['alias_of']}")
    print("\nwritten:", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
