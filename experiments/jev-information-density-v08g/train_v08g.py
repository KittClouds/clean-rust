"""Matched-policy v0.8G head training on immutable frozen LFM features."""

from __future__ import annotations

import ctypes
import hashlib
import importlib.util
import json
import math
import random
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import torch

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\codex-runs\jev-information-density-v08g")
MATERIALIZED = OUT / "materialized-inputs"
FEATURES = OUT / "feature-cache" / "lfm-v08g-features.pt"
LEGACY_FEATURES = Path(
    r"D:\codex-runs\jev-lfm-variable-v07\features\lfm2.5-1.2b-base-features.pt"
)
BINDING_FEATURES = Path(
    r"D:\codex-runs\jev-lfm-variable-v07\features\binding\lfm2.5-1.2b-base-features.pt"
)
PROBE_PATH = ROOT / "experiments" / "jev-frozen-readout-v01" / "probe.py"
V05_PATH = ROOT / "experiments" / "jev-frozen-scaling-v05" / "train_v05.py"
CONTRACT_PATH = ROOT / "experiments" / "jev-information-density-v08g" / "v08g-contract.json"
PROFILE = "name_definition"
FEATURE_KEY = "mean_full@16"
BATCH_SIZE = 256
EPOCHS = 3
Brier_WEIGHT = 0.25
INVARIANCE_WEIGHT = 0.10
SEEDS = [20260927, 20260928, 20260929]
SCHEDULE = [(0, "random"), (0, "curated"), (1, "curated"),
            (1, "random"), (2, "random"), (2, "curated")]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()


def load_module(name: str, path: Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import frozen helper {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


probe = load_module("jev_v08g_probe", PROBE_PATH)
trainer = load_module("jev_v08g_train_v05", V05_PATH)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def append_event(path: Path, event: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def process_peak_rss_bytes() -> int | None:
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    try:
        psapi, kernel = ctypes.WinDLL("Psapi.dll"), ctypes.WinDLL("Kernel32.dll")
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        value = Counters()
        value.cb = ctypes.sizeof(value)
        psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        ok = psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(value), value.cb)
        return int(value.PeakWorkingSetSize) if ok else None
    except (AttributeError, OSError):
        return None


def write_json(path: Path, payload: Any) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def verify_preflight() -> dict[str, Any]:
    auth_path = OUT / "preflight" / "model-contact-authorization.json"
    auth = read_json(auth_path)
    manifest_path = OUT / "v08g-run-manifest.json"
    if auth.get("status") != "PASS" or auth.get("model_contact_authorized") is not True:
        raise RuntimeError("model-contact authorization is not PASS")
    if auth.get("phoenix_access") is not False:
        raise RuntimeError("authorization receipt permits an out-of-scope Phoenix boundary")
    if sha256_file(manifest_path) != auth.get("manifest_sha256"):
        raise RuntimeError("run manifest hash drifted after preflight")
    manifest = read_json(manifest_path)
    if sha256_file(CONTRACT_PATH) != manifest.get("contract", {}).get("sha256"):
        raise RuntimeError("frozen v0.8G contract hash does not match the run manifest")
    if auth.get("D_train") != 0.13489 or auth.get("heldout_overlap_count") != 0 or auth.get("profile_pass") is not True:
        raise RuntimeError("sealed treatment/profile/held-out values differ from the authorized run")
    materialization_path = OUT / "materialized-inputs" / "materialization-receipt.json"
    materialization = read_json(materialization_path)
    if materialization.get("status") != "EXACT_ID_INPUTS_MATERIALIZED_NO_MODEL_LOADED":
        raise RuntimeError("exact-ID materialization receipt is not valid")
    for bank_name in ("random", "curated", "new_tight_eval"):
        row = materialization["group_files"][bank_name]
        if sha256_file(Path(row["path"])) != row["sha256"]:
            raise RuntimeError(f"materialized group bank hash mismatch: {bank_name}")
    for table in materialization["representation_tables"].values():
        if sha256_file(Path(table["path"])) != table["sha256"]:
            raise RuntimeError(f"materialized representation-table hash mismatch: {table['path']}")
    feature_receipt = read_json(OUT / "feature-cache" / "extraction-receipt.json")
    if feature_receipt.get("status") != "FEATURE_EXTRACTION_COMPLETE":
        raise RuntimeError("frozen feature extraction is incomplete")
    if feature_receipt["model"]["revision"] != manifest["model"]["revision"]:
        raise RuntimeError("feature model revision does not match preflight")
    if feature_receipt["path"]["batch_size"] != 1 or feature_receipt["path"]["padding"] is not False:
        raise RuntimeError("feature extraction violated the v0.7 exact-input path")
    cache_path = Path(feature_receipt["cache"]["path"])
    if cache_path.resolve() != FEATURES.resolve() or sha256_file(cache_path) != feature_receipt["cache"]["sha256"]:
        raise RuntimeError("frozen feature cache hash mismatch")
    return {"authorization": auth, "model": manifest["model"], "feature_receipt": feature_receipt,
            "materialization": materialization, "manifest": manifest,
            "manifest_path": manifest_path, "manifest_sha256": auth["manifest_sha256"]}


def load_run_data() -> dict[str, Any]:
    frozen = verify_preflight()
    cache = torch.load(FEATURES, map_location="cpu", weights_only=False)
    if cache.get("revision") != frozen["model"]["revision"]:
        raise RuntimeError("feature cache revision mismatch")
    if cache.get("hidden_dim") != 2048 or cache.get("layer_count") != 16:
        raise RuntimeError("unexpected LFM feature dimensions")
    groups = {arm: read_jsonl(MATERIALIZED / f"{arm}-groups.jsonl")
              for arm in ("random", "curated")}
    evaluation = read_jsonl(MATERIALIZED / "new_tight_eval-groups.jsonl")
    expected_counts = {"random": 100_000, "curated": 100_000}
    for arm, rows in groups.items():
        expected_hash = frozen["materialization"]["group_files"][arm]["sha256"]
        if sha256_file(MATERIALIZED / f"{arm}-groups.jsonl") != expected_hash:
            raise RuntimeError(f"materialized {arm} group file changed")
        if len(rows) != expected_counts[arm] or len({row["group_id"] for row in rows}) != expected_counts[arm]:
            raise RuntimeError(f"{arm} training occurrences were lost or duplicated")
        if rows != sorted(rows, key=lambda row: row["group_id"]):
            raise RuntimeError(f"{arm} groups are not in the sealed deterministic input order")
        if any(row["open_world"] or row["kind"] not in {"choice", "independent"} for row in rows):
            raise RuntimeError(f"unsupported training target in {arm}")
    if len(evaluation) != 83_328:
        raise RuntimeError("NewTight-Eval group count drifted")
    if sha256_file(MATERIALIZED / "new_tight_eval-groups.jsonl") != frozen["materialization"]["group_files"]["new_tight_eval"]["sha256"]:
        raise RuntimeError("materialized NewTight-Eval group file changed")
    if any(row["open_world"] or row["kind"] not in {"choice", "independent"} for row in evaluation):
        raise RuntimeError("NewTight-Eval contains an unsupported output type")
    legacy_cache = torch.load(LEGACY_FEATURES, map_location="cpu", weights_only=False)
    binding_cache = torch.load(BINDING_FEATURES, map_location="cpu", weights_only=False)
    for old in (legacy_cache, binding_cache):
        if old.get("revision") != cache.get("revision") or old.get("hidden_dim") != cache.get("hidden_dim"):
            raise RuntimeError("legacy feature cache is not the same pinned LFM representation")
    manifest = read_json(OUT / "v08g-run-manifest.json")
    legacy_groups: dict[str, list[dict[str, Any]]] = {}
    for split in ("dev", "test", "external"):
        path = Path(manifest["frozen_inputs"]["legacy_protected"][split]["path"])
        if sha256_file(path) != manifest["frozen_inputs"]["legacy_protected"][split]["sha256"]:
            raise RuntimeError(f"protected legacy {split} manifest hash mismatch")
        selected = read_jsonl(path)
        expected = manifest["frozen_inputs"]["legacy_protected"][split]["group_count"]
        if len(selected) != expected:
            raise RuntimeError(f"protected legacy {split} manifest count mismatch")
        rows = []
        for item in selected:
            index = int(item["cache_row_index"])
            if index < 0 or index >= len(legacy_cache["groups"]):
                raise RuntimeError(f"legacy {split} cache index is out of range")
            row = legacy_cache["groups"][index]
            if row["group_id"] != item["group_id"] or row["episode_id"] != item["episode_id"]:
                raise RuntimeError(f"legacy {split} manifest/cache row identity mismatch")
            rows.append(row)
        legacy_groups[split] = rows
    binding_spec = manifest["frozen_inputs"]["contradictory_binding_eval"]["group_id_manifest"]
    binding_manifest_path = Path(binding_spec["path"])
    if sha256_file(binding_manifest_path) != binding_spec["sha256"]:
        raise RuntimeError("contradictory-binding group manifest hash mismatch")
    binding_groups = []
    for item in read_jsonl(binding_manifest_path):
        index = int(item["cache_row_index"])
        if index < 0 or index >= len(binding_cache["groups"]):
            raise RuntimeError("contradictory-binding cache row index is out of range")
        row = binding_cache["groups"][index]
        if row["group_id"] != item["group_id"] or row["episode_id"] != item["episode_id"]:
            raise RuntimeError("contradictory-binding manifest/cache identity mismatch")
        if row["kind"] != "choice" or row["open_world"]:
            raise RuntimeError("contradictory-binding manifest contains unsupported group")
        binding_groups.append(row)
    if len(binding_groups) != binding_spec["group_count"]:
        raise RuntimeError("contradictory-binding manifest row count mismatch")
    if any(not legacy_groups[name] for name in legacy_groups):
        raise RuntimeError("a required legacy evaluation surface is empty")
    # OOD flags are analysis-only: compare held-out family IDs with the union
    # of policy-arm metadata. They never select or alter training records.
    ontology_seen = {row.get("family_ids", {}).get("ontology_family")
                     for bank in groups.values() for row in bank}
    world_seen = {row.get("family_ids", {}).get("world_or_topology_family")
                  for bank in groups.values() for row in bank}
    for row in evaluation:
        families = row.get("family_ids", {})
        axes = []
        ontology = families.get("ontology_family")
        world = families.get("world_or_topology_family")
        if ontology is not None and ontology not in ontology_seen:
            axes.append("ontology_family")
        if world is not None and world not in world_seen:
            axes.append("world_or_topology_family")
        row["held_out_axes"] = axes
    return {**frozen, "cache": cache, "groups": groups, "evaluation": evaluation,
            "legacy_cache": legacy_cache, "legacy_groups": legacy_groups,
            "binding_cache": binding_cache, "binding_groups": binding_groups}


def typed_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"by_view": {}, "by_probability_source": probe.metric_summary(rows)}
    for view in sorted({row.get("view", "unknown") for row in rows}):
        subset = [row for row in rows if row.get("view", "unknown") == view]
        result["by_view"][view] = probe.metric_summary(subset)
        if view == "ordinal_score":
            exact = adjacent = 0
            rps_values: list[float] = []
            gold_expectations: list[float] = []
            pred_expectations: list[float] = []
            for row in subset:
                gold, pred = row["gold"], row["prediction"]
                if len(gold) < 2 or len(gold) != len(pred):
                    continue
                gold_rank, pred_rank = max(range(len(gold)), key=gold.__getitem__), max(range(len(pred)), key=pred.__getitem__)
                exact += int(gold_rank == pred_rank)
                adjacent += int(abs(gold_rank - pred_rank) <= 1)
                gold_expectations.append(sum(i * p for i, p in enumerate(gold)))
                pred_expectations.append(sum(i * p for i, p in enumerate(pred)))
                g_cdf = p_cdf = 0.0
                squared = 0.0
                for g, p in zip(gold[:-1], pred[:-1]):
                    g_cdf += g
                    p_cdf += p
                    squared += (g_cdf - p_cdf) ** 2
                rps_values.append(squared / (len(gold) - 1))
            result["by_view"][view]["ordinal"] = {
                "count": len(rps_values),
                "exact_accuracy": exact / max(1, len(rps_values)),
                "adjacent_accuracy": adjacent / max(1, len(rps_values)),
                "expected_rank_spearman": spearman(gold_expectations, pred_expectations),
                "ranked_probability_score_normalized": sum(rps_values) / max(1, len(rps_values)),
                "rps_definition": "mean squared CDF error across K-1 thresholds, normalized by K-1",
            }
    return result


def spearman(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2:
        return None
    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=values.__getitem__)
        output = [0.0] * len(values)
        start = 0
        while start < len(order):
            end = start + 1
            while end < len(order) and values[order[end]] == values[order[start]]:
                end += 1
            rank = (start + end - 1) / 2.0
            for position in range(start, end):
                output[order[position]] = rank
            start = end
        return output
    a, b = ranks(left), ranks(right)
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    numerator = sum((x - ma) * (y - mb) for x, y in zip(a, b))
    denominator = math.sqrt(sum((x - ma) ** 2 for x in a) * sum((y - mb) ** 2 for y in b))
    return numerator / denominator if denominator else 0.0


def score_groups(head: torch.nn.Module, groups: list[dict[str, Any]], state: torch.Tensor,
                 candidates: torch.Tensor, profile: str, device: str,
                 batch_size: int = 1024) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    head.eval()
    with torch.inference_mode():
        for start in range(0, len(groups), batch_size):
            chunk = groups[start:start + batch_size]
            state_batch, candidate_batch, _gold, mask, _kinds, _sources = trainer.fast_tensor_batch(
                chunk, state, candidates, profile, device)
            logits = head(state_batch, candidate_batch)
            for index, group in enumerate(chunk):
                values = logits[index][mask[index]]
                prediction = (torch.sigmoid(values).cpu().tolist() if group["kind"] == "independent"
                              else torch.softmax(values, dim=0).cpu().tolist())
                rows.append({
                    "group_id": group["group_id"], "episode_id": group["episode_id"],
                    "query_id": group["query_id"], "kind": group["kind"], "view": group.get("view"),
                    "profile": profile, "probability_source": group["probability_source"],
                    "authority": group.get("authority"), "split": group.get("split"),
                    "candidate_cardinality": group["candidate_cardinality"],
                    "candidate_semantic_ids": group["candidate_semantic_ids"],
                    "gold": group["gold"], "prediction": prediction,
                    "semantic_fingerprint": group.get("semantic_fingerprint"),
                    "invariant_key": group.get("invariant_key"),
                    "perturbation_class": group.get("perturbation_class"),
                    "root_id": group.get("root_id"), "family_ids": group.get("family_ids", {}),
                    "coverage_features": group.get("coverage_features", {}),
                    "held_out_axes": group.get("held_out_axes", []),
                    "open_world": group.get("open_world", False),
                })
    return rows


def score_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for key in sorted(state):
        digest.update(key.encode("utf-8"))
        digest.update(state[key].detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()


def initialize_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def atomic_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    temp = path.with_suffix(path.suffix + ".tmp")
    torch.save(payload, temp)
    temp.replace(path)


def profile_metrics(head: torch.nn.Module, groups: list[dict[str, Any]], cache: dict[str, Any],
                    device: str, profiles: tuple[str, ...]) -> dict[str, Any]:
    state = cache["features"]["state"][FEATURE_KEY].to(device)
    report: dict[str, Any] = {}
    reference_rows: list[dict[str, Any]] | None = None
    for profile in profiles:
        candidate = cache["features"]["candidate"][profile][FEATURE_KEY].to(device)
        rows = score_groups(head, groups, state, candidate, profile, device)
        report[profile] = typed_metrics(rows)
        if profile == PROFILE:
            reference_rows = rows
        elif reference_rows is not None:
            by_id = {row["group_id"]: row for row in reference_rows}
            aligned = [(by_id[row["group_id"]], row) for row in rows if row["group_id"] in by_id]
            report[profile]["paired_schema_drift_vs_name_definition"] = distribution_drift(aligned)
    return report


def distribution_drift(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, Any]:
    l1_values: list[float] = []
    flips = 0
    for left, right in pairs:
        aligned = align_values(left, right)
        if not aligned:
            continue
        p, q = aligned
        l1_values.append(sum(abs(a - b) for a, b in zip(p, q)))
        flips += int(max(range(len(p)), key=p.__getitem__) != max(range(len(q)), key=q.__getitem__))
    return {"paired_count": len(l1_values), "mean_l1": sum(l1_values) / max(1, len(l1_values)),
            "argmax_flip_rate": flips / max(1, len(l1_values))}


def align_values(left: dict[str, Any], right: dict[str, Any]) -> tuple[list[float], list[float]]:
    left_map = dict(zip(left["candidate_semantic_ids"], left["prediction"]))
    right_map = dict(zip(right["candidate_semantic_ids"], right["prediction"]))
    keys = [key for key in left["candidate_semantic_ids"] if key in right_map]
    if not keys:
        return [], []
    return [left_map[key] for key in keys], [right_map[key] for key in keys]


def training_config(contract: dict[str, Any], seed: int, arm: str, feature_sha: str) -> dict[str, Any]:
    return {"contract_sha256": sha256_file(CONTRACT_PATH), "seed": seed, "arm": arm,
            "feature_cache_sha256": feature_sha, "head": "dynamic_mlp_compatibility",
            "projection_width": 128, "profile": PROFILE, "epochs": EPOCHS,
            "batch_size": BATCH_SIZE, "optimizer": "AdamW", "lr": 0.002,
            "weight_decay": 0.01, "brier_weight": Brier_WEIGHT,
            "invariance_weight": INVARIANCE_WEIGHT,
            "train_group_sha256": sha256_file(MATERIALIZED / f"{arm}-groups.jsonl"),
            "training_order": "sort_group_id_then_random.Random(seed+epoch).shuffle"}


def fit_one(data: dict[str, Any], seed_index: int, arm: str, device: str,
            feature_sha: str) -> dict[str, Any]:
    seed = SEEDS[seed_index]
    run_name = f"seed-{seed_index + 1}/{arm}"
    run_dir = OUT / "runs" / f"seed-{seed_index + 1}" / arm
    run_dir.mkdir(parents=True, exist_ok=True)
    config = training_config(read_json(CONTRACT_PATH), seed, arm, feature_sha)
    config_hash = sha256_json(config)
    config_path = run_dir / "run-config.json"
    if config_path.exists():
        if read_json(config_path) != {**config, "config_sha256": config_hash}:
            raise RuntimeError(f"immutable run config differs for {run_name}")
    else:
        write_json(config_path, {**config, "config_sha256": config_hash})
    final_report_path = run_dir / "run-report.json"
    if final_report_path.exists():
        report = read_json(final_report_path)
        if report.get("config_sha256") != config_hash or report.get("status") != "COMPLETE":
            raise RuntimeError(f"existing {run_name} report does not match this run")
        return report

    cache = data["cache"]
    state = cache["features"]["state"][FEATURE_KEY].to(device)
    candidates = cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
    groups = data["groups"][arm]
    initialize_seed(seed)
    head = probe.CompatibilityHead(cache["hidden_dim"], "mlp", 128).to(device)
    initial_sha = score_digest(head.state_dict())
    counterpart = "curated" if arm == "random" else "random"
    counterpart_report_path = OUT / "runs" / f"seed-{seed_index + 1}" / counterpart / "run-report.json"
    if counterpart_report_path.exists():
        paired_initial = read_json(counterpart_report_path).get("initial_head_sha256")
        if paired_initial != initial_sha:
            raise RuntimeError(f"paired head initialization differs for seed {seed_index + 1}")
    optimizer = torch.optim.AdamW(head.parameters(), lr=2e-3, weight_decay=0.01)
    pairs = probe.invariant_pairs(groups, "train")
    history: list[dict[str, Any]] = []
    next_epoch = 0
    checkpoint_path = run_dir / "latest-checkpoint.pt"
    if checkpoint_path.exists():
        saved = torch.load(checkpoint_path, map_location=device, weights_only=False)
        if saved.get("config_sha256") != config_hash or saved.get("initial_head_sha256") != initial_sha:
            raise RuntimeError(f"checkpoint binding mismatch for {run_name}")
        head.load_state_dict(saved["head_state"])
        optimizer.load_state_dict(saved["optimizer_state"])
        history = saved["history"]
        next_epoch = int(saved["next_epoch"])
        if "torch_rng" in saved:
            torch.set_rng_state(saved["torch_rng"].cpu())
        if device.startswith("cuda") and saved.get("cuda_rng") is not None:
            torch.cuda.set_rng_state_all(saved["cuda_rng"])

    events = run_dir / "training-events.jsonl"
    event_stream = events.open("a", encoding="utf-8", newline="\n")
    def emit(event: dict[str, Any]) -> None:
        event_stream.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")
        event_stream.flush()
    started = time.perf_counter()
    emit({"event": "run_start", "run": run_name, "seed": seed,
          "groups": len(groups), "initial_head_sha256": initial_sha,
          "config_sha256": config_hash, "time_unix": time.time()})
    for epoch in range(next_epoch, EPOCHS):
        epoch_start = time.perf_counter()
        shuffled = list(groups)
        random.Random(seed + epoch).shuffle(shuffled)
        head.train()
        aggregate = Counter()
        batches = 0
        emit({"event": "epoch_start", "epoch": epoch + 1, "run": run_name})
        for start in range(0, len(shuffled), BATCH_SIZE):
            step_start = time.perf_counter()
            batch = shuffled[start:start + BATCH_SIZE]
            state_batch, candidate_batch, gold, mask, kinds, sources = trainer.fast_tensor_batch(
                batch, state, candidates, PROFILE, device, reorder=True)
            optimizer.zero_grad(set_to_none=True)
            logits = head(state_batch, candidate_batch)
            semantic_plus_brier, brier = trainer.v05_loss(
                logits, gold, mask, kinds, sources, Brier_WEIGHT)
            invariance = trainer.vectorized_invariant_loss(
                head, pairs, state, candidates, PROFILE, device)
            loss = semantic_plus_brier + INVARIANCE_WEIGHT * invariance
            loss.backward()
            grad_parts = [parameter.grad.detach().norm(2) for parameter in head.parameters()
                          if parameter.grad is not None]
            grad_norm = float(torch.linalg.vector_norm(torch.stack(grad_parts), 2).detach().cpu()) if grad_parts else 0.0
            optimizer.step()
            count = len(batch)
            aggregate["total_loss_sum"] += float(loss.detach().cpu()) * count
            aggregate["semantic_plus_brier_sum"] += float(semantic_plus_brier.detach().cpu()) * count
            aggregate["brier_sum"] += float(brier.detach().cpu()) * count
            aggregate["invariance_sum"] += float(invariance.detach().cpu()) * count
            aggregate["groups"] += count
            batches += 1
            emit({
                "event": "training_step", "run": run_name, "epoch": epoch + 1,
                "step": batches, "steps_in_epoch": math.ceil(len(shuffled) / BATCH_SIZE),
                "groups": count, "examples_processed": start + count,
                "loss": float(loss.detach().cpu()),
                "semantic_plus_brier": float(semantic_plus_brier.detach().cpu()),
                "brier": float(brier.detach().cpu()),
                "invariance": float(invariance.detach().cpu()), "gradient_norm": grad_norm,
                "learning_rate": optimizer.param_groups[0]["lr"],
                "groups_per_second": count / max(1e-9, time.perf_counter() - step_start),
                "cuda_allocated_bytes": int(torch.cuda.memory_allocated()) if device.startswith("cuda") else 0,
                "cuda_reserved_bytes": int(torch.cuda.memory_reserved()) if device.startswith("cuda") else 0,
                "host_peak_rss_bytes": process_peak_rss_bytes(),
            })
        train_summary = {
            "groups": aggregate["groups"], "optimizer_steps": batches,
            "loss": aggregate["total_loss_sum"] / max(1, aggregate["groups"]),
            "semantic_plus_brier": aggregate["semantic_plus_brier_sum"] / max(1, aggregate["groups"]),
            "brier": aggregate["brier_sum"] / max(1, aggregate["groups"]),
            "invariance": aggregate["invariance_sum"] / max(1, aggregate["groups"]),
        }
        epoch_eval = score_groups(head, data["evaluation"], state,
                                  cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(device),
                                  PROFILE, device)
        eval_metrics: dict[str, Any] = {"new_tight_eval": typed_metrics(epoch_eval), "legacy": {}}
        legacy_cache = data["legacy_cache"]
        legacy_state = legacy_cache["features"]["state"][FEATURE_KEY].to(device)
        legacy_candidates = legacy_cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
        for split, split_groups in data["legacy_groups"].items():
            legacy_rows = score_groups(head, split_groups, legacy_state, legacy_candidates, PROFILE, device)
            eval_metrics["legacy"][split] = typed_metrics(legacy_rows)
        epoch_record = {
            "epoch": epoch + 1, "train": train_summary, "evaluation": eval_metrics,
            "wall_seconds": time.perf_counter() - epoch_start,
            "elapsed_total_seconds": time.perf_counter() - started,
        }
        history.append(epoch_record)
        write_json(run_dir / f"epoch-{epoch + 1}.json", epoch_record)
        emit({"event": "evaluation_snapshot", "run": run_name,
              "epoch": epoch + 1, "new_tight_eval": eval_metrics["new_tight_eval"],
              "legacy": eval_metrics["legacy"]})
        atomic_checkpoint(checkpoint_path, {
            "config_sha256": config_hash, "initial_head_sha256": initial_sha,
            "head_state": head.state_dict(), "optimizer_state": optimizer.state_dict(),
            "history": history, "next_epoch": epoch + 1,
            "torch_rng": torch.get_rng_state(),
            "cuda_rng": torch.cuda.get_rng_state_all() if device.startswith("cuda") else None,
        })
        emit({"event": "checkpoint", "run": run_name,
              "epoch": epoch + 1, "checkpoint_sha256": sha256_file(checkpoint_path)})
        emit({"event": "epoch_end", "run": run_name, "epoch": epoch + 1,
              "train": train_summary, "wall_seconds": epoch_record["wall_seconds"]})
        print(json.dumps({"run": run_name, "epoch": epoch + 1,
                          "new_tight": eval_metrics["new_tight_eval"]["by_probability_source"],
                          "elapsed_seconds": epoch_record["elapsed_total_seconds"]}), flush=True)

    if len(history) != EPOCHS:
        raise RuntimeError(f"incomplete epoch history for {run_name}")
    head.eval()
    legacy_cache = data["legacy_cache"]
    legacy_state = legacy_cache["features"]["state"][FEATURE_KEY].to(device)
    legacy_candidates = legacy_cache["features"]["candidate"][PROFILE][FEATURE_KEY].to(device)
    dev_rows = score_groups(head, data["legacy_groups"]["dev"], legacy_state,
                            legacy_candidates, PROFILE, device)
    temperature = probe.fit_temperature(dev_rows)
    primary_state = cache["features"]["state"][FEATURE_KEY].to(device)
    primary_rows = score_groups(head, data["evaluation"], primary_state, candidates, PROFILE, device)
    adjusted_primary = probe.temperature_rows(primary_rows, temperature)
    legacy_report: dict[str, Any] = {}
    for split, split_groups in data["legacy_groups"].items():
        split_rows = (dev_rows if split == "dev" else
                      score_groups(head, split_groups, legacy_state, legacy_candidates, PROFILE, device))
        legacy_report[split] = {"raw": typed_metrics(split_rows),
                                "temperature_scaled": typed_metrics(probe.temperature_rows(split_rows, temperature))}

    all_profile = profile_metrics(head, data["evaluation"], cache, device,
                                  ("name", "name_definition", "opaque_definition", "opaque_only"))
    binding_cache = data["binding_cache"]
    binding_groups = data["binding_groups"]
    binding_state = binding_cache["features"]["state"][FEATURE_KEY].to(device)
    binding_candidates = binding_cache["features"]["candidate"]["opaque_definition"][FEATURE_KEY].to(device)
    binding_rows = score_groups(head, binding_groups, binding_state, binding_candidates,
                                "opaque_definition", device)
    with (run_dir / "newtight-final-predictions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in primary_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    with (run_dir / "binding-opaque-definition-predictions.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
        for row in binding_rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")

    head_path = run_dir / "head.pt"
    torch.save(head.state_dict(), head_path)
    report = {
        "status": "COMPLETE", "protocol": "jev-information-density/v0.8g-matched-policy-lfm",
        "run": run_name, "arm": arm, "seed_index": seed_index + 1, "seed": seed,
        "config_sha256": config_hash, "initial_head_sha256": initial_sha,
        "head_sha256": sha256_file(head_path), "trainable_parameters": sum(p.numel() for p in head.parameters()),
        "training_occurrences": len(groups), "unique_training_group_ids": len({g["group_id"] for g in groups}),
        "unique_selector_input_count": len({(g["state_idx"], tuple(g["candidate_indices"][PROFILE]), g["view"])
                                             for g in groups}),
        "epochs": EPOCHS, "history": history,
        "primary_newtight_eval": {"raw": typed_metrics(primary_rows),
                                  "temperature_scaled": typed_metrics(adjusted_primary),
                                  "temperature": temperature,
                                  "temperature_fit_scope": "legacy_dev_exact_generative_posterior_only",
                                  "prediction_file": str(run_dir / "newtight-final-predictions.jsonl")},
        "legacy_evaluation": legacy_report,
        "schema_profiles_newtight": all_profile,
        "contradictory_binding": {"profile": "opaque_definition", "metrics": typed_metrics(binding_rows),
                                  "prediction_file": str(run_dir / "binding-opaque-definition-predictions.jsonl")},
        "open_world": {"status": "UNSUPPORTED_BY_CLOSED_SET_TRAINING_BANK",
                        "training_open_world_groups": sum(bool(g["open_world"]) for g in groups),
                        "no_open_world_score_claimed": True},
        "runtime": {"elapsed_seconds": time.perf_counter() - started,
                    "cuda_peak_allocated_bytes": int(torch.cuda.max_memory_allocated()) if device.startswith("cuda") else 0,
                    "host_peak_rss_bytes": process_peak_rss_bytes()},
        "backbone_frozen": True,
    }
    write_json(final_report_path, report)
    emit({"event": "run_complete", "run": run_name, "report_sha256": sha256_file(final_report_path)})
    event_stream.close()
    return report


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--only", choices=["all", "seed-1", "seed-2", "seed-3"], default="all")
    args = parser.parse_args()
    if args.device.startswith("cuda") and not torch.cuda.is_available():
        raise RuntimeError("CUDA requested but unavailable")
    data = load_run_data()
    feature_sha = data["feature_receipt"]["cache"]["sha256"]
    results = []
    allowed_seed = None if args.only == "all" else int(args.only[-1]) - 1
    active_run: tuple[int, str] | None = None
    try:
        for seed_index, arm in SCHEDULE:
            if allowed_seed is not None and seed_index != allowed_seed:
                continue
            active_run = (seed_index, arm)
            result = fit_one(data, seed_index, arm, args.device, feature_sha)
            results.append({"seed_index": seed_index + 1, "seed": SEEDS[seed_index],
                            "arm": arm, "report_sha256": sha256_file(Path(
                                result["primary_newtight_eval"]["prediction_file"]).parent / "run-report.json")})
    except Exception as exc:
        if active_run is not None:
            seed_index, arm = active_run
            error_path = OUT / "runs" / f"seed-{seed_index + 1}" / arm / "training-events.jsonl"
            if error_path.parent.exists():
                append_event(error_path, {"event": "run_error", "seed_index": seed_index + 1,
                                          "arm": arm, "error_type": type(exc).__name__,
                                          "error": str(exc), "time_unix": time.time()})
        raise
    summary_path = OUT / "reports" / "training-execution-summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    prior = read_json(summary_path) if summary_path.exists() else {"runs": []}
    merged = {(row["seed_index"], row["arm"]): row for row in prior.get("runs", [])}
    for row in results:
        merged[(row["seed_index"], row["arm"])] = row
    write_json(summary_path, {"status": "ALL_SCHEDULED_RUNS_COMPLETE" if len(merged) == 6 else "IN_PROGRESS",
                              "runs": [merged[key] for key in sorted(merged)],
                              "model_revision": data["cache"]["revision"],
                              "backbone_frozen": True})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
