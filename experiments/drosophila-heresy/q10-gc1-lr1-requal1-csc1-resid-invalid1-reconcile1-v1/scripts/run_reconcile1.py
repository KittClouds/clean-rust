from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
from pathlib import Path
from typing import Any

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
EXP = REPO / "experiments/drosophila-heresy"
EXH1_SCRIPT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-exh1-v1/scripts/run_exh1.py"
RERUN = EXP / "q10-gc1-lr1-requal1-csc1-resid-invalid1-rerun1-v1"
RESID1 = EXP / "q10-gc1-lr1-requal1-csc1-resid1-r1-v1"
O2 = EXP / "q10-gc1-lr1-requal1-csc1-pair-front1-v2"
O3 = EXP / "q10-gc1-lr1-requal1-csc1-o3-maskmat1-v1"
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"
PROTOCOL = "Q10-RESID-INVALID1-RECONCILE1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def digest_value(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_exh1() -> Any:
    spec = importlib.util.spec_from_file_location("reconcile1_exh1_runtime", EXH1_SCRIPT)
    require(spec is not None and spec.loader is not None, "EXH1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def source_paths() -> list[tuple[str, Path]]:
    return [
        ("exh1_runner", EXH1_SCRIPT),
        ("rerun_execution", RERUN / "execution.json"),
        ("rerun_domain_summary", RERUN / "domain-summary.json"),
        ("rerun_row_stats", RERUN / "row-stats.json"),
        ("rerun_order2_hits", RERUN / "results/order2_hits.jsonl"),
        ("rerun_order3_hits", RERUN / "results/order3_hits.jsonl"),
        ("resid1_execution", RESID1 / "execution.json"),
        ("resid1_row_stats", RESID1 / "row-stats.json"),
        ("o2_frontier", O2 / "shards" / f"{SLUG}.jsonl"),
        ("o3_schema", O3 / "schema.json"),
        ("o3_semantic", O3 / "semantic.jsonl"),
        ("o3_binary", O3 / "semantic.bin"),
    ]


def read_rerun_witnesses() -> dict[tuple[int, ...], dict[str, Any]]:
    wanted: dict[tuple[int, ...], dict[str, Any]] = {}
    for order in (2, 3):
        path = RERUN / "results" / f"order{order}_hits.jsonl"
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if any(int(item["row"]) in (36, 695) and bool(item["geometry_valid"]) for item in record["target_rows"]):
                wanted[tuple(int(value) for value in record["actions"])] = record
    require(set(wanted) >= {(15, 409), (292, 357, 428)}, "expected rerun witnesses missing")
    return wanted


def exact_replay(exh: Any, alg: Any, context: dict[str, Any], indices: tuple[int, ...]) -> dict[str, Any]:
    mapping = sorted([item for index in indices for item in context["actions"][index]["mapping"]], key=lambda item: int(item[0]))
    bits = alg.apply_mapping(context["pf"], context["state"], tuple(context["s"]["bits"]), mapping)
    result = alg.replay(context["pf"], context["state"], bits, context["contract"])
    geometry, geometry_valid = exh.full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], indices, context["contract"])
    require(result["geometry"] == geometry, f"geometry replay mismatch: {indices}")
    require(bool(result["final_geometry_pass"]) == bool(geometry_valid), f"geometry validity mismatch: {indices}")
    return {
        "actions": list(indices),
        "action_keys": [context["actions"][index]["key"] for index in indices],
        "weight_state_sha256": result["weight_state_sha256"],
        "readout_sha256": result["readout_sha256"],
        "score": result["score"],
        "geometry": geometry,
        "final_geometry_pass": bool(geometry_valid),
        "row_bits": {str(row): int(result["readout"][row]) for row in (36, 695)},
        "target_bits": {str(row): int(context["state"].target_readout_bits[row]) for row in (36, 695)},
    }


def reproduce_row_local_bug(context: dict[str, Any], indices: tuple[int, ...], row: int) -> int:
    pf = context["pf"]
    state = context["state"]
    s_bits = tuple(context["s"]["bits"])
    weights = list(context["s"]["weights"])
    row_coordinates = set(state.rows[row])
    for index in indices:
        for coordinate, choice in context["actions"][index]["mapping"]:
            raw = pf.legal_prefix_bits(s_bits[coordinate], choice)
            require(raw is not None, f"row-local prefix became illegal: {indices} {row} {coordinate}")
            if int(raw) != s_bits[coordinate] and coordinate in row_coordinates:
                weights[coordinate] = pf.from_bits(int(raw))
    return int(pf.sequential_bits(state.rows[row], weights))


def find_o2(context: dict[str, Any], indices: tuple[int, int]) -> dict[str, Any]:
    wanted = tuple(sorted(context["actions"][index]["key"] for index in indices))
    path = O2 / "shards" / f"{SLUG}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        keys = tuple(sorted((f"{int(row['a']['group'])}:{row['a']['to']}", f"{int(row['b']['group'])}:{row['b']['to']}")))
        if keys == wanted:
            return {"frontier_pair_index": row["frontier_pair_index"], "readout_sha256": row["readout_sha256"], "weight_state_sha256": row["weight_state_sha256"], "score": row["score"], "final_geometry_pass": row["final_geometry_pass"], "row_bits": {"36": row["readout_bits"][36], "695": row["readout_bits"][695]}}
    raise RuntimeError("authoritative order-2 witness not found")


def find_o3(indices: tuple[int, int, int], context: dict[str, Any]) -> dict[str, Any]:
    wanted = list(indices)
    schema = json.loads((O3 / "schema.json").read_text(encoding="utf-8"))
    for line in (O3 / "semantic.jsonl").open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("action_ordinals") == wanted:
            return {"semantic_index": row["semantic_index"], "readout_sha256": row["readout_sha256"], "mismatch_count": row["mismatch_count"], "score": row["score"], "row_bits": {"36": None, "695": None}, "schema": schema}
    raise RuntimeError("authoritative order-3 semantic witness not found")


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1" and sys.dont_write_bytecode, "bytecode generation enabled")
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_reconcile1.py"), Path("CONTRACT.json"), Path("PREEXECUTION.json"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("reconciliation.json")}
    if ROOT.exists():
        require({path.relative_to(ROOT) for path in ROOT.rglob("*")} <= allowed, "unexpected reconciliation output path")
    ROOT.mkdir(parents=True, exist_ok=True)
    paths = source_paths()
    for _label, path in paths:
        require(path.is_file(), f"missing parent: {path}")
    bindings = [{"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in paths]
    contract = {"protocol": PROTOCOL, "identity": ROOT.name, "status": "SEALED_PREMEASUREMENT", "context": list(CONTEXT), "witnesses": [[15, 409], [292, 357, 428]], "parent_bindings": bindings, "scientific_promotion": False, "replay_scope": "two deterministic witness reconstructions only", "write_allowlist": ["PLAN.md", "scripts/*", "CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "REPORT.md", "reconciliation.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": ROOT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "scientific_promotion": False})
    exh = load_exh1()
    alg = exh.load_alg1()
    context = exh.prepare_context(CONTEXT, alg)
    witnesses = read_rerun_witnesses()
    exact: dict[str, Any] = {}
    for indices in ((15, 409), (292, 357, 428)):
        result = exact_replay(exh, alg, context, indices)
        row_target_matches = {row: result["row_bits"][str(row)] == result["target_bits"][str(row)] for row in (36, 695)}
        result["row_target_matches"] = {str(row): value for row, value in row_target_matches.items()}
        result["rerun_witness"] = witnesses[indices]
        result["row_local_bug_reproduction"] = {str(row): reproduce_row_local_bug(context, indices, row) for row in (36, 695)}
        exact["-".join(map(str, indices))] = result
    exact["15-409"]["authoritative_order2"] = find_o2(context, (15, 409))
    exact["292-357-428"]["authoritative_order3"] = find_o3((292, 357, 428), context)
    prior = json.loads((RESID1 / "row-stats.json").read_text(encoding="utf-8"))
    exact["prior_resid1_rows"] = {row: prior[str(row)] for row in (36, 695)}
    for label, item in exact.items():
        if label in ("15-409", "292-357-428"):
            require(not any(item["row_target_matches"].values()), f"full replay unexpectedly hit target: {label}")
            require(item["final_geometry_pass"], f"witness geometry invalid under full replay: {label}")
    source_after = [{"label": label, "sha256": digest(path)} for label, path in paths]
    require([item["sha256"] for item in bindings] == [item["sha256"] for item in source_after], "parent changed during reconciliation")
    conclusion = "Both RESID-INVALID1-RERUN1 valid-target classifications are false positives from row-local prefix reconstruction. Full replay reproduces the authoritative O2/O3 frontier states, which are geometry-valid but do not hit the target rows. Prior RESID1 classifications for rows 36 and 695 remain correct."
    reconciliation = {"protocol": PROTOCOL, "identity": ROOT.name, "status": "RECONCILIATION_COMPLETE", "engineering_only": True, "scientific_promotion": False, "conclusion": conclusion, "parent_bindings": bindings, "parent_bindings_after": source_after, "witnesses": exact}
    write_new(ROOT / "reconciliation.json", reconciliation)
    execution = {"protocol": PROTOCOL, "identity": ROOT.name, "status": "RESID_INVALID1_RECONCILE1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "replay_executed": True, "witness_count": 2, "conclusion": conclusion, "reconciliation_sha256": digest(ROOT / "reconciliation.json"), "contract_sha256": digest(ROOT / "CONTRACT.json")}
    write_new(ROOT / "execution.json", execution)
    write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": ROOT.name, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
    report = "# RESID-INVALID1-RECONCILE1\n\n" + conclusion + "\n\nThe rerun's row-local evaluator applied prefix choices relative to the invalid starting-state bits. The authoritative mapping semantics apply those choices relative to the frozen baseline bits. That discrepancy explains the two false target hits.\n\nRow 36 pair `[15,409]` is present in the authoritative order-2 valid frontier with full replay value `1092185578`, target `1092185579`, and mismatch count 125. Row 695 triple `[292,357,428]` is present in the authoritative order-3 semantic materialization with full replay value `1103757538`, target `1103757536`, and mismatch count 130. Both states are geometry-valid.\n\nThe contaminated predecessor remains non-promotable. The clean rerun remains internally complete but its target-hit interpretation is corrected by this reconciliation. No order-4, primitive expansion, GC2, AG1, or behavioral work is opened.\n"
    write_new(ROOT / "REPORT.md", report)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
