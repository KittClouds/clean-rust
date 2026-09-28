"""Execute the frozen v0.8N Road-B head-only Phase-B schedule.

The trainer reads only sealed training inputs and the candidate feature tensor.
It has no evaluation paths. Failed attempts are retained separately; a retry,
when permitted, starts the affected seed/arm at epoch zero.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import random
import shutil
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import torch


ROOT = Path(__file__).resolve().parents[3]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
INPUTS = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-v03-inputs")
PACKET = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-authorization-packet-v01")
STATE_ROOT = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\shared-feature-cache")
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
SEEDS = (20260927, 20260928, 20260929)
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(tensor: torch.Tensor) -> str:
    value = tensor.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(value).cast("B")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_jsonl(path: Path, value: Any) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load frozen implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def frozen_bindings() -> tuple[dict[str, Any], dict[str, Any], Any, Any]:
    event_path = PHASE / "phase-b-authorization-event-v01.json"
    event = read_json(event_path)
    run_contract_path = PHASE / "phase-b-run-contract-v01.json"
    analysis_contract_path = PHASE / "phase-b-analysis-contract-v01.json"
    run_contract = read_json(run_contract_path)
    analysis_contract = read_json(analysis_contract_path)
    require(event.get("status") == "PHASE_B_AUTHORIZED", "missing operative Phase-B authorization event")
    require(event.get("phase_b_authorized") is True, "authorization event does not authorize Phase B")
    expected = event["bindings"]
    for name, path in (("run_contract", run_contract_path), ("analysis_contract", analysis_contract_path)):
        require(sha256_file(path) == expected[name]["sha256"], f"{name} hash drift")
    require(sha256_file(PACKET / "authorization-candidate-receipt.json") == expected["candidate_packet_receipt_sha256"], "candidate packet receipt drift")
    require(sha256_file(PACKET / "packet-hash-tree.json") == expected["candidate_packet_tree_sha256"], "candidate packet hash-tree drift")
    for relative, digest in event["implementation_bindings"].items():
        path = ROOT / relative
        require(path.is_file() and sha256_file(path) == digest, f"authorized implementation drift: {relative}")
    require(analysis_contract["parents"]["run_contract"]["sha256"] == expected["run_contract"]["sha256"], "analysis/run parent mismatch")
    require(run_contract["phase_b_ready"] is True and run_contract["phase_b_authorized"] is False, "frozen run contract state drift")
    require(analysis_contract["phase_b_ready"] is True and analysis_contract["phase_b_authorized"] is False, "frozen analysis contract state drift")

    expected_paths = {
        "probe": ("experiments/jev-frozen-readout-v01/probe.py", run_contract["head_input_and_architecture"]["head_implementation_sha256"]),
        "trainer_components": ("experiments/jev-frozen-scaling-v05/train_v05.py", run_contract["training"]["loss"]["implementation_sha256"]),
    }
    for name, (relative, digest) in expected_paths.items():
        require(sha256_file(ROOT / relative) == digest, f"frozen {name} implementation drift")
    probe = load_module("jev_v08n_frozen_probe", ROOT / expected_paths["probe"][0])
    trainer = load_module("jev_v08n_frozen_v05", ROOT / expected_paths["trainer_components"][0])
    return run_contract, analysis_contract, probe, trainer


def verify_runtime(contract: dict[str, Any]) -> None:
    expected = contract["runtime_environment"]
    import importlib.metadata as metadata

    actual = {
        "python": ".".join(map(str, sys.version_info[:3])),
        "torch": torch.__version__,
        "transformers": metadata.version("transformers"),
        "tokenizers": metadata.version("tokenizers"),
        "numpy": metadata.version("numpy"),
        "cuda_runtime": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(),
        "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "compute_capability": list(torch.cuda.get_device_capability(0)) if torch.cuda.is_available() else None,
    }
    for key, value in actual.items():
        require(value == expected[key], f"runtime mismatch for {key}: {value!r} != {expected[key]!r}")
    require(torch.cuda.is_available(), "frozen CUDA device unavailable")
    require(torch.backends.cuda.matmul.allow_tf32 is False, "TF32 matmul must be disabled")


def verify_inputs(contract: dict[str, Any]) -> tuple[torch.Tensor, torch.Tensor, list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    input_receipt_path = INPUTS / "execution-inputs-receipt.json"
    input_tree_path = INPUTS / "execution-inputs-hash-tree.json"
    input_receipt = read_json(input_receipt_path)
    require(sha256_file(input_receipt_path) == contract["parents"]["execution_input_receipt"]["sha256"], "execution input receipt drift")
    require(sha256_file(input_tree_path) == contract["parents"]["execution_input_hash_tree"]["sha256"], "execution input tree drift")
    require(input_receipt["common_primary_manifest"]["sha256"] == contract["head_input_and_architecture"]["arm_input_manifests"]["common_primary_occurrence_manifest"]["sha256"], "primary manifest receipt mismatch")

    paths = {
        "primary": INPUTS / "common-primary-occurrence-manifest.jsonl",
        "schedule": INPUTS / "fixed-training-schedule.jsonl",
        "B-DUP": INPUTS / "head-input-manifest-B-DUP.jsonl",
        "B-MATCHED": INPUTS / "head-input-manifest-B-MATCHED.jsonl",
        "B-SHAM": INPUTS / "head-input-manifest-B-SHAM.jsonl",
    }
    expected_hashes = {
        "primary": contract["head_input_and_architecture"]["arm_input_manifests"]["common_primary_occurrence_manifest"]["sha256"],
        "schedule": contract["training"]["fixed_schedule_sha256"],
        **{arm: contract["head_input_and_architecture"]["arm_input_manifests"][arm]["sha256"] for arm in ARMS},
    }
    for name, path in paths.items():
        require(path.is_file() and sha256_file(path) == expected_hashes[name], f"training input hash mismatch: {name}")

    state_receipt_path = STATE_ROOT / "shared-feature-cache-receipt.json"
    state_receipt = read_json(state_receipt_path)
    require(sha256_file(state_receipt_path) == contract["model_and_representation"]["state_feature_scope_receipt"]["sha256"], "state cache receipt drift")
    require(state_receipt["scope"]["sha256"] == contract["model_and_representation"]["state_feature_scope_sha256"], "state scope hash mismatch")
    state_path = Path(state_receipt["feature_tensor"]["path"])
    scope_path = Path(state_receipt["scope"]["path"])
    require(sha256_file(scope_path) == contract["model_and_representation"]["state_feature_scope_sha256"], "training-only feature scope file hash mismatch")
    scope_rows = read_jsonl(scope_path)
    require(len(scope_rows) == 55_000 and all(row.get("index") == i for i, row in enumerate(scope_rows)), "training-only feature scope index mismatch")
    require(sha256_file(state_path) == contract["model_and_representation"]["state_feature_source_sha256"], "sealed training feature file hash mismatch")
    state_cache = torch.load(state_path, map_location="cpu", weights_only=True)
    state_features = state_cache["features"]["state"][FEATURE_KEY]
    require(state_features.shape == (55_000, 2048) and state_features.dtype == torch.float32 and state_features.is_contiguous(), "training feature tensor contract mismatch")
    require(tensor_sha256(state_features) == state_receipt["feature_tensor"]["tensor_sha256"], "training feature tensor content hash mismatch")

    feature_dir = RUN / "feature-cache"
    candidate_path = feature_dir / "candidate-features.pt"
    candidate_receipt_path = feature_dir / "candidate-feature-receipt.json"
    candidate_receipt = read_json(candidate_receipt_path)
    candidate = torch.load(candidate_path, map_location="cpu", weights_only=True)
    catalog_path = INPUTS / "candidate-catalog.json"
    catalog = read_json(catalog_path)
    require(sha256_file(catalog_path) == contract["candidate_feature_extraction"]["parent_candidate_catalog_sha256"], "candidate catalog hash mismatch")
    extraction = contract["candidate_feature_extraction"]
    model_cfg = contract["model_and_representation"]
    token_receipt_path = feature_dir / "candidate-token-lengths.json"
    token_receipt = read_json(token_receipt_path)
    require(candidate_receipt.get("status") == "CANDIDATE_FEATURES_VALIDATED", "candidate feature receipt status mismatch")
    require(candidate_receipt.get("run_contract_sha256") == sha256_file(PHASE / "phase-b-run-contract-v01.json"), "candidate feature receipt run-contract mismatch")
    require(candidate_receipt.get("input_manifest_sha256") == extraction["candidate_text_manifest_sha256"], "candidate feature receipt text-manifest mismatch")
    require(candidate_receipt.get("catalog_sha256") == extraction["parent_candidate_catalog_sha256"], "candidate feature receipt catalog mismatch")
    require(candidate_receipt.get("model", {}).get("repo_id") == model_cfg["repo_id"] and candidate_receipt["model"].get("revision") == model_cfg["revision"], "candidate feature model identity mismatch")
    require(candidate_receipt["model"].get("snapshot_sha256") == model_cfg["snapshot_file_sha256"], "candidate feature snapshot binding mismatch")
    extractor = candidate_receipt.get("extractor", {})
    require(extractor.get("sha256") == model_cfg["extractor_sha256"] and extractor.get("pooling") == "final-layer mean_full", "candidate feature extractor/pooling mismatch")
    require(extractor.get("batch_size") == 1 and extractor.get("exact_length") is True and extractor.get("padding") is False and extractor.get("max_length") == model_cfg["maximum_length"], "candidate feature extraction mechanics mismatch")
    require(candidate_receipt.get("input_manifest_sha256") == sha256_file(PACKET / "candidate-model-input-manifest.jsonl"), "candidate feature input manifest changed")
    require(candidate_receipt.get("token_length_receipt_sha256") == sha256_file(token_receipt_path), "candidate token-length receipt hash mismatch")
    require(token_receipt.get("status") == "PASS_NO_TRUNCATION" and token_receipt.get("truncation") is False and token_receipt.get("count") == 48, "candidate token/truncation receipt mismatch")
    require(token_receipt.get("candidate_manifest_sha256") == extraction["candidate_text_manifest_sha256"] and token_receipt.get("tokenizer_snapshot_hashes") == model_cfg["snapshot_file_sha256"], "candidate tokenizer receipt identity mismatch")
    token_rows = token_receipt.get("per_candidate", [])
    require(len(token_rows) == 48 and [row.get("candidate_semantic_id") for row in token_rows] == catalog_ids, "candidate token receipt semantic ordering mismatch")
    require(all(0 < int(row.get("token_count", 0)) <= model_cfg["maximum_length"] for row in token_rows), "candidate token receipt contains invalid/truncated length")
    require(candidate_receipt.get("feature_file_sha256") == sha256_file(candidate_path) and candidate_receipt.get("feature_file_bytes") == candidate_path.stat().st_size, "candidate feature file receipt mismatch")
    require(candidate_receipt.get("shape") == [48, 2048] and candidate_receipt.get("dtype") == "torch.float32" and candidate_receipt.get("contiguous") is True, "candidate feature receipt tensor contract mismatch")
    require(sha256_file(candidate_path) == candidate_receipt["feature_file_sha256"], "candidate feature file hash mismatch")
    require(candidate.shape == (48, 2048) and candidate.dtype == torch.float32 and candidate.is_contiguous(), "candidate tensor shape/dtype/layout mismatch")
    require(torch.isfinite(candidate).all().item(), "candidate tensor contains non-finite values")
    require(tensor_sha256(candidate) == candidate_receipt["tensor_sha256"], "candidate tensor hash mismatch")
    catalog_ids = [row["candidate_semantic_id"] for row in catalog["rows"]]
    require(candidate_receipt["semantic_ids"] == catalog_ids and len(catalog_ids) == 48, "candidate tensor semantic ordering mismatch")
    candidate_index = {semantic_id: index for index, semantic_id in enumerate(catalog_ids)}
    require(len(candidate_index) == 48 and catalog["feature_dimension"] == 2048, "candidate catalog cardinality/dimension mismatch")
    require(candidate_receipt["authorization_event_sha256"] == sha256_file(PHASE / "phase-b-authorization-event-v01.json"), "candidate tensor not bound to this authorization")

    primary = read_jsonl(paths["primary"])
    schedule = read_jsonl(paths["schedule"])
    arm_rows = {arm: read_jsonl(paths[arm]) for arm in ARMS}
    require(len(primary) == 10_000 and len(schedule) == 360, "primary/schedule count mismatch")
    require(all(len(arm_rows[arm]) == 15_000 for arm in ARMS), "arm manifest row count mismatch")
    primary_by_episode: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(primary):
        require(source.get("occurrence_index") == index, f"common primary occurrence identity mismatch: {index}")
        require(source.get("source_partition") == "train", f"non-training primary occurrence: {index}")
        require(source["episode_id"] not in primary_by_episode, f"duplicate primary episode identity: {source['episode_id']}")
        primary_by_episode[source["episode_id"]] = source

    for arm in ARMS:
        rows = arm_rows[arm]
        for index, source in enumerate(primary):
            row = rows[index]
            require(row["event_kind"] == "primary" and row["occurrence_index"] == index, f"primary occurrence order drift {arm}:{index}")
            require(row["group_id"] == source["group_id"] and row["source_episode_id"] == source["episode_id"], f"primary identity drift {arm}:{index}")
            require(row["target_hash"] == source["target_hash"] and row["candidate_order_hash"] == source["candidate_order_hash"], f"primary semantic payload drift {arm}:{index}")
            require(row["candidate_semantic_ids"] == source["candidate_semantic_ids"], f"primary candidate semantic order drift {arm}:{index}")
            require(row["candidate_indices"] == [candidate_index[value] for value in source["candidate_semantic_ids"]], f"primary candidate feature index drift {arm}:{index}")
            require(row["feature_scope_index"] >= 0 and row["candidate_mask"] == [True] * 4, f"primary feature index/mask drift {arm}:{index}")
            scope = scope_rows[row["feature_scope_index"]]
            require(scope["episode_id"] == row["source_episode_id"] and scope["input_sha256"] == source["input_sha256"], f"primary feature-scope binding mismatch {arm}:{index}")
            require(row["target"] and len(row["target"]) == 4 and abs(sum(row["target"]) - 1.0) <= 1e-12, f"primary target shape/sum drift {arm}:{index}")
        expected_role = {"B-DUP": "anchor_duplicate", "B-MATCHED": "matched_neutral", "B-SHAM": "certified_sham"}[arm]
        for slot, row in enumerate(rows[10_000:]):
            require(row["event_kind"] == "auxiliary" and row["batch_slot"] == slot, f"auxiliary manifest offset drift {arm}:{slot}")
            require(row["auxiliary_source_role"] == expected_role, f"auxiliary source role drift {arm}:{slot}")
            require(row["target_source_episode_id"] == row["neighborhood_id"] + "-anchor", f"auxiliary target source drift {arm}:{slot}")
            anchor = primary_by_episode.get(row["target_source_episode_id"])
            require(anchor is not None and anchor["role"] == "anchor" and anchor["neighborhood_id"] == row["neighborhood_id"], f"auxiliary target anchor is absent/misbound {arm}:{slot}")
            require(row["target_hash"] == anchor["target_hash"], f"auxiliary target hash differs from its anchor {arm}:{slot}")
            anchor_event = rows[anchor["occurrence_index"]]
            require(row["target"] == anchor_event["target"], f"auxiliary target vector differs from its anchor {arm}:{slot}")
            require(row["candidate_semantic_ids"] == anchor["candidate_semantic_ids"], f"auxiliary candidate order differs from its anchor {arm}:{slot}")
            require(row["candidate_order_hash"] == anchor["candidate_order_hash"], f"auxiliary candidate-order hash differs from its anchor {arm}:{slot}")
            require(row["candidate_indices"] == [candidate_index[value] for value in row["candidate_semantic_ids"]], f"auxiliary candidate feature index drift {arm}:{slot}")
            scope = scope_rows[row["feature_scope_index"]]
            require(scope["episode_id"] == row["source_episode_id"] and scope["neighborhood_id"] == row["neighborhood_id"], f"auxiliary feature-scope binding mismatch {arm}:{slot}")
            expected_scope_role = {"B-DUP": "anchor", "B-MATCHED": None, "B-SHAM": "sham"}[arm]
            if expected_scope_role is None:
                require(str(scope["role"]).startswith("neutral_"), f"matched auxiliary source is not a selected neutral view {arm}:{slot}")
            else:
                require(scope["role"] == expected_scope_role, f"auxiliary source role/scope mismatch {arm}:{slot}")
            if arm == "B-DUP":
                require(row["feature_scope_index"] == anchor["feature_scope_index"], f"duplicate auxiliary does not reuse anchor feature {slot}")
            require(row["candidate_mask"] == [True] * 4 and len(row["candidate_indices"]) == 4, f"candidate mask/cardinality drift {arm}:{slot}")
            require(all(isinstance(i, int) and 0 <= i < 48 for i in row["candidate_indices"]), f"candidate feature index out of range {arm}:{slot}")
            require(len(row["target"]) == 4 and abs(sum(row["target"]) - 1.0) <= 1e-12, f"target shape/sum drift {arm}:{slot}")
    return state_features, candidate, primary, schedule, arm_rows


def prepare_event(row: dict[str, Any]) -> dict[str, Any]:
    return {
        # Auxiliary manifest rows intentionally have no group_id; the source
        # episode is their stable identity and fast_tensor_batch does not use
        # group_id to alter ordering or loss semantics.
        "group_id": row.get("group_id", row["source_episode_id"]),
        "state_idx": row["feature_scope_index"],
        "candidate_indices": {PROFILE: row["candidate_indices"]},
        "gold": row["target"],
        "kind": "choice",
        "probability_source": "exact_generative_posterior",
    }


def seed_everything(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(memoryview(value.numpy()).cast("B"))
    return digest.hexdigest()


def train_one(
    contract: dict[str, Any], trainer: Any, probe: Any, device: str, seed: int, arm: str,
    initial_state: dict[str, torch.Tensor], state_features: torch.Tensor, candidate_features: torch.Tensor,
    primary: list[dict[str, Any]], schedule_rows: list[dict[str, Any]], arm_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    final_dir = RUN / "runs" / f"seed-{seed}" / arm
    if final_dir.exists():
        integrity_path = final_dir / "run-integrity.json"
        require(integrity_path.is_file(), f"existing final run lacks integrity receipt: {final_dir}")
        integrity = read_json(integrity_path)
        require(integrity.get("status") == "TRAINING_COMPLETE_UNEVALUATED" and integrity.get("seed") == seed and integrity.get("arm") == arm, f"existing run identity/status mismatch: {final_dir}")
        run_config_path = final_dir / "run-config.json"
        require(run_config_path.is_file() and sha256_file(run_config_path) == integrity.get("run_config_sha256"), f"existing run config hash mismatch: {final_dir}")
        run_config = read_json(run_config_path)
        require(run_config.get("authorization_event_sha256") == sha256_file(PHASE / "phase-b-authorization-event-v01.json") and run_config.get("seed") == seed and run_config.get("arm") == arm, f"existing run config identity mismatch: {final_dir}")
        require(len(integrity.get("epoch_checkpoints", [])) == 3, f"existing run checkpoint count mismatch: {final_dir}")
        for item in integrity["epoch_checkpoints"]:
            path = final_dir / item["path"]
            require(path.is_file() and sha256_file(path) == item["sha256"], f"existing checkpoint integrity mismatch: {path}")
        terminal_path = final_dir / "epoch-3-terminal.pt"
        terminal = torch.load(terminal_path, map_location="cpu", weights_only=False)
        require(terminal.get("seed") == seed and terminal.get("arm") == arm and terminal.get("epoch") == 3, f"existing terminal checkpoint identity mismatch: {final_dir}")
        require(state_digest(terminal["head_state"]) == integrity["terminal_head_sha256"], f"existing terminal head digest mismatch: {final_dir}")
        require(sha256_file(final_dir / "training-events.jsonl") == integrity["training_events_sha256"], f"existing telemetry hash mismatch: {final_dir}")
        return integrity
    attempt_dir = RUN / "attempts" / f"seed-{seed}" / arm / f"attempt-{uuid.uuid4().hex}"
    attempt_dir.mkdir(parents=True, exist_ok=False)
    write_json(attempt_dir / "run-config.json", {
        "run_contract_sha256": sha256_file(PHASE / "phase-b-run-contract-v01.json"),
        "analysis_contract_sha256": sha256_file(PHASE / "phase-b-analysis-contract-v01.json"),
        "authorization_event_sha256": sha256_file(PHASE / "phase-b-authorization-event-v01.json"),
        "seed": seed, "arm": arm, "device": device, "initial_head_sha256": state_digest(initial_state),
        "primary_manifest_sha256": contract["training"]["primary_occurrence_manifest_sha256"],
        "schedule_sha256": contract["training"]["fixed_schedule_sha256"],
        "arm_manifest_sha256": contract["head_input_and_architecture"]["arm_input_manifests"][arm]["sha256"],
        "candidate_feature_receipt_sha256": sha256_file(RUN / "feature-cache/candidate-feature-receipt.json"),
        "epochs": 3, "optimizer_steps": 120, "evaluation_access": False, "newtight_access": False, "phoenix_access": False,
    })
    (attempt_dir / "initial-head-template.sha256").write_text(state_digest(initial_state) + "\n", encoding="ascii")
    event_path = attempt_dir / "training-events.jsonl"
    head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
    head.load_state_dict(initial_state, strict=True)
    initial_hash = state_digest(head.state_dict())
    require(initial_hash == state_digest(initial_state), f"initial head differs after load: {seed}/{arm}")
    training = contract["training"]
    opt = training["optimizer"]
    optimizer = torch.optim.AdamW(
        head.parameters(), lr=opt["learning_rate"], betas=tuple(opt["betas"]),
        eps=opt["epsilon"], weight_decay=opt["weight_decay"], amsgrad=opt["amsgrad"],
    )
    primary_events = [prepare_event(row) for row in primary]
    aux_events = [prepare_event(row) for row in arm_rows[10_000:]]
    sorted_schedule = sorted(schedule_rows, key=lambda row: (row["epoch"], row["step"]))
    history: list[dict[str, Any]] = []
    started = time.perf_counter()
    append_jsonl(event_path, {"event": "run_start", "seed": seed, "arm": arm, "initial_head_sha256": initial_hash, "evaluation_access": False})
    try:
        for epoch in range(1, 4):
            head.train()
            epoch_rows = [row for row in sorted_schedule if row["epoch"] == epoch]
            require(len(epoch_rows) == 40, f"schedule epoch count mismatch: {seed}/{epoch}")
            loss_sum = 0.0
            base_loss_sum = 0.0
            aux_loss_sum = 0.0
            base_total = aux_total = 0
            append_jsonl(event_path, {"event": "epoch_start", "epoch": epoch, "seed": seed, "arm": arm})
            for step_index, spec in enumerate(epoch_rows, 1):
                step_started = time.perf_counter()
                ids = spec["primary_occurrence_indices"]
                require(len(ids) == len(spec["primary_group_ids"]), "schedule group/index length mismatch")
                base = [primary[index] for index in ids]
                require([row["group_id"] for row in base] == spec["primary_group_ids"], f"schedule primary order mismatch {seed}/{epoch}/{step_index}")
                slots = spec["auxiliary_anchor_batch_slots"]
                require(len(slots) == spec["active_auxiliary_count"], "active auxiliary count mismatch")
                anchor_slots = [primary[index]["occurrence_index"] // 2 for index in ids if primary[index]["role"] == "anchor"]
                require(slots == anchor_slots, f"auxiliary slot alignment mismatch {seed}/{epoch}/{step_index}")
                aux = [arm_rows[10_000 + slot] for slot in slots]
                for slot, event in zip(slots, aux):
                    require(event["batch_slot"] == slot and event["neighborhood_id"] == primary[2 * slot]["neighborhood_id"], f"auxiliary anchor alignment drift at slot {slot}")
                base_group = [prepare_event(row) for row in base]
                aux_group = [prepare_event(row) for row in aux]
                batch = base_group + aux_group
                states, candidates, gold, mask, kinds, sources = trainer.fast_tensor_batch(
                    batch, state_features, candidate_features, PROFILE, device, reorder=True,
                )
                optimizer.zero_grad(set_to_none=True)
                logits = head(states, candidates)
                batch_loss, brier = trainer.v05_loss(logits, gold, mask, kinds, sources, 0.25)
                require(torch.isfinite(batch_loss).item() and torch.isfinite(brier).item(), f"non-finite loss at {seed}/{arm}/{epoch}/{step_index}")
                batch_loss.backward()
                grad_sq = torch.zeros((), device=device)
                for param in head.parameters():
                    if param.grad is not None:
                        require(torch.isfinite(param.grad).all().item(), f"non-finite gradient at {seed}/{arm}/{epoch}/{step_index}")
                        grad_sq += param.grad.detach().float().square().sum()
                grad_norm = float(torch.sqrt(grad_sq).detach().cpu())
                optimizer.step()
                step_loss = float(batch_loss.detach().cpu())
                step_elapsed = time.perf_counter() - step_started
                loss_sum += step_loss * len(batch)
                base_loss_sum += step_loss * len(base)
                aux_loss_sum += step_loss * len(aux)
                base_total += len(base)
                aux_total += len(aux)
                append_jsonl(event_path, {
                    "event": "training_step", "seed": seed, "arm": arm, "epoch": epoch, "step": step_index,
                    "primary_occurrence_indices": ids, "auxiliary_anchor_batch_slots": slots,
                    "primary_events": len(base), "auxiliary_events": len(aux), "loss": step_loss,
                    "brier_component": float(brier.detach().cpu()), "gradient_norm": grad_norm,
                    "learning_rate": optimizer.param_groups[0]["lr"], "evaluation_access": False,
                    "cuda_allocated_bytes": int(torch.cuda.memory_allocated()), "compute_seconds": step_elapsed,
                    "events_per_second": (len(base) + len(aux)) / max(step_elapsed, 1e-12),
                })
            require(base_total == 10_000 and aux_total == 5_000, f"epoch event total mismatch {seed}/{arm}/{epoch}")
            checkpoint = {
                "protocol": contract["protocol"], "seed": seed, "arm": arm, "epoch": epoch,
                "head_state": {key: value.detach().cpu().clone() for key, value in head.state_dict().items()},
                "optimizer_state": optimizer.state_dict(), "initial_head_sha256": initial_hash,
                "terminal_head_sha256": state_digest(head.state_dict()),
                "run_contract_sha256": sha256_file(PHASE / "phase-b-run-contract-v01.json"),
                "evaluation_access": False, "backbone_frozen": True,
            }
            checkpoint_name = f"epoch-{epoch}-terminal.pt" if epoch == 3 else f"epoch-{epoch}.pt"
            checkpoint_path = attempt_dir / checkpoint_name
            temporary = checkpoint_path.with_suffix(checkpoint_path.suffix + ".tmp")
            torch.save(checkpoint, temporary)
            temporary.replace(checkpoint_path)
            epoch_record = {
                "epoch": epoch, "primary_events": base_total, "auxiliary_events": aux_total,
                "optimizer_steps": 40, "mean_loss_over_all_events": loss_sum / (base_total + aux_total),
                "elapsed_seconds": time.perf_counter() - started,
                "epoch_events_per_second": (base_total + aux_total) / max(time.perf_counter() - started, 1e-12),
                "checkpoint_sha256": sha256_file(checkpoint_path),
                "checkpoint_head_sha256": checkpoint["terminal_head_sha256"],
            }
            history.append(epoch_record)
            append_jsonl(event_path, {"event": "epoch_end", **epoch_record, "seed": seed, "arm": arm})
        append_jsonl(event_path, {"event": "run_training_complete", "seed": seed, "arm": arm, "evaluation_access": False})
        integrity = {
            "status": "TRAINING_COMPLETE_UNEVALUATED", "seed": seed, "arm": arm,
            "initial_head_sha256": initial_hash, "terminal_head_sha256": state_digest(head.state_dict()),
            "epoch_checkpoints": [{"path": item.name, "sha256": sha256_file(item)} for item in sorted(attempt_dir.glob("epoch-*.pt"))],
            "training_events_sha256": sha256_file(event_path), "run_config_sha256": sha256_file(attempt_dir / "run-config.json"),
            "optimizer_steps": 120, "epochs": 3, "backbone_frozen": True,
            "evaluation_access": False, "newtight_access": False, "phoenix_access": False,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json(attempt_dir / "run-integrity.json", integrity)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        require(not final_dir.exists(), f"final run path appeared during execution: {final_dir}")
        attempt_dir.replace(final_dir)
        return integrity
    except BaseException as exc:
        write_json(attempt_dir / "failure-receipt.json", {
            "status": "ATTEMPT_FAILED_RETAINED", "seed": seed, "arm": arm,
            "exception_type": type(exc).__name__, "exception": str(exc),
            "attempt_path": str(attempt_dir), "restart_policy": "epoch_zero_only_for_infrastructure_failure",
            "evaluation_access": False,
        })
        raise


def validate_schedule(primary: list[dict[str, Any]], schedule: list[dict[str, Any]], arm_rows: dict[str, list[dict[str, Any]]]) -> None:
    by_seed_epoch: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in schedule:
        by_seed_epoch.setdefault((row["seed"], row["epoch"]), []).append(row)
    for seed in SEEDS:
        for epoch in range(1, 4):
            rows = sorted(by_seed_epoch[(seed, epoch)], key=lambda item: item["step"])
            require(len(rows) == 40 and [row["step"] for row in rows] == list(range(1, 41)), f"schedule step identity mismatch {seed}/{epoch}")
            occurrences = [index for row in rows for index in row["primary_occurrence_indices"]]
            require(sorted(occurrences) == list(range(10_000)), f"schedule primary coverage mismatch {seed}/{epoch}")
            slots = [slot for row in rows for slot in row["auxiliary_anchor_batch_slots"]]
            require(sorted(slots) == list(range(5_000)), f"schedule auxiliary coverage mismatch {seed}/{epoch}")
    for arm, rows in arm_rows.items():
        require(len(rows) == 15_000, f"manifest count mismatch {arm}")
        require(all(row["loss_weight"] == 1.0 for row in rows), f"loss weight drift {arm}")
    require(all(primary[i]["occurrence_index"] == i for i in range(10_000)), "common primary occurrence IDs are not dense/exact")


def main() -> int:
    contract, _analysis, probe, trainer = frozen_bindings()
    verify_runtime(contract)
    output_root = Path(contract["output"]["root"])
    require(output_root == RUN, "contract output path mismatch")
    require((RUN / "feature-cache/candidate-feature-receipt.json").is_file(), "candidate extraction must complete before trainer startup")
    state_cpu, candidate_cpu, primary, schedule, arm_rows = verify_inputs(contract)
    validate_schedule(primary, schedule, arm_rows)
    device = contract["runtime_environment"]["device"]
    state_features = state_cpu.to(device)
    candidate_features = candidate_cpu.to(device)
    require(torch.backends.cuda.matmul.allow_tf32 is False, "TF32 matmul enabled")

    results = []
    global_order = []
    schedule_map: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in schedule:
        schedule_map.setdefault((row["seed"], row["epoch"]), []).append(row)
    for seed in SEEDS:
        seed_everything(seed)
        template = probe.CompatibilityHead(2048, "mlp", 128).to(device)
        initial_state = {key: value.detach().cpu().clone() for key, value in template.state_dict().items()}
        initial_hash = state_digest(initial_state)
        require(sum(value.numel() for value in initial_state.values()) == 590_081, "head parameter count mismatch")
        template_dir = RUN / "head-templates"
        template_dir.mkdir(parents=True, exist_ok=True)
        template_path = template_dir / f"seed-{seed}.pt"
        if template_path.exists():
            saved = torch.load(template_path, map_location="cpu", weights_only=True)
            require(state_digest(saved["state_dict"]) == initial_hash and saved["seed"] == seed, f"paired head template drift: {seed}")
        else:
            temporary = template_path.with_suffix(".pt.tmp")
            torch.save({"seed": seed, "state_dict": initial_state, "state_sha256": initial_hash}, temporary)
            temporary.replace(template_path)
        for arm in contract["training"]["arm_execution_order"][str(seed)]:
            seed_everything(seed)
            arm_schedule = [row for epoch in range(1, 4) for row in sorted(schedule_map[(seed, epoch)], key=lambda item: item["step"])]
            integrity = train_one(
                contract, trainer, probe, device, seed, arm, initial_state,
                state_features, candidate_features, primary, arm_schedule, arm_rows[arm],
            )
            require(integrity["initial_head_sha256"] == initial_hash, f"paired initialization drift {seed}/{arm}")
            results.append({"seed": seed, "arm": arm, "status": integrity["status"], "terminal_head_sha256": integrity["terminal_head_sha256"]})
            global_order.append(f"{seed}/{arm}")
            write_json(RUN / "execution-order.json", {
                "status": "IN_PROGRESS", "authorized_order": contract["training"]["global_execution_order"],
                "completed_order": global_order, "completed_runs": results,
            })
    expected_order = contract["training"]["global_execution_order"]
    require(global_order == expected_order, "global execution order mismatch")
    write_json(RUN / "execution-order.json", {"status": "COMPLETE", "authorized_order": expected_order, "completed_order": global_order, "completed_runs": results})
    tree_entries = []
    for item in sorted((RUN / "head-templates").glob("*.pt")):
        tree_entries.append({"path": str(item), "sha256": sha256_file(item), "bytes": item.stat().st_size})
    for seed in SEEDS:
        for arm in ARMS:
            run_dir = RUN / "runs" / f"seed-{seed}" / arm
            integrity_path = run_dir / "run-integrity.json"
            integrity = read_json(integrity_path)
            require(integrity["status"] == "TRAINING_COMPLETE_UNEVALUATED", f"run incomplete {seed}/{arm}")
            for item in sorted(run_dir.iterdir()):
                if item.is_file():
                    tree_entries.append({"path": str(item), "sha256": sha256_file(item), "bytes": item.stat().st_size})
    for item in sorted((RUN / "feature-cache").iterdir()):
        if item.is_file():
            tree_entries.append({"path": str(item), "sha256": sha256_file(item), "bytes": item.stat().st_size})
    tree_entries.append({"path": str(RUN / "execution-order.json"), "sha256": sha256_file(RUN / "execution-order.json"), "bytes": (RUN / "execution-order.json").stat().st_size})
    write_json(RUN / "checkpoint-hash-tree.json", {"entries": tree_entries, "entry_count": len(tree_entries), "checkpoint_count": 27})
    seal = {
        "status": "ALL_NINE_RUNS_TRAINED_SEALED_UNEVALUATED", "protocol": contract["protocol"],
        "authorization_event_sha256": sha256_file(PHASE / "phase-b-authorization-event-v01.json"),
        "run_contract_sha256": sha256_file(PHASE / "phase-b-run-contract-v01.json"),
        "analysis_contract_sha256": sha256_file(PHASE / "phase-b-analysis-contract-v01.json"),
        "execution_order": global_order, "run_count": len(results), "checkpoint_count": 27,
        "runs": results, "hash_tree_entries": tree_entries,
        "checkpoint_hash_tree_sha256": sha256_file(RUN / "checkpoint-hash-tree.json"),
        "execution_order_sha256": sha256_file(RUN / "execution-order.json"),
        "evaluation_access": False, "protected_panel_opened": False, "newtight_access": False, "phoenix_access": False,
    }
    write_json(RUN / "training-seal-manifest.json", seal)
    print(json.dumps({"status": seal["status"], "runs": len(results), "checkpoints": 27, "training_seal": str(RUN / "training-seal-manifest.json"), "evaluation_access": False}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
