"""Full TRAIN/DEV target replay against canonical BANK; unavailable targets stay masked."""
from __future__ import annotations

import hashlib
import numpy as np
from p3_contract import (SOURCE, OUTPUT, GLOBAL_GROUPS, CANDIDATE_GROUPS,
                         supervision_abi, sha_file, write_json)
from graft.contracts import BANK_CODE
from graft.prepare import read_worlds
from graft.supervision import labels_from_world


def label_identity(values, available):
    h = hashlib.sha256()
    h.update(np.asarray(available, np.uint8).tobytes())
    h.update(np.asarray(values[available], np.float32).tobytes())
    return h.hexdigest()


def build_registry(train, dev):
    replay = {}
    for split, data in (("TRAIN", train), ("DEV", dev)):
        worlds = read_worlds(split, {r["group_id"] for r in data.rows})
        candidate_rows = 0
        for i, row in enumerate(data.rows):
            g, gm, c, cm = labels_from_world(worlds[row["group_id"]], row["candidate_actions"])
            lo, hi = data.arrays["offsets"][i:i+2]
            for actual, expected in ((data.arrays["global_y"][i], g),
                                     (data.arrays["global_available"][i], gm),
                                     (data.arrays["candidate_y"][lo:hi], c),
                                     (data.arrays["candidate_available"][lo:hi], cm)):
                if not np.array_equal(actual, expected):
                    raise ValueError("Canonical label replay mismatch: " + row["world_id"])
            candidate_rows += len(c)
        if not np.array_equal(data.arrays["global_y"][:, 2], data.arrays["global_y"][:, 5]):
            raise ValueError("Missing count/presence alias does not hold")
        replay[split] = {"rows": len(data), "unique_worlds": len(worlds),
                         "candidates": candidate_rows, "all_label_values_and_masks_match": True,
                         "missing_count_equals_presence": True}
    prevalence = {}
    entries = []
    abi = supervision_abi()
    for scope, groups in (("GLOBAL", GLOBAL_GROUPS), ("CANDIDATE", CANDIDATE_GROUPS)):
        prefix = scope.lower()
        y, mask = train.arrays[prefix + "_y"], train.arrays[prefix + "_available"]
        for sid, heads in groups.items():
            index = heads[0]
            values = y[:, index][mask[:, index]]
            pi = float(values.astype(np.float64).mean())
            if not 0 < pi < 1:
                raise ValueError("TRAIN source lacks balanced class support: " + sid)
            prevalence[sid] = pi
        for index, item in enumerate(abi[prefix]):
            sid = next((k for k, hs in groups.items() if index in hs), None)
            entries.append({
                "target_name": item["name"], "scope": scope, "head_index": index,
                "canonical_source_id": sid, "canonical_source": item["source"],
                "source_semantics": item["meaning"],
                "availability": ("PARTIAL" if item["kind"] == "count" else "AVAILABLE")
                                 if item["available"] else "UNAVAILABLE",
                "alias_of": "missing_information_present" if index == 5 and scope == "GLOBAL" else None,
                "partial_channels": ["annotation_count_only"] if item["kind"] == "count" else [],
                "source_identity_status": "SAME_CANONICAL_SOURCE" if index == 5 and scope == "GLOBAL" else None,
                "TRAIN_prevalence": prevalence.get(sid),
                "TRAIN_label_mask_sha256": label_identity(y[:, index], mask[:, index]),
                "TRAIN_support": {str(v): int(np.sum(y[:, index][mask[:, index]] == v)) for v in (0, 1)},
            })
    encoder = SOURCE.parent / "phase0-semantic-interface" / "src"
    disputes = {
        "solvable": {
            "encoder_expression": "shortest_plan(max_depth=5) is not None AND NOT goal_satisfied",
            "issue": "Already-satisfied worlds are labelled false although a zero-step plan exists; depth-bound failure does not certify unrestricted unsolvability",
            "disposition": "UNRESOLVED_TARGET_MASKED; do not invent bounded-target semantics"},
        "candidate_has_unmet_requirements": {
            "encoder_expression": "NOT candidate_legal",
            "issue": "Complement of legality supplies no independently defined candidate requirement mapping under the frozen causal ABI",
            "disposition": "UNRESOLVED_TARGET_MASKED; proxy is not independent sourceability"},
        "candidate_applicable": {
            "encoder_expression": "candidate_legal (exact duplicate)",
            "issue": "Duplicate is documented, but adopting its semantics would change the frozen causal unavailable-target decision",
            "disposition": "UNRESOLVED_TARGET_MASKED; future shared ABI decision required"},
        "candidate_satisfies_goal": {
            "encoder_expression": "goal_satisfied(apply_action if legal else unchanged initial_state)",
            "issue": "Illegal actions receive true when initial goal already holds; causal source requires legal AND achieved goal",
            "disposition": "Causal frozen legal-one-step definition replayed from canonical simulator; no silent cross-lane equivalence"},
    }
    result = {
        "schema": "frozen-fabrique.target-source-registry-phase3/v1", "lane": "causal_base",
        "registry": entries, "global_source_groups": GLOBAL_GROUPS,
        "candidate_source_groups": CANDIDATE_GROUPS, "TRAIN_prevalence": prevalence,
        "population_replay": replay,
        "canonical_code_hashes": {str(p): sha_file(p) for p in (BANK_CODE / "simulator.py", BANK_CODE / "worldgen.py")},
        "encoder_mapping_snapshot_hashes": {str(encoder / n): sha_file(encoder / n)
                                              for n in ("data.py", "ontology.py", "target_registry.py")},
        "identity_audit": {
            "sourceability_is_not_substrate_specific": True, "discrepancies": disputes,
            "unresolved_targets": ["solvable", "candidate_has_unmet_requirements", "candidate_applicable"],
            "scope": "Stop only unresolved targets; train already sourceable targets unchanged. This does not claim cross-lane source reconciliation is complete.",
            "missing_count_proxy": "Exact 0/1 equality verified on TRAIN/DEV; one source, two ABI heads",
            "no_new_derivations_or_target_meanings": True},
        "protected_TEST_truth_opened": False, "BANK_v2_used": False,
    }
    write_json(OUTPUT / "TARGET-SOURCE-REGISTRY.json", result)
    return result


def candidate_audit(train, dev):
    result = {"m_max": 28, "retain_every_canonical_candidate": True,
              "Phase1_truncated_rows": 0, "Phase1_truncated_candidates": 0, "populations": {}}
    for split, data in (("TRAIN", train), ("DEV", dev)):
        counts = np.diff(data.arrays["offsets"])
        if int(counts.max()) != 28:
            raise ValueError("Frozen exhaustive universe changed")
        aligned = 0
        for a, b in data.extras["renderer_pairs"]:
            if data.rows[a]["candidate_actions"] != data.rows[b]["candidate_actions"]:
                raise ValueError("Canonical pair identity differs")
            aligned += 1
        result["populations"][split] = {"rows": len(data), "max_candidates": int(counts.max()),
            "total_candidates": int(counts.sum()), "aligned_pairs": aligned,
            "histogram": {str(v): int(np.sum(counts == v)) for v in sorted(set(counts))}}
    write_json(OUTPUT / "CANDIDATE-AUDIT.json", result)
    return result
