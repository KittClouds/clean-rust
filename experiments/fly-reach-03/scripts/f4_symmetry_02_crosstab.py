"""Post-outcome block x cue-incidence localization for locked RUN4 outputs."""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

SCRIPT = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT.parent))

import f4_symmetry_02_leverage as parent  # noqa: E402
from f4_symmetry_01_common import (  # noqa: E402
    BLOCKS, CONTRACT_SHA, json_read, load_truth_after_integrity, read_raw,
    sha_file, write_json,
)

ROOT = parent.ROOT
RUN = parent.RUN
OUT = ROOT / "artifacts/f4-symmetry-02-block-pattern-crosstab"


def freeze_contract(out: Path) -> None:
    if out.exists():
        raise RuntimeError(f"output already exists; refusing overwrite: {out}")
    out.mkdir(parents=True)
    required = {
        "parent_integrity_receipt_sha256": RUN / "INTEGRITY-RECEIPT.json",
        "parent_prediction_lock_sha256": RUN / "PREDICTION-LOCK.json",
        "predictor_sha256": RUN / "RAW-PREDICTORS.bin",
        "scoring_truth_sha256": RUN / "RAW-SCORING-TRUTH.bin",
        "parent_SYMMETRY02_analysis_sha256": ROOT / "artifacts/f4-symmetry-02-leverage-localization/LEVERAGE-LOCALIZATION.json",
        "parent_SYMMETRY02_receipt_sha256": ROOT / "artifacts/f4-symmetry-02-leverage-localization/TERMINAL-RECEIPT.json",
    }
    source_hashes = {key: sha_file(path) for key, path in required.items()}
    contract = {
        "schema": "F4-SYMMETRY-02-block-pattern-crosstab-contract-v1",
        "status": "FROZEN_BEFORE_CROSSTAB_CALCULATION",
        "analysis_class": "EXPLORATORY_POST_OUTCOME_QUALIFICATION_ONLY",
        "parent_contract_sha256": CONTRACT_SHA,
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "analysis_script_sha256": sha_file(SCRIPT),
        "source_hashes": source_hashes,
        "population": "all 13,420 existing RUN4 U* rows; no refitting, resampling, row exclusion, or new seeds",
        "grid": "all four frozen blocks crossed with all 16 possible 4-bit absolute cue-incidence patterns; empty cells retained",
        "cue_pattern_encoding": "bit c is stored tuple[c].incidence; string label prints bit3..bit0, so 0011 means incidence in cue slots 0 and 1",
        "sign_rule": "+1 iff locked held-out logit > 0, otherwise -1, matching RUN4 scoring",
        "leverage_weight": "w=q*abs(native proposed delta)*abs(reference g), using frozen inclusion weight q",
        "cell_metrics": [
            "row_count", "cell_leverage_mass", "global_leverage_share", "disagreement_count",
            "disagreement_row_fraction", "disagreement_leverage_mass", "disagreement_leverage_share_global",
            "D_row_accuracy_on_disagreements", "C_row_accuracy_on_disagreements",
            "D_leverage_accuracy_on_disagreements", "C_leverage_accuracy_on_disagreements",
            "delta_psi_local", "delta_psi_global_contribution",
        ],
        "delta_psi_formula": "2*sum_cell(w*(I[D correct]-I[C correct]))/sum_all(w); cell contributions must sum to pooled Psi_D-Psi_C",
        "uncertainty": "none; deterministic decomposition of previously unlocked qualification outputs",
        "scope": "No causal, confirmatory, transferable, measured REACH-03, native-controller, biological, or PHENO claim",
    }
    write_json(out / "CROSSTAB-CONTRACT.json", contract)
    print(json.dumps({"status": contract["status"], "output": str(out), "script_sha256": contract["analysis_script_sha256"]}, sort_keys=True))


def _metric(mask: Any, *, block: int, pattern: int, q: Any, m: Any, g: Any,
            target: Any, c_sign: Any, d_sign: Any, total_leverage: float) -> dict[str, Any]:
    import numpy as np
    count = int(mask.sum())
    leverage = q[mask] * m[mask] * np.abs(g[mask])
    cell_mass = float(leverage.sum(dtype=np.float64))
    disagree = c_sign[mask] != d_sign[mask]
    disagree_count = int(disagree.sum())
    disagree_mass = float(leverage[disagree].sum(dtype=np.float64)) if disagree_count else 0.0
    c_correct = c_sign[mask] == target[mask]
    d_correct = d_sign[mask] == target[mask]
    delta_mass = float(np.sum(leverage * (d_correct.astype(np.float64) - c_correct.astype(np.float64)), dtype=np.float64))
    if cell_mass > 0.0:
        delta_local = 2.0 * delta_mass / cell_mass
    else:
        delta_local = None
    row_delta = 2.0 * delta_mass / total_leverage
    d_row_accuracy = float(np.mean(d_correct[disagree])) if disagree_count else None
    c_row_accuracy = float(np.mean(c_correct[disagree])) if disagree_count else None
    if disagree_mass > 0.0:
        d_lev_accuracy = float(np.sum(leverage[disagree] * d_correct[disagree], dtype=np.float64) / disagree_mass)
        c_lev_accuracy = float(np.sum(leverage[disagree] * c_correct[disagree], dtype=np.float64) / disagree_mass)
    else:
        d_lev_accuracy = None
        c_lev_accuracy = None
    return {
        "block": int(block),
        "cue_incidence_pattern": f"{pattern:04b}",
        "row_count": count,
        "cell_leverage_mass": cell_mass,
        "global_leverage_share": cell_mass / total_leverage,
        "disagreement_count": disagree_count,
        "disagreement_row_fraction": (disagree_count / count) if count else None,
        "disagreement_leverage_mass": disagree_mass,
        "disagreement_leverage_share_global": disagree_mass / total_leverage,
        "D_row_accuracy_on_disagreements": d_row_accuracy,
        "C_row_accuracy_on_disagreements": c_row_accuracy,
        "D_leverage_accuracy_on_disagreements": d_lev_accuracy,
        "C_leverage_accuracy_on_disagreements": c_lev_accuracy,
        "delta_psi_local": delta_local,
        "delta_psi_global_contribution": row_delta,
    }


def analyze(out: Path) -> None:
    import csv
    import numpy as np
    contract_path = out / "CROSSTAB-CONTRACT.json"
    contract = json_read(contract_path)
    if contract.get("status") != "FROZEN_BEFORE_CROSSTAB_CALCULATION" or sha_file(SCRIPT) != contract.get("analysis_script_sha256"):
        raise RuntimeError("crosstab contract or analysis script hash mismatch")
    for field, path in (
        ("parent_integrity_receipt_sha256", RUN / "INTEGRITY-RECEIPT.json"),
        ("parent_prediction_lock_sha256", RUN / "PREDICTION-LOCK.json"),
        ("predictor_sha256", RUN / "RAW-PREDICTORS.bin"),
        ("scoring_truth_sha256", RUN / "RAW-SCORING-TRUTH.bin"),
        ("parent_SYMMETRY02_analysis_sha256", ROOT / "artifacts/f4-symmetry-02-leverage-localization/LEVERAGE-LOCALIZATION.json"),
        ("parent_SYMMETRY02_receipt_sha256", ROOT / "artifacts/f4-symmetry-02-leverage-localization/TERMINAL-RECEIPT.json"),
    ):
        if sha_file(path) != contract["source_hashes"][field]:
            raise RuntimeError(f"parent input changed after crosstab contract freeze: {field}")
    data = read_raw(RUN / "RAW-PREDICTORS.bin", RUN / "RAW-SCORING-TRUTH.bin")
    integrity = json_read(RUN / "INTEGRITY-RECEIPT.json")
    q, target, native, _preweight, reference = load_truth_after_integrity(data, RUN / "INTEGRITY-RECEIPT.json")
    predictions, prediction_hashes = parent._load_predictions()
    c_sign = np.where(np.asarray(predictions["C"]) > 0.0, 1, -1).astype(np.int8)
    d_sign = np.where(np.asarray(predictions["D"]) > 0.0, 1, -1).astype(np.int8)
    target_sign = np.where(reference > 0.0, 1, -1).astype(np.int8)
    if not np.array_equal(target.astype(np.int8), target_sign):
        raise RuntimeError("target/reference sign mismatch")
    if integrity.get("status") != "PASS":
        raise RuntimeError("parent integrity status is not PASS")
    m = np.abs(native.astype(np.float64))
    g = reference.astype(np.float64)
    q64 = q.astype(np.float64)
    leverage = q64 * m * np.abs(g)
    total_leverage = float(leverage.sum(dtype=np.float64))
    total_delta = 2.0 * float(np.sum(leverage * ((d_sign == target_sign).astype(np.float64) - (c_sign == target_sign).astype(np.float64)), dtype=np.float64)) / total_leverage
    pattern = np.zeros(data.count, dtype=np.uint8)
    for cue in range(4):
        pattern |= data.tuples["incidence"][:, cue].astype(np.uint8) << cue
    cells: list[dict[str, Any]] = []
    for block in BLOCKS:
        for pattern_id in range(16):
            mask = (data.blocks == block) & (pattern == pattern_id)
            cells.append(_metric(mask, block=block, pattern=pattern_id, q=q64, m=m, g=g,
                                 target=target_sign, c_sign=c_sign, d_sign=d_sign,
                                 total_leverage=total_leverage))
    reconstructed = float(sum(float(cell["delta_psi_global_contribution"]) for cell in cells))
    if abs(reconstructed - total_delta) > 1e-12:
        raise RuntimeError("block-pattern contributions do not reconstruct pooled DeltaPsi")
    if sum(int(cell["row_count"]) for cell in cells) != data.count:
        raise RuntimeError("block-pattern grid does not cover all rows exactly once")
    nonempty = [cell for cell in cells if cell["row_count"] > 0]
    result = {
        "schema": "F4-SYMMETRY-02-block-pattern-crosstab-v1",
        "status": "EXPLORATORY_POST_OUTCOME_QUALIFICATION_ONLY_COMPLETE",
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "contract_sha256": sha_file(contract_path),
        "analysis_script_sha256": sha_file(SCRIPT),
        "input_hashes": contract["source_hashes"],
        "locked_prediction_hashes_C_D": prediction_hashes,
        "rows": data.count,
        "grid_cells": len(cells),
        "nonempty_cells": len(nonempty),
        "pooled_psi_D_minus_C": total_delta,
        "cross_tab_contribution_sum": reconstructed,
        "contribution_reconstruction_abs_error": abs(reconstructed - total_delta),
        "cells": cells,
        "uncertainty": None,
        "claim_ceiling": "descriptive localization within the locked RUN4 qualification rows only",
    }
    write_json(out / "BLOCK-PATTERN-CROSSTAB.json", result)
    fields = list(cells[0].keys())
    with (out / "BLOCK-PATTERN-CROSSTAB.csv").open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(cells)
    md = [
        "# F4-SYMMETRY-02 Block × Cue-Incidence Cross-Tab",
        "",
        "**Disposition:** post-outcome, exploratory, analysis-only qualification sidecar over locked RUN4 predictions. No fits were run.",
        "",
        f"- Pooled Psi D-C: {total_delta:.9f}",
        f"- Cross-cell contribution sum: {reconstructed:.9f}",
        f"- Rows: {data.count}; nonempty cells: {len(nonempty)}/64",
        "",
        "`delta_psi_global_contribution` is each cell's additive share of pooled Psi D-C. Empty cells are retained in the CSV with zero counts and zero leverage.",
        "",
        "| Block | Pattern | Rows | Leverage share | C/D disagreements | Disagreement leverage share | D correct: rows | D correct: leverage | Local DeltaPsi | Pooled contribution |",
        "|---:|:---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for cell in nonempty:
        drow = "n/a" if cell["D_row_accuracy_on_disagreements"] is None else f"{cell['D_row_accuracy_on_disagreements']:.3%}"
        dlev = "n/a" if cell["D_leverage_accuracy_on_disagreements"] is None else f"{cell['D_leverage_accuracy_on_disagreements']:.3%}"
        md.append(f"| {cell['block']} | {cell['cue_incidence_pattern']} | {cell['row_count']} | {cell['global_leverage_share']:.3%} | {cell['disagreement_count']} | {cell['disagreement_leverage_share_global']:.3%} | {drow} | {dlev} | {cell['delta_psi_local']:.6f} | {cell['delta_psi_global_contribution']:.6f} |")
    md.extend([
        "",
        "The table uses the original cue-slot incidence bits; `0011` means the coordinate is incident to cue slots 0 and 1. The output does not establish a general symmetry law, replication across fresh task blocks, or a controller/trajectory effect.",
        "",
    ])
    with (out / "BLOCK-PATTERN-CROSSTAB.md").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write("\n".join(md))
        stream.flush()
    receipt = {
        "schema": "F4-SYMMETRY-02-block-pattern-crosstab-receipt-v1",
        "status": "CLOSED_EXPLORATORY_QUALIFICATION_ONLY",
        "parent_identity": "F4-SYMMETRY-01-RUN4",
        "contract_sha256": sha_file(contract_path),
        "analysis_script_sha256": sha_file(SCRIPT),
        "json_sha256": sha_file(out / "BLOCK-PATTERN-CROSSTAB.json"),
        "csv_sha256": sha_file(out / "BLOCK-PATTERN-CROSSTAB.csv"),
        "markdown_sha256": sha_file(out / "BLOCK-PATTERN-CROSSTAB.md"),
        "source_hashes": contract["source_hashes"],
        "rows": data.count,
        "grid_cells": len(cells),
        "nonempty_cells": len(nonempty),
        "fits_run": 0,
        "pooled_psi_D_minus_C": total_delta,
        "contribution_reconstruction_abs_error": abs(reconstructed - total_delta),
        "qualification_only": True,
        "measured_reach03_result": False,
        "biological_promotion": False,
        "PHENO_status_unchanged": True,
    }
    write_json(out / "TERMINAL-RECEIPT.json", receipt)
    print(json.dumps({"status": receipt["status"], "output": str(out), "pooled_delta_psi": total_delta,
                      "grid_cells": len(cells), "nonempty_cells": len(nonempty),
                      "reconstruction_abs_error": abs(reconstructed - total_delta)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("freeze-contract", "analyze"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    if args.mode == "freeze-contract":
        freeze_contract(args.out)
    else:
        analyze(args.out)


if __name__ == "__main__":
    main()
