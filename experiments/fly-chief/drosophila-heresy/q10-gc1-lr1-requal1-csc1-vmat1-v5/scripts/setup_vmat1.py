"""Seal the current-lineage VMAT1 premeasurement contract."""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-VMAT1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-vmat1-v5"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_ROOT = DOMAIN_ROOT / "closures/twin-a"
CLOSURE_REPO = CLOSURE_ROOT / "repo"
PAIR_DOMAIN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
PAIR_RUN_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1"
REF_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
PF5_ROOT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1"
PAIR_KEYS = (
    ("seed9731-L-tau16.json", 2),
    ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1),
    ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0),
    ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2),
    ("seed9731-R-tau4.json", 3),
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    return digest_bytes(path.read_bytes())


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


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing current-lineage parent: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}


def import_current_modules() -> tuple[Any, Any]:
    pair_script = PAIR_RUN_ROOT / "scripts"
    sys.path.insert(0, str(pair_script))
    module = importlib.import_module("run_pairs")
    pf, builder = module.load_modules()
    require(Path(pf.__file__).resolve() == (CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts/run_q10_pf5.py").resolve(), "wrong PF5 module loaded")
    require(Path(builder.__file__).resolve() == (DOMAIN_ROOT / "scripts/build_domain_closure.py").resolve(), "wrong current domain builder loaded")
    return pf, builder


def ordered_domain() -> list[dict[str, Any]]:
    execution = load_json(PAIR_DOMAIN_ROOT / "execution.json")
    require(execution["status"] == "SREPLACE_PAIR_DOMAIN_COMPLETE", "pair domain is not complete")
    rows: list[dict[str, Any]] = []
    for key in PAIR_KEYS:
        path = PAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl"
        expected = str(execution["shard_hashes"][slug(key)]).upper()
        require(digest(path) == expected, f"pair domain shard drift: {key}")
        shard = load_json(path)
        for row in shard:
            rows.append({
                "context": [key[0], key[1]],
                "pair_index": int(row["pair_index"]),
                "a_group": int(row["a"]["group"]),
                "a_to": str(row["a"]["to"]),
                "b_group": int(row["b"]["group"]),
                "b_to": str(row["b"]["to"]),
                "a_mapping": row["a"]["canonical_mapping"],
                "b_mapping": row["b"]["canonical_mapping"],
                "application_base": row["application_base"],
            })
    require(len(rows) == 4999, f"pair domain cardinality drift: {len(rows)}")
    identities = [(tuple(item["context"]), item["pair_index"]) for item in rows]
    require(len(set(identities)) == len(identities), "duplicate pair domain identity")
    return rows


def current_state_inventory(builder: Any, pf: Any) -> tuple[dict[str, Any], dict[tuple[str, int], Any]]:
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    require(set(states) == set(PAIR_KEYS), "current state context set drift")
    inventory = []
    schemas = {}
    for key in PAIR_KEYS:
        state = states[key]
        row_ids = list(range(len(state.rows)))
        schemas[slug(key)] = {
            "context": [key[0], key[1]],
            "linear_drive_row_order": row_ids,
            "linear_drive_row_count": len(row_ids),
            "linear_drive_schema_sha256": object_hash(row_ids),
        }
        inventory.append({
            "context": [key[0], key[1]],
            "coordinate_count": len(state.baseline_weight_bits),
            "row_count": len(state.rows),
            "baseline_weight_sha256": digest_bytes(b"".join(int(x).to_bytes(4, "little") for x in state.baseline_weight_bits)),
            "target_weight_sha256": digest_bytes(b"".join(int(x).to_bytes(4, "little") for x in state.target_weight_bits)),
            "baseline_readout_sha256": digest_bytes(b"".join(int(x).to_bytes(4, "little") for x in state.baseline_readout_bits)),
            "target_readout_sha256": digest_bytes(b"".join(int(x).to_bytes(4, "little") for x in state.target_readout_bits)),
        })
    return {"contexts": inventory, "contexts_sha256": object_hash(inventory), "schemas": schemas}, states


def parent_bindings() -> list[dict[str, Any]]:
    paths: list[tuple[str, Path]] = [
        ("pair_domain_execution", PAIR_DOMAIN_ROOT / "execution.json"),
        ("pair_domain_plan", PAIR_DOMAIN_ROOT / "PLAN.md"),
        ("pair_domain_contract", PAIR_DOMAIN_ROOT / "CONTRACT.json"),
        ("pair_domain_runner", PAIR_DOMAIN_ROOT / "scripts/derive_pair_domain.py"),
        ("pair_run_execution", PAIR_RUN_ROOT / "execution.json"),
        ("pair_run_runner", PAIR_RUN_ROOT / "scripts/run_pairs.py"),
        ("pair_run_finalizer_report", PAIR_RUN_ROOT.parent / "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-finalizer-v1/REPORT.json"),
        ("morphology_report", PAIR_RUN_ROOT.parent / "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-morphology-v1/REPORT.json"),
        ("interaction_execution", PAIR_RUN_ROOT.parent / "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-v1/execution.json"),
        ("interaction_finalizer_report", PAIR_RUN_ROOT.parent / "q10-gc1-lr1-requal1-sreplace-pairs-rerun1-interaction-finalizer-v1/REPORT.json"),
        ("coverage_report", PAIR_RUN_ROOT.parent / "q10-gc1-lr1-requal1-csc1-coverage-v1/REPORT.json"),
        ("fresh_reference_execution", REF_ROOT / "execution.json"),
        ("closure_manifest", CLOSURE_ROOT / "MANIFEST.json"),
        ("closure_derived", CLOSURE_ROOT / "DERIVED.json"),
        ("current_domain_builder", DOMAIN_ROOT / "scripts/build_domain_closure.py"),
        ("current_pf5_runner", PF5_ROOT / "scripts/run_q10_pf5.py"),
        ("current_pf5_contract", PF5_ROOT / "CONTRACT.json"),
    ]
    for key in PAIR_KEYS:
        paths.append((f"pair_domain_shard:{slug(key)}", PAIR_DOMAIN_ROOT / "shards" / f"{slug(key)}.jsonl"))
    return [bind(label, path) for label, path in paths]


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "CONTRACT.json").exists(), "VMAT1 v2 already sealed")
    require((ROOT / "PLAN.md").is_file() and (ROOT / "scripts/vmat1.py").is_file(), "VMAT1 plan/runner missing")
    for name in ("shards", "sidecars", "context-schema"):
        (ROOT / name).mkdir(parents=True, exist_ok=True)
    pf, builder = import_current_modules()
    domain = ordered_domain()
    current, states = current_state_inventory(builder, pf)
    require(len(states) == 8, "current context reconstruction did not produce eight states")
    pf5_contract = load_json(PF5_ROOT / "CONTRACT.json")
    gates = pf5_contract["geometry"]["final_da2_gates"]
    tolerance = {
        "axis_normalized_abs": float(gates["axis_normalized_abs"]),
        "norm_normalized_abs": float(gates["norm_normalized_abs"]),
        "cue_linear_normalized_abs": float(gates["cue_linear_normalized_abs"]),
        "raw_denominators": {
            "axis": "max(abs(target_axis), 1e-12)",
            "norm": "max(target_norm, 1e-12)",
            "linear_drive": "max(l2(target_drive), 1e-12)",
        },
        "gate_normalized_admissibility": "abs(axis)<=1; abs(norm)<=1; l2(linear_drive)<=1",
    }
    bindings = parent_bindings()
    write_new(ROOT / "domain-manifest.json", {"protocol": PROTOCOL, "identity": IDENTITY, "count": len(domain), "ordered_pairs": domain, "ordered_pairs_sha256": object_hash(domain)})
    write_new(ROOT / "tolerance-schema.json", {"protocol": PROTOCOL, "identity": IDENTITY, "source_pf5_contract_sha256": digest(PF5_ROOT / "CONTRACT.json"), "tolerance": tolerance})
    for name, schema in current["schemas"].items():
        write_new(ROOT / "context-schema" / f"{name}.json", schema)
    contract = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "PREMEASUREMENT_SEALED",
        "plan_sha256": digest(ROOT / "PLAN.md"),
        "runner_sha256": digest(ROOT / "scripts/vmat1.py"),
        "parent_bindings": bindings,
        "domain_manifest_sha256": digest(ROOT / "domain-manifest.json"),
        "tolerance_schema_sha256": digest(ROOT / "tolerance-schema.json"),
        "context_schema_sha256": object_hash({name: digest(ROOT / "context-schema" / f"{name}.json") for name in sorted(current["schemas"])}),
        "current_context_inventory_sha256": current["contexts_sha256"],
        "counts": {"contexts": 8, "pair_records": len(domain), "states_per_pair": 4},
        "write_allowlist": ["records/*.jsonl", "shards/*.jsonl", "sidecars/*", "execution.json", "STATUS.json"],
        "array_schema": {"weights": "little-endian uint32 f32 bits", "readout": "little-endian uint32 f32 bits", "linear_drive": "little-endian float64", "constraint_raw": "little-endian float64", "constraint_gate": "little-endian float64"},
        "geometry_semantics": "signed axis and norm residual intervals plus signed linear-drive residual L2 ball; no componentwise linear-drive gate",
        "firewall": {"pair_domain_frozen": True, "search": False, "historical_measurement_import": False, "scientific_seed_bundles": 0, "behavioral_probe": False, "scientific_promotion": False},
    }
    write_new(ROOT / "CONTRACT.json", contract)
    pre = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED_NO_REPLAY", "contract_sha256": digest(ROOT / "CONTRACT.json"), "domain_manifest_sha256": digest(ROOT / "domain-manifest.json"), "execution_started": False, "measured_records": 0, "scientific_promotion": False}
    write_new(ROOT / "PREEXECUTION.json", pre)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED_NO_REPLAY", "scientific_promotion": False, "execution_sha256": None})
    print(json.dumps({"identity": IDENTITY, "status": "PREEXECUTION_SEALED_NO_REPLAY", "pair_records": len(domain), "domain_manifest_sha256": digest(ROOT / "domain-manifest.json"), "current_context_inventory_sha256": current["contexts_sha256"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
