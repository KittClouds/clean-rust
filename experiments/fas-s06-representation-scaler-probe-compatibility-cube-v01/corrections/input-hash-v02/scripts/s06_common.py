from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PROJECT = Path(__file__).resolve().parents[3]
RUN = Path(r"D:\codex-runs\fas-s06-representation-scaler-probe-compatibility-cube-v02")
CONTRACT = PROJECT / "contracts" / "analysis-contract-v01.json"
BINDING = PROJECT / "corrections" / "input-hash-v02" / "contracts" / "parent-binding-v02.json"
AUTHORIZATION = PROJECT / "contracts" / "authorization-packet-v01.json"
PROTOCOL_SEAL = PROJECT / "corrections" / "input-hash-v02" / "seals" / "protocol-seal-v02.json"

S05_RUN = Path(r"D:\codex-runs\fas-s05-crossed-representation-readout-decomposition-v07")
S05_PROJECT = Path(r"C:\code land\clean-rust\experiments\fas-s05-crossed-representation-readout-decomposition-v01")
S05_PROTOCOL_SEAL = S05_PROJECT / "corrections" / "s02-diagonal-binding-v07" / "seals" / "protocol-seal-v07.json"
S05_RESULT_SEAL = S05_RUN / "result-tree-seal-v01.json"
S05_POPULATIONS = S05_RUN / "event-populations-v01.json"
S05_LEDGER = S05_RUN / "crossed-replay-ledger-v01.jsonl"
S05_SUMMARY = S05_RUN / "crossed-summary-v01.json"
S05_TRANSITIONS = S05_RUN / "prediction-transitions-v01.json"
S05_RECEIPT = S05_RUN / "execution-receipt-v01.json"

FAS00_RUN = Path(r"D:\codex-runs\fas-frozen-adaptive-substrate-v00")
FAS00_MEAN_FEATURES = FAS00_RUN / "phase2a-v01" / "feature-cache-v01" / "features-v01.f32le"
S02_FINAL_FEATURES = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01\s02-1-final-position-v02\feature-cache-v01\final-position-v01.f32le")
FAS00_MEAN_PROBE = FAS00_RUN / "phase3-v02" / "results-v01" / "probe-artifacts" / "HELDOUT_TERM_EXACT_TARGET.npz"
S02_FINAL_PROBE = Path(r"D:\codex-runs\fas-s02-original-corpus-readout-surface-attribution-v01\s02-2-readout-attribution-v01\correction-v05\results-v01\final-position-probe-v01.npz")

S01_RUN = Path(r"D:\codex-runs\fas-s01-frozen-sensor-transfer-cartography")
S01_2_CACHE = S01_RUN / "s01-2-feature-geometry-v01" / "feature-cache-v01"
S01_MEAN_FEATURES = S01_2_CACHE / "V0_MEAN_FULL.f32le"
S01_FINAL_FEATURES = S01_2_CACHE / "V1_FINAL_POSITION.f32le"
S01_3_RUN = S01_RUN / "s01-3-linear-accessibility-v01"
S01_RESULT_SEAL = S01_3_RUN / "seals" / "result-tree-seal-v01.json"
S01_MEAN_PROBE = S01_3_RUN / "probes" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probe-state-v01.npz"
S01_FINAL_PROBE = S01_3_RUN / "probes" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probe-state-v01.npz"
S01_MEAN_PROBS = S01_3_RUN / "predictions" / "V0_MEAN_FULL" / "EXACT_TARGET" / "probabilities.npy"
S01_FINAL_PROBS = S01_3_RUN / "predictions" / "V1_FINAL_POSITION" / "EXACT_TARGET" / "probabilities.npy"

HIDDEN = 2048
FAS00_EVENTS = 32768
S01_FEATURE_ROWS = 106496
REPRESENTATIONS = ("M", "F")
SOURCES = ("M", "F")
CLASS_NAMES = {
    "FAS00_ORIGINAL": ["safe", "risky", "idle"],
    "S01_CONTROLLED": ["zavik", "nurex", "pavom"],
}
PAIR_ORDER = ((0, 1), (0, 2), (1, 2))
CELL_ORDER = tuple(
    f"R_{r}_C_{c}_D_{d}_W_{w}"
    for r in REPRESENTATIONS for c in SOURCES for d in SOURCES for w in SOURCES
)
CELL_INFO = {
    cell: {"representation": r, "center_source": c, "scale_source": d, "probe_source": w,
           "scaler_bundle": c if c == d else None}
    for cell, (r, c, d, w) in zip(CELL_ORDER,
        ((r, c, d, w) for r in REPRESENTATIONS for c in SOURCES for d in SOURCES for w in SOURCES))
}

DIRECT_INPUT_HASHES = {
    "fas00_mean_features": "6205b7d7a224b798b387886b43ec27103b37f091dccd9b623847cb7a52b0c8c2",
    "s02_final_features": "e4ef40343b10761236abdd2e77bb06aff69edb1ffe91a9344cf029a09790e3ba",
    "fas00_mean_readout": "be7c4fa016f1ad5887a8bf087a395a6ca02377d706be291a5ad1b6fbcc9cabbb",
    "s02_final_readout": "928e8aca604efb5c09c733ed23e94228ea24336cb417ff190103638d269871cc",
    "s01_mean_features": "9cc840390abd2c9d186f33b6a62948b55d4cdd15d52a4cfe03bd32775a2fe76c",
    "s01_final_features": "095366563e0ef08a38192c325c93a000614cbdbd3a467e2e8c5c92e14acd1409",
    "s01_mean_readout": "1b3db11aa1fe691a98b40b0b9001c3f0125d1acd47f7c069ef53fd487a2d46e4",
    "s01_final_readout": "2cbbd450468ae7ebbe073ca9badaf229dcf9d3b55ff80ed102ccf9eb7e942641",
    "s01_mean_probabilities": "d94ff21e4f3e2377c26cede424775bf8ef3b6ac019e3902347b7f1b6b2c93e2f",
    "s01_final_probabilities": "cc1451fdd4823cc6ce139375785af90b087793ce309ec5ec558bcf30593b3b03",
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
        raise FailClosed(f"Refusing to overwrite S06 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if path.exists():
        raise FailClosed(f"Refusing to overwrite S06 artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n", buffering=1024 * 1024) as stream:
        for row in rows:
            stream.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False))
            stream.write("\n")


def canonical_root(entries: list[dict[str, Any]], *, with_bytes: bool = False) -> str:
    ordered = sorted(entries, key=lambda item: item["path"].casefold())
    if with_bytes:
        text = "".join(f"{item['path']}\t{item['bytes']}\t{item['sha256']}\n" for item in ordered)
    else:
        text = "".join(f"{item['path']} {item['sha256']}\n" for item in ordered)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_entries(root: Path, entries: list[dict[str, Any]], *, with_bytes: bool = False) -> None:
    observed = []
    for entry in entries:
        path = root / Path(entry["path"])
        if not path.is_file():
            raise FailClosed(f"Missing sealed input: {path}")
        digest = sha_file(path)
        size = path.stat().st_size
        if digest != entry["sha256"] or (with_bytes and size != int(entry["bytes"])):
            raise FailClosed(f"Sealed input identity mismatch: {path}")
        observed.append({"path": entry["path"], "sha256": digest, "bytes": size})
    if canonical_root(observed, with_bytes=with_bytes) != canonical_root(entries, with_bytes=with_bytes):
        raise FailClosed("Input manifest reconstruction mismatch")


def verify_protocol() -> dict[str, Any]:
    seal = read_json(PROTOCOL_SEAL)
    if seal.get("seal_id") != "FAS_S06_PROTOCOL_SEAL_V02" or seal.get("status") != "SEALED":
        raise FailClosed("S06 v02 protocol seal missing or malformed")
    verify_entries(PROJECT, seal["files"], with_bytes=True)
    if canonical_root(seal["files"]) != seal.get("root_sha256"):
        raise FailClosed("S06 protocol root mismatch")
    return seal


def verify_parents() -> dict[str, Any]:
    binding = read_json(BINDING)
    contract = read_json(CONTRACT)
    authorization = read_json(AUTHORIZATION)
    if (contract.get("parent_s05_result_root_sha256") != binding["s05"]["result_root_sha256"] or
            authorization.get("status") != "AUTHORIZED_BY_USER_IN_CURRENT_TASK" or
            authorization.get("model_contact") is not False or authorization.get("probe_fitting") is not False):
        raise FailClosed("S06 contract/authorization/binding mismatch")

    s05_seal = read_json(S05_RESULT_SEAL)
    if (sha_file(S05_RESULT_SEAL) != binding["s05"]["result_seal_sha256"] or
            s05_seal.get("root_sha256") != binding["s05"]["result_root_sha256"] or
            s05_seal.get("S05_RESULT_READY") is not True or
            s05_seal.get("FAS00_SENSOR_PASS") is not False or
            s05_seal.get("FAS00_PHASE4_AUTHORIZED") is not False):
        raise FailClosed("S05 sealed result identity or disposition mismatch")
    if canonical_root(s05_seal["entries"]) != s05_seal["root_sha256"]:
        raise FailClosed("S05 result tree root does not reconstruct")
    verify_entries(S05_RUN, s05_seal["entries"], with_bytes=True)

    s05_protocol = read_json(S05_PROTOCOL_SEAL)
    if (sha_file(S05_PROTOCOL_SEAL) != binding["s05"]["protocol_seal_sha256"] or
            s05_protocol.get("root_sha256") != binding["s05"]["protocol_root_sha256"]):
        raise FailClosed("S05 protocol seal identity mismatch")
    verify_entries(S05_PROJECT, s05_protocol["files"], with_bytes=True)
    if canonical_root(s05_protocol["files"]) != binding["s05"]["protocol_root_sha256"]:
        raise FailClosed("S05 protocol bundle root mismatch")

    s05_receipt = read_json(S05_RECEIPT)
    if (sha_file(S05_RECEIPT) != binding["s05"]["files"]["execution-receipt-v01.json"] or
            s05_receipt.get("status") != "COMPLETE" or s05_receipt.get("model_contact") is not False or
            s05_receipt.get("probe_fitting") is not False):
        raise FailClosed("S05 execution receipt mismatch")
    for name, expected in binding["s05"]["files"].items():
        if sha_file(S05_RUN / name) != expected:
            raise FailClosed(f"S05 result artifact hash mismatch: {name}")

    paths = {
        "fas00_mean_features": FAS00_MEAN_FEATURES,
        "s02_final_features": S02_FINAL_FEATURES,
        "fas00_mean_readout": FAS00_MEAN_PROBE,
        "s02_final_readout": S02_FINAL_PROBE,
        "s01_mean_features": S01_MEAN_FEATURES,
        "s01_final_features": S01_FINAL_FEATURES,
        "s01_mean_readout": S01_MEAN_PROBE,
        "s01_final_readout": S01_FINAL_PROBE,
        "s01_mean_probabilities": S01_MEAN_PROBS,
        "s01_final_probabilities": S01_FINAL_PROBS,
    }
    declared = binding["inputs"]
    for name, path in paths.items():
        expected = DIRECT_INPUT_HASHES[name]
        if declared[name]["sha256"] != expected or sha_file(path) != expected:
            raise FailClosed(f"S06 direct input hash mismatch: {name}")
        if Path(declared[name]["path"]).as_posix().casefold() != path.as_posix().casefold():
            raise FailClosed(f"S06 direct input path binding mismatch: {name}")

    return {
        "s05_result_root_sha256": s05_seal["root_sha256"],
        "s05_protocol_root_sha256": s05_protocol["root_sha256"],
        "s05_result_seal_sha256": sha_file(S05_RESULT_SEAL),
        "s05_event_populations_sha256": sha_file(S05_POPULATIONS),
        "direct_input_hashes": dict(DIRECT_INPUT_HASHES),
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
    }
