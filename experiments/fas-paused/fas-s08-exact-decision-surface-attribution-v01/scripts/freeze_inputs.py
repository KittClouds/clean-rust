from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from s08_common import (
    FAS00_MEAN_FEATURES, FAS00_MEAN_PROBE, PROJECT, RUN, S01_ACCESS_RUN, S01_ACCESS_SEAL,
    S01_CACHE, S01_CACHE_RESULT_SEAL, S01_CACHE_SEAL, S01_FEATURE_ROWS, S01_FINAL_FEATURES,
    S01_FINAL_PROBE, S01_MEAN_FEATURES, S01_MEAN_PROBE, S01_META, S02_FINAL_FEATURES,
    S02_FINAL_PROBE, S02_RUN, S05_POPULATIONS, S06_BINDING, S06_LEDGER, S06_PROTOCOL_SEAL,
    S06_RECEIPT, S06_RESULT_SEAL, S06_RUN, S06_SUMMARY, S07_GATE_ROOT, S07_GATE_SEAL,
    EXPECTED_ROOTS, FailClosed, canonical_root, read_json, sha_file, verify_entries, write_json,
)


S01_ACCESS_BINDING = S01_ACCESS_RUN / "inputs" / "contracts" / "input-binding-v01.json"
S01_ACCESS_META = S01_ACCESS_RUN / "metadata" / "event-metadata-v01.npz"
FAS00_CACHE_SEAL = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00\phase2a-v01\phase2a-v01-cache-seal.json")
S02_FEATURE_SEAL = S02_RUN / "s02-1-final-position-v02" / "seals" / "s02-1-seal-v01.json"
S07_GATE = S07_GATE_ROOT / "reconstruction-gate-v01.json"


def _verify_root(seal_path: Path, root: Path, expected: str, *, with_bytes: bool, casefold: bool) -> dict[str, Any]:
    seal = read_json(seal_path)
    if seal.get("root_sha256") != expected:
        raise FailClosed(f"Unexpected parent root in {seal_path}")
    entries = seal.get("entries", seal.get("files", []))
    actual = canonical_root(entries, with_bytes=with_bytes, casefold=casefold)
    if actual != expected:
        raise FailClosed(f"Parent seal metadata root does not reconstruct: {seal_path}")
    verify_entries(root, entries, with_bytes=with_bytes, casefold=casefold)
    return seal


def main() -> None:
    s06_result = _verify_root(S06_RESULT_SEAL, S06_RUN, EXPECTED_ROOTS["s06_result"], with_bytes=False, casefold=True)
    if s06_result.get("status") != "SEALED" or s06_result.get("S06_RESULT_READY") is not True:
        raise FailClosed("S06 result disposition is not complete/sealed")
    s06_protocol = _verify_root(S06_PROTOCOL_SEAL, PROJECT.parent / "fas-s06-representation-scaler-probe-compatibility-cube-v01", EXPECTED_ROOTS["s06_protocol"], with_bytes=False, casefold=True)
    if s06_protocol.get("status") != "SEALED":
        raise FailClosed("S06 corrected protocol is not sealed")

    s06_binding = read_json(S06_BINDING)
    s06_receipt = read_json(S06_RECEIPT)
    if (s06_receipt.get("status") != "COMPLETE" or
            s06_receipt.get("protocol_root_sha256") != EXPECTED_ROOTS["s06_protocol"] or
            s06_receipt.get("model_contact") is not False or
            s06_receipt.get("feature_extraction") is not False or
            s06_receipt.get("probe_fitting") is not False or
            s06_receipt.get("parents", {}).get("direct_input_hashes") != {
                name: record["sha256"] for name, record in s06_binding["inputs"].items()
            }):
        raise FailClosed("S06 execution receipt and corrected input binding disagree")
    if s06_binding.get("s05", {}).get("result_root_sha256") != "6e5cb0586611aeb0b07dff7b8788b7b8bea749179bbe5a38ef98a8045e890466":
        raise FailClosed("S06 is not bound to the expected sealed S05 result")

    s01_cache_seal = read_json(S01_CACHE_SEAL)
    if (s01_cache_seal.get("root_sha256") != EXPECTED_ROOTS["s01_feature_cache"] or
            canonical_root(s01_cache_seal["entries"], with_bytes=True, casefold=False) != EXPECTED_ROOTS["s01_feature_cache"]):
        raise FailClosed("S01 feature-cache seal metadata does not match expected root")
    s01_cache_result = read_json(S01_CACHE_RESULT_SEAL)
    if (s01_cache_result.get("root_sha256") != "1fc3aeb432ecdbef21a35aea8fed5b0d59671681eb8eb8032533c9ce751a4384" or
            canonical_root(s01_cache_result["entries"], with_bytes=True, casefold=False) != s01_cache_result["root_sha256"]):
        raise FailClosed("S01-2 result seal metadata root mismatch")
    s01_access = _verify_root(S01_ACCESS_SEAL, S01_ACCESS_RUN, EXPECTED_ROOTS["s01_accessibility"], with_bytes=True, casefold=False)
    if s01_access.get("seal_id") != "FASS01_S01_3_LINEAR_ACCESSIBILITY_RESULT_SEAL_V01":
        raise FailClosed("Unexpected S01-3 result seal")
    s01_access_binding = read_json(S01_ACCESS_BINDING)
    if (s01_access_binding.get("parent_roots", {}).get("s01_2_corpus_sha256") != EXPECTED_ROOTS["s01_corpus"] or
            s01_access_binding.get("parent_roots", {}).get("feature_rows_sha256") != "a8ea72310c0926962a0783d90eb3ceda19ca0b334bd2c00aafdd226e8aaaa40b"):
        raise FailClosed("S01 event/feature-row identity does not match sealed S01 binding")

    s02_seal = read_json(S02_FEATURE_SEAL)
    fas00_seal = read_json(FAS00_CACHE_SEAL)
    if (s02_seal.get("root_sha256") != "baed3504533499880873db8f8bf16e37a0164844e657f9bda1397daaa0b4944b" or
            s02_seal.get("S02_FEATURE_CACHE_SEALED") is not True or
            fas00_seal.get("root_sha256") != "9af2c6c73a2f21608e8a2dc912d8838968eaebffb32b4b1ea0a18364e488d217" or
            fas00_seal.get("feature_cache_ready") is not True):
        raise FailClosed("FAS-00 or S02 feature parent disposition mismatch")

    s07_seal = read_json(S07_GATE_SEAL)
    s07_gate = read_json(S07_GATE)
    if (s07_seal.get("root_sha256") != EXPECTED_ROOTS["s07_gate"] or
            s07_gate.get("status") != "SAE_NOT_FAITHFUL_FOR_COMPATIBILITY_ANALYSIS" or
            s07_gate.get("S07_FEATURE_ANALYSIS_AUTHORIZED_BY_GATE") is not False):
        raise FailClosed("S07 closure disposition does not match the declared branch state")

    direct_expected = s06_receipt["parents"]["direct_input_hashes"]
    inputs = {
        "s06_result_seal": S06_RESULT_SEAL,
        "s06_execution_receipt": S06_RECEIPT,
        "s06_corrected_protocol_seal": S06_PROTOCOL_SEAL,
        "s06_corrected_parent_binding": S06_BINDING,
        "s06_ledger": S06_LEDGER,
        "s06_summary": S06_SUMMARY,
        "s05_event_populations": S05_POPULATIONS,
        "s01_feature_cache_seal": S01_CACHE_SEAL,
        "s01_feature_cache_result_seal": S01_CACHE_RESULT_SEAL,
        "s01_accessibility_result_seal": S01_ACCESS_SEAL,
        "s01_event_metadata": S01_ACCESS_META,
        "s01_feature_rows": S01_FEATURE_ROWS,
        "s01_mean_features": S01_MEAN_FEATURES,
        "s01_final_features": S01_FINAL_FEATURES,
        "s01_mean_readout": S01_MEAN_PROBE,
        "s01_final_readout": S01_FINAL_PROBE,
        "fas00_cache_seal": FAS00_CACHE_SEAL,
        "fas00_mean_features": FAS00_MEAN_FEATURES,
        "fas00_mean_readout": Path(s06_binding["inputs"]["fas00_mean_readout"]["path"]),
        "s02_feature_seal": S02_FEATURE_SEAL,
        "s02_final_features": S02_FINAL_FEATURES,
        "s02_final_readout": S02_FINAL_PROBE,
        "s07_gate_seal": S07_GATE_SEAL,
        "s07_gate_disposition": S07_GATE,
    }
    expected_direct = {
        "s01_mean_features": direct_expected["s01_mean_features"],
        "s01_final_features": direct_expected["s01_final_features"],
        "s01_mean_readout": direct_expected["s01_mean_readout"],
        "s01_final_readout": direct_expected["s01_final_readout"],
        "fas00_mean_features": direct_expected["fas00_mean_features"],
        "fas00_mean_readout": direct_expected["fas00_mean_readout"],
        "s02_final_features": direct_expected["s02_final_features"],
        "s02_final_readout": direct_expected["s02_final_readout"],
    }
    declared_files = []
    for name, path in inputs.items():
        if not path.is_file():
            raise FailClosed(f"Missing bound S08 input {name}: {path}")
        digest = sha_file(path)
        if name in expected_direct and digest != expected_direct[name]:
            raise FailClosed(f"Direct input digest differs from S06 binding: {name}")
        if name == "s05_event_populations" and digest != s06_receipt["parents"]["s05_event_populations_sha256"]:
            raise FailClosed("S05 event population digest differs from S06 receipt")
        if name == "s01_event_metadata":
            expected_meta = next(e["sha256"] for e in s01_access["entries"] if e["path"] == "metadata/event-metadata-v01.npz")
            if digest != expected_meta:
                raise FailClosed("S01 event metadata digest differs from S01 result seal")
        if name == "s01_feature_rows" and digest != s01_access_binding["parent_roots"]["feature_rows_sha256"]:
            raise FailClosed("S01 feature-row manifest digest differs from its parent binding")
        declared_files.append({"name": name, "path": str(path), "bytes": path.stat().st_size, "sha256": digest})

    binding = {
        "binding_id": "FAS_S08_PARENT_BINDING_V01",
        "status": "SEALED_INPUTS_VERIFIED_BEFORE_S08_ANALYSIS",
        "expected_roots": EXPECTED_ROOTS,
        "s06_root_sha256": s06_result["root_sha256"],
        "s06_protocol_root_sha256": s06_protocol["root_sha256"],
        "s01_feature_cache_root_sha256": s01_cache_seal["root_sha256"],
        "s01_2_result_root_sha256": s01_cache_result["root_sha256"],
        "s01_3_result_root_sha256": s01_access["root_sha256"],
        "s01_corpus_sha256": EXPECTED_ROOTS["s01_corpus"],
        "s06_s01_rows": 19732,
        "s06_fas00_rows": 512,
        "s01_feature_rows": 106496,
        "s01_train_rows": 85224,
        "s06_direct_input_hashes": direct_expected,
        "files": declared_files,
        "fas00_sensor_pass": False,
        "s07_disposition": s07_gate["status"],
        "parent_modified": False,
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
    }
    output = PROJECT / "contracts" / "parent-binding-v01.json"
    write_json(output, binding)
    print(f"S08_PARENT_BINDING_READY files={len(declared_files)} s06={binding['s06_root_sha256']} s01={binding['s01_3_result_root_sha256']}")


if __name__ == "__main__":
    main()
