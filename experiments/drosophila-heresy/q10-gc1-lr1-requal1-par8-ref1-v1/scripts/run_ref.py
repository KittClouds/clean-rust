"""Fresh current-lineage PAR8 reference requalification runner."""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
IDENTITY = "q10-gc1-lr1-requal1-par8-ref1-v1"
PROTOCOL = "REQUAL1-PAR8-REF1"
CLOSURE_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/closures/twin-a"
CLOSURE_REPO = CLOSURE_ROOT / "repo"
BUILDER_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/scripts"
GC1_ROOT = REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/scripts"
PF5_SCRIPTS = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts"
PALETTE = CLOSURE_REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
KEYS = (
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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def object_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def source_manifest() -> dict[str, Any]:
    paths = [
        ROOT / "PLAN.md",
        ROOT / "CONTRACT.json",
        Path(__file__),
        CLOSURE_ROOT / "MANIFEST.json",
        CLOSURE_ROOT / "DERIVED.json",
        CLOSURE_ROOT / "repo/experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/qualification/palettes.jsonl",
        CLOSURE_ROOT / "repo/experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/CONTRACT.json",
        CLOSURE_ROOT / "repo/experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json",
        REPO / "experiments/drosophila-heresy/q10-gc1-par8-v1/scripts/run_gc1.py",
        REPO / "experiments/drosophila-heresy/q10-rh1-f2-v1/scripts/run_rh1.py",
        REPO / "experiments/drosophila-heresy/q10-rh1-cq1-v1/scripts/common_runtime.py",
        REPO / "experiments/drosophila-heresy/q10-gc0-v1/scripts/run_gc0.py",
        REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1/scripts/build_domain_closure.py",
        REPO / "experiments/drosophila-heresy/q10-pf5-v1/scripts/run_q10_pf5.py",
    ]
    entries = []
    for path in paths:
        require(path.is_file(), f"missing fresh reference input: {path}")
        entries.append({"path": path.relative_to(REPO).as_posix(), "sha256": digest(path)})
    return {"protocol": PROTOCOL, "identity": IDENTITY, "entries": entries, "manifest_sha256": object_hash(entries)}


def load_modules() -> tuple[Any, Any, Any]:
    sys.path.insert(0, str(PF5_SCRIPTS))
    pf = importlib.import_module("run_q10_pf5")
    sys.path.insert(0, str(BUILDER_ROOT))
    builder = importlib.import_module("build_domain_closure")
    sys.path.insert(0, str(GC1_ROOT))
    gc1 = importlib.import_module("run_gc1")
    require(Path(gc1.RH1.PF5.__file__).resolve() == (PF5_SCRIPTS / "run_q10_pf5.py").resolve(), "assembly imported a different PF5 module")
    return pf, builder, gc1


def main() -> int:
    require(not (ROOT / "execution.json").exists(), "reference execution already sealed")
    contract = json.loads((ROOT / "CONTRACT.json").read_text(encoding="utf-8"))
    require(contract["identity"] == IDENTITY and contract["protocol"] == PROTOCOL, "reference contract identity drift")
    manifest = source_manifest()
    write_new(ROOT / "ROOT_MANIFEST.json", manifest)
    pf, builder, gc1 = load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    require(set(states) == set(KEYS), "fresh reference state coverage drift")
    palette_contract = json.loads((CLOSURE_REPO / "experiments/drosophila-heresy/q10-gc0-gp1-par2-v1/CONTRACT.json").read_text(encoding="utf-8"))
    all_palettes = gc1.compact_palettes(PALETTE)
    palettes = {key: groups for key, groups in all_palettes.items() if key in set(KEYS)}
    require(set(palettes) == set(KEYS), "fresh palette context coverage drift")
    cfg = dict(contract)
    cfg["sample"] = contract["sample"]
    counts = gc1.validate_palette_library(states, palettes, cfg)
    require(counts["raw_group_count"] == int(contract["sample"]["expected_raw_group_count"]), "fresh raw group count drift")
    require(counts["palette_count"] == int(contract["sample"]["expected_palette_count"]), "fresh palette count drift")
    raw_groups = data["groups"]
    for key, groups in palettes.items():
        raw_by_index = {int(group.group_index): group for group in raw_groups[key]}
        require(len(raw_by_index) == len(raw_groups[key]), "duplicate fresh raw group index")
        for group in groups:
            index = int(group["group_index"])
            require(index in raw_by_index, f"missing fresh raw group: {key} {index}")
            gc1.validate_group_topology(states[key], group, raw_by_index[index])
    pf5_contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    results = []
    for key in KEYS:
        result = gc1.assemble_state(key, palettes[key], states[key], pf5_contract, cfg)
        require(result["endpoint"] == key[0] and int(result["set_index"]) == key[1], "fresh result identity drift")
        results.append(result)
        print(json.dumps({"context": [key[0], key[1]], "status": result["status"], "mismatch": result["best_search"]["global_mismatch_count"], "evaluations": result["exact_evaluations"]}, sort_keys=True), flush=True)
    require(len(results) == len(KEYS), "fresh reference result cardinality drift")
    execution = {
        "protocol": PROTOCOL,
        "identity": IDENTITY,
        "status": "REQUAL1_PAR8_REFERENCE_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "behavioral_probe": False,
        "historical_par8_execution_used_as_result": False,
        "configuration": {"assembly": contract["assembly"], "geometry_metrics": contract["geometry_metrics"], "intermediate_geometry_guardrails": contract["intermediate_geometry_guardrails"]},
        "source_manifest_sha256": manifest["manifest_sha256"],
        "plan_sha256": digest(ROOT / "PLAN.md"),
        "contract_sha256": digest(ROOT / "CONTRACT.json"),
        "counts": {"endpoint_set_count": len(results), "raw_group_count": counts["raw_group_count"], "palette_count": counts["palette_count"], "exact_evaluations": sum(int(item["exact_evaluations"]) for item in results)},
        "results": results,
        "closure": {"manifest_sha256": digest(CLOSURE_ROOT / "MANIFEST.json"), "derived_sha256": digest(CLOSURE_ROOT / "DERIVED.json")},
        "palette_sha256": digest(PALETTE),
        "pf5_contract_sha256": digest(PF5_CONTRACT),
    }
    write_new(ROOT / "execution.json", execution)
    status = {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "behavioral_probe": False, "execution_sha256": digest(ROOT / "execution.json")}
    write_new(ROOT / "STATUS.json", status)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
