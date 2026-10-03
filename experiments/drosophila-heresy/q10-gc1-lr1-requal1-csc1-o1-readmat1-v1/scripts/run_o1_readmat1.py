from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[4]
OUT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "drosophila-heresy"
SINGLE = EXP / "q10-gc1-lr1-requal1-sreplace-singles-v1"
SINGLE_SCRIPT = SINGLE / "scripts" / "run_sreplace_singles.py"
SINGLE_EXEC = SINGLE / "execution.json"
SHARDS = SINGLE / "shards"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def digest_bits(values: list[int] | tuple[int, ...]) -> str:
    payload = b"".join(int(value).to_bytes(4, "little", signed=False) for value in values)
    return hashlib.sha256(payload).hexdigest().upper()


def load_runtime() -> Any:
    spec = importlib.util.spec_from_file_location("q10_o1_readmat_singletons", SINGLE_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("singleton runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module.IDENTITY != "q10-gc1-lr1-requal1-sreplace-singles-v1":
        raise RuntimeError("wrong singleton runtime identity")
    return module


def main() -> int:
    if OUT.exists():
        allowed = {
            Path("PLAN.md"),
            Path("scripts"),
            Path("scripts/run_o1_readmat1.py"),
            Path("execution.json"),
            Path("STATUS.json"),
            Path("REPORT.md"),
            Path("records.jsonl"),
        }
        existing = {path.relative_to(OUT) for path in OUT.rglob("*")}
        unexpected = existing - allowed
        if unexpected:
            raise RuntimeError(f"unexpected output files: {sorted(map(str, unexpected))}")
    else:
        OUT.mkdir(parents=True, exist_ok=False)
        (OUT / "scripts").mkdir()

    source_paths = [SINGLE_EXEC, SINGLE_SCRIPT]
    shard_paths = sorted(SHARDS.glob("*.jsonl"))
    source_paths.extend(shard_paths)
    before = {str(path): sha256(path) for path in source_paths}
    execution_parent = load_json(SINGLE_EXEC)
    if execution_parent.get("status") != "SREPLACE_SINGLETONS_COMPLETE":
        raise RuntimeError("singleton parent is not complete")
    runtime = load_runtime()
    pf, builder = runtime.load_modules()
    pf5_contract = load_json(runtime.PF5_CONTRACT)
    _, data = builder.fresh_lineage(runtime.CLOSURE_REPO, pf)
    states = {state.key: state for state in data["states"]}
    ref_execution = load_json(runtime.REF_ROOT / "execution.json")
    reference_s: dict[tuple[str, int], dict[str, Any]] = {}
    palette_rows: dict[tuple[str, int, int], dict[str, Any]] = {}
    for key, state in states.items():
        ref_result = next(
            item for item in ref_execution["results"]
            if str(item["endpoint"]) == key[0] and int(item["set_index"]) == key[1]
        )
        s_replayed, _v_replayed = runtime.verify_reference(pf, state, ref_result, pf5_contract)
        reference_s[key] = s_replayed
    for line in runtime.PALETTE.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        key = (str(item["identity"][0]), int(item["identity"][1]), int(item["identity"][2]))
        palette_rows[key] = item
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    parity_failures = 0
    for shard in shard_paths:
        source_rows = load_json(shard)
        if not isinstance(source_rows, list):
            raise RuntimeError(f"singleton shard is not an array: {shard}")
        for source in source_rows:
            key = (str(source["endpoint"]), int(source["set_index"]))
            state = states.get(key)
            if state is None:
                raise RuntimeError(f"missing current state: {key}")
            identity = f"{source['endpoint']}|{source['set_index']}|{source['group']}|{source['to']}"
            if identity in seen:
                raise RuntimeError(f"duplicate singleton identity: {identity}")
            seen.add(identity)
            group_index = int(source["group"])
            palette = palette_rows.get((key[0], key[1], group_index))
            if palette is None:
                raise RuntimeError(f"missing palette group: {key} {group_index}")
            candidate = next(
                item for item in palette["palette"]
                if str(item["candidate_identity"]) == str(source["to"])
            )
            mapping = [[int(coordinate), int(choice)] for coordinate, choice in candidate["canonical_mapping"]]
            if mapping != [[int(coordinate), int(choice)] for coordinate, choice in source["canonical_mapping"]]:
                raise RuntimeError(f"singleton mapping drift: {identity}")
            bits = list(reference_s[key]["bits"])
            for coordinate, _choice, committed in candidate["committed_f32_mapping"]:
                bits[int(coordinate)] = int(committed)
            bits = tuple(bits)
            replayed = runtime.replay(pf, state, bits, pf5_contract)
            score_key = list(runtime.score_key(replayed["score"]))
            expected_score_key = [
                int(source["score"]["mismatch_count"]),
                int(source["score"]["total_ulp_distance"]),
                float(source["score"]["residual_l2"]),
                float(source["score"]["maximum_absolute_residual"]),
            ]
            checks = {
                "weight": replayed["weight_state_sha256"] == str(source["weight_state_sha256"]).upper(),
                "readout": replayed["readout_sha256"] == str(source["readout_sha256"]).upper(),
                "score": replayed["score"] == source["score"],
                "geometry": replayed["geometry"] == source["geometry"],
                "gate": bool(replayed["final_geometry_pass"]) == bool(source["final_geometry_pass"]),
            }
            if not all(checks.values()):
                parity_failures += 1
                raise RuntimeError(f"singleton parity mismatch: {identity} {checks}")
            records.append({
                "identity": identity,
                "endpoint": key[0],
                "set_index": key[1],
                "group": int(source["group"]),
                "from": str(source["from"]),
                "to": str(source["to"]),
                "canonical_mapping": mapping,
                "weight_state_sha256": replayed["weight_state_sha256"],
                "readout_sha256": replayed["readout_sha256"],
                "readout_bits": list(replayed["readout"]),
                "score": replayed["score"],
                "score_key": score_key,
                "geometry": replayed["geometry"],
                "final_geometry_pass": bool(replayed["final_geometry_pass"]),
                "strictly_better_than_V": bool(source["strictly_better_than_V"]),
                "source_parity": checks,
            })

    if len(records) != 3696 or len(seen) != 3696:
        raise RuntimeError(f"singleton cardinality mismatch: {len(records)} / {len(seen)}")
    after = {str(path): sha256(path) for path in source_paths}
    if before != after:
        raise RuntimeError("source changed during O1-READMAT1")
    records.sort(key=lambda item: (item["endpoint"], item["set_index"], item["group"], item["to"]))
    payload = "\n".join(json.dumps(record, sort_keys=True, separators=(",", ":")) for record in records) + "\n"
    (OUT / "records.jsonl").write_text(payload, encoding="utf-8", newline="\n")
    execution = {
        "identity": OUT.name,
        "protocol": "Q10-O1-READMAT1",
        "status": "O1_READMAT1_COMPLETE",
        "engineering_only": True,
        "replay_executed": True,
        "scientific_promotion": False,
        "parent_sha256": {str(path): sha256(path) for path in source_paths},
        "counts": {
            "contexts": 8,
            "records": len(records),
            "parity_failures": parity_failures,
            "full_readout_vectors": len(records),
        },
        "records_sha256": sha256(OUT / "records.jsonl"),
    }
    (OUT / "execution.json").write_text(json.dumps(execution, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "STATUS.json").write_text(json.dumps({
        "identity": OUT.name,
        "status": execution["status"],
        "replay_executed": True,
        "scientific_promotion": False,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUT / "REPORT.md").write_text(
        "# O1-READMAT1\n\n"
        "Fresh order-1 readout materialization completed with exact parity against all 3,696 sealed singleton receipts.\n\n"
        "Every record now carries the complete sequential-f32 `readout_bits` vector, its readout hash, score, geometry, and canonical mapping. This closes the order-1 row-semantic measurement gap for downstream residual analysis.\n",
        encoding="utf-8",
        newline="\n",
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"O1_READMAT1_FAILED: {exc}", file=sys.stderr)
        raise
