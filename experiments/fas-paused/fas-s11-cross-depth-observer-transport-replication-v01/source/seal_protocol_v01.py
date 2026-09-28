from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


INCLUDED = (
    "FAS-S11-PROTOCOL-V01.md",
    "S11-PROPOSAL-V01.md",
    "contracts/s11-confirmatory-contract-v01.json",
    "source/seal_protocol_v01.py",
)


def sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def entry_for(path: Path, base: Path) -> dict[str, Any]:
    digest, size = sha256_file(path)
    return {"path": path.relative_to(base).as_posix(), "bytes": size, "sha256": digest}


def tree_root(entries: list[dict[str, Any]]) -> str:
    payload = "".join(
        f"{row['path']}\t{row['bytes']}\t{row['sha256']}\n"
        for row in sorted(entries, key=lambda row: row["path"])
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def main() -> int:
    project = Path(__file__).resolve().parents[1]
    seal_path = project / "seals" / "protocol-seal-v01.json"
    if seal_path.exists():
        raise SystemExit("S11 v01 protocol seal exists; refusing overwrite")

    contract_path = project / "contracts" / "s11-confirmatory-contract-v01.json"
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    authority = contract["authority"]
    if authority != {
        "S11_PROTOCOL_FROZEN": True,
        "S11_PANEL_CONSTRUCTION_AUTHORIZED": False,
        "S11_MODEL_CONTACT_AUTHORIZED": False,
        "S11_FEATURE_EXTRACTION_AUTHORIZED": False,
        "S11_OBSERVER_REPLAY_AUTHORIZED": False,
        "S11_RESULT_READY": False,
    }:
        raise RuntimeError("S11 authority state is not protocol-only")

    repo = project.parents[1]
    parents = contract["parents"]
    checks = {
        "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/contracts/world-contract-v01.json": parents["S01_2_world_contract_sha256"],
        "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/generate.rs": parents["S01_generator_generate_rs_sha256"],
        "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/model.rs": parents["S01_generator_model_rs_sha256"],
        "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/generator/src/validate.rs": parents["S01_generator_validate_rs_sha256"],
        "experiments/fas-s10-cross-depth-observer-transport-v03/source/linear_core.py": parents["S10_linear_core_py_sha256"],
        "experiments/fas-s10-cross-depth-observer-transport-v03/source/run_s10_transport.py": parents["S10_run_transport_py_sha256"],
        "experiments/fas-s10-cross-depth-observer-transport-v03/source/s09_math.py": parents["S09_math_py_sha256"],
    }
    for relative, expected in checks.items():
        actual, _ = sha256_file(repo / relative)
        if actual != expected:
            raise RuntimeError(f"parent source hash mismatch: {relative}: {actual}")

    seed = contract["fresh_panel"]["generator_seed_u64"]
    uncertainty = contract["uncertainty"]
    bootstrap_label = "FAS-S11-V01-BOOTSTRAP-SEED"
    bootstrap_digest = hashlib.sha256(bootstrap_label.encode("utf-8")).hexdigest()
    bootstrap_seed = int.from_bytes(bytes.fromhex(bootstrap_digest)[:8], "little")
    bootstrap = uncertainty["rng"]
    world_label = contract["fresh_panel"]["generator_seed_label"]
    world_digest = hashlib.sha256(world_label.encode("utf-8")).hexdigest()
    if world_digest != contract["fresh_panel"]["generator_seed_label_sha256"]:
        raise RuntimeError("world seed label digest mismatch")
    if int.from_bytes(bytes.fromhex(world_digest)[:8], "little") != seed:
        raise RuntimeError("world seed derivation mismatch")
    if bootstrap_digest not in bootstrap:
        raise RuntimeError("bootstrap seed digest mismatch")
    if str(bootstrap_seed) not in bootstrap:
        raise RuntimeError("bootstrap seed integer mismatch")

    old_contract = json.loads(
        (repo / "experiments/fas-s01-frozen-sensor-transfer-cartography/s01-2-v01/contracts/world-contract-v01.json").read_text(encoding="utf-8")
    )
    old_terms = {
        prefix + suffix
        for prefix in old_contract["term_inventory"]["prefixes"]
        for suffix in old_contract["term_inventory"]["suffixes"]
    }
    terms = {
        prefix + suffix
        for prefix in contract["fresh_panel"]["term_inventory"]["prefixes"]
        for suffix in contract["fresh_panel"]["term_inventory"]["suffixes"]
    }
    if len(terms) != 64 or terms & old_terms:
        raise RuntimeError("S11 term inventory is duplicated or overlaps S01-2")

    quotas = contract["fresh_panel"]["selection"]["per_class_quartet_quota"]
    if sum(quotas.values()) != contract["fresh_panel"]["selection"]["total_selected_quartets"]:
        raise RuntimeError("S11 class quotas do not sum to the fixed panel size")

    paths = [project.joinpath(*relative.split("/")) for relative in INCLUDED]
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise RuntimeError(f"S11 protocol source missing: {missing}")
    entries = sorted((entry_for(path, project) for path in paths), key=lambda row: row["path"])
    seal = {
        "seal_id": "FAS_S11_CONFIRMATORY_PROTOCOL_SEAL_V01",
        "project_id": "fas-s11-cross-depth-observer-transport-replication-v01",
        "entries": entries,
        "root_sha256": tree_root(entries),
        "panel_generated": False,
        "model_loaded": False,
        "features_extracted": False,
        "probe_fits_performed": False,
    }
    seal_path.parent.mkdir(parents=True, exist_ok=True)
    seal_path.write_text(
        json.dumps(seal, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"S11_PROTOCOL_SEALED root={seal['root_sha256']} files={len(entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
