from __future__ import annotations

from common import PHASE_ROOT, file_entry, sha256_file, tree_root, write_json


def seal_contract() -> dict[str, object]:
    seal_path = PHASE_ROOT / "seals" / "contract-freeze-seal-v01.json"
    if seal_path.exists():
        raise RuntimeError("S01-3 contract is already sealed; refusing to replace it")
    paths = [
        PHASE_ROOT / "README.md",
        PHASE_ROOT / "S01-3-PROTOCOL.md",
        *sorted((PHASE_ROOT / "contracts").glob("*.json")),
        *sorted((PHASE_ROOT / "source").glob("*.py")),
    ]
    entries = [file_entry(path, PHASE_ROOT) for path in paths]
    entries.sort(key=lambda item: item["path"])
    root = tree_root(entries)
    write_json(seal_path, {
        "seal_id": "FASS01_S01_3_CONTRACT_FREEZE_V01",
        "project_id": "fas-s01-frozen-sensor-transfer-cartography",
        "phase_id": "s01-3-linear-accessibility-v01",
        "algorithm": "SHA-256 over ordinal-sorted UTF-8 lines: relative_path<TAB>byte_length<TAB>file_sha256<LF>; seal excluded",
        "entries": entries,
        "root_sha256": root,
        "feature_fitting_performed": False,
    })
    return {"status": "CONTRACT_FROZEN", "contract_root_sha256": root, "entries": len(entries)}


if __name__ == "__main__":
    import json

    print(json.dumps(seal_contract(), sort_keys=True))
