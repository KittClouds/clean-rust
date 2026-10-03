from __future__ import annotations

from pathlib import Path

from s07_common import RUN, FailClosed, read_json, root_simple, sha256_file, verify_protocol


def verify_tree(root: Path, seal_name: str, expected_id: str) -> dict:
    seal_path = root / seal_name
    if not seal_path.is_file():
        raise FailClosed(f"Missing seal: {seal_path}")
    seal = read_json(seal_path)
    entries = seal.get("entries", [])
    if seal.get("seal_id") != expected_id or not entries or root_simple(entries) != seal.get("root_sha256"):
        raise FailClosed(f"Invalid tree seal: {seal_path}")
    for item in entries:
        path = root / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise FailClosed(f"Sealed file identity mismatch: {path}")
    return seal


def main() -> None:
    protocol = verify_protocol()
    training = verify_tree(RUN, "training-tree-seal-v01.json", "FAS_S07_TRAINING_TREE_SEAL_V01")
    gate = verify_tree(RUN, "gate-tree-seal-v01.json", "FAS_S07_GATE_TREE_SEAL_V01")
    analysis_root = RUN / "sparse-analysis-v01"
    s01 = verify_tree(analysis_root / "s01-analysis-v01", "s01-analysis-seal-v01.json", "FAS_S07_S01_ANALYSIS_SEAL_V01")
    external = verify_tree(analysis_root / "fas00-external-v01", "fas00-external-seal-v01.json", "FAS_S07_FAS00_EXTERNAL_SEAL_V01")
    result = verify_tree(analysis_root, "result-tree-seal-v01.json", "FAS_S07_RESULT_TREE_SEAL_V01")
    if training.get("status") != "SEALED" or gate.get("gate_status") != "PASS" or result.get("status") != "SEALED":
        raise FailClosed("S07 terminal seal status mismatch")
    if result.get("protocol_root_sha256") != protocol["root_sha256"] or result.get("gate_root_sha256") != gate["root_sha256"]:
        raise FailClosed("S07 parent root binding mismatch")
    if result.get("s01_analysis_root_sha256") != s01.get("root_sha256") or result.get("fas00_external_root_sha256") != external.get("root_sha256"):
        raise FailClosed("S07 phase result root binding mismatch")
    if result.get("S07_RESULT_READY") is not True or result.get("FAS00_SENSOR_PASS") is not False or result.get("adaptive_mechanism_authorized") is not False:
        raise FailClosed("S07 terminal disposition is invalid")
    print(f"S07_INDEPENDENT_RESULT_VERIFICATION_PASS root={result['root_sha256']} entries={len(result['entries'])}")


if __name__ == "__main__":
    try:
        main()
    except FailClosed as exc:
        print(f"S07_VERIFY_FAIL_CLOSED {exc}")
        raise SystemExit(2)
