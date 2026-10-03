from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = Path(__file__).resolve().parents[4]
FREEZE_PATH = PROJECT_ROOT / "contracts" / "e0-freeze-v01.json"
SEAL_PATH = PROJECT_ROOT / "seals" / "e0-seal-v01.json"
EXPECTED_STATUS = "E0_FROZEN_NOT_AUTHORIZED_FOR_MODEL_CONTACT"


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb", buffering=0) as stream:
        while chunk := stream.read(8 << 20):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def tree_root(entries: list[dict[str, Any]]) -> str:
    digest = hashlib.sha256()
    for row in sorted(entries, key=lambda item: item["path"]):
        digest.update(f'{row["path"]}\t{row["bytes"]}\t{row["sha256"]}\n'.encode("utf-8"))
    return digest.hexdigest()


def main() -> int:
    if SEAL_PATH.exists():
        raise SystemExit(f"refusing to overwrite existing E0 seal: {SEAL_PATH}")
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze.get("status") != EXPECTED_STATUS:
        raise SystemExit("E0 freeze has an invalid status")
    if freeze.get("model_contact_authorized") is not False or freeze.get("observer_fitting_authorized") is not False:
        raise SystemExit("E0 freeze crosses the model-contact or fitting authorization boundary")

    source_hashes = freeze.get("frozen_source_sha256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise SystemExit("E0 source hashes are missing")
    abi_path = PROJECT_ROOT / "contracts" / "representation-abi-v01.json"
    world_path = PROJECT_ROOT / "contracts" / "panel-world-contract-v01.json"
    abi = json.loads(abi_path.read_text(encoding="utf-8"))
    world = json.loads(world_path.read_text(encoding="utf-8"))
    abi_sha, _ = sha256_file(abi_path)
    world_sha, _ = sha256_file(world_path)
    extractor_path = "experiments/fas-frozen-observer-bundle-engineering-v01/source/scripts/extract_features_v01.py"
    generator_path = "experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator/src/generate.rs"
    builder_path = "experiments/fas-frozen-observer-bundle-engineering-v01/source/panel-generator/src/main.rs"
    if freeze.get("representation_abi_sha256") != abi_sha or freeze.get("panel_world_contract_sha256") != world_sha:
        raise SystemExit("E0 freeze does not bind the exact ABI and panel contract bytes")
    if freeze.get("extractor_source_sha256") != source_hashes.get(extractor_path):
        raise SystemExit("E0 extractor source hash is internally inconsistent")
    if abi.get("extractor_source_sha256") != source_hashes.get(extractor_path):
        raise SystemExit("representation ABI does not bind the frozen extractor source")
    if world.get("generator_lineage", {}).get("generator_source_sha256") != source_hashes.get(generator_path):
        raise SystemExit("panel world contract does not bind the frozen generator")
    if world.get("generator_lineage", {}).get("panel_builder_source_sha256") != source_hashes.get(builder_path):
        raise SystemExit("panel world contract does not bind the frozen panel builder")
    entries: list[dict[str, Any]] = []
    contract_base = PROJECT_ROOT.relative_to(REPO_ROOT).as_posix() + "/contracts/"
    files = {
        contract_base + "e0-freeze-v01.json",
        contract_base + "panel-world-contract-v01.json",
        contract_base + "representation-abi-v01.json",
        *source_hashes.keys(),
    }
    for relative in sorted(files):
        path = REPO_ROOT / Path(relative)
        if not path.is_file():
            raise SystemExit(f"frozen E0 artifact is missing: {relative}")
        digest, size = sha256_file(path)
        expected = source_hashes.get(relative)
        if expected is not None and digest != expected:
            raise SystemExit(f"frozen source hash differs: {relative}")
        entries.append({"path": relative.replace("\\", "/"), "bytes": size, "sha256": digest})

    root = tree_root(entries)
    seal = {
        "seal_id": "FAS_FROZEN_OBSERVER_BUNDLE_E0_SEAL_V01",
        "status": EXPECTED_STATUS,
        "root_sha256": root,
        "entry_count": len(entries),
        "entries": entries,
        "model_contact_authorized": False,
        "tokenizer_contact_authorized": False,
        "feature_extraction_authorized": False,
        "observer_fitting_authorized": False,
        "seal_created_utc": datetime.now(timezone.utc).isoformat(),
    }
    SEAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SEAL_PATH.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(seal, stream, ensure_ascii=True, indent=2)
        stream.write("\n")
        stream.flush()
    print(f"E0 sealed: root_sha256={root}; entries={len(entries)}; model_contact_authorized=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
