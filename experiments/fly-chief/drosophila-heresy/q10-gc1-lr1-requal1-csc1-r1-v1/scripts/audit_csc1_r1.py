from __future__ import annotations

import hashlib
import json
import math
import mmap
import struct
import statistics
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-R1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-r1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
VMAT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-v6"
FINALIZER = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-finalizer-v1"
PAIR_DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
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


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"count": 0, "median": None, "p05": None, "p95": None, "mean": None, "min": None, "max": None}
    ordered = sorted(values)
    return {"count": len(values), "median": statistics.median(ordered), "p05": ordered[max(0, math.ceil(0.05 * len(ordered)) - 1)], "p95": ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)], "mean": statistics.fmean(values), "min": ordered[0], "max": ordered[-1]}


class Sidecars:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = {}
        self.maps = {}

    def __enter__(self) -> "Sidecars":
        for name in ("constraint-gate.f64bin", "constraint-raw.f64bin", "linear-drive.f64bin", "linear-residual.f64bin"):
            handle = (self.root / name).open("rb")
            self.files[name] = handle
            self.maps[name] = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) if handle.seek(0, 2) else None
            handle.seek(0)
        return self

    def __exit__(self, *_: Any) -> None:
        for mapping in self.maps.values():
            if mapping is not None:
                mapping.close()
        for handle in self.files.values():
            handle.close()

    def f64(self, name: str, offset: int, length: int) -> tuple[float, ...]:
        mapping = self.maps[name]
        require(mapping is not None, f"empty nonempty sidecar requested: {name}")
        raw = mapping[offset:offset + length]
        require(len(raw) == length and length % 8 == 0, f"invalid sidecar slice: {name}")
        return struct.unpack("<" + "d" * (length // 8), raw)


def project_gate(c: tuple[float, ...]) -> tuple[float, ...]:
    axis = max(-1.0, min(1.0, c[0]))
    norm = max(-1.0, min(1.0, c[1]))
    linear = tuple(c[2:])
    radius = math.sqrt(math.fsum(value * value for value in linear))
    if radius > 1.0:
        linear = tuple(value / radius for value in linear)
    return (axis, norm, *linear)


def deficit(c: tuple[float, ...]) -> tuple[float, ...]:
    projected = project_gate(c)
    return tuple(p - value for p, value in zip(projected, c))


def distance_to_gate(c: tuple[float, ...]) -> float:
    d = deficit(c)
    return math.sqrt(math.fsum(value * value for value in d))


def dot(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    return math.fsum(a * b for a, b in zip(left, right))


def norm(value: tuple[float, ...]) -> float:
    return math.sqrt(math.fsum(item * item for item in value))


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    denom = norm(left) * norm(right)
    return None if denom == 0.0 else dot(left, right) / denom


def failed_faces(c: tuple[float, ...]) -> tuple[str, ...]:
    faces = []
    if abs(c[0]) > 1.0:
        faces.append("AXIS")
    if abs(c[1]) > 1.0:
        faces.append("NORM")
    if norm(tuple(c[2:])) > 1.0:
        faces.append("LINEAR_DRIVE")
    return tuple(faces)


def read_state(index: dict[str, Any], side: Sidecars) -> tuple[float, ...]:
    ref = index["state_refs"] if "state_refs" in index else index
    entry = ref
    offset = int(entry["offset_bytes"]["constraint-gate"])
    length = int(entry["byte_lengths"]["constraint-gate"])
    return side.f64("constraint-gate.f64bin", offset, length)


def main() -> int:
    report: dict[str, Any] = {"protocol": PROTOCOL, "identity": IDENTITY, "scientific_promotion": False, "replay_performed": False}
    try:
        vm_contract = load(VMAT / "CONTRACT.json")
        vm_execution = load(VMAT / "execution.json")
        finalizer = load(FINALIZER / "REPORT.json")
        require(vm_execution["status"] == "CSC1_VMAT1_COMPLETE", "VMAT1 incomplete")
        require(finalizer["status"] == "VMAT1_FINALIZER_PASS", "VMAT1 finalizer did not pass")
        require(finalizer["parent_vmat_identity"] == vm_contract["identity"], "finalizer parent identity drift")
        tolerance = load(VMAT / "tolerance-schema.json")["tolerance"]
        records_total = 0
        ordered_rows = 0
        pair_counts = {"valid_valid": 0, "valid_invalid": 0, "invalid_valid": 0, "invalid_invalid": 0}
        useful_counts = {"better_than_V": 0, "worse_than_V": 0, "other": 0}
        class_counts: dict[str, int] = {}
        context_reports: dict[str, Any] = {}
        alignment_success: list[float] = []
        alignment_worse: list[float] = []
        deficit_reduction_success: list[float] = []
        deficit_reduction_worse: list[float] = []
        additive_axis = []
        additive_linear = []
        additive_norm = []
        detailed = []
        for key in PAIR_KEYS:
            context_slug = slug(key)
            records = [json.loads(line) for line in (VMAT / "shards" / f"{context_slug}.jsonl").read_text(encoding="utf-8").splitlines() if line]
            ordered_domain = load(PAIR_DOMAIN / "shards" / f"{context_slug}.jsonl")
            require(len(records) == len(ordered_domain), f"record/domain count drift: {key}")
            index = {row["state_ref"]: row for row in (json.loads(line) for line in (VMAT / "sidecars" / context_slug / "state-index.jsonl").read_text(encoding="utf-8").splitlines() if line)}
            with Sidecars(VMAT / "sidecars" / context_slug) as side:
                context_align_success = []
                context_align_worse = []
                context_pairs = {"better_than_V": 0, "worse_than_V": 0}
                for record in records:
                    refs = record["state_refs"]
                    c = {role: read_state(index[refs[role]], side) for role in ("S", "A", "B", "AB")}
                    valid = {role: bool(record["final_geometry_pass"][role]) for role in ("S", "A", "B", "AB")}
                    kind = ("valid" if valid["A"] else "invalid") + "_" + ("valid" if valid["B"] else "invalid")
                    pair_counts[kind] += 1
                    outcome = record["outcome"]
                    if outcome == "VALID_ADVANTAGE_PRESERVED":
                        useful_counts["better_than_V"] += 1
                        context_pairs["better_than_V"] += 1
                    elif valid["AB"]:
                        useful_counts["worse_than_V"] += 1
                        context_pairs["worse_than_V"] += 1
                    else:
                        useful_counts["other"] += 1
                    faces_a = set(failed_faces(c["A"]))
                    faces_b = set(failed_faces(c["B"]))
                    if valid["A"] and valid["B"]:
                        morphology = "VALID_VALID_COMPOSITION"
                    elif not valid["A"] and not valid["B"] and valid["AB"]:
                        if faces_a & faces_b:
                            morphology = "INVALID_INVALID_SHARED_FACE_REPAIR"
                        elif faces_a and faces_b and not (faces_a & faces_b):
                            morphology = "INVALID_INVALID_CROSS_FACE_REPAIR"
                        else:
                            morphology = "INVALID_INVALID_MULTI_AXIS_REPAIR"
                    elif not valid["A"] and valid["B"] and valid["AB"]:
                        morphology = "INVALID_VALID_A_REPAIR"
                    elif valid["A"] and not valid["B"] and valid["AB"]:
                        morphology = "VALID_INVALID_B_REPAIR"
                    else:
                        morphology = "OTHER"
                    class_counts[morphology] = class_counts.get(morphology, 0) + 1
                    delta_a = tuple(x - y for x, y in zip(c["A"], c["S"]))
                    delta_b = tuple(x - y for x, y in zip(c["B"], c["S"]))
                    interaction = tuple(x - y - z + q for x, y, z, q in zip(c["AB"], c["A"], c["B"], c["S"]))
                    additive_axis.append(abs(interaction[0]))
                    additive_norm.append(abs(interaction[1]))
                    additive_linear.append(norm(tuple(interaction[2:])))
                    if not valid["A"]:
                        deficit_a = deficit(c["A"])
                        d_a = norm(deficit_a)
                        d_ab = distance_to_gate(c["AB"])
                        align = cosine(delta_b, deficit_a)
                        reduction = d_a - d_ab
                        if align is not None:
                            (alignment_success if outcome == "VALID_ADVANTAGE_PRESERVED" else alignment_worse).append(align)
                            (context_align_success if outcome == "VALID_ADVANTAGE_PRESERVED" else context_align_worse).append(align)
                        (deficit_reduction_success if outcome == "VALID_ADVANTAGE_PRESERVED" else deficit_reduction_worse).append(reduction)
                        if len(detailed) < 32:
                            detailed.append({"context": [key[0], key[1]], "pair_index": record["pair_index"], "outcome": outcome, "morphology": morphology, "A_failed_faces": sorted(faces_a), "B_failed_faces": sorted(faces_b), "A_deficit_norm": d_a, "AB_deficit_norm": d_ab, "partner_alignment": align, "axis_interaction_abs": abs(interaction[0]), "norm_interaction_abs": abs(interaction[1]), "linear_interaction_l2": norm(tuple(interaction[2:]))})
                context_reports[context_slug] = {"pairs": len(records), "better_than_V": context_pairs["better_than_V"], "worse_than_V": context_pairs["worse_than_V"], "invalid_invalid": sum(1 for row in records if not row["final_geometry_pass"]["A"] and not row["final_geometry_pass"]["B"]), "alignment_better": quantiles(context_align_success), "alignment_worse": quantiles(context_align_worse)}
            records_total += len(records)
            ordered_rows += len(ordered_domain)
        report.update({"status": "CSC1_R1_COMPLETE", "vmaterialization": {"identity": vm_contract["identity"], "execution_sha256": digest(VMAT / "execution.json"), "finalizer_report_sha256": digest(FINALIZER / "REPORT.json")}, "coverage": {"contexts": 8, "pair_records": records_total, "ordered_domain_records": ordered_rows}, "pair_validity_morphology": pair_counts, "pair_usefulness": useful_counts, "morphology_classes": class_counts, "additive_interaction_diagnostics": {"axis_linf_max": max(additive_axis, default=0.0), "norm_linf_max": max(additive_norm, default=0.0), "linear_l2_max": max(additive_linear, default=0.0), "axis_all_zero": all(value == 0.0 for value in additive_axis), "linear_all_zero": all(value == 0.0 for value in additive_linear), "norm_quantiles": quantiles(additive_norm)}, "routing_alignment": {"better_than_V": quantiles(alignment_success), "worse_than_V": quantiles(alignment_worse), "better_minus_worse_median": (statistics.median(alignment_success) - statistics.median(alignment_worse)) if alignment_success and alignment_worse else None}, "deficit_reduction": {"better_than_V": quantiles(deficit_reduction_success), "worse_than_V": quantiles(deficit_reduction_worse)}, "context_reports": context_reports, "sample_diagnostics": detailed, "admissibility_model": "axis and norm independent unit intervals in gate-normalized space; linear-drive block is a unit L2 ball", "replay_performed": False, "routing_conclusion": "descriptive_only"})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 0
    except Exception as exc:
        report.update({"status": "CSC1_R1_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
