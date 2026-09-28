from __future__ import annotations

import hashlib
import json
import math
import mmap
import statistics
import struct
import sys
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

PROTOCOL = "Q10-CSC1-PRED1"
IDENTITY = "q10-gc1-lr1-requal1-csc1-pred1-v1"
ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
VMAT = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-vmat1-v6"
R1 = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-csc1-r1-v1"
DOMAIN = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pair-domain-v1"
REF = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-par8-ref1-v1"
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


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def slug(key: tuple[str, int]) -> str:
    return f"{key[0].removesuffix('.json')}__set{key[1]}"


def score_key(score: dict[str, Any]) -> tuple[Any, ...]:
    return (int(score["mismatch_count"]), int(score["total_ulp_distance"]), float(score["residual_l2"]), float(score["maximum_absolute_residual"]))


def cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float | None:
    denom = math.sqrt(math.fsum(x * x for x in left)) * math.sqrt(math.fsum(x * x for x in right))
    return None if denom == 0.0 else math.fsum(x * y for x, y in zip(left, right)) / denom


def norm(value: tuple[float, ...]) -> float:
    return math.sqrt(math.fsum(item * item for item in value))


def project(c: tuple[float, ...]) -> tuple[float, ...]:
    axis = max(-1.0, min(1.0, c[0]))
    norm_value = max(-1.0, min(1.0, c[1]))
    linear = tuple(c[2:])
    length = norm(linear)
    if length > 1.0:
        linear = tuple(value / length for value in linear)
    return (axis, norm_value, *linear)


def deficit(c: tuple[float, ...]) -> tuple[float, ...]:
    projected = project(c)
    return tuple(a - b for a, b in zip(projected, c))


class Sidecar:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.handle = (root / "constraint-gate.f64bin").open("rb")
        self.mapping = mmap.mmap(self.handle.fileno(), 0, access=mmap.ACCESS_READ) if self.handle.seek(0, 2) else None
        self.handle.seek(0)

    def close(self) -> None:
        if self.mapping is not None:
            self.mapping.close()
        self.handle.close()

    def read(self, ref: dict[str, Any]) -> tuple[float, ...]:
        require(self.mapping is not None, "empty gate sidecar used for nonempty state")
        offset = int(ref["offset_bytes"]["constraint-gate"])
        length = int(ref["byte_lengths"]["constraint-gate"])
        raw = self.mapping[offset:offset + length]
        require(len(raw) == length and length % 8 == 0, "invalid gate sidecar slice")
        return struct.unpack("<" + "d" * (length // 8), raw)


def split_is_test(context: tuple[str, int], pair_index: int, direction: str) -> bool:
    token = f"{context[0]}|{context[1]}|{pair_index}|{direction}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(token).digest()[:8], "big") % 5 == 0


def rank_observations(observations: list[dict[str, Any]], metric: str) -> list[dict[str, Any]]:
    if metric == "full_alignment":
        return sorted(observations, key=lambda item: (-(item["full_alignment"] if item["full_alignment"] is not None else -float("inf")), item["tie"]))
    if metric == "axis_alignment":
        return sorted(observations, key=lambda item: (-(item["axis_alignment"] if item["axis_alignment"] is not None else -float("inf")), item["tie"]))
    if metric == "partner_magnitude":
        return sorted(observations, key=lambda item: (-item["partner_delta_norm"], item["tie"]))
    if metric == "partner_readout":
        return sorted(observations, key=lambda item: (item["partner_score_key"], item["tie"]))
    if metric == "deterministic_random":
        return sorted(observations, key=lambda item: (item["random_key"], item["tie"]))
    raise RuntimeError(f"unknown ranking metric: {metric}")


def quantiles(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0, "median": None, "mean": None, "min": None, "max": None}
    ordered = sorted(values)
    return {"count": len(values), "median": statistics.median(ordered), "mean": statistics.fmean(values), "min": ordered[0], "max": ordered[-1]}


def metrics_for(groups: dict[str, list[dict[str, Any]]], metric: str) -> dict[str, Any]:
    ranks: list[float] = []
    reciprocal: list[float] = []
    recall = {1: [], 5: [], 10: []}
    enrichments: list[float] = []
    avoided: list[float] = []
    candidate_count = 0
    successes = 0
    for observations in groups.values():
        ranked = rank_observations(observations, metric)
        candidate_count += len(ranked)
        successes += sum(bool(item["success"]) for item in ranked)
        success_ranks = [index + 1 for index, item in enumerate(ranked) if item["success"]]
        if not success_ranks:
            continue
        first = min(success_ranks)
        ranks.append(float(first))
        reciprocal.append(1.0 / first)
        for k in recall:
            recall[k].append(1.0 if first <= min(k, len(ranked)) else 0.0)
        top_n = max(1, math.ceil(len(ranked) / 10))
        top_rate = sum(bool(item["success"]) for item in ranked[:top_n]) / top_n
        overall = sum(bool(item["success"]) for item in ranked) / len(ranked)
        enrichments.append(top_rate / overall if overall else 0.0)
        avoided.append(1.0 - (first / len(ranked)))
    return {"sources": len(groups), "candidates": candidate_count, "successes": successes, "first_success_rank": quantiles(ranks), "mrr": statistics.fmean(reciprocal) if reciprocal else None, "recall_at_1": statistics.fmean(recall[1]) if recall[1] else None, "recall_at_5": statistics.fmean(recall[5]) if recall[5] else None, "recall_at_10": statistics.fmean(recall[10]) if recall[10] else None, "top_decile_enrichment": quantiles(enrichments), "estimated_fraction_evaluations_avoided": quantiles(avoided)}


def main() -> int:
    report: dict[str, Any] = {"protocol": PROTOCOL, "identity": IDENTITY, "replay_performed": False, "scientific_promotion": False}
    try:
        vmat_contract = load(VMAT / "CONTRACT.json")
        vmat_execution = load(VMAT / "execution.json")
        r1_contract = load(R1 / "CONTRACT.json")
        r1_report = load(R1 / "REPORT.json")
        require(vmat_execution["status"] == "CSC1_VMAT1_COMPLETE", "VMAT1 incomplete")
        require(r1_report["status"] == "CSC1_R1_COMPLETE", "CSC1-R1 incomplete")
        require(r1_contract["parent_bindings"][0]["sha256"] == digest(VMAT / "CONTRACT.json"), "R1 VMAT parent drift")
        require(digest(VMAT / "execution.json") == r1_report["vmaterialization"]["execution_sha256"], "R1 materialization hash drift")
        sys.path.insert(0, str(REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-pairs-rerun1-v1/scripts"))
        pair = __import__("run_pairs")
        ref = load(REF / "execution.json")
        v_scores = {(item["endpoint"], int(item["set_index"])): score_key(item["best_valid"]["score"]) for item in ref["results"]}
        groups: dict[str, list[dict[str, Any]]] = {}
        context_counts: dict[str, Any] = {}
        heldout_pairs = 0
        directional_observations = 0
        for key in PAIR_KEYS:
            context_slug = slug(key)
            records = [json.loads(line) for line in (VMAT / "shards" / f"{context_slug}.jsonl").read_text(encoding="utf-8").splitlines() if line]
            domain_rows = load(DOMAIN / "shards" / f"{context_slug}.jsonl")
            index = {row["state_ref"]: row for row in (json.loads(line) for line in (VMAT / "sidecars" / context_slug / "state-index.jsonl").read_text(encoding="utf-8").splitlines() if line)}
            side = Sidecar(VMAT / "sidecars" / context_slug)
            try:
                for record, domain_row in zip(records, domain_rows):
                    for source_role, partner_role, source_field, partner_field in (("A", "B", "a", "b"), ("B", "A", "b", "a")):
                        if not split_is_test(key, int(record["pair_index"]), source_role):
                            continue
                        if bool(record["final_geometry_pass"][source_role]):
                            continue
                        if score_key(record["scores"][source_role]) >= v_scores[key]:
                            continue
                        source = side.read(index[record["state_refs"][source_role]])
                        partner = side.read(index[record["state_refs"][partner_role]])
                        delta = tuple(x - y for x, y in zip(partner, side.read(index[record["state_refs"]["S"])))
                        source_deficit = deficit(source)
                        partner_score = score_key(record["scores"][partner_role])
                        full = cosine(delta, source_deficit)
                        axis = None if delta[0] == 0.0 or source_deficit[0] == 0.0 else (delta[0] * source_deficit[0]) / (abs(delta[0]) * abs(source_deficit[0]))
                        token = f"{key[0]}|{key[1]}|{record['pair_index']}|{source_role}|{domain_row[source_field]['group']}|{domain_row[source_field]['to']}|{domain_row[partner_field]['group']}|{domain_row[partner_field]['to']}".encode("utf-8")
                        source_id = f"{source_role}:{domain_row[source_field]['group']}:{domain_row[source_field]['to']}"
                        groups.setdefault(f"{context_slug}|{source_id}", []).append({"success": record["outcome"] == "VALID_ADVANTAGE_PRESERVED", "full_alignment": full, "axis_alignment": axis, "partner_delta_norm": norm(delta), "partner_score_key": partner_score, "random_key": hashlib.sha256(token).hexdigest(), "tie": (int(record["pair_index"]), partner_role), "pair_index": int(record["pair_index"]), "source_role": source_role, "partner_role": partner_role})
                        heldout_pairs += 1
                        directional_observations += 1
            finally:
                side.close()
            context_counts[context_slug] = {"pair_records": len(records), "heldout_directional_observations_added": directional_observations - sum(item.get("heldout_directional_observations_added", 0) for item in context_counts.values())}
        eligible = {key: value for key, value in groups.items() if len(value) >= 2 and any(item["success"] for item in value)}
        metrics = {name: metrics_for(eligible, name) for name in ("full_alignment", "axis_alignment", "partner_magnitude", "partner_readout", "deterministic_random")}
        report.update({"status": "CSC1_PRED1_COMPLETE", "parents": {"vmat_execution_sha256": digest(VMAT / "execution.json"), "r1_report_sha256": digest(R1 / "REPORT.json")}, "split": {"rule": "sha256(context|pair_index|direction) first eight bytes modulo five equals zero", "heldout_directional_observations": directional_observations, "eligible_sources": len(eligible), "source_filter": "source singleton geometry-invalid and lexicographically better than fresh V", "candidate_pool": "held-out directional observations only"}, "metrics": metrics, "context_counts": context_counts, "score_definitions": {"full_alignment": "cosine(partner gate displacement, source projected-gate deficit)", "axis_alignment": "signed scalar direction agreement", "partner_magnitude": "descending norm of partner gate displacement", "partner_readout": "ascending singleton lexicographic readout score", "deterministic_random": "ascending SHA-256 tie key"}, "replay_performed": False, "routing_conclusion": "engineering_heldout_prediction_only"})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 0
    except Exception as exc:
        report.update({"status": "CSC1_PRED1_BLOCKED", "error_type": type(exc).__name__, "error": str(exc)})
        (ROOT / "REPORT.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
