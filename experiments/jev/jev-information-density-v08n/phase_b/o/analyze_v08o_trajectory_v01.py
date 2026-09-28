"""Analyze sealed v0.8O predictions and checkpoint parameter trajectories."""

from __future__ import annotations

import hashlib
import html
import importlib.util
import json
import math
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

import numpy as np
import torch


ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / "experiments/jev-information-density-v08n/phase_b/o"
PHASE = ROOT / "experiments/jev-information-density-v08n/phase_b"
RUN = Path(r"D:\codex-runs\jev-information-density-v08n\v0.8N-base-v01\phase-b-run-v01")
OUTPUT = Path(r"D:\codex-runs\jev-information-density-v08o\v0.8O-capability-trajectory-cartography-v01")
RUN_CONTRACT = SOURCE / "phase-b-o-run-contract-v01.json"
ANALYSIS_CONTRACT = SOURCE / "phase-b-o-analysis-contract-v01.json"
EXPECTED_ANALYSIS_CONTRACT_SHA256 = "d3b022f20c16dd11e0923b8d52940d6f6d88cde5d68dfe739085213c13ecb4bf"
FROZEN_ANALYZER_SHA256 = "dbde07fe1ec009f2bca7f1f22ad913a2a79f4f8dfb8120a1f31ebf37d5f59b70"
SEEDS = (20260927, 20260928, 20260929)
ARMS = ("B-DUP", "B-MATCHED", "B-SHAM")
EPOCHS = (0, 1, 2, 3)
FAMILIES = ("exposure_control", "respiratory_monitoring", "salinity_control", "vibration_monitoring")
VIEWS = ("anchor", "fact_flip", "sham", "matched_neutral")
METRICS = (
    "sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip", "anchor_old_map",
    "fact_new_map", "strict_transition", "correct_direction", "new_probability_delta",
    "delta_mae", "anchor_nll", "anchor_brier", "anchor_gold_map_accuracy",
    "sham_gold_probability_movement", "sham_margin_movement",
    "matched_gold_probability_movement", "matched_margin_movement",
)
TRANSITION_CELLS = (
    ("A_AND_F", True, True),
    ("A_AND_NOT_F", True, False),
    ("NOT_A_AND_F", False, True),
    ("NOT_A_AND_NOT_F", False, False),
)
COLORS = {"B-DUP": "#2878b5", "B-MATCHED": "#e07b24", "B-SHAM": "#27864b"}
MARKERS = {0: "o", 1: "s", 2: "^", 3: "D"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json_exclusive(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def write_jsonl_exclusive(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def import_frozen_analyzer() -> Any:
    path = PHASE / "analyze_phase_b_v01.py"
    if sha256_file(path) != FROZEN_ANALYZER_SHA256:
        raise RuntimeError("frozen v0.8N neighborhood metric implementation drift")
    spec = importlib.util.spec_from_file_location("jev_v08o_frozen_analyzer", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot import frozen neighborhood metric implementation")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def verify_sealed_predictions(preflight: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if not OUTPUT.is_dir():
        raise FileNotFoundError("v0.8O inference output directory is absent")
    tree_path = OUTPUT / "raw-prediction-hash-tree-v01.json"
    receipt_path = OUTPUT / "inference-receipt-v01.json"
    pred_path = OUTPUT / "raw-predictions-v01.jsonl"
    diag_path = OUTPUT / "input-geometry-diagnostics-v01.jsonl"
    identity_audit_path = OUTPUT / "raw-prediction-identity-audit-v01.json"
    amendment_path = OUTPUT / "analysis-reporting-correction-v01.json"
    if not all(path.is_file() for path in (tree_path, receipt_path, pred_path, diag_path, identity_audit_path, amendment_path)):
        raise RuntimeError("raw prediction seal is incomplete; analysis is forbidden")
    tree, receipt = read_json(tree_path), read_json(receipt_path)
    identity_audit, amendment = read_json(identity_audit_path), read_json(amendment_path)
    if tree.get("status") != "V08O_ALL_EPOCH_RAW_PREDICTIONS_SEALED_BEFORE_ANALYSIS" or tree.get("prediction_rows") != 288_000:
        raise RuntimeError("O prediction tree does not seal the complete 36-cell matrix")
    if receipt.get("prediction_hash_tree_sha256") != sha256_file(tree_path) or receipt.get("prediction_sha256") != sha256_file(pred_path):
        raise RuntimeError("O inference receipt does not match sealed raw predictions")
    if tree.get("files", {}).get(pred_path.name, {}).get("sha256") != sha256_file(pred_path):
        raise RuntimeError("raw prediction bytes differ from O tree")
    if tree.get("files", {}).get(diag_path.name, {}).get("sha256") != sha256_file(diag_path):
        raise RuntimeError("geometry diagnostic bytes differ from O tree")
    if identity_audit.get("status") != "V08O_RAW_PREDICTION_IDENTITY_AUDIT_PASS_NO_METRIC_ANALYSIS" or identity_audit.get("raw_prediction_sha256") != sha256_file(pred_path):
        raise RuntimeError("raw prediction identity audit is missing or bound to different predictions")
    if amendment.get("status") != "V08O_PREANALYSIS_REPORTING_CORRECTION_NO_METRIC_CHANGE":
        raise RuntimeError("analysis reporting correction receipt is missing or has unexpected disposition")
    if amendment.get("raw_prediction_sha256") != sha256_file(pred_path):
        raise RuntimeError("reporting correction receipt is not bound to the sealed raw predictions")
    if amendment.get("analysis_source_sha256_at_opening") != preflight.get("source_hashes", {}).get("analysis"):
        raise RuntimeError("reporting correction does not identify the analysis source bound at opening")
    if amendment.get("corrected_analysis_source_sha256") != sha256_file(Path(__file__).resolve()):
        raise RuntimeError("corrected analysis source differs from the recorded reporting amendment")
    if sha256_file(ANALYSIS_CONTRACT) != EXPECTED_ANALYSIS_CONTRACT_SHA256:
        raise RuntimeError("frozen O analysis schema drift")
    return tree, receipt


def read_cell(stream: TextIO, expected: tuple[int, str, int], metric: Any) -> list[dict[str, Any]]:
    seed, arm, epoch = expected
    records: list[dict[str, Any]] = []
    neighborhood_ids: set[str] = set()
    for _ in range(2000):
        views: dict[str, dict[str, Any]] = {}
        nid: str | None = None
        for _view_index in range(4):
            line = stream.readline()
            if not line:
                raise RuntimeError(f"raw prediction stream ended inside cell {seed}/{arm}/epoch-{epoch}")
            row = json.loads(line)
            if (int(row["seed"]), str(row["arm"]), int(row["epoch"])) != expected:
                raise RuntimeError(f"unexpected response-matrix ordering at {seed}/{arm}/epoch-{epoch}")
            current = str(row["neighborhood_id"])
            if nid is None:
                nid = current
            elif current != nid:
                raise RuntimeError("a neighborhood's four view rows are not contiguous")
            view = str(row["view"])
            if view not in VIEWS or view in views:
                raise RuntimeError(f"duplicate or unknown view for {seed}/{arm}/{epoch}/{current}")
            views[view] = row
        if nid is None or set(views) != set(VIEWS) or nid in neighborhood_ids:
            raise RuntimeError(f"invalid or duplicate neighborhood block in {seed}/{arm}/{epoch}")
        neighborhood_ids.add(nid)
        values = metric.neighborhood_metrics(views)
        if str(values["family_id"]) not in FAMILIES:
            raise RuntimeError("unexpected held-out family in trajectory analysis")
        records.append({
            "seed": seed, "arm": arm, "epoch": epoch, "neighborhood_id": nid,
            "family_id": str(values["family_id"]), **{name: float(values[name]) for name in METRICS},
        })
    if len(records) != 2000 or len(neighborhood_ids) != 2000:
        raise RuntimeError(f"cell cardinality mismatch: {seed}/{arm}/epoch-{epoch}")
    return records


def mean_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    return {name: float(np.mean([float(row[name]) for row in rows])) for name in METRICS}


def summarize_cell(rows: list[dict[str, Any]]) -> dict[str, Any]:
    family_counts = Counter(row["family_id"] for row in rows)
    if family_counts != Counter({family: 500 for family in FAMILIES}):
        raise RuntimeError(f"family counts drift in cell {rows[0]['seed']}/{rows[0]['arm']}/{rows[0]['epoch']}: {family_counts}")
    return {
        "n": len(rows),
        "overall": mean_metrics(rows),
        "by_family": {family: mean_metrics([row for row in rows if row["family_id"] == family]) for family in FAMILIES},
    }


def transition_cells(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {"n": len(rows), "overall": {}, "by_family": {family: {} for family in FAMILIES}}
    for name, old, new in TRANSITION_CELLS:
        selected = [row for row in rows if bool(row["anchor_old_map"]) is old and bool(row["fact_new_map"]) is new]
        result["overall"][name] = {"count": len(selected), "proportion": len(selected) / len(rows)}
        for family in FAMILIES:
            block = [row for row in selected if row["family_id"] == family]
            family_n = sum(row["family_id"] == family for row in rows)
            result["by_family"][family][name] = {"count": len(block), "proportion": len(block) / family_n}
    if sum(item["count"] for item in result["overall"].values()) != len(rows):
        raise RuntimeError("four-cell transition partition does not sum to 2000")
    for family in FAMILIES:
        if sum(item["count"] for item in result["by_family"][family].values()) != 500:
            raise RuntimeError(f"four-cell transition partition does not sum to 500 for {family}")
    strict = result["overall"]["A_AND_F"]["proportion"]
    if not math.isclose(strict, float(np.mean([row["strict_transition"] for row in rows])), abs_tol=1e-15):
        raise RuntimeError("strict transition does not equal the A_AND_F cell")
    return result


def paired_sham_minus_matched(matched: list[dict[str, Any]], sham: list[dict[str, Any]]) -> dict[str, Any]:
    matched_map = {str(row["neighborhood_id"]): row for row in matched}
    sham_map = {str(row["neighborhood_id"]): row for row in sham}
    if set(matched_map) != set(sham_map):
        raise RuntimeError("paired arms do not share exact neighborhood identity")
    differences = {metric: [] for metric in METRICS}
    by_family = {family: {metric: [] for metric in METRICS} for family in FAMILIES}
    for nid in sorted(matched_map):
        left, right = sham_map[nid], matched_map[nid]
        if left["family_id"] != right["family_id"]:
            raise RuntimeError(f"family drift in paired neighborhood {nid}")
        family = str(left["family_id"])
        for metric in METRICS:
            difference = float(left[metric]) - float(right[metric])
            differences[metric].append(difference)
            by_family[family][metric].append(difference)
    return {
        "definition": "B-SHAM minus B-MATCHED; raw signed difference, no composite or threshold",
        "n": 2000,
        "mean_by_metric": {metric: float(np.mean(values)) for metric, values in differences.items()},
        "by_family": {family: {metric: float(np.mean(values)) for metric, values in fields.items()} for family, fields in by_family.items()},
    }


def stream_behavioral_analysis(tree: dict[str, Any]) -> dict[str, Any]:
    frozen = import_frozen_analyzer()
    response: dict[str, Any] = {}
    transitions: dict[str, Any] = {}
    paired: dict[str, Any] = {}
    metric_rows_path = OUTPUT / "neighborhood-metrics-v01.jsonl"
    if metric_rows_path.exists():
        raise FileExistsError("trajectory metric output already exists; no rewrite")
    all_counts: dict[str, int] = {}
    with (OUTPUT / "raw-predictions-v01.jsonl").open("r", encoding="utf-8") as pred_stream, metric_rows_path.open("x", encoding="utf-8", newline="\n") as metric_stream:
        for seed in SEEDS:
            response[str(seed)] = {}
            transitions[str(seed)] = {}
            paired[str(seed)] = {}
            for epoch in EPOCHS:
                cell_rows: dict[str, list[dict[str, Any]]] = {}
                for arm in ARMS:
                    key = f"{seed}/{arm}/epoch-{epoch}"
                    rows = read_cell(pred_stream, (seed, arm, epoch), frozen)
                    cell_rows[arm] = rows
                    all_counts[key] = len(rows)
                    response[str(seed)].setdefault(arm, {})[str(epoch)] = summarize_cell(rows)
                    transitions[str(seed)].setdefault(arm, {})[str(epoch)] = transition_cells(rows)
                    for row in rows:
                        metric_stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
                paired[str(seed)][str(epoch)] = paired_sham_minus_matched(cell_rows["B-MATCHED"], cell_rows["B-SHAM"])
        if pred_stream.readline():
            raise RuntimeError("extra rows after the expected 36-cell response matrix")
        metric_stream.flush()
        os.fsync(metric_stream.fileno())
    if len(all_counts) != 36 or sum(all_counts.values()) != 72_000:
        raise RuntimeError("trajectory analysis did not consume exactly 72,000 neighborhoods")
    return {
        "status": "V08O_BEHAVIORAL_TRAJECTORY_ANALYSIS_COMPLETE",
        "raw_prediction_tree_sha256": sha256_file(OUTPUT / "raw-prediction-hash-tree-v01.json"),
        "metric_rows_sha256": sha256_file(metric_rows_path),
        "metric_row_count": 72_000,
        "response_matrix": response,
        "transition_four_cell_decomposition": transitions,
        "paired_sham_minus_matched_trajectory": paired,
        "rows_by_cell": all_counts,
        "aggregate_uncertainty": "not computed; descriptive neighborhood/seed trajectories only",
    }


def state_digest(state: dict[str, torch.Tensor]) -> str:
    digest = hashlib.sha256()
    for name in sorted(state):
        value = state[name].detach().cpu().contiguous()
        digest.update(name.encode("utf-8")); digest.update(str(value.dtype).encode("ascii"))
        digest.update(json.dumps(list(value.shape)).encode("ascii")); digest.update(memoryview(value.numpy()).cast("B"))
    return digest.hexdigest()


def load_state(path: Path, seed: int, arm: str, epoch: int, expected_file_sha: str, expected_state_sha: str) -> dict[str, torch.Tensor]:
    if sha256_file(path) != expected_file_sha:
        raise RuntimeError(f"checkpoint bytes changed before parameter analysis: {seed}/{arm}/{epoch}")
    if epoch == 0:
        payload = torch.load(path, map_location="cpu", weights_only=True)
        state = payload.get("state_dict")
        if payload.get("seed") != seed or payload.get("state_sha256") != expected_state_sha:
            raise RuntimeError(f"initial template identity drift: seed {seed}")
    else:
        payload = torch.load(path, map_location="cpu", weights_only=False)
        state = payload.get("head_state")
        if (payload.get("seed"), payload.get("arm"), payload.get("epoch")) != (seed, arm, epoch):
            raise RuntimeError(f"parameter checkpoint identity drift: {seed}/{arm}/{epoch}")
        if payload.get("initial_head_sha256") != expected_state_sha:
            raise RuntimeError(f"paired initial-head digest mismatch: {seed}/{arm}/{epoch}")
        expected_state_sha = payload.get("terminal_head_sha256")
    if not isinstance(state, dict) or state_digest(state) != expected_state_sha:
        raise RuntimeError(f"parameter state digest mismatch: {seed}/{arm}/{epoch}")
    return state


def vector_stats(delta: dict[str, torch.Tensor]) -> tuple[float, dict[str, Any]]:
    total_sq = 0.0
    fields = {}
    for name, value in delta.items():
        sq = float(torch.sum(value.to(torch.float64) ** 2).item())
        total_sq += sq
        fields[name] = {"parameter_count": int(value.numel()), "displacement_l2": math.sqrt(sq)}
    return math.sqrt(total_sq), fields


def cosine_between(left: dict[str, torch.Tensor], right: dict[str, torch.Tensor]) -> float | None:
    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for name in left:
        a, b = left[name].to(torch.float64), right[name].to(torch.float64)
        dot += float(torch.sum(a * b).item())
        left_sq += float(torch.sum(a * a).item())
        right_sq += float(torch.sum(b * b).item())
    if left_sq == 0.0 or right_sq == 0.0:
        return None
    return dot / math.sqrt(left_sq * right_sq)


def parameter_trajectory(preflight: dict[str, Any]) -> dict[str, Any]:
    checkpoint_map = {f"{item['seed']}/{item['arm']}/epoch-{item['epoch']}": item for item in preflight["checkpoints"]}
    initial_map = preflight["initialization_templates"]
    per_cell: dict[str, Any] = {}
    pairwise: dict[str, Any] = {}
    for seed in SEEDS:
        init_item = initial_map[str(seed)]
        initial = load_state(Path(init_item["path"]), seed, "shared", 0, init_item["sha256"], init_item["state_sha256"])
        initial = {key: value.detach().cpu().to(torch.float64) for key, value in initial.items()}
        if sum(value.numel() for value in initial.values()) != 590_081:
            raise RuntimeError("initial head parameter count differs from contract")
        for arm in ARMS:
            zero_key = f"{seed}/{arm}/epoch-0"
            per_cell[zero_key] = {
                "checkpoint_sha256": init_item["sha256"], "head_state_sha256": init_item["state_sha256"],
                "global_l2_displacement": 0.0,
                "per_tensor": {name: {"parameter_count": int(value.numel()), "displacement_l2": 0.0} for name, value in initial.items()},
            }
        pairwise[str(seed)] = {"0": {
            "B-DUP_vs_B-MATCHED": {"update_cosine": None, "update_distance_l2": 0.0},
            "B-DUP_vs_B-SHAM": {"update_cosine": None, "update_distance_l2": 0.0},
            "B-MATCHED_vs_B-SHAM": {"update_cosine": None, "update_distance_l2": 0.0},
        }}
        for epoch in (1, 2, 3):
            updates: dict[str, dict[str, torch.Tensor]] = {}
            for arm in ARMS:
                key = f"{seed}/{arm}/epoch-{epoch}"
                item = checkpoint_map[key]
                integrity = read_json(RUN / "runs" / f"seed-{seed}" / arm / "run-integrity.json")
                state = load_state(Path(item["path"]), seed, arm, epoch, item["sha256"], integrity["initial_head_sha256"])
                if set(state) != set(initial):
                    raise RuntimeError(f"state-dict key set differs from initialization: {key}")
                updates[arm] = {name: state[name].detach().cpu().to(torch.float64) - initial[name] for name in initial}
                distance, per_tensor = vector_stats(updates[arm])
                per_cell[key] = {
                    "checkpoint_sha256": item["sha256"], "head_state_sha256": state_digest(state),
                    "global_l2_displacement": distance, "per_tensor": per_tensor,
                }
            pairwise.setdefault(str(seed), {})
            pairwise[str(seed)][str(epoch)] = {}
            for left, right in (("B-DUP", "B-MATCHED"), ("B-DUP", "B-SHAM"), ("B-MATCHED", "B-SHAM")):
                left_delta, right_delta = updates[left], updates[right]
                pairwise[str(seed)][str(epoch)][f"{left}_vs_{right}"] = {
                    "update_cosine": cosine_between(left_delta, right_delta),
                    "update_distance_l2": math.sqrt(sum(float(torch.sum((left_delta[name] - right_delta[name]) ** 2).item()) for name in left_delta)),
                }
    return {
        "status": "V08O_PARAMETER_TRAJECTORIES_COMPLETE",
        "source_checkpoint_tree_sha256": preflight["checkpoint_hash_tree_sha256"],
        "initialization_templates": initial_map,
        "by_seed_arm_epoch": per_cell,
        "pairwise_arm_update_geometry": pairwise,
        "interpretation_limit": "descriptive parameter-space distances and cosines; no basin or mechanism claims",
    }


def plot_trajectories(behavior: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    matrix = behavior["response_matrix"]
    for group in ("sham", "matched"):
        out = OUTPUT / f"{group}-trajectory-planes.svg"
        if out.exists():
            raise FileExistsError(out)
        out.write_text(render_trajectory_svg(matrix, group), encoding="utf-8", newline="\n")
        paths.append(out)
    return paths


def render_trajectory_svg(matrix: dict[str, Any], group: str) -> str:
    """Render fixed trajectory panels as deterministic static SVG, dependency-free."""
    if group not in ("sham", "matched"):
        raise ValueError(f"unknown trajectory group: {group}")
    x_metric = "sham_l1" if group == "sham" else "matched_l1"
    x_label = "Sham posterior L1" if group == "sham" else "Matched-neutral posterior L1"
    title = "SHAM locality trajectories" if group == "sham" else "Matched-neutral locality trajectories"
    y_metrics = (
        ("strict_transition", "Strict transition"),
        ("anchor_old_map", "Anchor old-winner MAP"),
        ("fact_new_map", "Fact new-winner MAP"),
        ("new_probability_delta", "Fact new-winner Δp"),
    )
    width, height = 1600, 1060
    left, right, top, bottom = 74, 28, 72, 66
    panel_w = (width - left - right) / 4
    panel_h = (height - top - bottom) / 3
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        '<style>text{font-family:Segoe UI,Arial,sans-serif;fill:#17212b}.tick{font-size:11px}.axis{font-size:12px}.panel-title{font-size:14px;font-weight:600}.suptitle{font-size:20px;font-weight:700}.legend{font-size:13px}</style>',
        f'<text class="suptitle" x="{width / 2}" y="32" text-anchor="middle">{html.escape(title)} — fixed-checkpoint paths (epoch 0–3)</text>',
    ]
    for row_index, seed in enumerate(SEEDS):
        for col_index, (y_metric, y_label) in enumerate(y_metrics):
            x0 = left + col_index * panel_w
            y0 = top + row_index * panel_h
            px0, py0 = x0 + 54, y0 + 34
            pw, ph = panel_w - 76, panel_h - 82
            series: dict[str, tuple[list[float], list[float]]] = {}
            for arm in ARMS:
                xs, ys = [], []
                for epoch in EPOCHS:
                    point = matrix[str(seed)][arm][str(epoch)]["overall"]
                    xs.append(float(point[x_metric]))
                    ys.append(float(point[y_metric]))
                series[arm] = (xs, ys)
            all_x = [value for xs, _ in series.values() for value in xs]
            all_y = [value for _, ys in series.values() for value in ys]
            x_min, x_max = min(all_x), max(all_x)
            y_min, y_max = min(all_y), max(all_y)
            x_pad = max((x_max - x_min) * 0.08, 0.002)
            y_pad = max((y_max - y_min) * 0.08, 0.002)
            x_min, x_max = max(0.0, x_min - x_pad), x_max + x_pad
            y_min, y_max = max(0.0, y_min - y_pad), min(1.0, y_max + y_pad)
            if x_max <= x_min:
                x_max = x_min + 0.01
            if y_max <= y_min:
                y_max = y_min + 0.01
            parts.append(f'<text class="panel-title" x="{px0 + pw / 2:.1f}" y="{y0 + 18:.1f}" text-anchor="middle">Seed {seed} · {html.escape(y_label)}</text>')
            for tick in range(5):
                frac = tick / 4
                gx = px0 + frac * pw
                gy = py0 + frac * ph
                xv = x_min + frac * (x_max - x_min)
                yv = y_max - frac * (y_max - y_min)
                parts.append(f'<line x1="{gx:.2f}" y1="{py0:.2f}" x2="{gx:.2f}" y2="{py0 + ph:.2f}" stroke="#dce2e7" stroke-width="1"/>')
                parts.append(f'<line x1="{px0:.2f}" y1="{gy:.2f}" x2="{px0 + pw:.2f}" y2="{gy:.2f}" stroke="#dce2e7" stroke-width="1"/>')
                parts.append(f'<text class="tick" x="{gx:.2f}" y="{py0 + ph + 17:.2f}" text-anchor="middle">{xv:.3f}</text>')
                parts.append(f'<text class="tick" x="{px0 - 7:.2f}" y="{gy + 4:.2f}" text-anchor="end">{yv:.3f}</text>')
            parts.append(f'<line x1="{px0:.2f}" y1="{py0:.2f}" x2="{px0:.2f}" y2="{py0 + ph:.2f}" stroke="#46525c"/>')
            parts.append(f'<line x1="{px0:.2f}" y1="{py0 + ph:.2f}" x2="{px0 + pw:.2f}" y2="{py0 + ph:.2f}" stroke="#46525c"/>')
            for arm in ARMS:
                xs, ys = series[arm]
                points = []
                for x, y in zip(xs, ys):
                    sx = px0 + (x - x_min) / (x_max - x_min) * pw
                    sy = py0 + (y_max - y) / (y_max - y_min) * ph
                    points.append((sx, sy))
                polyline = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
                parts.append(f'<polyline points="{polyline}" fill="none" stroke="{COLORS[arm]}" stroke-width="2" opacity="0.9"/>')
                for epoch, (sx, sy) in zip(EPOCHS, points):
                    if epoch == 0:
                        parts.append(f'<circle cx="{sx:.2f}" cy="{sy:.2f}" r="5" fill="{COLORS[arm]}"/>')
                    elif epoch == 1:
                        parts.append(f'<rect x="{sx - 4:.2f}" y="{sy - 4:.2f}" width="8" height="8" fill="{COLORS[arm]}"/>')
                    elif epoch == 2:
                        parts.append(f'<path d="M {sx:.2f} {sy - 5:.2f} L {sx + 5:.2f} {sy + 4:.2f} L {sx - 5:.2f} {sy + 4:.2f} Z" fill="{COLORS[arm]}"/>')
                    else:
                        parts.append(f'<path d="M {sx:.2f} {sy - 5:.2f} L {sx + 5:.2f} {sy:.2f} L {sx:.2f} {sy + 5:.2f} L {sx - 5:.2f} {sy:.2f} Z" fill="{COLORS[arm]}"/>')
                    parts.append(f'<text class="tick" x="{sx + 5:.2f}" y="{sy - 5:.2f}" fill="{COLORS[arm]}">{epoch}</text>')
            parts.append(f'<text class="axis" x="{px0 + pw / 2:.2f}" y="{py0 + ph + 34:.2f}" text-anchor="middle">{html.escape(x_label)}</text>')
    legend_y = height - 14
    start_x = width / 2 - 180
    for index, arm in enumerate(ARMS):
        lx = start_x + index * 130
        parts.append(f'<line x1="{lx:.1f}" y1="{legend_y - 4}" x2="{lx + 28:.1f}" y2="{legend_y - 4}" stroke="{COLORS[arm]}" stroke-width="3"/>')
        parts.append(f'<text class="legend" x="{lx + 34:.1f}" y="{legend_y}">{arm}</text>')
    parts.append('</svg>')
    return "\n".join(parts) + "\n"


def build_report(behavior: dict[str, Any], parameters: dict[str, Any], figure_paths: list[Path], raw_sha: str) -> str:
    lines = [
        "# JEV v0.8O: Capability Trajectory Cartography",
        "",
        "**Identity:** POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS  ",
        "**Status:** Post-hoc trajectory inference and descriptive analysis complete.  ",
        "**Original v0.8N Phase B:** `EVALUATION_INPUT_CONTRACT_INCOMPLETE`; unchanged.  ",
        "**v0.8N-E1:** post-registered repaired terminal evaluation; unchanged.  ",
        "**Training/checkpoint selection:** none; every sealed epoch was evaluated, and no epoch is promoted.",
        "",
        "## Scope and boundaries",
        "",
        "This analysis evaluates all 27 byte-sealed epoch checkpoints plus the three shared per-seed initialization templates as epoch-0 baselines on the same E1 held-out panel, candidate basis, and exact candidate join. It is a new post-hoc evaluation identity with opening count 3. The full 288,000-row prediction matrix was sealed before epoch-wise metrics were analyzed. The frozen backbone was not loaded; there was no training, NewTight/legacy access, or Phoenix access.",
        "",
        "The report describes optimizer trajectories of the learned decision heads over this held-out object. It does not identify a mechanism, establish a valid alternate operating point, or change the terminal E1 result.",
        "",
        "## Trajectory figures",
        "",
        "Epoch numbers label points along each line; colors identify DUP, MATCHED, and SHAM. Rows are the three fixed seeds. Axes show separate capability coordinates; no composite score is used.",
        "",
    ]
    for path in figure_paths:
        lines.extend([f"![{path.stem}]({path.name})", ""])
    lines.extend([
        "## Complete arm × seed × epoch response matrix",
        "",
        "Rates are proportions. `A_old` is anchor old-winner MAP; `F_new` is fact-view new-winner MAP; `T_strict` is their joint event. Probability movement and exact-delta error remain separate.",
        "",
        "| Seed | Epoch | Arm | Sham L1 | Sham flips | Matched L1 | Matched flips | A_old | F_new | T_strict | Δp_new | Δ MAE | Anchor NLL | Anchor Brier |",
        "|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    matrix = behavior["response_matrix"]
    for seed in SEEDS:
        for epoch in EPOCHS:
            for arm in ARMS:
                m = matrix[str(seed)][arm][str(epoch)]["overall"]
                lines.append(
                    f"| {seed} | {epoch} | {arm} | {m['sham_l1']:.6f} | {m['sham_map_flip']:.4f} | {m['matched_l1']:.6f} | {m['matched_map_flip']:.4f} | {m['anchor_old_map']:.4f} | {m['fact_new_map']:.4f} | {m['strict_transition']:.4f} | {m['new_probability_delta']:.6f} | {m['delta_mae']:.6f} | {m['anchor_nll']:.6f} | {m['anchor_brier']:.6f} |"
                )
    lines.extend([
        "",
        "## Four-cell transition decomposition",
        "",
        "Each cell is shown as `A∧F / A∧¬F / ¬A∧F / ¬A∧¬F` proportions. These four events partition each 2,000-neighborhood cell; family-level counts are in the machine report.",
        "",
        "| Seed | Epoch | Arm | A∧F | A∧¬F | ¬A∧F | ¬A∧¬F |",
        "|---:|---:|---|---:|---:|---:|---:|",
    ])
    for seed in SEEDS:
        for epoch in EPOCHS:
            for arm in ARMS:
                cells = behavior["transition_four_cell_decomposition"][str(seed)][arm][str(epoch)]["overall"]
                lines.append(f"| {seed} | {epoch} | {arm} | " + " | ".join(f"{cells[name]['proportion']:.4f}" for name, _, _ in TRANSITION_CELLS) + " |")
    lines.extend([
        "",
        "## Paired SHAM−MATCHED trajectory",
        "",
        "Signed neighborhood-paired differences, averaged over the same 2,000 IDs. Negative L1 means lower drift under SHAM. These are descriptive means, not pooled optimizer-seed inference.",
        "",
        "| Seed | Epoch | Δ sham L1 | Δ sham flips | Δ matched L1 | Δ matched flips | Δ A_old | Δ F_new | Δ strict | Δp_new | Δ MAE |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for seed in SEEDS:
        for epoch in EPOCHS:
            diff = behavior["paired_sham_minus_matched_trajectory"][str(seed)][str(epoch)]["mean_by_metric"]
            cols = ["sham_l1", "sham_map_flip", "matched_l1", "matched_map_flip", "anchor_old_map", "fact_new_map", "strict_transition", "new_probability_delta", "delta_mae"]
            lines.append(f"| {seed} | {epoch} | " + " | ".join(f"{diff[key]:+.5f}" for key in cols) + " |")
    lines.extend([
        "",
        "## Parameter-space path",
        "",
        "`Δφ` is the float64 L2 distance from the shared seed initialization. Per-tensor displacement, paired update-vector cosine, and pairwise update distance are in the machine-readable parameter report.",
        "",
        "| Seed | Epoch | DUP ‖Δφ‖₂ | MATCHED ‖Δφ‖₂ | SHAM ‖Δφ‖₂ | cos(DUP,MATCHED) | cos(DUP,SHAM) | cos(MATCHED,SHAM) |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for seed in SEEDS:
        for epoch in (1, 2, 3):
            norms = [parameters["by_seed_arm_epoch"][f"{seed}/{arm}/epoch-{epoch}"]["global_l2_displacement"] for arm in ARMS]
            pairs = parameters["pairwise_arm_update_geometry"][str(seed)][str(epoch)]
            cos = [pairs["B-DUP_vs_B-MATCHED"]["update_cosine"], pairs["B-DUP_vs_B-SHAM"]["update_cosine"], pairs["B-MATCHED_vs_B-SHAM"]["update_cosine"]]
            cos_text = ["—" if value is None else f"{value:.5f}" for value in cos]
            lines.append(f"| {seed} | {epoch} | " + " | ".join([*(f"{value:.5f}" for value in norms), *cos_text]) + " |")
    lines.extend([
        "",
        "## Family visibility and interpretation",
        "",
        "All four families remain separately available at every seed/arm/epoch in `trajectory-response-matrix-v01.json` and `transition-four-cell-decomposition-v01.json`. The descriptive taxonomy—early broad coupling, late coupling, anchor-specific coupling, fact-response coupling, low-response basin, and nonmonotonicity—is not assigned by a threshold or collapsed into a pass score.",
        "",
        "No epoch is selected or promoted. Any apparent epoch-specific tradeoff is only a hypothesis for a future prospective duration/dose experiment.",
        "",
        "## Provenance",
        "",
        f"- Sealed O raw-prediction SHA-256: `{raw_sha}` (`288,000` rows).",
        f"- Analysis schema SHA-256: `{sha256_file(ANALYSIS_CONTRACT)}`.",
        f"- E1 frozen metric implementation SHA-256: `{FROZEN_ANALYZER_SHA256}`.",
        "- Original Phase-B disposition and E1 result artifacts were not modified.",
        "- Machine-readable artifacts and final result seal are in the O output directory.",
        f"- Raw prediction identity audit SHA-256: `{sha256_file(OUTPUT / 'raw-prediction-identity-audit-v01.json')}`; it checked cell/checkpoint/view bindings without computing metrics.",
        f"- Reporting-only correction SHA-256: `{sha256_file(OUTPUT / 'analysis-reporting-correction-v01.json')}`; it adds explicitly null epoch-0 update cosines required by the frozen schema and does not change prediction or metric values.",
        "",
    ])
    return "\n".join(lines)


def analyze() -> None:
    preflight = read_json(OUTPUT / "preinference-verification-v01.json")
    tree, inference = verify_sealed_predictions(preflight)
    behavior = stream_behavioral_analysis(tree)
    parameters = parameter_trajectory(preflight)
    write_json_exclusive(OUTPUT / "trajectory-response-matrix-v01.json", {
        "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
        **behavior,
    })
    write_json_exclusive(OUTPUT / "transition-four-cell-decomposition-v01.json", {
        "status": "V08O_FOUR_CELL_TRANSITION_PARTITIONS_COMPLETE",
        "definition": "A = anchor old-winner MAP; F = fact-view new-winner MAP",
        "cells": [name for name, _, _ in TRANSITION_CELLS],
        "by_seed_arm_epoch": behavior["transition_four_cell_decomposition"],
    })
    write_json_exclusive(OUTPUT / "paired-sham-minus-matched-trajectories-v01.json", {
        "status": "V08O_PAIRED_SHAM_MINUS_MATCHED_TRAJECTORIES_COMPLETE",
        "definition": "SHAM minus MATCHED within the same neighborhood IDs; means only, no seed pooling",
        "by_seed_epoch": behavior["paired_sham_minus_matched_trajectory"],
    })
    write_json_exclusive(OUTPUT / "parameter-trajectories-v01.json", parameters)
    figures = plot_trajectories(behavior)
    report = build_report(behavior, parameters, figures, sha256_file(OUTPUT / "raw-predictions-v01.jsonl"))
    report_path = OUTPUT / "trajectory-cartography-v01.md"
    if report_path.exists():
        raise FileExistsError(report_path)
    report_path.write_text(report, encoding="utf-8", newline="\n")

    files = (
        "preinference-verification-v01.json", "v08o-opening-receipt-v01.json", "opened-input-validation-v01.json",
        "raw-predictions-v01.jsonl", "input-geometry-diagnostics-v01.jsonl", "raw-prediction-hash-tree-v01.json",
        "inference-receipt-v01.json", "neighborhood-metrics-v01.jsonl", "trajectory-response-matrix-v01.json",
        "transition-four-cell-decomposition-v01.json", "paired-sham-minus-matched-trajectories-v01.json",
        "parameter-trajectories-v01.json", "sham-trajectory-planes.svg", "matched-trajectory-planes.svg",
        "raw-prediction-identity-audit-v01.json", "analysis-reporting-correction-v01.json",
        "trajectory-cartography-v01.md",
    )
    seal = {
        "status": "V08O_POSTHOC_TRAJECTORY_CARTOGRAPHY_SEALED",
        "identity": "POST-HOC v0.8O CAPABILITY TRAJECTORY CARTOGRAPHY OF SEALED PHASE-B CHECKPOINTS",
        "original_phase_b_disposition": "EVALUATION_INPUT_CONTRACT_INCOMPLETE",
        "e1_result_seal_sha256": "a23b3a6dc90a739888ae8d1cab440ac6c8f6ed23dd12b26c1bfd7786cd56ce68",
        "opening_count": 3, "prediction_rows": 288_000, "checkpoint_count": 27,
        "initialization_baseline_cells": 9, "checkpoint_selection": False, "training": False,
        "newtight": False, "legacy_evaluation": False, "phoenix_access": False,
        "analysis_contract_sha256": sha256_file(ANALYSIS_CONTRACT),
        "files": {name: {"sha256": sha256_file(OUTPUT / name), "bytes": (OUTPUT / name).stat().st_size} for name in files},
        "sealed_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    write_json_exclusive(OUTPUT / "v08o-result-seal-v01.json", seal)
    print(json.dumps({"status": seal["status"], "prediction_sha256": seal["files"]["raw-predictions-v01.jsonl"]["sha256"],
                      "seal_sha256": sha256_file(OUTPUT / "v08o-result-seal-v01.json"), "rows": 288000}, separators=(",", ":")))


if __name__ == "__main__":
    analyze()
