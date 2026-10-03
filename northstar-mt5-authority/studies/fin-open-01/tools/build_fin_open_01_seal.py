"""Build and seal FIN-OPEN-01 without opening financial outcomes."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

from fin_open_01_synthetic import run_synthetic_qualification


ALLOWED_AUTHORITY_FILES = (
    "contracts/obs_open_01_protocol_v1.json",
    "qualification/universe/universe/admitted_sessions.tsv",
    "qualification/universe/universe/partition_manifest.tsv",
    "qualification/universe/universe/universe_qualification_receipt.json",
    "qualification/universe/seal/universe_qualification_root_receipt.json",
    "qualification/universe/clock/clock_transport_receipt.json",
    "qualification/parity/opening_range_oracle_receipt.json",
    "qualification/parity/blackbox_parity_receipt.json",
)
FORBIDDEN_PATH_TOKENS = (
    "obs_open_03_discovery",
    "obs-open-03-discovery",
    "discovery_findings",
    "discovery_scale_summary",
    "confirmation_rows",
    "science_confirmation",
)


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def pretty_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def assert_allowed(relative_path: str) -> None:
    lowered = relative_path.lower().replace("\\", "/")
    assert relative_path in ALLOWED_AUTHORITY_FILES, f"authority path is not allowlisted: {relative_path}"
    assert not any(token in lowered for token in FORBIDDEN_PATH_TOKENS), f"forbidden substantive path: {relative_path}"


def build_authority_manifest(authority_root: Path) -> dict[str, object]:
    files: dict[str, dict[str, object]] = {}
    for relative_path in ALLOWED_AUTHORITY_FILES:
        assert_allowed(relative_path)
        path = authority_root / Path(relative_path)
        assert path.is_file(), f"missing qualified authority: {path}"
        files[relative_path] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}

    contract = read_json(authority_root / ALLOWED_AUTHORITY_FILES[0])
    universe = read_json(authority_root / ALLOWED_AUTHORITY_FILES[3])
    universe_root = read_json(authority_root / ALLOWED_AUTHORITY_FILES[4])
    clock = read_json(authority_root / ALLOWED_AUTHORITY_FILES[5])
    oracle = read_json(authority_root / ALLOWED_AUTHORITY_FILES[6])
    parity = read_json(authority_root / ALLOWED_AUTHORITY_FILES[7])
    rows = read_tsv(authority_root / ALLOWED_AUTHORITY_FILES[1])
    discovery = sorted((row for row in rows if row["partition"] == "DISCOVERY"), key=lambda row: (row["civil_date"], row["session_id"]))
    confirmation = [row for row in rows if row["partition"] == "CONFIRMATION"]

    assert len(rows) == 326
    assert len(discovery) == 257
    assert len(confirmation) == 69
    assert all(row["confirmation_status"] == "FROZEN_UNOPENED" for row in confirmation)
    assert universe["outcome"] == "QUALIFIED"
    assert universe["discovery_sessions"] == 257
    assert universe["confirmation_sessions"] == 69
    assert universe["substantive_observer_outputs_read"] is False
    assert universe_root["economic_authority"] is False
    assert universe_root["trading_authority"] is False
    assert universe_root["substantive_results_status"] == "FROZEN_UNOPENED"
    assert clock["outcome"] == "QUALIFIED"
    assert clock["substantive_observer_outputs_read"] is False
    assert oracle["range_count"] == 30
    assert parity["outcome"] == "PASS"
    assert parity["substantive_results_status"] == "FROZEN_UNOPENED"
    assert contract["economic_authority"] is False
    assert contract["trading_authority"] is False

    population_lines = ["session_id\tcivil_date\tserver_offset_minutes\n"]
    population_lines.extend(
        f"{row['session_id']}\t{row['civil_date']}\t{row['server_offset_minutes']}\n" for row in discovery
    )
    population_bytes = "".join(population_lines).encode("utf-8")
    offset_counts: dict[str, int] = {}
    for row in discovery:
        offset_counts[row["server_offset_minutes"]] = offset_counts.get(row["server_offset_minutes"], 0) + 1
    return {
        "schema": "FIN_OPEN_01_AUTHORITY_MANIFEST_V1",
        "parent_study_id": "OBS-OPEN-01",
        "authorized_source_partition": "DISCOVERY",
        "authorized_session_count": len(discovery),
        "confirmation_session_count": len(confirmation),
        "confirmation_status": "FROZEN_UNOPENED",
        "substantive_observer_outputs_read": False,
        "economic_authority_inherited": False,
        "trading_authority_inherited": False,
        "qualified_server_offset_minutes": sorted(int(value) for value in offset_counts),
        "discovery_offset_counts": {key: offset_counts[key] for key in sorted(offset_counts)},
        "discovery_population_sha256": sha256_bytes(population_bytes),
        "source_files": files,
        "source_contract_sha256": files[ALLOWED_AUTHORITY_FILES[0]]["sha256"],
        "universe_qualification_root_sha256": universe_root["qualification_root_sha256"],
        "range_oracle_sha256": oracle["oracle_sha256"],
        "observer_source_sha256": contract["instrument"]["observer_source_sha256"],
        "observer_binary_sha256": contract["instrument"]["preexisting_compiled_candidate_sha256"],
    }


def partition_text(rows: list[dict[str, str]]) -> tuple[bytes, dict[str, object]]:
    ordered = sorted((row for row in rows if row["partition"] == "DISCOVERY"), key=lambda row: (row["civil_date"], row["session_id"]))
    development = ordered[:180]
    validation = ordered[180:]
    assert len(development) == 180 and len(validation) == 77
    assert {row["server_offset_minutes"] for row in development} == {"120", "180"}
    assert {row["server_offset_minutes"] for row in validation} == {"120", "180"}
    lines = ["session_id\tcivil_date\tfinancial_partition\tserver_offset_minutes\tsource_partition\tconfirmation_status\n"]
    for index, row in enumerate(ordered):
        financial_partition = "D_F" if index < 180 else "V_F"
        lines.append(
            f"{row['session_id']}\t{row['civil_date']}\t{financial_partition}\t{row['server_offset_minutes']}\t{row['partition']}\t{row['confirmation_status']}\n"
        )
    metadata = {
        "schema": "FIN_OPEN_01_FINANCIAL_PARTITION_V1",
        "population_count": len(ordered),
        "development": {"name": "D_F", "count": len(development), "last_civil_date": development[-1]["civil_date"]},
        "validation": {"name": "V_F", "count": len(validation), "first_civil_date": validation[0]["civil_date"], "state": "FROZEN_UNOPENED"},
        "assignment": "METADATA_ONLY_CHRONOLOGICAL",
        "offset_regimes_in_development": sorted({int(row["server_offset_minutes"]) for row in development}),
        "offset_regimes_in_validation": sorted({int(row["server_offset_minutes"]) for row in validation}),
        "outcomes_read": False,
    }
    return "".join(lines).encode("utf-8"), metadata


def write_file(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def build_seal(study_root: Path, authority_root: Path, output_dir: Path) -> dict[str, object]:
    contract_path = study_root / "contracts" / "fin_open_01_protocol_v1.json"
    readme_path = study_root / "README.md"
    assert contract_path.is_file() and readme_path.is_file()
    authority = build_authority_manifest(authority_root)
    admitted_rows = read_tsv(authority_root / "qualification/universe/universe/admitted_sessions.tsv")
    partition_bytes, partition_metadata = partition_text(admitted_rows)
    synthetic = run_synthetic_qualification()

    authority_bytes = pretty_json(authority)
    synthetic_bytes = pretty_json(synthetic)
    generated = {
        "authority_manifest.json": authority_bytes,
        "financial_partition.tsv": partition_bytes,
        "synthetic_qualification_receipt.json": synthetic_bytes,
    }
    for name, content in generated.items():
        write_file(output_dir / name, content)

    content_entries = [
        {"path": "README.md", "sha256": sha256_file(readme_path), "bytes": readme_path.stat().st_size},
        {"path": "contracts/fin_open_01_protocol_v1.json", "sha256": sha256_file(contract_path), "bytes": contract_path.stat().st_size},
    ]
    content_entries.extend({"path": name, "sha256": sha256_bytes(content), "bytes": len(content)} for name, content in generated.items())
    content_lines = ["path\tsha256\tbytes\n"]
    content_lines.extend(f"{entry['path']}\t{entry['sha256']}\t{entry['bytes']}\n" for entry in content_entries)
    content_manifest_bytes = "".join(content_lines).encode("utf-8")
    write_file(output_dir / "protocol_content_manifest.tsv", content_manifest_bytes)
    protocol_root_sha256 = sha256_bytes(content_manifest_bytes)

    root_receipt = {
        "schema": "FIN_OPEN_01_PROTOCOL_ROOT_RECEIPT_V1",
        "protocol_id": "FIN-OPEN-01",
        "status": "PROTOCOL_QUALIFIED",
        "protocol_root_sha256": protocol_root_sha256,
        "content_manifest_sha256": protocol_root_sha256,
        "authority_manifest_sha256": sha256_bytes(authority_bytes),
        "financial_partition_sha256": sha256_bytes(partition_bytes),
        "synthetic_qualification_sha256": sha256_bytes(synthetic_bytes),
        "authority": {
            "parent_study_id": "OBS-OPEN-01",
            "authorized_discovery_sessions": 257,
            "confirmation_sessions": 69,
            "confirmation_status": "FROZEN_UNOPENED",
            "substantive_observer_outputs_read": False,
        },
        "partition": partition_metadata,
        "outcomes": {
            "financial_development": "FROZEN_UNOPENED",
            "financial_validation": "FROZEN_UNOPENED",
            "science_confirmation": "FROZEN_UNOPENED",
            "economic_findings_created": False,
        },
        "resolution": {
            "permutations": 8192,
            "alpha_familywise": 0.05,
            "minimum_attainable_p": 1.0 / 8193.0,
            "approximate_alpha_monte_carlo_se": math.sqrt(0.05 * 0.95 / 8193.0),
            "resolution_qualified": True,
        },
        "trading_authority": False,
    }
    root_bytes = pretty_json(root_receipt)
    write_file(output_dir / "protocol_root_receipt.json", root_bytes)
    build_receipt = {
        "schema": "FIN_OPEN_01_BUILD_RECEIPT_V1",
        "protocol_id": "FIN-OPEN-01",
        "status": "PROTOCOL_QUALIFIED",
        "protocol_root_sha256": protocol_root_sha256,
        "rebuild_identity": "DETERMINISTIC_OUTPUT_EXPECTED",
        "outcome_inspection": "FORBIDDEN",
        "financial_development_outcomes": "FROZEN_UNOPENED",
        "financial_validation": "FROZEN_UNOPENED",
        "science_confirmation": "FROZEN_UNOPENED",
        "real_outcome_files_read": False,
        "substantive_obs_open_03_files_read": False,
        "output_file_count": len(generated) + 3,
    }
    write_file(output_dir / "build_receipt.json", pretty_json(build_receipt))
    return root_receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--study-root", required=True, type=Path)
    parser.add_argument("--authority-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    build_seal(args.study_root.resolve(), args.authority_root.resolve(), args.output_dir.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
