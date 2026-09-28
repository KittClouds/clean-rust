from __future__ import annotations

import hashlib
import json
import math
import shutil
from collections import defaultdict
from pathlib import Path

import numpy as np


PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s01-frozen-sensor-transfer-cartography")
FAS00 = Path(r"C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00")
RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
OUTPUT = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography\read-only-cartography-v01")
CONTRACT_PATH = PROJECT / "contracts" / "read-only-cartography-contract-v01.json"
PROJECT_SEAL_PATH = PROJECT / "seals" / "project-seal-v01.json"
CORPUS = RUN / "phase1-v03" / "corpus" / "qualification-events-v03.jsonl"
FEATURE_DIR = RUN / "phase2a-v01" / "feature-cache-v01"
FEATURE_ROWS = FEATURE_DIR / "feature-rows-v01.jsonl"
FEATURE_BYTES = FEATURE_DIR / "features-v01.f32le"
PHASE3_RESULTS = RUN / "phase3-v02" / "results-v01"
SCORES = PHASE3_RESULTS / "scores-v01.jsonl"
PROBE_ID = "HELDOUT_TERM_EXACT_TARGET"
CONTEXT_PARTITION = "test_context_term_3"
ENTITY_PARTITION = "test_entity_term_7"
EXPECTED_PROJECT_ROOT = "894b4a0c6db98a5d84fe75589168715a00660d48917e47b0c21bb794a2fc3777"
EXPECTED_CONTRACT_SHA = "660a76946b7652206e3d823de97dd89947531ebb33f3fa13d35aeeb8dadcb69f"
EXPECTED_FAS00_CLOSURE_ROOT = "870e1d29d7db3dd458f16fcb56315f6976e5a4f35ba5731d642b3330a8d7d652"
EXPECTED_PHASE3_ROOT = "09fd072754e3b149ac2a9564928209a792eba091064033ca0d7f455333dda0c5"
EXPECTED_PHASE2A_ROOT = "9af2c6c73a2f21608e8a2dc912d8838968eaebffb32b4b1ea0a18364e488d217"
EXPECTED_PHASE1_ROOT = "d3ca9f8ef988a6f0ae93318fc0ea7c504b23b3be801dbf133d66f67746a69274"
EXPECTED_CORRECTION_ROOT = "d2c84b22e141845392e6ad51ba9ca9584778cc283953bd137518b577e857360b"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8")


def rows(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def nearest_rank(values: np.ndarray, quantile: float) -> float:
    ordered = np.sort(np.asarray(values, dtype=np.float64))
    if ordered.size == 0:
        raise ValueError("nearest-rank summary requires at least one value")
    index = max(0, math.ceil(quantile * ordered.size) - 1)
    return float(ordered[index])


def distribution(values: np.ndarray) -> dict:
    vector = np.asarray(values, dtype=np.float64)
    if vector.size == 0:
        return {"n": 0, "median": None, "p25": None, "p75": None}
    return {
        "n": int(vector.size),
        "median": nearest_rank(vector, 0.50),
        "p25": nearest_rank(vector, 0.25),
        "p75": nearest_rank(vector, 0.75),
    }


def check_authorized_inputs() -> tuple[dict, dict, dict, dict, dict, dict]:
    project_seal = read_json(PROJECT_SEAL_PATH)
    contract = read_json(CONTRACT_PATH)
    identity = read_json(PROJECT / "contracts" / "project-identity-v01.json")
    closure = read_json(FAS00 / "closure-v01" / "seals" / "closure-seal-v01.json")
    phase3_receipt = read_json(PHASE3_RESULTS / "phase3-execution-receipt-v01.json")
    phase3_report = read_json(PHASE3_RESULTS / "sensor-report-v01.json")
    if project_seal["root_sha256"] != EXPECTED_PROJECT_ROOT or project_seal["project_id"] != "fas-s01-frozen-sensor-transfer-cartography":
        raise RuntimeError("S01 construction seal identity mismatch")
    if sha256_file(CONTRACT_PATH) != EXPECTED_CONTRACT_SHA:
        raise RuntimeError("S01-1 contract hash mismatch")
    if contract["execution_authorized"] is not False:
        raise RuntimeError("Sealed S01-1 contract bytes unexpectedly changed")
    if identity["cross_project_writes_authorized"] or identity["other_project_access_authorized"] or identity["FAS00_PHASE4_AUTHORIZED"]:
        raise RuntimeError("S01 project boundary mismatch")
    roots = contract["input_roots"]
    checks = {
        "fas00_terminal_closure": EXPECTED_FAS00_CLOSURE_ROOT,
        "fas00_phase3_result": EXPECTED_PHASE3_ROOT,
        "fas00_phase2a_cache": EXPECTED_PHASE2A_ROOT,
        "fas00_phase1_v03": EXPECTED_PHASE1_ROOT,
    }
    if any(roots[key] != value for key, value in checks.items()):
        raise RuntimeError("S01-1 input roots do not match the sealed parent identities")
    if closure["root_sha256"] != EXPECTED_FAS00_CLOSURE_ROOT:
        raise RuntimeError("FAS-00 closure seal mismatch")
    if (phase3_receipt["phase2a_cache_root_sha256"] != EXPECTED_PHASE2A_ROOT or
            phase3_receipt["phase3_source_root_sha256"] != "11ce804afa9c68fb461a76e5f754dd21715eed3c0336d2b6676ac9f3b9a0f264" or
            phase3_receipt["verifier_correction_root_sha256"] != EXPECTED_CORRECTION_ROOT):
        raise RuntimeError("FAS-00 Phase 3 receipt lineage mismatch")
    if (phase3_receipt["selected_rows"]["test"] != 2720 or
            sha256_file(PHASE3_RESULTS / "sensor-report-v01.json") != phase3_receipt["report_sha256"]):
        raise RuntimeError("FAS-00 Phase 3 test partition size changed")
    return project_seal, contract, identity, closure, phase3_receipt, phase3_report


def load_worlds(phase3_receipt: dict, phase3_report: dict) -> tuple[list[dict], list[int]]:
    corpus_hash = sha256_file(CORPUS)
    if corpus_hash != phase3_receipt["phase1_corpus_sha256"]:
        raise RuntimeError("FAS-00 qualification corpus hash mismatch")
    worlds = list(rows(CORPUS))
    if len(worlds) != 32768:
        raise RuntimeError(f"Expected 32768 sealed qualification events, found {len(worlds)}")
    selected = []
    seen = set()
    for index, world in enumerate(worlds):
        event_id = world["event_id"]
        if event_id in seen:
            raise RuntimeError(f"Duplicate event identity: {event_id}")
        seen.add(event_id)
        if (world["world_seed"] in range(24, 32) and world["surface_template_id"] == 5 and
                world["observation_text"] is not None):
            selected.append(index)
    expected_observed = phase3_report["probe_results"]["OBSERVATION_STATE"]["evaluations"]["test"]["overall"]["rows"]
    if len(selected) != expected_observed:
        raise RuntimeError(f"Frozen S01-1 observed test population has {len(selected)} rows, expected {expected_observed}")
    return worlds, selected


def load_feature_identity(worlds: list[dict], selected: list[int], features: np.memmap) -> list[dict]:
    selected_set = set(selected)
    selected_manifest = []
    with FEATURE_ROWS.open("r", encoding="utf-8") as stream:
        for row_index, line in enumerate(stream):
            row = json.loads(line)
            event_index = row_index // 2
            if event_index not in selected_set:
                continue
            world = worlds[event_index]
            view = "FULL" if row_index % 2 == 0 else "QUERY_ONLY"
            vector = np.asarray(features[row_index], dtype="<f4")
            if (row["row_index"] != row_index or row["event_id"] != world["event_id"] or
                    row["input_view"] != view or row["source_rendered_event_sha256"] != world["rendered_event_sha256"] or
                    row["feature_shape"] != [2048] or hashlib.sha256(vector.tobytes()).hexdigest() != row["feature_sha256"]):
                raise RuntimeError(f"Selected cache row identity mismatch at row {row_index}")
            selected_manifest.append({
                "event_id": row["event_id"],
                "row_index": row_index,
                "row_id": row["row_id"],
                "view": view,
                "rendered_event_sha256": row["source_rendered_event_sha256"],
                "feature_sha256": row["feature_sha256"],
            })
    if len(selected_manifest) != len(selected) * 2:
        raise RuntimeError("Selected feature receipt coverage mismatch")
    return selected_manifest


def load_scores(phase3_receipt: dict, worlds: list[dict]) -> dict:
    if sha256_file(SCORES) != phase3_receipt["scores_sha256"]:
        raise RuntimeError("Phase 3 score file hash mismatch")
    index = {}
    for score in rows(SCORES):
        if score["probe_id"] == PROBE_ID and score["partition"] in (CONTEXT_PARTITION, ENTITY_PARTITION):
            key = (score["event_id"], score["partition"])
            if key in index:
                raise RuntimeError(f"Duplicate sealed Phase 3 score row: {key}")
            index[key] = score
    for event_index, world in enumerate(worlds):
        if world["world_seed"] not in range(24, 32) or world["surface_template_id"] != 5 or world["observation_text"] is None:
            continue
        if world["context_term_id"] == 3:
            score = index.get((world["event_id"], CONTEXT_PARTITION))
            if score is None or score["label"] != world["exact_target"] or score["world_seed"] != world["world_seed"]:
                raise RuntimeError(f"Missing or mismatched frozen context score at event {event_index}")
        if world["entity_term_id"] == 7:
            score = index.get((world["event_id"], ENTITY_PARTITION))
            if score is None or score["label"] != world["exact_target"] or score["world_seed"] != world["world_seed"]:
                raise RuntimeError(f"Missing or mismatched frozen entity score at event {event_index}")
    return index


def metric_record(target: list[int], prediction: list[int], classes: int = 3) -> dict:
    confusion = np.zeros((classes, classes), dtype=np.int64)
    for actual, predicted in zip(target, prediction, strict=True):
        if actual not in range(classes) or predicted not in range(classes):
            raise RuntimeError("Target or frozen prediction is outside the three-class domain")
        confusion[actual, predicted] += 1
    support = confusion.sum(axis=1)
    recalls = [float(confusion[i, i] / support[i]) if support[i] else None for i in range(classes)]
    balanced = float(np.mean(recalls)) if all(value is not None for value in recalls) else None
    return {
        "n": int(confusion.sum()),
        "class_support": support.tolist(),
        "confusion_true_by_predicted": confusion.tolist(),
        "class_recall": recalls,
        "balanced_accuracy": balanced,
        "undefined_reason": "at least one exact-target class has zero support" if balanced is None else None,
    }


def transfer_confusion(worlds: list[dict], scores: dict) -> dict:
    output = {}
    groups = (
        "world_family", "task_structure", "feedback_condition", "relation_id", "world_seed"
    )
    for slice_name, term_field, term_value, partition in (
            ("test_context_term_3", "context_term_id", 3, CONTEXT_PARTITION),
            ("test_entity_term_7", "entity_term_id", 7, ENTITY_PARTITION)):
        selected = [w for w in worlds if w["world_seed"] in range(24, 32) and
                    w["surface_template_id"] == 5 and w["observation_text"] is not None and
                    w[term_field] == term_value]
        target = []
        prediction = []
        for world in selected:
            score = scores[(world["event_id"], partition)]
            target.append(int(score["label"]))
            prediction.append(int(score["prediction"]))
        record = {"overall": metric_record(target, prediction)}
        record["by"] = {}
        for field in groups:
            buckets: dict[str, tuple[list[int], list[int]]] = {}
            for world in selected:
                key = str(world[field])
                if key not in buckets:
                    buckets[key] = ([], [])
                score = scores[(world["event_id"], partition)]
                buckets[key][0].append(int(score["label"]))
                buckets[key][1].append(int(score["prediction"]))
            record["by"][field] = {
                key: metric_record(actual, predicted) for key, (actual, predicted) in sorted(buckets.items())
            }
        record["slice_definition"] = {"term_field": term_field, "term_id": term_value, "partition": partition}
        output[slice_name] = record
    return output


def load_probe_artifact(phase3_receipt: dict) -> tuple[dict, dict]:
    path = PHASE3_RESULTS / "probe-artifacts" / f"{PROBE_ID}.npz"
    expected_hash = phase3_receipt["probe_artifacts_sha256"][f"{PROBE_ID}.npz"]
    actual_hash = sha256_file(path)
    if actual_hash != expected_hash:
        raise RuntimeError("Frozen Phase 3 probe artifact hash mismatch")
    with np.load(path, allow_pickle=False) as artifact:
        model = {name: np.asarray(artifact[name], dtype=np.float64) for name in ("weights", "bias", "mean", "scale")}
    if (model["weights"].shape != (3, 2048) or model["bias"].shape != (3,) or
            model["mean"].shape != (2048,) or model["scale"].shape != (2048,)):
        raise RuntimeError("Frozen Phase 3 probe tensor shape mismatch")
    return model, {"path": str(path), "sha256": actual_hash}


def margins_for_slice(worlds: list[dict], features: np.memmap, scores: dict, model: dict,
                      term_field: str, term_value: int, partition: str) -> tuple[dict, list[dict]]:
    chosen = [(i, w) for i, w in enumerate(worlds) if w["world_seed"] in range(24, 32) and
              w["surface_template_id"] == 5 and w["observation_text"] is not None and w[term_field] == term_value]
    indexes = np.asarray([i * 2 for i, _ in chosen], dtype=np.int64)
    matrix = np.asarray(features[indexes], dtype=np.float64)
    scaled = (matrix - model["mean"]) / model["scale"]
    logits = scaled @ model["weights"].T + model["bias"]
    targets = np.asarray([int(w["exact_target"]) for _, w in chosen], dtype=np.int64)
    true_logits = logits[np.arange(targets.size), targets]
    other = logits.copy()
    other[np.arange(targets.size), targets] = -np.inf
    margins = true_logits - np.max(other, axis=1)
    saved_predictions = np.asarray([int(scores[(w["event_id"], partition)]["prediction"]) for _, w in chosen], dtype=np.int64)
    if not np.array_equal(np.argmax(logits, axis=1), saved_predictions):
        raise RuntimeError("Frozen Phase 3 logits do not reproduce the sealed row predictions")
    report = {
        "n": int(margins.size),
        "true_class_minus_best_other_logit": distribution(margins),
        "fraction_margin_le_zero": float(np.mean(margins <= 0.0)),
    }
    by = {}
    for field in ("world_family", "task_structure", "feedback_condition", "relation_id", "world_seed"):
        buckets: dict[str, list[float]] = defaultdict(list)
        for (_, world), margin in zip(chosen, margins, strict=True):
            buckets[str(world[field])].append(float(margin))
        by[field] = {key: distribution(np.asarray(values)) | {"fraction_margin_le_zero": float(np.mean(np.asarray(values) <= 0.0))}
                     for key, values in sorted(buckets.items())}
    report["by"] = by
    return report, [{"event_id": w["event_id"], "partition": partition, "margin": float(m)} for (_, w), m in zip(chosen, margins, strict=True)]


def cosine_distance_to(vector: np.ndarray, centroid: np.ndarray) -> float:
    denominator = max(float(np.linalg.norm(vector)), 1e-12) * max(float(np.linalg.norm(centroid)), 1e-12)
    return float(1.0 - float(np.dot(vector, centroid)) / denominator)


def geometry(worlds: list[dict], selected: list[int], features: np.memmap) -> dict:
    rows_by_cell_context: dict[tuple, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    rows_by_cell_entity: dict[tuple, dict[int, list[int]]] = defaultdict(lambda: defaultdict(list))
    for event_index in selected:
        world = worlds[event_index]
        base = (world["world_family"], world["task_structure"], world["feedback_condition"],
                int(world["relation_id"]), int(world["exact_target"]), int(world["observation_answer_index"]))
        rows_by_cell_context[base + (int(world["entity_term_id"]),)][int(world["context_term_id"])].append(event_index)
        rows_by_cell_entity[base + (int(world["context_term_id"]),)][int(world["entity_term_id"])].append(event_index)

    def compare(groups: dict, first: int, second: int, fixed_name: str) -> dict:
        eligible = []
        ineligible_reasons: dict[str, int] = defaultdict(int)
        ineligible = 0
        for group_key in sorted(groups, key=lambda value: tuple(str(v) for v in value)):
            by_term = groups[group_key]
            n_first = len(by_term.get(first, ()))
            n_second = len(by_term.get(second, ()))
            if n_first < 5 or n_second < 5:
                ineligible += 1
                reason = "both_below_minimum" if n_first < 5 and n_second < 5 else (
                    "first_below_minimum" if n_first < 5 else "second_below_minimum")
                ineligible_reasons[reason] += 1
                continue
            term_stats = {}
            centroids = {}
            for term, name in ((first, "first"), (second, "second")):
                indices = np.asarray([event_index * 2 for event_index in by_term[term]], dtype=np.int64)
                vectors = np.asarray(features[indices], dtype=np.float64)
                centroid = np.mean(vectors, axis=0, dtype=np.float64)
                centroids[name] = centroid
                distances = np.asarray([cosine_distance_to(vector, centroid) for vector in vectors], dtype=np.float64)
                term_stats[name] = {
                    "term_id": term,
                    "n": int(vectors.shape[0]),
                    "median_raw_cosine_distance_to_own_centroid": nearest_rank(distances, 0.50),
                }
            distance = cosine_distance_to(centroids["first"], centroids["second"])
            base_names = ("world_family", "task_structure", "feedback_condition", "relation_id",
                          "exact_target", "observation_answer_index", fixed_name)
            eligible.append({"cell": dict(zip(base_names, group_key, strict=True)),
                             "term_counts": {"first": n_first, "second": n_second},
                             "centroid_cosine_distance": distance,
                             "per_term_geometry": term_stats})
        return {
            "compared_term_ids": [first, second],
            "fixed_factor": fixed_name,
            "minimum_rows_per_term": 5,
            "candidate_cells": len(groups),
            "eligible_cell_count": len(eligible),
            "ineligible_cell_count": ineligible,
            "ineligible_reason_counts": dict(sorted(ineligible_reasons.items())),
            "eligible_cells": eligible,
        }

    return {
        "context_term_2_vs_3_holding_entity_fixed": compare(rows_by_cell_context, 2, 3, "entity_term_id"),
        "entity_term_4_vs_7_holding_context_fixed": compare(rows_by_cell_entity, 4, 7, "context_term_id"),
    }


def observation_increment(worlds: list[dict], selected: list[int], features: np.memmap,
                          term_field: str, term_value: int) -> dict:
    indexes = [i for i in selected if worlds[i][term_field] == term_value]
    full = np.asarray(features[np.asarray(indexes, dtype=np.int64) * 2], dtype=np.float64)
    query = np.asarray(features[np.asarray(indexes, dtype=np.int64) * 2 + 1], dtype=np.float64)
    delta = full - query
    full_norm = np.linalg.norm(full, axis=1)
    query_norm = np.linalg.norm(query, axis=1)
    similarity = np.sum(full * query, axis=1) / (np.maximum(full_norm, 1e-12) * np.maximum(query_norm, 1e-12))
    return {
        "n": len(indexes),
        "full_minus_query_only_l2_norm": distribution(np.linalg.norm(delta, axis=1)),
        "full_query_only_cosine_similarity": distribution(similarity),
    }


def build_markdown(report: dict) -> str:
    confusion = report["TRANSFER_CONFUSION"]
    margins = report["FROZEN_MARGIN"]
    geom = report["GLOBAL_VECTOR_GEOMETRY"]
    lines = [
        "# FAS-S01-1 Read-Only Global-Feature Cartography",
        "",
        "Disposition: `DESCRIPTIVE_MAP_COMPLETE`.",
        "",
        "This is exploratory anatomy of the revealed FAS-00 qualification split. It is not a new confirmatory evaluation and does not revise the FAS-00 sensor failure.",
        "",
        "## Fixed transfer slices",
        "",
        "| Slice | Rows | Balanced accuracy | Supports by target class |",
        "|---|---:|---:|---|",
    ]
    for name, data in confusion.items():
        metric = data["overall"]
        lines.append(f"| {name} | {metric['n']} | {metric['balanced_accuracy']:.6f} | {metric['class_support']} |")
    lines.extend(["", "## Frozen probe margins", "", "| Slice | Rows | Median margin | P25 | P75 | Fraction ≤ 0 |", "|---|---:|---:|---:|---:|---:|"])
    for name in ("test_context_term_3", "test_entity_term_7"):
        data = margins[name]
        dist = data["true_class_minus_best_other_logit"]
        lines.append(f"| {name} | {data['n']} | {dist['median']:.6f} | {dist['p25']:.6f} | {dist['p75']:.6f} | {data['fraction_margin_le_zero']:.6f} |")
    lines.extend(["", "## Matched global-vector geometry", "", "| Comparison | Eligible cells | Ineligible cells | Median between-centroid cosine distance |", "|---|---:|---:|---:|"])
    for name, data in geom.items():
        distances = [cell["centroid_cosine_distance"] for cell in data["eligible_cells"]]
        median = "undefined" if not distances else f"{nearest_rank(np.asarray(distances), 0.5):.6f}"
        lines.append(f"| {name} | {data['eligible_cell_count']} | {data['ineligible_cell_count']} | {median} |")
    lines.extend([
        "",
        "## Interpretation limits",
        "",
        "The sealed FAS-00 test partition contains one held-out context term (ID 3), one held-out entity term (ID 7), and one test surface template (ID 5). Subgroup summaries can show variation across the contracted world-family, task, feedback, relation, and seed groups; this corpus cannot estimate variation across multiple held-out context terms or test templates.",
        "",
        "All geometry uses the existing final-layer `FULL` mean vectors. `QUERY_ONLY` appears only in the contracted observation-increment calculation. No token-local, span, last-token, alternative-pooling, or nonlinear-accessibility conclusion follows from this run.",
        "",
        "No fitting, feature extraction, model loading, or adaptive mechanism was run.",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    resuming_unsealed = False
    if OUTPUT.exists():
        if ((OUTPUT / "seals" / "cartography-seal-v01.json").exists() or
                (OUTPUT / "execution-receipt-v01.json").exists()):
            raise RuntimeError(f"Refusing to overwrite a sealed or receipted S01-1 output: {OUTPUT}")
        expected_partial = {
            "cartography-report-v01.json", "fixed-probe-margins-v01.jsonl", "selected-feature-rows-v01.jsonl",
            "inputs/project-seal-v01.json", "inputs/read-only-cartography-contract-v01.json",
            "source/run-cartography-v01.py", "source/seal-result.ps1",
        }
        actual_partial = {path.relative_to(OUTPUT).as_posix() for path in OUTPUT.rglob("*") if path.is_file()}
        if actual_partial != expected_partial:
            raise RuntimeError(f"Existing unsealed S01-1 output inventory differs from the known partial attempt: {sorted(actual_partial)}")
        partial_report = read_json(OUTPUT / "cartography-report-v01.json")
        if partial_report.get("project_id") != "fas-s01-frozen-sensor-transfer-cartography":
            raise RuntimeError("Existing partial output belongs to a different identity")
        resuming_unsealed = True
    project_seal, contract, identity, closure, phase3_receipt, phase3_report = check_authorized_inputs()
    worlds, selected = load_worlds(phase3_receipt, phase3_report)
    features = np.memmap(FEATURE_BYTES, mode="r", dtype="<f4", shape=(65536, 2048))
    selected_rows = load_feature_identity(worlds, selected, features)
    score_index = load_scores(phase3_receipt, worlds)
    model, probe_identity = load_probe_artifact(phase3_receipt)

    context_margins, context_margin_rows = margins_for_slice(worlds, features, score_index, model, "context_term_id", 3, CONTEXT_PARTITION)
    entity_margins, entity_margin_rows = margins_for_slice(worlds, features, score_index, model, "entity_term_id", 7, ENTITY_PARTITION)
    report = {
        "report_id": "FASS01_READ_ONLY_CARTOGRAPHY_V01",
        "project_id": identity["project_id"],
        "disposition": "DESCRIPTIVE_MAP_COMPLETE",
        "scientific_status": contract["scientific_status"],
        "input_roots": contract["input_roots"],
        "population": {
            "rule": contract["data_selection"]["population"],
            "rows": len(selected),
            "world_seeds": [24, 25, 26, 27, 28, 29, 30, 31],
            "surface_template_ids": [5],
            "observation_text_non_null": True,
        },
        "TRANSFER_CONFUSION": transfer_confusion(worlds, score_index),
        "FROZEN_MARGIN": {
            "probe_id": PROBE_ID,
            "probe_artifact": probe_identity,
            "rule": "true-class logit minus max other-class logit using sealed weights, bias, training mean, and training scale",
            "test_context_term_3": context_margins,
            "test_entity_term_7": entity_margins,
        },
        "GLOBAL_VECTOR_GEOMETRY": geometry(worlds, selected, features),
        "OBSERVATION_INCREMENT": {
            "test_context_term_3": observation_increment(worlds, selected, features, "context_term_id", 3),
            "test_entity_term_7": observation_increment(worlds, selected, features, "entity_term_id", 7),
            "interpretation": "Input-view difference in paired global mean features; not a token-local representation.",
        },
        "scope_limit": {
            "heldout_context_term_ids": [3],
            "heldout_entity_term_ids": [7],
            "test_template_ids": [5],
            "cannot_estimate_multiple_heldout_term_or_test_template_variation": True,
            "exploratory_revealed_split": True,
            "claims_not_supported": ["context-span representations", "token-local information", "last-token representations", "relation-span information", "nonlinear accessibility", "alternative pooling"],
        },
    }

    output_parent = OUTPUT.parent
    output_parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=False, exist_ok=resuming_unsealed)
    source_dir = OUTPUT / "source"
    source_dir.mkdir(exist_ok=resuming_unsealed)
    (OUTPUT / "inputs").mkdir(exist_ok=resuming_unsealed)
    (OUTPUT / "seals").mkdir(exist_ok=resuming_unsealed)
    shutil.copy2(Path(__file__), source_dir / "run-cartography-v01.py")
    shutil.copy2(PROJECT / "scripts" / "seal-result.ps1", source_dir / "seal-result.ps1")
    shutil.copy2(CONTRACT_PATH, OUTPUT / "inputs" / CONTRACT_PATH.name)
    shutil.copy2(PROJECT_SEAL_PATH, OUTPUT / "inputs" / PROJECT_SEAL_PATH.name)

    selected_path = OUTPUT / "selected-feature-rows-v01.jsonl"
    with selected_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in selected_rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    margin_path = OUTPUT / "fixed-probe-margins-v01.jsonl"
    with margin_path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in context_margin_rows + entity_margin_rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    write_json(OUTPUT / "cartography-report-v01.json", report)
    (OUTPUT / "cartography-report-v01.md").write_text(build_markdown(report), encoding="utf-8")

    input_files = {
        "phase1_qualification_events": CORPUS,
        "phase1_manifest": RUN / "phase1-v03" / "corpus" / "corpus-manifest-v03.json",
        "phase2a_feature_rows": FEATURE_ROWS,
        "phase2a_feature_tensor": FEATURE_BYTES,
        "phase2a_cache_seal": RUN / "phase2a-v01" / "phase2a-v01-cache-seal.json",
        "phase2a_cache_disposition": RUN / "phase2a-v01" / "phase2a-v01-cache-disposition.json",
        "phase2a_verifier_correction_receipt": FAS00 / "phase2a-verifier-correction-v01" / "correction-receipt-v01.json",
        "phase2a_verifier_correction_seal": FAS00 / "phase2a-verifier-correction-v01" / "correction-seal-v01.json",
        "phase3_scores": SCORES,
        "phase3_probe_artifact": Path(probe_identity["path"]),
        "phase3_report": PHASE3_RESULTS / "sensor-report-v01.json",
        "phase3_execution_receipt": PHASE3_RESULTS / "phase3-execution-receipt-v01.json",
        "phase3_result_seal": PHASE3_RESULTS / "phase3-result-seal-v01.json",
        "phase2a_cache_seal": RUN / "phase2a-v01" / "phase2a-v01-cache-seal.json",
        "phase1_seal": FAS00 / "phase1-v03" / "seals" / "phase1-v03-seal.json",
        "fas00_closure_seal": FAS00 / "closure-v01" / "seals" / "closure-seal-v01.json",
    }
    source_files = [
        {"path": "source/run-cartography-v01.py", "sha256": sha256_file(source_dir / "run-cartography-v01.py")},
        {"path": "source/seal-result.ps1", "sha256": sha256_file(source_dir / "seal-result.ps1")},
        {"path": "inputs/read-only-cartography-contract-v01.json", "sha256": sha256_file(OUTPUT / "inputs" / CONTRACT_PATH.name)},
        {"path": "inputs/project-seal-v01.json", "sha256": sha256_file(OUTPUT / "inputs" / PROJECT_SEAL_PATH.name)},
    ]
    write_json(OUTPUT / "execution-receipt-v01.json", {
        "receipt_id": "FASS01_READ_ONLY_CARTOGRAPHY_EXECUTION_V01",
        "project_id": identity["project_id"],
        "authorization_basis": "Explicit user authorization for S01-1 in the active conversation, 2026-09-23.",
        "authorization_scope": "Sealed read-only cartography contract only; no model contact, fitting, new representations, or adaptation.",
        "contract_sha256": sha256_file(CONTRACT_PATH),
        "project_construction_root_sha256": project_seal["root_sha256"],
        "fas00_terminal_closure_root_sha256": closure["root_sha256"],
        "phase3_result_root_sha256": EXPECTED_PHASE3_ROOT,
        "phase2a_cache_root_sha256": EXPECTED_PHASE2A_ROOT,
        "phase1_v03_root_sha256": EXPECTED_PHASE1_ROOT,
        "phase2a_verifier_correction_root_sha256": EXPECTED_CORRECTION_ROOT,
        "verified_parent_checks": {
            "phase1_v03": "PASS",
            "phase2a_cache_and_correction": "PASS",
            "phase3_result": "PASS",
        },
        "input_files": {name: {"path": str(path), "sha256": sha256_file(path)} for name, path in input_files.items()},
        "selected_world_count": len(selected),
        "selected_feature_rows": len(selected_rows),
        "feature_view": "existing final-layer mean_full and query_only only",
        "new_feature_extraction": False,
        "model_loaded": False,
        "probe_training": False,
        "new_probe_fitting": False,
        "adaptive_mechanisms": False,
        "unsealed_retry": {
            "occurred": resuming_unsealed,
            "prior_attempt": "report serializer key-path error after calculations; no execution receipt or seal existed",
            "change_scope": "serializer access path only; sealed contract, input selection, and metric calculations unchanged",
        },
        "result_source_files": source_files,
    })
    print(f"FASS01_CARTOGRAPHY_COMPLETE output={OUTPUT} rows={len(selected)} context_rows={report['TRANSFER_CONFUSION']['test_context_term_3']['overall']['n']} entity_rows={report['TRANSFER_CONFUSION']['test_entity_term_7']['overall']['n']}")


if __name__ == "__main__":
    main()
