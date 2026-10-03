"""Read-only validator-reuse audit over the sealed MAT1-R1 library."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def write_exclusive(path: Path, text: str) -> None:
    require(not path.exists(), f"VR1 refuses overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"VR1 orphan temporary file: {temporary}")
    temporary.write_text(text, encoding="utf-8", newline="\n")
    temporary.replace(path)


def score_tuple(score: dict) -> tuple:
    return (
        int(score["mismatch_count"]),
        int(score["total_ulp_distance"]),
        float(score["residual_l2"]),
        float(score["maximum_absolute_residual"]),
    )


def component_key(case: str, item: dict) -> str:
    return f"{case}|group={int(item['group'])}|candidate={item['to']}"


def component_summary(case: str, item: dict, source: dict) -> dict:
    return {
        "identity": component_key(case, item),
        "case": case,
        "group": int(item["group"]),
        "candidate_identity": str(item["to"]),
        "domain_index": int(item["domain_index"]),
        "singleton_final_pass": bool(source["final_pass"]),
        "singleton_score": source["score"],
        "singleton_score_tuple": list(score_tuple(source["score"])),
    }


def empty_component(summary: dict) -> dict:
    return {
        **summary,
        "successful_pair_count": 0,
        "distinct_partner_count": 0,
        "distinct_case_count": 0,
        "singleton_invalid_count": 0,
        "singleton_valid_count": 0,
        "best_single_count": 0,
        "tied_best_single_count": 0,
        "invalid_to_valid_participations": 0,
        "both_invalid_to_valid_participations": 0,
        "geometry_classes": {},
        "partners": [],
        "cases": [],
    }


def run() -> None:
    contract = read_json(ROOT / "CONTRACT.json")
    for binding in contract["parent_bindings"]:
        path = REPO / str(binding["path"])
        require(path.exists(), f"VR1 missing parent: {path}")
        require(digest(path) == str(binding["sha256"]).upper(), f"VR1 parent drift: {binding['label']}")

    source_path = REPO / "experiments/drosophila-heresy/q10-gc1-cancel1-mat1-r1-v1/qualification/materialized-pairs.jsonl"
    source_records = [json.loads(line) for line in source_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    require(len(source_records) == 201, f"VR1 source count drift: {len(source_records)}")

    observations = []
    components: dict[str, dict] = {}
    pair_count_by_case = Counter()
    class_counts = Counter()
    for record in source_records:
        case = str(record["case"])
        source = record["source"]
        a = source["a"]
        b = source["b"]
        sa = source["single_a"]
        sb = source["single_b"]
        pair_state = record["states"]["pair_ab"]
        require(bool(pair_state["final_pass"]), "VR1 source pair is not final-valid")

        a_summary = component_summary(case, a, sa)
        b_summary = component_summary(case, b, sb)
        for summary in (a_summary, b_summary):
            components.setdefault(summary["identity"], empty_component(summary))

        a_score = score_tuple(sa["score"])
        b_score = score_tuple(sb["score"])
        if a_score < b_score:
            best = ["A"]
        elif b_score < a_score:
            best = ["B"]
        else:
            best = ["A", "B"]

        a_valid = bool(sa["final_pass"])
        b_valid = bool(sb["final_pass"])
        geometry_class = str(record["component_geometry_class"])
        pair_count_by_case[case] += 1
        class_counts[geometry_class] += 1
        observation = {
            "case": case,
            "pair_domain_index": int(record["pair_domain_index"]),
            "component_a": a_summary,
            "component_b": b_summary,
            "best_single_components": best,
            "pair_final_pass": True,
            "component_geometry_class": geometry_class,
            "invalid_singleton_components": [x for x, ok in (("A", a_valid), ("B", b_valid)) if not ok],
            "both_invalid_to_valid": not a_valid and not b_valid,
            "one_invalid_to_valid": a_valid != b_valid,
        }
        observations.append(observation)

        for label, current, other, valid, other_valid in (
            ("A", a_summary, b_summary, a_valid, b_valid),
            ("B", b_summary, a_summary, b_valid, a_valid),
        ):
            row = components[current["identity"]]
            row["successful_pair_count"] += 1
            row["distinct_partner_count"] = row["distinct_partner_count"]
            row["singleton_invalid_count"] += int(not valid)
            row["singleton_valid_count"] += int(valid)
            row["best_single_count"] += int(label in best and len(best) == 1)
            row["tied_best_single_count"] += int(label in best and len(best) == 2)
            row["invalid_to_valid_participations"] += int(not valid)
            row["both_invalid_to_valid_participations"] += int(not valid and not other_valid)
            row["geometry_classes"][geometry_class] = row["geometry_classes"].get(geometry_class, 0) + 1
            row["partners"].append(other["identity"])
            row["cases"].append(case)

    for row in components.values():
        row["partners"] = sorted(set(row["partners"]))
        row["cases"] = sorted(set(row["cases"]))
        row["distinct_partner_count"] = len(row["partners"])
        row["distinct_case_count"] = len(row["cases"])
        row["geometry_classes"] = dict(sorted(row["geometry_classes"].items()))

    component_rows = [components[key] for key in sorted(components)]
    output = ROOT / "qualification"
    output.mkdir(parents=True, exist_ok=True)
    observations_path = output / "pair-observations.jsonl"
    components_path = output / "component-reuse.jsonl"
    execution_path = output / "execution.json"
    write_exclusive(observations_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in observations))
    write_exclusive(components_path, "".join(json.dumps(row, sort_keys=True) + "\n" for row in component_rows))
    execution = {
        "identity": contract["identity"],
        "protocol": contract["protocol"],
        "scope": "derived_read_only_association_audit",
        "source_records": len(source_records),
        "component_identities": len(component_rows),
        "pair_count_by_case": dict(sorted(pair_count_by_case.items())),
        "geometry_class_counts": dict(sorted(class_counts.items())),
        "observations_sha256": digest(observations_path),
        "components_sha256": digest(components_path),
        "checks_passed": True,
        "causal_allocation": False,
    }
    write_exclusive(execution_path, json.dumps(execution, indent=2, sort_keys=True) + "\n")
    print(json.dumps(execution, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    run()
