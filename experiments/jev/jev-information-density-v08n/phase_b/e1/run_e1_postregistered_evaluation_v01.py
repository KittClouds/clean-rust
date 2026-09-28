"""Run the explicitly authorized, post-registered v0.8N-E1 evaluation.

This sidecar never edits the original Phase-B evaluator, panel, checkpoints, or
their seals. It records E1 opening 2 before reading panel bodies, writes every
raw prediction before invoking the frozen analyzer, and refuses an existing
output directory so a failed opening cannot be silently repeated.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[4]
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
E1_SOURCE = ROOT / "experiments/jev-information-density-v08n/phase_b/e1"
E1 = Path(r"D:\codex-runs\jev-information-density-v08n-e1\v0.8N-E1-heldout-candidate-basis-v01")
PANEL = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-eval-panel-v01")
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
OUTPUT = Path(r"D:\codex-runs\jev-information-density-v08n-e1\v0.8N-E1-postregistered-repaired-heldout-evaluation-v01")

IDENTITY = "POST-REGISTERED v0.8N-E1 REPAIRED HELD-OUT EVALUATION OF SEALED PHASE-B CHECKPOINTS"
SEEDS = (20260927, 20260928, 20260929)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
DEVICE = "cuda:0"

EXPECTED = {
    "e1_contract": "770d2e3a548e4e31e6a1e7af878f19db925f901666c5bceecd0c11454ee858e2",
    "e1_candidate_manifest": "7987ae385454b32ddec548e48ef6543253b7b061ee1f077c064363c06304a285",
    "e1_extraction_auth": "e1b0c2894eaa9330cabdb500330570d6d0edad9bba7a3067d2df41b10f32552f",
    "e1_basis_seal": "f3469f326200d1c097969be1d36741e2b01cc7542911ce79c5b240dc5b6c2b33",
    "e1_feature_receipt": "b869ac29d2b552db34e93f1d585898d51ad4617d8b62ccfb09cafc4dd062d391",
    "e1_feature_file": "58f38feb6af0e1c4f7b6d245b3c374aea3c8777fdbb78b3626c8ee7f13e5448a",
    "e1_tensor_content": "642f7bf4d83866beb1efaa0d92e16544636cdc19e8e1e75b4f1424dce8a50fb8",
    "e1_join_receipt": "03022f1159d7b29d51a33f3e0638b7d8e111cce0ae3795dc81177b2ccc4db920",
    "e1_join_manifest": "5d9b851b61a305091a6489df6f7a3b09b02dd70c043d2554f17e9487f6544003",
    "panel_seal": "425cef320df94e2b47b448203f8a916ebcbb2019539b2d09e51f5b4ced92f614",
    "panel_hash_tree": "fc0adf7f8d1b9a10914dd9aa85282a42b0cd4bbe185f8b09710498b556d0f08f",
    "panel_firewall": "79d25ac82fba1bc6332e16d8bc5f877fadd11cccaed5ef3f07eacfe5e1877da2",
    "panel_manifest": "80e09c0f203b8a6505e062a2091a594273dca808258ff2f4539ab8414db9eabe",
    "neighborhood_identities": "031e834e784868c16e3a71cd8f1c5ccab88c81ff496c6b062d535266a33028ac",
    "training_seal": "43932fc963b150167972e81b1c1bb93f6989e9b93faa65ab1eee3ecf55c7b727",
    "checkpoint_tree": "add6dfd013c936b100e7cbdb205018bf91b95e91ed11ca854b26aed998c66923",
    "first_opening": "e8ff5e4548ab5e0b2b96433d844c64836aa03ff878034381c1933db913cb3ec0",
    "original_disposition": "bae6d7ac88f5ca0c5684c219e0e0b82f03962bf6f0292c205cba58765c75a656",
    "run_contract": "da538aa03355732a2ba362da45d947e169b87aa644d0efd6ba7ef7a546306c1f",
    "execution_contract": "efb2bbe59293d7899083927cc187a292b5dfd1dc2948a0b752b3d9cbae2fd18d",
    "analysis_contract": "0072c44903ea253cd8ad288cda8c100270f19d909ddced098af32d388ac29e1f",
    "frozen_evaluator": "fa22bc8febff89d2b635091c6cb40be6f3beba4549c4a135d16e213f6fd3dda4",
    "v08n_analyzer": "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70",
    "reference_metric": "892939aaa4d3bd2d7868c18d411cab7ac4f9c03aaef9f0d4a1fdaadb7d39d06a",
    "probe": "a3049d52e1183c806c84522a617a05646eb86fbcb69af72b5bb26f4808852cb1",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tensor_sha256(value: torch.Tensor) -> str:
    array = value.detach().cpu().contiguous().numpy()
    return hashlib.sha256(memoryview(array).cast("B")).hexdigest()


def state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8"))
        digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii"))
        digest.update(memoryview(value.numpy()).cast("B"))
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json_exclusive(path: Path, value: Any) -> None:
    payload = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def write_json_atomic(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def import_module(path: Path, module_name: str) -> Any:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen implementation: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def assert_hash(path: Path, expected: str, label: str) -> str:
    if not path.is_file():
        raise FileNotFoundError(f"missing {label}: {path}")
    actual = sha256_file(path)
    if actual != expected:
        raise RuntimeError(f"{label} SHA-256 mismatch: expected {expected}, got {actual}")
    return actual


def static_preflight() -> dict[str, Any]:
    if OUTPUT.exists():
        raise FileExistsError(f"E1 output identity already exists; refusing a second attempt: {OUTPUT}")

    paths = {
        "e1_contract": E1_SOURCE / "e1-repair-contract-v01.json",
        "e1_candidate_manifest": E1_SOURCE / "e1-candidate-text-manifest-v01.jsonl",
        "e1_extraction_auth": E1_SOURCE / "e1-candidate-extraction-authorization-v01.json",
        "e1_basis_seal": E1 / "e1-candidate-basis-seal-v01.json",
        "e1_feature_receipt": E1 / "feature-cache/heldout-candidate-feature-receipt.json",
        "e1_feature_file": E1 / "feature-cache/heldout-candidate-features.pt",
        "e1_join_receipt": E1 / "target-free-schema-candidate-join-receipt-v01.json",
        "e1_join_manifest": E1 / "target-free-schema-candidate-join-v01.jsonl",
        "panel_seal": PANEL / "seal/seal-manifest.json",
        "panel_hash_tree": PANEL / "seal/heldout-panel-hash-tree.json",
        "panel_firewall": PANEL / "seal/evaluation-firewall-lock.json",
        "panel_manifest": PANEL / "matched-panel-v02/heldout-matched-panel-manifest.jsonl",
        "training_seal": RUN / "training-seal-manifest.json",
        "checkpoint_tree": RUN / "checkpoint-hash-tree.json",
        "first_opening": RUN / "panel-unlock-receipt.json",
        "original_disposition": PHASE / "phase-b-final-disposition-v01.json",
        "run_contract": PHASE / "phase-b-run-contract-v01.json",
        "execution_contract": PHASE / "phase_b-contract-v02.json",
        "analysis_contract": PHASE / "phase-b-analysis-contract-v01.json",
        "frozen_evaluator": PHASE / "evaluate_phase_b_v01.py",
        "v08n_analyzer": PHASE / "analyze_phase_b_v01.py",
        "reference_metric": ROOT / "experiments/jev-information-density-v08i/phase_b/analyze_phase_b.py",
        "probe": ROOT / "experiments/jev-frozen-readout-v01/probe.py",
    }
    verified = {name: assert_hash(path, EXPECTED[name], name) for name, path in paths.items()}

    e1_seal = read_json(paths["e1_basis_seal"])
    join_receipt = read_json(paths["e1_join_receipt"])
    panel_seal = read_json(paths["panel_seal"])
    firewall = read_json(paths["panel_firewall"])
    panel_tree = read_json(paths["panel_hash_tree"])
    training_seal = read_json(paths["training_seal"])
    checkpoint_tree = read_json(paths["checkpoint_tree"])
    first_opening = read_json(paths["first_opening"])
    original_disposition = read_json(paths["original_disposition"])
    analysis_contract = read_json(paths["analysis_contract"])

    if e1_seal.get("status") != "E1_CANDIDATE_BASIS_AND_TARGET_FREE_JOIN_SEALED":
        raise RuntimeError("E1 candidate-basis seal is not in its promotable sealed state")
    if e1_seal.get("original_phase_b_status") != "EVALUATION_INPUT_CONTRACT_INCOMPLETE":
        raise RuntimeError("original Phase-B disposition drifted")
    if e1_seal.get("candidate_count") != 16 or e1_seal.get("feature_shape") != [16, 2048]:
        raise RuntimeError("E1 candidate basis shape/count mismatch")
    if e1_seal.get("repeat_max_absolute_error") != 0.0 or e1_seal.get("neighborhoods_resolved") != 2000:
        raise RuntimeError("E1 extraction repeat or target-free join is not a full pass")
    if e1_seal.get("predictions_or_metrics") is not False:
        raise RuntimeError("E1 basis seal claims behavioral data already exist")
    if join_receipt.get("status") != "PASS_TARGET_FREE_EXACT_IDENTITY_JOIN_2000_OF_2000" or join_receipt.get("neighborhoods_joined") != 2000:
        raise RuntimeError("E1 target-free join receipt is not a full pass")
    if join_receipt.get("heldout_targets_decoded_or_used") is not False or join_receipt.get("head_inference") is not False:
        raise RuntimeError("E1 target-free join crossed its declared boundary")
    if panel_seal.get("status") != "V08N_HELDOUT_MATCHED_PANEL_SEALED_PHASE_B_GATE_PASS" or panel_seal.get("panel_locked") is not True:
        raise RuntimeError("held-out panel seal or firewall pre-opening state mismatch")
    if firewall.get("body_access_granted") is not False or firewall.get("evaluation_process_may_read_panel") is not False:
        raise RuntimeError("original evaluation firewall state changed")
    if first_opening.get("opening_count") != 1 or first_opening.get("status") != "HELDOUT_PANEL_UNLOCKED_ONCE_AFTER_TRAINING_SEAL":
        raise RuntimeError("first opening receipt is not the recorded failed opening")
    if training_seal.get("status") != "ALL_NINE_RUNS_TRAINED_SEALED_UNEVALUATED" or training_seal.get("run_count") != 9 or training_seal.get("checkpoint_count") != 27:
        raise RuntimeError("training seal identity/count mismatch")
    if checkpoint_tree.get("entry_count") != 81 or checkpoint_tree.get("checkpoint_count") != 27:
        raise RuntimeError("training hash tree cardinality mismatch")
    if original_disposition.get("status") != "EVALUATION_INPUT_CONTRACT_INCOMPLETE":
        raise RuntimeError("original Phase-B final disposition is not the required incomplete state")
    if analysis_contract.get("sensitivity_guard_and_claim_rules", {}).get("absolute_sensitivity_floor", {}).get("minimum_per_seed") != 0.37:
        raise RuntimeError("frozen 0.37 strict-transition floor drifted")
    if analysis_contract.get("reporting", {}).get("newtight") is not False:
        raise RuntimeError("analysis contract unexpectedly includes NewTight")

    # Verify every byte-level run artifact without deserializing any checkpoint.
    tree_entries = checkpoint_tree.get("entries", [])
    if len(tree_entries) != 81:
        raise RuntimeError("checkpoint tree does not contain all 81 sealed entries")
    for item in tree_entries:
        path = Path(item["path"])
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"training artifact hash-tree mismatch: {path}")
    if tree_entries != training_seal.get("hash_tree_entries"):
        raise RuntimeError("training seal and detached checkpoint tree entries differ")

    # Verify the 9 exact terminal identities from metadata and the sealed byte tree.
    terminal_hashes: dict[str, str] = {}
    terminal_state_hashes: dict[str, str] = {}
    for item in training_seal.get("runs", []):
        seed, arm = int(item["seed"]), str(item["arm"])
        if seed not in SEEDS or arm not in ARMS or item.get("status") != "TRAINING_COMPLETE_UNEVALUATED":
            raise RuntimeError(f"unexpected terminal run identity/status: {seed}/{arm}")
        terminal = RUN / "runs" / f"seed-{seed}" / arm / "epoch-3-terminal.pt"
        tree_entry = next((entry for entry in tree_entries if Path(entry["path"]).resolve() == terminal.resolve()), None)
        if tree_entry is None:
            raise RuntimeError(f"terminal checkpoint is not separately bound in the hash tree: {seed}/{arm}")
        actual = sha256_file(terminal)
        if actual != tree_entry["sha256"]:
            raise RuntimeError(f"terminal checkpoint file digest differs from hash tree: {seed}/{arm}")
        integrity = read_json(terminal.parent / "run-integrity.json")
        if integrity.get("terminal_head_sha256") != item.get("terminal_head_sha256"):
            raise RuntimeError(f"terminal head-state digest differs across training receipts: {seed}/{arm}")
        terminal_hashes[f"{seed}/{arm}"] = actual
        terminal_state_hashes[f"{seed}/{arm}"] = str(item["terminal_head_sha256"])
    if len(terminal_hashes) != 9:
        raise RuntimeError("training seal does not bind exactly nine terminal heads")

    if torch.__version__ != "2.11.0+cu128" or not torch.cuda.is_available():
        raise RuntimeError("frozen inference runtime is unavailable or changed")
    gpu_name = torch.cuda.get_device_name(0)
    if gpu_name != "NVIDIA GeForce RTX 3080":
        raise RuntimeError(f"inference device identity mismatch: {gpu_name}")
    if torch.backends.cuda.matmul.allow_tf32 is not False:
        raise RuntimeError("matmul TF32 setting drifted from the frozen runtime")

    runtime = {
        "python": platform.python_version(), "torch": torch.__version__,
        "numpy": np.__version__, "cuda": torch.version.cuda,
        "cudnn": torch.backends.cudnn.version(), "device_identity": gpu_name,
        "runtime_device_locator": DEVICE,
        "matmul_tf32": torch.backends.cuda.matmul.allow_tf32,
        "cudnn_tf32": torch.backends.cudnn.allow_tf32,
        "deterministic_algorithms": torch.are_deterministic_algorithms_enabled(),
    }
    return {
        "status": "PREINFERENCE_IDENTITIES_AND_CHECKPOINT_BYTES_PASS",
        "verified_sha256": verified,
        "training_hash_tree_entries_rehashed": len(tree_entries),
        "terminal_heads": terminal_hashes,
        "terminal_head_state_digests": terminal_state_hashes,
        "panel_tree_manifest_sha256": verified["panel_hash_tree"],
        "panel_tree_entry_names": sorted(panel_tree),
        "original_opening_count": 1,
        "original_disposition": original_disposition["status"],
        "runtime": runtime,
        "head_payloads_deserialized": False,
        "heldout_panel_bodies_or_targets_read": False,
    }


def record_second_opening(preflight: dict[str, Any]) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(OUTPUT / "preinference-verification-v01.json", preflight)
    receipt = {
        "status": "E1_SECOND_HELDOUT_OPENING_AUTHORIZED_AND_RECORDED",
        "identity": IDENTITY,
        "opening_count": 2,
        "opening_1_receipt_sha256": EXPECTED["first_opening"],
        "original_phase_b_disposition": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
        "authorization_source": "explicit user authorization in the active conversation",
        "authorized_operations": ["E1 held-out panel read", "exact nine terminal-head loads", "frozen E1 inference", "frozen analysis"],
        "e1_candidate_basis_seal_sha256": EXPECTED["e1_basis_seal"],
        "e1_join_receipt_sha256": EXPECTED["e1_join_receipt"],
        "e1_join_manifest_sha256": EXPECTED["e1_join_manifest"],
        "heldout_panel_seal_sha256": EXPECTED["panel_seal"],
        "heldout_panel_hash_tree_sha256": EXPECTED["panel_hash_tree"],
        "training_seal_sha256": EXPECTED["training_seal"],
        "checkpoint_hash_tree_sha256": EXPECTED["checkpoint_tree"],
        "analysis_contract_sha256": EXPECTED["analysis_contract"],
        "metric_implementation_sha256": {
            "frozen_evaluator": EXPECTED["frozen_evaluator"],
            "v08n_analyzer": EXPECTED["v08n_analyzer"],
            "reference_metric": EXPECTED["reference_metric"],
            "probe": EXPECTED["probe"],
        },
        "runner_source_sha256": sha256_file(Path(__file__)),
        "runtime": preflight["runtime"],
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        "predictions_or_metrics_exist_at_opening": False,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json_exclusive(OUTPUT / "e1-second-opening-receipt-v01.json", receipt)


def verify_opened_panel() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]], torch.Tensor, torch.Tensor, dict[str, int], dict[str, list[str]], dict[str, Any]]:
    panel_tree = read_json(PANEL / "seal/heldout-panel-hash-tree.json")
    paths = {
        "semantic_scope": PANEL / "semantic-scope/heldout-feature-scope.jsonl",
        "neighborhood_identities": PANEL / "semantic-scope/heldout-neighborhoods.jsonl",
        "panel_manifest": PANEL / "matched-panel-v02/heldout-matched-panel-manifest.jsonl",
        "selected": PANEL / "matched-panel-v02/selected-heldout-matched-neutral.jsonl",
        "feature_cache_receipt": PANEL / "feature-cache/heldout-feature-cache-receipt.json",
        "feature_tensor": PANEL / "feature-cache/heldout-features.pt",
    }
    for name, path in paths.items():
        expected = EXPECTED["neighborhood_identities"] if name == "neighborhood_identities" else panel_tree[name]
        if sha256_file(path) != expected:
            raise RuntimeError(f"opened panel artifact hash mismatch: {name}")

    scope_rows = read_jsonl(paths["semantic_scope"])
    neighborhood_rows = read_jsonl(paths["neighborhood_identities"])
    panel_rows = read_jsonl(paths["panel_manifest"])
    selected_rows = read_jsonl(paths["selected"])
    if (len(scope_rows), len(neighborhood_rows), len(panel_rows), len(selected_rows)) != (22_000, 2_000, 2_000, 2_000):
        raise RuntimeError("sealed panel record counts do not match the contract")

    feature_receipt = read_json(paths["feature_cache_receipt"])
    feature_pack = torch.load(paths["feature_tensor"], map_location="cpu", weights_only=True)
    eval_features = feature_pack["features"]
    if tuple(eval_features.shape) != (22_000, 2048) or eval_features.dtype != torch.float32:
        raise RuntimeError("held-out state feature tensor shape/dtype mismatch")
    if tensor_sha256(eval_features) != feature_receipt["feature_tensor"]["tensor_sha256"]:
        raise RuntimeError("held-out state feature tensor content digest mismatch")
    if any(row.get("index") != index for index, row in enumerate(scope_rows)):
        raise RuntimeError("held-out feature-scope ordering mismatch")

    scope_by_neighborhood: dict[str, dict[str, dict[str, Any]]] = {}
    for row in scope_rows:
        scope_by_neighborhood.setdefault(str(row["neighborhood_id"]), {})[str(row["episode_id"])] = row
    if len(scope_by_neighborhood) != 2_000 or any(len(items) != 11 for items in scope_by_neighborhood.values()):
        raise RuntimeError("held-out neighborhood feature-scope join is not 2,000 x 11")
    neighborhoods = {str(row["anchor_id"]): row for row in neighborhood_rows}
    panels = {str(row["neighborhood_id"]): row for row in panel_rows}
    selected_by_id = {str(row["neighborhood_id"]): row for row in selected_rows}
    if len(neighborhoods) != 2_000 or len(panels) != 2_000 or len(selected_by_id) != 2_000:
        raise RuntimeError("duplicate held-out neighborhood identity")
    if set(neighborhoods) != set(panels) or set(panels) != set(selected_by_id) or set(panels) != set(scope_by_neighborhood):
        raise RuntimeError("panel, selection, neighborhood, and feature-scope identities do not reconcile")
    family_counts: dict[str, int] = {}
    for nid, panel in panels.items():
        selected = selected_by_id[nid]
        for key in ("anchor_episode_id", "fact_episode_id", "sham_episode_id", "matched_neutral_episode_id"):
            if str(panel[key]) != str(selected[key]):
                raise RuntimeError(f"sealed selected-view identity mismatch: {nid}/{key}")
        family = str(panel["family_id"]).split(":")[-1]
        family_counts[family] = family_counts.get(family, 0) + 1
    if family_counts != {"exposure_control": 500, "respiratory_monitoring": 500, "salinity_control": 500, "vibration_monitoring": 500}:
        raise RuntimeError(f"held-out family counts differ from seal: {family_counts}")

    join_rows = read_jsonl(E1 / "target-free-schema-candidate-join-v01.jsonl")
    if len(join_rows) != 2_000 or {str(row["neighborhood_id"]) for row in join_rows} != set(panels):
        raise RuntimeError("E1 join rows do not cover the sealed panel identities exactly")
    schema_ids: dict[str, list[str]] = {}
    schema_full_ids: dict[str, str] = {}
    candidate_index: dict[str, int] = {}
    row_hashes: dict[int, str] = {}
    join_by_neighborhood: dict[str, dict[str, Any]] = {}
    for row in join_rows:
        neighborhood_id = str(row["neighborhood_id"])
        if neighborhood_id in join_by_neighborhood:
            raise RuntimeError(f"duplicate E1 join identity: {neighborhood_id}")
        join_by_neighborhood[neighborhood_id] = row
        full_schema = str(row["schema_family_id"])
        slug = full_schema.split(":")[-1]
        ids = [str(value) for value in row["candidate_semantic_ids"]]
        feature_rows = row["candidate_feature_rows"]
        if len(ids) != 4 or len(set(ids)) != 4 or len(feature_rows) != 4:
            raise RuntimeError(f"E1 exact candidate join is not four unique identities: {row['neighborhood_id']}")
        if [str(candidate["candidate_semantic_id"]) for candidate in feature_rows] != ids:
            raise RuntimeError(f"E1 explicit feature bindings do not preserve the sealed semantic order: {neighborhood_id}")
        if slug in schema_ids and (schema_ids[slug] != ids or schema_full_ids[slug] != full_schema):
            raise RuntimeError(f"E1 candidate order is inconsistent within schema {slug}")
        schema_ids[slug], schema_full_ids[slug] = ids, full_schema
        for candidate in feature_rows:
            cid = str(candidate["candidate_semantic_id"])
            index = int(candidate["feature_row_index"])
            if cid not in ids or index < 0 or index >= 16:
                raise RuntimeError(f"invalid explicit E1 feature-row binding: {cid}/{index}")
            if cid in candidate_index and candidate_index[cid] != index:
                raise RuntimeError(f"candidate identity has multiple feature rows: {cid}")
            if index in row_hashes and row_hashes[index] != str(candidate["feature_sha256"]):
                raise RuntimeError(f"E1 feature row has conflicting candidate digests: {index}")
            candidate_index[cid] = index
            row_hashes[index] = str(candidate["feature_sha256"])
    if set(schema_ids) != {"exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring"}:
        raise RuntimeError("E1 schema map does not contain exactly the four sealed schemas")
    if len(candidate_index) != 16 or set(row_hashes) != set(range(16)):
        raise RuntimeError("E1 candidate feature map does not cover exactly 16 rows")

    candidate_features = torch.load(E1 / "feature-cache/heldout-candidate-features.pt", map_location="cpu", weights_only=True)
    if not isinstance(candidate_features, torch.Tensor) or tuple(candidate_features.shape) != (16, 2048) or candidate_features.dtype != torch.float32:
        raise RuntimeError("sealed E1 candidate feature tensor shape/dtype mismatch")
    if tensor_sha256(candidate_features) != EXPECTED["e1_tensor_content"]:
        raise RuntimeError("sealed E1 candidate feature tensor content mismatch")
    for index, expected_digest in row_hashes.items():
        if tensor_sha256(candidate_features[index]) != expected_digest:
            raise RuntimeError(f"candidate semantic identity does not match its sealed feature row: {index}")

    # Validate all target/view joins and unique gold MAPs before loading a head.
    for nid, panel in panels.items():
        joined = join_by_neighborhood[nid]
        if str(joined["schema_family_id"]) != str(neighborhoods[nid]["schema_family_id"]):
            raise RuntimeError(f"E1 candidate join schema differs from authoritative held-out schema: {nid}")
        episode_map = scope_by_neighborhood[nid]
        wanted = {"anchor": panel["anchor_episode_id"], "fact_flip": panel["fact_episode_id"],
                  "sham": panel["sham_episode_id"], "matched_neutral": panel["matched_neutral_episode_id"]}
        slug = str(neighborhoods[nid]["schema_family_id"]).split(":")[-1]
        ids = schema_ids[slug]
        targets: dict[str, list[float]] = {}
        for view, episode_id in wanted.items():
            item = episode_map.get(str(episode_id))
            if item is None:
                raise RuntimeError(f"selected view is absent from sealed feature scope: {nid}/{view}")
            if item.get("partition") != "eval":
                raise RuntimeError(f"non-evaluation row in held-out scope: {nid}/{view}")
            target = [float(value) for value in item["target"]]
            if len(target) != 4 or abs(sum(target) - 1.0) > 1e-12:
                raise RuntimeError(f"invalid held-out target vector: {nid}/{view}")
            if max(target) - sorted(target)[-2] <= 0:
                raise RuntimeError(f"gold MAP tie conflicts with frozen metric alignment: {nid}/{view}")
            targets[view] = target
        if max(abs(a - b) for a, b in zip(targets["anchor"], targets["sham"])) > 1e-12:
            raise RuntimeError(f"sham exact target differs from anchor: {nid}")
        if max(abs(a - b) for a, b in zip(targets["anchor"], targets["matched_neutral"])) > 1e-12:
            raise RuntimeError(f"matched-neutral exact target differs from anchor: {nid}")
        if int(np.argmax(targets["anchor"])) == int(np.argmax(targets["fact_flip"])):
            raise RuntimeError(f"fact-flip target does not change MAP winner: {nid}")

    return panel_rows, scope_by_neighborhood, neighborhoods, eval_features, candidate_features, candidate_index, schema_ids, {
        "scope_rows": len(scope_rows), "neighborhoods": len(panel_rows), "schema_family_counts": family_counts,
        "candidate_features": [16, 2048], "candidate_identity_count": len(candidate_index),
        "exact_view_target_preflight": "PASS", "gold_map_ties": 0,
        "panel_artifact_hashes": {name: sha256_file(path) for name, path in paths.items()},
    }


def write_jsonl_exclusive(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def execute() -> None:
    preflight = static_preflight()
    record_second_opening(preflight)
    stage = "opened_panel_input_validation"
    try:
        panel_rows, scope, neighborhoods, eval_features, candidate_features, candidate_index, schema_ids, panel_audit = verify_opened_panel()
        write_json_exclusive(OUTPUT / "opened-panel-validation-v01.json", {
            "status": "E1_OPENED_PANEL_INPUTS_AND_ALL_SCHEMA_JOINS_PASS",
            "opening_receipt_sha256": sha256_file(OUTPUT / "e1-second-opening-receipt-v01.json"),
            **panel_audit,
        })

        stage = "terminal_head_inference"
        device = torch.device(DEVICE)
        eval_features = eval_features.to(device)
        candidate_features = candidate_features.to(device)
        evaluator = import_module(PHASE / "evaluate_phase_b_v01.py", "jev_e1_frozen_evaluator")
        probe = import_module(ROOT / "experiments/jev-frozen-readout-v01/probe.py", "jev_e1_frozen_probe")
        analysis_contract = read_json(PHASE / "phase-b-analysis-contract-v01.json")
        predictions_path = OUTPUT / "raw-predictions-v01.jsonl"
        diagnostics_path = OUTPUT / "geometry-and-surface-diagnostics-v01.jsonl"
        if predictions_path.exists() or diagnostics_path.exists():
            raise FileExistsError("E1 raw output exists; refusing to resume/repeat inference")

        all_diagnostics: list[dict[str, Any]] = []
        started = time.perf_counter()
        prediction_count = 0
        with predictions_path.open("x", encoding="utf-8", newline="\n") as stream:
            for seed in SEEDS:
                for arm in ARMS:
                    checkpoint_path = RUN / "runs" / f"seed-{seed}" / arm / "epoch-3-terminal.pt"
                    checkpoint_entry = next(item for item in preflight["terminal_heads"].items() if item[0] == f"{seed}/{arm}")
                    if sha256_file(checkpoint_path) != checkpoint_entry[1]:
                        raise RuntimeError(f"terminal head changed after preflight: {seed}/{arm}")
                    checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
                    if checkpoint.get("seed") != seed or checkpoint.get("arm") != arm or checkpoint.get("epoch") != 3:
                        raise RuntimeError(f"loaded terminal identity mismatch: {seed}/{arm}")
                    if state_digest(checkpoint["head_state"]) != preflight["terminal_head_state_digests"][f"{seed}/{arm}"]:
                        raise RuntimeError(f"loaded terminal state digest mismatch: {seed}/{arm}")
                    head = probe.CompatibilityHead(2048, "mlp", 128).to(device)
                    head.load_state_dict(checkpoint["head_state"], strict=True)
                    predictions, diagnostics = evaluator.metrics_for_run(
                        seed, arm, head, panel_rows, scope, neighborhoods, eval_features,
                        candidate_features, candidate_index, schema_ids, DEVICE,
                    )
                    if len(predictions) != 8_000 or len(diagnostics) != 2_000:
                        raise RuntimeError(f"unexpected output count for {seed}/{arm}")
                    for row in predictions:
                        pred = row["prediction"]
                        if len(pred) != 4 or not np.isfinite(np.asarray(pred, dtype=np.float64)).all() or abs(sum(pred) - 1.0) > 1e-6:
                            raise RuntimeError(f"invalid model output vector in {seed}/{arm}")
                        stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                    prediction_count += len(predictions)
                    all_diagnostics.extend(diagnostics)
                    print(json.dumps({"event": "E1_arm_predictions_written", "seed": seed, "arm": arm,
                                      "rows": len(predictions), "total_rows": prediction_count,
                                      "elapsed_seconds": round(time.perf_counter() - started, 2)}, separators=(",", ":")), flush=True)
                    del head, checkpoint, predictions, diagnostics
        if prediction_count != 72_000 or len(all_diagnostics) != 18_000:
            raise RuntimeError(f"incomplete E1 matrix: predictions={prediction_count}; diagnostics={len(all_diagnostics)}")
        write_jsonl_exclusive(diagnostics_path, all_diagnostics)
        prediction_hash = sha256_file(predictions_path)
        diagnostics_hash = sha256_file(diagnostics_path)
        prediction_tree = {
            "status": "E1_COMPLETE_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS",
            "identity": IDENTITY,
            "prediction_rows": prediction_count,
            "diagnostic_rows": len(all_diagnostics),
            "files": {
                predictions_path.name: {"sha256": prediction_hash, "bytes": predictions_path.stat().st_size},
                diagnostics_path.name: {"sha256": diagnostics_hash, "bytes": diagnostics_path.stat().st_size},
            },
            "seed_arm_cells": [f"{seed}/{arm}" for seed in SEEDS for arm in ARMS],
            "checkpoint_sha256": preflight["terminal_heads"],
            "panel_opening_receipt_sha256": sha256_file(OUTPUT / "e1-second-opening-receipt-v01.json"),
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_exclusive(OUTPUT / "raw-prediction-hash-tree-v01.json", prediction_tree)
        inference_receipt = {
            "status": "E1_FULL_9_HEAD_RESPONSE_MATRIX_COMPLETE_PREDICTIONS_SEALED",
            "identity": IDENTITY,
            "opening_count": 2,
            "e1_candidate_basis_seal_sha256": EXPECTED["e1_basis_seal"],
            "join_manifest_sha256": EXPECTED["e1_join_manifest"],
            "heldout_panel_seal_sha256": EXPECTED["panel_seal"],
            "training_seal_sha256": EXPECTED["training_seal"],
            "checkpoint_hash_tree_sha256": EXPECTED["checkpoint_tree"],
            "analysis_contract_sha256": EXPECTED["analysis_contract"],
            "prediction_hash_tree_sha256": sha256_file(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "prediction_sha256": prediction_hash, "prediction_rows": prediction_count,
            "terminal_epoch_only": True, "checkpoint_selection": False,
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "elapsed_seconds": time.perf_counter() - started,
        }
        write_json_exclusive(OUTPUT / "e1-inference-receipt-v01.json", inference_receipt)
        print(json.dumps({"event": "E1_RAW_PREDICTIONS_SEALED", "rows": prediction_count,
                          "prediction_sha256": prediction_hash,
                          "hash_tree_sha256": inference_receipt["prediction_hash_tree_sha256"]}, separators=(",", ":")), flush=True)

        # The first analysis call occurs strictly after the complete raw file and hash tree are sealed.
        stage = "frozen_analysis"
        analyzer = import_module(PHASE / "analyze_phase_b_v01.py", "jev_e1_frozen_analyzer")
        prediction_rows = read_jsonl(predictions_path)
        if len(prediction_rows) != 72_000:
            raise RuntimeError("sealed E1 prediction file count changed before analysis")
        frozen_result = analyzer.analyze(prediction_rows, analysis_contract)
        result = {
            "identity": IDENTITY,
            "status": "POSTREGISTERED_E1_ANALYSIS_COMPLETE",
            "original_phase_b_disposition": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
            "e1_repair_contract_sha256": EXPECTED["e1_contract"],
            "opening_receipt_sha256": sha256_file(OUTPUT / "e1-second-opening-receipt-v01.json"),
            "inference_receipt_sha256": sha256_file(OUTPUT / "e1-inference-receipt-v01.json"),
            "raw_prediction_hash_tree_sha256": sha256_file(OUTPUT / "raw-prediction-hash-tree-v01.json"),
            "analysis_implementation_sha256": EXPECTED["v08n_analyzer"],
            "analysis": frozen_result,
            "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        }
        result_path = OUTPUT / "e1-analysis-v01.json"
        write_json_exclusive(result_path, result)
        seal = {
            "status": "POSTREGISTERED_E1_RESULT_SEALED",
            "identity": IDENTITY,
            "original_phase_b_disposition": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
            "files": {
                name: {"sha256": sha256_file(OUTPUT / name), "bytes": (OUTPUT / name).stat().st_size}
                for name in (
                    "preinference-verification-v01.json", "e1-second-opening-receipt-v01.json",
                    "opened-panel-validation-v01.json", "raw-predictions-v01.jsonl",
                    "geometry-and-surface-diagnostics-v01.jsonl", "raw-prediction-hash-tree-v01.json",
                    "e1-inference-receipt-v01.json", "e1-analysis-v01.json",
                )
            },
            "prediction_rows": prediction_count,
            "analysis_contract_sha256": EXPECTED["analysis_contract"],
            "opening_count": 2, "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        write_json_exclusive(OUTPUT / "e1-result-seal-v01.json", seal)
        print(json.dumps({"event": "E1_RESULT_SEALED", "result_sha256": sha256_file(result_path),
                          "seal_sha256": sha256_file(OUTPUT / "e1-result-seal-v01.json"),
                          "primary_gate": frozen_result["primary_gate"]["localized_radius_control_support"]}, separators=(",", ":")), flush=True)
    except Exception as exc:
        failure = {
            "status": "E1_FAILED_CLOSED_PARTIAL_ARTIFACTS_PRESERVED",
            "identity": IDENTITY, "stage": stage, "exception_type": type(exc).__name__,
            "exception": str(exc), "opening_receipt_sha256": sha256_file(OUTPUT / "e1-second-opening-receipt-v01.json"),
            "prediction_file_exists": (OUTPUT / "raw-predictions-v01.jsonl").exists(),
            "prediction_file_sha256": sha256_file(OUTPUT / "raw-predictions-v01.jsonl") if (OUTPUT / "raw-predictions-v01.jsonl").exists() else None,
            "automatic_retry": False, "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
            "failed_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        failure_path = OUTPUT / "failure-disposition-v01.json"
        if not failure_path.exists():
            write_json_exclusive(failure_path, failure)
        raise


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true", help="verify identities and checkpoint bytes without opening the panel")
    parser.add_argument("--execute-authorized-e1", action="store_true", help="record opening 2 and run the explicitly authorized E1 evaluation")
    args = parser.parse_args()
    if args.preflight_only == args.execute_authorized_e1:
        parser.error("choose exactly one of --preflight-only or --execute-authorized-e1")
    if args.preflight_only:
        print(json.dumps(static_preflight(), indent=2, ensure_ascii=False))
        return 0
    execute()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
