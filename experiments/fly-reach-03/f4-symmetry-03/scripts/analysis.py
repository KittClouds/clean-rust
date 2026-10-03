"""Score locked out-of-fold predictions after independent integrity PASS."""
from __future__ import annotations

import csv
import json
import math
import struct
from pathlib import Path

import numpy as np

from common import (
    ARMS, PATTERNS, PRED_MAGIC, REPO, read_json, read_predictors, require,
    sha_bytes, sha_file, write_json,
)


def _prediction(path: Path, arm: str, block: int, keys: list[bytes], row_hash: str) -> np.ndarray:
    raw = path.read_bytes()
    require(raw[:16] == PRED_MAGIC and raw[40:72].hex() == row_hash, f"prediction header/hash mismatch {path.name}")
    ver, heldout, arm_id, count = struct.unpack_from("<IQIQ", raw, 16)
    require((ver, heldout, arm_id, count) == (1, block, ARMS.index(arm), len(keys)), f"prediction identity mismatch {path.name}")
    require(len(raw) == 72 + 22 * count, "prediction stream size mismatch")
    logits = np.empty(count, dtype=np.float32)
    offset = 72
    for i, key in enumerate(keys):
        require(raw[offset:offset + 18] == key, f"prediction key/order mismatch {path.name}:{i}")
        logits[i] = struct.unpack_from("<f", raw, offset + 18)[0]
        offset += 22
    require(np.isfinite(logits).all(), f"nonfinite locked predictions {path.name}")
    return logits


def _truth(data, integrity_path: Path):
    receipt = read_json(integrity_path)
    require(receipt.get("status") == "PASS" and receipt.get("heldout_truth_state") == "SEALED", "truth firewall not passed")
    raw = data.truth_path.read_bytes()
    n = data.count
    p = np.ndarray(n, dtype="<f8", buffer=raw, offset=50, strides=(39,)).copy()
    y = np.ndarray(n, dtype="i1", buffer=raw, offset=58, strides=(39,)).copy()
    native = np.ndarray(n, dtype="<f4", buffer=raw, offset=59, strides=(39,)).copy()
    preweight = np.ndarray(n, dtype="<f4", buffer=raw, offset=63, strides=(39,)).copy()
    reference = np.ndarray(n, dtype="<f4", buffer=raw, offset=67, strides=(39,)).copy()
    require(np.isfinite(p).all() and (p > 0.0).all() and (p <= 1.0).all(), "invalid inclusion probabilities")
    require(np.isin(y, (-1, 1)).all(), "nonbinary measured target")
    require(np.isfinite(native).all() and np.isfinite(preweight).all() and np.isfinite(reference).all(), "nonfinite scoring truth")
    return 1.0 / p, y, native.astype(np.float64), preweight.astype(np.float64), reference.astype(np.float64)


def _balanced_error(sign: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> float | None:
    plus, minus = mask & (y == 1), mask & (y == -1)
    if not plus.any() or not minus.any():
        return None
    error = sign != y
    return 0.5 * (float(np.sum(q[plus] * error[plus]) / np.sum(q[plus])) + float(np.sum(q[minus] * error[minus]) / np.sum(q[minus])))


def _signed_margin(logit: np.ndarray, q: np.ndarray, y: np.ndarray, mask: np.ndarray) -> tuple[float | None, str]:
    plus, minus = mask & (y == 1), mask & (y == -1)
    margin = y.astype(np.float64) * logit.astype(np.float64)
    if plus.any() and minus.any():
        value = 0.5 * (float(np.sum(q[plus] * margin[plus]) / q[plus].sum()) + float(np.sum(q[minus] * margin[minus]) / q[minus].sum()))
        return value, "class_balanced_ipw"
    selected = plus | minus
    if selected.any():
        return float(np.sum(q[selected] * margin[selected]) / q[selected].sum()), "single_class_ipw"
    return None, "undefined"


def _concentration(w: np.ndarray) -> dict[str, object]:
    total = float(np.sum(w, dtype=np.float64))
    if len(w) == 0 or total <= 0.0:
        return {"leverage_total": total, "effective_sample_size": 0.0, "top_1pct_share": None, "top_5pct_share": None, "top_20pct_share": None}
    square = float(np.sum(w * w, dtype=np.float64))
    order = np.sort(w)[::-1]
    shares = {}
    for label, fraction in (("1pct", .01), ("5pct", .05), ("20pct", .20)):
        count = max(1, math.ceil(len(order) * fraction))
        shares[f"top_{label}_share"] = float(np.sum(order[:count], dtype=np.float64) / total)
    return {"leverage_total": total, "effective_sample_size": total * total / square if square > 0.0 else 0.0, **shares}


def _metrics(mask: np.ndarray, *, q: np.ndarray, y: np.ndarray, native: np.ndarray,
             preweight: np.ndarray, reference: np.ndarray, logits: np.ndarray) -> dict[str, object]:
    signs = np.where(logits > 0.0, 1, -1).astype(np.int8)
    err = _balanced_error(signs, q, y, mask)
    margin, margin_scope = _signed_margin(logits, q, y, mask)
    m = np.abs(native)
    w = q[mask] * m[mask] * np.abs(reference[mask])
    local_signs, local_y = signs[mask], y[mask]
    total = float(w.sum(dtype=np.float64))
    psi = None if total <= 0.0 else 2.0 * float(np.sum(w * (local_signs == local_y), dtype=np.float64) / total) - 1.0
    native_signs = np.where(native >= 0.0, 1, -1).astype(np.int8)
    oracle_signs = np.where(reference >= 0.0, 1, -1).astype(np.int8)
    native_psi = None if total <= 0 else 2.0 * float(np.sum(w * (native_signs[mask] == local_y), dtype=np.float64) / total) - 1.0
    oracle_psi = None if total <= 0 else 2.0 * float(np.sum(w * (oracle_signs[mask] == local_y), dtype=np.float64) / total) - 1.0
    u = np.clip(preweight[mask] + m[mask] * local_signs, 0.0, 2.0) - preweight[mask]
    g = reference[mask]
    dot = float(np.sum(q[mask] * u * g, dtype=np.float64))
    unorm = math.sqrt(float(np.sum(q[mask] * u * u, dtype=np.float64)))
    gnorm = math.sqrt(float(np.sum(q[mask] * g * g, dtype=np.float64)))
    eta = None if unorm == 0.0 or gnorm == 0.0 else dot / (unorm * gnorm)
    class_counts = {"positive": int(np.sum(mask & (y == 1))), "negative": int(np.sum(mask & (y == -1)))}
    return {
        "rows": int(mask.sum()), "class_counts": class_counts,
        "balanced_error": err,
        "omega_hat_unclipped": None if err is None else 1.0 - 2.0 * err,
        "omega_hat_clipped": None if err is None else max(0.0, 1.0 - 2.0 * err),
        "signed_margin": margin, "signed_margin_scope": margin_scope,
        "psi_prop": psi, "psi_native_sign": native_psi, "psi_reference_sign": oracle_psi,
        "eta_del": eta, "leverage_concentration": _concentration(w),
    }


def analyze(run: Path) -> None:
    integrity_path = run / "INTEGRITY-RECEIPT.json"
    integrity = read_json(integrity_path)
    require(integrity.get("status") == "PASS" and integrity.get("heldout_truth_state") == "SEALED", "analysis requires integrity PASS")
    manifest = read_json(run / "EXECUTION-MANIFEST.json")
    require(sha_file(run / "EXECUTION-MANIFEST.json") == read_json(run / "PREEXECUTION-SEAL.json")["execution_manifest_file_sha256"], "sealed execution manifest changed")
    # Revalidate every external source before opening the truth payload.
    src = read_json(run / "SOURCE-INPUT-MANIFEST.json")
    for entry in src["entries"]:
        path = REPO / Path(entry["path"])
        require(path.stat().st_size == entry["byte_length"] and sha_file(path) == entry["sha256"], f"sealed source drift: {entry['path']}")
    data = read_predictors(run / "RAW-PREDICTORS.bin", run / "RAW-SCORING-TRUTH.bin", [int(x) for x in manifest["block_ids"]])
    row_hashes = read_json(run / "FIT-MANIFEST-ROW-HASHES.json")["rows"]
    n = data.count
    logits = {arm: np.empty(n, dtype=np.float32) for arm in ARMS}
    position = {key: i for i, key in enumerate(data.keys)}
    for block in manifest["block_ids"]:
        hold = int(block)
        mask = data.blocks == hold
        keys = [key for key, selected in zip(data.keys, mask, strict=True) if selected]
        for arm in ARMS:
            fit_id = f"{arm}-H{hold}"
            local = _prediction(run / "heldout-predictions" / f"{fit_id}.bin", arm, hold, keys, row_hashes[fit_id])
            for key, value in zip(keys, local, strict=True):
                logits[arm][position[key]] = value
    require(all(np.isfinite(values).all() for values in logits.values()), "incomplete out-of-fold prediction panel")
    q, y, native, preweight, reference = _truth(data, integrity_path)
    # From this point onward the outcomes are open under the integrity receipt.
    pattern = np.zeros(n, dtype=np.uint8)
    for cue in range(4):
        pattern |= data.tuples["incidence"][:, cue].astype(np.uint8) << cue
    masks: dict[str, np.ndarray] = {"POOLED": np.ones(n, dtype=bool)}
    for block in manifest["block_ids"]:
        masks[f"BLOCK:{int(block)}"] = data.blocks == int(block)
    for value in range(16):
        masks[f"PATTERN:{value:04b}"] = pattern == value
    for block in manifest["block_ids"]:
        for value in range(16):
            masks[f"BLOCK_PATTERN:{int(block)}:{value:04b}"] = (data.blocks == int(block)) & (pattern == value)

    by_group: dict[str, dict[str, dict[str, object]]] = {}
    for group, mask in masks.items():
        by_group[group] = {arm: _metrics(mask, q=q, y=y, native=native, preweight=preweight, reference=reference, logits=logits[arm]) for arm in ARMS}
        c, d = by_group[group]["C"], by_group[group]["D"]
        ec, ed = c["balanced_error"], d["balanced_error"]
        pc, pd = c["psi_prop"], d["psi_prop"]
        by_group[group]["paired"] = {
            "error_D_minus_C": None if ec is None or ed is None else float(ed) - float(ec),
            "delta_psi_D_minus_C": None if pc is None or pd is None else float(pd) - float(pc),
        }

    named = list(PATTERNS)
    block_pattern_rows = []
    for block in manifest["block_ids"]:
        for pattern_name in (f"{i:04b}" for i in range(16)):
            group = f"BLOCK_PATTERN:{int(block)}:{pattern_name}"
            c, d = by_group[group]["C"], by_group[group]["D"]
            block_pattern_rows.append({
                "block": int(block), "incidence_pattern": pattern_name,
                "row_count": c["rows"], "positive_count": c["class_counts"]["positive"], "negative_count": c["class_counts"]["negative"],
                "leverage_total": c["leverage_concentration"]["leverage_total"],
                "balanced_error_C": c["balanced_error"], "balanced_error_D": d["balanced_error"],
                "signed_margin_C": c["signed_margin"], "signed_margin_D": d["signed_margin"],
                "psi_C": c["psi_prop"], "psi_D": d["psi_prop"],
                "delta_psi_D_minus_C": by_group[group]["paired"]["delta_psi_D_minus_C"],
                "leverage_ess": c["leverage_concentration"]["effective_sample_size"],
                "leverage_top_1pct_share": c["leverage_concentration"]["top_1pct_share"],
                "leverage_top_5pct_share": c["leverage_concentration"]["top_5pct_share"],
                "leverage_top_20pct_share": c["leverage_concentration"]["top_20pct_share"],
            })
    # Convert pattern-local effects to a transparent additive share of pooled Psi.
    all_w = q * np.abs(native) * np.abs(reference)
    all_d = float(all_w.sum(dtype=np.float64))
    pattern_global_contribution = {}
    for name in named:
        mask = pattern == int(name, 2)
        if all_d == 0.0:
            contribution = None
        else:
            c_ok = np.where(logits["C"] > 0, 1, -1) == y
            d_ok = np.where(logits["D"] > 0, 1, -1) == y
            contribution = 2.0 * float(np.sum(all_w[mask] * (d_ok[mask].astype(np.float64) - c_ok[mask].astype(np.float64)), dtype=np.float64)) / all_d
        pattern_global_contribution[name] = contribution

    interaction = []
    for block in manifest["block_ids"]:
        p11 = by_group[f"BLOCK_PATTERN:{int(block)}:0011"]["paired"]["delta_psi_D_minus_C"]
        p01 = by_group[f"BLOCK_PATTERN:{int(block)}:0101"]["paired"]["delta_psi_D_minus_C"]
        interaction.append({"block": int(block), "delta_psi_0011": p11, "delta_psi_0101": p01, "interaction_0011_minus_0101": None if p11 is None or p01 is None else float(p11) - float(p01)})
    support_receipt = read_json(REPO / "experiments/fly-reach-03/runs/f4-symmetry-03-structural-screen/STRUCTURAL-SCREEN.json")
    supported_0011 = [int(block["block_id"]) for block in support_receipt["batches"][-1]["blocks"] if int(block["patterns"].get("0011", 0)) > 0]
    positive_0011 = [row["block"] for row in block_pattern_rows if row["incidence_pattern"] == "0011" and row["delta_psi_D_minus_C"] is not None and row["delta_psi_D_minus_C"] > 0.0]
    result = {
        "schema": "F4-SYMMETRY-03-analysis-v1", "run_id": manifest["run_id"],
        "contract_sha256": manifest["contract_sha256"], "integrity_receipt_sha256": sha_file(integrity_path),
        "qualification_only": True, "measured_reach03_authorized": False,
        "row_count": n, "block_ids": manifest["block_ids"],
        "ipw_convention": "q=1/p_inclusion; equal class weight for balanced error and margin",
        "pooled": by_group["POOLED"],
        "blockwise": {str(block): by_group[f"BLOCK:{int(block)}"] for block in manifest["block_ids"]},
        "patternwise": {name: by_group[f"PATTERN:{int(name, 2):04b}"] for name in named},
        "pattern_global_additive_delta_psi_contribution": pattern_global_contribution,
        "pattern_interaction": interaction,
        "cross_block_0011_support": {"structurally_supported_blocks": supported_0011, "positive_delta_psi_blocks": positive_0011, "positive_count": len(positive_0011), "required_count": 6, "status": "SUPPORTED" if len(positive_0011) >= 6 else "NOT_SUPPORTED"},
        "block_pattern_table": block_pattern_rows,
        "claim_boundary": "Qualification replication only. A positive result supports repeatability within these structurally selected blocks; it is not a population-level or biological claim. Psi is local first-order alignment and does not guarantee trajectory improvement.",
    }
    write_json(run / "ANALYSIS.json", result)
    csv_fields = list(block_pattern_rows[0].keys())
    with (run / "BLOCK-PATTERN-SUMMARY.csv").open("x", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, lineterminator="\n")
        writer.writeheader(); writer.writerows(block_pattern_rows)
    with (run / "FINAL-OUTCOMES.csv").open("x", encoding="utf-8", newline="") as f:
        fields = ["scope", "arm", "rows", "positive_count", "negative_count", "balanced_error", "signed_margin", "psi_prop", "eta_del", "leverage_total", "leverage_ess", "top_1pct_share", "top_5pct_share", "top_20pct_share"]
        writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n"); writer.writeheader()
        for group in ("POOLED", *(f"BLOCK:{int(b)}" for b in manifest["block_ids"]), *(f"PATTERN:{int(p, 2):04b}" for p in named)):
            for arm in ARMS:
                item = by_group[group][arm]; conc = item["leverage_concentration"]
                writer.writerow({"scope": group, "arm": arm, "rows": item["rows"], "positive_count": item["class_counts"]["positive"], "negative_count": item["class_counts"]["negative"], "balanced_error": item["balanced_error"], "signed_margin": item["signed_margin"], "psi_prop": item["psi_prop"], "eta_del": item["eta_del"], "leverage_total": conc["leverage_total"], "leverage_ess": conc["effective_sample_size"], "top_1pct_share": conc["top_1pct_share"], "top_5pct_share": conc["top_5pct_share"], "top_20pct_share": conc["top_20pct_share"]})
    pooled = by_group["POOLED"]
    ec, ed = pooled["C"]["balanced_error"], pooled["D"]["balanced_error"]
    pc, pd = pooled["C"]["psi_prop"], pooled["D"]["psi_prop"]
    lines = [
        "# F4-SYMMETRY-03 Results",
        "",
        "Qualification-only fresh crossed-regime replication. RUN4 and SYMMETRY-02 were not re-sliced or pooled.",
        "",
        f"- Fresh task blocks: {', '.join(str(x) for x in manifest['block_ids'])}.",
        f"- Common scored rows: {n}.",
        f"- Pooled IPW-balanced error, C: {ec:.9g}; D: {ed:.9g}; D-C: {ed-ec:+.9g}.",
        f"- Pooled signed margin, C: {pooled['C']['signed_margin']:.9g}; D: {pooled['D']['signed_margin']:.9g}.",
        f"- Pooled Psi, C: {pc:.9g}; D: {pd:.9g}; D-C: {pd-pc:+.9g}.",
        f"- Cross-block 0011 rule: {len(positive_0011)}/8 positive; {result['cross_block_0011_support']['status']}.",
        "",
        "## Pattern-conditioned D-C effects",
        "",
        "| Pattern | Rows | Error C | Error D | Psi C | Psi D | Delta Psi D-C | Additive pooled Delta Psi share |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in named:
        item = by_group[f"PATTERN:{int(name, 2):04b}"]
        c, d = item["C"], item["D"]
        lines.append(f"| {name} | {c['rows']} | {c['balanced_error']} | {d['balanced_error']} | {c['psi_prop']} | {d['psi_prop']} | {item['paired']['delta_psi_D_minus_C']} | {pattern_global_contribution[name]} |")
    lines.extend(["", "## Leverage concentration", "", "Pooled and pattern summaries report effective sample size and top 1%, 5%, and 20% leverage shares in `ANALYSIS.json` and `FINAL-OUTCOMES.csv`. Large Psi values describe the declared first-order consequence weighting; they do not imply broad row-wise accuracy or trajectory improvement.", "", "## Block by pattern", "", "See `BLOCK-PATTERN-SUMMARY.csv` for all 8×16 cells, including empty cells.", "", "## Interpretation boundary", "", result["claim_boundary"], "Measured REACH-03 remains closed; no controller or PHENO work was opened.", ""])
    with (run / "RESULTS.md").open("x", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines))
    write_json(run / "ANALYSIS-RECEIPT.json", {
        "schema": "F4-SYMMETRY-03-analysis-receipt-v1", "status": "PASS",
        "integrity_receipt_sha256": sha_file(integrity_path), "analysis_script_sha256": sha_file(Path(__file__)),
        "analysis_json_sha256": sha_file(run / "ANALYSIS.json"), "results_sha256": sha_file(run / "RESULTS.md"),
        "block_pattern_csv_sha256": sha_file(run / "BLOCK-PATTERN-SUMMARY.csv"),
        "outcomes_csv_sha256": sha_file(run / "FINAL-OUTCOMES.csv"),
        "truth_opened_after_integrity_pass": True, "qualification_only": True,
    })
    print(json.dumps({"status": "ANALYSIS_COMPLETE", "pooled_error_C": ec, "pooled_error_D": ed, "pooled_delta_psi": pd-pc, "0011_positive_blocks": len(positive_0011)}, sort_keys=True))


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--run", type=Path, required=True)
    analyze(p.parse_args().run.resolve())
