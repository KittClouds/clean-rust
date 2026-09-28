"""Single-opening, complete Q-R1 prediction pass over the fresh sealed panel."""

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
R1 = ROOT / "experiments/jev-information-density-v08q-r1"
RUN = Path(r"D:\codex-runs\jev-information-density-v08q-r1\training-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08q-r1\panel-v01")
TRAIN = RUN / "training"
OUTPUT = RUN / "evaluation-v01"
PACKET = R1 / "seals/q-r1-packet-seal-and-authorization-v01.json"
TRAIN_CONTRACT = R1 / "contracts/q-r1-run-contract-v01.json"
ANALYSIS_CONTRACT = R1 / "contracts/q-r1-analysis-contract-v01.json"
PANEL_SEAL = PANEL / "seals/q-r1-panel-input-terminal-seal-v01.json"
SEEDS = (77720160, 4245719435, 3815947415, 3112928194, 4241626823, 534474641,
         3124582801, 4247677041, 811956520, 3972258, 950790373, 949206414)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM", "B-SHAM-LOW")
STEPS = (40, 80, 100, 120)
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
PANEL_ROOT_SHA = "f90fc1de0ce1e728e4b6c72cbc58756e2278c5932adb77dcf33f2b9dff2b6f53"
TRAIN_SHA = "e5fb3bd147bd5866849266937dc5b060abd8047c13faf2dea48908af518c1317"
ANALYSIS_SHA = "98d5f781d8f98a9a2e6f3737ddbcb2765bbb1f174c25a01292db1e3e5cc4e81b"
PACKET_ROOT_SHA = "dfc1f1c9d1e59a1a9abd930f437f3227261e9fa91f85a70ff3ed4c849e6833c0"
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


def per_seed_schedule_hashes() -> dict[int, str]:
    collected: dict[int, list[bytes]] = {seed: [] for seed in SEEDS}
    with (RUN / "schedule/fixed-schedule.jsonl").open("rb") as stream:
        for raw in stream:
            if raw.strip():
                seed = int(json.loads(raw)["seed"])
                need(seed in collected, f"unexpected schedule seed: {seed}")
                collected[seed].append(raw)
    return {seed: hashlib.sha256(b"".join(lines)).hexdigest() for seed, lines in collected.items()}


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
    need(packet.get("status") == "SEALED_AUTHORIZED_PENDING_EXECUTION"
         and packet.get("contract_bundle_root_sha256") == PACKET_ROOT_SHA,
         "R1 sealed authorization packet mismatch")
    for row in packet["contracts"]:
        path = R1 / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"R1 contract binding mismatch: {row['path']}")
    need(sha(TRAIN_CONTRACT) == TRAIN_SHA and sha(ANALYSIS_CONTRACT) == ANALYSIS_SHA,
         "R1 run/analysis contract hash mismatch")
    return {"packet_sha256": sha(PACKET), "packet_root_sha256": PACKET_ROOT_SHA}


def verify_instrument_package() -> dict[str, Any]:
    verifier = load_module(R1 / "source/verify_q_r1_instrument_package_v01.py", "q_r1_instrument_verifier_eval")
    return verifier.verify()


def verify_training() -> tuple[dict[str, Any], dict[tuple[int, str, int], dict[str, Any]]]:
    seal_path = TRAIN / "training-seal-manifest.json"
    tree_path = TRAIN / "checkpoint-hash-tree.json"
    need(seal_path.is_file() and tree_path.is_file(), "R1 training seal/tree missing")
    seal, tree = read_json(seal_path), read_json(tree_path)
    need(seal.get("status") == "Q_R1_ALL_48_RUNS_COMPLETE_SEALED_UNEVALUATED"
         and seal.get("run_count") == 48 and seal.get("trained_checkpoint_count") == 192
         and seal.get("initial_template_count") == 12 and seal.get("sealed_object_count") == 204,
         "R1 training seal count/status mismatch")
    need(seal.get("run_contract_sha256") == TRAIN_SHA
         and seal.get("analysis_contract_sha256") == ANALYSIS_SHA
         and seal.get("packet_bundle_root_sha256") == PACKET_ROOT_SHA
         and seal.get("panel_input_root_sha256") == PANEL_ROOT_SHA,
         "R1 training parent binding mismatch")
    need(seal.get("execution_packet_sha256") == sha(PACKET)
         and seal.get("schedule_sha256") == sha(RUN / "schedule/fixed-schedule.jsonl")
         and seal.get("evaluation_panel_opened") is False
         and seal.get("evaluation_feedback") is False,
         "R1 training seal packet/schedule/firewall mismatch")
    need(INSTRUMENT_RECEIPT is not None
         and seal.get("instrument_manifest_sha256") == INSTRUMENT_RECEIPT["manifest_sha256"]
         and seal.get("instrument_entries_root_sha256") == INSTRUMENT_RECEIPT["entries_root_sha256"],
         "R1 training seal instrument-package binding mismatch")
    preflight_path = TRAIN / "training-preflight-receipt-v01.json"
    preflight = read_json(preflight_path)
    need(seal.get("training_preflight_sha256") == sha(preflight_path)
         and preflight.get("trainer_sha256") == sha(R1 / "source/run_q_r1_training_v01.py")
         and preflight.get("instrument_package", {}).get("seal_sha256") == INSTRUMENT_RECEIPT["seal_sha256"],
         "R1 training preflight/code/instrument receipt mismatch")
    seed_schedule_rows = preflight.get("per_seed_schedule_receipts", [])
    seed_schedule = {int(row["seed"]): row for row in seed_schedule_rows}
    recomputed_seed_schedule = per_seed_schedule_hashes()
    need(len(seed_schedule_rows) == len(SEEDS) and set(seed_schedule) == set(SEEDS)
         and all(row.get("rows") == 120 and row.get("schedule_sha256") == recomputed_seed_schedule[seed]
                 for seed, row in seed_schedule.items()),
         "R1 per-seed schedule receipts are incomplete")
    need(seal.get("checkpoint_tree_sha256") == sha(tree_path)
         and tree.get("trained_checkpoint_count") == 192
         and tree.get("initial_template_count") == 12
         and tree.get("entry_count") == len(tree.get("entries", [])),
         "R1 checkpoint tree identity/count mismatch")
    tree_entries_root = hashlib.sha256("".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(tree["entries"], key=lambda item: item["path"])).encode()).hexdigest()
    need(tree.get("entries_root_sha256") == tree_entries_root,
         "R1 checkpoint tree entries-root mismatch")
    for entry in tree["entries"]:
        path = TRAIN / Path(entry["path"])
        need(path.is_file() and path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"],
             f"R1 training artifact changed: {entry['path']}")
    checkpoint_lookup: dict[tuple[int, str, int], dict[str, Any]] = {}
    for seed in SEEDS:
        template_path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
        template = torch.load(template_path, map_location="cpu", weights_only=True)
        need(template.get("seed") == seed and state_sha(template["state_dict"]) == template.get("state_sha256"),
             f"R1 shared initialization invalid: {seed}")
        for arm in ARMS:
            run_dir = TRAIN / "runs" / f"seed-{seed}" / arm
            integrity = read_json(run_dir / "run-integrity.json")
            need(integrity.get("status") == "Q_R1_TRAINING_COMPLETE_UNEVALUATED"
                 and integrity.get("optimizer_steps") == 120 and integrity.get("checkpoint_count") == 4
                 and integrity.get("evaluation_panel_opened") is False,
                 f"R1 run integrity mismatch: {seed}/{arm}")
            run_config = read_json(run_dir / "run-config.json")
            need(run_config.get("seed") == seed and run_config.get("arm") == arm
                 and run_config.get("initial_state_sha256") == template.get("state_sha256")
                 and run_config.get("seed_schedule_sha256") == seed_schedule[seed]["schedule_sha256"]
                 and integrity.get("seed_schedule_sha256") == seed_schedule[seed]["schedule_sha256"]
                 and integrity.get("run_config_sha256") == sha(run_dir / "run-config.json"),
                 f"R1 run schedule/init receipt mismatch: {seed}/{arm}")
            index = read_jsonl(run_dir / "checkpoint-index.jsonl")
            need([row["step"] for row in index] == list(STEPS), f"R1 checkpoint cadence mismatch: {seed}/{arm}")
            for row in index:
                path = run_dir / row["path"]
                need(path.is_file() and sha(path) == row["sha256"],
                     f"R1 checkpoint file hash mismatch: {seed}/{arm}/{row['step']}")
                checkpoint_lookup[(seed, arm, int(row["step"]))] = {
                    "path": path, "sha256": row["sha256"], "head_sha256": row["head_sha256"]
                }
    need(len(checkpoint_lookup) == 192, "R1 complete checkpoint matrix absent")
    return seal, checkpoint_lookup


def verify_panel_seal() -> dict[str, Any]:
    seal = read_json(PANEL_SEAL)
    entries = seal.get("entries", [])
    need(seal.get("status") == "Q_R1_PANEL_FEATURE_CACHE_RADIUS_AND_TARGETS_SEALED_TRAINING_PENDING"
         and seal.get("root_sha256") == PANEL_ROOT_SHA and seal.get("entry_count") == len(entries),
         "R1 panel terminal input seal mismatch")
    payload = "".join(f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
                      for row in sorted(entries, key=lambda row: row["path"]))
    need(hashlib.sha256(payload.encode()).hexdigest() == PANEL_ROOT_SHA, "R1 panel root digest mismatch")
    for row in entries:
        path = PANEL / row["path"]
        need(path.is_file() and path.stat().st_size == row["bytes"] and sha(path) == row["sha256"],
             f"R1 panel input changed: {row['path']}")
    expected_statuses = {
        "panel_verification_status": "Q_R1_INDEPENDENT_PANEL_VERIFICATION_PASS",
        "radius_verification_status": "Q_R1_INDEPENDENT_RADIUS_AND_CANDIDATE_JOIN_VERIFICATION_PASS",
        "target_verification_status": "Q_R1_INDEPENDENT_EXACT_WORLD_TARGET_JOIN_VERIFICATION_PASS",
    }
    for key, expected in expected_statuses.items():
        need(seal.get(key) == expected, f"R1 panel prerequisite not verified: {key}")
    for raw_path, expected_hash in seal["external_receipts"].items():
        path = Path(raw_path)
        need(path.is_file() and sha(path) == expected_hash, f"R1 external panel receipt mismatch: {path}")
    need(not seal.get("head_initialization") and not seal.get("training") and not seal.get("heldout_inference"),
         "R1 panel seal overstates downstream execution")
    return {"panel_seal_sha256": sha(PANEL_SEAL), "panel_root_sha256": PANEL_ROOT_SHA,
            "entry_count": len(entries)}


def build_panel() -> tuple[list[dict[str, Any]], dict[str, dict[str, dict[str, Any]]],
                           dict[str, dict[str, Any]], torch.Tensor, torch.Tensor,
                           dict[str, int], dict[str, list[str]]]:
    scope = read_jsonl(PANEL / "panel/panel-feature-scope.jsonl")
    target_rows = read_jsonl(PANEL / "target-joins/r1-exact-world-targets.jsonl")
    neighborhoods = read_jsonl(PANEL / "panel/panel-neighborhoods.jsonl")
    selections = read_jsonl(PANEL / "matching/matched-neutral-selection.jsonl")
    state_manifest = read_jsonl(PANEL / "features/r1-state-feature-manifest.jsonl")
    candidate_manifest = read_jsonl(PANEL / "features/r1-candidate-feature-manifest.jsonl")
    sealed_hashes = {row["path"]: row["sha256"] for row in read_json(PANEL_SEAL)["entries"]}
    scope_path = PANEL / "panel/panel-feature-scope.jsonl"
    target_path = PANEL / "target-joins/r1-exact-world-targets.jsonl"
    need(sha(scope_path) == sealed_hashes["panel/panel-feature-scope.jsonl"]
         and sha(target_path) == sealed_hashes["target-joins/r1-exact-world-targets.jsonl"],
         "R1 opened scope/target rows differ from sealed hashes")
    need(len(scope) == len(target_rows) == len(state_manifest) == 22_000
         and len(neighborhoods) == len(selections) == 2_000,
         "R1 opened panel cardinality mismatch")
    need(all(row["index"] == i and target_rows[i]["index"] == i and state_manifest[i]["index"] == i
             for i, row in enumerate(scope)), "R1 panel row order mismatch")
    state_path = PANEL / "features/r1-state-features.pt"
    candidate_path = PANEL / "features/r1-candidate-features.pt"
    state_pack = torch.load(state_path, map_location="cpu", weights_only=True)
    candidate_pack = torch.load(candidate_path, map_location="cpu", weights_only=True)
    states = state_pack["features"]
    candidates = candidate_pack["features"].to("cuda")
    need(tuple(states.shape) == (22_000, 2048) and states.dtype == torch.float32 and states.is_contiguous(),
         "R1 state feature tensor schema mismatch")
    need(tuple(candidates.shape) == (16, 2048) and candidates.dtype == torch.float32 and candidates.is_contiguous(),
         "R1 candidate feature tensor schema mismatch")
    receipt = read_json(PANEL / "features/r1-feature-extraction-receipt.json")
    feature_seal = read_json(PANEL / "seals/q-r1-feature-cache-seal-v01.json")
    construction_seal_path = PANEL / "seals/q-r1-panel-construction-seal-v01.json"
    need(receipt.get("status") == "Q_R1_FROZEN_PANEL_FEATURE_EXTRACTION_PASS"
         and receipt.get("panel_root_sha256") == feature_seal.get("panel_construction_root_sha256")
         and receipt.get("panel_seal_sha256") == sha(construction_seal_path)
         and feature_seal.get("root_sha256") == read_json(PANEL_SEAL)["feature_cache_root_sha256"]
         and feature_seal.get("feature_receipt_sha256") == sha(PANEL / "features/r1-feature-extraction-receipt.json"),
         "R1 feature cache receipt/seal identity mismatch")
    need(state_pack.get("scope_sha256") == sha(scope_path)
         and tensor_sha(states) == receipt["state_tensor"]["tensor_sha256"]
         and tensor_sha(candidates) == receipt["candidate_tensor"]["tensor_sha256"],
         "R1 feature tensor content/scope mismatch")
    for i, row in enumerate(state_manifest):
        need(row.get("episode_id") == scope[i]["episode_id"]
             and row.get("feature_sha256") == tensor_sha(states[i]), f"R1 state-feature row binding mismatch: {i}")
    candidate_ids = [str(row["candidate_semantic_id"]) for row in candidate_manifest]
    need(candidate_pack.get("candidate_ids") == candidate_ids and len(candidate_ids) == 16
         and len(set(candidate_ids)) == 16, "R1 candidate feature semantic identity/order mismatch")
    for i, row in enumerate(candidate_manifest):
        need(row.get("feature_sha256") == tensor_sha(candidates[i]), f"R1 candidate feature row binding mismatch: {i}")

    target_by_index = {int(row["index"]): row for row in target_rows}
    scope_by_nid: dict[str, dict[str, dict[str, Any]]] = {}
    for index, raw in enumerate(scope):
        target = target_by_index[index]
        need(raw["episode_id"] == target["episode_id"] and raw["neighborhood_id"] == target["neighborhood_id"]
             and raw["role"] == target["role"], f"R1 target/scope identity mismatch: {index}")
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
         and all(len(ids) == 4 for ids in schema_order.values()), "R1 candidate schema/order map invalid")

    panel_rows: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    for neighborhood_id, raw in neighborhood_by_nid.items():
        roles = scope_by_nid[neighborhood_id]
        selection = selection_by_nid[neighborhood_id]
        neutral_id = str(selection["matched_neutral_episode_id"])
        need(neutral_id in roles and roles[neutral_id]["role"] == selection["matched_neutral_role"],
             f"R1 radius-selected neutral identity mismatch: {neighborhood_id}")
        role_episode = {str(row["role"]): str(row["episode_id"]) for row in roles.values()}
        need(all(role in role_episode for role in ("anchor", "fact_flip", "sham")),
             f"R1 required role absent: {neighborhood_id}")
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
        need(not OUTPUT.exists(), f"R1 evaluation output already exists; no second opening allowed: {OUTPUT}")
        OUTPUT.mkdir(parents=True, exist_ok=False)
        opening = {
            "status": "Q_R1_FRESH_PANEL_OPENED_ONCE_AFTER_COMPLETE_TRAINING_SEAL",
            "opening_count": 1, "panel_root_sha256": PANEL_ROOT_SHA,
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
             "Q-R1 frozen probe or prediction implementation changed")
        probe = load_module(probe_path, "q_r1_frozen_probe")
        metric = load_module(metric_path, "q_r1_frozen_prediction_function")
        prediction_path = OUTPUT / "raw-predictions-v01.jsonl"
        cell_order: list[dict[str, Any]] = []
        with prediction_path.open("x", encoding="utf-8", newline="\n") as stream:
            for seed in SEEDS:
                init_path = TRAIN / "initial-templates" / f"seed-{seed}.pt"
                init_pack = torch.load(init_path, map_location="cpu", weights_only=True)
                head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                head.load_state_dict(init_pack["state_dict"], strict=True)
                try:
                    rows, _ = metric.metrics_for_run(seed, "COMMON_INIT", head, panel_rows, scope, metadata,
                                                     states, candidates, candidate_index, schema_order, "cuda")
                    need(len(rows) == 8_000, f"R1 initialization prediction count mismatch: {seed}")
                    for row in rows:
                        row.update({"global_step": 0, "checkpoint_label": "COMMON_INIT",
                                    "checkpoint_sha256": sha(init_path), "head_state_sha256": init_pack["state_sha256"]})
                        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    cell_order.append({"seed": seed, "arm": "COMMON_INIT", "step": 0, "rows": len(rows),
                                       "checkpoint_sha256": sha(init_path)})
                finally:
                    del head
                    torch.cuda.empty_cache()
                for step in STEPS:
                    for arm in ARMS:
                        entry = checkpoint_lookup[(seed, arm, step)]
                        checkpoint = torch.load(entry["path"], map_location="cpu", weights_only=False)
                        need(checkpoint.get("seed") == seed and checkpoint.get("arm") == arm
                             and checkpoint.get("global_step") == step
                             and checkpoint.get("schedule_sha256") == sha(RUN / "schedule/fixed-schedule.jsonl")
                             and checkpoint.get("seed_schedule_sha256") == seed_schedule[seed]["schedule_sha256"]
                             and checkpoint.get("initial_head_sha256") == init_pack["state_sha256"],
                             f"R1 checkpoint metadata mismatch: {seed}/{arm}/{step}")
                        need(state_sha(checkpoint["head_state"]) == checkpoint.get("head_sha256") == entry["head_sha256"],
                             f"R1 checkpoint head-state hash mismatch: {seed}/{arm}/{step}")
                        head = probe.CompatibilityHead(2048, "mlp", 128).to("cuda")
                        head.load_state_dict(checkpoint["head_state"], strict=True)
                        try:
                            rows, _ = metric.metrics_for_run(seed, arm, head, panel_rows, scope, metadata,
                                                             states, candidates, candidate_index, schema_order, "cuda")
                            need(len(rows) == 8_000, f"R1 prediction row count mismatch: {seed}/{arm}/{step}")
                            for row in rows:
                                row.update({"global_step": step, "checkpoint_label": f"step-{step:03}",
                                            "checkpoint_sha256": entry["sha256"],
                                            "head_state_sha256": checkpoint["head_sha256"]})
                                stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                            cell_order.append({"seed": seed, "arm": arm, "step": step, "rows": len(rows),
                                               "checkpoint_sha256": entry["sha256"]})
                        finally:
                            del head, checkpoint
                            torch.cuda.empty_cache()
                        if len(cell_order) % 8 == 0:
                            stream.flush()
                            os.fsync(stream.fileno())
                        print(json.dumps({"event": "q_r1_eval_cell_complete", "seed": seed, "arm": arm,
                                          "step": step, "cells": len(cell_order), "expected_cells": 204}),
                              flush=True)
            stream.flush()
            os.fsync(stream.fileno())
        need(len(cell_order) == 204 and sum(row["rows"] for row in cell_order) == 1_632_000
             and all(row["rows"] == 8_000 for row in cell_order), "R1 complete prediction matrix cardinality mismatch")
        prediction_sha = sha(prediction_path)
        tree = {
            "status": "Q_R1_ALL_204_CELLS_AND_1632000_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS",
            "identity": "JEV-V08Q-R1-RESPONSE-PHENOTYPE-REPLICATION",
            "packet_sha256": packet_binding["packet_sha256"],
            "training_seal_sha256": sha(TRAIN / "training-seal-manifest.json"),
            "checkpoint_tree_sha256": sha(TRAIN / "checkpoint-hash-tree.json"),
            "panel_opening_receipt_sha256": sha(OUTPUT / "panel-opening-receipt-v01.json"),
            "panel_root_sha256": PANEL_ROOT_SHA,
            "cell_count": 204, "prediction_rows": 1_632_000, "rows_by_cell": cell_order,
            "raw_predictions": {"path": str(prediction_path), "bytes": prediction_path.stat().st_size,
                                "sha256": prediction_sha},
            "panel_open_count": 1, "predictions_before_analysis": True,
            "checkpoint_selection": False, "training_feedback": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json(OUTPUT / "raw-prediction-hash-tree-v01.json", tree)
        write_json(OUTPUT / "inference-receipt-v01.json", {
            "status": "Q_R1_ALL_204_CELLS_INFERRED_AND_SEALED",
            "prediction_hash_tree_sha256": sha(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "prediction_sha256": prediction_sha, "prediction_rows": 1_632_000,
            "cell_count": 204, "panel_open_count": 1, "predictions_before_analysis": True,
            "training": False,
        })
        print(json.dumps({"status": tree["status"], "cells": 204, "rows": 1_632_000,
                          "prediction_sha256": prediction_sha,
                          "elapsed_seconds": time.perf_counter() - started}, indent=2), flush=True)
        return 0
    except BaseException as exc:
        if OUTPUT.exists() and not (OUTPUT / "evaluation-failure-receipt-v01.json").exists():
            write_json(OUTPUT / "evaluation-failure-receipt-v01.json", {
                "status": "Q_R1_EVALUATION_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
                "stage": stage, "exception_type": type(exc).__name__, "exception": str(exc),
                "panel_opened": opened, "automatic_retry": False,
                "failed_at_utc": datetime.now(timezone.utc).isoformat(),
            })
        raise


if __name__ == "__main__":
    raise SystemExit(main())
