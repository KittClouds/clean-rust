"""Build the fresh REQUAL1 premeasurement closure and domain.

This runner intentionally lives below the historical PF5/LR1 contract audit.
It imports the current PF5 arithmetic from each copied closure, supplies fresh
parent hashes and freshly derived topology invariants, and refuses all replay
outputs beyond candidate-byte validation.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROTOCOL = "REQUAL1-DOMAIN"
IDENTITY = "q10-gc1-lr1-requal1-domain-r1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
SELECTED_KEYS = (
    ("seed9731-L-tau16.json", 2),
    ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1),
    ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0),
    ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2),
    ("seed9731-R-tau4.json", 3),
)

INPUT_REL = (
    "experiments/drosophila-heresy/q10-rmt-v1/CONTRACT.json",
    "experiments/drosophila-heresy/q10-rmt-v1/PREEXECUTION.json",
    "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732/endpoints.json",
    "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732/rows.json",
    "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732/components.json",
    "experiments/drosophila-heresy/q10-rmt-v1/qualification/sample-9731-9732/moves.jsonl",
    "experiments/drosophila-heresy/q10-da2-geometry-v1/CONTRACT.json",
    "experiments/drosophila-heresy/q10-da2-geometry-v1/PREEXECUTION.json",
    "experiments/drosophila-heresy/q10-da2-geometry-v1/qualification/sample-9731-9732/results.json",
    "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json",
    "experiments/drosophila-heresy/q10-pf5-v1/scripts/run_q10_pf5.py",
    "experiments/drosophila-heresy/q10-pf5-v1/scripts/qualify_q10_pf5.py",
    "experiments/drosophila-heresy/q10-gc1-par8-v1/CONTRACT.json",
    "experiments/drosophila-heresy/q10-gc1-par8-v1/qualification/execution.json",
    "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/CONTRACT.json",
    "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/PLAN.md",
    "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/scripts/run_par2.py",
    "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


def bits_hash(values: tuple[int, ...] | list[int]) -> str:
    return digest_bytes(b"".join(int(value).to_bytes(4, "little", signed=False) for value in values))


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def object_hash(value: Any) -> str:
    return digest_bytes(canonical(value))


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def input_manifest() -> dict[str, Any]:
    entries = []
    requested = set(INPUT_REL)
    source_root = REPO / "experiments/drosophila-heresy/q10-distributed-additive-v1/qualification/sample-9731-9732"
    requested.update(path.relative_to(REPO).as_posix() for path in source_root.glob("*.json"))
    for rel in sorted(requested):
        path = REPO / Path(rel)
        require(path.is_file(), f"missing declared current input: {rel}")
        entries.append({"path": rel, "sha256": digest(path), "bytes": path.stat().st_size})
    return {"protocol": PROTOCOL, "identity": IDENTITY, "source": "current-live-tree", "entries": entries}


def copy_closure(manifest: dict[str, Any], name: str) -> tuple[Path, dict[str, Any]]:
    root = ROOT / "closures" / name
    require(not root.exists(), f"closure already exists: {root}")
    repo = root / "repo"
    for entry in manifest["entries"]:
        source = REPO / Path(entry["path"])
        target = repo / Path(entry["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    copied = []
    for entry in manifest["entries"]:
        target = repo / Path(entry["path"])
        actual = digest(target)
        require(actual == entry["sha256"], f"closure copy hash mismatch: {name}/{entry['path']}")
        copied.append({"path": entry["path"], "sha256": actual, "bytes": target.stat().st_size})
    result = {"protocol": PROTOCOL, "closure": name, "entries": copied}
    write_new(root / "MANIFEST.json", result)
    return repo, result


def topology_invariants(rows: list[dict[str, Any]], moves: list[dict[str, Any]]) -> dict[str, Any]:
    kstars = Counter("none" if row.get("k_star") is None else str(row["k_star"]) for row in rows)
    classes = Counter(str(row.get("class_final")) for row in rows)
    components = Counter(int(row["component_index"]) for row in rows if row.get("component_index") is not None)
    return {
        "mismatch_rows": len(rows),
        "one_step_orphan_rows": sum(int(row["one_step_helpful_coordinates"]) == 0 for row in rows),
        "one_step_fragile_rows": sum(int(row["one_step_helpful_coordinates"]) == 1 for row in rows),
        "one_step_broad_rows": sum(int(row["one_step_helpful_coordinates"]) >= 2 for row in rows),
        "k_star_counts": dict(sorted(kstars.items())),
        "class_final_counts": dict(sorted(classes.items())),
        "helpful_components": len(components),
        "largest_helpful_component_rows": max(components.values(), default=0),
        "serialized_moves": len(moves),
        "no_helpful_rows_are_diagnostic": True,
        "no_helpful_rows_are_entry_blockers": False,
    }


def fresh_lineage(repo: Path, pf: Any) -> tuple[Any, dict[str, Any]]:
    experiment = repo / "experiments/drosophila-heresy"
    rmt = experiment / "q10-rmt-v1"
    receipt = rmt / "qualification/sample-9731-9732"
    source = experiment / "q10-distributed-additive-v1/qualification/sample-9731-9732"
    da2 = experiment / "q10-da2-geometry-v1/qualification/sample-9731-9732/results.json"
    old_semantics = load_json(experiment / "q10-pf5-v1/CONTRACT.json")
    endpoints = tuple(load_json(receipt / "endpoints.json"))
    rows = tuple(load_json(receipt / "rows.json"))
    components = tuple(load_json(receipt / "components.json"))
    moves = [json.loads(line) for line in (receipt / "moves.jsonl").read_text(encoding="utf-8").splitlines() if line]
    source_hashes = {path.name: digest(path) for path in sorted(source.glob("*.json"))}
    contract = {
        "geometry": old_semantics["geometry"],
        "prefix_domain": old_semantics["prefix_domain"],
        "topology_invariants": topology_invariants(list(rows), moves),
    }
    parent = {"source_input_sha256": source_hashes}
    lineage = pf.Lineage(
        protocol_root=ROOT,
        contract=contract,
        parent=parent,
        rmt_root=rmt,
        receipt_root=receipt,
        source_root=source,
        da2_results_path=da2,
        endpoints=endpoints,
        rows=rows,
        components=components,
    )
    states = pf.load_endpoint_states(lineage, selected_keys=set(SELECTED_KEYS))
    topology = pf.augment_missing_prefix_topology(pf.load_topology(lineage), states, lineage)
    groups = {state.key: pf.build_raw_groups(state, topology, lineage) for state in states}
    require(sum(len(value) for value in groups.values()) > 0, "fresh raw-group reconstruction produced no groups")
    state_inventory = []
    for state in sorted(states, key=lambda item: item.key):
        state_inventory.append(
            {
                "key": [state.key[0], state.key[1]],
                "baseline_weight_hash": bits_hash(state.baseline_weight_bits),
                "target_weight_hash": bits_hash(state.target_weight_bits),
                "baseline_readout_hash": bits_hash(state.baseline_readout_bits),
                "target_readout_hash": bits_hash(state.target_readout_bits),
                "coordinate_count": len(state.baseline_weight_bits),
                "row_count": len(state.rows),
            }
        )
    derived = {
        "state_inventory": state_inventory,
        "state_inventory_sha256": object_hash(state_inventory),
        "topology_invariants": contract["topology_invariants"],
        "topology_sha256": object_hash(contract["topology_invariants"]),
        "raw_group_counts": {f"{key[0]}::{key[1]}": len(value) for key, value in sorted(groups.items())},
        "raw_group_inventory_sha256": object_hash(
            [
                {
                    "key": [key[0], key[1]],
                    "group_index": group.group_index,
                    "rows": list(group.rows),
                    "coordinates": list(group.coordinates),
                    "domain_sizes": [len(domain) for domain in group.domains],
                }
                for key in sorted(groups)
                for group in groups[key]
            ]
        ),
    }
    return (lineage, {"states": states, "groups": groups, "derived": derived, "source_hashes": source_hashes})


def validate_candidate_inventory(repo: Path, pf: Any, data: dict[str, Any]) -> dict[str, Any]:
    palette_path = repo / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
    rows = [json.loads(line) for line in palette_path.read_text(encoding="utf-8").splitlines() if line]
    selected = {key: groups for key, groups in data["groups"].items()}
    by_identity = {(str(item["identity"][0]), int(item["identity"][1]), int(item["identity"][2])): item for item in rows}
    domain = []
    checked_candidates = 0
    for key in sorted(selected):
        groups = selected[key]
        for group in groups:
            identity = (key[0], key[1], group.group_index)
            item = by_identity.get(identity)
            require(item is not None, f"current GP1 candidate inventory missing group: {identity}")
            require(tuple(int(x) for x in item["coordinates_canonical"]) == group.coordinates, f"current GP1 coordinate inventory drift: {identity}")
            state = next(state for state in data["states"] if state.key == key)
            baseline_hash = item["baseline"]["committed_f32_weight_state_sha256"]
            require(baseline_hash == bits_hash(state.baseline_weight_bits), f"current GP1 baseline bytes drift: {identity}")
            for candidate in item["palette"]:
                mapping = {int(coordinate): int(choice) for coordinate, choice in candidate["canonical_mapping"]}
                require(tuple(sorted(mapping)) == group.coordinates, f"candidate coordinate map drift: {identity}")
                raw = list(state.baseline_weight_bits)
                for coordinate, choice in mapping.items():
                    if choice == 0:
                        continue
                    replacement = pf.legal_prefix_bits(state.baseline_weight_bits[coordinate], choice)
                    require(replacement is not None, f"candidate prefix is not legal in current state: {identity}")
                    raw[coordinate] = replacement
                require(bits_hash(raw) == str(candidate["committed_f32_weight_state_sha256"]).upper(), f"candidate bytes drift: {identity}")
                checked_candidates += 1
                domain.append(
                    {
                        "endpoint": key[0],
                        "set_index": key[1],
                        "group": group.group_index,
                        "from": item["baseline"]["candidate_identity"],
                        "to": candidate["candidate_identity"],
                    }
                )
    require(len(domain) > 0, "current candidate inventory produced an empty singleton domain")
    return {
        "palette_rows_selected": sum(len(data["groups"][key]) for key in selected),
        "candidate_records_checked": checked_candidates,
        "singleton_domain": domain,
        "singleton_domain_count": len(domain),
        "singleton_domain_sha256": object_hash(domain),
    }


def import_pf5(repo: Path) -> Any:
    script_dir = repo / "experiments/drosophila-heresy/q10-pf5-v1/scripts"
    sys.path.insert(0, str(script_dir))
    return importlib.import_module("run_q10_pf5")


def derive_twin(repo: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    pf = import_pf5(repo)
    _, data = fresh_lineage(repo, pf)
    candidate = validate_candidate_inventory(repo, pf, data)
    derived = dict(data["derived"])
    derived.update(candidate)
    derived["source_hashes"] = data["source_hashes"]
    derived["source_hashes_sha256"] = object_hash(data["source_hashes"])
    derived["root_manifest_sha256"] = object_hash(manifest)
    return derived


def build_contract(manifest_hash: str) -> dict[str, Any]:
    return {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "PREMEASUREMENT_SEALED",
        "plan_sha256": digest(ROOT / "PLAN.md"),
        "runner_sha256": digest(Path(__file__)),
        "root_manifest_sha256": manifest_hash,
        "closure_count": 2,
        "selected_contexts": [[key, index] for key, index in SELECTED_KEYS],
        "singleton_replay_allowed": False,
        "pair_replay_allowed": False,
        "scientific_seed_bundles": 0,
        "behavioral_probe": False,
        "scientific_promotion": False,
        "historical_inputs_are_measurements": False,
        "candidate_inventory_policy": "current GP1 mappings are byte-revalidated; scores and readouts are not imported as measurements",
    }


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "REQUAL1-DOMAIN execution already exists; immutable identity cannot rerun")
    manifest = input_manifest()
    manifest_hash = object_hash(manifest)
    write_new(ROOT / "ROOT_MANIFEST.json", manifest)
    contract = build_contract(manifest_hash)
    write_new(ROOT / "CONTRACT.json", contract)
    pre = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "PREEXECUTION_SEALED_NO_REPLAY",
        "plan_sha256": contract["plan_sha256"],
        "contract_sha256": digest(ROOT / "CONTRACT.json"),
        "runner_sha256": contract["runner_sha256"],
        "root_manifest_sha256": manifest_hash,
        "execution_started": False,
        "result_exposure": False,
        "parent_bindings_sealed": True,
        "singleton_replay_allowed": False,
        "pair_replay_allowed": False,
    }
    write_new(ROOT / "PREEXECUTION.json", pre)
    closures = {}
    results = {}
    try:
        for name in ("twin-a", "twin-b"):
            repo, copied = copy_closure(manifest, name)
            closures[name] = {"manifest_sha256": object_hash(copied), "repo": str(repo)}
            results[name] = derive_twin(repo, manifest)
            write_new(ROOT / "closures" / name / "DERIVED.json", results[name])
        comparison = {
            "root_manifest_identical": results["twin-a"]["root_manifest_sha256"] == results["twin-b"]["root_manifest_sha256"],
            "source_hashes_identical": results["twin-a"]["source_hashes_sha256"] == results["twin-b"]["source_hashes_sha256"],
            "state_inventory_identical": results["twin-a"]["state_inventory_sha256"] == results["twin-b"]["state_inventory_sha256"],
            "topology_identical": results["twin-a"]["topology_sha256"] == results["twin-b"]["topology_sha256"],
            "group_inventory_identical": results["twin-a"]["raw_group_inventory_sha256"] == results["twin-b"]["raw_group_inventory_sha256"],
            "candidate_inventory_identical": results["twin-a"]["singleton_domain_sha256"] == results["twin-b"]["singleton_domain_sha256"],
        }
        all_equal = all(comparison.values())
        counts = {
            "selected_contexts": len(SELECTED_KEYS),
            "raw_groups": sum(results["twin-a"]["raw_group_counts"].values()),
            "candidate_records_checked": results["twin-a"]["candidate_records_checked"],
            "singleton_domain_records": results["twin-a"]["singleton_domain_count"],
        }
        execution = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": "DOMAIN_READY_FOR_SMOKE" if all_equal else "BLOCKED_TWIN_DERIVED_HASH_MISMATCH",
            "engineering_only": True,
            "scientific_promotion": False,
            "behavioral_probe": False,
            "singleton_replay_executed": False,
            "pair_replay_executed": False,
            "closures": closures,
            "comparison": comparison,
            "counts": counts,
            "derived_hashes": {name: {key: value for key, value in result.items() if key.endswith("_sha256")} for name, result in results.items()},
            "firewall": {"scientific_seed_bundles": 0, "singleton_replay_allowed": False, "pair_replay_allowed": False},
        }
    except Exception as exc:
        execution = {
            "protocol": PROTOCOL,
            "identity": IDENTITY,
            "status": "BLOCKED_CURRENT_DOMAIN_REDERIVATION",
            "engineering_only": True,
            "scientific_promotion": False,
            "singleton_replay_executed": False,
            "pair_replay_executed": False,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "closures": closures,
            "firewall": {"scientific_seed_bundles": 0, "singleton_replay_allowed": False, "pair_replay_allowed": False},
        }
    write_new(ROOT / "execution.json", execution)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0 if execution["status"] == "DOMAIN_READY_FOR_SMOKE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
