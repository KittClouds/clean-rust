#!/usr/bin/env python3
"""Fit the V04-world /256 continuation-value head from frozen V04 rollouts."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import random
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

PROPOSAL_DIR = Path(__file__).resolve().parents[1]
V02_DIR = PROPOSAL_DIR / "v02"
V04_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROPOSAL_DIR))
sys.path.insert(0, str(V02_DIR))
sys.path.insert(0, str(V04_DIR))

from feature_math import load_feature_store, read_jsonl, sha256_file  # noqa: E402
from v02.value_training import ValueModel, binary_metrics, predict_value  # noqa: E402
import vreach_requests as REQUESTS  # noqa: E402

REFIT_PATH = V04_DIR / "refit_vreach.py"
REFIT_SPEC = importlib.util.spec_from_file_location("r1_v04_vreach_refit_v07_shared", REFIT_PATH)
if REFIT_SPEC is None or REFIT_SPEC.loader is None:
    raise ImportError(f"could not load V07 refit validation helpers from {REFIT_PATH}")
REFIT = importlib.util.module_from_spec(REFIT_SPEC)
sys.modules[REFIT_SPEC.name] = REFIT
REFIT_SPEC.loader.exec_module(REFIT)

HELPERS_PATH = V02_DIR / "vreach_scaled_refit_v01.py"
SPEC = importlib.util.spec_from_file_location("r1_v04_vreach_refit_helpers", HELPERS_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"could not load fit helpers from {HELPERS_PATH}")
HELPERS = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = HELPERS
SPEC.loader.exec_module(HELPERS)

PIPELINE_PATH = V02_DIR / "train_pipeline.py"
INPUT_DIM = 4345
HIDDEN = 32
H_DIM = 2048
MAX_BUDGET = 256
OUTPUT_VERSION = "v07_runtime_v01"
WEIGHTS_NAME = "v-reach-weights-v07-runtime-v01.json"
HISTORY_NAME = "training-history-v07-runtime-v01.json"
RECEIPT_NAME = "vreach-runtime-refit-receipt-v01.json"
RUNTIME_PROPOSAL_RECEIPT_SCHEMA = "FAS_R1_PROPOSAL_RUNTIME_FIT_V01"
RUNTIME_PROPOSAL_RECEIPT_STATUS = "R1_RUNTIME_PROPOSAL_FIT_COMPLETE"
TEMPERATURE_CALIBRATION_SCHEMA = "FAS_R1_RUNTIME_TEMPERATURE_CALIBRATION_V01"
TEMPERATURE_ENGINEERING_OVERRIDE_SCHEMA = "FAS_R1_RUNTIME_TEMPERATURE_ENGINEERING_OVERRIDE_V01"
ENGINEERING_OVERRIDE_PROPOSAL_SHA256 = "748ceb3d527408b06b7cb46b101c73e2609a7c13e7fd78dcde589fb9914c93d4"
ENGINEERING_OVERRIDE_SELECTED_TEMPERATURE = 0.17864354564164298
ENGINEERING_OVERRIDE_TEMPERATURE_BITS_LE_HEX = "3c0f16adcaddc63f"
V03_SIMULATOR_RECEIPT_SCHEMA = "R1_VREACH_SIMULATOR_RECEIPT_V03"
V03_LABEL_SCHEMA = "r1-v-reach-label-dataset-v03"
V03_STATE_SCHEMA = "r1-v-reach-rollout-label-v03"
V03_IDENTITY_SCHEMA = "r1-vreach-policy-identity-v03"
V03_MIXTURE_ID = "incidence_masked_norm_4"
V03_SIMULATOR_VERSION = "r1-vreach-simulator-v03"
POLICY_IDENTITY_PREFIX = b"FAS_R1_VREACH_POLICY_IDENTITY_V03\0"
POLICY_IDENTITY_SOURCE_FILES = {
    "simulator_core": Path("proposal/src/simulator_v03.rs"),
    "simulator_cli": Path("proposal/src/bin/r1_proposal_data_v03.rs"),
    "simulator_util": Path("proposal/src/simulator_v03/util.rs"),
    "simulator_policy": Path("proposal/src/simulator_v03/policy.rs"),
    "rollout_engine": Path("proposal/src/rollout.rs"),
    "runtime_mixture": Path("search/src/inference_v02.rs"),
    "runtime_action_delta": Path("search/src/terminal.rs"),
    "runtime_sampler": Path("search/src/policy.rs"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--world-dir", type=Path, required=True)
    parser.add_argument("--sensor-dir", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--traces", type=Path, required=True)
    parser.add_argument("--label-receipt", type=Path, required=True)
    parser.add_argument("--start-states", type=Path, required=True)
    parser.add_argument("--request-receipt", type=Path, required=True)
    parser.add_argument("--proposal-sha256", required=True)
    parser.add_argument("--policy-identity-sha256", required=True)
    parser.add_argument("--proposal-weights", type=Path, required=True)
    parser.add_argument("--runtime-proposal-receipt", type=Path, required=True)
    temperature_group = parser.add_mutually_exclusive_group(required=True)
    temperature_group.add_argument("--temperature-calibration", type=Path)
    temperature_group.add_argument("--temperature-override", type=Path)
    parser.add_argument("--baseline-weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--h-scale", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260926)
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    return parser.parse_args()


def sha(path: Path) -> str:
    return sha256_file(path.resolve(strict=True))[0]


def file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    digest, size = sha256_file(resolved)
    return {"path": str(resolved), "sha256": digest, "bytes": size}


def canonical_path_key(value: str | Path) -> str:
    raw = os.fspath(value)
    folded = raw.casefold()
    if folded.startswith("\\\\?\\unc\\"):
        raw = "\\\\" + raw[8:]
    elif folded.startswith("\\\\?\\"):
        raw = raw[4:]
    try:
        resolved = str(Path(raw).resolve(strict=False))
    except (OSError, RuntimeError):
        resolved = os.path.normpath(raw)
    return os.path.normcase(os.path.normpath(resolved))


def _require_file_record(record: Any, path: Path, label: str) -> dict[str, Any]:
    observed = file_record(path)
    if not isinstance(record, dict):
        raise ValueError(f"receipt is missing the {label} file record")
    if record.get("sha256") != observed["sha256"] or record.get("bytes") != observed["bytes"]:
        raise ValueError(f"{label} differs from receipt hash or byte count")
    receipt_path = record.get("path")
    if not isinstance(receipt_path, str) or canonical_path_key(receipt_path) != canonical_path_key(
        observed["path"]
    ):
        raise ValueError(f"{label} path differs from receipt")
    return observed


def _valid_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        character not in "0123456789abcdefABCDEF" for character in value
    ):
        raise ValueError(f"{label} must be a 64-character hexadecimal SHA-256")
    return value.lower()


def _policy_identity_digest(
    weights_sha256: str,
    mixture_id: str,
    temperature: float,
    simulator_version: str,
    source_sha256: dict[str, str],
) -> str:
    digest = hashlib.sha256()
    digest.update(POLICY_IDENTITY_PREFIX)
    digest.update(bytes.fromhex(weights_sha256))
    digest.update(len(mixture_id.encode("utf-8")).to_bytes(8, "little"))
    digest.update(mixture_id.encode("utf-8"))
    digest.update(struct.pack("<d", temperature))
    digest.update(simulator_version.encode("utf-8"))
    for name in POLICY_IDENTITY_SOURCE_FILES:
        digest.update(bytes.fromhex(source_sha256[name]))
    return digest.hexdigest()


def _expected_policy_source_hashes() -> dict[str, str]:
    stage1_dir = PROPOSAL_DIR.parent
    return {
        name: sha(stage1_dir / relative_path)
        for name, relative_path in POLICY_IDENTITY_SOURCE_FILES.items()
    }


def validate_policy_identity(
    identity: Any,
    proposal_weights_sha256: str,
    selected_temperature: float,
    expected_policy_identity_sha256: str,
    expected_source_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(identity, dict) or identity.get("schema") != V03_IDENTITY_SCHEMA:
        raise ValueError("V03 simulator receipt has an unsupported policy identity schema")
    if identity.get("weights_sha256") != proposal_weights_sha256:
        raise ValueError("V03 policy identity weights SHA differs from current proposal weights")
    if identity.get("mixture_id") != V03_MIXTURE_ID:
        raise ValueError("V03 policy identity does not use incidence_masked_norm_4")
    if identity.get("simulator_version") != V03_SIMULATOR_VERSION:
        raise ValueError("V03 policy identity has an unexpected simulator version")
    try:
        temperature = float(identity.get("temperature"))
    except (TypeError, ValueError) as error:
        raise ValueError("V03 policy identity temperature is invalid") from error
    if not math.isfinite(temperature) or temperature != selected_temperature:
        raise ValueError("V03 policy identity temperature differs from calibration artifact")
    expected_bits = struct.pack("<d", selected_temperature).hex()
    if identity.get("temperature_f64_bits_le_hex") != expected_bits:
        raise ValueError("V03 policy identity temperature bit pattern differs from calibration")
    source_hashes = identity.get("source_sha256")
    if not isinstance(source_hashes, dict) or set(source_hashes) != set(POLICY_IDENTITY_SOURCE_FILES):
        raise ValueError("V03 policy identity source digest set is incomplete")
    normalized_sources = {
        name: _valid_sha256(source_hashes[name], f"policy source {name}")
        for name in POLICY_IDENTITY_SOURCE_FILES
    }
    if expected_source_hashes is not None and normalized_sources != expected_source_hashes:
        raise ValueError("V03 policy identity source digests differ from the pinned source files")
    calculated = _policy_identity_digest(
        proposal_weights_sha256,
        V03_MIXTURE_ID,
        selected_temperature,
        V03_SIMULATOR_VERSION,
        normalized_sources,
    )
    declared_identity = _valid_sha256(identity.get("sha256"), "V03 policy identity SHA")
    if calculated != declared_identity or calculated != expected_policy_identity_sha256:
        raise ValueError("V03 composite policy identity SHA does not match its components")
    return identity


def validate_temperature_calibration(
    calibration: dict[str, Any],
    runtime_receipt: dict[str, Any],
    calibration_path: Path,
) -> float:
    if calibration.get("schema") != TEMPERATURE_CALIBRATION_SCHEMA:
        raise ValueError("runtime temperature calibration has an unsupported schema")
    if calibration.get("calibration_scope") != "validation one-step teacher-distribution calibration":
        raise ValueError("temperature artifact is not validation one-step teacher-distribution calibration")
    if calibration.get("search_reachability_evidence") is not False:
        raise ValueError("temperature artifact is not marked as non-reachability evidence")
    if calibration.get("qualification_teacher_rows_used") is not False or calibration.get(
        "qualification_labels_or_outcomes_used"
    ) is not False:
        raise ValueError("temperature calibration reports qualification access")
    status = calibration.get("status")
    allowed_statuses = {
        "INTERIOR_OPTIMUM",
        "NONIDENTIFIABLE_FALLBACK_T1",
        "LOWER_BOUNDARY_FALLBACK_T1",
        "UPPER_BOUNDARY_FALLBACK_T1",
    }
    if status not in allowed_statuses:
        raise ValueError("temperature calibration has an unrecognized optimizer status")
    try:
        temperature = float(calibration.get("selected_temperature"))
    except (TypeError, ValueError) as error:
        raise ValueError("temperature calibration selected value is invalid") from error
    if not math.isfinite(temperature) or not 0.05 <= temperature <= 50.0:
        raise ValueError("temperature calibration value is outside the pre-registered bounds")
    if status == "INTERIOR_OPTIMUM":
        try:
            beta = float(calibration.get("selected_inverse_temperature"))
        except (TypeError, ValueError) as error:
            raise ValueError("interior calibration omits selected inverse temperature") from error
        if not math.isfinite(beta) or not math.isclose(beta * temperature, 1.0, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError("temperature and selected inverse temperature are inconsistent")
    elif temperature != 1.0 or calibration.get("fallback_temperature") != 1.0:
        raise ValueError("boundary or nonidentifiable calibration must fall back to T=1")

    binding = runtime_receipt.get("temperature_calibration", {})
    if (
        binding.get("selected_temperature") != temperature
        or binding.get("status") != status
        or binding.get("calibration_scope") != calibration.get("calibration_scope")
        or binding.get("search_reachability_evidence") is not False
    ):
        raise ValueError("runtime fit receipt does not bind the temperature calibration result")
    calibration_record = file_record(calibration_path)
    _require_file_record(
        runtime_receipt.get("output_files", {}).get(calibration_path.name),
        calibration_path,
        "temperature calibration artifact",
    )
    if (
        binding.get("artifact_file") != calibration_path.name
        or binding.get("temperature_sha256") != calibration_record["sha256"]
    ):
        raise ValueError("runtime fit receipt does not bind the supplied temperature artifact")
    return temperature


def validate_temperature_override(
    override: dict[str, Any],
    override_path: Path,
    current_proposal_sha256: str,
) -> float:
    """Validate the disclosed engineering-only qualification temperature override."""
    if not isinstance(override, dict):
        raise ValueError("runtime temperature override must be a JSON object")
    if override.get("schema") != TEMPERATURE_ENGINEERING_OVERRIDE_SCHEMA:
        raise ValueError("runtime temperature override has an unsupported schema")
    if override.get("status") != "COMPLETE":
        raise ValueError("runtime temperature override is not COMPLETE")
    if override.get("mode") != "ADAPTIVE_ENGINEERING":
        raise ValueError("runtime temperature override is not ADAPTIVE_ENGINEERING")
    if override.get("qualification_selection_access") is not True:
        raise ValueError("temperature override must explicitly disclose qualification selection access")
    if override.get("scientific_confirmation_eligible") is not False:
        raise ValueError("temperature override must remain scientifically ineligible")

    observed_proposal_sha256 = _valid_sha256(
        current_proposal_sha256, "current V132 proposal SHA"
    )
    declared_proposal_sha256 = _valid_sha256(
        override.get("proposal_sha256"), "temperature override proposal SHA"
    )
    if (
        observed_proposal_sha256 != ENGINEERING_OVERRIDE_PROPOSAL_SHA256
        or declared_proposal_sha256 != ENGINEERING_OVERRIDE_PROPOSAL_SHA256
        or declared_proposal_sha256 != observed_proposal_sha256
    ):
        raise ValueError("temperature override does not bind the exact current V132 proposal SHA")

    try:
        temperature = float(override.get("selected_temperature"))
    except (TypeError, ValueError) as error:
        raise ValueError("temperature override selected value is invalid") from error
    if (
        not math.isfinite(temperature)
        or temperature != ENGINEERING_OVERRIDE_SELECTED_TEMPERATURE
    ):
        raise ValueError("temperature override selected value differs from the pinned engineering temperature")
    expected_bits = struct.pack("<d", ENGINEERING_OVERRIDE_SELECTED_TEMPERATURE).hex()
    if (
        override.get("selected_temperature_f64_bits_le_hex")
        != ENGINEERING_OVERRIDE_TEMPERATURE_BITS_LE_HEX
        or override.get("selected_temperature_f64_bits_le_hex") != expected_bits
    ):
        raise ValueError("temperature override selected f64 bits differ from the pinned engineering temperature")

    source_lineage = override.get("source_lineage")
    if not isinstance(source_lineage, dict):
        raise ValueError("temperature override is missing qualification source lineage")
    if source_lineage.get("proposal_id") != "V132":
        raise ValueError("temperature override source lineage does not identify V132")
    if source_lineage.get("proposal_sha256") != ENGINEERING_OVERRIDE_PROPOSAL_SHA256:
        raise ValueError("temperature override source lineage does not bind the V132 proposal SHA")
    trial_id = source_lineage.get("qualification_trial_id")
    if not isinstance(trial_id, str) or not trial_id.strip():
        raise ValueError("temperature override source lineage omits the qualification trial ID")
    _valid_sha256(
        source_lineage.get("qualification_trial_receipt_sha256"),
        "qualification trial receipt SHA",
    )
    if source_lineage.get("qualification_trial_design") != "paired-one-salt":
        raise ValueError("temperature override source lineage is not the paired one-salt trial")

    # Resolve the artifact now so a missing or non-file path fails before model fitting.
    override_path.resolve(strict=True)
    return temperature


def validate_runtime_proposal_receipt(
    receipt: dict[str, Any], proposal_weights_path: Path
) -> tuple[str, dict[str, Any]]:
    if (
        receipt.get("schema") != RUNTIME_PROPOSAL_RECEIPT_SCHEMA
        or receipt.get("status") != RUNTIME_PROPOSAL_RECEIPT_STATUS
        or receipt.get("analysis_mode") != "ADAPTIVE_ENGINEERING"
        or receipt.get("scientific_confirmation_eligible") is not False
    ):
        raise ValueError("matched proposal fit receipt is incomplete or has an unsupported schema")
    if receipt.get("runtime_mix", {}).get("name") != V03_MIXTURE_ID:
        raise ValueError("matched proposal fit receipt does not bind incidence_masked_norm_4")
    non_use = receipt.get("qualification_non_use", {})
    for flag in (
        "teacher_rows_used_for_fit",
        "score_rows_used_for_fit",
        "private_labels_or_outcomes_read",
        "features_used_for_fit",
        "metrics_used_for_selection",
        "qualification_embeddings_used_for_fit",
    ):
        if non_use.get(flag) is not False:
            raise ValueError(f"matched proposal receipt does not certify {flag}=false")
    proposal_sha256 = sha(proposal_weights_path)
    weights_record = _require_file_record(
        receipt.get("output_files", {}).get("proposal-weights-runtime-v01.json"),
        proposal_weights_path,
        "matched proposal weights",
    )
    if (
        receipt.get("model", {}).get("output_weights_sha256") != proposal_sha256
        or weights_record["sha256"] != proposal_sha256
    ):
        raise ValueError("runtime fit receipt does not bind the supplied V132 proposal weights")
    weights = REQUESTS.verify_proposal_weights(proposal_weights_path)
    if receipt.get("model", {}).get("architecture") != REQUESTS.PROPOSAL_ARCHITECTURE:
        raise ValueError("runtime fit receipt proposal architecture differs from V02 runtime")
    if receipt.get("model", {}).get("initial_weights_sha256") != receipt.get(
        "input_hashes", {}
    ).get("initial_weights", {}).get("sha256"):
        raise ValueError("runtime fit receipt initial checkpoint lineage is inconsistent")
    return proposal_sha256, weights


def get_request_proposal_sha256(request_receipt: dict[str, Any]) -> str:
    """Return the proposal digest that generated the fixed request/start provenance."""
    proposal_sha256 = _valid_sha256(
        request_receipt.get("proposal", {}).get("weights_sha256"),
        "request/start proposal SHA",
    )
    input_sha = request_receipt.get("inputs", {}).get("proposal_weights", {}).get("sha256")
    if input_sha != proposal_sha256:
        raise ValueError("request receipt proposal digest differs from its recorded proposal input")
    return proposal_sha256


def validate_v03_simulator_receipt(
    receipt: dict[str, Any],
    labels_path: Path,
    traces_path: Path,
    request_path: Path,
    proposal_weights_path: Path,
    proposal_sha256: str,
    policy_identity_sha256: str,
    temperature: float,
    expected_source_hashes: dict[str, str] | None = None,
    expected_tasks: int = REQUESTS.TRAIN_VALIDATION_COUNT,
) -> dict[str, Any]:
    if (
        receipt.get("schema") != V03_SIMULATOR_RECEIPT_SCHEMA
        or receipt.get("status") != "COMPLETE"
        or receipt.get("qualification_access_by_simulator") is not False
    ):
        raise ValueError("V03 simulator receipt is incomplete or reports qualification access")
    identity = validate_policy_identity(
        receipt.get("policy_identity"),
        proposal_sha256,
        temperature,
        policy_identity_sha256,
        expected_source_hashes,
    )
    request_record = _require_file_record(receipt.get("request_file"), request_path, "V03 request file")
    weights_record = _require_file_record(
        receipt.get("proposal_weights_file"), proposal_weights_path, "V03 proposal weights"
    )
    if weights_record["sha256"] != proposal_sha256:
        raise ValueError("V03 simulator receipt proposal file digest differs from raw proposal SHA")
    label_record = _require_file_record(receipt.get("label_file"), labels_path, "V03 label file")
    trace_record = _require_file_record(receipt.get("trace_file"), traces_path, "V03 trace file")
    if receipt.get("task_count") != expected_tasks:
        raise ValueError("V03 label receipt task count is not the train/validation roster size")
    state_count = receipt.get("state_count")
    rollout_count = receipt.get("rollout_count")
    if type(state_count) is not int or state_count <= 0 or type(rollout_count) is not int or rollout_count <= 0:
        raise ValueError("V03 label receipt has invalid state or rollout counts")
    return {
        "policy_identity": identity,
        "request_file": request_record,
        "proposal_weights_file": weights_record,
        "label_file": label_record,
        "trace_file": trace_record,
        "task_count": expected_tasks,
        "state_count": state_count,
        "rollout_count": rollout_count,
    }


def validate_v03_label_rows(
    labels_path: Path,
    expected_tasks: set[str],
    split_by_task: dict[str, str],
    proposal_sha256: str,
    policy_identity_sha256: str,
    policy_identity: dict[str, Any],
    expected_state_count: int,
    expected_rollout_count: int,
) -> dict[str, int]:
    seen: set[str] = set()
    state_count = 0
    rollout_count = 0
    for dataset in REQUESTS.iter_jsonl(labels_path):
        if dataset.get("schema") != V03_LABEL_SCHEMA:
            raise ValueError("V03 V_reach labels have an unexpected dataset schema")
        task_id = dataset.get("task_id")
        split = split_by_task.get(task_id)
        if split == "qualification":
            raise ValueError("qualification V_reach labels entered the runtime refit input")
        if task_id not in expected_tasks or split not in ("train", "validation"):
            raise ValueError(f"V03 V_reach labels contain a non-trainval task {task_id!r}")
        if dataset.get("proposal_sha256") != policy_identity_sha256:
            raise ValueError(f"V03 labels for {task_id} use an unexpected policy identity digest")
        if dataset.get("policy_identity_sha256") != policy_identity_sha256:
            raise ValueError(f"V03 dataset policy identity digest differs for {task_id}")
        if dataset.get("policy_identity") != policy_identity:
            raise ValueError(f"V03 dataset policy identity components differ for {task_id}")
        if policy_identity.get("weights_sha256") != proposal_sha256:
            raise ValueError("V03 policy identity is not bound to current raw proposal weights")
        states = dataset.get("states")
        if not isinstance(states, list) or not states:
            raise ValueError(f"V03 V_reach dataset has no states for {task_id}")
        for state in states:
            if state.get("schema") != V03_STATE_SCHEMA:
                raise ValueError(f"V03 V_reach state has an unexpected schema for {task_id}")
            if state.get("task_id") != task_id:
                raise ValueError(f"V03 state task ID differs from dataset for {task_id}")
            if state.get("proposal_sha256") != policy_identity_sha256 or state.get(
                "policy_identity_sha256"
            ) != policy_identity_sha256:
                raise ValueError(f"V03 state is not bound to the composite policy identity for {task_id}")
            rollouts = state.get("rollouts")
            if not isinstance(rollouts, list) or not rollouts:
                raise ValueError(f"V03 state has no rollout records for {task_id}")
            for rollout in rollouts:
                if rollout.get("proposal_sha256") != policy_identity_sha256 or rollout.get(
                    "policy_identity_sha256"
                ) != policy_identity_sha256:
                    raise ValueError(f"nested V03 rollout identity differs for {task_id}")
            state_count += 1
            rollout_count += len(rollouts)
        if task_id in seen:
            raise ValueError(f"duplicate V03 V_reach dataset for {task_id}")
        seen.add(task_id)
    if seen != expected_tasks:
        raise ValueError(f"V03 labels must cover exactly 80 train/validation tasks; got {len(seen)}")
    if state_count != expected_state_count or rollout_count != expected_rollout_count:
        raise ValueError("V03 label row totals differ from simulator receipt")
    return {"task_count": len(seen), "state_count": state_count, "rollout_count": rollout_count}


def output_quantiles(values: np.ndarray) -> dict[str, float]:
    return {
        "min": float(values.min()),
        "p01": float(np.quantile(values, 0.01)),
        "p10": float(np.quantile(values, 0.10)),
        "median": float(np.median(values)),
        "p90": float(np.quantile(values, 0.90)),
        "p99": float(np.quantile(values, 0.99)),
        "max": float(values.max()),
        "std": float(values.std()),
    }


def export_v07(
    model: ValueModel,
    h_scale: float,
    proposal_sha256: str,
    policy_identity_sha256: str,
    path: Path,
) -> str:
    state = model.network.state_dict()
    payload = {
        "schema": "r1-v-reach-weights-v07",
        "architecture": "tanh_mlp_value_4345_h32_v07_stress_v04_scaled_h_groups_budget256",
        "input_dim": INPUT_DIM,
        "hidden_dim": HIDDEN,
        "budget_normalization_max": MAX_BUDGET,
        "feature_schema": "r1-value-input-h-global-meanH-assignment-latent-budget-v02",
        "h_input_scale": h_scale,
        "proposal_sha256": proposal_sha256,
        "proposal_policy_identity_sha256": policy_identity_sha256,
        "identity_sha256": REQUESTS.IDENTITY_SHA256,
        "initialization": "fresh-tanh-mlp; trained on frozen V04 proposal rollouts through 256 steps from uniform, exact-solution-neighborhood, and proposal-trace states",
        "w1": state["0.weight"].detach().cpu().numpy().astype(np.float32).tolist(),
        "b1": state["0.bias"].detach().cpu().numpy().astype(np.float32).tolist(),
        "w2": state["2.weight"].detach().cpu().numpy().reshape(-1).astype(np.float32).tolist(),
        "b2": float(state["2.bias"].detach().cpu().numpy().reshape(())),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
    return hashlib.sha256(raw).hexdigest()


def main() -> int:
    args = parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"refusing to overwrite {output}")
    if not 0.01 <= args.h_scale <= 1.0 or args.epochs <= 0:
        raise ValueError("H scale must be in [0.01, 1] and epochs must be positive")
    proposal_sha256 = _valid_sha256(args.proposal_sha256, "--proposal-sha256")
    policy_identity_sha256 = _valid_sha256(
        args.policy_identity_sha256, "--policy-identity-sha256"
    )
    output.mkdir(parents=True)
    try:
        world_dir = args.world_dir.resolve(strict=True)
        sensor_dir = args.sensor_dir.resolve(strict=True)
        labels_path = args.labels.resolve(strict=True)
        traces_path = args.traces.resolve(strict=True)
        label_receipt_path = args.label_receipt.resolve(strict=True)
        start_states_path = args.start_states.resolve(strict=True)
        request_receipt_path = args.request_receipt.resolve(strict=True)
        proposal_weights_path = args.proposal_weights.resolve(strict=True)
        runtime_proposal_receipt_path = args.runtime_proposal_receipt.resolve(strict=True)
        temperature_artifact_path = (
            args.temperature_calibration or args.temperature_override
        ).resolve(strict=True)
        baseline_path = args.baseline_weights.resolve(strict=True)
        public_path = world_dir / "public-tasks.jsonl"
        support_path = world_dir / REQUESTS.SUPPORT_FILENAME
        start_receipt_path = start_states_path.with_suffix(".receipt-v04-v01.json")

        runtime_proposal_receipt = json.loads(
            runtime_proposal_receipt_path.read_text(encoding="utf-8")
        )
        observed_proposal_sha256, proposal_weights = validate_runtime_proposal_receipt(
            runtime_proposal_receipt, proposal_weights_path
        )
        if observed_proposal_sha256 != proposal_sha256:
            raise ValueError("--proposal-sha256 differs from V132 proposal weights")
        runtime_policy = {
            "proposal_weights_file": proposal_weights_path.name,
            "proposal_weights_sha256": proposal_sha256,
            "mixture_id": V03_MIXTURE_ID,
        }
        if args.temperature_calibration is not None:
            calibration = json.loads(temperature_artifact_path.read_text(encoding="utf-8"))
            temperature = validate_temperature_calibration(
                calibration,
                runtime_proposal_receipt,
                temperature_artifact_path,
            )
            runtime_policy.update(
                {
                    "temperature": temperature,
                    "temperature_calibration_schema": calibration["schema"],
                    "temperature_calibration_sha256": sha(temperature_artifact_path),
                }
            )
        else:
            temperature_override = json.loads(
                temperature_artifact_path.read_text(encoding="utf-8")
            )
            temperature = validate_temperature_override(
                temperature_override,
                temperature_artifact_path,
                observed_proposal_sha256,
            )
            runtime_policy.update(
                {
                    "temperature": temperature,
                    "temperature_override": {
                        "artifact_file": temperature_artifact_path.name,
                        "schema": temperature_override["schema"],
                        "sha256": sha(temperature_artifact_path),
                        "selected_temperature": temperature,
                        "tuning_provenance": "qualification-based engineering tuning; not scientific confirmation",
                        "qualification_selection_access": True,
                        "v_reach_fit_scope": "train/validation only",
                        "scientific_confirmation_eligible": False,
                        "source_lineage": temperature_override["source_lineage"],
                    },
                }
            )

        public_rows = read_jsonl(public_path)
        support = json.loads(support_path.read_text(encoding="utf-8"))
        public, split_by_task = REQUESTS.validate_split_roster(public_rows, support)
        trainval_tasks = {
            task_id for task_id, split in split_by_task.items() if split in ("train", "validation")
        }
        if len(trainval_tasks) != REQUESTS.TRAIN_VALIDATION_COUNT:
            raise ValueError("V04 train/validation roster must contain exactly 80 tasks")

        start_sha256 = sha(start_states_path)
        request_receipt = json.loads(request_receipt_path.read_text(encoding="utf-8"))
        request_proposal_sha = get_request_proposal_sha256(request_receipt)
        proposal_lineage, request_inputs = REFIT.validate_request_receipt(
            request_receipt, request_proposal_sha, start_sha256
        )
        if request_inputs.get("public_tasks", {}).get("sha256") != sha(public_path):
            raise ValueError("request receipt public-task hash differs from refit input")
        if request_inputs.get("support_manifest", {}).get("sha256") != sha(support_path):
            raise ValueError("request receipt support-manifest hash differs from refit input")
        if request_inputs.get("sensor_receipt", {}).get("sha256") != sha(sensor_dir / "receipt.json"):
            raise ValueError("request receipt sensor hash differs from refit input")
        if request_inputs.get("proposal_weights", {}).get("sha256") != request_proposal_sha:
            raise ValueError("request receipt proposal weights hash differs from its request proposal")
        if request_inputs.get("identity_model", {}).get("sha256") != REQUESTS.IDENTITY_SHA256:
            raise ValueError("request receipt identity head hash differs from pinned identity")
        if sha(start_receipt_path) != request_inputs.get("start_state_receipt", {}).get("sha256"):
            raise ValueError("request receipt start-state receipt hash differs from refit input")

        start_receipt = json.loads(start_receipt_path.read_text(encoding="utf-8"))
        REQUESTS.verify_start_receipt(
            start_receipt,
            start_sha256,
            request_inputs["private_trainval_only"]["sha256"],
            request_inputs["proposal_fit_receipt"]["sha256"],
        )

        private_trainval_path = Path(request_inputs["private_trainval_only"]["path"]).resolve(strict=True)
        old_proposal_path = Path(request_inputs["proposal_weights"]["path"]).resolve(strict=True)
        old_proposal_record = _require_file_record(
            request_inputs["proposal_weights"], old_proposal_path, "request/start proposal weights"
        )
        old_proposal_fit_receipt_path = Path(
            request_inputs["proposal_fit_receipt"]["path"]
        ).resolve(strict=True)
        runtime_inputs = runtime_proposal_receipt.get("input_hashes", {})
        _require_file_record(
            runtime_inputs.get("fit_receipt"),
            old_proposal_fit_receipt_path,
            "V132 initial V04 fit receipt",
        )
        _require_file_record(
            runtime_inputs.get("initial_weights"),
            old_proposal_path,
            "V132 initial V04 proposal weights",
        )
        private_trainval_record = _require_file_record(
            request_inputs["private_trainval_only"],
            private_trainval_path,
            "filtered train/validation private sidecar",
        )
        old_fit_receipt = json.loads(old_proposal_fit_receipt_path.read_text(encoding="utf-8"))
        old_proposal_lineage = REQUESTS.verify_proposal_receipt(
            old_fit_receipt,
            old_proposal_record,
            request_proposal_sha,
            private_trainval_record,
            len(read_jsonl(private_trainval_path)),
        )
        if old_proposal_lineage.get("identity_receipt_sha256") != proposal_lineage.get(
            "identity_receipt_sha256"
        ):
            raise ValueError("request receipt frozen identity lineage differs from the old V04 fit")
        if runtime_proposal_receipt.get("input_hashes", {}).get("fit_receipt", {}).get(
            "sha256"
        ) != request_inputs["proposal_fit_receipt"].get("sha256"):
            raise ValueError("V132 fit does not descend from the V04 fit bound by the start states")

        start_rows = read_jsonl(start_states_path)
        grouped_starts = REQUESTS.validate_start_rows(start_rows, public, split_by_task)
        if len(grouped_starts) != REQUESTS.TRAIN_VALIDATION_COUNT:
            raise ValueError("start-state input does not cover the complete train/validation roster")

        label_receipt = json.loads(label_receipt_path.read_text(encoding="utf-8"))
        label_contract = validate_v03_simulator_receipt(
            label_receipt,
            labels_path,
            traces_path,
            Path(request_receipt["request_file"]["path"]).resolve(strict=True),
            proposal_weights_path,
            proposal_sha256,
            policy_identity_sha256,
            temperature,
            expected_source_hashes=_expected_policy_source_hashes(),
            expected_tasks=len(trainval_tasks),
        )
        expected_rollouts = int(request_receipt["rollouts_per_state"])
        if label_contract["rollout_count"] != label_contract["state_count"] * expected_rollouts:
            raise ValueError("V03 simulator rollout totals differ from request receipt")
        label_counts = validate_v03_label_rows(
            labels_path,
            trainval_tasks,
            split_by_task,
            proposal_sha256,
            policy_identity_sha256,
            label_contract["policy_identity"],
            label_contract["state_count"],
            label_contract["rollout_count"],
        )
        feature_store = load_feature_store(sensor_dir, public_path, public_rows, support_path)
        x, y, splits, metadata = HELPERS.PIPELINE.assemble_vreach(
            labels_path, feature_store, max_budget=MAX_BUDGET
        )
        if any(row["split"] == "qualification" for row in metadata):
            raise ValueError("qualification V_reach targets entered the fit dataset")
        if set(splits) != {"train", "validation"}:
            raise ValueError(f"fit requires train and validation labels, got {set(splits)}")
        if {row["task_id"] for row in metadata} != trainval_tasks:
            raise ValueError("assembled labels do not cover exactly the V04 train/validation roster")

        scaled_x = HELPERS.scale_h_groups(x, args.h_scale)
        import torch

        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        random.seed(args.seed)
        np.random.seed(args.seed)
        torch.manual_seed(args.seed)
        device_name = "cuda" if args.device == "auto" and torch.cuda.is_available() else args.device
        device = torch.device("cpu" if device_name == "auto" else device_name)
        train_mask = splits == "train"
        validation_mask = splits == "validation"

        baseline_x, baseline_y, baseline_splits, baseline_metadata = HELPERS.PIPELINE.assemble_vreach(
            labels_path, feature_store, max_budget=64
        )
        if (
            baseline_metadata != metadata
            or not np.array_equal(baseline_y, y)
            or not np.array_equal(baseline_splits, splits)
        ):
            raise ValueError("/64 baseline and /256 V04 value rows are not aligned")

        start_kind = {
            (row["task_id"], int(row["state_index"])): row["source_kind"]
            for row in start_rows
        }
        if len(start_kind) != REQUESTS.TRAIN_VALIDATION_COUNT * REQUESTS.STARTS_PER_TASK:
            raise ValueError("expected exactly 2,560 unique V04 train/validation start states")
        mix = {
            kind: sum(row["source_kind"] == kind for row in start_rows)
            for kind in ("uniform", "solution_neighborhood")
        }
        expected_mix = {"uniform": 1_280, "solution_neighborhood": 1_280}
        if mix != expected_mix:
            raise ValueError(f"start-state source mix differs from frozen 50/50 design: {mix}")

        source_kinds = []
        task_sizes = []
        for row in metadata:
            task_sizes.append(int(public[row["task_id"]]["n"]))
            state_id = row["state_id"]
            if "-t" in state_id:
                source_kinds.append("proposal_trace")
            else:
                state_index = int(state_id.split("-s", 1)[1].split("-", 1)[0])
                source_kinds.append(start_kind[(row["task_id"], state_index)])
        task_sizes_array = np.asarray(task_sizes, dtype=np.int16)
        source_kinds_array = np.asarray(source_kinds, dtype=object)

        baseline = ValueModel(torch, baseline_x.shape[1])
        HELPERS.copy_baseline(baseline, baseline_path, torch)
        baseline.network.to(device)
        baseline_metrics = {
            "raw_validation": binary_metrics(
                predict_value(baseline, baseline_x[validation_mask], device), y[validation_mask]
            ),
            "scaled_validation_without_refit": binary_metrics(
                predict_value(
                    baseline,
                    HELPERS.scale_h_groups(baseline_x, args.h_scale)[validation_mask],
                    device,
                ),
                y[validation_mask],
            ),
            "raw_hidden_saturation": HELPERS.hidden_saturation(
                baseline, baseline_x[validation_mask], device
            ),
            "scaled_hidden_saturation": HELPERS.hidden_saturation(
                baseline, HELPERS.scale_h_groups(baseline_x, args.h_scale)[validation_mask], device
            ),
        }

        model, history, best_epoch = HELPERS.fit_scaled(
            scaled_x, y, splits, args.seed + 1, args.epochs, torch, device
        )
        probabilities = predict_value(model, scaled_x, device)
        metrics = {
            "train": binary_metrics(probabilities[train_mask], y[train_mask]),
            "validation": binary_metrics(probabilities[validation_mask], y[validation_mask]),
        }
        metrics_by_size_and_source: dict[str, dict[str, Any]] = {}
        for split_name, split_mask in (("train", train_mask), ("validation", validation_mask)):
            metrics_by_size_and_source[split_name] = {}
            for size in sorted(set(task_sizes)):
                size_mask = split_mask & (task_sizes_array == size)
                if not size_mask.any():
                    continue
                metrics_by_size_and_source[split_name][str(size)] = {
                    source: binary_metrics(
                        probabilities[size_mask & (source_kinds_array == source)],
                        y[size_mask & (source_kinds_array == source)],
                    )
                    for source in ("uniform", "solution_neighborhood", "proposal_trace")
                    if np.any(size_mask & (source_kinds_array == source))
                }
        saturation = {
            "train": HELPERS.hidden_saturation(model, scaled_x[train_mask], device),
            "validation": HELPERS.hidden_saturation(model, scaled_x[validation_mask], device),
        }

        weights_path = output / WEIGHTS_NAME
        weights_sha256 = export_v07(
            model,
            args.h_scale,
            proposal_sha256,
            policy_identity_sha256,
            weights_path,
        )
        history_path = output / HISTORY_NAME
        with history_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(history, indent=2, sort_keys=True) + "\n")

        request_file_path = Path(request_receipt["request_file"]["path"])
        source_paths = [
            Path(__file__).resolve(),
            REFIT_PATH.resolve(),
            HELPERS_PATH.resolve(),
            PIPELINE_PATH.resolve(),
            (PROPOSAL_DIR / "feature_math.py").resolve(),
            (V02_DIR / "value_training.py").resolve(),
            *[
                (PROPOSAL_DIR.parent / relative_path).resolve()
                for relative_path in POLICY_IDENTITY_SOURCE_FILES.values()
            ],
            public_path,
            support_path,
            labels_path,
            traces_path,
            label_receipt_path,
            start_states_path,
            start_receipt_path,
            request_receipt_path,
            request_file_path,
            Path(request_inputs["private_trainval_only"]["path"]),
            Path(request_inputs["proposal_weights"]["path"]),
            Path(request_inputs["proposal_fit_receipt"]["path"]),
            proposal_weights_path,
            runtime_proposal_receipt_path,
            temperature_artifact_path,
            sensor_dir / "receipt.json",
            sensor_dir / "constraint_H.float32.npy",
            sensor_dir / "global_h.float32.npy",
            sensor_dir / "rows.jsonl",
            baseline_path,
        ]
        receipt = {
            "schema": "FAS_R1_VREACH_RUNTIME_REFIT_V01",
            "status": "VREACH_RUNTIME_REFIT_COMPLETE",
            "mode": "adaptive engineering fit; V03 train/validation runtime-matched rollout labels only",
            "analysis_mode": "ADAPTIVE_ENGINEERING",
            "qualification_previously_opened": True,
            "scientific_confirmation_eligible": False,
            "qualification_targets_consumed": False,
            "qualification_features_used_for_fit": False,
            "proposal_refit": False,
            "proposal_sha256": proposal_sha256,
            "proposal_policy_identity_sha256": policy_identity_sha256,
            "request_start_proposal_sha256": request_proposal_sha,
            "runtime_policy": {
                **runtime_policy,
                "policy_identity": label_contract["policy_identity"],
            },
            "request_start_provenance": {
                "request_receipt_schema": request_receipt.get("schema"),
                "request_proposal_sha256": request_proposal_sha,
                "request_file_sha256": request_receipt["request_file"]["sha256"],
                "start_states_sha256": start_sha256,
                "start_state_receipt_sha256": sha(start_receipt_path),
            },
            "label_generation": {
                "simulator_receipt_schema": label_receipt.get("schema"),
                "simulator_receipt_sha256": sha(label_receipt_path),
                "dataset_schema": V03_LABEL_SCHEMA,
                "state_schema": V03_STATE_SCHEMA,
                "labels_sha256": label_contract["label_file"]["sha256"],
                "traces_sha256": label_contract["trace_file"]["sha256"],
                "task_count": label_counts["task_count"],
                "state_count": label_counts["state_count"],
                "rollout_count": label_counts["rollout_count"],
            },
            "identity_sha256": REQUESTS.IDENTITY_SHA256,
            "request_receipt_sha256": sha(request_receipt_path),
            "dataset": {
                "world_split_counts": support["split_counts"],
                "label_sha256": sha(labels_path),
                "state_rows": int(len(metadata)),
                "train_rows": int(train_mask.sum()),
                "validation_rows": int(validation_mask.sum()),
                "start_state_rows": len(start_kind),
                "start_state_mix": mix,
                "rollout_rows": int(sum(row["rollouts"] for row in metadata)),
                "train_families": len({row["family_id"] for row in metadata if row["split"] == "train"}),
                "validation_families": len({row["family_id"] for row in metadata if row["split"] == "validation"}),
            },
            "baseline_v02_same_validation_rows": baseline_metrics,
            OUTPUT_VERSION: {
                "weights_file": weights_path.name,
                "weights_sha256": weights_sha256,
                "h_input_scale": args.h_scale,
                "budget_normalization_max": MAX_BUDGET,
                "best_epoch": best_epoch,
                "metrics": metrics,
                "metrics_by_size_and_source": metrics_by_size_and_source,
                "hidden_saturation": saturation,
                "train_forecast_quantiles": output_quantiles(probabilities[train_mask]),
                "validation_forecast_quantiles": output_quantiles(probabilities[validation_mask]),
            },
            "training": {
                "seed": args.seed + 1,
                "optimizer": "AdamW",
                "learning_rate": 1e-3,
                "weight_decay": 1e-4,
                "max_epochs": args.epochs,
                "early_stopping_patience": 10,
                "device": str(device),
            },
            "input_pins": {
                str(path.resolve(strict=True)): {
                    "sha256": sha(path),
                    "bytes": path.stat().st_size,
                }
                for path in source_paths
            },
        }
        receipt_path = output / RECEIPT_NAME
        with receipt_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        print(f"weights_sha256={weights_sha256}")
        print(f"proposal_policy_identity_sha256={policy_identity_sha256}")
        print(f"best_epoch={best_epoch}")
        print(f"validation_metrics={json.dumps(metrics['validation'], sort_keys=True)}")
        print(f"receipt_sha256={sha(receipt_path)}")
        return 0
    except Exception as error:
        failure = {
            "schema": "FAS_R1_VREACH_RUNTIME_REFIT_FAILURE_V01",
            "status": "VREACH_RUNTIME_REFIT_FAILED",
            "analysis_mode": "ADAPTIVE_ENGINEERING",
            "qualification_previously_opened": True,
            "scientific_confirmation_eligible": False,
            "model_version": OUTPUT_VERSION,
            "error": str(error),
        }
        failure_path = output / "failure-runtime-v01.json"
        with failure_path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        raise


if __name__ == "__main__":
    raise SystemExit(main())
