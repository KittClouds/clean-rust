from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

from s09_common import RUN_ROOT, entry_for, read_json, sha256_file, tree_root, verify_tree, write_json


def markdown_report(metrics: dict[str, Any], extraction: dict[str, Any]) -> str:
    lines = [
        "# FAS-S09 Results: Depthwise Decision-Subspace Emergence",
        "",
        f"Feature cache root: `{metrics['feature_cache_root_sha256']}`",
        f"S01 terminal gate: exact S01-3 state/probability/metric reproduction; S08 plane checks within frozen tolerance.",
        f"Backbone parameter delta: `{extraction['backbone_parameter_delta']}`; repeated rows: `{extraction['deterministic_repeat']['sample_rows']}`; terminal feature parity rows: `{extraction['terminal_parent_parity']['events_compared']}`.",
        "",
        "This is exploratory analysis on the already-revealed S01 grouped split. No FAS-00 data, adaptive mechanism, significance test, or additional view was used.",
        "",
        "## Depth trajectory",
        "",
        "| Layer | M BA | F BA | M/F plane angles | M/F overlap | M cross-pipeline BA | F cross-pipeline BA | M terminal angles | F terminal angles |",
        "|---:|---:|---:|---|---:|---:|---:|---|---|",
    ]
    for row in metrics["layers"]:
        cells = row["cells"]
        angle = ", ".join(f"{x:.2f}°" for x in row["M_vs_F_plane"]["principal_angle_degrees"])
        mterm = ", ".join(f"{x:.2f}°" for x in row["convergence_to_S08_terminal_plane"]["M"]["principal_angle_degrees"])
        fterm = ", ".join(f"{x:.2f}°" for x in row["convergence_to_S08_terminal_plane"]["F"]["principal_angle_degrees"])
        lines.append(
            f"| {row['layer']} | {cells['M_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.4f} "
            f"| {cells['F_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.4f} "
            f"| {angle} | {row['M_vs_F_plane']['projection_overlap_fraction']:.5f} "
            f"| {cells['M_REP_F_PIPELINE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.4f} "
            f"| {cells['F_REP_M_PIPELINE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.4f} "
            f"| {mterm} | {fterm} |"
        )
    terminal = metrics["layers"][-1]
    lines.extend([
        "",
        "## Terminal reproduction",
        "",
        f"The layer-16 feature vectors matched the sealed S01-2 `mean_full` and final-position arrays byte-for-byte for {extraction['terminal_parent_parity']['events_compared']:,} events. The two layer-16 probe states and test probability arrays reproduced the S01-3 artifacts exactly. S08 effective pair normals had maximum absolute residuals M=`{metrics['terminal_gate']['S08_pair_normal_max_abs_residuals']['M']:.3e}`, F=`{metrics['terminal_gate']['S08_pair_normal_max_abs_residuals']['F']:.3e}`.",
        f"Layer-16 native balanced accuracy: M=`{terminal['cells']['M_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.6f}`, F=`{terminal['cells']['F_NATIVE']['metrics']['ALL_TEST_ROWS']['balanced_accuracy']:.6f}`.",
        "",
        "## Limits",
        "",
        "The grouped test split was already revealed in S01, so these depth curves are exploratory rather than confirmatory. Probe scores describe fixed linear accessibility; weak scores do not establish information absence. Subspace angles compare observer normals in the shared indexed residual coordinates, not circuits or semantic features. Cross cells transport the donor scaler and probe without refitting. No categorical emergence layer or causal transformer mechanism is claimed.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    if (RUN_ROOT / "result-tree-seal-v02.json").exists() or (RUN_ROOT / "result-disposition-v02.json").exists():
        raise RuntimeError("S09 result seal already exists; refusing overwrite")
    protocol_seal = read_json(RUN_ROOT / "inputs" / "project-snapshot" / "seals" / "protocol-seal-v02.json")
    snapshot_root = RUN_ROOT / "inputs" / "project-snapshot"
    snapshot_actual = [entry_for(snapshot_root.joinpath(*e["path"].split("/")), snapshot_root) for e in protocol_seal["entries"]]
    snapshot_actual.sort(key=lambda e: e["path"])
    if snapshot_actual != protocol_seal["entries"] or tree_root(snapshot_actual) != protocol_seal["root_sha256"]:
        raise RuntimeError("S09 protocol/source snapshot no longer matches its seal")
    feature_seal = read_json(RUN_ROOT / "feature-cache-v02" / "feature-cache-seal-v02.json")
    feature_actual = [entry_for((RUN_ROOT / "feature-cache-v02").joinpath(*e["path"].split("/")), RUN_ROOT / "feature-cache-v02") for e in feature_seal["entries"]]
    feature_actual.sort(key=lambda e: e["path"])
    if feature_actual != feature_seal["entries"] or tree_root(feature_actual) != feature_seal["root_sha256"]:
        raise RuntimeError("S09 feature cache no longer matches its seal")
    analysis_seal = read_json(RUN_ROOT / "analysis-v02" / "analysis-seal-v02.json")
    analysis_base = RUN_ROOT / "analysis-v02"
    analysis_actual = [entry_for(analysis_base.joinpath(*e["path"].split("/")), analysis_base) for e in analysis_seal["entries"]]
    analysis_actual.sort(key=lambda e: e["path"])
    if analysis_actual != analysis_seal["entries"] or tree_root(analysis_actual) != analysis_seal["root_sha256"]:
        raise RuntimeError("S09 analysis tree no longer matches its seal")
    metrics = read_json(RUN_ROOT / "metrics-v02.json")
    extraction = read_json(RUN_ROOT / "extraction-receipt-v02.json")
    if metrics["terminal_gate"].get("S01_probe_state_probability_and_metrics_reproduced_exactly") is not True:
        raise RuntimeError("S09 terminal S01 reproduction gate is not true")
    if metrics["terminal_gate"].get("S08_terminal_plane_reproduced_within_tolerance") is not True:
        raise RuntimeError("S09 S08 terminal plane gate is not true")
    if extraction.get("backbone_parameter_delta") != 0 or extraction.get("probe_fitting_performed") is not False:
        raise RuntimeError("S09 extraction receipt fails immutable-backbone/probe boundary")
    report = RUN_ROOT / "S09-RESULTS.md"
    report.write_text(markdown_report(metrics, extraction), encoding="utf-8", newline="\n")

    excluded = {"result-tree-seal-v02.json", "result-disposition-v02.json"}
    entries = [entry_for(path, RUN_ROOT) for path in RUN_ROOT.rglob("*") if path.is_file() and path.name not in excluded and "__pycache__" not in path.parts]
    entries.sort(key=lambda e: e["path"])
    root = tree_root(entries)
    seal = {
        "seal_id": "FAS_S09_RESULT_TREE_SEAL_V02",
        "project_id": "fas-s09-depthwise-decision-subspace-emergence",
        "entries": entries,
        "root_sha256": root,
        "S09_RESULT_READY": True,
        "FAS00_PHASE4_AUTHORIZED": False,
        "ADAPTIVE_MECHANISMS_AUTHORIZED": False,
    }
    write_json(RUN_ROOT / "result-tree-seal-v02.json", seal)
    disposition = {
        "disposition_id": "FAS_S09_DISPOSITION_V02",
        "FAS_S09_PROTOCOL_SEALED": True,
        "S09_PARENT_PREFLIGHT_PASS": True,
        "S09_FEATURE_EXTRACTION_COMPLETE": True,
        "S09_TERMINAL_REPRODUCED": True,
        "S09_ANALYSIS_COMPLETE": True,
        "S09_RESULT_READY": True,
        "result_tree_root_sha256": root,
        "fas00_access": False,
        "FAS00_SENSOR_PASS": False,
        "FAS00_PHASE4_AUTHORIZED": False,
        "ADAPTIVE_MECHANISMS_AUTHORIZED": False,
        "S09_LAYERWISE_EXTENSIONS_AUTHORIZED": False,
    }
    write_json(RUN_ROOT / "result-disposition-v02.json", disposition)
    print(f"result_root_sha256={root} entries={len(entries)} S09_RESULT_READY=true")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
