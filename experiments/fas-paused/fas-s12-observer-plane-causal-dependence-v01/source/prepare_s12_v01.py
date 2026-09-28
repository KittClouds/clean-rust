from __future__ import annotations

import json
import hashlib
import os
import struct
import sys
from pathlib import Path
from typing import Any

import numpy as np

from s12_math import canonical_json, draw_bootstrap_plan, entry, orthonormal_row_basis, pair_normals, random_plane, seed_from_label, sha256_file, tree_root


ROOT = Path(r"D:\codex-runs\fas-s12-observer-plane-causal-dependence-v01\run-v01")
S11 = Path(r"D:\codex-runs\fas-s11-cross-depth-observer-transport-replication-v01\execution-v01")
S09 = Path(r"D:\codex-runs\fas-s09-depthwise-decision-subspace-emergence-v09")
S09_PROBES = S09 / "analysis-v09" / "probes"
S11_SEAL = S11 / "s11-final-seal-v02.json"
S09_SEAL = S09 / "result-tree-seal-v09.json"
ROWS = 21_272
QUARTETS = 5_318
DIM = 2_048
EXPECTED_S11_ROOT = "23758806537df1895772025e97824393dd4cd79ede7956360cd93f341c30740a"
EXPECTED_PANEL_ROOT = "9011d425faaac7c6c1bee0f619a696a4469816ebeae1c0df2c6d4f8516fde824"
EXPECTED_CACHE_ROOT = "b93f724f674219484002aeece36eb0512322e59ae37df204b76885c22624cff3"
EXPECTED_TOKEN_ROOT = "1c759a420594db8ce682259058ac9da3cc52c202c1bbacf8ed4fe0235ba6cf39"
EXPECTED_S09_ROOT = "664af5b22f071b28d52a67d748e9f6f93ae3e67d587edec80b921dd529945880"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        rows = []
        for line_no, line in enumerate(stream, 1):
            if not line.endswith("\n"):
                raise RuntimeError(f"non-terminated JSONL row {line_no}: {path}")
            rows.append(json.loads(line))
    return rows


def write_bytes_stable(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.read_bytes() != payload:
            raise RuntimeError(f"preparation artifact already exists with different bytes: {path}")
        return
    path.write_bytes(payload)


def write_array_stable(path: Path, array: np.ndarray) -> None:
    contiguous = np.ascontiguousarray(array)
    expected = hashlib.sha256(memoryview(contiguous).cast("B")).hexdigest()
    if path.exists():
        actual, size = sha256_file(path)
        if actual != expected or size != contiguous.nbytes:
            raise RuntimeError(f"preparation array already exists with different bytes: {path}")
        return
    contiguous.tofile(path)


def verify_selected_entries(base: Path, seal: dict[str, Any], relative_paths: list[str]) -> list[dict[str, Any]]:
    expected = {row["path"]: row for row in seal["entries"]}
    verified = []
    for relative in relative_paths:
        if relative not in expected:
            raise RuntimeError(f"parent seal lacks required path: {relative}")
        path = base.joinpath(*relative.split("/"))
        actual = entry(path, base)
        if actual != expected[relative]:
            raise RuntimeError(f"parent entry mismatch: {relative}")
        verified.append(actual)
    return verified


def verify_events_and_tokens() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    s11_seal = read_json(S11_SEAL)
    if s11_seal.get("root_sha256") != EXPECTED_S11_ROOT:
        raise RuntimeError("S11 final result root does not match S12 parent identity")
    if read_json(S11 / "execution-manifest-v01.json").get("feature_cache_root_sha256") != EXPECTED_CACHE_ROOT:
        raise RuntimeError("S11 feature-cache root mismatch")
    token_seal = read_json(S11 / "tokenization-v01" / "tokenization-seal-v01.json")
    if token_seal.get("root_sha256") != EXPECTED_TOKEN_ROOT:
        raise RuntimeError("S11 tokenization root mismatch")
    feature_seal = read_json(S11 / "feature-cache-v01" / "feature-cache-seal-v01.json")
    if feature_seal.get("root_sha256") != EXPECTED_CACHE_ROOT:
        raise RuntimeError("S11 feature-cache seal mismatch")

    required = [
        "inputs/panel/selected-events-v02.jsonl",
        "inputs/panel/selected-quartets-v02.jsonl",
        "inputs/panel/panel-tree-seal-v02.json",
        "tokenization-v01/token-rows-v01.jsonl",
        "tokenization-v01/tokenization-seal-v01.json",
        "feature-cache-v01/feature-cache-seal-v01.json",
        "feature-cache-v01/feature-extraction-receipt-v01.json",
        "feature-cache-v01/matrices/layer-16-M.f32le",
        "feature-cache-v01/matrices/layer-16-F.f32le",
        "analysis-v01/s11-confirmatory-analysis-v01.json",
        "inputs/tokenizer-identity-v01.json",
        "inputs/parent/s09-model-asset-manifest-v02.json",
    ]
    verified = verify_selected_entries(S11, s11_seal, required)
    panel_seal = read_json(S11 / "inputs" / "panel" / "panel-tree-seal-v02.json")
    if panel_seal.get("tree_root_sha256") != EXPECTED_PANEL_ROOT:
        raise RuntimeError("S11 panel seal root mismatch")
    if read_json(S11 / "execution-manifest-v01.json")["authoritative_s11_ancestry"].get("panel_id") != "fas-s11-fresh-quartet-panel-v02-uniqueness-conditioned":
        raise RuntimeError("unexpected S11 panel identity")

    events = read_jsonl(S11 / "inputs" / "panel" / "selected-events-v02.jsonl")
    quartets = read_jsonl(S11 / "inputs" / "panel" / "selected-quartets-v02.jsonl")
    token_rows = read_jsonl(S11 / "tokenization-v01" / "token-rows-v01.jsonl")
    if len(events) != ROWS or len(token_rows) != ROWS or len(quartets) != QUARTETS:
        raise RuntimeError("S11 row or quartet counts do not match S12")
    if len({row["event_id"] for row in events}) != ROWS or len({row["input_sha256"] for row in events}) != ROWS:
        raise RuntimeError("S11 event or rendered-input identities are not unique")

    quartet_rows: dict[str, list[dict[str, Any]]] = {}
    quartet_targets: dict[str, int] = {}
    for index, (event, token) in enumerate(zip(events, token_rows, strict=True)):
        if event["event_id"] != token["event_id"] or event["input_sha256"] != token["input_sha256"] or token["row_index"] != index:
            raise RuntimeError(f"S11 event/token identity mismatch at row {index}")
        ids = token["token_ids"]
        token_sha = __import__("hashlib").sha256(struct.pack(f"<{len(ids)}I", *ids)).hexdigest()
        if len(ids) != token["sequence_length"] or token_sha != token["token_ids_sha256"]:
            raise RuntimeError(f"S11 token identity mismatch at row {index}")
        quartet_id = event["quartet_id"]
        target = int(event["exact_target"])
        if quartet_id in quartet_targets and quartet_targets[quartet_id] != target:
            raise RuntimeError(f"quartet target is not invariant: {quartet_id}")
        quartet_targets[quartet_id] = target
        quartet_rows.setdefault(quartet_id, []).append({"row_index": index, "event_id": event["event_id"], "variant_id": event["variant_id"], "exact_target": target})

    quartet_ids = [row["quartet_id"] for row in quartets]
    if len(set(quartet_ids)) != QUARTETS or set(quartet_ids) != set(quartet_rows):
        raise RuntimeError("S11 quartet identity table does not match event rows")
    for quartet_id, members in quartet_rows.items():
        if len(members) != 4 or {m["variant_id"] for m in members} != {"A", "C", "E", "P"}:
            raise RuntimeError(f"invalid quartet members: {quartet_id}")
    counts = {str(cls): sum(target == cls for target in quartet_targets.values()) for cls in (0, 1, 2)}
    if counts != {"0": 1733, "1": 1815, "2": 1770}:
        raise RuntimeError(f"S11 exact-target quartet support changed: {counts}")
    for quartet_id in quartet_ids:
        if quartet_id not in quartet_targets:
            raise RuntimeError(f"quartet table contains absent quartet: {quartet_id}")
    return events, token_rows, quartets, {
        "s11_final_seal": str(S11_SEAL),
        "s11_final_seal_file_sha256": sha256_file(S11_SEAL)[0],
        "s11_result_root_sha256": EXPECTED_S11_ROOT,
        "s11_panel_root_sha256": EXPECTED_PANEL_ROOT,
        "s11_feature_cache_root_sha256": EXPECTED_CACHE_ROOT,
        "s11_tokenization_root_sha256": EXPECTED_TOKEN_ROOT,
        "verified_s11_entries": verified,
        "class_quartet_counts": counts,
        "row_count": len(events),
        "quartet_count": len(quartets),
    }


def make_planes() -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]], list[dict[str, Any]]]:
    bank = np.empty((6, 9, 2, DIM), dtype="<f8")
    centers = np.empty((6, DIM), dtype="<f8")
    sites: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    slot = 0
    for layer in (4, 8, 12):
        for surface in ("M", "F"):
            relative = f"analysis-v09/probes/layer-{layer:02d}/{surface}/probe-state-v09.npz"
            path = S09.joinpath(*relative.split("/"))
            s09_seal = read_json(S09_SEAL)
            matches = [row for row in s09_seal["entries"] if row["path"] == relative]
            if len(matches) != 1 or entry(path, S09) != matches[0]:
                raise RuntimeError(f"S09 source observer not verified: {relative}")
            with np.load(path, allow_pickle=False) as arrays:
                required = {"classes", "weights", "bias", "scaler_mean", "scaler_scale"}
                if set(arrays.files) != required:
                    raise RuntimeError(f"unexpected S09 observer fields: {relative}")
                classes = np.asarray(arrays["classes"], dtype=np.int64)
                if not np.array_equal(classes, np.asarray([0, 1, 2], dtype=np.int64)):
                    raise RuntimeError(f"S09 class order mismatch: {relative}")
                weights = np.asarray(arrays["weights"], dtype=np.float64)
                scale = np.asarray(arrays["scaler_scale"], dtype=np.float64)
                center = np.asarray(arrays["scaler_mean"], dtype="<f8")
                rows = pair_normals(weights, scale)
                basis, checks = orthonormal_row_basis(rows)
                bank[slot, 0] = basis
                centers[slot] = center
                sites.append({
                    "slot": slot,
                    "layer": layer,
                    "surface": surface,
                    "observer_path": relative,
                    "observer_sha256": matches[0]["sha256"],
                    "source_center_sha256_f64le": __import__("hashlib").sha256(center.tobytes(order="C")).hexdigest(),
                    "checks": checks,
                })
            for control in range(1, 9):
                seed_label = f"FAS-S12-V01-RANDOM-PLANE|layer={layer}|surface={surface}|control={control}"
                seed_u64, seed_hash = seed_from_label(seed_label)
                random = random_plane(seed_u64)
                bank[slot, control] = random
                cosines = np.linalg.svd(basis @ random.T, compute_uv=False)
                angles = np.degrees(np.arccos(np.clip(cosines, 0.0, 1.0)))
                controls.append({
                    "slot": slot,
                    "layer": layer,
                    "surface": surface,
                    "control_id": control,
                    "seed_label": seed_label,
                    "seed_sha256": seed_hash,
                    "seed_u64": seed_u64,
                    "generation": "NumPy Generator(PCG64).standard_normal((2048,2),float64); reduced QR; transpose Q",
                    "principal_angles_to_target_degrees": angles.tolist(),
                })
            slot += 1
    return bank, centers, sites, controls


def main() -> int:
    if ROOT.exists():
        allowed = {
            "inputs/plane-bank-v01.f64le",
            "inputs/source-centers-v01.f64le",
            "inputs/bootstrap-plan-v01.u32le",
            "inputs/repeat-quartets-v01.json",
            "inputs/parent-binding-v01.json",
            "preparation-receipt-v01.json",
        }
        unexpected = [path for path in ROOT.rglob("*") if path.is_file() and path.relative_to(ROOT).as_posix() not in allowed]
        if unexpected:
            raise RuntimeError(f"S12 run contains non-preparation artifacts: {unexpected[0]}")
    inputs = ROOT / "inputs"
    (inputs / "parent").mkdir(parents=True, exist_ok=True)
    events, token_rows, quartets, panel_info = verify_events_and_tokens()
    if read_json(S09_SEAL).get("root_sha256") != EXPECTED_S09_ROOT:
        raise RuntimeError("S09 result root does not match S12 parent identity")

    s09_selected = []
    s09_seal = read_json(S09_SEAL)
    for layer in (4, 8, 12, 16):
        for surface in ("M", "F"):
            relative = f"analysis-v09/probes/layer-{layer:02d}/{surface}/probe-state-v09.npz"
            found = [row for row in s09_seal["entries"] if row["path"] == relative]
            if len(found) != 1:
                raise RuntimeError(f"S09 root lacks observer state: {relative}")
            actual = entry(S09.joinpath(*relative.split("/")), S09)
            if actual != found[0]:
                raise RuntimeError(f"S09 observer state changed: {relative}")
            s09_selected.append(actual)

    bank, centers, sites, controls = make_planes()
    bank_path = inputs / "plane-bank-v01.f64le"
    centers_path = inputs / "source-centers-v01.f64le"
    write_array_stable(bank_path, bank)
    write_array_stable(centers_path, centers)

    label_by_quartet: dict[str, int] = {}
    member_by_quartet: dict[str, list[int]] = {}
    for index, event in enumerate(events):
        qid = event["quartet_id"]
        label_by_quartet.setdefault(qid, int(event["exact_target"]))
        member_by_quartet.setdefault(qid, []).append(index)
    ordered_qids = [row["quartet_id"] for row in quartets]
    labels = np.asarray([label_by_quartet[qid] for qid in ordered_qids], dtype=np.int64)
    boot_seed, boot_hash = seed_from_label("FAS-S12-V01-BOOTSTRAP-SEED")
    plan = draw_bootstrap_plan(labels, boot_seed)
    bootstrap_path = inputs / "bootstrap-plan-v01.u32le"
    write_array_stable(bootstrap_path, plan)

    repeat_seed, repeat_hash = seed_from_label("FAS-S12-V01-REPEAT-QUARTET-SEED")
    repeat_rng = np.random.Generator(np.random.PCG64(repeat_seed))
    repeat_indices: list[int] = []
    repeat_quartets: list[dict[str, Any]] = []
    for target in (0, 1, 2):
        eligible = np.flatnonzero(labels == target)
        chosen = np.sort(repeat_rng.choice(eligible, size=10, replace=False))
        for qi in chosen.tolist():
            qid = ordered_qids[qi]
            repeat_indices.extend(member_by_quartet[qid])
            repeat_quartets.append({"quartet_index": qi, "quartet_id": qid, "exact_target": target, "row_indices": member_by_quartet[qid]})
    repeat_payload = {
        "selection_id": "FAS_S12_REPEAT_QUARTETS_V01",
        "seed_label": "FAS-S12-V01-REPEAT-QUARTET-SEED",
        "seed_sha256": repeat_hash,
        "seed_u64": repeat_seed,
        "quartets_per_target": 10,
        "selected_quartets": repeat_quartets,
        "selected_row_indices_sorted": sorted(repeat_indices),
    }
    repeat_path = inputs / "repeat-quartets-v01.json"
    write_bytes_stable(repeat_path, canonical_json(repeat_payload) + b"\n")

    model_manifest_path = S11 / "inputs" / "parent" / "s09-model-asset-manifest-v02.json"
    tokenizer_identity_path = S11 / "inputs" / "tokenizer-identity-v01.json"
    s09_seal_digest, _ = sha256_file(S09_SEAL)
    parent_binding = {
        "binding_id": "FAS_S12_PARENT_BINDING_V01",
        "parents": {
            "s09": {"path": str(S09), "result_tree_seal": str(S09_SEAL), "result_tree_seal_file_sha256": s09_seal_digest, "result_root_sha256": EXPECTED_S09_ROOT, "observer_entries": s09_selected},
            "s11": {"path": str(S11), "final_seal": str(S11_SEAL), "final_seal_file_sha256": panel_info["s11_final_seal_file_sha256"], "result_root_sha256": EXPECTED_S11_ROOT, "panel_root_sha256": EXPECTED_PANEL_ROOT, "feature_cache_root_sha256": EXPECTED_CACHE_ROOT, "tokenization_root_sha256": EXPECTED_TOKEN_ROOT, "verified_entries": panel_info["verified_s11_entries"]},
            "model_assets_manifest": {"path": str(model_manifest_path), "sha256": sha256_file(model_manifest_path)[0], "manifest": read_json(model_manifest_path)},
            "tokenizer_identity": {"path": str(tokenizer_identity_path), "sha256": sha256_file(tokenizer_identity_path)[0], "identity": read_json(tokenizer_identity_path)},
        },
        "panel": panel_info,
        "runtime_expected": {"python": sys.version.split()[0], "numpy": np.__version__, "torch": "2.11.0+cu128", "transformers": "5.17.0", "device": "NVIDIA GeForce RTX 3080"},
        "terminal_baseline_context_from_s11": {
            "row_count": 21272,
            "M_layer16_balanced_accuracy": 0.604337864053308,
            "M_layer16_accuracy": 0.6029522376833396,
            "M_class_recall": [0.7023946912867859, 0.5212121212121212, 0.589406779661017],
            "F_layer16_balanced_accuracy": 0.9784932619144247,
            "F_layer16_accuracy": 0.978469349379466,
            "F_class_recall": [0.9685516445470282, 0.9674931129476584, 0.9994350282485875],
            "note": "Design context only; no newly invented threshold or pass gate.",
        },
    }
    write_bytes_stable(inputs / "parent-binding-v01.json", canonical_json(parent_binding) + b"\n")

    prep_receipt = {
        "receipt_id": "FAS_S12_PREPARATION_RECEIPT_V01",
        "complete": True,
        "s09_result_root_sha256": EXPECTED_S09_ROOT,
        "s11_result_root_sha256": EXPECTED_S11_ROOT,
        "s11_panel_root_sha256": EXPECTED_PANEL_ROOT,
        "s11_feature_cache_root_sha256": EXPECTED_CACHE_ROOT,
        "s11_tokenization_root_sha256": EXPECTED_TOKEN_ROOT,
        "rows": ROWS,
        "quartets": QUARTETS,
        "class_quartet_counts": panel_info["class_quartet_counts"],
        "site_count": len(sites),
        "random_plane_count": len(controls),
        "source_sites": sites,
        "random_controls": controls,
        "plane_bank": {"path": bank_path.relative_to(ROOT).as_posix(), "shape": list(bank.shape), "dtype": "<f8", "sha256": sha256_file(bank_path)[0], "bytes": sha256_file(bank_path)[1]},
        "source_centers": {"path": centers_path.relative_to(ROOT).as_posix(), "shape": list(centers.shape), "dtype": "<f8", "sha256": sha256_file(centers_path)[0], "bytes": sha256_file(centers_path)[1]},
        "bootstrap": {"path": bootstrap_path.relative_to(ROOT).as_posix(), "shape": list(plan.shape), "dtype": "<u4", "sha256": sha256_file(bootstrap_path)[0], "bytes": sha256_file(bootstrap_path)[1], "seed_label": "FAS-S12-V01-BOOTSTRAP-SEED", "seed_sha256": boot_hash, "seed_u64": boot_seed, "replicates": 10000, "stratum_order": [0, 1, 2]},
        "repeat_selection": {"path": repeat_path.relative_to(ROOT).as_posix(), "sha256": sha256_file(repeat_path)[0], "seed_label": "FAS-S12-V01-REPEAT-QUARTET-SEED", "seed_sha256": repeat_hash, "seed_u64": repeat_seed, "quartets": 30, "rows": len(repeat_indices)},
    }
    write_bytes_stable(ROOT / "preparation-receipt-v01.json", canonical_json(prep_receipt) + b"\n")
    print(json.dumps(prep_receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
