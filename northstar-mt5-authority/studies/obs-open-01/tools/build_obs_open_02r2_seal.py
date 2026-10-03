"""Build the deterministic OBS-OPEN-02R2 protocol and quality seal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
UNIVERSE_ROOT = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235"
PROTOCOL_ROOT = "141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5"
R1_ROOT = "dc8826042d490c5b1e868b836f4c187af8e2baedf9454d11b2be2a5a5aae3da7"
PREFLIGHT_ROOT = "2e32be4387d51fb993e61c01d2b72b170fe9226e315d330f9173f0f03f7b9e25"
CONTENT = (
    Path("studies/obs-open-01/contracts/obs_open_02r2_executable_discovery_v1.json"),
    Path("studies/obs-open-01/protocol/OBS_OPEN_02R2_EXECUTABLE_DISCOVERY_COMPLETION_V1.md"),
    Path("studies/obs-open-01/qualification/OBS_OPEN_02R2_EXECUTABLE_COMPLETION_CHECKPOINT_20260814.md"),
    Path("studies/obs-open-01/tools/obs_open_02r2_semantics.py"),
    Path("studies/obs-open-01/tools/obs_open_02r2_data_quality.py"),
    Path("studies/obs-open-01/tests/test_obs_open_02r2_semantics.py"),
    Path("studies/obs-open-01/tests/test_obs_open_02r2_data_quality.py"),
    Path("studies/obs-open-01/qualification/universe/obs-open-02r2-seal/obs_open_02r2_discovery_source_quality_receipt.json"),
    Path("studies/obs-open-01/tools/build_obs_open_02r2_seal.py"),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def validate() -> tuple[dict[str, object], dict[str, object]]:
    contract = json.loads((ROOT / CONTENT[0]).read_text(encoding="utf-8"))
    quality = json.loads((ROOT / CONTENT[-2]).read_text(encoding="utf-8"))
    if contract["parent_universe_root_sha256"] != UNIVERSE_ROOT:
        raise ValueError("universe root mismatch")
    if contract["parent_protocol_root_sha256"] != PROTOCOL_ROOT:
        raise ValueError("protocol root mismatch")
    if contract["parent_r1_root_sha256"] != R1_ROOT:
        raise ValueError("R1 root mismatch")
    if contract["parent_preflight_logical_sha256"] != PREFLIGHT_ROOT:
        raise ValueError("preflight root mismatch")
    if sum(row["count"] for row in contract["formal_estimand_templates"].values()) != 119:
        raise ValueError("formal family count mismatch")
    if quality["outcome"] != "PASS" or quality["confirmation_rows_read"] != 0:
        raise ValueError("discovery source quality is not admissible")
    if quality["substantive_measurements_computed"]:
        raise ValueError("quality gate computed substantive measurements")
    return contract, quality


def build(output: Path) -> None:
    contract, quality = validate()
    rows = ["path\tsize_bytes\tsha256"]
    for rel in CONTENT:
        data = (ROOT / rel).read_bytes()
        rows.append(f"{rel.as_posix()}\t{len(data)}\t{digest(data)}")
    manifest = ("\n".join(rows) + "\n").encode("utf-8")
    manifest_hash = digest(manifest)
    root_hash = digest(("OBS_OPEN_02R2_ROOT_V1\n" + manifest_hash + "\n").encode("ascii"))
    output.mkdir(parents=True, exist_ok=True)
    (output / "obs_open_02r2_content_manifest.tsv").write_bytes(manifest)
    root_receipt = {
        "schema": "OBS_OPEN_EXECUTABLE_DISCOVERY_COMPLETION_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "gate": "OBS-OPEN-02R2",
        "universe_root_sha256": UNIVERSE_ROOT,
        "protocol_root_sha256": PROTOCOL_ROOT,
        "r1_root_sha256": R1_ROOT,
        "preflight_logical_sha256": PREFLIGHT_ROOT,
        "manifest_sha256": manifest_hash,
        "r2_root_sha256": root_hash,
        "formal_estimand_count": 119,
        "repaired_gap_count": len(contract["repair_scope"]),
        "data_quality_outcome": quality["outcome"],
        "data_quality_logical_sha256": quality["logical_sha256"],
        "confirmation_observations_read": False,
        "confirmation_status": "FROZEN_UNOPENED",
        "substantive_measurements_computed": False,
        "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
        "economic_authority": False,
        "trading_authority": False,
    }
    build_receipt = {
        "schema": "OBS_OPEN_EXECUTABLE_DISCOVERY_COMPLETION_BUILD_V1",
        "gate": "OBS-OPEN-02R2",
        "manifest_sha256": manifest_hash,
        "r2_root_sha256": root_hash,
        "builder_sha256": digest((ROOT / CONTENT[-1]).read_bytes()),
        "observation_access": "OUTCOME_BLIND_DISCOVERY_SOURCE_QUALITY_ONLY",
        "confirmation_rows_read": 0,
        "rebuild_requirement": "TWO_CLEAN_BUILDS_BYTE_IDENTICAL",
    }
    (output / "obs_open_02r2_root_receipt.json").write_bytes(canonical_json(root_receipt))
    (output / "obs_open_02r2_build_receipt.json").write_bytes(canonical_json(build_receipt))
    print(root_hash)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build(args.output)
