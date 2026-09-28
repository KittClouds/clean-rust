"""Single-opening, complete paired Q-R2 prediction pass over its fresh panel."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
Q = ROOT / "experiments/jev-information-density-v08q"
R2 = ROOT / "experiments/jev-information-density-v08q-r2-late-branch"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r2-late-branch-v01")
PANEL = RUN / "panel-v01"
TRAIN = RUN / "training-v01"
OUTPUT = RUN / "evaluation-v01"
PACKET = R2 / "seals/q-r2-phase-packet-seal-v01.json"
TRAIN_CONTRACT = R2 / "contracts/q-r2-run-contract-v01.json"
ANALYSIS_CONTRACT = R2 / "contracts/q-r2-analysis-contract-v01.json"
PANEL_SEAL = PANEL / "seals/q-r2-panel-input-terminal-seal-v01.json"
SEEDS = (646142852, 4252058077, 1220728050, 2568717680, 3591276468, 1418365871,
         3679801188, 3460102370, 2742373327, 154863765, 2514222543, 3252782908,
         139770160, 4146187570, 3662026063, 3393901947, 147164975, 3776251307,
         1091781421, 3214909693, 642604459, 3342956466, 2210322644, 1629262270)
ARMS = ("LATE_SHAM_1X", "LATE_SHAM_HALF")
BRANCH_STEPS = (100, 120)
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
RUN_SHA = "52d093a00076700ed24bfe0e2cc33ada73dfc07d073b39cbdbe52103aef525e6"
ANALYSIS_SHA = "e06cb4d9428f6c1e30603fbfcb442629f991ef96e37555fb09ac7a4fd0b80e64"
PANEL_CONTRACT_SHA = "a835b3d2934265b8f64ebd287e4dbf48f80ffe9bbbfcc1d6ed2650da69f63153"
PACKET_SHA = "3f6367cb5bf03400923913fffb9acc5cc21ffa32ffdaee807615725ff7f2c209"
PACKET_ROOT_SHA = "6b3b826fd3c861e1aa9114371f9db68c704fb9c5ad85e5c8c60a93afba527275"
PROBE_SHA = "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1"
METRIC_SHA = "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4"
INSTRUMENT_RECEIPT: dict[str, Any] | None = None


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha(tensor: torch.Tensor) -> str:
    array = tensor.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def state_sha(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        array = value.detach().cpu().contiguous()
        digest.update(name.encode())
        digest.update(str(array.dtype).encode())
        digest.update(json.dumps(list(array.shape)).encode())
        digest.update(memoryview(array.numpy()).cast("B"))
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with temp.open("r+b") as stream:
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def need(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)


def load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    need(spec is not None and spec.loader is not None, f"cannot load frozen module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def verify_packet() -> dict[str, Any]:
    packet = read_json(PACKET)
    need(sha(PACKET) == PACKET_SHA and packet.get("status") == "SEALED_AUTHORIZED_FOR_PHASE_EXECUTION"
         and packet.get("contract_bundle_root_sha256") == PACKET_ROOT_SHA,
         "R2 sealed authorization packet mismatch")
    for row in packet["contracts"]:
        path = R2 / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"R2 contract binding mismatch: {row['path']}")
    need(sha(TRAIN_CONTRACT) == RUN_SHA and sha(ANALYSIS_CONTRACT) == ANALYSIS_SHA,
         "R2 run/analysis contract hash mismatch")
    return {"packet_sha256": PACKET_SHA, "packet_root_sha256": PACKET_ROOT_SHA}


def verify_instrument_package() -> dict[str, Any]:
    verifier = load_module(R2 / "source/verify_q_r2_instrument_package_v01.py", "q_r2_instrument_verifier_eval")
    return verifier.verify()


def verify_training() -> tuple[dict[str, Any], dict[tuple[int, str, int], dict[str, Any]]]:
    seal_path = TRAIN / "training-seal-manifest.json"
    tree_path = TRAIN / "checkpoint-hash-tree.json"
    need(seal_path.is_file() and tree_path.is_file(), "R2 training seal/tree missing")
    seal, tree = read_json(seal_path), read_json(tree_path)
    need(seal.get("status") == "Q_R2_ALL_PREFIXES_AND_BRANCHES_COMPLETE_SEALED_UNEVALUATED"
         and seal.get("seed_count") == 24 and seal.get("trained_checkpoint_count") == 120
         and seal.get("prefix_count") == 24 and seal.get("continuation_count") == 48,
         "R2 training seal count/status mismatch")
    need(seal.get("run_contract_sha256") == RUN_SHA
         and seal.get("analysis_contract_sha256") == ANALYSIS_SHA
         and seal.get("packet_bundle_root_sha256") == PACKET_ROOT_SHA
         and seal.get("panel_input_seal_sha256") == sha(PANEL_SEAL),
         "R2 training parent binding mismatch")
    need(seal.get("packet_sha256") == PACKET_SHA
         and seal.get("schedule_sha256") == sha(TRAIN / "schedule/fixed-schedule.jsonl")
         and seal.get("evaluation_panel_opened") is False
         and seal.get("training_panel_feedback") is False,
         "R2 training seal packet/schedule/firewall mismatch")
    need(INSTRUMENT_RECEIPT is not None
         and seal.get("instrument_seal_sha256") == INSTRUMENT_RECEIPT["seal_sha256"]
         and seal.get("instrument_entries_root_sha256") == INSTRUMENT_RECEIPT["entries_root_sha256"],
         "R2 training seal instrument-package binding mismatch")
    need(seal.get("checkpoint_tree_sha256") == sha(tree_path)
         and tree.get("trained_checkpoint_count") == 120
         and tree.get("shared_step80_checkpoints") == 24
         and tree.get("late_branch_checkpoints") == 96
         and tree.get("entry_count") == len(tree.get("entries", [])),
         "R2 checkpoint tree identity/count mismatch")
    tree_entries_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(tree["entries"], key=lambda item: item["path"])).encode()).hexdigest()
    need(tree.get("entries_root_sha256") == tree_entries_root,
         "R2 checkpoint tree entries-root mismatch")
    tree_paths = set()
    for entry in tree["entries"]:
        need(entry["path"] not in tree_paths, "duplicate R2 checkpoint tree path")
        tree_paths.add(entry["path"])
        path = TRAIN / Path(entry["path"])
        need(path.is_file() and path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"],
             f"R2 training artifact changed: {entry['path']}")
    checkpoint_lookup: dict[tuple[int, str, int], dict[str, Any]] = {}
    common_seal_path = TRAIN / "common-prefix-seal-v01.json"
    common_seal = read_json(common_seal_path)
    need(common_seal.get("status") == "Q_R2_ALL_24_COMMON_PREFIXES_SEALED"
         and common_seal.get("count") == 24 and common_seal.get("branches_started") is False,
         "R2 common prefix seal mismatch")
    need(seal.get("common_prefix_seal_sha256") == sha(common_seal_path),
         "R2 common-prefix seal hash is not bound by the training seal")
    for seed in SEEDS:
        prefix = common_seal.get("prefixes", {}).get(str(seed))
        need(prefix is not None and prefix.get("seed") == seed and prefix.get("common_prefix_steps") == 80,
             f"R2 common prefix receipt missing: {seed}")
        path80 = Path(prefix["step80_path"])
        need(path80.is_file() and sha(path80) == prefix["step80_sha256"], f"R2 step80 checkpoint mismatch: {seed}")
        checkpoint_lookup[(seed, "COMMON_SHAM_1X", 80)] = {
            "path": path80, "sha256": prefix["step80_sha256"], "head_sha256": prefix["step80_head_sha256"],
            "initial_head_sha256": prefix["initial_sha256"], "schedule_sha256": seal["schedule_sha256"]}
        for branch in ARMS:
            branch_dir = TRAIN / "trajectories/continuations" / f"seed-{seed}" / branch
            receipt = read_json(branch_dir / "branch-receipt.json")
            weight = 1.0 if branch == "LATE_SHAM_1X" else 0.5
            need(receipt.get("status") == "Q_R2_BRANCH_COMPLETE_UNEVALUATED",
                 f"R2 branch disposition invalid: {seed}/{branch}")
            need(receipt.get("seed") == seed and receipt.get("branch") == branch
                 and receipt.get("weight") == weight and receipt.get("fork_step") == 80
                 and receipt.get("fork_sha256") == prefix["step80_sha256"]
                 and receipt.get("fork_head_sha256") == prefix["step80_head_sha256"]
                 and receipt.get("fork_optimizer_sha256") == prefix["optimizer_state_sha256"]
                 and receipt.get("evaluation_panel_opened") is False, f"R2 branch/fork binding mismatch: {seed}/{branch}")
            for step in BRANCH_STEPS:
                path = branch_dir / f"step-{step:03}.pt"
                digest = receipt[f"step{step}_sha256"]
                head_digest = receipt[f"step{step}_head_sha256"]
                need(path.is_file() and sha(path) == digest, f"R2 branch checkpoint bytes mismatch: {seed}/{branch}/{step}")
                checkpoint_lookup[(seed, branch, step)] = {"path": path, "sha256": digest,
                    "head_sha256": head_digest, "initial_head_sha256": prefix["initial_sha256"],
                    "schedule_sha256": seal["schedule_sha256"], "weight": weight}
    need(len(checkpoint_lookup) == 120, "R2 complete evaluation checkpoint matrix absent")
    return seal, checkpoint_lookup


def verify_panel_seal() -> dict[str, Any]:
    seal = read_json(PANEL_SEAL)
    entries = seal.get("entries", [])
    need(seal.get("status") == "Q_R2_PANEL_INPUTS_SEALED_TRAINING_PENDING"
         and seal.get("entry_count") == len(entries) and seal.get("panel_opened") is False,
         "R2 panel terminal input seal mismatch")
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                      for row in sorted(entries, key=lambda row: row["path"]))
    root = hashlib.sha256(payload.encode()).hexdigest()
    need(root == seal.get("root_sha256"), "R2 panel root digest mismatch")
    observed = {path.relative_to(PANEL).as_posix() for path in PANEL.rglob("*")
                if path.is_file() and path != PANEL_SEAL}
    need(observed == {row["path"] for row in entries}, "R2 panel terminal seal file set mismatch")
    for row in entries:
        path = PANEL / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"R2 panel input changed: {row['path']}")
    need(seal.get("panel_verification_status") == "Q_R2_INDEPENDENT_PANEL_VERIFICATION_PASS"
         and seal.get("radius_verification_status") == "PASS"
         and seal.get("target_verification_status") == "Q_R2_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS",
         "R2 panel construction/radius/target verification incomplete")
    for raw_path, expected_hash in seal["external_receipts"].items():
        path = Path(raw_path)
        need(path.is_file() and sha(path) == expected_hash, f"R2 external panel receipt mismatch: {path}")
    need(not seal.get("head_initialization") and not seal.get("training") and not seal.get("inference"),
         "R2 panel seal overstates downstream execution")
    return {"panel_seal_sha256": sha(PANEL_SEAL), "panel_root_sha256": root,
            "entry_count": len(entries)}


def build_panel() -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]],
                           dict[str, dict[str, Any]], torch.Tensor, torch.Tensor,
                           dict[str, int], dict[str, list[str]]]:
    scope = read_jsonl(PANEL / "panel/panel-feature-scope.jsonl")
    target_rows = read_jsonl(PANEL / "target-joins/r2-exact-world-targets.jsonl")
    neighborhoods = read_jsonl(PANEL / "panel/panel-neighborhoods.jsonl")
    selections = read_jsonl(PANEL / "matching/matched-neutral-selection.jsonl")
    state_manifest = read_jsonl(PANEL / "features/r2-state-feature-manifest.jsonl")
    candidate_manifest = read_jsonl(PANEL / "features/r2-candidate-feature-manifest.jsonl")
    sealed_hashes = {row["path"]: row["sha256"] for row in read_json(PANEL_SEAL)["entries"]}
    scope_path = PANEL / "panel/panel-feature-scope.jsonl"
    target_path = PANEL / "target-joins/r2-exact-world-targets.jsonl"
    need(sha(scope_path) == sealed_hashes["panel/panel-feature-scope.jsonl"]
         and sha(target_path) == sealed_hashes["target-joins/r2-exact-world-targets.jsonl"],
         "R2 opened scope/target rows differ from sealed hashes")
    need(len(scope) == len(target_rows) == len(state_manifest) == 22_000
         and len(neighborhoods) == len(selections) == 2_000,
         "R2 opened panel cardinality mismatch")
    need(all(row["index"] == i and target_rows[i]["index"] == i and state_manifest[i]["index"] == i
             for i, row in enumerate(scope)), "R2 panel row order mismatch")
    state_path = PANEL / "features/r2-state-features.pt"
    candidate_path = PANEL / "features/r2-candidate-features.pt"
    state_pack = torch.load(state_path, map_location="cpu", weights_only=True)
    candidate_pack = torch.load(candidate_path, map_location="cpu", weights_only=True)
    states = state_pack["features"]
    candidates = candidate_pack["features"].to("cuda")
    need(tuple(states.shape) == (22_000, 2048) and states.dtype == torch.float32 and states.is_contiguous(),
         "R2 state feature tensor schema mismatch")
    need(tuple(candidates.shape) == (16, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous(),
         "R2 candidate feature tensor schema mismatch")
    receipt = read_json(PANEL / "features/r2-feature-extraction-receipt.json")
    feature_seal = read_json(PANEL / "seals/q-r2-feature-cache-seal-v01.json")
    construction_seal_path = PANEL / "seals/q-r2-panel-construction-seal-v01.json"
    need(receipt.get("status") == "Q_R2_FROZEN_PANEL_FEATURE_EXTRACTION_PASS"
         and receipt.get("panel_root_sha256") == read_json(construction_seal_path).get("root_sha256")
         and receipt.get("panel_seal_sha256") == sha(construction_seal_path)
         and feature_seal.get("root_sha256") == read_json(PANEL_SEAL)["feature_cache_root_sha256"]
         and feature_seal.get("feature_receipt_sha256") == sha(PANEL / "features/r2-feature-extraction-receipt.json"),
         "R2 feature cache receipt/seal identity mismatch")
    need(state_pack.get("scope_sha256") == sha(scope_path)
         and tensor_sha(states) == receipt["state_tensor"]["tensor_sha256"]
         and tensor_sha(candidates) == receipt["candidate_tensor"]["tensor_sha256"],
         "R2 feature tensor content/scope mismatch")
    for i, row in enumerate(state_manifest):
        need(row.get("episode_id") == scope[i]["episode_id"]
             and row.get("feature_sha256") == tensor_sha(states[i]), f"R2 state-feature row binding mismatch: {i}")
    candidate_ids = [str(row["candidate_semantic_id"]) for row in candidate_manifest]
    need(candidate_pack.get("candidate_ids") == candidate_ids and len(candidate_ids) == 16
         and len(set(candidate_ids)) == 16, "R2 candidate feature semantic identity/order mismatch")
    for i, row in enumerate(candidate_manifest):
        need(row.get("feature_sha256") == tensor_sha(candidates[i]), f"R2 candidate feature row binding mismatch: {i}")

    target_by_index = {int(row["index"]): row for row in target_rows}
    scope_by_nid: dict[str, dict[str, dict[str, Any]]] = {}
    for index, raw in enumerate(scope):
        target = target_by_index[index]
        need(raw["episode_id"] == target["episode_id"] and raw["neighborhood_id"] == target["neighborhood_id"]
             and raw["role"] == target["role"], f"R2 target/scope identity mismatch: {index}")
        row = dict(raw)
        row["target"] = [float(value) for value in target["target"]]
        need(len(row["target"]) == 4 and abs(sum(row["target"]) - 1.0) <= 1e-12,
             f"R1 exact target invalid: {index}")
        scope_by_nid.setdefault(str(row["neighborhood_id"]), {})[str(row["episode_id"])] = row
    selection_by_nid = {str(row["neighborhood_id"]): row for row in selections}
    neighborhood_by_nid = {str(row["neighborhood_id"]): row for row in neighborhoods}
    need(len(scope_by_nid) == len(selection_by_nid) == len(neighborhood_by_nid) == 2_000,
         "R1 panel neighborhood identity sets differ")

    candidate_index = {candidate_id: index for index, candidate_id in enumerate(candidate_ids)}
    schema_order: dict[str, list[str]] = {}
    schema_by_slug: dict[str, str] = {}
    for row in sorted(candidate_manifest, key=lambda value: (str(value["schema_family_id"]), int(value["candidate_order"]))):
        slug = str(row["schema_family_id"]).split(":")[-1]
        schema_order.setdefault(slug, []).append(str(row["candidate_semantic_id"]))
        schema_by_slug[slug] = str(row["schema_family_id"])
    need(set(schema_order) == {"exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring"}
         and all(len(ids) == 4 for ids in schema_order.values()), "R2 candidate schema/order map invalid")

    panel_rows: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    for neighborhood_id, raw in neighborhood_by_nid.items():
        roles = scope_by_nid[neighborhood_id]
        selection = selection_by_nid[neighborhood_id]
        neutral_id = str(selection["matched_neutral_episode_id"])
        need(neutral_id in roles and roles[neutral_id]["role"] == selection["matched_neutral_role"],
             f"R2 radius-selected neutral identity mismatch: {neighborhood_id}")
        role_episode = {str(row["role"]): str(row["episode_id"]) for row in roles.values()}
        need(all(role in role_episode for role in ("anchor", "fact_flip", "sham")),
             f"R2 required role absent: {neighborhood_id}")
        slug = str(raw["family_slug"])
        schema_id = schema_by_slug[slug]
        panel_rows.append({
            "neighborhood_id": neighborhood_id, "family_id": raw["family_id"],
            "template_id": roles[role_episode["anchor"]].get("template_id"),
            "anchor_episode_id": role_episode["anchor"], "fact_episode_id": role_episode["fact_flip"],
            "sham_episode_id": role_episode["sham"], "matched_neutral_episode_id": neutral_id,
        })
        metadata[neighborhood_id] = {"schema_family_id": schema_id, "family_id": raw["family_id"],
                                     "family_slug": slug, "template_id": roles[role_episode["anchor"]].get("template_id")}
    return panel_rows, scope_by_nid, metadata, states, candidates, candidate_index, schema_order


def main() -> int:
    stage = "pre_opening_identity_check"
    opened = False
    started = time.perf_counter()
    try:
        global INSTRUMENT_RECEIPT
        INSTRUMENT_RECEIPT = verify_instrument_package()
        packet_binding = verify_packet()
        training_seal, checkpoint_lookup = verify_training()
        panel_binding = verify_panel_seal()
        need(not OUTPUT.exists(), f"R2 evaluation output already exists; no second opening allowed: {OUTPUT}")
        OUTPUT.mkdir(parents=True, exist_ok=False)
        opening = {
            "status": "Q_R2_FRESH_PANEL_OPENED_ONCE_AFTER_COMPLETE_TRAINING_SEAL",
            "opening_count": 1, "panel_root_sha256": panel_binding["panel_root_sha256"],
            "panel_input_seal_sha256": panel_binding["panel_seal_sha256"],
            "packet_sha256": packet_binding["packet_sha256"],
            "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
            "checkpoint_tree_sha256": sha(TRAIN / "checkpoint-hash-tree.json"),
            "instrument_package_seal_sha256": INSTRUMENT_RECEIPT["seal_sha256"],
            "instrument_package_entries_root_sha256": INSTRUMENT_RECEIPT["entries_root_sha256"],
            "training_panel_feedback": False, "all_training_artifacts_sealed_before_open": True,
            "opened_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(OUTPUT / "panel-opening-receipt-v01.json", opening)
        opened = True
        stage = "panel_materialization_and_join_validation"
        panel_rows, scope, metadata, states, candidates, candidate_index, schema_order = build_panel()
        probe_path = ROOT / "experiments/jev-frozen-readout-v01/probe.py"
        metric_path = ROOT / "experiments/jev-information-density-v08n/phase_b/evaluate_phase_b_v01.py"
        need(sha(probe_path) == PROBE_SHA and sha(metric_path) == METRIC_SHA,
             "Q-R2 frozen probe or prediction implementation changed")
        probe = load_module(probe_path, "q_r2_frozen_probe")
        metric = load_module(metric_path, "q_r2_frozen_prediction_function")
        prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
        cell_order: list[dict[str, Any]] = []
        with prediction_path.open("x", encoding="utf-8", newline="\n") as stream:
            for seed in SEEDS:
                cells = [("COMMON_SHAM_1X", 80)]
                cells.extend((branch, step) for branch in ARMS for step in BRANCH_STEPS)
                for branch, step in cells:
                    entry = checkpoint_lookup[(seed, branch, step)]
                    checkpoint = torch.load(entry["path"], map_location="cpu", weights_only=False)
                    weight = 1.0 if branch in {"COMMON_SHAM_1X", "LATE_SHAM_1X"} else 0.5
                    need(checkpoint.get("seed") == seed and checkpoint.get("branch") == branch
                         and checkpoint.get("global_step") == step
                         and checkpoint.get("branch_auxiliary_multiplier") == weight
                         and checkpoint.get("run_contract_sha256") == RUN_SHA
                         and checkpoint.get("initial_head_sha256") == entry["initial_head_sha256"]
                         and checkpoint.get("schedule_sha256") == entry["schedule_sha256"]
                         and checkpoint.get("event_cursor") == step
                         and checkpoint.get("evaluation_panel_opened") is False
                         and checkpoint.get("head_sha256") == entry["head_sha256"]
                         and state_sha(checkpoint["head_state"]) == entry["head_sha256"],
                         f"R2 checkpoint identity/state mismatch: {seed}/{branch}/{step}")
                    head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                    head.load_state_dict(checkpoint["head_state"], strict=True)
                    try:
                        rows, _diagnostics = metric.metrics_for_run(seed, branch, head, panel_rows, scope, metadata,
                                                                    states, candidates, candidate_index, schema_order, "cuda")
                        need(len(rows) == 8_000, f"R2 prediction row count mismatch: {seed}/{branch}/{step}")
                        for row in rows:
                            row.update({"global_step": step, "checkpoint_label": f"step-{step:03}",
                                        "checkpoint_sha256": entry["sha256"],
                                        "head_state_sha256": checkpoint["head_sha256"],
                                        "branch_auxiliary_multiplier": weight})
                            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
                        cell_order.append({"seed": seed, "branch": branch, "step": step, "rows": len(rows),
                                           "checkpoint_sha256": entry["sha256"], "head_state_sha256": entry["head_sha256"]})
                    finally:
                        del head, checkpoint
                        torch.cuda.empty_cache()
                    if len(cell_order) % 4 == 0:
                        stream.flush()
                        os.fsync(stream.fileno())
                    print(json.dumps({"event": "q_r2_eval_cell_complete", "seed": seed, "branch": branch,
                                      "step": step, "cells": len(cell_order), "expected_cells": 120}), flush=True)
            stream.flush()
            os.fsync(stream.fileno())
        need(len(cell_order) == 120 and sum(row["rows"] for row in cell_order) == 960_000
             and all(row["rows"] == 8_000 for row in cell_order), "R2 complete prediction matrix cardinality mismatch")
        prediction_sha = sha(prediction_path)
        tree = {
            "status": "Q_R2_ALL_120_CELLS_AND_960000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS",
            "identity": "JEV-V08Q-R2-PAIRED-LATE-SHAM-WEIGHT-BRANCH-V01",
            "packet_sha256": packet_binding["packet_sha256"],
            "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
            "checkpoint_tree_sha256": sha(TRAIN / "checkpoint-hash-tree.json"),
            "panel_opening_receipt_sha256": sha(OUTPUT / "panel-opening-receipt-v01.json"),
            "panel_root_sha256": panel_binding["panel_root_sha256"],
            "cell_count": 120, "prediction_rows": 960_000, "rows_by_cell": cell_order,
            "raw_predictions": {"path": str(prediction_path), "bytes": prediction_path.stat().st_size,
                                "sha256": prediction_sha},
            "panel_open_count": 1, "predictions_before_analysis": True,
            "checkpoint_selection": False, "training_feedback": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(OUTPUT / "raw-prediction-hash-tree-v01.json", tree)
        write_json(OUTPUT / "inference-receipt-v01.json", {
            "status": "Q_R2_ALL_120_CELLS_INFERRED_AND_SEALED",
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "prediction_sha256": prediction_sha, "prediction_rows": 960_000,
            "cell_count": 120, "panel_open_count": 1, "predictions_before_analysis": True,
            "training": False,
        })
        print(json.dumps({"status": tree["status"], "cells": 120, "rows": 960_000,
                          "prediction_sha256": prediction_sha,
                          "elapsed_seconds": time.perf_counter() - started}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if OUTPUT.exists() and not (OUTPUT / "evaluation-failure-receipt-v01.json").exists():
            write_json(OUTPUT / "evaluation-failure-receipt-v01.json", {
                "status": "Q_R2_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "panel_opened": opened, "automatic_retry": False,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
