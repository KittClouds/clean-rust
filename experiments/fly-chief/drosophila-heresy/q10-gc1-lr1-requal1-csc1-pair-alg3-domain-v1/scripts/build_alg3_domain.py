from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-PAIR-ALG3-DOM1"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
UVD0 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-uvd0-v1"
CONTEXTS = (
    ("seed9731-L-tau16.json", 2), ("seed9731-L-tau4.json", 3),
    ("seed9731-R-tau16.json", 1), ("seed9731-R-tau16.json", 3),
    ("seed9731-R-tau4.json", 0), ("seed9731-R-tau4.json", 1),
    ("seed9731-R-tau4.json", 2), ("seed9731-R-tau4.json", 3),
)
PER_CONTEXT = 256


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def write_bytes_new(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_context(key: tuple[str, int]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    actions = {str(item["action_key"]): item for item in descriptor["actions"]}
    require(len(actions) == len(descriptor["actions"]), f"descriptor duplicate action: {key}")
    rows = [json.loads(line) for line in (UVD0 / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines() if line]
    return actions, rows


def action_key(item: dict[str, Any]) -> str:
    return f"{int(item['group'])}:{str(item['to'])}"


def coordinates(action: dict[str, Any]) -> set[int]:
    return {int(coordinate) for coordinate, _choice in action["canonical_mapping"]}


def run_context(key: tuple[str, int]) -> dict[str, Any]:
    actions, pair_rows = load_context(key)
    action_coords = {name: coordinates(item) for name, item in actions.items()}
    action_names = tuple(sorted(actions))
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for pair in pair_rows:
        a_id = action_key(pair["a"])
        b_id = action_key(pair["b"])
        used = action_coords[a_id] | action_coords[b_id]
        candidates = [name for name in action_names if name not in (a_id, b_id) and not (action_coords[name] & used)]
        candidates.sort(key=lambda name: hashlib.sha256(f"{slug(key)}|{a_id}|{b_id}|{name}".encode("utf-8")).hexdigest())
        for c_id in candidates:
            triple = tuple(sorted((a_id, b_id, c_id)))
            if triple in seen:
                continue
            seen.add(triple)
            selected.append({"triple_index": len(selected), "case": [key[0], key[1]], "a": triple[0], "b": triple[1], "c": triple[2], "coordinate_count": sum(len(action_coords[name]) for name in triple), "pair_source_uvd0_index": int(pair["pair_index"])})
            break
        if len(selected) >= PER_CONTEXT:
            break
    require(len(selected) == PER_CONTEXT, f"insufficient compatible triples: {key} {len(selected)}")
    path = ROOT / "shards" / f"{slug(key)}.jsonl"
    payload = "".join(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n" for item in selected).encode("utf-8")
    write_bytes_new(path, payload)
    return {"context": [key[0], key[1]], "source_pairs": len(pair_rows), "triple_records": len(selected), "shard": path.name, "shard_sha256": digest(path)}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(not (ROOT / "execution.json").exists(), "ALG3 domain execution already exists")
    inputs = [("alg3_domain_plan", ROOT / "PLAN.md"), ("alg3_domain_runner", Path(__file__)), ("alg1_execution", ALG1 / "execution.json"), ("uvd0_execution", UVD0 / "execution.json"), ("uvd0_contract", UVD0 / "CONTRACT.json")]
    for key in CONTEXTS:
        inputs.extend([(f"alg1_descriptor:{slug(key)}", ALG1 / "descriptors" / f"{slug(key)}.json"), (f"uvd0_shard:{slug(key)}", UVD0 / "shards" / f"{slug(key)}.jsonl")])
    bindings = [{"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)} for label, path in inputs]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "per_context_triples": PER_CONTEXT, "outcomes_consulted": False, "geometry_executed": False, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json")})
    results = []
    try:
        for key in CONTEXTS:
            result = run_context(key)
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
        require(sum(item["triple_records"] for item in results) == PER_CONTEXT * len(CONTEXTS), "ALG3 domain cardinality drift")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_DOMAIN_COMPLETE", "engineering_only": True, "scientific_promotion": False, "outcomes_consulted": False, "geometry_executed": False, "readout_executed": False, "counts": {"contexts": len(CONTEXTS), "triple_records": sum(item["triple_records"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json")}
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_DOMAIN", "engineering_only": True, "scientific_promotion": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
