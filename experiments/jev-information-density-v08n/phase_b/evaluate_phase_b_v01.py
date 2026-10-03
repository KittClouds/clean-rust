"""One-time frozen inference on the sealed v0.8N matched held-out panel."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
SEEDS = (20260927, 20260928, 20260929)
ROLE_ORDER = ("anchor", "fact_flip", "sham", "neutral_1", "neutral_2", "neutral_3", "neutral_4", "neutral_5", "neutral_6", "neutral_7", "neutral_8")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def load_probe() -> Any:
    path = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
    spec = importlib.util.spec_from_file_location("jev_v08n_eval_probe", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load frozen CompatibilityHead")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_training_and_panel_metadata() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    verifier_path = PHASE / "verify_training_seal_v01.py"
    spec = importlib.util.spec_from_file_location("jev_v08n_training_seal_verifier", verifier_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load independent training-seal verifier")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    training_validation = module.verify()
    event = read_json(PHASE / "phase-b-authorization-event-v01.json")
    if event.get("phase_b_authorized") is not True:
        raise RuntimeError("Phase-B authorization event is not active")
    analysis_contract = read_json(PHASE / "phase-b-analysis-contract-v01.json")
    surface = analysis_contract["evaluation_surface"]
    seal_path = PANEL / "seal/seal-manifest.json"
    tree_path = PANEL / "seal/heldout-panel-hash-tree.json"
    firewall_path = PANEL / "seal/evaluation-firewall-lock.json"
    seal, tree, firewall = read_json(seal_path), read_json(tree_path), read_json(firewall_path)
    if sha256_file(seal_path) != surface["seal_manifest_sha256"]:
        raise RuntimeError("held-out seal identity drift")
    if sha256_file(tree_path) != surface["panel_hash_tree_sha256"] or sha256_file(firewall_path) != surface["firewall_lock_sha256"]:
        raise RuntimeError("held-out hash-tree/firewall identity drift")
    if seal.get("phase_b_authorized") is not False or seal.get("panel_locked") is not True:
        raise RuntimeError("panel seal state is not pre-unlock")
    if firewall.get("body_access_granted") is not False or firewall.get("evaluation_process_may_read_panel") is not False:
        raise RuntimeError("held-out firewall is not locked")
    if tree.get("panel_manifest") != surface["panel_manifest_sha256"]:
        raise RuntimeError("matched panel manifest hash differs from analysis contract")
    return training_validation, seal, tree


def surface_edit(anchor: str, child: str) -> dict[str, Any]:
    a_lines, b_lines = anchor.splitlines(), child.splitlines()
    changed_lines = [i for i, (a, b) in enumerate(zip(a_lines, b_lines), 1) if a != b]
    if len(a_lines) != len(b_lines) or len(changed_lines) != 1:
        return {"changed_line_count": len(changed_lines), "changed_line_number_one_based": None, "changed_field_identity": None, "changed_character_count": None, "changed_character_start_document_zero_based": None, "whitespace_tokens_before_edit": None, "whitespace_token_count_before": len(anchor.split()), "whitespace_token_count_after": len(child.split())}
    line_no = changed_lines[0]
    left, right = a_lines[line_no - 1], b_lines[line_no - 1]
    prefix_len = 0
    while prefix_len < min(len(left), len(right)) and left[prefix_len] == right[prefix_len]:
        prefix_len += 1
    suffix_len = 0
    while suffix_len < min(len(left) - prefix_len, len(right) - prefix_len) and left[-1 - suffix_len] == right[-1 - suffix_len]:
        suffix_len += 1
    old_changed = len(left) - prefix_len - suffix_len
    new_changed = len(right) - prefix_len - suffix_len
    char_count = max(old_changed, new_changed)
    prefix = left.split(":", 1)[0] if ":" in left else left.strip()
    token_count = len(left[:prefix_len].split())
    document_offset = sum(len(line) + 1 for line in a_lines[:line_no - 1]) + prefix_len
    return {"changed_line_count": 1, "changed_line_number_one_based": line_no,
            "changed_field_identity": prefix.strip(), "changed_character_count": char_count,
            "changed_character_start_document_zero_based": document_offset,
            "whitespace_tokens_before_edit": token_count,
            "whitespace_token_count_before": len(anchor.split()), "whitespace_token_count_after": len(child.split())}


def cosine(left: torch.Tensor, right: torch.Tensor) -> float:
    denom = float(torch.linalg.vector_norm(left) * torch.linalg.vector_norm(right))
    return float(torch.dot(left, right)) / denom if denom else 0.0


def metrics_for_run(seed: int, arm: str, head: torch.nn.Module, panel_rows: list[dict[str, Any]],
                    scope_by_neighborhood: dict[str, dict[str, dict[str, Any]]], neighborhoods: dict[str, dict[str, Any]],
                    eval_features: torch.Tensor, candidate_features: torch.Tensor,
                    candidate_index: dict[str, int], schema_candidate_order: dict[str, list[str]], device: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered_rows: list[dict[str, Any]] = []
    diagnostic_rows: list[dict[str, Any]] = []
    head.eval()
    with torch.inference_mode():
        for panel in sorted(panel_rows, key=lambda row: row["neighborhood_id"]):
            nid = str(panel["neighborhood_id"])
            meta = neighborhoods[nid]
            schema_slug = str(meta["schema_family_id"]).split(":")[-1]
            ids = schema_candidate_order[schema_slug]
            if len(ids) != 4:
                raise RuntimeError(f"held-out schema does not resolve exactly four frozen candidates: {nid}/{schema_slug}/{len(ids)}")
            episode_to_scope = scope_by_neighborhood[nid]
            wanted = {
                "anchor": str(panel["anchor_episode_id"]),
                "fact_flip": str(panel["fact_episode_id"]),
                "sham": str(panel["sham_episode_id"]),
                "matched_neutral": str(panel["matched_neutral_episode_id"]),
            }
            views: dict[str, dict[str, Any]] = {}
            feature_indices: list[int] = []
            targets: list[list[float]] = []
            for view in VIEWS:
                episode_id = wanted[view]
                scope = episode_to_scope.get(episode_id)
                if scope is None:
                    raise RuntimeError(f"selected panel episode lacks feature-scope row: {nid}/{view}")
                feature_indices.append(int(scope["index"]))
                target = [float(value) for value in scope["target"]]
                if len(target) != 4 or abs(sum(target) - 1.0) > 1e-12:
                    raise RuntimeError(f"held-out target is not four-way normalized: {nid}/{view}")
                targets.append(target)
                views[view] = scope
            if max(abs(a - b) for a, b in zip(targets[0], targets[2])) > 1e-12 or max(abs(a - b) for a, b in zip(targets[0], targets[3])) > 1e-12:
                raise RuntimeError(f"held-out invariant target mismatch: {nid}")
            old_index = max(range(4), key=lambda i: (targets[0][i], -i))
            new_index = max(range(4), key=lambda i: (targets[1][i], -i))
            if old_index == new_index:
                raise RuntimeError(f"held-out fact target does not change exact MAP winner: {nid}")
            old_id, new_id = ids[old_index], ids[new_index]
            feature_index_tensor = torch.tensor(feature_indices, dtype=torch.long, device=eval_features.device)
            state_batch = eval_features[feature_index_tensor].to(device)
            cand_indices = torch.tensor([candidate_index[value] for value in ids], dtype=torch.long, device=device)
            candidates = candidate_features[cand_indices].unsqueeze(0).expand(4, -1, -1)
            logits = head(state_batch, candidates)
            probabilities = torch.softmax(logits, dim=1).detach().cpu().tolist()
            for view_index, view in enumerate(VIEWS):
                ordered_rows.append({
                    "seed": seed, "arm": arm, "neighborhood_id": nid,
                    "family_id": panel["family_id"], "template_id": panel.get("template_id"),
                    "schema_family_id": meta["schema_family_id"], "view": view,
                    "episode_id": wanted[view], "candidate_semantic_ids": ids,
                    "prediction": probabilities[view_index], "gold": targets[view_index],
                    "old_candidate_id": old_id, "new_candidate_id": new_id,
                })
            anchor_feature, fact_feature, sham_feature, matched_feature = [eval_features[index].to(torch.float64) for index in feature_indices]
            delta_s, delta_m, delta_f = sham_feature - anchor_feature, matched_feature - anchor_feature, fact_feature - anchor_feature
            selected_axis = next((role for role in ROLE_ORDER if episode_to_scope.get(wanted["matched_neutral"], {}).get("role") == role), None)
            diag = {
                "seed": seed, "arm": arm, "neighborhood_id": nid,
                "family_id": panel["family_id"], "schema_family_id": meta["schema_family_id"],
                "selected_neutral_role": selected_axis,
                "cosine_sham_neutral": cosine(delta_s, delta_m),
                "cosine_sham_fact": cosine(delta_s, delta_f),
                "cosine_matched_fact": cosine(delta_m, delta_f),
                "raw_distance_anchor_sham": float(torch.linalg.vector_norm(delta_s)),
                "raw_distance_anchor_matched": float(torch.linalg.vector_norm(delta_m)),
                "raw_distance_fact_sham": float(torch.linalg.vector_norm(sham_feature - fact_feature)),
                "raw_distance_fact_matched": float(torch.linalg.vector_norm(matched_feature - fact_feature)),
                "radius_error": abs(float(torch.linalg.vector_norm(delta_s)) - float(torch.linalg.vector_norm(delta_m))),
                "sham_surface_edit": surface_edit(views["anchor"]["text"], views["sham"]["text"]),
                "matched_surface_edit": surface_edit(views["anchor"]["text"], views["matched_neutral"]["text"]),
            }
            diagnostic_rows.append(diag)
    return ordered_rows, diagnostic_rows


def main() -> int:
    event_path = PHASE / "phase-b-authorization-event-v01.json"
    event = read_json(event_path)
    if event.get("status") != "PHASE_B_AUTHORIZED" or event.get("phase_b_authorized") is not True:
        raise RuntimeError("no active Phase-B authorization")
    for relative, expected in event["implementation_bindings"].items():
        path = ROOT / relative
        if not path.is_file() or sha256_file(path) != expected:
            raise RuntimeError(f"authorized evaluator/implementation drift: {relative}")
    training_validation, panel_seal, panel_tree = verify_training_and_panel_metadata()
    unlock_path = RUN / "panel-unlock-receipt.json"
    if unlock_path.exists():
        raise FileExistsError("held-out panel unlock receipt already exists; no second opening")
    panel_contract = read_json(PHASE / "phase-b-analysis-contract-v01.json")["evaluation_surface"]
    unlock = {
        "status": "HELDOUT_PANEL_UNLOCKED_ONCE_AFTER_TRAINING_SEAL",
        "authorization_event_sha256": sha256_file(event_path),
        "training_seal_sha256": sha256_file(RUN / "training-seal-manifest.json"),
        "independent_training_seal_validation": training_validation,
        "panel_identity": panel_contract["identity"], "panel_seal_sha256": sha256_file(PANEL / "seal/seal-manifest.json"),
        "panel_hash_tree_sha256": sha256_file(PANEL / "seal/heldout-panel-hash-tree.json"),
        "panel_manifest_sha256": panel_contract["panel_manifest_sha256"],
        "opening_count": 1, "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
    }
    with unlock_path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(unlock, indent=2) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    # This is the single authorized opening of the held-out panel.
    scope_dir = PANEL / "semantic-scope"
    feature_dir = PANEL / "feature-cache"
    matched_dir = PANEL / "matched-panel-v02"
    scope_path = scope_dir / "heldout-feature-scope.jsonl"
    neighborhoods_path = scope_dir / "heldout-neighborhoods.jsonl"
    panel_manifest_path = matched_dir / "heldout-matched-panel-manifest.jsonl"
    selected_path = matched_dir / "selected-heldout-matched-neutral.jsonl"
    feature_receipt_path = feature_dir / "heldout-feature-cache-receipt.json"
    feature_path = feature_dir / "heldout-features.pt"
    expected_hashes = panel_tree
    for key, path in (("semantic_scope", scope_path), ("panel_manifest", panel_manifest_path), ("selected", selected_path), ("feature_cache_receipt", feature_receipt_path), ("feature_tensor", feature_path)):
        if key in expected_hashes and sha256_file(path) != expected_hashes[key]:
            raise RuntimeError(f"opened held-out artifact hash mismatch: {key}")
    scope_rows = read_jsonl(scope_path)
    neighborhood_rows = read_jsonl(neighborhoods_path)
    panel_rows = read_jsonl(panel_manifest_path)
    selected_rows = read_jsonl(selected_path)
    feature_receipt = read_json(feature_receipt_path)
    feature_pack = torch.load(feature_path, map_location="cpu", weights_only=True)
    eval_features = feature_pack["features"]
    if len(scope_rows) != 22_000 or len(neighborhood_rows) != 2_000 or len(panel_rows) != 2_000 or len(selected_rows) != 2_000:
        raise RuntimeError("held-out panel count mismatch after opening")
    if tuple(eval_features.shape) != (22_000, 2048) or eval_features.dtype != torch.float32:
        raise RuntimeError("held-out feature tensor shape/dtype mismatch")
    if any(row.get("index") != index for index, row in enumerate(scope_rows)):
        raise RuntimeError("held-out feature-scope index ordering mismatch")
    if tensor_sha256(eval_features) != feature_receipt["feature_tensor"]["tensor_sha256"]:
        raise RuntimeError("held-out feature tensor content hash mismatch")
    scope_by_id = {str(row["episode_id"]): row for row in scope_rows}
    if len(scope_by_id) != 22_000:
        raise RuntimeError("duplicate held-out episode identity")
    scope_by_neighborhood: dict[str, dict[str, dict[str, Any]]] = {}
    for row in scope_rows:
        scope_by_neighborhood.setdefault(str(row["neighborhood_id"]), {})[str(row["episode_id"])] = row
    if len(scope_by_neighborhood) != 2_000 or any(len(rows) != 11 for rows in scope_by_neighborhood.values()):
        raise RuntimeError("held-out neighborhood-to-scope index mismatch")
    neighborhoods = {str(row["anchor_id"]): row for row in neighborhood_rows}
    panels = {str(row["neighborhood_id"]): row for row in panel_rows}
    selected_by_id = {str(row["neighborhood_id"]): row for row in selected_rows}
    if len(neighborhoods) != 2_000 or len(panels) != 2_000 or len(selected_by_id) != 2_000:
        raise RuntimeError("duplicate held-out neighborhood/panel selection identity")
    if set(neighborhoods) != set(panels) or set(panels) != set(selected_by_id):
        raise RuntimeError("held-out selected panel identities do not reconcile")
    family_counts: dict[str, int] = {}
    for nid, panel in panels.items():
        selected = selected_by_id[nid]
        for panel_key, selected_key in (("anchor_episode_id", "anchor_episode_id"), ("fact_episode_id", "fact_episode_id"), ("sham_episode_id", "sham_episode_id"), ("matched_neutral_episode_id", "matched_neutral_episode_id")):
            if str(panel[panel_key]) != str(selected[selected_key]):
                raise RuntimeError(f"selected held-out panel episode mismatch: {nid}/{panel_key}")
        family = str(panel["family_id"]).split(":")[-1]
        family_counts[family] = family_counts.get(family, 0) + 1
    if family_counts != {"exposure_control": 500, "respiratory_monitoring": 500, "salinity_control": 500, "vibration_monitoring": 500}:
        raise RuntimeError(f"held-out panel family counts drift: {family_counts}")
    if any(row.get("partition") != "eval" for row in scope_rows):
        raise RuntimeError("non-evaluation row found in held-out panel scope")

    run_contract = read_json(PHASE / "phase-b-run-contract-v01.json")
    catalog = read_json(Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs\candidate-catalog.json"))
    candidate_ids = [str(row["candidate_semantic_id"]) for row in catalog["rows"]]
    candidate_index = {value: index for index, value in enumerate(candidate_ids)}
    candidate_pack = torch.load(RUN / "feature-cache/candidate-features.pt", map_location="cpu", weights_only=True)
    candidate_features = candidate_pack
    if candidate_features.shape != (48, 2048) or candidate_features.dtype != torch.float32:
        raise RuntimeError("candidate feature tensor drift during evaluation")
    candidate_receipt_path = RUN / "feature-cache/candidate-feature-receipt.json"
    candidate_receipt = read_json(candidate_receipt_path)
    if candidate_receipt.get("authorization_event_sha256") != sha256_file(PHASE / "phase-b-authorization-event-v01.json"):
        raise RuntimeError("candidate feature receipt belongs to a different authorization event")
    if candidate_receipt.get("feature_file_sha256") != sha256_file(RUN / "feature-cache/candidate-features.pt"):
        raise RuntimeError("candidate feature tensor file is not bound to its receipt")
    if tensor_sha256(candidate_features) != candidate_receipt.get("tensor_sha256"):
        raise RuntimeError("candidate feature tensor content differs from its receipt")
    primary_manifest = read_jsonl(Path(run_contract["head_input_and_architecture"]["arm_input_manifests"]["common_primary_occurrence_manifest"]["path"]))
    schema_candidate_order: dict[str, list[str]] = {}
    for row in primary_manifest:
        ids = [str(value) for value in row["candidate_semantic_ids"]]
        slug = ids[0].split("::", 1)[0]
        if slug in schema_candidate_order and schema_candidate_order[slug] != ids:
            raise RuntimeError(f"training candidate ordering varies within schema: {slug}")
        schema_candidate_order[slug] = ids
    for meta in neighborhood_rows:
        slug = str(meta["schema_family_id"]).split(":")[-1]
        if slug not in schema_candidate_order:
            raise RuntimeError(f"held-out schema has no training candidate-order binding: {slug}")
        if set(schema_candidate_order[slug]) != {candidate_id for candidate_id in candidate_ids if candidate_id.startswith(slug + "::")}:
            raise RuntimeError(f"held-out schema candidate catalog does not reconcile: {slug}")

    device = run_contract["runtime_environment"]["device"]
    eval_features = eval_features.to(device)
    candidate_features = candidate_features.to(device)
    probe = load_probe()
    evaluation_dir = RUN / "evaluation"
    if evaluation_dir.exists():
        raise FileExistsError("evaluation output directory already exists; refusing overwrite")
    evaluation_dir.mkdir(parents=True, exist_ok=False)
    diagnostics_all: list[dict[str, Any]] = []
    predictions_path = evaluation_dir / "predictions.jsonl"
    started = time.perf_counter()
    with predictions_path.open("x", encoding="utf-8", newline="\n") as stream:
        for seed in SEEDS:
            for arm in ARMS:
                checkpoint_path = RUN / "runs" / f"seed-{seed}" / arm / "epoch-3-terminal.pt"
                checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
                head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
                head.load_state_dict(checkpoint["head_state"], strict=True)
                predictions, diagnostics = metrics_for_run(
                    seed, arm, head, panel_rows, scope_by_neighborhood, neighborhoods,
                    eval_features, candidate_features, candidate_index, schema_candidate_order, device,
                )
                for row in predictions:
                    stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
                diagnostics_all.extend(diagnostics)
                print(json.dumps({"event": "heldout_arm_complete", "seed": seed, "arm": arm,
                                  "rows": len(predictions), "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")), flush=True)
                del head, checkpoint
    diagnostics_path = evaluation_dir / "geometry-and-surface-diagnostics.jsonl"
    with diagnostics_path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in diagnostics_all:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    receipt = {
        "status": "FROZEN_TERMINAL_HELDOUT_INFERENCE_COMPLETE",
        "authorization_event_sha256": sha256_file(event_path), "unlock_receipt_sha256": sha256_file(unlock_path),
        "training_seal_sha256": sha256_file(RUN / "training-seal-manifest.json"),
        "panel_seal_sha256": sha256_file(PANEL / "seal/seal-manifest.json"),
        "panel_manifest_sha256": sha256_file(panel_manifest_path), "heldout_feature_receipt_sha256": sha256_file(feature_receipt_path),
        "prediction_path": str(predictions_path), "prediction_sha256": sha256_file(predictions_path),
        "prediction_rows": 72_000, "diagnostics_path": str(diagnostics_path), "diagnostics_sha256": sha256_file(diagnostics_path),
        "terminal_epoch_only": True, "checkpoint_selection": False, "heldout_panel_open_count": 1,
        "newtight_access": False, "legacy_evaluation_access": False, "phoenix_access": False,
        "elapsed_seconds": time.perf_counter() - started,
    }
    write_json(evaluation_dir / "evaluation-receipt.json", receipt)
    print(json.dumps({"status": receipt["status"], "prediction_sha256": receipt["prediction_sha256"], "rows": receipt["prediction_rows"], "phoenix_access": False}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
