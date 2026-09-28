"""Build and audit per-case compound motifs from MAT1-R1 receipts."""
from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
LR1_SCRIPT = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-lr1-v1/scripts"
RH1_SCRIPT = REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts"
GC0_SCRIPT = REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts"
sys.path.insert(0, str(LR1_SCRIPT))
sys.path.insert(0, str(RH1_SCRIPT))
sys.path.insert(0, str(GC0_SCRIPT))
sys.dont_write_bytecode = True
import lr1_adapter as A  # noqa: E402
import run_lr1_case as LR1  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"PAL1 refuses overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"PAL1 orphan temporary file: {temporary}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def vector_interaction(left, a, b, base):
    return [x - y - z + w for x, y, z, w in zip(left, a, b, base)]


def l2(values) -> float:
    return math.sqrt(math.fsum(x * x for x in values))


def vector_rank(vectors: list[list[float]], tolerance: float = 1e-12) -> int:
    basis: list[list[float]] = []
    for original in vectors:
        v = [float(x) for x in original]
        for b in basis:
            scale = math.fsum(x * y for x, y in zip(v, b))
            v = [x - scale * y for x, y in zip(v, b)]
        norm = l2(v)
        if norm > tolerance:
            basis.append([x / norm for x in v])
    return len(basis)


def case_name(endpoint: str, set_index: int) -> str:
    return f"{endpoint.replace('.json', '')}__set{set_index}"


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"PAL1 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"PAL1 parent drift: {binding['label']}")

    source_path = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-mat1-r1-v1/qualification/materialized-pairs.jsonl"
    source = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(source) == 201, f"PAL1 source count drift: {len(source)}")

    contexts: dict[str, tuple] = {}
    motifs = []
    for record in source:
        endpoint = str(record["endpoint"])
        set_index = int(record["set_index"])
        context = case_name(endpoint, set_index)
        if context not in contexts:
            state, groups, _, _, _ = LR1.load_case(endpoint, set_index)
            target_readout = list(A.replay(state.rows, tuple(state.target_weight_bits)))
            contexts[context] = (state, groups, target_readout)
        state, groups, target_readout = contexts[context]
        source_pair = record["source"]["pair"]
        a = record["source"]["a"]
        b = record["source"]["b"]
        group_a = int(a["group"])
        group_b = int(b["group"])
        require(group_a != group_b, f"PAL1 same-group motif: {context} {record['pair_domain_index']}")
        support = sorted(set(groups[group_a]["physical_support_rows"]) | set(groups[group_b]["physical_support_rows"]))
        invalid_bits = record["states"]["invalid_search"]["readout_bits"]
        pair_bits = record["states"]["pair_ab"]["readout_bits"]
        baseline_mismatch = {i for i, (x, y) in enumerate(zip(invalid_bits, target_readout)) if x != y}
        pair_mismatch = {i for i, (x, y) in enumerate(zip(pair_bits, target_readout)) if x != y}
        changed_rows = {i for i, (x, y) in enumerate(zip(pair_bits, invalid_bits)) if x != y}
        delta_a = record["states"]["single_a"]["signed_geometry"]
        delta_b = record["states"]["single_b"]["signed_geometry"]
        delta_s = record["states"]["invalid_search"]["signed_geometry"]
        action_a = [float(delta_a["axis_debt"] - delta_s["axis_debt"]), float(delta_a["norm_debt"] - delta_s["norm_debt"]), *[float(x - y) for x, y in zip(delta_a["linear_drive_debt"], delta_s["linear_drive_debt"])]]
        action_b = [float(delta_b["axis_debt"] - delta_s["axis_debt"]), float(delta_b["norm_debt"] - delta_s["norm_debt"]), *[float(x - y) for x, y in zip(delta_b["linear_drive_debt"], delta_s["linear_drive_debt"])]]
        motifs.append({
            "motif_identity": f"{context}|pair={int(record['pair_domain_index'])}",
            "case": context,
            "pair_domain_index": int(record["pair_domain_index"]),
            "groups": [group_a, group_b],
            "components": [
                {"group": group_a, "candidate_identity": str(a["to"]), "source_domain_index": int(a["domain_index"])},
                {"group": group_b, "candidate_identity": str(b["to"]), "source_domain_index": int(b["domain_index"])},
            ],
            "canonical_selection": record["states"]["pair_ab"]["selection"],
            "nonzero_coordinate_prefix": record["states"]["pair_ab"]["nonzero_coordinate_prefix"],
            "committed_f32_mapping": record["states"]["pair_ab"]["committed_f32_mapping"],
            "weight_bits_hash": record["states"]["pair_ab"]["weight_bits_hash"],
            "readout_hash": record["states"]["pair_ab"]["readout_hash"],
            "score": source_pair["score"],
            "geometry": record["states"]["pair_ab"]["geometry"],
            "physical_support_rows": support,
            "readout_changed_rows": sorted(changed_rows),
            "baseline_mismatch_rows": sorted(baseline_mismatch),
            "pair_mismatch_rows": sorted(pair_mismatch),
            "fixed_baseline_rows": sorted(baseline_mismatch - pair_mismatch),
            "newly_damaged_rows": sorted(pair_mismatch - baseline_mismatch),
            "component_constraint_actions": {"A": action_a, "B": action_b},
            "source_mat1_record_hash": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest().upper(),
        })

    by_case: dict[str, list[dict]] = defaultdict(list)
    for motif in motifs:
        by_case[motif["case"]].append(motif)
    case_summaries = []
    conflict_edges = []
    for case in sorted(by_case):
        rows = by_case[case]
        state, groups, target_readout = contexts[case]
        support_union = set()
        effect_union = set()
        baseline_mismatch = set()
        action_vectors = []
        group_edges = 0
        coordinate_edges = 0
        for motif in rows:
            support_union.update(motif["physical_support_rows"])
            effect_union.update(motif["readout_changed_rows"])
            baseline_mismatch.update(motif["baseline_mismatch_rows"])
            action_vectors.extend(motif["component_constraint_actions"].values())
        for i, left in enumerate(rows):
            left_map = {int(x[0]): int(x[1]) for x in left["nonzero_coordinate_prefix"]}
            for right in rows[i + 1:]:
                if set(left["groups"]) & set(right["groups"]):
                    group_edges += 1
                    reason = "group_overlap"
                else:
                    right_map = {int(x[0]): int(x[1]) for x in right["nonzero_coordinate_prefix"]}
                    reason = "coordinate_conflict" if any(k in right_map and right_map[k] != v for k, v in left_map.items()) else None
                    if reason:
                        coordinate_edges += 1
                if reason:
                    conflict_edges.append({"case": case, "left": left["motif_identity"], "right": right["motif_identity"], "reason": reason})
        case_summaries.append({
            "case": case,
            "motif_count": len(rows),
            "baseline_mismatch_count": len(baseline_mismatch),
            "physical_support_union_count": len(support_union),
            "baseline_mismatch_outside_physical_support": sorted(baseline_mismatch - support_union),
            "readout_effect_union_count": len(effect_union),
            "baseline_mismatch_outside_readout_effect_union": sorted(baseline_mismatch - effect_union),
            "group_conflict_edges": group_edges,
            "coordinate_conflict_edges": coordinate_edges,
            "component_constraint_action_rank": vector_rank(action_vectors),
        })

    output = ROOT / "qualification"
    output.mkdir(parents=True, exist_ok=True)
    motif_path = output / "motif-library.jsonl"
    case_path = output / "case-support-conflict.jsonl"
    edge_path = output / "conflict-edges.jsonl"
    execution_path = output / "execution.json"
    write_exclusive(motif_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in motifs))
    write_exclusive(case_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in case_summaries))
    write_exclusive(edge_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in conflict_edges))
    execution = {
        "identity": contract["identity"],
        "protocol": contract["protocol"],
        "scope": "derived_read_only_motif_palette_support_audit",
        "motifs": len(motifs),
        "cases": len(case_summaries),
        "case_summaries": case_summaries,
        "conflict_edges": len(conflict_edges),
        "motif_library_sha256": digest(motif_path),
        "case_support_sha256": digest(case_path),
        "conflict_edges_sha256": digest(edge_path),
        "checks_passed": True,
        "global_assembly": False,
    }
    write_exclusive(execution_path, json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
