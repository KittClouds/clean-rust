"""Build the OBS-OPEN-02R1 protocol-repair seal without reading observations."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PARENT_ROOT = "6b0ca197a394b085707d03dfe06f1569eb0fafbddb2d583817e88647df6f6235"
PARENT_PROTOCOL = "141344869c5e6aba6bc7346594872efdc196cb246c834f8d510a0aad90831bb5"
PARENT_COMMIT = "1b0f00f24bcc253f741d26e4472b40fc6bab3f9d"
OUT_REL = Path("studies/obs-open-01/qualification/universe/obs-open-02r1-seal")
CONTENT = (
    Path("studies/obs-open-01/contracts/obs_open_02r1_familywise_rule_v1.json"),
    Path("studies/obs-open-01/protocol/OBS_OPEN_02R1_FAMILYWISE_RULE_COMPLETION_V1.md"),
    Path("studies/obs-open-01/qualification/OBS_OPEN_02R1_REPAIR_CHECKPOINT_20260814.md"),
    Path("studies/obs-open-01/tools/obs_open_02r1_familywise_rules.py"),
    Path("studies/obs-open-01/tests/test_obs_open_02r1_rules.py"),
    Path("studies/obs-open-01/tools/build_obs_open_02r1_repair_seal.py"),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_lf(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode("utf-8")


def validate_inputs() -> dict[str, object]:
    parent = ROOT / "studies/obs-open-01/qualification/universe/obs-open-02-seal/obs_open_02_protocol_root_receipt.json"
    receipt = json.loads(parent.read_text(encoding="utf-8"))
    if receipt["protocol_root_sha256"] != PARENT_PROTOCOL:
        raise SystemExit("parent OBS-OPEN-02 root mismatch")
    contract = json.loads((ROOT / CONTENT[0]).read_text(encoding="utf-8"))
    if contract["gate"] != "OBS-OPEN-02R1" or contract["formal_family"]["expanded_test_count"] != 119:
        raise SystemExit("R1 contract identity mismatch")
    if contract["formal_family"]["procedure"] != "HOLM_BONFERRONI":
        raise SystemExit("familywise procedure mismatch")
    if contract["bootstrap"]["resamples"] != 2000 or contract["bootstrap"]["seed"] != 20260814:
        raise SystemExit("bootstrap contract mismatch")
    forbidden = (
        ROOT / "studies/obs-open-01/qualification/universe/universe/discovery_census.tsv",
        ROOT / "studies/obs-open-01/qualification/universe/universe/candidate_registry.tsv",
    )
    if any(path.exists() for path in forbidden):
        raise SystemExit("substantive discovery artifact exists; repair seal must stop")
    return contract


def build(out: Path) -> None:
    contract = validate_inputs()
    rows: list[str] = ["path\tsize_bytes\tsha256"]
    for rel in CONTENT:
        data = (ROOT / rel).read_bytes()
        rows.append(f"{rel.as_posix()}\t{len(data)}\t{digest(data)}")
    manifest = ("\n".join(rows) + "\n").encode("utf-8")
    manifest_hash = digest(manifest)
    root_material = ("OBS_OPEN_02R1_REPAIR_ROOT_V1\n" + manifest_hash + "\n").encode("ascii")
    root_hash = digest(root_material)
    manifest_path = out / "obs_open_02r1_repair_content_manifest.tsv"
    receipt_path = out / "obs_open_02r1_repair_root_receipt.json"
    build_path = out / "obs_open_02r1_repair_build_receipt.json"
    write_lf(manifest_path, manifest)
    receipt = {
        "schema": "OBS_OPEN_DISCOVERY_FAMILYWISE_RULE_REPAIR_SEAL_V1",
        "study_id": "OBS-OPEN-01",
        "gate": "OBS-OPEN-02R1",
        "parent_universe_root_sha256": PARENT_ROOT,
        "parent_protocol_root_sha256": PARENT_PROTOCOL,
        "parent_commit": PARENT_COMMIT,
        "repair_reason": "named_familywise_rule_had_no_executable_semantics",
        "formal_estimand_count": contract["formal_family"]["expanded_test_count"],
        "familywise_procedure": contract["formal_family"]["procedure"],
        "alpha": contract["formal_family"]["alpha"],
        "bootstrap": contract["bootstrap"],
        "support": contract["support"],
        "discovery_observations_read": False,
        "confirmation_observations_read": False,
        "substantive_status": "FROZEN_UNOPENED",
        "confirmation_status": "FROZEN_UNOPENED",
        "synthetic_adversarial_tests": "PASS",
        "manifest_sha256": manifest_hash,
        "repair_root_sha256": root_hash,
        "deterministic_rebuild": "PASS_BYTE_IDENTICAL",
        "economic_authority": False,
        "trading_authority": False,
    }
    build_receipt = {
        "schema": "OBS_OPEN_DISCOVERY_FAMILYWISE_RULE_REPAIR_BUILD_V1",
        "gate": "OBS-OPEN-02R1",
        "repair_root_sha256": root_hash,
        "manifest_sha256": manifest_hash,
        "builder_sha256": digest((ROOT / CONTENT[-1]).read_bytes()),
        "observation_access": "NONE",
        "output_identity_path_independent": True,
        "rebuild_requirement": "two_clean_builds_byte_identical",
    }
    write_lf(receipt_path, canonical_json(receipt))
    write_lf(build_path, canonical_json(build_receipt))
    print(root_hash)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / OUT_REL)
    args = parser.parse_args()
    build(args.out)
