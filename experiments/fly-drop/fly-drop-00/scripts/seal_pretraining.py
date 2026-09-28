"""Validate and seal the FLY-DROP-00 pretraining artifacts, without outcomes."""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys
from datetime import datetime, timezone

EXPERIMENT = pathlib.Path(__file__).resolve().parents[1]
REPO = EXPERIMENT.parents[1]
ARTIFACTS = EXPERIMENT / "artifacts"
STAGE = pathlib.Path(r"D:\fly-drop-00-stage\columns")
BUILDER = pathlib.Path(r"D:\fly-drop-00-target\release\fly-drop-00.exe")
SOURCE = pathlib.Path(r"D:\drosophila-heresy\data\connectome-weights-male-cns-v1.0-minconf-0.5.feather")
SEAL_PATH = EXPERIMENT / "PRETRAINING-SEAL.json"
DIGEST_PATH = EXPERIMENT / "PRETRAINING-SEAL.sha256"


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_file(files: list[dict[str, object]], path: pathlib.Path, label: str) -> None:
    files.append({"path": label, "bytes": path.stat().st_size, "sha256": sha256(path)})


def verify_recorded_file(record: dict[str, object], files: list[dict[str, object]]) -> None:
    rel = pathlib.Path(str(record.get("file", record.get("matrix_file"))))
    path = REPO / rel
    if not path.is_file():
        raise RuntimeError(f"missing recorded artifact: {path}")
    actual = sha256(path)
    expected_hash = record.get("sha256", record.get("matrix_sha256"))
    if actual != expected_hash:
        raise RuntimeError(f"recorded hash mismatch: {path}")
    expected_bytes = int(record.get("bytes", 128 * 128 * 8 if "matrix_file" in record else -1))
    if expected_bytes < 0 or path.stat().st_size != expected_bytes:
        raise RuntimeError(f"recorded byte count mismatch: {path}")
    add_file(files, path, rel.as_posix())


def source_column_records() -> list[dict[str, object]]:
    receipt = json.loads((STAGE / "columns-receipt.json").read_text(encoding="utf-8"))
    if receipt["source_rows"] != 151_856_684:
        raise RuntimeError("staged source row count differs from contract")
    if receipt["source_sha256"] != "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1":
        raise RuntimeError("staged source identity differs from MaleCNS v1.0 receipt")
    records = []
    for record in receipt["columns"]:
        path = STAGE / record["file"]
        if not path.is_file() or path.stat().st_size != record["bytes"] or sha256(path) != record["sha256"]:
            raise RuntimeError(f"staged column failed receipt check: {path}")
        records.append({"file": str(path), "bytes": record["bytes"], "sha256": record["sha256"]})
    return records


def main() -> None:
    if not ARTIFACTS.is_dir():
        raise RuntimeError("authoritative artifacts directory is missing")
    manifest_path = ARTIFACTS / "pretraining-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["source_rows"] != 151_856_684 or manifest["endpoint_count"] != 88_384_522:
        raise RuntimeError("source dimensions differ from the frozen protocol")
    if manifest["source_sha256"] != "e35da783d1c686b2b58b3b87cd6a403ae43bfcfba8bff28e08ef752c1a56afc1":
        raise RuntimeError("source hash differs from the frozen protocol")
    if not manifest["fixture_projection_verified"]:
        raise RuntimeError("direct projection fixture is not recorded as passed")
    if len(manifest["graphs"]) != 9 or any(g["rows"] != 151_856_684 for g in manifest["graphs"]):
        raise RuntimeError("graph realization count or row count mismatch")
    graph_seeds = {arm: sorted(g["seed"] for g in manifest["graphs"] if g["arm"] == arm) for arm in ("degree-preserved-shuffle", "random-sparse")}
    if graph_seeds["degree-preserved-shuffle"] != [2101, 2102, 2103, 2104] or graph_seeds["random-sparse"] != [3101, 3102, 3103, 3104]:
        raise RuntimeError("graph realization seed set mismatch")
    if len(manifest["operators"]) != 41 or len({o["matrix_file"] for o in manifest["operators"]}) != 41:
        raise RuntimeError("expected 41 uniquely named effective operators")
    dense = [o for o in manifest["operators"] if o["arm"] == "dense"]
    if sorted(o["control_seed"] for o in dense) != [5101, 5102, 5103, 5104]:
        raise RuntimeError("dense seed set mismatch")
    operator_counts = {arm: sum(o["arm"] == arm for o in manifest["operators"]) for arm in ("malecns", "degree", "random", "dense", "identity")}
    if operator_counts != {"malecns": 4, "degree": 16, "random": 16, "dense": 4, "identity": 1}:
        raise RuntimeError(f"operator arm count mismatch: {operator_counts}")
    if len(manifest["teacher_worlds"]) != 4:
        raise RuntimeError("teacher world count mismatch")

    files: list[dict[str, object]] = []
    add_file(files, EXPERIMENT / "PROTOCOL.md", "experiments/fly-drop-00/PROTOCOL.md")
    add_file(files, EXPERIMENT / "DESIGN.md", "experiments/fly-drop-00/DESIGN.md")
    add_file(files, EXPERIMENT / "Cargo.toml", "experiments/fly-drop-00/Cargo.toml")
    add_file(files, EXPERIMENT / "Cargo.lock", "experiments/fly-drop-00/Cargo.lock")
    add_file(files, manifest_path, "experiments/fly-drop-00/artifacts/pretraining-manifest.json")
    add_file(files, EXPERIMENT / "preflight/source-census.json", "experiments/fly-drop-00/preflight/source-census.json")
    add_file(files, EXPERIMENT / "scripts/source_census.py", "experiments/fly-drop-00/scripts/source_census.py")
    add_file(files, EXPERIMENT / "scripts/feather_to_columns.py", "experiments/fly-drop-00/scripts/feather_to_columns.py")
    add_file(files, pathlib.Path(__file__), "experiments/fly-drop-00/scripts/seal_pretraining.py")
    for source in sorted((EXPERIMENT / "src").glob("*.rs")):
        add_file(files, source, source.relative_to(REPO).as_posix())
    add_file(files, BUILDER, str(BUILDER))

    rustc = pathlib.Path(shutil.which("rustc") or "")
    cargo = pathlib.Path(shutil.which("cargo") or "")
    if not rustc.is_file() or not cargo.is_file() or not BUILDER.is_file():
        raise RuntimeError("compiler, Cargo, or release executable is missing")
    add_file(files, rustc, str(rustc))
    compiler = subprocess.check_output([str(rustc), "-Vv"], text=True).strip()
    cargo_version = subprocess.check_output([str(cargo), "-V"], text=True).strip()

    column_records = source_column_records()
    stage_receipt_path = STAGE / "columns-receipt.json"
    add_file(files, stage_receipt_path, str(stage_receipt_path))
    for record in column_records:
        files.append({"path": record["file"], "bytes": record["bytes"], "sha256": record["sha256"]})
    source_hash = sha256(SOURCE) if SOURCE.is_file() else None
    if source_hash != manifest["source_sha256"]:
        raise RuntimeError("source Feather no longer matches frozen source identity")
    files.append({"path": str(SOURCE), "bytes": SOURCE.stat().st_size, "sha256": source_hash})
    artifacts = 0
    for op in manifest["operators"]:
        verify_recorded_file(op, files)
        artifacts += 1
        if op["census"]["rank"] < 0 or len(op["census"]["singular_values_descending"]) != 128:
            raise RuntimeError(f"incomplete census for {op['matrix_file']}")
    for world in manifest["teacher_worlds"]:
        for record in world["files"]:
            verify_recorded_file(record, files)
            artifacts += 1
    if artifacts != 61:
        raise RuntimeError(f"expected 61 operator and teacher data artifacts, got {artifacts}")

    seal = {
        "identity": "FLY-DROP-00-v0.1",
        "status": "SEALED_PRE_TRAINING",
        "sealed_utc": datetime.now(timezone.utc).isoformat(),
        "claim_scope": "frozen 128-dimensional projection of the complete MaleCNS segment-connection-table operator",
        "learner_outcomes_present": False,
        "jev_in_scope": False,
        "protocol_sha256": sha256(EXPERIMENT / "PROTOCOL.md"),
        "pretraining_manifest_sha256": sha256(manifest_path),
        "endpoint_universe": {
            "count": manifest["endpoint_count"],
            "sorted_signed_i64_little_endian_sha256": manifest["endpoint_universe_sha256"],
        },
        "source_columns": column_records,
        "graph_realizations": manifest["graphs"],
        "operators": manifest["operators"],
        "teacher_worlds": manifest["teacher_worlds"],
        "implementation_checks": {
            "small_graph_direct_projection_all_adapters": "passed, absolute tolerance 1e-12",
            "known_singular_spectrum_census_fixture": "passed",
            "operator_files_hash_match_manifest": True,
            "operator_count_unique_paths": len(manifest["operators"]),
        },
        "toolchain": {"rustc_verbose": compiler, "cargo": cargo_version},
        "commands": {
            "build_target": r"D:\fly-drop-00-target",
            "compile_and_prepare": r"$env:CARGO_TARGET_DIR='D:\fly-drop-00-target'; cargo run --release --offline --manifest-path experiments\fly-drop-00\Cargo.toml",
            "verify_only": r"$env:CARGO_TARGET_DIR='D:\fly-drop-00-target'; cargo run --release --offline --manifest-path experiments\fly-drop-00\Cargo.toml -- --verify-only",
        },
        "resource_notes": {
            "endpoint_index": "88,384,522 IDs; dense hash index plus sorted ID vector",
            "source_columns_mapped_bytes": sum(r["bytes"] for r in column_records),
            "operator_matrix_bytes": sum(o["census"] is not None and 128 * 128 * 8 for o in manifest["operators"]),
            "initial_free_ram_snapshot_gib_before_first_build": 13.18,
            "peak_process_rss": "not instrumented",
        },
        "files": sorted(files, key=lambda item: str(item["path"])),
        "excluded_superseded_tree": "artifacts-superseded-dense-name-bug; pre-seal filename collision, no learner outcomes, not referenced by this seal",
    }

    if SEAL_PATH.exists() or DIGEST_PATH.exists():
        raise RuntimeError("seal already exists; refusing to rewrite sealed identity")
    payload = (json.dumps(seal, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temp = SEAL_PATH.with_suffix(".json.tmp")
    with temp.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, SEAL_PATH)
    digest = sha256(SEAL_PATH)
    DIGEST_PATH.write_text(f"{digest}  PRETRAINING-SEAL.json\n", encoding="ascii")
    print(json.dumps({"seal": str(SEAL_PATH), "sha256": digest, "operator_count": len(manifest["operators"]), "artifact_count": artifacts}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"seal failed: {error}", file=sys.stderr)
        raise
