"""One sealed FAS-00 Phase 3 sensor qualification over the existing feature cache."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import platform
import sys
from collections import defaultdict
from pathlib import Path

for thread_variable in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[thread_variable] = "4"

PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-frozen-adaptive-substrate-v00")
SOURCE = PROJECT / "phase3-v02"
RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase3-v02")
DEPENDENCIES = RUN / "python-deps"
sys.path.insert(0, str(DEPENDENCIES))

import numpy as np  # noqa: E402
import scipy  # noqa: E402

from probe_core import apply_scale, fit, metrics, predict, query_only_cluster_interval, scale_from_train, self_test  # noqa: E402

WORLD_CORPUS = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase1-v03\corpus\qualification-events-v03.jsonl")
PHASE2A_RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01")
CACHE = PHASE2A_RUN / "feature-cache-v01"
RESULTS = RUN / "results-v01"
CONTRACT = PROJECT / "phase2a-v01" / "contracts" / "sensor-qualification-contract-v01.json"
CORRECTION = PROJECT / "phase2a-verifier-correction-v01"
SOURCE_SEAL = SOURCE / "seals" / "phase3-source-seal-v02.json"
PLAN = SOURCE / "execution-plan-v02.json"

SOURCE_FILES = (
    "README.md",
    "execution-plan-v02.json",
    "phase3.py",
    "probe_core.py",
    "scripts/seal-source.ps1",
    "supersession-v02.json",
)
GROUP_FIELDS = (
    "world_family",
    "task_structure",
    "feedback_condition",
    "surface_template_id",
    "world_seed",
)
POSITIVES = (
    "OBSERVATION_STATE",
    "CONTEXT_IDENTITY",
    "ENTITY_IDENTITY",
    "QUERY_RELATION",
    "EXACT_TARGET",
)
NEGATIVES = (
    "QUERY_ONLY_TARGET",
    "TEMPLATE_ID_ONLY_TARGET",
    "CONTEXT_TERM_ID_ONLY_TARGET",
    "ENTITY_TERM_ID_ONLY_TARGET",
    "TERM_PAIR_ONLY_TARGET",
    "CANDIDATE_ORDER_ONLY_TARGET",
)
EXPECTED_ROOT = "9af2c6c73a2f21608e8a2dc912d8838968eaebffb32b4b1ea0a18364e488d217"
EXPECTED_CORRECTION_ROOT = "d2c84b22e141845392e6ad51ba9ca9584778cc283953bd137518b577e857360b"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def canonical_root(rows: list[dict]) -> str:
    canonical = "".join(f"{row['path']} {row['sha256']}\n" for row in sorted(rows, key=lambda row: row["path"].casefold()))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_file_list(root: Path, rows: list[dict], expected: str) -> None:
    for row in rows:
        path = root / Path(row["path"])
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise RuntimeError(f"Sealed file mismatch: {path}")
    if canonical_root(rows) != expected:
        raise RuntimeError(f"Hash-tree root mismatch: {root}")


def verify_source(plan: dict) -> dict:
    seal = read_json(SOURCE_SEAL)
    rows = [{"path": name, "sha256": sha256_file(SOURCE / name)} for name in SOURCE_FILES]
    if seal["root_sha256"] != canonical_root(rows) or seal["files"] != sorted(rows, key=lambda row: row["path"].casefold()):
        raise RuntimeError("Phase 3 implementation source seal mismatch")
    if seal["implementation_sha256"] != sha256_file(SOURCE / "phase3.py") or seal["core_sha256"] != sha256_file(SOURCE / "probe_core.py"):
        raise RuntimeError("Phase 3 implementation hash mismatch")
    if plan["runtime"] != seal["runtime"] or sha256_file(RUN / "wheels" / "scipy-1.16.2-cp313-cp313-win_amd64.whl") != plan["runtime"]["scipy_wheel_sha256"]:
        raise RuntimeError("Frozen numerical runtime identity mismatch")
    if platform.python_version() != plan["runtime"]["python"] or np.__version__ != plan["runtime"]["numpy"] or scipy.__version__ != plan["runtime"]["scipy"]:
        raise RuntimeError("Numerical library version mismatch")
    if not Path(scipy.__file__).resolve().is_relative_to(DEPENDENCIES.resolve()):
        raise RuntimeError("SciPy was not loaded from the FAS-only dependency directory")
    return seal


def verify_parents(plan: dict) -> dict:
    if sha256_file(CONTRACT) != plan["contract_sha256"]:
        raise RuntimeError("Sensor qualification contract hash mismatch")
    correction_seal = read_json(CORRECTION / "correction-seal-v01.json")
    verify_file_list(CORRECTION, correction_seal["files"], EXPECTED_CORRECTION_ROOT)
    if correction_seal["root_sha256"] != EXPECTED_CORRECTION_ROOT or correction_seal["cache_root_sha256"] != EXPECTED_ROOT:
        raise RuntimeError("Accepted verifier correction seal mismatch")
    correction_receipt = read_json(CORRECTION / "correction-receipt-v01.json")
    cache_seal = read_json(PHASE2A_RUN / "phase2a-v01-cache-seal.json")
    verify_file_list(PHASE2A_RUN, cache_seal["files"], EXPECTED_ROOT)
    if cache_seal["root_sha256"] != EXPECTED_ROOT or plan["phase2a_cache_root_sha256"] != EXPECTED_ROOT:
        raise RuntimeError("Phase 2A cache root mismatch")
    cache_files = {"feature-cache-v01/" + path.relative_to(CACHE).as_posix() for path in CACHE.rglob("*") if path.is_file()}
    sealed_cache_files = {row["path"] for row in cache_seal["files"] if row["path"].startswith("feature-cache-v01/")}
    if cache_files != sealed_cache_files:
        raise RuntimeError("Phase 2A cache file inventory changed")
    disposition_path = PHASE2A_RUN / "phase2a-v01-cache-disposition.json"
    disposition = read_json(disposition_path)
    if sha256_file(disposition_path) != correction_receipt["disposition_sha256"]:
        raise RuntimeError("Phase 2A disposition changed after verifier correction")
    if disposition["phase2a_cache_root_sha256"] != EXPECTED_ROOT or not disposition["FAS00_FEATURE_CACHE_READY"]:
        raise RuntimeError("Phase 2A disposition is not cache-ready")
    if disposition["FAS00_SENSOR_PROBE_AUTHORIZED"] or disposition["FAS00_ONLINE_MECHANISMS_AUTHORIZED"]:
        raise RuntimeError("Phase 2A disposition crossed an authorization boundary")
    if sha256_file(WORLD_CORPUS) != plan["phase1_corpus_sha256"]:
        raise RuntimeError("Phase 1 v03 qualification corpus hash mismatch")
    cache_manifest = read_json(CACHE / "extraction-manifest-v01.json")
    if cache_manifest["feature_shape"] != [65536, 2048] or cache_manifest["input_views"] != ["FULL", "QUERY_ONLY"]:
        raise RuntimeError("Feature cache shape or view mismatch")
    return cache_seal


def load_events() -> list[dict]:
    events = []
    with WORLD_CORPUS.open("r", encoding="utf-8") as world_stream, (CACHE / "feature-rows-v01.jsonl").open("r", encoding="utf-8") as feature_stream:
        for event_index, line in enumerate(world_stream):
            world = json.loads(line)
            event_id = world["event_id"]
            for offset, view in enumerate(("FULL", "QUERY_ONLY")):
                feature_line = feature_stream.readline()
                if not feature_line:
                    raise RuntimeError("Feature receipt ended before world corpus")
                row = json.loads(feature_line)
                if (row["row_index"] != event_index * 2 + offset or row["event_id"] != event_id or
                    row["input_view"] != view or row["source_rendered_event_sha256"] != world["rendered_event_sha256"] or
                    row["feature_shape"] != [2048]):
                    raise RuntimeError(f"Event-to-feature identity mismatch at event {event_index}")
            candidate_order = tuple(world["candidate_identities_in_order"])
            if (sorted(candidate_order) != [0, 1, 2] or world["world_seed"] not in range(32) or
                world["surface_template_id"] not in (3, 4, 5) or world["context_term_id"] not in (2, 3) or
                world["entity_term_id"] not in (4, 5, 6, 7) or world["relation_id"] not in (0, 1) or
                world["exact_target"] not in (0, 1, 2)):
                raise RuntimeError(f"Unexpected qualification label domain at event {event_index}")
            observation = world["observation_answer_index"]
            if (world["observation_text"] is None) != (observation is None) or observation not in (None, 0, 1, 2):
                raise RuntimeError(f"Observation label mismatch at event {event_index}")
            events.append({
                "event_id": event_id,
                "world_family": world["world_family"],
                "world_seed": world["world_seed"],
                "task_structure": world["task_structure"],
                "feedback_condition": world["feedback_condition"],
                "surface_template_id": world["surface_template_id"],
                "context_term_id": world["context_term_id"],
                "entity_term_id": world["entity_term_id"],
                "relation_id": world["relation_id"],
                "observation_answer_index": observation,
                "exact_target": world["exact_target"],
                "candidate_order": candidate_order,
            })
        if feature_stream.readline():
            raise RuntimeError("Feature receipt has rows beyond world corpus")
    if len(events) != 32768:
        raise RuntimeError(f"Expected 32768 qualification events, found {len(events)}")
    return events


def selected_partitions(events: list[dict]) -> dict[str, np.ndarray]:
    partitions: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    for index, event in enumerate(events):
        seed, template = event["world_seed"], event["surface_template_id"]
        if seed <= 15 and template in (3, 4):
            partitions["train"].append(index)
        elif 16 <= seed <= 23 and template == 5:
            partitions["validation"].append(index)
        elif 24 <= seed <= 31 and template == 5:
            partitions["test"].append(index)
    if any(not rows for rows in partitions.values()):
        raise RuntimeError("Frozen grouped seed/template split has an empty partition")
    return {name: np.asarray(rows, dtype=np.int32) for name, rows in partitions.items()}


def one_hot(categories: np.ndarray, dimension: int) -> np.ndarray:
    out = np.zeros((categories.size, dimension), dtype=np.float64)
    out[np.arange(categories.size), categories] = 1.0
    return out


def group_metrics(events: list[dict], indexes: np.ndarray, y: np.ndarray, prediction: np.ndarray, classes: int) -> dict:
    result = {}
    for field in GROUP_FIELDS:
        positions: dict[str, list[int]] = defaultdict(list)
        for position, index in enumerate(indexes):
            positions[str(events[int(index)][field])].append(position)
        result[field] = {key: metrics(y[location], prediction[location], classes) for key, location in sorted(positions.items())}
    return result


def execute_probe(
    probe_id: str,
    view: str,
    matrix: np.ndarray,
    labels: np.ndarray,
    classes: int,
    train_indexes: np.ndarray,
    evaluation_indexes: dict[str, np.ndarray],
    events: list[dict],
    artifact_root: Path,
    score_stream,
) -> dict:
    support = {name: np.bincount(labels[indexes], minlength=classes).tolist() for name, indexes in evaluation_indexes.items()}
    support_pass = all(min(counts) >= 30 for counts in support.values())
    record = {
        "probe_id": probe_id,
        "view": view,
        "classes": classes,
        "class_support": support,
        "class_support_pass": support_pass,
        "evaluations": {},
        "solver": None,
    }
    if not support_pass:
        record["failure"] = "class support below 30 in a fitted or scored slice"
        return record

    training, mean, scale = scale_from_train(matrix[train_indexes])
    model = fit(training, labels[train_indexes], classes)
    record["solver"] = {key: value for key, value in model.items() if key not in ("weights", "bias")}
    if not model["converged"]:
        record["failure"] = "fixed L-BFGS did not meet the 1e-8 gradient infinity-norm gate"
        return record

    artifact_path = artifact_root / f"{probe_id}.npz"
    np.savez(artifact_path, weights=model["weights"], bias=model["bias"], mean=mean, scale=scale)
    record["artifact_sha256"] = sha256_file(artifact_path)
    for partition, indexes in evaluation_indexes.items():
        transformed = training if partition == "train" else apply_scale(matrix[indexes], mean, scale)
        prediction = predict(transformed, model["weights"], model["bias"])
        actual = labels[indexes]
        record["evaluations"][partition] = {
            "overall": metrics(actual, prediction, classes),
            "by": group_metrics(events, indexes, actual, prediction, classes),
        }
        for index, label, predicted in zip(indexes, actual, prediction):
            row = {
                "probe_id": probe_id,
                "partition": partition,
                "event_id": events[int(index)]["event_id"],
                "world_seed": events[int(index)]["world_seed"],
                "label": int(label),
                "prediction": int(predicted),
            }
            score_stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    return record


def main_run() -> None:
    plan = read_json(PLAN)
    source_seal = verify_source(plan)
    verify_parents(plan)
    events = load_events()
    partitions = selected_partitions(events)
    contract = read_json(CONTRACT)
    if ([probe["probe_id"] for probe in contract["positive_probes"]] != list(POSITIVES) or
        [control["control_id"] for control in contract["negative_controls"]] != list(NEGATIVES)):
        raise RuntimeError("Frozen contract probe inventory mismatch")
    if RESULTS.exists():
        raise RuntimeError("Refusing to overwrite an existing Phase 3 result identity")

    features = np.memmap(CACHE / "features-v01.f32le", mode="r", dtype="<f4", shape=(65536, 2048))
    full, query = features[::2], features[1::2]
    observation = np.asarray([event["observation_answer_index"] if event["observation_answer_index"] is not None else -1 for event in events], dtype=np.int16)
    target = np.asarray([event["exact_target"] for event in events], dtype=np.int16)
    context = np.asarray([event["context_term_id"] - 2 for event in events], dtype=np.int16)
    entity = np.asarray([event["entity_term_id"] - 4 for event in events], dtype=np.int16)
    relation = np.asarray([event["relation_id"] for event in events], dtype=np.int16)
    template = np.asarray([event["surface_template_id"] - 3 for event in events], dtype=np.int16)
    permutations = {value: index for index, value in enumerate(itertools.permutations((0, 1, 2)))}
    candidate = np.asarray([permutations[event["candidate_order"]] for event in events], dtype=np.int16)
    metadata = {
        "TEMPLATE_ID_ONLY_TARGET": one_hot(template, 3),
        "CONTEXT_TERM_ID_ONLY_TARGET": one_hot(context, 2),
        "ENTITY_TERM_ID_ONLY_TARGET": one_hot(entity, 4),
        "TERM_PAIR_ONLY_TARGET": one_hot(context * 4 + entity, 8),
        "CANDIDATE_ORDER_ONLY_TARGET": one_hot(candidate, 6),
    }
    observed = {name: indexes[observation[indexes] >= 0] for name, indexes in partitions.items()}
    transfer_train = observed["train"][(context[observed["train"]] != 1) & (entity[observed["train"]] != 3)]
    transfer_context = observed["test"][context[observed["test"]] == 1]
    transfer_entity = observed["test"][entity[observed["test"]] == 3]
    train_obs_eval = {"train": observed["train"], "validation": observed["validation"], "test": observed["test"]}
    all_eval = dict(partitions)
    specs = [
        ("OBSERVATION_STATE", "FULL", full, observation, 3, train_obs_eval),
        ("CONTEXT_IDENTITY", "FULL", full, context, 2, all_eval),
        ("ENTITY_IDENTITY", "FULL", full, entity, 4, all_eval),
        ("QUERY_RELATION", "FULL", full, relation, 2, all_eval),
        ("EXACT_TARGET", "FULL", full, target, 3, train_obs_eval),
        ("HELDOUT_TERM_EXACT_TARGET", "FULL", full, target, 3, {"train": transfer_train, "test_context_term_3": transfer_context, "test_entity_term_7": transfer_entity}),
        ("QUERY_ONLY_TARGET", "QUERY_ONLY", query, target, 3, all_eval),
        *[(probe_id, "METADATA_ONLY", metadata[probe_id], target, 3, all_eval) for probe_id in NEGATIVES[1:]],
    ]

    RESULTS.mkdir(parents=True, exist_ok=False)
    artifacts = RESULTS / "probe-artifacts"
    artifacts.mkdir()
    report = {
        "report_id": "FAS00_PHASE3_SENSOR_QUALIFICATION_V01",
        "contract_sha256": plan["contract_sha256"],
        "source_root_sha256": source_seal["root_sha256"],
        "phase2a_cache_root_sha256": EXPECTED_ROOT,
        "verifier_correction_root_sha256": EXPECTED_CORRECTION_ROOT,
        "selected_rows": {name: int(indexes.size) for name, indexes in partitions.items()},
        "probe_results": {},
    }
    with (RESULTS / "scores-v01.jsonl").open("w", encoding="utf-8", newline="\n") as score_stream:
        for number, (probe_id, view, matrix, labels, classes, evaluations) in enumerate(specs, start=1):
            print(f"FAS00_PHASE3_PROGRESS probe={number}/{len(specs)} id={probe_id}", flush=True)
            result = execute_probe(probe_id, view, matrix, labels, classes, evaluations["train"], evaluations, events, artifacts, score_stream)
            report["probe_results"][probe_id] = result

    no_signal = []
    target_leakage = []
    surface_shortcut = []
    positive_rules = {probe["probe_id"]: probe for probe in contract["positive_probes"]}
    for probe_id in POSITIVES:
        result = report["probe_results"][probe_id]
        if "failure" in result:
            no_signal.append({"probe_id": probe_id, "reason": result["failure"]})
            continue
        minimum = positive_rules[probe_id]["minimum"]
        for partition in ("validation", "test"):
            value = result["evaluations"][partition]["overall"]["balanced_accuracy"]
            if value is None or value < minimum:
                no_signal.append({"probe_id": probe_id, "partition": partition, "balanced_accuracy": value, "minimum": minimum})

    transfer = report["probe_results"]["HELDOUT_TERM_EXACT_TARGET"]
    if "failure" in transfer:
        no_signal.append({"probe_id": transfer["probe_id"], "reason": transfer["failure"]})
    else:
        for slice_rule, partition in zip(contract["heldout_term_transfer"]["test_slices"], ("test_context_term_3", "test_entity_term_7")):
            value = transfer["evaluations"][partition]["overall"]["balanced_accuracy"]
            if value is None or value < slice_rule["minimum"]:
                no_signal.append({"probe_id": transfer["probe_id"], "partition": partition, "balanced_accuracy": value, "minimum": slice_rule["minimum"]})

    controls = {control["control_id"]: control for control in contract["negative_controls"]}
    query_result = report["probe_results"]["QUERY_ONLY_TARGET"]
    if "failure" in query_result:
        no_signal.append({"probe_id": "QUERY_ONLY_TARGET", "reason": query_result["failure"]})
    else:
        test_scores = query_result["evaluations"]["test"]
        per_seed = np.asarray([test_scores["by"]["world_seed"][str(seed)]["accuracy"] for seed in range(24, 32)], dtype=np.float64)
        ci = query_only_cluster_interval(per_seed)
        query_result["test_seed_cluster_interval"] = ci
        pooled = test_scores["overall"]["accuracy"]
        if (pooled > controls["QUERY_ONLY_TARGET"]["maximum"] or
            ci["point_estimate"] > controls["QUERY_ONLY_TARGET"]["maximum"] or
            ci["upper_95"] > controls["QUERY_ONLY_TARGET"]["upper_95_percent_confidence_bound_maximum"]):
            target_leakage.append({"probe_id": "QUERY_ONLY_TARGET", "pooled_accuracy": pooled, **ci})

    for probe_id in NEGATIVES[1:]:
        result = report["probe_results"][probe_id]
        if "failure" in result:
            no_signal.append({"probe_id": probe_id, "reason": result["failure"]})
            continue
        value = result["evaluations"]["test"]["overall"]["accuracy"]
        if value > controls[probe_id]["maximum"]:
            surface_shortcut.append({"probe_id": probe_id, "test_accuracy": value, "maximum": controls[probe_id]["maximum"]})

    failures = {"no_signal": no_signal, "target_leakage": target_leakage, "surface_shortcut": surface_shortcut}
    report["gate_failures"] = failures
    if target_leakage:
        disposition_name = "SENSOR_FAIL_TARGET_LEAKAGE"
    elif surface_shortcut:
        disposition_name = "SENSOR_FAIL_SURFACE_SHORTCUT"
    elif no_signal:
        disposition_name = "SENSOR_FAIL_NO_SIGNAL"
    else:
        disposition_name = "SENSOR_PASS"
    report["disposition"] = disposition_name
    write_json(RESULTS / "sensor-report-v01.json", report)
    disposition = {
        "disposition_id": "FAS00_PHASE3_SENSOR_V01",
        "project_id": "fas-frozen-adaptive-substrate-v00",
        "disposition": disposition_name,
        "FAS00_SENSOR_PASS": disposition_name == "SENSOR_PASS",
        "FAS00_ONLINE_MECHANISMS_AUTHORIZED": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "FAS00_PHASE5_AUTHORIZED": False,
        "phase2a_cache_root_sha256": EXPECTED_ROOT,
        "phase3_source_root_sha256": source_seal["root_sha256"],
        "probe_training_performed": True,
    }
    write_json(RESULTS / "sensor-disposition-v01.json", disposition)
    artifact_hashes = {path.name: sha256_file(path) for path in sorted(artifacts.glob("*.npz"))}
    receipt = {
        "receipt_id": "FAS00_PHASE3_EXECUTION_V01",
        "project_id": "fas-frozen-adaptive-substrate-v00",
        "contract_sha256": plan["contract_sha256"],
        "phase3_source_root_sha256": source_seal["root_sha256"],
        "phase2a_cache_root_sha256": EXPECTED_ROOT,
        "verifier_correction_root_sha256": EXPECTED_CORRECTION_ROOT,
        "phase1_corpus_sha256": plan["phase1_corpus_sha256"],
        "runtime": plan["runtime"],
        "selected_rows": report["selected_rows"],
        "fit_count": len(specs),
        "probe_artifacts_sha256": artifact_hashes,
        "scores_sha256": sha256_file(RESULTS / "scores-v01.jsonl"),
        "report_sha256": sha256_file(RESULTS / "sensor-report-v01.json"),
        "disposition_sha256": sha256_file(RESULTS / "sensor-disposition-v01.json"),
        "disposition": disposition_name,
        "FAS00_ONLINE_MECHANISMS_AUTHORIZED": False,
    }
    write_json(RESULTS / "phase3-execution-receipt-v01.json", receipt)
    rows = [{"path": path.relative_to(RESULTS).as_posix(), "sha256": sha256_file(path)} for path in RESULTS.rglob("*") if path.is_file()]
    result_root = canonical_root(rows)
    seal = {
        "seal_id": "FAS00_PHASE3_RESULT_V01",
        "project_id": "fas-frozen-adaptive-substrate-v00",
        "phase3_source_root_sha256": source_seal["root_sha256"],
        "phase2a_cache_root_sha256": EXPECTED_ROOT,
        "root_sha256": result_root,
        "files": sorted(rows, key=lambda row: row["path"]),
    }
    write_json(RESULTS / "phase3-result-seal-v01.json", seal)
    print(f"FAS00_PHASE3_SEALED disposition={disposition_name} root_sha256={result_root} files={len(rows)}", flush=True)


def verify_result() -> None:
    plan = read_json(PLAN)
    source_seal = verify_source(plan)
    verify_parents(plan)
    seal = read_json(RESULTS / "phase3-result-seal-v01.json")
    verify_file_list(RESULTS, seal["files"], seal["root_sha256"])
    current = {path.relative_to(RESULTS).as_posix() for path in RESULTS.rglob("*") if path.is_file()}
    if current != {row["path"] for row in seal["files"]} | {"phase3-result-seal-v01.json"}:
        raise RuntimeError("Phase 3 result file inventory changed")
    disposition = read_json(RESULTS / "sensor-disposition-v01.json")
    receipt = read_json(RESULTS / "phase3-execution-receipt-v01.json")
    if (seal["phase3_source_root_sha256"] != source_seal["root_sha256"] or
        disposition["FAS00_ONLINE_MECHANISMS_AUTHORIZED"] or
        disposition["FAS00_PHASE4_AUTHORIZED"] or
        receipt["disposition"] != disposition["disposition"] or
        disposition["FAS00_SENSOR_PASS"] != (disposition["disposition"] == "SENSOR_PASS")):
        raise RuntimeError("Phase 3 disposition or authorization boundary mismatch")
    print(f"FAS00_PHASE3_RESULT_VERIFIED disposition={disposition['disposition']} root_sha256={seal['root_sha256']} files={len(seal['files'])}")


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--self-test", action="store_true")
    group.add_argument("--run", action="store_true")
    group.add_argument("--verify-result", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("FAS00_PHASE3_SYNTHETIC_SELF_TEST_PASS")
    elif args.run:
        main_run()
    else:
        verify_result()


if __name__ == "__main__":
    main()
