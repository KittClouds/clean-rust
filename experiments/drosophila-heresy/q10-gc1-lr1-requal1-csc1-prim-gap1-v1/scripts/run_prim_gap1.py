from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[4]
EXP = ROOT / "experiments" / "drosophila-heresy"
OUT = Path(__file__).resolve().parents[1]
CONTEXT = ("seed9731-R-tau4.json", 3)
SLUG = "seed9731-R-tau4__set3"
FRONT2_SCRIPT = EXP / "q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3" / "scripts" / "run_front2.py"
ALG1 = EXP / "q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts" / "run_alg1.py"
DOMAIN = EXP / "q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures" / "twin-a" / "repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = EXP / "q10-gc1-lr1-requal1-par8-ref1-v1"
SUPPORT1 = EXP / "q10-gc1-lr1-requal1-csc1-resid-support1-v1"
PROTOCOL = "Q10-PRIM-GAP1"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest().upper()


def digest_payload(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, f"module load failed: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    allowed = {Path("PLAN.md"), Path("scripts"), Path("scripts/run_prim_gap1.py"), Path("CONTRACT.json"), Path("PREEXECUTION.json"), Path("execution.json"), Path("STATUS.json"), Path("REPORT.md"), Path("row-stats.json"), Path("gap-summary.json")}
    if OUT.exists():
        unexpected = {path.relative_to(OUT) for path in OUT.rglob("*")} - allowed
        require(not unexpected, f"unexpected output paths: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    sources = [
        ("front2_runner", FRONT2_SCRIPT),
        ("alg1_runner", ALG1_SCRIPT),
        ("alg1_descriptor", ALG1 / "descriptors" / f"{SLUG}.json"),
        ("alg1_execution", ALG1 / "execution.json"),
        ("pf5_contract", PF5_CONTRACT),
        ("reference_execution", REF / "execution.json"),
        ("support1_execution", SUPPORT1 / "execution.json"),
        ("support1_rows", SUPPORT1 / "row-stats.json"),
        ("support1_summary", SUPPORT1 / "support-summary.json"),
    ]
    parent_bindings = [{"label": label, "path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in sources]
    support_rows = json.loads((SUPPORT1 / "row-stats.json").read_text(encoding="utf-8"))["rows"]
    unsupported_rows = sorted(int(row["row"]) for row in support_rows if row["support_classification"] == "NO_PRIMITIVE_DEPENDENCY_SUPPORT")
    require(len(unsupported_rows) == 33, f"unsupported-row cardinality drift: {len(unsupported_rows)}")
    domain_hash = digest_payload({"context": list(CONTEXT), "rows": unsupported_rows})

    front2 = load_module(FRONT2_SCRIPT, "q10_prim_gap1_front2_runtime")
    alg = front2.load_alg1()
    context = front2.prepare_context(CONTEXT, alg)
    require(len(context["actions"]) == 472, f"singleton action cardinality drift: {len(context['actions'])}")
    state = context["state"]
    baseline_bits = tuple(int(value) for value in context["s"]["bits"])
    mapped_choices: dict[int, set[int]] = {}
    mapped_actions: dict[int, set[int]] = {}
    for ordinal, action in context["actions"].items():
        for coordinate, choice in action["canonical_mapping"]:
            coordinate, choice = int(coordinate), int(choice)
            raw = int(action["weight_bits"][coordinate])
            if raw == baseline_bits[coordinate]:
                continue
            mapped_choices.setdefault(coordinate, set()).add(choice)
            mapped_actions.setdefault(coordinate, set()).add(int(ordinal))

    row_records: list[dict[str, Any]] = []
    aggregate: Counter[str] = Counter()
    all_legal_nonzero = set()
    for coordinate, base_raw in enumerate(baseline_bits):
        for choice in context["pf"].CHOICES:
            if int(choice) == 0:
                continue
            raw = context["pf"].legal_prefix_bits(base_raw, int(choice))
            if raw is not None and int(raw) != base_raw:
                all_legal_nonzero.add(coordinate)

    for row in unsupported_rows:
        closure = tuple(sorted(int(coordinate) for coordinate in state.rows[row]))
        represented = tuple(coordinate for coordinate in closure if coordinate in mapped_choices)
        unrepresented = tuple(coordinate for coordinate in closure if coordinate not in mapped_choices)
        legal_unrepresented = tuple(coordinate for coordinate in unrepresented if coordinate in all_legal_nonzero)
        nonlegal_unrepresented = tuple(coordinate for coordinate in unrepresented if coordinate not in all_legal_nonzero)
        mapped_action_count = sum(len(mapped_actions[coordinate]) for coordinate in represented)
        action_rows_touching = sum(1 for rows in context["action_rows"].values() if row in rows)
        require(action_rows_touching == 0, f"unsupported row has action-row support: row={row}, count={action_rows_touching}")
        require(not set(represented), f"unsupported row has mapped coordinate in closure: row={row}, coords={represented}")
        if not closure:
            classification = "EMPTY_DEPENDENCY_CLOSURE"
        elif legal_unrepresented:
            classification = "MUTABLE_COORDINATE_UNREPRESENTED_BY_ACTION_GRAMMAR"
        elif nonlegal_unrepresented:
            classification = "NO_LEGAL_NONZERO_PREFIX_IN_CURRENT_DOMAIN"
        else:
            classification = "UNRESOLVED"
        aggregate[classification] += 1
        row_records.append({
            "row": row,
            "dependency_closure_coordinates": list(closure),
            "dependency_closure_size": len(closure),
            "represented_coordinates": list(represented),
            "unrepresented_coordinates": list(unrepresented),
            "legal_unrepresented_coordinates": list(legal_unrepresented),
            "no_legal_nonzero_prefix_coordinates": list(nonlegal_unrepresented),
            "mapped_action_count": mapped_action_count,
            "action_rows_touching_row": action_rows_touching,
            "classification": classification,
        })

    after = {label: digest(path) for label, path in sources}
    require(after == {item["label"]: item["sha256"] for item in parent_bindings}, "bound source changed during PRIM-GAP1")
    require(sum(aggregate.values()) == 33, "row classification accounting failure")
    require(aggregate["UNRESOLVED"] == 0, "unresolved primitive-gap row")

    contract = {
        "protocol": PROTOCOL,
        "identity": OUT.name,
        "status": "SEALED_PREMEASUREMENT",
        "context": list(CONTEXT),
        "parent_bindings": parent_bindings,
        "unsupported_row_domain": unsupported_rows,
        "unsupported_row_domain_sha256": domain_hash,
        "singleton_action_count": len(context["actions"]),
        "coordinate_count": len(baseline_bits),
        "prefix_choices": [int(choice) for choice in context["pf"].CHOICES],
        "replay_executed": False,
        "readout_executed": False,
        "scientific_promotion": False,
        "write_allowlist": ["PLAN.md", "scripts/*", "CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "REPORT.md", "row-stats.json", "gap-summary.json"],
    }
    write_new(OUT / "CONTRACT.json", contract)
    write_new(OUT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(OUT / "CONTRACT.json"), "replay_executed": False, "scientific_promotion": False})
    summary = {"context": list(CONTEXT), "unsupported_rows": unsupported_rows, "unsupported_row_domain_sha256": domain_hash, "classification_counts": dict(sorted(aggregate.items())), "singleton_action_count": len(context["actions"]), "coordinate_count": len(baseline_bits), "mapped_nonzero_coordinate_count": len(mapped_choices), "legal_nonzero_coordinate_count": len(all_legal_nonzero)}
    write_new(OUT / "row-stats.json", {"context": list(CONTEXT), "rows": row_records})
    write_new(OUT / "gap-summary.json", summary)
    execution = {"protocol": PROTOCOL, "identity": OUT.name, "status": "PRIM_GAP1_COMPLETE", "engineering_only": True, "replay_executed": False, "readout_executed": False, "scientific_promotion": False, "context": list(CONTEXT), "counts": summary, "parent_bindings": parent_bindings, "row_stats_sha256": digest(OUT / "row-stats.json"), "gap_summary_sha256": digest(OUT / "gap-summary.json"), "contract_sha256": digest(OUT / "CONTRACT.json"), "conclusion": "Current dependency closures were compared with the current singleton action grammar without replay; no unsupported row had a mapped nonzero action coordinate inside its closure."}
    write_new(OUT / "execution.json", execution)
    write_new(OUT / "STATUS.json", {"protocol": PROTOCOL, "identity": OUT.name, "status": execution["status"], "engineering_only": True, "replay_executed": False, "scientific_promotion": False, "execution_sha256": digest(OUT / "execution.json")})
    report = "\n".join([
        "# PRIM-GAP1 primitive-support gap audit",
        "",
        f"Context: `{CONTEXT[0]}`, set `{CONTEXT[1]}`.",
        f"Unsupported residual rows audited: `{len(unsupported_rows)}`; current singleton actions: `{len(context['actions'])}`; dependency rows: `{len(state.rows)}`.",
        f"Classification counts: `{json.dumps(dict(sorted(aggregate.items())), sort_keys=True)}`.",
        "",
        "This is a structural read-only audit. It does not establish functional reachability, invalid-state target attainment, or a need for new primitives.",
        "",
        "RESID-INVALID1, order 4, GC2, AG1, behavior, and scientific promotion remain closed.",
        "",
    ])
    write_new(OUT / "REPORT.md", report)
    print(json.dumps(execution, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

