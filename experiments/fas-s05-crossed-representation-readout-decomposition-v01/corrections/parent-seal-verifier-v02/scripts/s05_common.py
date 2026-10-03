from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\fas-s05-crossed-representation-readout-decomposition-v02")
CONTRACT_PATH = PROJECT / "contracts" / "analysis-contract-v01.json"
BINDING_PATH = PROJECT / "contracts" / "parent-binding-v01.json"
AUTHORIZATION_PATH = PROJECT / "contracts" / "authorization-packet-v01.json"
PROTOCOL_SEAL = PROJECT / "corrections" / "parent-seal-verifier-v02" / "seals" / "protocol-seal-v02.json"

FAS00_RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
FAS00_EVENTS = FAS00_RUN / "phase1-v03" / "corpus" / "qualification-events-v03.jsonl"
FAS00_FEATURES = FAS00_RUN / "phase2a-v01" / "feature-cache-v01" / "features-v01.f32le"
FAS00_PHASE2_SEAL = FAS00_RUN / "phase2a-v01" / "phase2a-v01-cache-seal.json"
FAS00_MEAN_PROBE = FAS00_RUN / "phase3-v02" / "results-v01" / "probe-artifacts" / "HELDOUT_TERM_EXACT_TARGET.npz"
FAS00_PHASE3_SEAL = FAS00_RUN / "phase3-v02" / "results-v01" / "phase3-result-seal-v01.json"

S02_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s02-original-corpus-readout-surface-attribution-v01")
S02_RUN = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01")
S02_CONSTRUCTION_SEAL = S02_PROJECT / "seals" / "construction-seal-v01.json"
S02_RESULT_DIR = S02_RUN / "s02-2-readout-attribution-v01" / "correction-v05"
S02_RESULT_SEAL = S02_RESULT_DIR / "seals" / "result-tree-seal-v01.json"
S02_FINAL_CACHE = S02_RUN / "s02-1-final-position-v02" / "feature-cache-v01"
S02_FINAL_CACHE_SEAL = S02_FINAL_CACHE / "feature-cache-seal-v01.json"
S02_FINAL_FEATURES = S02_FINAL_CACHE / "final-position-v01.f32le"
S02_FINAL_PROBE = S02_RESULT_DIR / "results-v01" / "final-position-probe-v01.npz"
S02_MEAN_PREDICTIONS = S02_RESULT_DIR / "historical-reproduction-v01" / "mean-full-predictions-v01.jsonl"
S02_FINAL_PREDICTIONS = S02_RESULT_DIR / "results-v01" / "final-position-predictions-v01.jsonl"
S02_METRICS = S02_RESULT_DIR / "results-v01" / "readout-metrics-v01.json"

S01_RUN = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_2_CACHE = S01_RUN / "s01-2-feature-geometry-v01" / "feature-cache-v01"
S01_3_RUN = S01_RUN / "s01-3-linear-accessibility-v01"
S01_TEST_EVENTS = S01_3_RUN / "metadata" / "test-events-v01.jsonl"
S01_RESULT_SEAL = S01_3_RUN / "seals" / "result-tree-seal-v01.json"
S04_RUN = Path(r"D:\codex-runs\fas-s04-controlled-factor-to-decision-transfer-geometry-v01")
S04_SEAL = S04_RUN / "result-tree-seal-v01.json"
S04_ELIGIBILITY = S04_RUN / "design-eligibility-v01.json"

FEATURE_ROWS = 65_536
FAS_EVENTS = 32_768
S01_FEATURE_ROWS = 106_496
S01_TEST_ROWS = 21_272
HIDDEN = 2048
S01_SPLIT_PREFIX = "FASS01-S01-3-GROUPSPLIT-V01|"
CELL_ORDER = ("MM", "FM", "MF", "FF")
CELL_DESCRIPTION = {
    "MM": ("mean_full", "mean_full"),
    "FM": ("final_position", "mean_full"),
    "MF": ("mean_full", "final_position"),
    "FF": ("final_position", "final_position"),
}
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))
CLASS_NAMES = {
    "FAS00_ORIGINAL": ["safe", "risky", "idle"],
    "S01_CONTROLLED": ["zavik", "nurex", "pavom"],
}

INPUT_HASHES = {
    "fas00_events": "9fdd7ce9e49b86ac9acb3da035429c616865f527123bd0ac7c312b1b912439ca",
    "fas00_features": "6205b7d7a224b798b387886b43ec27103b7f091dccd9b623847cb7a52b0c8c2",
    "fas00_mean_probe": "be7c4fa016f1ad5887a8bf087a395a6ca02377d706be291a5ad1b6fbcc9cabbb",
    "s02_final_features": "e4ef40343b10761236abdd2e77bb06aff69edb1ffe91a9344cf029a09790e3ba",
    "s02_final_probe": "928e8aca604efb5c09c733ed23e94228ea24336cb417ff190103638d269871cc",
    "s02_mean_predictions": "0c5c0b45bac09b3d25fb4b7634b4af880531d4de2ad95bf66cdff77b1f73fbd4",
    "s02_final_predictions": "7bd03915d41e1dd8744caa4dbee5d6136860c92dfb115e261487aa23c720c868",
    "s01_test_events": "b8a9e4dbeda07d98519cb3fe3508a839d17652494f5a3e0f7b0c82020fdc3498",
    "s01_v0_features": "9cc840390abd2c9d186f33b6a62948b55d4cdd15d52a4cfe03bd32775a2fe76c",
    "s01_v1_features": "095366563e0ef08a38192c325c93a000614cbdbd3a467e2e8c5c92e14acd1409",
    "s01_v0_probe": "1b3db11aa1fe691a98b40b0b9001c3f0125d1acd47f7c069ef53fd487a2d46e4",
    "s01_v1_probe": "2cbbd450468ae7ebbe073ca9badaf229dcf9d3b55ff80ed102ccf9eb7e942641",
    "s01_v0_probabilities": "d94ff21e4f3e2377c26cede424775bf8ef3b6ac019e3902347b7f1b6b2c93e2f",
    "s01_v1_probabilities": "cc1451fdd4823cc6de139375785af90b087793ce309ec5ec558bcf30593b3b03",
}


class FailClosed(RuntimeError):
    pass


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
        raise FailClosed(f"Refusing to overwrite existing S05 output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite existing S05 output: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
            stream.write("\n")


def canonical_root(rows: list[dict[str, Any]], path_key: str = "path", hash_key: str = "sha256",
                   *, mode: str = "path_sha_casefold") -> str:
    if mode in {"path_sha_casefold", "path_sha_utf8"}:
        key = (lambda row: row[path_key].casefold()) if mode == "path_sha_casefold" else (lambda row: row[path_key].encode("utf-8"))
        body = "".join(f"{row[path_key]} {row[hash_key]}\n" for row in sorted(rows, key=key))
    elif mode == "path_bytes_sha":
        ordered = sorted(rows, key=lambda row: row[path_key])
        body = "".join(f"{row[path_key]}\t{row['bytes']}\t{row[hash_key]}\n" for row in ordered)
    else:
        raise FailClosed(f"Unsupported parent seal canonicalization: {mode}")
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as stream:
        for index, line in enumerate(stream):
            if not line.strip():
                continue
            try:
                yield index, json.loads(line)
            except json.JSONDecodeError as exc:
                raise FailClosed(f"Malformed JSONL at {path}:{index + 1}: {exc}") from exc


def test_bucket(quartet_id: str) -> int:
    digest = hashlib.sha256((S01_SPLIT_PREFIX + quartet_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % 5


def verify_entry_list(root_dir: Path, rows: list[dict[str, Any]], expected_root: str, *, with_bytes: bool,
                      canonicalization: str = "path_sha_casefold") -> None:
    observed = []
    for row in rows:
        path = root_dir / Path(row["path"])
        if not path.is_file():
            raise FailClosed(f"Missing sealed parent artifact: {path}")
        actual_hash = sha_file(path)
        if actual_hash != row["sha256"] or (with_bytes and path.stat().st_size != row["bytes"]):
            raise FailClosed(f"Sealed parent artifact identity mismatch: {path}")
        observed.append({"path": row["path"], "sha256": actual_hash, "bytes": path.stat().st_size})
    if canonical_root(observed, mode=canonicalization) != expected_root:
        raise FailClosed("Parent seal tree root does not reproduce")


def verify_protocol_bundle() -> dict[str, Any]:
    seal = read_json(PROTOCOL_SEAL)
    if seal.get("seal_id") != "FAS_S05_PROTOCOL_SEAL_V02" or not seal.get("files"):
        raise FailClosed("S05 v02 protocol seal missing or malformed")
    verify_entry_list(PROJECT, seal["files"], seal["root_sha256"], with_bytes=True,
                      canonicalization="path_sha_casefold")
    return seal


def verify_parents(deep: bool = True) -> dict[str, Any]:
    binding = read_json(BINDING_PATH)
    authorization = read_json(AUTHORIZATION_PATH)
    contract = read_json(CONTRACT_PATH)
    if (authorization.get("status") != "AUTHORIZED_BY_USER_IN_CURRENT_TASK" or
            authorization.get("model_contact") is not False or
            authorization.get("probe_fitting") is not False or
            authorization.get("adaptive_mechanisms") is not False or
            contract.get("authority", {}).get("model_contact") is not False):
        raise FailClosed("S05 authorization or analysis boundary differs")

    # Verify the root seals first, then the precise files used by the replay.
    p2 = read_json(FAS00_PHASE2_SEAL)
    p3 = read_json(FAS00_PHASE3_SEAL)
    s02_construct = read_json(S02_CONSTRUCTION_SEAL)
    s02_final_cache = read_json(S02_FINAL_CACHE_SEAL)
    s02_result = read_json(S02_RESULT_SEAL)
    s01_result = read_json(S01_RESULT_SEAL)
    s04_result = read_json(S04_SEAL)

    if (p2.get("root_sha256") != binding["fas00_phase2a"]["root_sha256"] or
            sha_file(FAS00_PHASE2_SEAL) != binding["fas00_phase2a"]["seal_sha256"] or
            p3.get("root_sha256") != binding["fas00_phase3"]["root_sha256"] or
            sha_file(FAS00_PHASE3_SEAL) != binding["fas00_phase3"]["seal_sha256"] or
            s02_construct.get("root_sha256") != binding["s02"]["construction_root_sha256"] or
            sha_file(S02_CONSTRUCTION_SEAL) != "ef0d0c269eff60a37aa6bdfa23dafa6179d64a6d01f0b75a02bc3b0fca19aaee" or
            s02_final_cache.get("root_sha256") != binding["s02"]["s02_1_cache_root_sha256"] or
            sha_file(S02_FINAL_CACHE_SEAL) != "30f7484150861d386eb8e67acda5211ac1ed67c23fea43d493468b4c74dda109" or
            s02_result.get("root_sha256") != binding["s02"]["s02_2_result_root_sha256"] or
            s02_result.get("S02_RESULT_READY") is not True or
            s01_result.get("root_sha256") != binding["s01"]["s01_3_result_root_sha256"] or
            s04_result.get("root_sha256") != binding["s04_result_root_sha256"] or
            s04_result.get("S04_MARGIN_ANALYSIS_COMPLETE") is not True or
            s04_result.get("S04_MODEL_CONTACT") is not False):
        raise FailClosed("A sealed FAS-00/S01/S02/S04 parent root or disposition differs")

    if deep:
        if s02_construct.get("canonicalization") != "SHA-256 of UTF-8 '<relative_posix_path> <file_sha256>\\n' rows sorted by UTF-8 path bytes.":
            raise FailClosed("S02 construction seal canonicalization declaration differs")
        if s01_result.get("algorithm") != "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; result seal and disposition excluded":
            raise FailClosed("S01 result seal algorithm declaration differs")
        verify_entry_list(FAS00_RUN / "phase2a-v01", p2["files"], p2["root_sha256"], with_bytes=False,
                          canonicalization="path_sha_casefold")
        verify_entry_list(FAS00_PHASE3_SEAL.parent, p3["files"], p3["root_sha256"], with_bytes=False,
                          canonicalization="path_sha_casefold")
        verify_entry_list(S02_PROJECT, s02_construct["files"], s02_construct["root_sha256"], with_bytes=False,
                          canonicalization="path_sha_utf8")
        verify_entry_list(S02_FINAL_CACHE, s02_final_cache["files"], s02_final_cache["root_sha256"], with_bytes=False,
                          canonicalization="path_sha_casefold")
        verify_entry_list(S02_RESULT_DIR, s02_result["files"], s02_result["root_sha256"], with_bytes=False,
                          canonicalization="path_sha_casefold")
        verify_entry_list(S01_RESULT_SEAL.parent, s01_result["entries"], s01_result["root_sha256"], with_bytes=True,
                          canonicalization="path_bytes_sha")
        verify_entry_list(S04_RUN, s04_result["entries"], s04_result["root_sha256"], with_bytes=True,
                          canonicalization="path_sha_casefold")

    for key, path in {
        "fas00_events": FAS00_EVENTS,
        "fas00_features": FAS00_FEATURES,
        "fas00_mean_probe": FAS00_MEAN_PROBE,
        "s02_final_features": S02_FINAL_FEATURES,
        "s02_final_probe": S02_FINAL_PROBE,
        "s02_mean_predictions": S02_MEAN_PREDICTIONS,
        "s02_final_predictions": S02_FINAL_PREDICTIONS,
        "s01_test_events": S01_TEST_EVENTS,
        "s01_v0_features": S01_2_CACHE / "V0_MEAN_FULL.f32le",
        "s01_v1_features": S01_2_CACHE / "V1_FINAL_POSITION.f32le",
    }.items():
        if not deep and key in {"fas00_features", "s02_final_features", "s01_v0_features", "s01_v1_features"}:
            continue
        if sha_file(path) != INPUT_HASHES[key]:
            raise FailClosed(f"S05 source artifact hash mismatch: {key}")

    s01_entries = {row["path"]: row["sha256"] for row in s01_result["entries"]}
    s04_entries = {row["path"]: row["sha256"] for row in s04_result["entries"]}
    for view, short in (("V0_MEAN_FULL", "V0"), ("V1_FINAL_POSITION", "V1")):
        base = f"probes/{view}/EXACT_TARGET"
        if (s01_entries.get(f"{base}/probe-state-v01.npz") != binding["s01"][f"{short.lower()}_probe_sha256"] or
                s01_entries.get(f"predictions/{view}/EXACT_TARGET/probabilities.npy") != binding["s01"][f"{short.lower()}_probability_sha256"]):
            raise FailClosed(f"S01 parent seal does not bind {view} readout inputs")
    if (s04_entries.get("quartet-margin-ledger-v01.jsonl") is None or
            s04_entries.get("design-eligibility-v01.json") is None):
        raise FailClosed("S04 seal lacks frozen selected population artifacts")

    return {
        "fas00_phase1_root_sha256": binding["fas00_phase1_events"]["root_sha256"],
        "fas00_phase2a_root_sha256": p2["root_sha256"],
        "fas00_phase3_root_sha256": p3["root_sha256"],
        "s02_construction_root_sha256": s02_construct["root_sha256"],
        "s02_1_cache_root_sha256": s02_final_cache["root_sha256"],
        "s02_2_result_root_sha256": s02_result["root_sha256"],
        "s01_3_result_root_sha256": s01_result["root_sha256"],
        "s04_result_root_sha256": s04_result["root_sha256"],
        "input_hashes": dict(INPUT_HASHES),
        "deep_parent_rehash": deep,
        "model_contact": False,
        "probe_fitting": False,
    }
