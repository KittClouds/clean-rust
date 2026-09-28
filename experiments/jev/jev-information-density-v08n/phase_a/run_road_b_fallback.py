"""Local fallback executor for the frozen v0.8N Road-B radius-only rule.

This is used only when the delegated deputy does not materialize a branch
artifact. It is intentionally separate from Road-A and never reads Road-A
outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"
NEUTRAL_COUNT = 8
ROLES = ["anchor", "fact_flip", "sham", *[f"neutral_{i}" for i in range(1, NEUTRAL_COUNT + 1)]]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def quantiles(values: torch.Tensor) -> dict[str, float]:
    values = values.detach().to(dtype=torch.float64).flatten()
    q = torch.quantile(values, torch.tensor([0.05, 0.50, 0.95], dtype=torch.float64))
    return {"count": int(values.numel()), "mean": float(values.mean()), "p05": float(q[0]), "p50": float(q[1]), "p95": float(q[2]), "max": float(values.max())}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    selection = read_json(args.selection / "selection-receipt.json")
    selected = read_jsonl(args.selection / "selected-training-neighborhoods.jsonl")
    cache_dir = args.run / "shared-feature-cache"
    cache_receipt_path = cache_dir / "shared-feature-cache-receipt.json"
    cache_receipt = read_json(cache_receipt_path)
    if selection.get("status") != "V08N_N0_FEATURE_FREE_SELECTION_PASS" or len(selected) != 5_000:
        raise RuntimeError("Road B selection gate not passed")
    if cache_receipt.get("status") != "V08N_SHARED_FEATURE_CACHE_SEALED_TRAINING_ONLY":
        raise RuntimeError("shared cache not sealed")
    if cache_receipt.get("evaluation_inference") is not False or cache_receipt.get("protected_evaluation_bodies_opened") is not False:
        raise RuntimeError("cache boundary drift")

    feature_payload = torch.load(cache_dir / "shared-training-features.pt", map_location="cpu", weights_only=True)
    features = feature_payload["features"].to(dtype=torch.float32).reshape(5_000, 11, 2_048)
    certificates = {row["anchor_id"]: row for row in read_jsonl(args.run / "train-contrast-certificates.jsonl")}
    parent_hashes = {
        "contract": sha256_file(CONTRACT),
        "selection_manifest": sha256_file(args.selection / "selected-training-neighborhoods.jsonl"),
        "cache_receipt": sha256_file(cache_receipt_path),
        "feature_tensor": cache_receipt["feature_tensor"]["sha256"],
    }
    radius_sham = torch.linalg.vector_norm(features[:, 2, :] - features[:, 0, :], dim=1).to(torch.float64)
    radius_neutral = torch.linalg.vector_norm(features[:, 3:, :] - features[:, 0, None, :], dim=2).to(torch.float64)
    mismatch = (radius_neutral - radius_sham[:, None]).abs()
    tie_hashes = [[hashlib.sha256(f"jev-v08n-road-b-tie-v01|{selected[i]['anchor_id']}|{j}|{parent_hashes['contract']}|{parent_hashes['feature_tensor']}".encode("utf-8")).hexdigest() for j in range(NEUTRAL_COUNT)] for i in range(5_000)]
    chosen: list[int] = []
    for row_index in range(5_000):
        best = min(range(NEUTRAL_COUNT), key=lambda j: (float(mismatch[row_index, j]), tie_hashes[row_index][j]))
        chosen.append(best)

    chosen_tensor = torch.tensor(chosen, dtype=torch.long)
    chosen_abs = mismatch[torch.arange(5_000), chosen_tensor]
    chosen_rel = chosen_abs / radius_sham.clamp_min(torch.finfo(torch.float64).tiny)
    families = [str(row["family_id"]) for row in selected]
    family_values: dict[str, list[float]] = defaultdict(list)
    for family, value in zip(families, chosen_rel.tolist()):
        family_values[family].append(float(value))
    family_means = {family: float(sum(values) / len(values)) for family, values in sorted(family_values.items())}
    gates = {
        "mean_relative_radius_error": float(chosen_rel.mean()),
        "mean_relative_radius_error_limit": 0.10,
        "p95_absolute_radius_error": float(torch.quantile(chosen_abs, torch.tensor(0.95, dtype=torch.float64))),
        "p95_absolute_radius_error_limit": 0.25,
        "maximum_family_mean_relative_error": max(family_means.values()),
        "family_mean_relative_error_limit": 0.15,
    }
    gate_pass = gates["mean_relative_radius_error"] <= 0.10 and gates["p95_absolute_radius_error"] <= 0.25 and gates["maximum_family_mean_relative_error"] <= 0.15

    certificates_rows: list[dict[str, Any]] = []
    for i, selected_row in enumerate(selected):
        certificate = certificates[selected_row["anchor_id"]]
        anchor_target = certificate["exact_target_before"]
        neutral_index = chosen[i]
        neutral_target = certificate["exact_neutral_targets"][neutral_index]
        if max(abs(float(a) - float(b)) for a, b in zip(anchor_target, neutral_target)) > 1e-12:
            raise RuntimeError(f"neutral target failure: {selected_row['anchor_id']}")
        if certificate["nuisance_axes"]["neutral"][neutral_index] == certificate["nuisance_axes"]["sham"]:
            raise RuntimeError(f"neutral/sham axis collision: {selected_row['anchor_id']}")
        certificates_rows.append({
            "anchor_id": selected_row["anchor_id"],
            "family_id": selected_row["family_id"],
            "auxiliary_source_role": "matched_neutral",
            "neutral_index": neutral_index + 1,
            "neutral_axis": certificate["nuisance_axes"]["neutral"][neutral_index],
            "anchor_episode_id": certificate["episode_ids"]["anchor"],
            "fact_episode_id": certificate["episode_ids"]["fact_flip"],
            "sham_episode_id": certificate["episode_ids"]["sham"],
            "neutral_episode_id": certificate["episode_ids"]["neutrals"][neutral_index],
            "target_sha256": sha256_json(anchor_target),
            "sham_radius": float(radius_sham[i]),
            "neutral_radius": float(radius_neutral[i, neutral_index]),
            "absolute_radius_error": float(chosen_abs[i]),
            "relative_radius_error": float(chosen_rel[i]),
            "edit_magnitude": certificate["edit_magnitude"],
        })

    branch_dir = args.output / "road-b-local-fallback"
    if branch_dir.exists():
        raise RuntimeError("refusing to overwrite Road-B fallback branch")
    branch_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(branch_dir / "selected-matched-neutral.jsonl", certificates_rows)
    axis_histogram = dict(sorted(Counter(row["neutral_axis"] for row in certificates_rows).items()))
    selected_hash = sha256_file(branch_dir / "selected-matched-neutral.jsonl")
    if gate_pass:
        common = {"primary_bank": "F100 from v0.8N selected neighborhoods", "auxiliary_count": 5_000, "target_multiset": "anchor target for all auxiliary events", "weights": "frozen contract", "schedule": "frozen contract", "feature_universe": "shared A,F,S,N1..N8 cache"}
        write_json(branch_dir / "b-dup-arm.json", {**common, "arm": "B-DUP", "auxiliary_source_role": "anchor_duplicate"})
        write_json(branch_dir / "b-matched-arm.json", {**common, "arm": "B-MATCHED", "auxiliary_source_role": "matched_neutral", "selected_control_sha256": selected_hash})
        write_json(branch_dir / "b-sham-arm.json", {**common, "arm": "B-SHAM", "auxiliary_source_role": "certified_sham"})
    report = {
        "status": "V08N_ROAD_B_RADIUS_MATCHED_CONTROL_PASS" if gate_pass else "V08N_ROAD_B_RADIUS_GATE_FAIL",
        "phase_identity": "v0.8N-road-b-matched-control-v01-local-fallback",
        "deputy_status": "DEPUTY_NO_MATERIALIZED_ARTIFACT",
        "parent_hashes": parent_hashes,
        "selected_control_sha256": selected_hash,
        "selection_rule": "argmin absolute sham-radius mismatch; deterministic hash tie-break only",
        "forbidden_selection_inputs": ["direction", "cosine", "learned outputs", "Road-A outputs", "historical outcomes", "evaluation data", "family performance"],
        "gates": gates,
        "selected_axis_histogram": axis_histogram,
        "counts": {"anchors": 5_000, "selected_controls": len(certificates_rows)},
        "boundary": {"training_only": True, "head_training": False, "evaluation_inference": False, "protected_evaluation_bodies_opened": False, "phoenix_access": False, "road_a_read": False},
        "replacement_selection_after_gate": False,
        "threshold_relaxation": False,
    }
    write_json(branch_dir / "road-b-report.json", report)
    files = [branch_dir / "selected-matched-neutral.jsonl", branch_dir / "road-b-report.json", CONTRACT, args.selection / "selected-training-neighborhoods.jsonl", cache_receipt_path]
    hash_tree = {str(path): sha256_file(path) for path in files}
    write_json(branch_dir / "road-b-hash-tree.json", hash_tree)
    write_json(branch_dir / "road-b-seal-manifest.json", {"status": report["status"], "report_sha256": sha256_file(branch_dir / "road-b-report.json"), "hash_tree_sha256": sha256_file(branch_dir / "road-b-hash-tree.json"), "local_fallback": True, "luna_status": "NOT_APPLICABLE", "deputy_status": report["deputy_status"]})
    write_json(branch_dir / "road-b-boundary-audit.json", report["boundary"])
    print(json.dumps({"status": report["status"], "gates": gates, "selected_axis_histogram": axis_histogram, "branch_dir": str(branch_dir)}, indent=2))
    return 0 if gate_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
