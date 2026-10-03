from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

from s09_common import RUN_ROOT, S08_ROOT, entry_for, read_json, sha256_file, write_json
from s09_math import effective_geometry


V04_ROOT = RUN_ROOT / "history-v04" / "full-run-v04"
V04_PROJECT = RUN_ROOT / "history-v04" / "project-v04"
EXPECTED = {
    "v04_protocol_root_sha256": "0cb82fce63e4f390e63116d8ac94117bd0d3e52e037a1c89fd861b2e6998ab69",
    "v04_protocol_seal_file_sha256": "f377ca19cac0a6bceb729df015a9a50e717395519e2ef0b58414268a16911431",
    "v04_preflight_root_sha256": "4b2c98e5fa69b4ac3d6cbf297afab9e152e85a1508062ebf0bd6ff00390bbaa3",
    "v04_failure_sha256": "2b10293430730f694dabf9dff2a17794f81b7f0ef91f65a2fe78802280dd54b3",
    "M_probe_state_sha256": "1b3db11aa1fe691a98b40b0b9001c3f0125d1acd47f7c069ef53fd487a2d46e4",
    "F_probe_state_sha256": "2cbbd450468ae7ebbe073ca9badaf229dcf9d3b55ff80ed102ccf9eb7e942641",
    "S08_common_sha256": "1825739666f7e5605a5a48e26f5907f381b20591e3f3b83c8f7045c32a632346",
    "S08_math_sha256": "57c52d875dab894b3c9773fe91803e7ed0565017b0885144450618a0a1b9ab7e",
}
GEOMETRY_TOLERANCE = 1e-12


def load_npz(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as data:
        return {key: data[key].copy() for key in data.files}


def main() -> int:
    protocol_path = V04_PROJECT / "seals" / "protocol-seal-v04.json"
    protocol = read_json(protocol_path)
    if protocol.get("root_sha256") != EXPECTED["v04_protocol_root_sha256"]:
        raise RuntimeError("archived v04 project protocol root differs from correction binding")
    protocol_entries = [entry_for(V04_PROJECT.joinpath(*item["path"].split("/")), V04_PROJECT) for item in protocol["entries"]]
    protocol_entries.sort(key=lambda item: item["path"])
    from s09_common import tree_root

    if protocol_entries != protocol["entries"] or tree_root(protocol_entries) != protocol["root_sha256"]:
        raise RuntimeError("archived v04 source tree does not reproduce its protocol seal")
    protocol_seal_hash = sha256_file(protocol_path)[0]
    if protocol_seal_hash != EXPECTED["v04_protocol_seal_file_sha256"]:
        raise RuntimeError("archived v04 protocol seal file hash differs from correction binding")

    v04_preflight_path = V04_ROOT / "seals" / "preflight-seal-v04.json"
    v04_preflight = read_json(v04_preflight_path)
    if v04_preflight.get("root_sha256") != EXPECTED["v04_preflight_root_sha256"]:
        raise RuntimeError("archived v04 preflight root differs from correction binding")
    v04_failure_path = V04_ROOT / "analysis-failure-v04.json"
    failure = read_json(v04_failure_path)
    failure_hash = sha256_file(v04_failure_path)[0]
    if failure_hash != EXPECTED["v04_failure_sha256"]:
        raise RuntimeError("archived v04 failure receipt differs from correction binding")
    if failure.get("error") != "layer-16 M effective pair normals fail S08 identity: max_abs=4.180381107943276e-07":
        raise RuntimeError("archived v04 failure is not the contracted scaler precision mismatch")

    s08_geometry_path = S08_ROOT / "s01-analysis" / "s01-native-decision-geometry-v02.npz"
    if not s08_geometry_path.exists():
        s08_geometry_path = RUN_ROOT / "inputs" / "S08" / "s01-native-decision-geometry-v02.npz"
    with np.load(s08_geometry_path, allow_pickle=False) as s08:
        results = {}
        for surface in ("M", "F"):
            state_path = V04_ROOT / "analysis-v04" / "probes" / "layer-16" / surface / "probe-state-v04.npz"
            if sha256_file(state_path)[0] != EXPECTED[f"{surface}_probe_state_sha256"]:
                raise RuntimeError(f"archived v04 {surface} probe-state hash differs from correction binding")
            state = load_npz(state_path)
            parent = load_npz(RUN_ROOT / "inputs" / "S01-3" / "terminal-reference" / f"{surface}-probe-state.npz")
            for key in ("classes", "weights", "bias", "scaler_mean", "scaler_scale"):
                if not np.array_equal(state[key], parent[key]):
                    raise RuntimeError(f"archived v04 {surface} probe differs from S01 terminal reference: {key}")

            base = {
                "weights": state["weights"],
                "bias": state["bias"],
                "mean": state["scaler_mean"].astype(np.float64),
                "scale": state["scaler_scale"].astype(np.float64),
            }
            runtime = {
                "weights": state["weights"].astype(np.float32),
                "bias": state["bias"].astype(np.float32),
                "mean": state["scaler_mean"].astype(np.float32).astype(np.float64),
                "scale": state["scaler_scale"].astype(np.float32).astype(np.float64),
            }
            original = effective_geometry(**base)
            corrected = effective_geometry(**runtime)
            sealed_pair = np.asarray(s08[f"{surface}_pair_normals"], dtype=np.float64)
            original_residual = float(np.max(np.abs(original["pair_normals"] - sealed_pair)))
            corrected_residual = float(np.max(np.abs(corrected["pair_normals"] - sealed_pair)))
            if corrected_residual > GEOMETRY_TOLERANCE:
                raise RuntimeError(f"corrected {surface} S08 normal residual exceeds tolerance: {corrected_residual}")
            if surface == "M" and not np.isclose(original_residual, 4.180381107943276e-07, rtol=1e-9, atol=1e-15):
                raise RuntimeError(f"v04 M raw-scaler mismatch does not reproduce: {original_residual}")
            results[surface] = {
                "v04_probe_state_sha256": EXPECTED[f"{surface}_probe_state_sha256"],
                "probe_state_exact_to_S01": True,
                "v04_float64_scaler_normal_residual": original_residual,
                "runtime_float32_scaler_normal_residual": corrected_residual,
                "corrected_S08_plane_pass": True,
            }

    report = {
        "audit_id": "FAS_S09_GEOMETRY_SEMANTICS_AUDIT_V06",
        "disposition": "RUNTIME_SCALER_PRECISION_CORRECTION_QUALIFIED",
        "v04_protocol_root_sha256": protocol["root_sha256"],
        "v04_protocol_seal_file_sha256": protocol_seal_hash,
        "v04_preflight_root_sha256": v04_preflight["root_sha256"],
        "v04_failure_sha256": failure_hash,
        "S08_parent_protocol_root_sha256": "9b640d39840a5beeca41d72e6e48e4af313deef34575a090eedf4502bf306b04",
        "S08_source_sha256": {
            "s08_common.py": EXPECTED["S08_common_sha256"],
            "s08_math.py": EXPECTED["S08_math_sha256"],
        },
        "formula_correction": {
            "geometry_scaler_semantics": "FP32 runtime scaler values promoted to FP64",
            "pair_margin_raw": "n dot h + beta",
            "beta": "delta_b - n dot mu",
            "pair_margin_centered": "n dot (h-mu) + delta_b",
            "delta_b": "b_a - b_b",
            "normal_tolerance": GEOMETRY_TOLERANCE,
        },
        "surfaces": results,
        "model_loaded": False,
        "features_extracted": False,
        "probes_fitted": False,
        "FAS00_access": False,
    }
    write_json(RUN_ROOT / "geometry-semantics-audit-v06.json", report)
    print("geometry_semantics_audit_v06=PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
