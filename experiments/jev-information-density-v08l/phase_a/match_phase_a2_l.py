"""Match L-NOVEL candidates to certified sham radii under the frozen contract."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean, median
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
CONTRACT_PATH = ROOT / "experiments/jev-information-density-v08l/phase_a/phase-a-v01-contract.json"
OUT = Path(r"D:\codex-runs\jev-information-density-v08l\phase-a-v01-clean")
POOL = OUT / "candidate-pool.jsonl"
FEATURE_DIR = OUT / "feature-cache"
FEATURES = FEATURE_DIR / "state-features.pt"
SCOPE = FEATURE_DIR / "state-scope.jsonl"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    temporary.replace(path)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def tie_key(anchor_id: str, candidate_id: str, contract_hash: str) -> str:
    return hashlib.sha256(f"{anchor_id}|{candidate_id}|{contract_hash}".encode("utf-8")).hexdigest()


def l2(a: torch.Tensor, b: torch.Tensor) -> float:
    return float(torch.linalg.vector_norm(a - b).item())


def assign_group(rows: list[dict[str, Any]], features: torch.Tensor, contract_hash: str) -> list[dict[str, Any]]:
    by_anchor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    candidates: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_anchor[row["anchor_group_id"]].append(row)
        candidates[row["candidate_group_id"]] = row
    anchor_data: dict[str, dict[str, Any]] = {}
    for anchor_id, edges in by_anchor.items():
        first = edges[0]
        anchor_feature = features[int(first["anchor_local_idx"])]
        sham_feature = features[int(first["sham_local_idx"])]
        anchor_data[anchor_id] = {
            "rows": edges,
            "sham_radius": l2(sham_feature, anchor_feature),
        }
    # The frozen order is sham-radius first, then the stable anchor identity.
    order = sorted(anchor_data, key=lambda key: (anchor_data[key]["sham_radius"], key))
    used: set[str] = set()
    chosen: dict[str, dict[str, Any]] = {}
    for anchor_id in order:
        data = anchor_data[anchor_id]
        anchor_feature = features[int(data["rows"][0]["anchor_local_idx"])]
        options = []
        for row in data["rows"]:
            candidate_id = row["candidate_group_id"]
            candidate_radius = l2(features[int(row["candidate_local_idx"])], anchor_feature)
            cost = abs(candidate_radius - data["sham_radius"])
            options.append((cost, tie_key(anchor_id, candidate_id, contract_hash), candidate_id, row, candidate_radius))
        options.sort(key=lambda item: (item[0], item[1], item[2]))
        best_unconstrained_cost = options[0][0]
        available = [item for item in options if item[2] not in used]
        if available:
            best = available[0]
            used.add(best[2])
            chosen[anchor_id] = {"row": best[3], "candidate_radius": best[4], "cost": best[0], "best_unconstrained_cost": best_unconstrained_cost}
            continue
        # The only unused candidate is normally the current anchor itself. Repair the
        # final self-collision by swapping it with one earlier assignment.
        repair_options = []
        for previous_anchor, previous in chosen.items():
            previous_candidate = previous["row"]["candidate_group_id"]
            if previous_candidate == anchor_id:
                continue
            previous_row = next((row for row in anchor_data[previous_anchor]["rows"] if row["candidate_group_id"] == anchor_id), None)
            current_row = next((row for row in data["rows"] if row["candidate_group_id"] == previous_candidate), None)
            if previous_row is None or current_row is None:
                continue
            previous_feature = features[int(previous_row["candidate_local_idx"])]
            previous_anchor_feature = features[int(anchor_data[previous_anchor]["rows"][0]["anchor_local_idx"])]
            previous_candidate_radius = l2(previous_feature, previous_anchor_feature)
            previous_cost = abs(previous_candidate_radius - anchor_data[previous_anchor]["sham_radius"])
            current_feature = features[int(current_row["candidate_local_idx"])]
            current_anchor_feature = features[int(data["rows"][0]["anchor_local_idx"])]
            current_candidate_radius = l2(current_feature, current_anchor_feature)
            current_cost = abs(current_candidate_radius - data["sham_radius"])
            repair_options.append((previous_cost + current_cost, tie_key(anchor_id, previous_anchor, contract_hash), previous_anchor, previous_row, previous_candidate_radius, current_row, current_candidate_radius))
        require(repair_options, f"no feasible self-collision repair for {anchor_id}")
        _, _, previous_anchor, previous_row, previous_radius, current_row, current_radius = min(repair_options, key=lambda item: (item[0], item[1], item[2]))
        previous_anchor_local_idx = int(anchor_data[previous_anchor]["rows"][0]["anchor_local_idx"])
        previous_best = min(
            abs(l2(features[int(row["candidate_local_idx"])], features[previous_anchor_local_idx]) - anchor_data[previous_anchor]["sham_radius"])
            for row in anchor_data[previous_anchor]["rows"]
        )
        chosen[previous_anchor] = {"row": previous_row, "candidate_radius": previous_radius, "cost": abs(previous_radius - anchor_data[previous_anchor]["sham_radius"]), "best_unconstrained_cost": previous_best}
        chosen[anchor_id] = {"row": current_row, "candidate_radius": current_radius, "cost": abs(current_radius - data["sham_radius"]), "best_unconstrained_cost": best_unconstrained_cost}

    require(len(chosen) == len(anchor_data), "assignment did not cover every anchor")
    output = []
    for anchor_id in sorted(chosen):
        selected = chosen[anchor_id]
        row = dict(selected["row"])
        row.update({
            "anchor_radius": anchor_data[anchor_id]["sham_radius"],
            "novel_radius": selected["candidate_radius"],
            "radius_error": selected["cost"],
            "best_unconstrained_radius_error": selected["best_unconstrained_cost"],
            "matching_algorithm": "sorted_sham_radius_greedy_with_self_collision_repair",
        })
        output.append(row)
    return output


def main() -> int:
    contract = read_json(CONTRACT_PATH)
    contract_hash = sha256_file(CONTRACT_PATH)
    receipt = read_json(FEATURE_DIR / "extraction-receipt.json")
    require(receipt["status"] == "PHASE_A1_FEATURE_EXTRACTION_COMPLETE_TRAINING_ONLY", "A1 feature extraction is not complete")
    require(receipt["contract_sha256"] == contract_hash, "feature cache contract binding drift")
    require(sha256_file(POOL) == read_json(OUT / "candidate-pool-summary.json")["candidate_pool_sha256"], "candidate pool drift")
    scope = read_jsonl(SCOPE)
    feature_payload = torch.load(FEATURES, map_location="cpu", weights_only=True)
    features = feature_payload["features"].to(torch.float32)
    require(features.ndim == 2 and features.shape[0] == len(scope) and features.shape[1] == 2048, "feature cache shape drift")
    source_to_local = {int(row["source_state_idx"]): int(row["index"]) for row in scope}
    pool = read_jsonl(POOL)
    for row in pool:
        row["anchor_local_idx"] = source_to_local[int(row["anchor_state_idx"])]
        row["sham_local_idx"] = source_to_local[int(row["sham_state_idx"])]
        row["candidate_local_idx"] = source_to_local[int(row["candidate_state_idx"])]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in pool:
        grouped[row["hard_key_sha256"]].append(row)

    matches: list[dict[str, Any]] = []
    for index, rows in enumerate(grouped.values(), start=1):
        matches.extend(assign_group(rows, features, contract_hash))
        if index % 10 == 0:
            print(json.dumps({"stage": "matching_group", "completed": index, "total": len(grouped)}, separators=(",", ":")), flush=True)
    matches.sort(key=lambda row: row["triplet_id"])
    require(len(matches) == 5000, f"match count drift: {len(matches)}")
    require(len({row["candidate_group_id"] for row in matches}) == 5000, "NOVEL candidate reuse cap violated")
    require(all(row["candidate_group_id"] != row["anchor_group_id"] for row in matches), "self assignment detected")
    errors = [float(row["radius_error"]) for row in matches]
    lower_bounds = [float(row["best_unconstrained_radius_error"]) for row in matches]
    p95 = sorted(errors)[int(0.95 * (len(errors) - 1))]
    lower_p95 = sorted(lower_bounds)[int(0.95 * (len(lower_bounds) - 1))]
    summary = {
        "protocol": contract["protocol"],
        "status": "PHASE_A2_MATCHING_COMPLETE_NO_MODEL_HEAD_OR_EVALUATION",
        "contract_sha256": contract_hash,
        "match_count": len(matches),
        "hard_key_count": len(grouped),
        "candidate_unique_count": len({row["candidate_group_id"] for row in matches}),
        "target_exact": True,
        "different_root": True,
        "different_state": True,
        "radius_error": {"mean": mean(errors), "median": median(errors), "p95": p95, "max": max(errors), "mean_threshold": contract["representation_matching"]["acceptance"]["mean_absolute_radius_error_max"], "p95_threshold": contract["representation_matching"]["acceptance"]["p95_absolute_radius_error_max"]},
        "unconstrained_nearest_lower_bound": {"mean": mean(lower_bounds), "median": median(lower_bounds), "p95": lower_p95, "max": max(lower_bounds)},
        "acceptance": {"mean_pass": mean(errors) <= contract["representation_matching"]["acceptance"]["mean_absolute_radius_error_max"], "p95_pass": p95 <= contract["representation_matching"]["acceptance"]["p95_absolute_radius_error_max"]},
        "model_head_training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "feature_cache_sha256": sha256_file(FEATURES),
        "matching_sha256": "",
    }
    write_jsonl(OUT / "novel-matching.jsonl", matches)
    summary["matching_sha256"] = sha256_file(OUT / "novel-matching.jsonl")
    write_json(OUT / "matching-summary.json", summary)
    write_json(OUT / "matching-receipt.json", {"status": "PASS" if summary["acceptance"]["mean_pass"] and summary["acceptance"]["p95_pass"] else "FAIL_RADIUS_ACCEPTANCE", "summary_sha256": sha256_file(OUT / "matching-summary.json"), "matching_sha256": summary["matching_sha256"], "model_contact": True, "model_head_training": False, "evaluation_inference": False, "protected_evaluation_bodies_opened": False, "phoenix_access": False})
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
