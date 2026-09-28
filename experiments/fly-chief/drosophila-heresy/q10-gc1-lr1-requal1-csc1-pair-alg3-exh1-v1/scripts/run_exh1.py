from __future__ import annotations

import concurrent.futures
import hashlib
import importlib.util
import json
import math
import os
import struct
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
PROTOCOL = "Q10-ALG3-EXH1"
IDENTITY = ROOT.name
ALG1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-alg1-v2"
ALG1_SCRIPT = ALG1 / "scripts/run_alg1.py"
CENS0 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-cens0-v1"
ALG3_SAMPLE = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-v1"
ALG3_DOMAIN3 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-alg3-domain-v1"
EXH1_PAIR = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-pair-exh1-v1"
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
BOUNDARY_GUARD = 1.0e-12
RANGE_SIZE = 1_000_000
AUDIT_SAMPLES_PER_CONTEXT = 256
WORKERS = 4
CENS0_EXECUTION = json.loads((CENS0 / "execution.json").read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def digest_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest().upper()


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def write_new(path: Path, value: Any) -> None:
    require(not path.exists(), f"refusing to overwrite sealed output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def load_alg1() -> Any:
    spec = importlib.util.spec_from_file_location("q10_alg3_exh1_alg1_runtime", ALG1_SCRIPT)
    require(spec is not None and spec.loader is not None, "ALG1 runtime load failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    require(module.IDENTITY == "q10-gc1-lr1-requal1-csc1-alg1-v2", "wrong ALG1 runtime")
    return module


def bind(label: str, path: Path) -> dict[str, Any]:
    require(path.is_file(), f"missing EXH1 input: {path}")
    return {"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path)}


def action_key(row: dict[str, Any]) -> str:
    return f"{int(row['group'])}:{str(row['to'])}"


def failure_mask(geometry: dict[str, float], gates: dict[str, float]) -> int:
    mask = 0
    if float(geometry["axis_normalized_error"]) > float(gates["axis_normalized_abs"]):
        mask |= 1
    if float(geometry["norm_normalized_error"]) > float(gates["norm_normalized_abs"]):
        mask |= 2
    if float(geometry["cue_linear_normalized_error"]) > float(gates["cue_linear_normalized_abs"]):
        mask |= 4
    return mask


def finite_geometry(geometry: dict[str, float]) -> None:
    require(all(math.isfinite(float(value)) for value in geometry.values()), "nonfinite fast geometry")


def margins(geometry: dict[str, float], gates: dict[str, float]) -> tuple[float, float, float]:
    return (
        float(gates["axis_normalized_abs"]) - float(geometry["axis_normalized_error"]),
        float(gates["norm_normalized_abs"]) - float(geometry["norm_normalized_error"]),
        float(gates["cue_linear_normalized_abs"]) - float(geometry["cue_linear_normalized_error"]),
    )


def near_boundary(geometry: dict[str, float], gates: dict[str, float]) -> bool:
    return any(abs(value) <= BOUNDARY_GUARD for value in margins(geometry, gates))


def classification_bytes(global_rank: int, a: int, b: int, c: int, valid: bool, n1: int, n2: int, mask: int) -> bytes:
    return struct.pack("<QIIIBBBH", global_rank, a, b, c, int(valid), n1, n2, mask)


def full_geometry(alg: Any, pf: Any, state: Any, s: dict[str, Any], actions: list[dict[str, Any]], indices: tuple[int, int, int], contract: dict[str, Any]) -> tuple[dict[str, float], bool]:
    mapping: list[list[int]] = []
    for index in indices:
        mapping.extend(actions[index]["mapping"])
    mapping.sort(key=lambda item: int(item[0]))
    bits = alg.apply_mapping(pf, state, tuple(s["bits"]), mapping)
    result = alg.geometry_only(pf, state, bits, contract)
    return result["geometry"], bool(result["final_geometry_pass"])


def prepare_context(key: tuple[str, int], alg: Any) -> dict[str, Any]:
    pf, builder = alg.load_modules()
    _, data = builder.fresh_lineage(CLOSURE_REPO, pf)
    state = next(item for item in data["states"] if item.key == key)
    contract = json.loads(PF5_CONTRACT.read_text(encoding="utf-8"))
    reference = json.loads((REF / "execution.json").read_text(encoding="utf-8"))
    ref_result = next(item for item in reference["results"] if item["endpoint"] == key[0] and int(item["set_index"]) == key[1])
    s = alg.verify_reference(pf, state, ref_result, contract)
    descriptor = json.loads((ALG1 / "descriptors" / f"{slug(key)}.json").read_text(encoding="utf-8"))
    raw_actions = sorted(descriptor["actions"], key=lambda row: (int(row["group"]), str(row["to"])))
    require(len(raw_actions) == len(set(action_key(row) for row in raw_actions)), f"duplicate action identity: {key}")

    s_weights = tuple(pf.from_bits(int(raw)) for raw in s["bits"])
    s_displacement = tuple(value - initial for value, initial in zip(s_weights, state.base_weights))
    target_displacement = tuple(value - initial for value, initial in zip(state.target_weights, state.base_weights))
    rows_by_coordinate: dict[int, list[int]] = defaultdict(list)
    for row_index, row in enumerate(state.rows):
        for coordinate in row:
            rows_by_coordinate[int(coordinate)].append(row_index)
    rows_by_coordinate = {coordinate: sorted(rows) for coordinate, rows in rows_by_coordinate.items()}
    s_drive = tuple(math.fsum(s_displacement[index] for index in row) for row in state.rows)
    target_drive = tuple(math.fsum(target_displacement[index] for index in row) for row in state.rows)
    residual = tuple(actual - target for actual, target in zip(s_drive, target_drive))

    actions: list[dict[str, Any]] = []
    by_key: dict[str, int] = {}
    by_group: dict[int, list[int]] = defaultdict(list)
    for index, raw in enumerate(raw_actions):
        mapping = sorted([[int(coordinate), int(choice)] for coordinate, choice in raw["canonical_mapping"]], key=lambda item: item[0])
        sparse: dict[int, float] = {}
        for coordinate, _choice in mapping:
            endpoint = pf.from_bits(int(raw["weight_bits"][coordinate]))
            delta = endpoint - s_weights[coordinate]
            if delta != 0.0:
                sparse[coordinate] = delta
        drive_values: dict[int, list[float]] = defaultdict(list)
        for coordinate, delta in sparse.items():
            for row_index in rows_by_coordinate.get(coordinate, []):
                drive_values[row_index].append(delta)
        drive = {row_index: math.fsum(values) for row_index, values in sorted(drive_values.items())}
        drive_norm_sq = math.fsum(value * value for value in drive.values())
        r_dot = math.fsum(residual[row_index] * value for row_index, value in drive.items())
        item = {
            "ordinal": index,
            "key": action_key(raw),
            "group": int(raw["group"]),
            "to": str(raw["to"]),
            "mapping": mapping,
            "sparse": sparse,
            "drive": drive,
            "dependency_rows": tuple(sorted(drive)),
            "axis_delta": math.fsum(delta * state.axis[coordinate] for coordinate, delta in sparse.items()),
            "norm_delta": math.fsum(2.0 * s_displacement[coordinate] * delta + delta * delta for coordinate, delta in sparse.items()),
            "action_q": 2.0 * r_dot + drive_norm_sq,
            "r_dot": r_dot,
            "drive_norm_sq": drive_norm_sq,
            "final_geometry_pass": bool(raw["final_geometry_pass"]),
        }
        actions.append(item)
        by_key[item["key"]] = index
        by_group[item["group"]].append(index)
    groups = sorted(by_group)
    require(all(len(by_group[group]) == 8 for group in groups), f"group action arity drift: {key}")

    pair_valid: set[tuple[int, int]] = set()
    frontier = EXH1_PAIR / "valid-frontier" / f"{slug(key)}.jsonl"
    for line in frontier.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        row = json.loads(line)
        left = by_key[f"{int(row['a']['group'])}:{str(row['a']['to'])}"]
        right = by_key[f"{int(row['b']['group'])}:{str(row['b']['to'])}"]
        pair_valid.add(tuple(sorted((left, right))))
    exh_execution = json.loads((EXH1_PAIR / "execution.json").read_text(encoding="utf-8"))
    expected_pair_count = next(item["valid_pairs"] for item in exh_execution["contexts"] if item["context"] == [key[0], key[1]])
    require(len(pair_valid) == int(expected_pair_count), f"pair frontier cardinality drift: {key}")

    baseline_norm_sq = math.fsum(value * value for value in s_displacement)
    baseline_linear_sq = math.fsum(value * value for value in residual)
    pair_dot = [[0.0] * len(actions) for _ in actions]
    action_groups = {index: item["group"] for index, item in enumerate(actions)}
    for left in range(len(actions)):
        for right in range(left + 1, len(actions)):
            if action_groups[left] == action_groups[right]:
                continue
            a_drive, b_drive = actions[left]["drive"], actions[right]["drive"]
            if len(a_drive) > len(b_drive):
                a_drive, b_drive = b_drive, a_drive
            dot = math.fsum(value * b_drive.get(row_index, 0.0) for row_index, value in a_drive.items())
            pair_dot[left][right] = dot
            pair_dot[right][left] = dot

    sample_domain = {
        int(json.loads(line)["triple_index"]): json.loads(line)
        for line in (ALG3_DOMAIN3 / "shards" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    }
    sample_results = {
        int(json.loads(line)["triple_index"]): json.loads(line)
        for line in (ALG3_SAMPLE / "results" / f"{slug(key)}.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    }
    require(set(sample_domain) == set(sample_results), f"ALG3 sample identity drift: {key}")

    return {
        "pf": pf,
        "state": state,
        "contract": contract,
        "s": s,
        "actions": actions,
        "by_key": by_key,
        "by_group": {group: tuple(values) for group, values in by_group.items()},
        "groups": tuple(groups),
        "pair_valid": pair_valid,
        "pair_dot": pair_dot,
        "baseline_norm_sq": baseline_norm_sq,
        "baseline_linear_sq": baseline_linear_sq,
        "residual": residual,
        "target_drive_norm": math.sqrt(math.fsum(value * value for value in target_drive)),
        "sample_domain": sample_domain,
        "sample_results": sample_results,
    }


def fast_geometry(context: dict[str, Any], indices: tuple[int, int, int]) -> dict[str, float]:
    actions = context["actions"]
    a, b, c = (actions[index] for index in indices)
    s_geometry = context["s"]["geometry"]
    final_axis = s_geometry["final_axis"] + a["axis_delta"] + b["axis_delta"] + c["axis_delta"]
    norm_sq = context["baseline_norm_sq"] + a["norm_delta"] + b["norm_delta"] + c["norm_delta"]
    require(norm_sq >= 0.0, "negative fast norm square")
    final_norm = math.sqrt(norm_sq)
    pair_dot = context["pair_dot"]
    cue_sq = context["baseline_linear_sq"] + a["action_q"] + b["action_q"] + c["action_q"]
    cue_sq += 2.0 * (pair_dot[indices[0]][indices[1]] + pair_dot[indices[0]][indices[2]] + pair_dot[indices[1]][indices[2]])
    require(cue_sq >= 0.0, "negative fast cue square")
    cue_error = math.sqrt(cue_sq)
    target_axis = float(s_geometry["target_axis"])
    target_norm = float(s_geometry["target_norm"])
    cue_scale = max(context["target_drive_norm"], 1.0e-12)
    geometry = {
        "axis_absolute_error": abs(final_axis - target_axis),
        "axis_normalized_error": abs(final_axis - target_axis) / max(abs(target_axis), 1.0e-12),
        "norm_absolute_error": abs(final_norm - target_norm),
        "norm_normalized_error": abs(final_norm - target_norm) / max(target_norm, 1.0e-12),
        "cue_linear_absolute_error": cue_error,
        "cue_linear_normalized_error": cue_error / cue_scale,
        "final_axis": final_axis,
        "target_axis": target_axis,
        "final_norm": final_norm,
        "target_norm": target_norm,
    }
    finite_geometry(geometry)
    return geometry


def validate_sample(context: dict[str, Any], alg: Any) -> dict[str, Any]:
    audits = []
    max_error = 0.0
    fallbacks = 0
    for triple_index in sorted(context["sample_domain"]):
        row = context["sample_domain"][triple_index]
        result = context["sample_results"][triple_index]
        indices = tuple(context["by_key"][str(row[name])] for name in ("a", "b", "c"))
        predicted = fast_geometry(context, indices)
        exact, exact_valid = full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], indices, context["contract"])
        error = max(abs(float(predicted[name]) - float(exact[name])) for name in exact)
        max_error = max(max_error, error)
        valid_predicted = bool(context["pf"].final_geometry_pass(predicted, context["contract"]))
        require(valid_predicted == exact_valid, f"sample fast/full validity disagreement: {row['triple_index']}")
        require(exact_valid == bool(result["exact_final_geometry_pass"]), f"sample historical validity drift: {row['triple_index']}")
        audits.append({"triple_index": triple_index, "a": row["a"], "b": row["b"], "c": row["c"], "geometry_error": error, "valid": exact_valid})
    return {"records": len(audits), "max_geometry_error": max_error, "validity_mismatches": 0, "audits": audits, "boundary_guard": BOUNDARY_GUARD, "authoritative_full_replay": True, "fallbacks": fallbacks}


def rescue_class(n2: int) -> str:
    return {3: "PAIRWISE_VALID_TRIANGLE", 2: "ONE_PAIR_RESCUED", 1: "TWO_PAIR_RESCUED", 0: "PURE_HIGHER_ORDER_RESCUE"}[n2]


def run_context(key: tuple[str, int], context_index: int, context_count: int) -> dict[str, Any]:
    alg = load_alg1()
    context = prepare_context(key, alg)
    sample = validate_sample(context, alg)
    gates = context["contract"]["geometry"]["final_da2_gates"]
    groups = context["groups"]
    action_lists = context["by_group"]
    local_total = math.comb(len(groups), 3) * 512
    require(local_total == context_count, f"context triple cardinality drift: {key}")
    global_offset = sum(int(item["structural_triples"]) for item in CENS0_EXECUTION["contexts"][:context_index])
    context_root = ROOT / "valid-frontier" / slug(key)
    summary_root = ROOT / "range-summaries" / slug(key)
    context_root.mkdir(parents=True, exist_ok=True)
    summary_root.mkdir(parents=True, exist_ok=True)
    ranges: list[dict[str, Any]] = []
    failure_hist = Counter()
    valid_n1 = Counter()
    valid_n2 = Counter()
    audit_by_class: dict[str, dict[str, Any]] = {}
    audit_fixed: list[dict[str, Any]] = []
    closest: list[tuple[float, int, tuple[int, int, int]]] = []
    fallback_count = 0
    deterministic_stride = max(1, local_total // AUDIT_SAMPLES_PER_CONTEXT)
    local_rank = 0
    range_start = 0
    range_end = min(RANGE_SIZE, local_total)

    def open_range(start: int, end: int) -> dict[str, Any]:
        path = context_root / f"{start:09d}-{end:09d}.jsonl"
        summary_path = summary_root / f"{start:09d}-{end:09d}.json"
        require(not path.exists() and not summary_path.exists(), f"range output already exists: {path}")
        return {"start": start, "end": end, "path": path, "summary_path": summary_path, "stream": path.open("xb"), "identity_hash": hashlib.sha256(), "valid_payload_hash": hashlib.sha256(), "evaluated": 0, "valid": 0, "fallbacks": 0, "failure": Counter(), "first_identity": None, "last_identity": None}

    def finish_range(current: dict[str, Any]) -> None:
        current["stream"].close()
        require(current["evaluated"] == current["end"] - current["start"], f"range evaluation drift: {key} {current['start']}-{current['end']}")
        summary = {"context": [key[0], key[1]], "start": current["start"], "end": current["end"], "evaluated": current["evaluated"], "valid": current["valid"], "first_identity": current["first_identity"], "last_identity": current["last_identity"], "classification_sha256": current["identity_hash"].hexdigest().upper(), "valid_payload_sha256": current["valid_payload_hash"].hexdigest().upper(), "failure_histogram": dict(sorted(current["failure"].items())), "fallbacks": current["fallbacks"], "valid_shard": current["path"].relative_to(REPO).as_posix()}
        write_new(current["summary_path"], summary)
        ranges.append(summary)
        print(json.dumps({"context": slug(key), "range": [current["start"], current["end"]], "valid": current["valid"], "fallbacks": current["fallbacks"]}, sort_keys=True), flush=True)

    current = open_range(range_start, range_end)
    total_valid = 0
    for gi in range(len(groups) - 2):
        for gj in range(gi + 1, len(groups) - 1):
            for gk in range(gj + 1, len(groups)):
                for ia in action_lists[groups[gi]]:
                    for ib in action_lists[groups[gj]]:
                        for ic in action_lists[groups[gk]]:
                            require(local_rank < local_total, f"enumeration overflow: {key}")
                            if local_rank >= current["end"]:
                                finish_range(current)
                                range_start = current["end"]
                                range_end = min(range_start + RANGE_SIZE, local_total)
                                current = open_range(range_start, range_end)
                            indices = (ia, ib, ic)
                            identity = [context["actions"][item]["key"] for item in indices]
                            if current["first_identity"] is None:
                                current["first_identity"] = identity
                            current["last_identity"] = identity
                            predicted = fast_geometry(context, indices)
                            use_full = near_boundary(predicted, gates)
                            geometry = predicted
                            valid = bool(context["pf"].final_geometry_pass(predicted, context["contract"]))
                            if use_full:
                                geometry, valid = full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], indices, context["contract"])
                                fallback_count += 1
                                current["fallbacks"] += 1
                            if local_rank % deterministic_stride == 0:
                                exact_geometry, exact_valid = full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], indices, context["contract"])
                                error = max(abs(float(predicted[name]) - float(exact_geometry[name])) for name in exact_geometry)
                                require(valid == exact_valid, f"order-3 audit validity disagreement: {key} {local_rank}")
                                require(error <= 1.0e-10, f"order-3 audit geometry disagreement: {key} {local_rank} {error}")
                                audit_fixed.append({"local_rank": local_rank, "actions": identity, "valid": exact_valid, "geometry_error": error})
                            margin_distance = min(abs(value) for value in margins(predicted, gates))
                            closest.append((margin_distance, local_rank, indices))
                            if len(closest) > 32:
                                closest.sort(key=lambda item: item[0])
                                del closest[32:]
                            mask = failure_mask(geometry, gates)
                            if valid:
                                n1 = sum(int(context["actions"][item]["final_geometry_pass"]) for item in indices)
                                pair_bits = (tuple(sorted((ia, ib))) in context["pair_valid"], tuple(sorted((ia, ic))) in context["pair_valid"], tuple(sorted((ib, ic))) in context["pair_valid"])
                                n2 = sum(int(value) for value in pair_bits)
                                dependency_rows = sorted(set().union(*(context["actions"][item]["dependency_rows"] for item in indices)))
                                record = {"global_rank": global_offset + local_rank, "local_rank": local_rank, "context": [key[0], key[1]], "action_ordinals": list(indices), "actions": identity, "geometry": geometry, "gate_margins": list(margins(geometry, gates)), "n1": n1, "n2": n2, "pair_valid_bits": list(pair_bits), "rescue_class": rescue_class(n2), "dependency_rows": dependency_rows, "fallback_authoritative": use_full}
                                payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                                current["stream"].write(payload)
                                current["valid_payload_hash"].update(payload)
                                current["valid"] += 1
                                total_valid += 1
                                valid_n1[n1] += 1
                                valid_n2[n2] += 1
                                audit_by_class.setdefault(rescue_class(n2), {"local_rank": local_rank, "actions": identity, "n1": n1, "n2": n2, "geometry": geometry})
                                n1_hash, n2_hash = n1, n2
                            else:
                                n1_hash, n2_hash = 255, 255
                            label = "VALID" if valid else str(mask)
                            current["failure"][label] += 1
                            failure_hist[label] += 1
                            current["identity_hash"].update(classification_bytes(global_offset + local_rank, ia, ib, ic, valid, n1_hash, n2_hash, mask))
                            current["evaluated"] += 1
                            local_rank += 1
    finish_range(current)
    for _distance, audit_rank, audit_indices in sorted(closest, key=lambda item: item[0])[:16]:
        exact_geometry, exact_valid = full_geometry(alg, context["pf"], context["state"], context["s"], context["actions"], audit_indices, context["contract"])
        predicted = fast_geometry(context, audit_indices)
        error = max(abs(float(predicted[name]) - float(exact_geometry[name])) for name in exact_geometry)
        require(bool(context["pf"].final_geometry_pass(predicted, context["contract"])) == exact_valid, f"closest-gate audit validity disagreement: {key} {audit_rank}")
        require(error <= 1.0e-10, f"closest-gate audit geometry disagreement: {key} {audit_rank} {error}")
    require(local_rank == local_total, f"context coverage drift: {key} {local_rank} != {local_total}")
    require(sum(int(item["evaluated"]) for item in ranges) == local_total, f"range sum drift: {key}")
    return {"context": [key[0], key[1]], "structural_triples": local_total, "valid_triples": total_valid, "failure_histogram": dict(sorted(failure_hist.items())), "valid_n1": dict(sorted(valid_n1.items())), "valid_n2": dict(sorted(valid_n2.items())), "fallbacks": fallback_count, "sample_validation": sample, "audit_fixed": audit_fixed, "audit_closest_count": min(16, len(closest)), "rescue_examples": audit_by_class, "ranges": ranges}


def main() -> int:
    require(os.environ.get("PYTHONDONTWRITEBYTECODE") == "1", "PYTHONDONTWRITEBYTECODE must equal 1")
    require(sys.dont_write_bytecode, "bytecode generation is enabled")
    require(not (ROOT / "scripts" / "__pycache__").exists(), "unexpected EXH1 script cache")
    require(not (ROOT / "execution.json").exists(), "EXH1 execution already exists")
    inputs: list[tuple[str, Path]] = [("exh1_plan", ROOT / "PLAN.md"), ("exh1_runner", Path(__file__)), ("cens0_execution", CENS0 / "execution.json"), ("cens0_contract", CENS0 / "CONTRACT.json"), ("alg3_sample_execution", ALG3_SAMPLE / "execution.json"), ("alg3_sample_contract", ALG3_SAMPLE / "CONTRACT.json"), ("alg1_execution", ALG1 / "execution.json"), ("exh1_pair_execution", EXH1_PAIR / "execution.json"), ("exh1_pair_contract", EXH1_PAIR / "CONTRACT.json"), ("pf5_contract", PF5_CONTRACT), ("reference_execution", REF / "execution.json")]
    for key in CONTEXTS:
        name = slug(key)
        inputs.extend([(f"alg1_descriptor:{name}", ALG1 / "descriptors" / f"{name}.json"), (f"alg3_domain:{name}", ALG3_DOMAIN3 / "shards" / f"{name}.jsonl"), (f"alg3_result:{name}", ALG3_SAMPLE / "results" / f"{name}.jsonl"), (f"exh1_pair_frontier:{name}", EXH1_PAIR / "valid-frontier" / f"{name}.jsonl")])
    bindings = [bind(label, path) for label, path in inputs]
    counts = [int(item["structural_triples"]) for item in CENS0_EXECUTION["contexts"]]
    contract = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "SEALED_PREMEASUREMENT", "parent_bindings": bindings, "structural_triples": sum(counts), "per_context_triples": counts, "enumeration_uses_pair_validity_as_filter": False, "pair_validity_role": "post hoc n2 label for geometry-valid triples only", "boundary_guard_normalized": BOUNDARY_GUARD, "range_size": RANGE_SIZE, "authoritative_boundary_fallback": True, "audit_samples_per_context": AUDIT_SAMPLES_PER_CONTEXT, "readout_executed": False, "scientific_promotion": False, "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "valid-frontier/*/*.jsonl", "range-summaries/*/*.json"]}
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": "PREEXECUTION_SEALED", "contract_sha256": digest(ROOT / "CONTRACT.json"), "structural_triples": sum(counts), "pair_validity_pruning": False, "readout_executed": False})
    results: list[dict[str, Any]] = []
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=WORKERS) as pool:
            futures = {pool.submit(run_context, key, index, counts[index]): key for index, key in enumerate(CONTEXTS)}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                results.append(result)
                print(json.dumps({"context": result["context"], "structural_triples": result["structural_triples"], "valid_triples": result["valid_triples"], "fallbacks": result["fallbacks"]}, sort_keys=True), flush=True)
        results.sort(key=lambda item: CONTEXTS.index(tuple(item["context"])))
        require(len(results) == len(CONTEXTS), "context result cardinality drift")
        for index, result in enumerate(results):
            require(int(result["structural_triples"]) == counts[index], f"context count drift: {result['context']}")
            ranges = sorted(result["ranges"], key=lambda item: int(item["start"]))
            cursor = 0
            for item in ranges:
                require(int(item["start"]) == cursor, f"noncontiguous range: {result['context']} {item['start']}")
                require(int(item["end"]) > int(item["start"]) and int(item["evaluated"]) == int(item["end"]) - int(item["start"]), f"bad range accounting: {result['context']}")
                cursor = int(item["end"])
            require(cursor == counts[index], f"range coverage incomplete: {result['context']}")
        execution = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "ALG3_EXH1_COMPLETE", "engineering_only": True, "scientific_promotion": False, "readout_executed": False, "enumeration_uses_pair_validity_as_filter": False, "counts": {"contexts": len(results), "structural_triples": sum(item["structural_triples"] for item in results), "valid_triples": sum(item["valid_triples"] for item in results), "fallbacks": sum(item["fallbacks"] for item in results)}, "contexts": results, "contract_sha256": digest(ROOT / "CONTRACT.json"), "conclusion": "Complete order-3 structural compatibility domain evaluated for geometry validity; order-2 validity was used only for post hoc rescue labels."}
        require(execution["counts"]["structural_triples"] == sum(counts), "global triple cardinality drift")
        write_new(ROOT / "execution.json", execution)
        write_new(ROOT / "STATUS.json", {"protocol": PROTOCOL, "identity": IDENTITY, "status": execution["status"], "engineering_only": True, "scientific_promotion": False, "execution_sha256": digest(ROOT / "execution.json")})
        print(json.dumps(execution, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        blocked = {"protocol": PROTOCOL, "identity": IDENTITY, "status": "BLOCKED_ALG3_EXH1", "engineering_only": True, "scientific_promotion": False, "readout_executed": False, "error_type": type(exc).__name__, "error": str(exc), "completed_contexts": results}
        write_new(ROOT / "execution.json", blocked)
        print(json.dumps(blocked, indent=2, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
