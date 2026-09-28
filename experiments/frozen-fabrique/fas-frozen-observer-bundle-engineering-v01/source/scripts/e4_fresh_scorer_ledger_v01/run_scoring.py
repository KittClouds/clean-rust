from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import importlib.util
import json
import math
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import ledger_adapter as adapter


FROZEN_WRITER_PATH = adapter.WORKSPACE_ROOT / (
    "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/"
    "e4_fresh_scorer_v04/output_artifacts.py"
)
FROZEN_WRITER_BYTES = 5887
FROZEN_WRITER_SHA256 = "73fbdd184d01df6de913676a0caa0be8f38f264bc9667e3985b52485425b33d4"
ROW_FILE_CAP_BYTES = 382300160
OTHER_PERSISTENT_CAP_BYTES = 536870912
TEMPORARY_CAP_BYTES = 536870912
HOST_RAM_PEAK_CAP_BYTES = 25769803776
PRIMARY_PANEL_BYTES = 39363264
DISK_RESERVE_FRACTION = 0.10
OUTPUT_NAMES = (
    "score/predictions-v01.jsonl",
    "score/scored-rows-v01.jsonl",
    "score/metrics-v01.json",
    "score/bootstrap-v01.npz",
    "score/label-open-receipt-v01.json",
    "score/terminal-receipt-v01.json",
    "score/stage-seal-v01.json",
)
ROW_OUTPUT_NAMES = frozenset({
    "score/predictions-v01.jsonl", "score/scored-rows-v01.jsonl",
})
OTHER_OUTPUT_NAMES = frozenset(set(OUTPUT_NAMES) - ROW_OUTPUT_NAMES)


class RunnerError(RuntimeError):
    pass


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise RunnerError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json_object(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        raise RunnerError("runtime handoff path must not be a symlink")
    resolved = path.resolve(strict=True)
    if not resolved.is_file():
        raise RunnerError("runtime handoff path is not an ordinary file")
    try:
        value = json.loads(resolved.read_bytes(), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RunnerError(f"invalid runtime handoff JSON: {resolved.name}") from error
    if not isinstance(value, dict):
        raise RunnerError(f"runtime handoff must be a JSON object: {resolved.name}")
    return value


def validate_runtime_handoff_paths(
    *, invocation: Mapping[str, Any], invocation_path: Path,
    delivery_path: Path, panel_path: Path,
) -> tuple[Path, Path, Path]:
    """Require all dynamic Library handoffs at their fixed attempt-root paths."""
    attempt_root = adapter.validate_invocation(invocation)
    ledger_inputs = attempt_root / "ledger-inputs"
    expected = (
        ledger_inputs / "scoring-invocation-v01.json",
        ledger_inputs / "panel-delivery-v01.json",
        ledger_inputs / "primary-panel-e4-v01.jsonl",
    )
    supplied = tuple(path.resolve(strict=True) for path in (
        invocation_path, delivery_path, panel_path
    ))
    if supplied != expected:
        raise RunnerError("runtime handoff files differ from the fixed attempt-root paths")
    return supplied


def _file_identity(path: Path) -> tuple[str, int]:
    digest, size = hashlib.sha256(), 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _load_frozen_writer() -> tuple[Any, Any]:
    if _file_identity(FROZEN_WRITER_PATH) != (FROZEN_WRITER_SHA256, FROZEN_WRITER_BYTES):
        raise RunnerError("frozen E4 output writer hash or length changed")
    adapter.load_frozen_math()
    scorer_path = adapter.FROZEN_MATH_PATH.resolve(strict=True)
    existing_scorer = sys.modules.get("scorer")
    if existing_scorer is None:
        scorer_spec = importlib.util.spec_from_file_location("scorer", scorer_path)
        if scorer_spec is None or scorer_spec.loader is None:
            raise RunnerError("cannot load bound frozen E4 scorer")
        scorer = importlib.util.module_from_spec(scorer_spec)
        sys.modules["scorer"] = scorer
        scorer_spec.loader.exec_module(scorer)
    else:
        scorer = existing_scorer
        if Path(scorer.__file__).resolve() != scorer_path:
            raise RunnerError("another scorer module is already loaded in this process")
    writer_path = FROZEN_WRITER_PATH.resolve(strict=True)
    existing_writer = sys.modules.get("output_artifacts")
    if existing_writer is None:
        writer_spec = importlib.util.spec_from_file_location("output_artifacts", writer_path)
        if writer_spec is None or writer_spec.loader is None:
            raise RunnerError("cannot load bound frozen E4 output writer")
        writer = importlib.util.module_from_spec(writer_spec)
        sys.modules["output_artifacts"] = writer
        writer_spec.loader.exec_module(writer)
    else:
        writer = existing_writer
        if Path(writer.__file__).resolve() != writer_path:
            raise RunnerError("another output writer module is already loaded in this process")
    if scorer.torch.cuda.is_initialized():
        raise RunnerError("CPU-only E4 scoring process unexpectedly initialized CUDA")
    return scorer, writer


def _existing_ancestor(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        if candidate.parent == candidate:
            raise RunnerError("output path has no existing volume ancestor")
        candidate = candidate.parent
    return candidate.resolve(strict=True)


def preflight_disk(output_root: Path) -> dict[str, int]:
    if output_root.exists():
        raise RunnerError("scoring output root already exists; preserve this attempt")
    usage = shutil.disk_usage(_existing_ancestor(output_root.parent))
    persistent = 2 * ROW_FILE_CAP_BYTES + OTHER_PERSISTENT_CAP_BYTES
    projected = persistent + TEMPORARY_CAP_BYTES + PRIMARY_PANEL_BYTES
    reserve = math.ceil(usage.total * DISK_RESERVE_FRACTION)
    required = projected + reserve
    if usage.free < required:
        raise RunnerError("scoring disk preflight is below frozen projected output plus reserve")
    return {
        "volume_total_bytes": usage.total,
        "free_before_bytes": usage.free,
        "projected_scoring_bytes": projected,
        "reserve_bytes": reserve,
        "required_free_bytes": required,
    }


def process_peak_memory() -> dict[str, int]:
    if os.name != "nt":
        raise RunnerError("the frozen scoring runtime requires Windows process memory telemetry")
    from ctypes import wintypes

    class ProcessMemoryCountersEx(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    counters = ProcessMemoryCountersEx()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    ok = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "peak_working_set_bytes": int(counters.PeakWorkingSetSize),
        "peak_pagefile_usage_bytes": int(counters.PeakPagefileUsage),
        "private_usage_at_receipt_bytes": int(counters.PrivateUsage),
    }


def _check_output_sizes(output_root: Path) -> dict[str, int]:
    sizes: dict[str, int] = {}
    for name in OUTPUT_NAMES:
        path = output_root.joinpath(*name.split("/"))
        if not path.is_file() or path.is_symlink():
            raise RunnerError(f"declared score output is missing or not a regular file: {name}")
        size = path.stat().st_size
        if name in ROW_OUTPUT_NAMES and size > ROW_FILE_CAP_BYTES:
            raise RunnerError(f"row-level score output exceeds the frozen per-file cap: {name}")
        sizes[name] = size
    other_total = sum(sizes[name] for name in OTHER_OUTPUT_NAMES)
    if other_total > OTHER_PERSISTENT_CAP_BYTES:
        raise RunnerError("non-row persistent score outputs exceed the frozen aggregate cap")
    return sizes


def _stop_receipt(
    *, error: Exception, invocation: Mapping[str, Any] | None,
    reader: adapter.OneShotLibraryPanelReader | None, output_root: Path,
) -> Path | None:
    try:
        score_root = output_root / "score"
        score_root.mkdir(parents=True, exist_ok=True)
        stop_path = score_root / "score-stop-v01.json"
        if stop_path.exists():
            return stop_path
        payload = {
            "schema": "FAS_E4_0_FRESH_SCORING_STOP_V01",
            "status": "SCORING_ATTEMPT_STOPPED_AND_PRESERVED",
            "authorization_id": (
                invocation.get("authority", {}).get("authorization_id")
                if isinstance(invocation, Mapping) else None
            ),
            "error_type": type(error).__name__,
            "error": str(error),
            "ledger_panel_open_event_count": 1 if reader and reader.attempted else 0,
            "scorer_materialized_file_open_count": reader.local_file_open_count if reader else 0,
            "label_open_partial_receipt": reader.last_receipt if reader else None,
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        writer_path = score_root / "score-stop-v01.json"
        writer_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        return writer_path
    except Exception:
        return None


def execute_scoring(
    *, invocation: Mapping[str, Any], delivery: Mapping[str, Any],
    feature_cache_path: Path, row_manifest_path: Path, e3_head_root: Path,
    staged_panel_file: Path, output_root: Path,
) -> dict[str, Any]:
    """Run one authorized primary-label scoring stage; never opens escrow panels."""
    reader: adapter.OneShotLibraryPanelReader | None = None
    output_root = output_root.resolve()
    if output_root.exists():
        raise RunnerError("KAMMI output root already exists; preserve this attempt")
    adapter.validate_invocation(invocation)
    score_root = output_root / "score"
    try:
        disk = preflight_disk(output_root)
        score_root.mkdir(parents=True, exist_ok=False)
        attempt_root = adapter.validate_invocation(invocation)
        adapter.validate_panel_delivery(invocation, delivery, attempt_root, staged_panel_file)
        scorer, writer = _load_frozen_writer()
        primary, predictions, manifest = adapter.prepare_primary_predictions(
            invocation=invocation,
            feature_cache_path=feature_cache_path,
            row_manifest_path=row_manifest_path,
            e3_head_root=e3_head_root,
        )
        if scorer.torch.cuda.is_initialized():
            raise RunnerError("CUDA initialized during CPU-only primary inference")
        prediction_path = score_root / "predictions-v01.jsonl"
        writer.write_prediction_rows(prediction_path, primary, predictions)
        if prediction_path.stat().st_size > ROW_FILE_CAP_BYTES:
            raise RunnerError("primary predictions exceed the frozen row-level output cap")

        reader = adapter.OneShotLibraryPanelReader()
        metrics, panel_receipt, joined = adapter.score_from_ledger_materialization(
            invocation=invocation,
            delivery=delivery,
            manifest=manifest,
            predictions=predictions,
            reader=reader,
            staged_panel_file=staged_panel_file,
        )

        scored_rows_path = score_root / "scored-rows-v01.jsonl"
        writer.write_scored_rows(scored_rows_path, joined)
        metrics_out, bootstrap_payload = writer.metrics_and_bootstrap(metrics)
        metrics_path = score_root / "metrics-v01.json"
        bootstrap_path = score_root / "bootstrap-v01.npz"
        label_receipt_path = score_root / "label-open-receipt-v01.json"
        writer.atomic_json(metrics_path, metrics_out)
        writer.atomic_create_bytes(bootstrap_path, bootstrap_payload)
        label_receipt = writer.label_open_receipt(panel_receipt)
        label_receipt["library_source_file_hash_read_expected"] = True
        writer.atomic_json(label_receipt_path, label_receipt)

        memory = process_peak_memory()
        if memory["peak_working_set_bytes"] > HOST_RAM_PEAK_CAP_BYTES:
            raise RunnerError("scoring process exceeded the frozen host RAM peak ceiling")
        if scorer.torch.cuda.is_initialized():
            raise RunnerError("CUDA initialized during E4 scoring")

        terminal = {
            "schema": "FAS_E4_0_FRESH_SCORING_TERMINAL_V01",
            "status": "SCORING_EXECUTION_COMPLETE",
            "authorization_id": invocation["authority"]["authorization_id"],
            "contract_sha256": adapter.CONTRACT_SHA256,
            "contract_seal_manifest_sha256": adapter.CONTRACT_SEAL_MANIFEST_SHA256,
            "contract_seal_root_sha256": adapter.CONTRACT_SEAL_ROOT_SHA256,
            "exact_predecessor_roots": dict(adapter.PREDECESSOR_ROOTS),
            "primary_rows_scored": len(primary),
            "heldout_template_rows_inferred": 0,
            "heldout_template_labels_opened": False,
            "joint_template_labels_opened": False,
            "ledger_panel_open_event_count": 1,
            "scorer_materialized_file_open_count": 1,
            "library_source_file_hash_read_expected": True,
            "library_open_panel_event_id": panel_receipt["ledger_exposure_event_id"],
            "library_panel_id": panel_receipt["ledger_panel_id"],
            "refit_performed": False,
            "tuning_performed": False,
            "alternate_view_used": False,
            "terminal_disposition": metrics["terminal_disposition"],
            "passed_endpoints": metrics["passed_endpoints"],
            "failed_endpoints": metrics["failed_endpoints"],
            "outputs": {
                "predictions": "score/predictions-v01.jsonl",
                "scored_rows": "score/scored-rows-v01.jsonl",
                "metrics": "score/metrics-v01.json",
                "bootstrap": "score/bootstrap-v01.npz",
                "label_open_receipt": "score/label-open-receipt-v01.json",
                "stage_seal": "score/stage-seal-v01.json",
            },
            "resources": {
                "disk_preflight": disk,
                "process_memory": memory,
                "host_ram_peak_limit_bytes": HOST_RAM_PEAK_CAP_BYTES,
                "cuda_initialized": False,
                "projected_scoring_bytes_including_staged_panel": (
                    2 * ROW_FILE_CAP_BYTES + OTHER_PERSISTENT_CAP_BYTES
                    + TEMPORARY_CAP_BYTES + PRIMARY_PANEL_BYTES
                ),
            },
            "created_utc": datetime.now(timezone.utc).isoformat(),
        }
        terminal_path = score_root / "terminal-receipt-v01.json"
        writer.atomic_json(terminal_path, terminal)

        entries = [
            writer.artifact_entry("E4_SCORING_PREDICTIONS_V01", prediction_path, run_root=output_root),
            writer.artifact_entry("E4_SCORING_SCORED_ROWS_V01", scored_rows_path, run_root=output_root),
            writer.artifact_entry("E4_SCORING_METRICS_V01", metrics_path, run_root=output_root),
            writer.artifact_entry("E4_SCORING_BOOTSTRAP_V01", bootstrap_path, run_root=output_root),
            writer.artifact_entry("E4_SCORING_LABEL_OPEN_RECEIPT_V01", label_receipt_path, run_root=output_root),
            writer.artifact_entry("E4_SCORING_TERMINAL_RECEIPT_V01", terminal_path, run_root=output_root),
        ]
        seal = writer.stage_seal_payload(
            entries=entries,
            contract_sha256=adapter.CONTRACT_SHA256,
            contract_seal_root_sha256=adapter.CONTRACT_SEAL_ROOT_SHA256,
            predecessor_roots=adapter.PREDECESSOR_ROOTS,
        )
        seal_path = score_root / "stage-seal-v01.json"
        writer.atomic_json(seal_path, seal)
        sizes = _check_output_sizes(output_root)
        nonrow_total = sum(sizes[name] for name in OTHER_OUTPUT_NAMES)
        if nonrow_total > OTHER_PERSISTENT_CAP_BYTES:
            raise RunnerError("sealed non-row outputs exceed aggregate cap")
        return {
            "status": terminal["status"],
            "terminal_disposition": metrics["terminal_disposition"],
            "passed_endpoints": metrics["passed_endpoints"],
            "failed_endpoints": metrics["failed_endpoints"],
            "scoring_stage_root_sha256": seal["root_sha256"],
            "scoring_stage_seal_path": str(seal_path),
            "outputs": sizes,
        }
    except Exception as error:
        _stop_receipt(error=error, invocation=invocation, reader=reader, output_root=output_root)
        raise


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one Ledger-authorized E4-0 scoring stage.")
    parser.add_argument("--invocation", type=Path, required=True)
    parser.add_argument("--delivery", type=Path, required=True)
    parser.add_argument("--panel-file", type=Path, required=True)
    parser.add_argument("--feature-cache", type=Path, required=True)
    parser.add_argument("--row-manifest", type=Path, required=True)
    parser.add_argument("--e3-head-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        invocation = read_json_object(args.invocation)
        validate_runtime_handoff_paths(
            invocation=invocation,
            invocation_path=args.invocation,
            delivery_path=args.delivery,
            panel_path=args.panel_file,
        )
        delivery = read_json_object(args.delivery)
        result = execute_scoring(
            invocation=invocation,
            delivery=delivery,
            feature_cache_path=args.feature_cache,
            row_manifest_path=args.row_manifest,
            e3_head_root=args.e3_head_root,
            staged_panel_file=args.panel_file,
            output_root=args.output_root,
        )
        sys.stdout.write(json.dumps(result, ensure_ascii=True, indent=2) + "\n")
        return 0
    except Exception as error:
        sys.stderr.write(f"E4 scoring stopped and preserved: {type(error).__name__}: {error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
