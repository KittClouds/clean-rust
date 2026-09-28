from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
FRONT2 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-front2-v3"
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-domain-r2-v1"
CLOSURE_REPO = DOMAIN / "closures/twin-a/repo"
PF5_CONTRACT = CLOSURE_REPO / "experiments/drosophila-heresy/q10-pf5-v1/CONTRACT.json"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
CONTEXTS = (
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
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_front2_audit_alg1", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong ALG1 runtime")
    return module


def prepare_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = load_json(PF5_CONTRACT)
    reference = load_json(REF / "execution.json")
    ref_result = next(item for item in reference["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    descriptor = load_json(ALG1 / "descriptors" / f"{slug(key)}.json")
    actions = sorted(descriptor["actions"], key=lambda row: (int(row["group"]), str(row["to"])))
    assignments: dict[int, tuple[tuple[int, int, float], ...]] = {}
    for ordinal, row in enumerate(actions):
        current = []
        for coordinate, choice in row["canonical_mapping"]:
            coordinate = int(coordinate)
            raw = int(row["weight_bits"][coordinate])
            current.append((coordinate, raw, pf.from_bits(raw)))
        assignments[ordinal] = tuple(current)
    return {"pf": pf, "state": state, "s": s, "assignments": assignments}


def reconstruct_sample(context: dict[str, Any], record: dict[str, Any], alg: Any) -> dict[str, Any]:
    pf = context["pf"]
    state = context["state"]
    bits = list(context["s"]["bits"])
    weights = list(context["s"]["weights"])
    for ordinal in record["action_ordinals"]:
        for coordinate, raw, value in context["assignments"][int(ordinal)]:
            bits[coordinate] = raw
            weights[coordinate] = value
    full = tuple(int(value) for value in pf.readout_bits(state.rows, weights))
    score = alg.score_dict(pf, full, state.target_readout_bits)
    return {
        "global_rank": int(record["global_rank"]),
        "local_rank": int(record["local_rank"]),
        "context": record["context"],
        "readout_sha256": alg.bits_hash(full),
        "weight_sha256": alg.bits_hash(tuple(bits)),
        "score": score,
        "matches_receipt": alg.bits_hash(full) == record["readout_sha256"] and score == record["score"],
    }


def expected_paths() -> set[str]:
    allowed = {"CONTRACT.json", "PREEXECUTION.json", "execution.json", "PLAN.md", "STATUS.json", "scripts/run_front2.py"}
    for key in CONTEXTS:
        name = slug(key)
        allowed.add(f"results/{name}")
        allowed.add(f"range-summaries/{name}")
    return allowed


def audit_write_surface() -> list[str]:
    unexpected = []
    allowed = expected_paths()
    for path in FRONT2.rglob("*"):
        relative = path.relative_to(FRONT2).as_posix()
        if path.is_dir():
            continue
        if relative in allowed:
            continue
        if any(relative.startswith(prefix + "/") for prefix in ("results", "range-summaries")):
            suffix = Path(relative).suffix
            if suffix in {".jsonl", ".json"}:
                continue
        unexpected.append(relative)
    return sorted(unexpected)


def audit_context(key: tuple[str, int], execution: dict[str, Any], alg: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = slug(key)
    entry = next(item for item in execution["contexts"] if item["context"] == [key[0], key[1]])
    summary_dir = FRONT2 / "range-summaries" / name
    result_dir = FRONT2 / "results" / name
    expected_local = 0
    previous_local_rank = -1
    total = improved = exact = 0
    summaries = []
    samples: list[dict[str, Any]] = []
    first_record = None
    first_rescue = None
    for source in sorted(entry["ranges"], key=lambda row: int(row["start"])):
        start, end = int(source["start"]), int(source["end"])
        result_path = REPO / source["result_path"]
        summary_path = summary_dir / Path(source["result_path"]).with_suffix(".json").name
        require(result_path.exists() and summary_path.exists(), f"missing FRONT2 range output: {key} {start}")
        summary = load_json(summary_path)
        require(summary["start"] == start and summary["end"] == end, f"range boundary drift: {key} {start}")
        output_hash = hashlib.sha256()
        records = range_improved = range_exact = 0
        with result_path.open("rb") as stream:
            for raw_line in stream:
                output_hash.update(raw_line)
                record = json.loads(raw_line.decode("utf-8"))
                require(record["context"] == [key[0], key[1]], f"context drift: {key} {start}")
                local_rank = int(record["local_rank"])
                require(local_rank > previous_local_rank, f"local rank order/duplicate: {key} {local_rank}")
                previous_local_rank = local_rank
                expected_local += 1
                records += 1
                improved_flag = bool(record["improved_vs_V"])
                exact_flag = bool(record["exact_target_distinct"])
                range_improved += int(improved_flag)
                range_exact += int(exact_flag)
                improved += int(improved_flag)
                exact += int(exact_flag)
                if first_record is None:
                    first_record = record
                if first_rescue is None and int(record["n2"]) == 0:
                    first_rescue = record
        actual_hash = output_hash.hexdigest().upper()
        require(actual_hash == summary["result_sha256"], f"result hash mismatch: {key} {start}")
        require(records == int(summary["records"]), f"record count mismatch: {key} {start}")
        require(range_improved == int(summary["improved"]), f"improvement count mismatch: {key} {start}")
        require(range_exact == int(summary["exact"]), f"exact count mismatch: {key} {start}")
        summaries.append({"start": start, "end": end, "records": records, "sha256": actual_hash})
    require(expected_local == int(entry["evaluated"]) == int(entry["valid_frontier"]), f"context cardinality mismatch: {key}")
    require(improved == int(entry["improved_vs_V"]), f"context improvement mismatch: {key}")
    require(exact == int(entry["exact_target_distinct"]) == 0, f"unexpected exact record: {key}")
    context = prepare_context(key, alg)
    for record, reason in ((first_record, "first"), (first_rescue, "first_n2_zero")):
        if record is not None:
            sample = reconstruct_sample(context, record, alg)
            require(sample["matches_receipt"], f"independent full-replay sample mismatch: {key} {reason}")
            sample["reason"] = reason
            samples.append(sample)
    return ({"context": [key[0], key[1]], "evaluated": expected_local, "improved_vs_V": improved, "exact": exact, "ranges": summaries}, samples)


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "audit script cache exists")
    execution = load_json(FRONT2 / "execution.json")
    contract = load_json(FRONT2 / "CONTRACT.json")
    require(execution["status"] == "ALG3_FRONT2_COMPLETE_NO_EXACT", "FRONT2 is not complete-no-exact")
    require(execution["full_readout_audit_passed"] is True, "FRONT2 full replay audit did not pass")
    for binding in contract["parent_bindings"]:
        path = REPO / binding["path"]
        require(path.exists(), f"missing bound parent: {binding['label']}")
        require(path.stat().st_size == int(binding["bytes"]), f"bound size drift: {binding['label']}")
        require(digest(path) == binding["sha256"], f"bound hash drift: {binding['label']}")
    unexpected = audit_write_surface()
    require(not unexpected, f"unexpected FRONT2 files: {unexpected}")
    alg = load_alg1()
    context_reports = []
    samples = []
    for key in CONTEXTS:
        report, context_samples = audit_context(key, execution, alg)
        context_reports.append(report)
        samples.extend(context_samples)
    totals = {
        "contexts": len(context_reports),
        "evaluated": sum(item["evaluated"] for item in context_reports),
        "improved_vs_V": sum(item["improved_vs_V"] for item in context_reports),
        "exact_target_distinct": sum(item["exact"] for item in context_reports),
        "range_files": sum(len(item["ranges"]) for item in context_reports),
    }
    require(totals["evaluated"] == int(execution["counts"]["evaluated"]), "aggregate evaluated mismatch")
    require(totals["improved_vs_V"] == int(execution["counts"]["improved_vs_V"]), "aggregate improvement mismatch")
    require(totals["exact_target_distinct"] == 0 == int(execution["counts"]["exact_target_distinct"]), "aggregate exact mismatch")
    require(len(samples) >= 8, "independent sample coverage too small")
    result = {
        "identity": ROOT.name,
        "protocol": "Q10-ALG3-FRONT2-AUDIT",
        "audited_identity": FRONT2.name,
        "status": "FRONT2_AUDIT_COMPLETE",
        "engineering_only": True,
        "scientific_promotion": False,
        "parent_bindings_verified": True,
        "write_surface_verified": True,
        "range_hashes_and_counts_verified": True,
        "independent_full_replay_samples_verified": len(samples),
        "totals": totals,
        "contexts": context_reports,
        "samples": samples,
    }
    write_new(ROOT / "execution.json", result)
    write_new(ROOT / "STATUS.json", {"identity": ROOT.name, "status": result["status"], "scientific_promotion": False})
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
