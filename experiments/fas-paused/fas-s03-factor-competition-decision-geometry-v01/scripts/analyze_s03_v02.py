from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

os.environ["OPENBLAS_NUM_THREADS"] = "4"
os.environ["OMP_NUM_THREADS"] = "4"
os.environ["MKL_NUM_THREADS"] = "4"

import numpy as np


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s03-factor-competition-decision-geometry-v01")
CONSTRUCTION_SEAL = PROJECT / "seals" / "construction-seal-v01.json"
CONTRACT_PATH = PROJECT / "contracts" / "analysis-contract-v01.json"
PARENT_BINDING_PATH = PROJECT / "contracts" / "parent-binding-v01.json"
AUTH_PATH = PROJECT / "contracts" / "authorization-v01.json"
RUNNER_CORRECTION = PROJECT / "seals" / "runner-correction-v01.json"
RUNNER_CORRECTION_SEAL = PROJECT / "seals" / "runner-correction-seal-v01.json"
RUNNER_FAILURE = RUN / "runner-failure-v01.json"

P1_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\phase1-v03")
P1_RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v03")
P1_CORPUS = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v03\corpus\qualification-events-v03.jsonl")
P1_SEAL = P1_PROJECT / "seals" / "phase1-v03-seal.json"
P2A_ROOT = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01")
P2A_SEAL = P2A_ROOT / "phase2a-v01-cache-seal.json"
P2A_CACHE = P2A_ROOT / "feature-cache-v01"
P2A_TENSOR = P2A_CACHE / "features-v01.f32le"
P2A_ROWS = P2A_CACHE / "feature-rows-v01.jsonl"
MEAN_PROBE = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase3-v02\results-v01\probe-artifacts\HELDOUT_TERM_EXACT_TARGET.npz")
PHASE3_CORE = Path(r"C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00\phase3-v02\probe_core.py")
PHASE3_RESULTS = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase3-v02\results-v01")
PHASE3_SEAL = PHASE3_RESULTS / "phase3-result-seal-v01.json"
S02_RUN = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01\s02-2-readout-attribution-v01\correction-v05")
S02_SEAL = S02_RUN / "seals" / "result-tree-seal-v01.json"
S02_1_RUN = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01\s02-1-final-position-v02")
S02_1_SEAL = S02_1_RUN / "seals" / "s02-1-seal-v01.json"
S02_1_CACHE = S02_1_RUN / "feature-cache-v01"
S02_1_CACHE_SEAL = S02_1_CACHE / "feature-cache-seal-v01.json"
S02_FINAL_PROBE = S02_RUN / "results-v01" / "final-position-probe-v01.npz"

EVENTS = 32768
WIDTH = 2048
CLASSES = ("safe", "risky", "idle")
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))
SLICES = ("test_context_term_3", "test_entity_term_7")
OUTPUT_NAMES = (
    "runner-failure-v01.json",
    "runner-correction-v01.json",
    "runner-correction-seal-v01.json",
    "construction-seal-v01.json",
    "preflight-v01.json",
    "selected-events-v01.jsonl",
    "event-margin-ledger-v01.jsonl",
    "descriptive-summary-v01.json",
    "membership-overlap-v01.json",
    "decision-normal-geometry-v01.json",
    "execution-receipt-v01.json",
    "S03-RESULTS.md",
)


class FailClosed(RuntimeError):
    pass


def sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n")


def canonical_root(rows: list[dict]) -> str:
    body = "".join(f'{row["path"]} {row["sha256"]}\n' for row in sorted(rows, key=lambda x: x["path"].casefold()))
    return sha_bytes(body.encode("utf-8"))


def verify_file_list(base: Path, rows: list[dict], expected_root: str, label: str) -> None:
    observed = []
    for row in rows:
        path = base / Path(row["path"])
        if not path.is_file():
            raise FailClosed(f"{label}: missing sealed file {path}")
        actual = sha_file(path)
        if actual != row["sha256"]:
            raise FailClosed(f"{label}: hash mismatch for {row['path']}")
        observed.append({"path": row["path"], "sha256": actual})
    root = canonical_root(observed)
    if root != expected_root:
        raise FailClosed(f"{label}: root mismatch {root} != {expected_root}")


def verify_seal(path: Path, base: Path, expected_root: str, label: str) -> dict:
    seal = read_json(path)
    if seal.get("root_sha256") != expected_root:
        raise FailClosed(f"{label}: declared root differs from bound root")
    verify_file_list(base, seal.get("files", []), expected_root, label)
    return seal


def verify_phase1_files(seal: dict, expected_root: str) -> None:
    observed = []
    for row in seal.get("files", []):
        relative = Path(row["path"])
        if relative.parts[0] == "source":
            candidates = (P1_PROJECT.joinpath(*relative.parts[1:]),)
        elif relative.parts[0] == "corpus":
            candidates = (P1_RUN / relative,)
        else:
            candidates = (P1_PROJECT / relative, P1_RUN / relative)
        path = next((candidate for candidate in candidates if candidate.is_file() and sha_file(candidate) == row["sha256"]), None)
        if path is None or sha_file(path) != row["sha256"]:
            raise FailClosed(f"Phase 1 sealed file missing or changed: {row['path']}")
        observed.append({"path": row["path"], "sha256": row["sha256"]})
    if canonical_root(observed) != expected_root:
        raise FailClosed("Phase 1 file-tree root does not reproduce")


def verify_construction() -> dict:
    seal = read_json(CONSTRUCTION_SEAL)
    rows = seal.get("files", [])
    actual_rows = []
    for row in rows:
        path = PROJECT / Path(row["path"])
        if not path.is_file() or sha_file(path) != row["sha256"]:
            raise FailClosed(f"S03 construction source changed: {row['path']}")
        actual_rows.append({"path": row["path"], "sha256": row["sha256"]})
    root = canonical_root(actual_rows)
    if root != seal.get("root_sha256"):
        raise FailClosed("S03 construction root mismatch")
    if any(seal.get(flag) is not False for flag in (
        "model_contact_authorized", "probe_fitting_authorized", "significance_testing_authorized", "adaptive_mechanisms_authorized"
    )):
        raise FailClosed("S03 construction seal has an invalid authority flag")
    return seal


def verify_runner_correction() -> dict:
    correction = read_json(RUNNER_CORRECTION)
    correction_seal = read_json(RUNNER_CORRECTION_SEAL)
    seal = read_json(CONSTRUCTION_SEAL)
    original = next((row for row in seal.get("files", []) if row.get("path") == "scripts/analyze_s03.py"), None)
    corrected_path = Path(__file__).resolve()
    verify_file_list(PROJECT / "seals", correction_seal.get("files", []), correction_seal.get("root_sha256", ""), "S03 runner correction")
    if (original is None or correction.get("original_runner_sha256") != original["sha256"] or
            correction.get("construction_root_sha256") != seal.get("root_sha256") or
            correction.get("corrected_runner_sha256") != sha_file(corrected_path) or
            correction.get("failure_receipt_sha256") != sha_file(RUNNER_FAILURE) or
            correction.get("status") != "S03_RUNNER_CORRECTION_SEALED" or
            correction_seal.get("seal_id") != "FAS_S03_RUNNER_CORRECTION_SEAL_V01" or
            len(correction_seal.get("files", [])) != 1 or
            correction_seal["files"][0].get("path") != "runner-correction-v01.json"):
        raise FailClosed("S03 runner correction sidecar does not match the sealed source and failure receipt")
    return correction


def parse_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise FailClosed(f"Malformed JSONL {path}:{line_number}: {exc}") from exc


def verify_parent_seals() -> dict:
    contract = read_json(CONTRACT_PATH)
    binding = read_json(PARENT_BINDING_PATH)
    authorization = read_json(AUTH_PATH)
    if authorization.get("status") != "AUTHORIZED" or authorization.get("bound_s02_result_root_sha256") != contract["parents"]["s02_readout_result_root_sha256"]:
        raise FailClosed("S03 authorization does not bind the sealed S02 result")
    if binding.get("source_result_root_sha256") != contract["parents"]["s02_readout_result_root_sha256"]:
        raise FailClosed("S03 parent binding differs from analysis contract")
    if (binding.get("source_phase2a_cache_root_sha256") != contract["parents"]["fas00_phase2a_cache_root_sha256"] or
            binding.get("source_final_position_phase_root_sha256") != contract["parents"]["s02_final_position_phase_root_sha256"] or
            binding.get("source_final_position_cache_root_sha256") != contract["parents"]["s02_final_position_cache_root_sha256"] or
            binding.get("phase1_corpus_sha256") != contract["parents"]["fas00_phase1_corpus_sha256"]):
        raise FailClosed("S03 parent-binding fields differ from the sealed analysis contract")

    p1 = read_json(P1_SEAL)
    if p1.get("root_sha256") != contract["parents"]["fas00_phase1_root_sha256"]:
        raise FailClosed("Phase 1 root differs from the S03 contract")
    verify_phase1_files(p1, contract["parents"]["fas00_phase1_root_sha256"])
    if sha_file(P1_CORPUS) != contract["parents"]["fas00_phase1_corpus_sha256"]:
        raise FailClosed("Phase 1 corpus hash differs from the S03 contract")
    phase1_corpus_rows = [row for row in p1.get("files", []) if row.get("path") == "corpus/qualification-events-v03.jsonl"]
    if len(phase1_corpus_rows) != 1 or phase1_corpus_rows[0]["sha256"] != contract["parents"]["fas00_phase1_corpus_sha256"]:
        raise FailClosed("Phase 1 seal does not bind the allowlisted event corpus")

    p2a = verify_seal(P2A_SEAL, P2A_ROOT, contract["parents"]["fas00_phase2a_cache_root_sha256"], "FAS00 Phase 2A cache")
    if p2a.get("feature_cache_ready") is not True or p2a.get("probe_training_performed") is not False or p2a.get("online_mechanisms_authorized") is not False:
        raise FailClosed("FAS00 Phase 2A cache seal flags are inconsistent")
    phase3 = verify_seal(PHASE3_SEAL, PHASE3_RESULTS, contract["parents"]["fas00_phase3_result_root_sha256"], "FAS00 Phase 3 result")
    phase3_probe_rows = [row for row in phase3.get("files", []) if row.get("path") == "probe-artifacts/HELDOUT_TERM_EXACT_TARGET.npz"]
    if len(phase3_probe_rows) != 1 or phase3_probe_rows[0]["sha256"] != binding["mean_full_probe_sha256"]:
        raise FailClosed("FAS00 Phase 3 seal does not bind the mean_full probe")

    s02_1 = verify_seal(S02_1_SEAL, S02_1_RUN, contract["parents"]["s02_final_position_phase_root_sha256"], "S02-1 final-position phase")
    fp_cache = verify_seal(S02_1_CACHE_SEAL, S02_1_CACHE, contract["parents"]["s02_final_position_cache_root_sha256"], "S02-1 final-position cache")
    if fp_cache.get("feature_tensor_sha256") != "e4ef40343b10761236abdd2e77bb06aff69edb1ffe91a9344cf029a09790e3ba":
        raise FailClosed("S02-1 final-position cache tensor identity mismatch")

    s02 = verify_seal(S02_SEAL, S02_RUN, contract["parents"]["s02_readout_result_root_sha256"], "S02-2 result tree")
    actual_s02_files = {path.relative_to(S02_RUN).as_posix() for path in S02_RUN.rglob("*") if path.is_file() and path != S02_SEAL}
    if actual_s02_files != {row["path"] for row in s02["files"]}:
        raise FailClosed("S02-2 result tree contains an unsealed or missing file")
    if any(s02.get(flag) is not True for flag in ("S02_MEAN_FULL_REPRODUCED", "S02_FINAL_POSITION_PROBE_FIT", "S02_RESULT_READY")):
        raise FailClosed("S02-2 result flags are not complete")
    if any(s02.get(flag) is not False for flag in ("FAS00_SENSOR_PASS", "FAS00_PHASE4_AUTHORIZED", "S02_ADAPTIVE_MECHANISM_AUTHORIZED")):
        raise FailClosed("S02-2 result flags crossed a forbidden boundary")
    if s02.get("probe_training_count") != 1:
        raise FailClosed("S02-2 result seal probe count is inconsistent")
    if sha_file(MEAN_PROBE) != binding["mean_full_probe_sha256"]:
        raise FailClosed("Mean probe identity mismatch")
    if sha_file(S02_FINAL_PROBE) != binding["final_position_probe_sha256"]:
        raise FailClosed("Final-position probe identity mismatch")
    if sha_file(PHASE3_CORE) != binding["probe_core_source_sha256"]:
        raise FailClosed("FAS Phase 3 probe math source changed")

    execution = read_json(S02_RUN / "results-v01" / "execution-receipt-v01.json")
    if execution.get("probe_training_count") != 1 or execution.get("model_loaded") is not False or execution.get("LFM_reextracted") is not False:
        raise FailClosed("S02 execution receipt includes an unauthorized operation")
    if execution.get("S02_RESULT_READY") is not True:
        raise FailClosed("S02 execution receipt is not complete")
    if (execution.get("phase1_corpus_sha256") != contract["parents"]["fas00_phase1_corpus_sha256"] or
            execution.get("phase2a_cache_root_sha256") != p2a["root_sha256"] or
            execution.get("phase3_result_root_sha256") != contract["parents"]["fas00_phase3_result_root_sha256"] or
            execution.get("s02_1_phase_root_sha256") != s02_1["root_sha256"] or
            execution.get("reference_probe_sha256") != binding["mean_full_probe_sha256"] or
            execution.get("final_position_probe_sha256") != binding["final_position_probe_sha256"]):
        raise FailClosed("S02 execution receipt does not bind the authorized parent artifacts")
    return {
        "phase1_root_sha256": p1["root_sha256"],
        "phase1_corpus_sha256": contract["parents"]["fas00_phase1_corpus_sha256"],
        "phase2a_cache_root_sha256": p2a["root_sha256"],
        "phase3_result_root_sha256": phase3["root_sha256"],
        "s02_1_phase_root_sha256": s02_1["root_sha256"],
        "s02_1_cache_root_sha256": fp_cache["root_sha256"],
        "s02_2_result_root_sha256": s02["root_sha256"],
        "mean_probe_sha256": sha_file(MEAN_PROBE),
        "final_position_probe_sha256": sha_file(S02_FINAL_PROBE),
        "probe_core_sha256": sha_file(PHASE3_CORE),
    }


def load_feature_manifests(events: list[dict], selected_indices: set[int], mean_features: np.memmap, final_features: np.memmap) -> dict[int, dict]:
    selected = {}
    with P2A_ROWS.open("r", encoding="utf-8") as mean_stream, (S02_1_CACHE / "final-position-rows-v01.jsonl").open("r", encoding="utf-8") as final_stream:
        for index, event in enumerate(events):
            full_line = mean_stream.readline()
            query_line = mean_stream.readline()
            final_line = final_stream.readline()
            if not full_line or not query_line or not final_line:
                raise FailClosed("Feature row manifests ended before the event corpus")
            full = json.loads(full_line)
            final = json.loads(final_line)
            expected_rendered = event.get("rendered_event_sha256")
            if (full.get("row_index") != 2 * index or full.get("input_view") != "FULL" or
                    full.get("event_id") != event.get("event_id") or full.get("source_rendered_event_sha256") != expected_rendered):
                raise FailClosed(f"mean_full row identity mismatch at corpus row {index}")
            if (final.get("output_row_index") != index or final.get("event_id") != event.get("event_id") or
                    final.get("source_rendered_event_sha256") != expected_rendered or final.get("selected_position") != final.get("sequence_length", 0) - 1):
                raise FailClosed(f"final_position row identity mismatch at corpus row {index}")
            if index in selected_indices:
                mean_sha = sha_bytes(mean_features[2 * index].tobytes(order="C"))
                final_sha = sha_bytes(final_features[index].tobytes(order="C"))
                if mean_sha != full.get("feature_sha256") or final_sha != final.get("feature_sha256"):
                    raise FailClosed(f"Selected feature bytes do not match row receipts at row {index}")
                selected[index] = {
                    "event_id": event["event_id"],
                    "row_index": index,
                    "rendered_event_sha256": expected_rendered,
                    "mean_full_feature_sha256": mean_sha,
                    "final_position_feature_sha256": final_sha,
                }
        if mean_stream.readline() or mean_stream.readline() or final_stream.readline():
            raise FailClosed("Feature row manifests contain trailing rows")
    return selected


def load_predictions(path: Path) -> dict[str, dict[str, dict]]:
    rows = {slice_name: {} for slice_name in SLICES}
    for row in parse_jsonl(path):
        slice_name = row.get("slice")
        if slice_name not in rows or row["event_id"] in rows[slice_name]:
            raise FailClosed(f"Unexpected or duplicate sealed prediction row in {path}")
        rows[slice_name][row["event_id"]] = row
    return rows


def preflight() -> None:
    if any((RUN / name).exists() for name in OUTPUT_NAMES):
        raise FailClosed("S03 output exists; refusing overwrite")
    RUN.mkdir(parents=True, exist_ok=True)
    construction = verify_construction()
    parents = verify_parent_seals()
    contract = read_json(CONTRACT_PATH)
    if sha_file(P1_CORPUS) != contract["parents"]["fas00_phase1_corpus_sha256"]:
        raise FailClosed("Phase 1 corpus changed during preflight")

    for path, expected, label in (
        (P2A_TENSOR, "6205b7d7a224b798b387886b43ec27103b37f091dccd9b623847cb7a52b0c8c2", "Phase 2A tensor"),
        (P2A_ROWS, "6ee54626d0da6e1b3fab5f544e9af9f4c68f0afd5045bc39d62994e0a629011b", "Phase 2A rows"),
        (S02_1_CACHE / "final-position-v01.f32le", "e4ef40343b10761236abdd2e77bb06aff69edb1ffe91a9344cf029a09790e3ba", "final-position tensor"),
        (S02_1_CACHE / "final-position-rows-v01.jsonl", "279a2cefcda70842b7bff8b1072d0ee590dbb0a13c0c16f181a1df62ad2aa9f2", "final-position rows"),
    ):
        if sha_file(path) != expected:
            raise FailClosed(f"{label} hash mismatch")

    events = list(parse_jsonl(P1_CORPUS))
    if len(events) != EVENTS or len({e["event_id"] for e in events}) != EVENTS:
        raise FailClosed("Phase 1 event count or event identity is invalid")
    masks = {name: [] for name in SLICES}
    selected_indices: set[int] = set()
    selection_rows = []
    for index, event in enumerate(events):
        in_test = 24 <= int(event["world_seed"]) <= 31 and event.get("surface_template_id") == 5
        observed = event.get("observation_text") is not None
        context = bool(in_test and observed and event.get("context_term_id") == 3)
        entity = bool(in_test and observed and event.get("entity_term_id") == 7)
        if context:
            masks[SLICES[0]].append(index)
        if entity:
            masks[SLICES[1]].append(index)
        if context or entity:
            selected_indices.add(index)
            selection_rows.append({
                "row_index": index,
                "event_id": event["event_id"],
                "world_seed": event["world_seed"],
                "world_family": event["world_family"],
                "task_structure": event["task_structure"],
                "feedback_condition": event["feedback_condition"],
                "time_step": event["time_step"],
                "context_id": event["context_id"],
                "entity_id": event["entity_id"],
                "relation_id": event["relation_id"],
                "key_id": event["key_id"],
                "context_term_id": event["context_term_id"],
                "entity_term_id": event["entity_term_id"],
                "observation_answer_index": event["observation_answer_index"],
                "exact_target": event["exact_target"],
                "rendered_event_sha256": event["rendered_event_sha256"],
                "context_slice": context,
                "entity_slice": entity,
            })
    expected_counts = {SLICES[0]: 412, SLICES[1]: 212}
    observed_counts = {name: len(indices) for name, indices in masks.items()}
    if observed_counts != expected_counts or len(selected_indices) != 512:
        raise FailClosed(f"S03 event-selection counts mismatch: {observed_counts}, union={len(selected_indices)}")
    intersection = len(set(masks[SLICES[0]]) & set(masks[SLICES[1]]))
    if intersection != 112:
        raise FailClosed(f"S03 event intersection mismatch: {intersection}")

    mean_features = np.memmap(P2A_TENSOR, dtype="<f4", mode="r", shape=(65536, WIDTH))
    final_features = np.memmap(S02_1_CACHE / "final-position-v01.f32le", dtype="<f4", mode="r", shape=(EVENTS, WIDTH))
    selected_feature_hashes = load_feature_manifests(events, selected_indices, mean_features, final_features)
    del mean_features, final_features
    if len(selected_feature_hashes) != 512:
        raise FailClosed("Selected feature identity count mismatch")
    for row in selection_rows:
        feature_ids = selected_feature_hashes[int(row["row_index"])]
        row["mean_full_feature_sha256"] = feature_ids["mean_full_feature_sha256"]
        row["final_position_feature_sha256"] = feature_ids["final_position_feature_sha256"]

    prediction_paths = {
        "mean_full": S02_RUN / "historical-reproduction-v01" / "mean-full-predictions-v01.jsonl",
        "final_position": S02_RUN / "results-v01" / "final-position-predictions-v01.jsonl",
    }
    prediction_maps = {view: load_predictions(path) for view, path in prediction_paths.items()}
    support = {}
    for slice_name in SLICES:
        indexes = masks[slice_name]
        prediction_rows = prediction_maps["mean_full"][slice_name]
        final_rows = prediction_maps["final_position"][slice_name]
        if len(prediction_rows) != len(indexes) or len(final_rows) != len(indexes):
            raise FailClosed(f"S02 prediction count mismatch for {slice_name}")
        expected_ids = {events[i]["event_id"] for i in indexes}
        if set(prediction_rows) != expected_ids or set(final_rows) != expected_ids:
            raise FailClosed(f"S02 prediction event set mismatch for {slice_name}")
        labels = []
        for index in indexes:
            event = events[index]
            event_id = event["event_id"]
            label = int(event["exact_target"])
            labels.append(label)
            for rows in (prediction_rows, final_rows):
                saved = rows[event_id]
                if saved.get("row_index") != index or saved.get("world_seed") != event["world_seed"] or saved.get("label") != label:
                    raise FailClosed(f"S02 prediction row metadata mismatch for {event_id}")
                if saved.get("prediction") not in (0, 1, 2):
                    raise FailClosed(f"S02 prediction class invalid for {event_id}")
        support[slice_name] = np.bincount(np.asarray(labels, dtype=np.int16), minlength=3).tolist()
    if support != {SLICES[0]: [212, 134, 66], SLICES[1]: [106, 64, 42]}:
        raise FailClosed(f"S03 class support differs from contract: {support}")
    saved_paired = read_json(S02_RUN / "results-v01" / "paired-outcome-summary-v01.json")
    transition_names = ("both_correct", "mean_full_only_correct", "final_position_only_correct", "both_incorrect")
    for slice_name in SLICES:
        transition_counts = {name: 0 for name in transition_names}
        for event_id, mean_row in prediction_maps["mean_full"][slice_name].items():
            final_row = prediction_maps["final_position"][slice_name][event_id]
            mean_correct = mean_row["prediction"] == mean_row["label"]
            final_correct = final_row["prediction"] == final_row["label"]
            name = "both_correct" if mean_correct and final_correct else "mean_full_only_correct" if mean_correct else "final_position_only_correct" if final_correct else "both_incorrect"
            transition_counts[name] += 1
        if transition_counts != saved_paired["four_way_event_counts"][slice_name]:
            raise FailClosed(f"S02 paired correctness table does not reproduce for {slice_name}")

    selection_path = RUN / "selected-events-v01.jsonl"
    write_jsonl(selection_path, selection_rows)
    receipt = {
        "preflight_id": "FAS_S03_PREFLIGHT_V01",
        "status": "PASS",
        "construction_root_sha256": construction["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT_PATH),
        "authorization_sha256": sha_file(AUTH_PATH),
        "parent_binding_sha256": sha_file(PARENT_BINDING_PATH),
        "parents": parents,
        "phase1_event_count": len(events),
        "event_selection": {
            "context_slice_count": observed_counts[SLICES[0]],
            "entity_slice_count": observed_counts[SLICES[1]],
            "intersection_count": intersection,
            "unique_union_count": len(selected_indices),
            "class_support": support,
            "selected_events_sha256": sha_file(selection_path),
            "selected_feature_hash_count": len(selected_feature_hashes),
        },
        "cache_hash_checks": {
            "phase2a_tensor": sha_file(P2A_TENSOR),
            "phase2a_feature_rows": sha_file(P2A_ROWS),
            "final_position_tensor": sha_file(S02_1_CACHE / "final-position-v01.f32le"),
            "final_position_rows": sha_file(S02_1_CACHE / "final-position-rows-v01.jsonl"),
        },
        "probe_hash_checks": {
            "mean_full": sha_file(MEAN_PROBE),
            "final_position": sha_file(S02_FINAL_PROBE),
        },
        "logits_computed": False,
        "probe_fitting_performed": False,
        "model_contact_performed": False,
    }
    shutil.copyfile(CONSTRUCTION_SEAL, RUN / "construction-seal-v01.json")
    write_json(RUN / "preflight-v01.json", receipt)
    print(f"S03_PREFLIGHT_PASS union={len(selected_indices)} intersection={intersection}")


def load_probe(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as archive:
        if set(archive.files) != {"weights", "bias", "mean", "scale"}:
            raise FailClosed(f"Probe array inventory mismatch: {path}")
        arrays = {name: np.array(archive[name], dtype=np.float64, copy=True, order="C") for name in archive.files}
    expected_shapes = {"weights": (3, WIDTH), "bias": (3,), "mean": (WIDTH,), "scale": (WIDTH,)}
    for name, shape in expected_shapes.items():
        if arrays[name].shape != shape or not np.isfinite(arrays[name]).all():
            raise FailClosed(f"Probe state shape/finiteness mismatch: {path}:{name}")
    if (arrays["scale"] <= 0).any():
        raise FailClosed(f"Probe standardization scales must be positive: {path}")
    return arrays


def dist(values, signed: bool = False) -> dict:
    array = np.asarray(values, dtype=np.float64)
    if array.size == 0 or not np.isfinite(array).all():
        raise FailClosed("Empty or nonfinite descriptive distribution")
    result = {
        "n": int(array.size),
        "mean": float(array.mean()),
        "median": float(np.median(array)),
        "p10": float(np.quantile(array, 0.1, method="linear")),
        "p90": float(np.quantile(array, 0.9, method="linear")),
        "min": float(array.min()),
        "max": float(array.max()),
    }
    if signed:
        result["positive"] = int(np.count_nonzero(array > 0))
        result["zero"] = int(np.count_nonzero(array == 0))
        result["negative"] = int(np.count_nonzero(array < 0))
    return result


def score_slices(view: str, arrays: dict, features: np.memmap, selected: list[dict], saved: dict) -> tuple[dict[str, np.ndarray], dict]:
    logits_by_event: dict[str, np.ndarray] = {}
    max_duplicate_abs_delta = 0.0
    for slice_name in SLICES:
        flag = "context_slice" if slice_name == SLICES[0] else "entity_slice"
        slice_rows = [row for row in selected if row[flag]]
        if not slice_rows:
            raise FailClosed(f"No selected rows in {slice_name}")
        indices = np.asarray([int(row["row_index"]) for row in slice_rows], dtype=np.int64)
        source_indices = indices * 2 if view == "mean_full" else indices
        x = np.asarray(features[source_indices], dtype=np.float64, order="C")
        x -= arrays["mean"]
        x /= arrays["scale"]
        logits = x @ arrays["weights"].T + arrays["bias"]
        pred = np.argmax(logits, axis=1)
        for row, z, prediction in zip(slice_rows, logits, pred):
            event_id = row["event_id"]
            if int(prediction) != int(saved[slice_name][event_id]["prediction"]):
                raise FailClosed(f"Recomputed S02 prediction mismatch for {view}, {slice_name}, {event_id}")
            if event_id in logits_by_event:
                delta = float(np.max(np.abs(logits_by_event[event_id] - z)))
                max_duplicate_abs_delta = max(max_duplicate_abs_delta, delta)
                if not np.allclose(logits_by_event[event_id], z, rtol=1e-12, atol=1e-12):
                    raise FailClosed(f"Duplicate-slice logits differ for {view}, {event_id}")
            else:
                logits_by_event[event_id] = np.asarray(z, dtype=np.float64).copy()
    if len(logits_by_event) != len(selected):
        raise FailClosed(f"Scored event count mismatch for {view}")
    return logits_by_event, {"max_duplicate_slice_logit_abs_delta": max_duplicate_abs_delta}


def metric_bundle(logits: np.ndarray, labels: np.ndarray) -> dict:
    predictions = np.argmax(logits, axis=1)
    support = np.bincount(labels, minlength=3)
    correct = np.bincount(labels[labels == predictions], minlength=3)
    recall = correct / support
    return {
        "rows": int(labels.size),
        "support": support.astype(int).tolist(),
        "correct_by_class": correct.astype(int).tolist(),
        "recall_by_class": recall.astype(float).tolist(),
        "balanced_accuracy": float(recall.mean()),
        "accuracy": float(np.mean(labels == predictions)),
    }


def event_metrics(logits: np.ndarray, label: int) -> dict:
    margins = {f"{CLASSES[a]}_minus_{CLASSES[b]}": float(logits[a] - logits[b]) for a, b in PAIR_ORDER}
    rivals = {CLASSES[rival]: float(logits[label] - logits[rival]) for rival in range(3) if rival != label}
    ordered = np.sort(logits)
    return {
        "logits": [float(x) for x in logits],
        "canonical_pair_margins": margins,
        "true_vs_rival_margins": rivals,
        "target_margin": float(min(rivals.values())),
        "top_two_margin": float(ordered[-1] - ordered[-2]),
        "prediction": int(np.argmax(logits)),
        "correct": bool(int(np.argmax(logits)) == label),
    }


def summarize_rows(rows: list[dict]) -> dict:
    labels = np.asarray([r["exact_target"] for r in rows], dtype=np.int16)
    result = {"rows": len(rows), "support": np.bincount(labels, minlength=3).tolist(), "views": {}}
    view_data = {view: [r["views"][view] for r in rows] for view in ("mean_full", "final_position")}
    for view, data in view_data.items():
        logits = np.asarray([x["logits"] for x in data], dtype=np.float64)
        metric = metric_bundle(logits, labels)
        result["views"][view] = {
            "metrics": metric,
            "class_logits": {CLASSES[c]: dist(logits[:, c]) for c in range(3)},
            "canonical_pair_margins": {
                name: dist([x["canonical_pair_margins"][name] for x in data], signed=True)
                for name in ("safe_minus_risky", "safe_minus_idle", "risky_minus_idle")
            },
            "target_margin": dist([x["target_margin"] for x in data], signed=True),
            "true_vs_rival_margins": {
                rival: dist([x["true_vs_rival_margins"][rival] for x in data if rival in x["true_vs_rival_margins"]], signed=True)
                for rival in CLASSES
                if any(rival in x["true_vs_rival_margins"] for x in data)
            },
            "top_two_margin": dist([x["top_two_margin"] for x in data]),
        }
    delta_keys = {
        "logit_safe": lambda r: r["paired_delta"]["logits"][0],
        "logit_risky": lambda r: r["paired_delta"]["logits"][1],
        "logit_idle": lambda r: r["paired_delta"]["logits"][2],
        "target_margin": lambda r: r["paired_delta"]["target_margin"],
        "top_two_margin": lambda r: r["paired_delta"]["top_two_margin"],
        "safe_minus_risky": lambda r: r["paired_delta"]["canonical_pair_margins"]["safe_minus_risky"],
        "safe_minus_idle": lambda r: r["paired_delta"]["canonical_pair_margins"]["safe_minus_idle"],
        "risky_minus_idle": lambda r: r["paired_delta"]["canonical_pair_margins"]["risky_minus_idle"],
    }
    result["paired_deltas"] = {name: dist([fn(r) for r in rows], signed=True) for name, fn in delta_keys.items()}
    transitions = {key: 0 for key in ("both_correct", "mean_full_only_correct", "final_position_only_correct", "both_incorrect")}
    for row in rows:
        a = row["views"]["mean_full"]["correct"]
        b = row["views"]["final_position"]["correct"]
        key = "both_correct" if a and b else "mean_full_only_correct" if a else "final_position_only_correct" if b else "both_incorrect"
        transitions[key] += 1
    result["paired_correctness_transitions"] = transitions
    return result


def group_key(row: dict, keys: tuple[str, ...], slice_name: str) -> tuple:
    values = []
    for key in keys:
        if key == "slice":
            values.append(slice_name)
        elif key == "target_class":
            values.append(CLASSES[int(row["exact_target"])])
        else:
            values.append(row.get(key))
    return tuple(values)


def build_group_summaries(rows: list[dict]) -> list[dict]:
    axes = (
        ("slice_target_class", ("slice", "target_class")),
        ("slice_context_term_target_class", ("slice", "context_term_id", "target_class")),
        ("slice_context_identity_target_class", ("slice", "context_id", "target_class")),
        ("slice_entity_term_target_class", ("slice", "entity_term_id", "target_class")),
        ("slice_entity_identity_target_class", ("slice", "entity_id", "target_class")),
        ("slice_key_target_class", ("slice", "key_id", "target_class")),
        ("slice_world_seed_target_class", ("slice", "world_seed", "target_class")),
        ("slice_observation_state_target_class", ("slice", "observation_answer_index", "target_class")),
        ("slice_context_entity_target_class", ("slice", "context_term_id", "entity_term_id", "target_class")),
        ("slice_world_family_task_feedback_target_class", ("slice", "world_family", "task_structure", "feedback_condition", "target_class")),
    )
    output = []
    for axis_name, keys in axes:
        buckets: dict[tuple, list[dict]] = {}
        for slice_name, flag in ((SLICES[0], "context_slice"), (SLICES[1], "entity_slice")):
            for row in rows:
                if row[flag]:
                    buckets.setdefault(group_key(row, keys, slice_name), []).append(row)
        for group, members in sorted(buckets.items(), key=lambda x: tuple("" if v is None else str(v) for v in x[0])):
            summary = summarize_rows(members)
            summary["axis"] = axis_name
            summary["group"] = {key: value for key, value in zip(keys, group)}
            output.append(summary)
    return output


def paired_overlap(rows: list[dict]) -> dict:
    cells = {}
    all_transitions = {key: 0 for key in ("both_correct", "mean_full_only_correct", "final_position_only_correct", "both_incorrect")}
    both_event_ids = {key: [] for key in all_transitions}
    for row in rows:
        membership = "both" if row["context_slice"] and row["entity_slice"] else "context_only" if row["context_slice"] else "entity_only"
        cell = cells.setdefault(membership, {"rows": 0, "target_margin_delta_sign": {"positive": 0, "zero": 0, "negative": 0}, "correctness_transitions": {key: 0 for key in all_transitions}})
        cell["rows"] += 1
        delta = row["paired_delta"]["target_margin"]
        cell["target_margin_delta_sign"]["positive" if delta > 0 else "negative" if delta < 0 else "zero"] += 1
        a = row["views"]["mean_full"]["correct"]
        b = row["views"]["final_position"]["correct"]
        transition = "both_correct" if a and b else "mean_full_only_correct" if a else "final_position_only_correct" if b else "both_incorrect"
        cell["correctness_transitions"][transition] += 1
        if row["context_slice"] and row["entity_slice"]:
            all_transitions[transition] += 1
            both_event_ids[transition].append(row["event_id"])
    membership_counts = {"neither": 0, "context_only": 0, "entity_only": 0, "both": 0}
    membership_counts.update({key: value["rows"] for key, value in cells.items()})
    cells["neither"] = {
        "rows": 0,
        "target_margin_delta_sign": {"positive": 0, "zero": 0, "negative": 0},
        "correctness_transitions": {key: 0 for key in all_transitions},
    }
    return {
        "membership_counts": membership_counts,
        "membership_cells": cells,
        "intersection_correctness_transitions": all_transitions,
        "intersection_event_ids_by_transition": both_event_ids,
        "interpretation_limit": "The same event has one paired prediction and one paired margin delta; slice membership does not create separate causal context and entity effects.",
    }


def normal_geometry(probes: dict[str, dict]) -> dict:
    result = {"coordinate_note": "The views share final-layer hidden width, but their separately trained probes and standardizers differ. Cosines describe fitted coefficient vectors only.", "canonical_pair_order": [], "views": {}, "cross_view": {}}
    for a, b in PAIR_ORDER:
        pair = f"{CLASSES[a]}_minus_{CLASSES[b]}"
        result["canonical_pair_order"].append(pair)
        vectors = {}
        for view, probe in probes.items():
            normal_std = probe["weights"][a] - probe["weights"][b]
            normal_raw = normal_std / probe["scale"]
            intercept_raw = float((probe["bias"][a] - probe["bias"][b]) - np.dot(probe["mean"] / probe["scale"], normal_std))
            vectors[view] = {"standardized": normal_std, "raw": normal_raw}
            result["views"].setdefault(view, {})[pair] = {
                "standardized_normal_l2": float(np.linalg.norm(normal_std)),
                "effective_original_hidden_coordinate_normal_l2": float(np.linalg.norm(normal_raw)),
                "effective_original_hidden_coordinate_intercept": intercept_raw,
            }
        cross = {}
        for space in ("standardized", "raw"):
            left = vectors["mean_full"][space]
            right = vectors["final_position"][space]
            denom = float(np.linalg.norm(left) * np.linalg.norm(right))
            cross[f"{space}_normal_cosine"] = float(np.dot(left, right) / denom) if denom else None
        result["cross_view"][pair] = cross
    return result


def build_ledger(selected: list[dict], logits: dict[str, dict[str, np.ndarray]]) -> list[dict]:
    ledger = []
    for selected_row in selected:
        event_id = selected_row["event_id"]
        label = int(selected_row["exact_target"])
        mean = event_metrics(logits["mean_full"][event_id], label)
        final = event_metrics(logits["final_position"][event_id], label)
        delta_logits = [final["logits"][i] - mean["logits"][i] for i in range(3)]
        delta_pairs = {name: final["canonical_pair_margins"][name] - mean["canonical_pair_margins"][name] for name in mean["canonical_pair_margins"]}
        ledger.append({
            **selected_row,
            "target_class": CLASSES[label],
            "views": {"mean_full": mean, "final_position": final},
            "paired_delta": {
                "logits": delta_logits,
                "canonical_pair_margins": delta_pairs,
                "target_margin": final["target_margin"] - mean["target_margin"],
                "top_two_margin": final["top_two_margin"] - mean["top_two_margin"],
            },
        })
    return ledger


def validate_and_score() -> None:
    if not (RUN / "preflight-v01.json").is_file() or not (RUN / "selected-events-v01.jsonl").is_file():
        raise FailClosed("S03 preflight must pass before logits are computed")
    allowed_existing = {"runner-failure-v01.json", "runner-correction-v01.json", "runner-correction-seal-v01.json", "construction-seal-v01.json", "preflight-v01.json", "selected-events-v01.jsonl"}
    if any((RUN / name).exists() for name in OUTPUT_NAMES if name not in allowed_existing):
        raise FailClosed("S03 result outputs already exist; refusing overwrite")
    construction = verify_construction()
    correction = verify_runner_correction()
    parents = verify_parent_seals()
    preflight_receipt = read_json(RUN / "preflight-v01.json")
    if preflight_receipt.get("status") != "PASS" or preflight_receipt.get("construction_root_sha256") != construction["root_sha256"]:
        raise FailClosed("S03 preflight receipt does not match sealed construction")
    if sha_file(RUN / "construction-seal-v01.json") != sha_file(CONSTRUCTION_SEAL):
        raise FailClosed("S03 copied construction seal differs from source seal")
    shutil.copyfile(RUNNER_CORRECTION, RUN / "runner-correction-v01.json")
    shutil.copyfile(RUNNER_CORRECTION_SEAL, RUN / "runner-correction-seal-v01.json")
    selected = list(parse_jsonl(RUN / "selected-events-v01.jsonl"))
    if sha_file(RUN / "selected-events-v01.jsonl") != preflight_receipt["event_selection"]["selected_events_sha256"] or len(selected) != 512:
        raise FailClosed("S03 selected-event manifest changed after preflight")
    events = list(parse_jsonl(P1_CORPUS))
    for item in selected:
        event = events[int(item["row_index"])]
        if event["event_id"] != item["event_id"] or event["rendered_event_sha256"] != item["rendered_event_sha256"] or int(event["exact_target"]) != int(item["exact_target"]):
            raise FailClosed(f"Selected event manifest no longer matches corpus: {item['event_id']}")

    probes = {"mean_full": load_probe(MEAN_PROBE), "final_position": load_probe(S02_FINAL_PROBE)}
    prediction_maps = {
        "mean_full": load_predictions(S02_RUN / "historical-reproduction-v01" / "mean-full-predictions-v01.jsonl"),
        "final_position": load_predictions(S02_RUN / "results-v01" / "final-position-predictions-v01.jsonl"),
    }
    mean_features = np.memmap(P2A_TENSOR, dtype="<f4", mode="r", shape=(65536, WIDTH))
    final_features = np.memmap(S02_1_CACHE / "final-position-v01.f32le", dtype="<f4", mode="r", shape=(EVENTS, WIDTH))
    scored = {}
    duplicate_checks = {}
    scored["mean_full"], duplicate_checks["mean_full"] = score_slices("mean_full", probes["mean_full"], mean_features, selected, prediction_maps["mean_full"])
    scored["final_position"], duplicate_checks["final_position"] = score_slices("final_position", probes["final_position"], final_features, selected, prediction_maps["final_position"])
    del mean_features, final_features

    slice_metrics = {}
    sealed_metrics = read_json(S02_RUN / "results-v01" / "readout-metrics-v01.json")
    for slice_name, flag in ((SLICES[0], "context_slice"), (SLICES[1], "entity_slice")):
        members = [row for row in selected if row[flag]]
        labels = np.asarray([row["exact_target"] for row in members], dtype=np.int16)
        slice_metrics[slice_name] = {}
        for view in ("mean_full", "final_position"):
            logits = np.asarray([scored[view][row["event_id"]] for row in members], dtype=np.float64)
            metrics = metric_bundle(logits, labels)
            slice_metrics[slice_name][view] = metrics
        for view in ("mean_full", "final_position"):
            observed = slice_metrics[slice_name][view]
            if observed["support"] != ([212, 134, 66] if slice_name == SLICES[0] else [106, 64, 42]):
                raise FailClosed(f"Scored support differs from contract for {slice_name}/{view}")
            expected_ba = {
                (SLICES[0], "mean_full"): 0.5654062449331388,
                (SLICES[0], "final_position"): 0.6721651889210323,
                (SLICES[1], "mean_full"): 0.8119478137166816,
                (SLICES[1], "final_position"): 0.6675932165318957,
            }[(slice_name, view)]
            expected_metrics = sealed_metrics["views"][view]["evaluations"][slice_name]
            if (abs(observed["balanced_accuracy"] - expected_ba) > 1e-15 or
                    observed["support"] != expected_metrics["support"] or
                    observed["correct_by_class"] != expected_metrics["correct_by_class"] or
                    abs(observed["accuracy"] - expected_metrics["accuracy"]) > 1e-15 or
                    any(abs(observed["recall_by_class"][i] - expected_metrics["recall_by_class"][i]) > 1e-15 for i in range(3))):
                raise FailClosed(f"S02 metric parity failed for {slice_name}/{view}")
            saved_map = prediction_maps[view][slice_name]
            for row, prediction in zip(members, np.argmax(np.asarray([scored[view][r["event_id"]] for r in members]), axis=1)):
                if int(prediction) != int(saved_map[row["event_id"]]["prediction"]):
                    raise FailClosed(f"S02 prediction parity failed for {view}/{slice_name}")

    ledger = build_ledger(selected, scored)
    # Keep original corpus order, independent of slice membership.
    ledger.sort(key=lambda row: int(row["row_index"]))
    summary = {
        "summary_id": "FAS_S03_DESCRIPTIVE_SUMMARY_V01",
        "slices": {},
        "conditioned_margin_tables": build_group_summaries(ledger),
        "descriptive_only": True,
        "significance_tests": 0,
    }
    for slice_name, flag in ((SLICES[0], "context_slice"), (SLICES[1], "entity_slice")):
        summary["slices"][slice_name] = summarize_rows([row for row in ledger if row[flag]])
        summary["slices"][slice_name]["s02_metric_parity"] = slice_metrics[slice_name]
    overlap = paired_overlap(ledger)
    geometry = normal_geometry(probes)

    write_jsonl(RUN / "event-margin-ledger-v01.jsonl", ledger)
    write_json(RUN / "descriptive-summary-v01.json", summary)
    write_json(RUN / "membership-overlap-v01.json", overlap)
    write_json(RUN / "decision-normal-geometry-v01.json", geometry)
    receipt = {
        "receipt_id": "FAS_S03_EXECUTION_V01",
        "status": "PASS",
        "construction_root_sha256": construction["root_sha256"],
        "analysis_contract_sha256": sha_file(CONTRACT_PATH),
        "runner_correction_sha256": sha_file(RUNNER_CORRECTION),
        "runner_correction_seal_sha256": sha_file(RUNNER_CORRECTION_SEAL),
        "corrected_runner_sha256": sha_file(Path(__file__).resolve()),
        "runner_failure_receipt_sha256": correction["failure_receipt_sha256"],
        "preflight_sha256": sha_file(RUN / "preflight-v01.json"),
        "selected_events_sha256": sha_file(RUN / "selected-events-v01.jsonl"),
        "parents": parents,
        "event_rows": len(ledger),
        "slice_rows": {
            SLICES[0]: len([row for row in ledger if row["context_slice"]]),
            SLICES[1]: len([row for row in ledger if row["entity_slice"]]),
        },
        "prediction_row_parity": True,
        "balanced_accuracy_parity": True,
        "duplicate_slice_logit_checks": duplicate_checks,
        "model_contact_performed": False,
        "feature_extraction_performed": False,
        "probe_fitting_performed": False,
        "significance_testing_performed": False,
        "adaptive_mechanism_authorized": False,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "S04_OR_COMPOSITIONAL_INTERVENTION_AUTHORIZED": False,
    }
    write_json(RUN / "execution-receipt-v01.json", receipt)
    print("S03_ANALYSIS_COMPLETE; machine-readable output written; no tests or fits performed")


def result_seal() -> None:
    rows = []
    for relative in OUTPUT_NAMES:
        path = RUN / relative
        if not path.is_file():
            raise FailClosed(f"Missing S03 result output: {relative}")
        rows.append({"path": relative, "sha256": sha_file(path)})
    seal = {
        "seal_id": "FAS_S03_RESULT_TREE_V01",
        "experiment_id": "fas-s03-factor-competition-decision-geometry-v01",
        "construction_root_sha256": verify_construction()["root_sha256"],
        "runner_correction_sha256": sha_file(RUNNER_CORRECTION),
        "runner_correction_seal_sha256": sha_file(RUNNER_CORRECTION_SEAL),
        "files": rows,
        "root_sha256": canonical_root(rows),
        "S03_PARENT_INTEGRITY_PASS": True,
        "S03_S02_PREDICTION_PARITY": True,
        "S03_DECISION_GEOMETRY_READY": True,
        "S03_MODEL_CONTACT": False,
        "S03_PROBE_FITTING": False,
        "S03_SIGNIFICANCE_TESTING": False,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "S04_OR_COMPOSITIONAL_INTERVENTION_AUTHORIZED": False,
    }
    write_json(RUN / "result-tree-seal-v01.json", seal)
    actual = {p.name for p in RUN.iterdir() if p.is_file()}
    if actual != set(OUTPUT_NAMES) | {"result-tree-seal-v01.json"}:
        raise FailClosed(f"Unexpected S03 top-level result files: {sorted(actual)}")
    print(f"S03_RESULT_SEALED root={seal['root_sha256']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--preflight", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--seal-results", action="store_true")
    args = parser.parse_args()
    try:
        if args.preflight:
            preflight()
        elif args.run:
            verify_runner_correction()
            validate_and_score()
        else:
            verify_runner_correction()
            result_seal()
    except Exception as exc:
        print(f"S03_FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
