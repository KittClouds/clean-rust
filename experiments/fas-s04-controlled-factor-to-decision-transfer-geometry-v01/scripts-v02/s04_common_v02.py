from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[1]
RUN = Path(r"D:\codex-runs\fas-s04-controlled-factor-to-decision-transfer-geometry-v01")
CONTRACT = PROJECT / "contracts" / "analysis-contract-v01.json"
BINDING = PROJECT / "contracts" / "parent-binding-v01.json"
AUTHORIZATION = PROJECT / "contracts" / "authorization-packet-v01.json"
PROTOCOL_SEAL = PROJECT / "seals" / "protocol-seal-v01.json"
RUNNER_CORRECTION_SEAL = PROJECT / "seals" / "runner-correction-seal-v02.json"

S01_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s01-frozen-sensor-transfer-cartography")
S01_RUN = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_2_RUN = S01_RUN / "s01-2-feature-geometry-v01"
S01_2_CORPUS = S01_RUN / "s01-2-v01-sealed" / "corpus" / "counterfactual-quartets-v01.jsonl"
S01_2_CACHE = S01_2_RUN / "feature-cache-v01"
S01_2_RESULT_SEAL = S01_2_RUN / "seals" / "result-tree-seal-v01.json"
S01_2_CACHE_SEAL = S01_2_RUN / "seals" / "feature-cache-seal-v01.json"
S01_2_FEATURE_ROWS = S01_2_CACHE / "feature-rows-v01.jsonl"
S01_3_RUN = S01_RUN / "s01-3-linear-accessibility-v01"
S01_3_RESULT_SEAL = S01_3_RUN / "seals" / "result-tree-seal-v01.json"
S01_3_DISPOSITION = S01_3_RUN / "seals" / "phase-disposition-v01.json"
S01_3_TEST_EVENTS = S01_3_RUN / "metadata" / "test-events-v01.jsonl"
S01_3_CONTRACT = S01_PROJECT / "s01-3-linear-accessibility-v01" / "contracts" / "linear-accessibility-contract-v01.json"

VIEW_INFO = {
    "V0_MEAN_FULL": {
        "tensor": S01_2_CACHE / "V0_MEAN_FULL.f32le",
        "probe": S01_3_RUN / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz",
        "probe_meta": S01_3_RUN / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-metadata-v01.json",
        "probabilities": S01_3_RUN / "predictions" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probabilities.npy",
        "dimension": 2048,
    },
    "V1_FINAL_POSITION": {
        "tensor": S01_2_CACHE / "V1_FINAL_POSITION.f32le",
        "probe": S01_3_RUN / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz",
        "probe_meta": S01_3_RUN / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-metadata-v01.json",
        "probabilities": S01_3_RUN / "predictions" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probabilities.npy",
        "dimension": 2048,
    },
}
EVENTS = 106_496
PROBE_SPLIT_PREFIX = "FASS01-S01-3-GROUPSPLIT-V01|"
CLASS_NAMES = {0: "zavik", 1: "nurex", 2: "pavom"}
VARIANT_ORDER = ("A", "C", "E", "P")
FACTOR_ORDER = ("C", "E", "P")
STATE_PAIRS = ((0, 1), (0, 2), (1, 2))


class FailClosed(RuntimeError):
    pass


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite existing S04 artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite existing S04 artifact: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
            stream.write("\n")


def canonical_root(rows: list[dict[str, Any]]) -> str:
    body = "".join(f"{row['path']} {row['sha256']}\n" for row in sorted(rows, key=lambda x: x["path"].casefold()))
    return sha_bytes(body.encode("utf-8"))


def reject_nonstandard_json_constant(value: str) -> None:
    raise FailClosed(f"Nonstandard JSON numeric constant: {value}")


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line, parse_constant=reject_nonstandard_json_constant)
            except (json.JSONDecodeError, FailClosed) as exc:
                raise FailClosed(f"Malformed or nonfinite JSONL row at {path}:{line_number}: {exc}") from exc


def test_bucket(quartet_id: str) -> int:
    digest = hashlib.sha256((PROBE_SPLIT_PREFIX + quartet_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 5


def verify_protocol_bundle() -> dict[str, Any]:
    seal = read_json(PROTOCOL_SEAL)
    rows = seal.get("files", [])
    if seal.get("seal_id") != "FAS_S04_PROTOCOL_SEAL_V01" or not rows:
        raise FailClosed("S04 protocol seal is absent or malformed")
    observed = []
    for row in rows:
        path = PROJECT / Path(row["path"])
        if not path.is_file() or sha_file(path) != row["sha256"]:
            raise FailClosed(f"S04 protocol bundle member changed: {row['path']}")
        observed.append({"path": row["path"], "sha256": row["sha256"]})
    if canonical_root(observed) != seal.get("root_sha256"):
        raise FailClosed("S04 protocol root does not reproduce")
    correction = read_json(RUNNER_CORRECTION_SEAL)
    correction_rows = correction.get("files", [])
    if (correction.get("seal_id") != "FAS_S04_RUNNER_CORRECTION_SEAL_V02" or
            correction.get("parent_protocol_root_sha256") != seal["root_sha256"] or
            correction.get("status") != "PASS" or not correction_rows):
        raise FailClosed("S04 v02 runner-correction seal is absent or malformed")
    observed_correction = []
    for row in correction_rows:
        path = PROJECT / Path(row["path"])
        if not path.is_file() or sha_file(path) != row["sha256"]:
            raise FailClosed(f"S04 runner-correction bundle member changed: {row['path']}")
        observed_correction.append({"path": row["path"], "sha256": row["sha256"]})
    if canonical_root(observed_correction) != correction.get("root_sha256"):
        raise FailClosed("S04 v02 runner-correction root does not reproduce")
    return {**seal, "runner_correction_root_sha256": correction["root_sha256"]}


def _assert_seal_entry(seal: dict[str, Any], relative: str, path: Path, expected_sha: str) -> None:
    matches = [row for row in seal.get("entries", []) if row.get("path") == relative]
    if len(matches) != 1:
        raise FailClosed(f"Parent seal has no unique entry for {relative}")
    row = matches[0]
    if row.get("sha256") != expected_sha or row.get("bytes") != path.stat().st_size:
        raise FailClosed(f"Parent seal identity differs for {relative}")
    if sha_file(path) != expected_sha:
        raise FailClosed(f"Parent artifact hash mismatch for {relative}")


def verify_parents() -> dict[str, Any]:
    contract = read_json(CONTRACT)
    binding = read_json(BINDING)
    authorization = read_json(AUTHORIZATION)
    p = contract["parents"]
    if (authorization.get("status") != "AUTHORIZED_BY_USER_IN_CURRENT_TASK" or
            authorization.get("model_contact") is not False or
            authorization.get("probe_fitting") is not False or
            authorization.get("adaptive_mechanisms") is not False):
        raise FailClosed("S04 authorization boundary is inconsistent")

    s02 = read_json(S01_2_RESULT_SEAL)
    cseal = read_json(S01_2_CACHE_SEAL)
    s03 = read_json(S01_3_RESULT_SEAL)
    disposition = read_json(S01_3_DISPOSITION)
    if (s02.get("root_sha256") != p["s01_2_result_root_sha256"] or
            s02.get("feature_cache_root_sha256") != p["s01_2_feature_cache_root_sha256"] or
            s02.get("parent_roots", {}).get("S01_2") != p["s01_2_construction_root_sha256"] or
            s02.get("parent_roots", {}).get("S01_2C") != p["s01_2c_alignment_root_sha256"] or
            cseal.get("root_sha256") != p["s01_2_feature_cache_root_sha256"] or
            s03.get("root_sha256") != p["s01_3_result_root_sha256"] or
            s03.get("feature_cache_root_sha256") != p["s01_2_feature_cache_root_sha256"] or
            disposition.get("S01_3_COMPLETE") is not True or
            disposition.get("S01_3_LINEAR_ACCESSIBILITY_DIAGNOSTIC") != "COMPLETE" or
            disposition.get("S01_3_LFM_LOADED") is not False or
            disposition.get("S01_3_FEATURE_REEXTRACTION") is not False or
            disposition.get("S01_ADAPTIVE_MECHANISMS_AUTHORIZED") is not False):
        raise FailClosed("S01 parent seal or terminal disposition differs from the S04 binding")

    if sha_file(S01_2_CORPUS) != p["s01_2_corpus_sha256"]:
        raise FailClosed("S01-2 corpus hash mismatch")
    if sha_file(S01_3_CONTRACT) != p["s01_3_contract_sha256"]:
        raise FailClosed("S01-3 probe contract hash mismatch")

    feature_entries = {row["path"]: row for row in cseal.get("entries", [])}
    for view, short, rel in (
        ("V0_MEAN_FULL", "V0_MEAN_FULL_sha256", "feature-cache-v01/V0_MEAN_FULL.f32le"),
        ("V1_FINAL_POSITION", "V1_FINAL_POSITION_sha256", "feature-cache-v01/V1_FINAL_POSITION.f32le"),
    ):
        expected = binding["s01_2"][short]
        if feature_entries.get(rel, {}).get("sha256") != expected:
            raise FailClosed(f"S01-2 feature-cache seal does not bind {view}")
        tensor = VIEW_INFO[view]["tensor"]
        if tensor.stat().st_size != EVENTS * VIEW_INFO[view]["dimension"] * 4 or sha_file(tensor) != expected:
            raise FailClosed(f"S01-2 feature tensor identity mismatch for {view}")
    if feature_entries.get("feature-cache-v01/feature-rows-v01.jsonl", {}).get("sha256") != binding["s01_2"]["feature_rows_sha256"]:
        raise FailClosed("S01-2 cache seal does not bind the feature-row manifest")
    if sha_file(S01_2_FEATURE_ROWS) != binding["s01_2"]["feature_rows_sha256"]:
        raise FailClosed("S01-2 feature-row manifest hash mismatch")

    result_entries = {row["path"]: row for row in s03.get("entries", [])}
    direct_s03 = {
        "metadata/test-events-v01.jsonl": (S01_3_TEST_EVENTS, binding["s01_3"]["test_events_sha256"]),
    }
    for view in VIEW_INFO:
        base = Path("probes") / view / "EXACT_TARGET"
        base_relative = base.as_posix()
        direct_s03[f"{base_relative}/probe-state-v01.npz"] = (VIEW_INFO[view]["probe"], binding["s01_3"][f"EXACT_TARGET_{view[:2]}_probe_state_sha256"])
        direct_s03[f"{base_relative}/probe-metadata-v01.json"] = (VIEW_INFO[view]["probe_meta"], None)
        direct_s03[f"predictions/{view}/EXACT_TARGET/probabilities.npy"] = (VIEW_INFO[view]["probabilities"], binding["s01_3"][f"EXACT_TARGET_{view[:2]}_probabilities_sha256"])
    for relative, (path, expected) in direct_s03.items():
        row = result_entries.get(relative)
        if row is None:
            raise FailClosed(f"S01-3 result tree lacks {relative}")
        expected = expected or row["sha256"]
        if row["sha256"] != expected or path.stat().st_size != row["bytes"] or sha_file(path) != expected:
            raise FailClosed(f"S01-3 parent artifact identity mismatch for {relative}")
    for view in VIEW_INFO:
        metadata = read_json(VIEW_INFO[view]["probe_meta"])
        if (metadata.get("task") != "EXACT_TARGET" or
                metadata.get("class_ids") != [0, 1, 2] or
                metadata.get("prediction_shape") != [21_272, 3] or
                metadata.get("optimizer_iteration_limit_reached") is not True or
                metadata.get("optimizer_iterations") != 300):
            raise FailClosed(f"S01-3 sealed exact-target probe metadata mismatch for {view}")

    contract_digest = sha_file(CONTRACT)
    binding_digest = sha_file(BINDING)
    return {
        "s01_2_construction_root_sha256": p["s01_2_construction_root_sha256"],
        "s01_2_alignment_root_sha256": p["s01_2c_alignment_root_sha256"],
        "s01_2_corpus_sha256": p["s01_2_corpus_sha256"],
        "s01_2_result_root_sha256": s02["root_sha256"],
        "s01_2_feature_cache_root_sha256": cseal["root_sha256"],
        "s01_3_result_root_sha256": s03["root_sha256"],
        "s01_3_contract_sha256": sha_file(S01_3_CONTRACT),
        "s01_3_test_events_sha256": sha_file(S01_3_TEST_EVENTS),
        "selected_feature_tensor_sha256": {
            "V0_MEAN_FULL": binding["s01_2"]["V0_MEAN_FULL_sha256"],
            "V1_FINAL_POSITION": binding["s01_2"]["V1_FINAL_POSITION_sha256"],
        },
        "exact_target_probe_state_sha256": {
            "V0_MEAN_FULL": binding["s01_3"]["EXACT_TARGET_V0_probe_state_sha256"],
            "V1_FINAL_POSITION": binding["s01_3"]["EXACT_TARGET_V1_probe_state_sha256"],
        },
        "exact_target_probabilities_sha256": {
            "V0_MEAN_FULL": binding["s01_3"]["EXACT_TARGET_V0_probabilities_sha256"],
            "V1_FINAL_POSITION": binding["s01_3"]["EXACT_TARGET_V1_probabilities_sha256"],
        },
        "analysis_contract_sha256": contract_digest,
        "parent_binding_sha256": binding_digest,
        "authorization_packet_sha256": sha_file(AUTHORIZATION),
        "model_contact": False,
        "probe_fitting": False,
    }
