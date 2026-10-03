"""Independent raw-record audit and finalization of Phase 2B candidates.

This validator does not import the bank builder, optimizer, selector, or CP-SAT
solver. It recomputes eligibility, training-only entropy bins, full frozen
profile constraints, atom-count equivalence, and candidate objective sums from
the pinned raw metadata before emitting final ID-only manifests.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
V08_DIR = REPO / "experiments" / "jev-information-density-v08"
V08B_DIR = REPO / "experiments" / "jev-information-density-v08b"
FAMILY_AXES = (
    "world_or_topology_family", "ontology_family", "schema_composition_family",
    "candidate_set_construction_family", "definition_template_family", "intervention_family",
)
COVERAGE_AXES = (
    "semantic_novelty", "local_discrimination", "probability_geometry",
    "structural_coverage", "redundancy",
)
GROUP_FIELDS = {
    "group_id", "episode_id", "root_id", "valid", "family_ids", "strata",
    "coverage_features", "overlap_keys", "split_family_bundle_id", "posterior_entropy_nats",
}
HOLDOUT_SALT = "jev-idv08-family-bundle-holdout-sha256-v1"
HOLDOUT_FRACTION = 0.20
GROUP_LIMIT = 100_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(seed: str, key: str) -> bytes:
    return hashlib.sha256(f"{seed}|{key}".encode("utf-8")).digest()


def held_out(bundle: str) -> bool:
    raw = hashlib.sha256(f"{HOLDOUT_SALT}|family_bundle|{bundle}".encode("utf-8")).digest()
    return int.from_bytes(raw, "big") < int(HOLDOUT_FRACTION * (1 << 256))


def entropy_band(value: float) -> str:
    if value < 0.20:
        return "very_low"
    if value < 0.55:
        return "low"
    if value < 0.95:
        return "medium"
    if value < 1.30:
        return "high"
    return "very_high"


def parse_input_gold(keys: list[str], where: str) -> tuple[str, str]:
    inputs = [v.removeprefix("model_input:") for v in keys if v.startswith("model_input:")]
    gold = [v.removeprefix("gold_target:") for v in keys if v.startswith("gold_target:")]
    if len(inputs) != 1 or len(gold) != 1:
        raise ValueError(f"expected one input/gold digest at {where}")
    return inputs[0], gold[0]


def manifest(path: Path, count: int) -> tuple[dict[str, str], str]:
    result: dict[str, str] = {}
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            group_id, episode_id = row.get("group_id"), row.get("episode_id")
            if not isinstance(group_id, str) or not group_id or not isinstance(episode_id, str) or not episode_id:
                raise ValueError(f"bad group/episode ID at {path}:{line_no}")
            if group_id in result:
                raise ValueError(f"duplicate group ID at {path}:{line_no}")
            result[group_id] = episode_id
    if len(result) != count:
        raise ValueError(f"{path} contains {len(result)} IDs, expected {count}")
    return result, digest.hexdigest()


def profile_cell(row: dict[str, Any], thresholds: list[float]) -> tuple[str, ...]:
    entropy = float(row["entropy"])
    q = bisect.bisect_right(thresholds, entropy) + 1
    return (
        row["world"], row["bundle"], row["query"], row["cardinality"],
        f"q{q}", entropy_band(entropy),
    )


def atom(row: dict[str, Any], cell: tuple[str, ...]) -> tuple[Any, ...]:
    return row["input"], row["root"], cell, row["topology"], row["intervention"]


def row_features(raw: dict[str, Any], input_id: str) -> tuple[tuple[str, ...], ...]:
    values = [tuple(sorted({str(v) for v in raw["coverage_features"][axis]})) for axis in COVERAGE_AXES]
    i = COVERAGE_AXES.index("redundancy")
    values[i] = tuple(sorted(set(values[i]) | {f"input:{input_id}"}))
    return tuple(values)


def score(features: tuple[tuple[str, ...], ...], counts: list[Counter[str]]) -> float:
    axes = [
        sum(1.0 / math.sqrt(counts[i][feature]) for feature in row) / len(row)
        for i, row in enumerate(features) if row
    ]
    return sum(axes) / len(axes)


def histogram(counter: Counter[Any]) -> Counter[int]:
    return Counter(counter.values())


def tv(left: Counter[Any], right: Counter[Any]) -> float:
    n_left, n_right = sum(left.values()), sum(right.values())
    if not n_left or not n_right:
        return 0.0 if n_left == n_right == 0 else 1.0
    return 0.5 * sum(
        abs(left.get(key, 0) / n_left - right.get(key, 0) / n_right)
        for key in set(left) | set(right)
    )


def profile(rows: list[dict[str, Any]], thresholds: list[float]) -> dict[str, Counter[Any]]:
    result = {name: Counter() for name in ("cells", "inputs", "roots", "topology", "interventions")}
    for row in rows:
        cell = profile_cell(row, thresholds)
        result["cells"][cell] += 1
        result["inputs"][row["input"]] += 1
        result["roots"][row["root"]] += 1
        result["topology"].update(row["topology"])
        result["interventions"][row["intervention"]] += 1
    return result


def profile_comparison(candidate: list[dict[str, Any]], reference: list[dict[str, Any]], thresholds: list[float]) -> dict[str, Any]:
    selected, target = profile(candidate, thresholds), profile(reference, thresholds)

    def count_bound(actual: int, expected: int) -> bool:
        return math.floor(expected * 0.98) <= actual <= math.ceil(expected * 1.02)

    metrics = {
        "groups": len(candidate),
        "joint_cells_exact": selected["cells"] == target["cells"],
        "unique_inputs": {
            "selected": len(selected["inputs"]), "reference": len(target["inputs"]),
            "relative_error": abs(len(selected["inputs"]) - len(target["inputs"])) / len(target["inputs"]),
            "multiplicity_histogram_tv": tv(histogram(selected["inputs"]), histogram(target["inputs"])),
        },
        "unique_roots": {
            "selected": len(selected["roots"]), "reference": len(target["roots"]),
            "relative_error": abs(len(selected["roots"]) - len(target["roots"])) / len(target["roots"]),
            "multiplicity_histogram_tv": tv(histogram(selected["roots"]), histogram(target["roots"])),
        },
        "topology_tv": tv(selected["topology"], target["topology"]),
        "intervention_tv": tv(selected["interventions"], target["interventions"]),
    }
    metrics["all_hard_constraints_pass"] = all((
        len(candidate) == GROUP_LIMIT,
        metrics["joint_cells_exact"],
        count_bound(len(selected["inputs"]), len(target["inputs"])),
        metrics["unique_inputs"]["multiplicity_histogram_tv"] <= 0.02 + 1e-12,
        count_bound(len(selected["roots"]), len(target["roots"])),
        metrics["unique_roots"]["multiplicity_histogram_tv"] <= 0.02 + 1e-12,
        metrics["topology_tv"] <= 0.02 + 1e-12,
        metrics["intervention_tv"] <= 0.02 + 1e-12,
    ))
    return metrics


def objective_scores(
    path: Path,
    target_cells: dict[str, Counter[tuple[str, ...]]],
    thresholds: list[float],
    feature_counts: list[Counter[str]],
    selected_ids: dict[str, set[str]],
    seed: str,
    mode: str,
) -> dict[str, Any]:
    items: list[tuple[Any, ...]] = []
    with path.open("rb") as stream:
        for raw in stream:
            if not raw.strip():
                continue
            row = json.loads(raw)
            if row["valid"] is not True or held_out(str(row["split_family_bundle_id"])):
                continue
            group_id = str(row["group_id"])
            input_id, _gold_id = parse_input_gold(row["overlap_keys"], group_id)
            cell = profile_cell({
                "entropy": float(row["posterior_entropy_nats"]),
                "world": str(row["strata"]["world_family"]),
                "bundle": str(row["split_family_bundle_id"]),
                "query": str(row["strata"]["query_view_type"]),
                "cardinality": str(row["strata"]["candidate_cardinality_bin"]),
            }, thresholds)
            if mode == "curated":
                value = score(row_features(row, input_id), feature_counts)
                items.append((value, stable_digest(seed, group_id), group_id, cell))
            else:
                items.append((stable_digest(seed, group_id), group_id, cell))
    if mode == "curated":
        items.sort(key=lambda item: (-item[0], item[1], item[2]))
    else:
        items.sort(key=lambda item: (item[0], item[1]))
    values = {name: 0 for name in selected_ids}
    bounds = {name: 0 for name in selected_ids}
    seen = {name: Counter() for name in selected_ids}
    for rank, item in enumerate(items):
        if mode == "curated":
            group_id, cell = item[2], item[3]
        else:
            group_id, cell = item[1], item[2]
        priority = len(items) - rank
        for name, ids in selected_ids.items():
            if group_id in ids:
                values[name] += priority
            if seen[name][cell] < target_cells[name].get(cell, 0):
                bounds[name] += priority
                seen[name][cell] += 1
    return {"selected_objective_sums": values, "cell_relaxed_valid_upper_bounds": bounds}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\full-universe-500k-v08\group-records.jsonl"))
    parser.add_argument("--r100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-r100-group-ids.jsonl"))
    parser.add_argument("--c100", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-c100-group-ids.jsonl"))
    parser.add_argument("--eval", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08\selection-v08-c100v12\new-tight-eval-group-ids.jsonl"))
    parser.add_argument("--candidate-dir", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\equivalent-substitution-v01"))
    parser.add_argument("--witness-receipt", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\witness-validation-v02.json"))
    parser.add_argument("--out", type=Path, default=Path(r"D:\codex-runs\jev-information-density-v08c\phase2b-v01\equivalent-substitution-v01\candidate-validation.json"))
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"refusing to overwrite validation receipt: {args.out}")
    started = time.perf_counter()
    construction = json.loads((args.candidate_dir / "construction-report.json").read_text(encoding="utf-8"))
    witness = json.loads(args.witness_receipt.read_text(encoding="utf-8"))
    if construction["witness_receipt_sha256"] != sha256_file(args.witness_receipt):
        raise ValueError("construction report witness receipt hash mismatch")
    phase2_contract_path = HERE / "v08c-phase2-contract.json"
    phase2 = json.loads(phase2_contract_path.read_text(encoding="utf-8"))
    pins = phase2["inputs"]
    source_paths = {
        "v08_contract_sha256": V08_DIR / "v08-contract.json",
        "v08_selector_sha256": V08_DIR / "select_banks.py",
        "v08b_contract_sha256": V08B_DIR / "v08b-contract.json",
        "phase1_solver_sha256": HERE / "solve_feasibility.py",
        "phase2_solver_sha256": HERE / "optimize_matched_banks.py",
    }
    source_hashes = {key: sha256_file(path) for key, path in source_paths.items()}
    for key, value in source_hashes.items():
        if value != pins[key]:
            raise ValueError(f"source pin mismatch: {key}")
    if sha256_file(HERE / "v08c-contract.json") != phase2["phase1_contract_sha256"]:
        raise ValueError("Phase 1 contract hash mismatch")
    if sha256_file(phase2_contract_path) != construction["source_pins"]["phase2_contract_sha256"]:
        raise ValueError("Phase 2 contract hash mismatch")
    if sha256_file(HERE / "v08c-phase2b-contract.json") != construction["phase2b_contract_sha256"]:
        raise ValueError("Phase 2B contract hash mismatch")

    manifests: dict[str, dict[str, str]] = {}
    manifest_hashes: dict[str, str] = {}
    for name, path, count in (
        ("R100", args.r100, GROUP_LIMIT), ("C100", args.c100, GROUP_LIMIT),
        ("Eval", args.eval, 83_328),
        ("CM100", args.candidate_dir / "cm100-provisional-ids.jsonl", GROUP_LIMIT),
        ("RM100", args.candidate_dir / "rm100-provisional-ids.jsonl", GROUP_LIMIT),
    ):
        manifests[name], manifest_hashes[name] = manifest(path, count)
    expected_source_hashes = {
        "R100": pins["r100_manifest_sha256"], "C100": pins["c100_manifest_sha256"],
        "Eval": pins["eval_manifest_sha256"],
        "CM100": construction["banks"]["CM100"]["provisional_manifest_sha256"],
        "RM100": construction["banks"]["RM100"]["provisional_manifest_sha256"],
    }
    for name, expected in expected_source_hashes.items():
        if manifest_hashes[name] != expected:
            raise ValueError(f"manifest hash mismatch: {name}")

    names_by_id: dict[str, set[str]] = defaultdict(set)
    for name in ("R100", "C100", "CM100", "RM100"):
        for group_id in manifests[name]:
            names_by_id[group_id].add(name)
    profile_rows: dict[str, list[dict[str, Any]]] = {name: [] for name in ("R100", "C100", "CM100", "RM100")}
    feature_counts = [Counter() for _ in COVERAGE_AXES]
    entropies: list[float] = []
    input_gold: dict[str, str] = {}
    seen_ids: set[str] = set()
    eval_found: set[str] = set()
    found = Counter()
    raw_digest = hashlib.sha256()
    valid_count = eligible_count = heldout_count = 0
    start_load = time.perf_counter()
    with args.groups.open("rb") as stream:
        for line_no, raw in enumerate(stream, 1):
            raw_digest.update(raw)
            if not raw.strip():
                continue
            row = json.loads(raw)
            if set(row) != GROUP_FIELDS:
                raise ValueError(f"source record schema mismatch at line {line_no}")
            group_id = str(row["group_id"])
            if not group_id or group_id in seen_ids:
                raise ValueError(f"empty or duplicate group ID at line {line_no}")
            seen_ids.add(group_id)
            if row["valid"] is not True:
                continue
            valid_count += 1
            bundle = str(row["split_family_bundle_id"])
            if held_out(bundle):
                heldout_count += 1
                if group_id in manifests["Eval"]:
                    eval_found.add(group_id)
                if group_id in names_by_id:
                    raise ValueError(f"candidate/reference group is held out: {group_id}")
                continue
            eligible_count += 1
            if group_id in manifests["Eval"]:
                raise ValueError(f"eval ID is not held out: {group_id}")
            entropy = float(row["posterior_entropy_nats"])
            if not math.isfinite(entropy) or entropy < 0:
                raise ValueError(f"invalid entropy at line {line_no}")
            entropies.append(entropy)
            input_id, gold_id = parse_input_gold(row["overlap_keys"], f"line {line_no}")
            if input_gold.setdefault(input_id, gold_id) != gold_id:
                raise ValueError(f"conflicting gold for input {input_id}")
            features = row_features(row, input_id)
            for i, values in enumerate(features):
                feature_counts[i].update(values)
            if group_id not in names_by_id:
                continue
            for name in names_by_id[group_id]:
                if manifests[name][group_id] != str(row["episode_id"]):
                    raise ValueError(f"episode ID mismatch: {name}/{group_id}")
                families = row["family_ids"]
                topology = tuple(sorted({
                    str(value) for value in row["coverage_features"]["structural_coverage"]
                    if str(value).startswith("topology:")
                }))
                profile_rows[name].append({
                    "group_id": group_id,
                    "episode_id": str(row["episode_id"]),
                    "input": input_id,
                    "root": str(row["root_id"]),
                    "bundle": bundle,
                    "world": str(row["strata"]["world_family"]),
                    "query": str(row["strata"]["query_view_type"]),
                    "cardinality": str(row["strata"]["candidate_cardinality_bin"]),
                    "entropy": entropy,
                    "topology": topology,
                    "intervention": str(families["intervention_family"]),
                })
                found[name] += 1
    raw_hash = raw_digest.hexdigest()
    if raw_hash != pins["group_records_sha256"]:
        raise ValueError("raw group-record hash mismatch")
    if eligible_count != 416_672 or heldout_count != 83_328 or valid_count != 500_000:
        raise ValueError("frozen universe population counts differ")
    if eval_found != set(manifests["Eval"]):
        raise ValueError("Eval identity differs from holdout reconstructed from raw source")
    if any(found[name] != GROUP_LIMIT for name in ("R100", "C100", "CM100", "RM100")):
        raise ValueError(f"selected eligible membership incomplete: {dict(found)}")
    entropies.sort()
    thresholds = [entropies[min(len(entropies) - 1, math.floor(len(entropies) * q / 5))] for q in range(1, 5)]
    load_seconds = time.perf_counter() - start_load

    target_names = {"CM100": "R100", "RM100": "C100"}
    audits: dict[str, Any] = {}
    target_cells: dict[str, Counter[tuple[str, ...]]] = {}
    for name, reference_name in target_names.items():
        candidate, reference = profile_rows[name], profile_rows[reference_name]
        candidate_ids = set(manifests[name])
        reference_ids = set(manifests[reference_name])
        candidate_profile = profile_comparison(candidate, reference, thresholds)
        candidate_atoms = Counter(atom(row, profile_cell(row, thresholds)) for row in candidate)
        reference_atoms = Counter(atom(row, profile_cell(row, thresholds)) for row in reference)
        atom_counts_exact = candidate_atoms == reference_atoms
        distinct = candidate_ids != reference_ids
        target_cells[name] = Counter(profile_cell(row, thresholds) for row in reference)
        audits[name] = {
            "reference_profile": reference_name,
            "eligible_membership": True,
            "distinct_group_ids": distinct,
            "reference_overlap_count": len(candidate_ids & reference_ids),
            "reference_overlap_fraction": len(candidate_ids & reference_ids) / GROUP_LIMIT,
            "changed_group_count": len(candidate_ids ^ reference_ids),
            "profile_constraints": candidate_profile,
            "exact_atom_count_vector_preserved": atom_counts_exact,
            "counterfactual_feasible": distinct and candidate_profile["all_hard_constraints_pass"],
        }

    objective_results: dict[str, Any] = {}
    phase2 = json.loads((HERE / "v08c-phase2-contract.json").read_text(encoding="utf-8"))
    phase2b = json.loads((HERE / "v08c-phase2b-contract.json").read_text(encoding="utf-8"))
    start_objective = time.perf_counter()
    curated = objective_scores(
        args.groups, {"CM100": target_cells["CM100"], "R100": target_cells["CM100"]}, thresholds, feature_counts,
        {"CM100": set(manifests["CM100"]), "R100": set(manifests["R100"])},
        phase2["objective"]["curated_seed"], "curated",
    )
    random = objective_scores(
        args.groups, {"RM100": target_cells["RM100"], "C100": target_cells["RM100"]}, thresholds, feature_counts,
        {"RM100": set(manifests["RM100"]), "C100": set(manifests["C100"])},
        phase2["objective"]["random_seed"], "random",
    )
    objective_seconds = time.perf_counter() - start_objective
    if sha256_file(args.groups) != raw_hash:
        raise ValueError("group-record source changed between validation passes")
    for bank, result, policy, reference in (
        ("CM100", curated, "curated", "R100"),
        ("RM100", random, "random", "C100"),
    ):
        values = result["selected_objective_sums"]
        upper = result["cell_relaxed_valid_upper_bounds"][bank]
        identity = values[reference]
        candidate = values[bank]
        construction_claim = construction["banks"][bank]
        if candidate != construction_claim["candidate_objective"] or identity != construction_claim["identity_objective"]:
            raise ValueError(f"objective value mismatch against construction report for {bank}")
        delta = candidate - identity
        audits[bank]["objective"] = {
            "policy": policy,
            "identity_objective": identity,
            "candidate_objective": candidate,
            "delta": delta,
            "independently_reproduced": True,
            "valid_cell_relaxed_upper_bound": upper,
            "headroom_recovery": (candidate - identity) / (upper - identity) if upper > identity else None,
            "bound_caveat": "upper bound is valid but may be loose because it ignores all non-cell constraints",
            "separated": delta >= 1,
        }
        audits[bank]["construction_report_objective_match"] = True

    all_pass = all(
        audits[name]["counterfactual_feasible"]
        and audits[name]["exact_atom_count_vector_preserved"]
        and audits[name]["objective"]["separated"]
        for name in ("CM100", "RM100")
    )
    finals = [args.candidate_dir / f"{name.lower()}-ids.jsonl" for name in ("CM100", "RM100")]
    if all_pass and any(path.exists() for path in finals):
        raise FileExistsError("refusing to overwrite an existing final candidate manifest")
    report = {
        "receipt": "jev-information-density-v08c-phase2b-candidate-validation/v1",
        "status": "PASS_COUNTERFACTUAL_AND_POLICY_SEPARATION" if all_pass else "FAIL_CANDIDATE_ACCEPTANCE",
        "source_hashes": source_hashes,
        "group_records_sha256": raw_hash,
        "manifest_hashes": manifest_hashes,
        "phase2_contract_sha256": sha256_file(phase2_contract_path),
        "phase2b_contract_sha256": sha256_file(HERE / "v08c-phase2b-contract.json"),
        "construction_report_sha256": sha256_file(args.candidate_dir / "construction-report.json"),
        "witness_receipt_sha256": sha256_file(args.witness_receipt),
        "population": {
            "all_unique_group_ids": len(seen_ids), "valid": valid_count,
            "eligible_training": eligible_count, "heldout": heldout_count,
            "input_gold_conflicts": 0,
            "training_only_entropy_thresholds_nats": thresholds,
        },
        "timing_seconds": {
            "raw_source_membership_profiles_and_feature_counts": load_seconds,
            "objective_reproduction_and_valid_bounds": objective_seconds,
        },
        "banks": audits,
        "final_manifests_emitted": False,
        "model_contact": False,
        "phoenix_access": False,
        "training_materialized": False,
    }
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if all_pass:
        temporaries: list[tuple[Path, Path]] = []
        for name in ("CM100", "RM100"):
            source = args.candidate_dir / f"{name.lower()}-provisional-ids.jsonl"
            final = args.candidate_dir / f"{name.lower()}-ids.jsonl"
            temporary = final.with_suffix(final.suffix + ".tmp")
            with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
                while chunk := input_stream.read(1024 * 1024):
                    output_stream.write(chunk)
                output_stream.flush()
                os.fsync(output_stream.fileno())
            temporaries.append((temporary, final))
        for temporary, final in temporaries:
            os.replace(temporary, final)
            audits[name]["final_manifest_path"] = str(final)
            audits[name]["final_manifest_sha256"] = sha256_file(final)
        report["final_manifests_emitted"] = True
        report["banks"] = audits
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"],
        "timing_seconds": report["timing_seconds"],
        "banks": {name: {
            "counterfactual_feasible": value["counterfactual_feasible"],
            "exact_atom_count_vector_preserved": value["exact_atom_count_vector_preserved"],
            "changed_group_count": value["changed_group_count"],
            "objective_delta": value.get("objective", {}).get("delta"),
            "headroom_recovery": value.get("objective", {}).get("headroom_recovery"),
            "separated": value.get("objective", {}).get("separated"),
        } for name, value in audits.items()},
        "final_manifests_emitted": report["final_manifests_emitted"],
        "report": str(args.out),
    }, ensure_ascii=False))
    return 0 if all_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
