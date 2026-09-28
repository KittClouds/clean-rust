"""Feature-blind, family-balanced selection for the shared v0.8N basis."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08n/phase-a-v01-contract.json"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    contract = read_json(CONTRACT)
    contract_hash = sha256_file(CONTRACT)
    certificates_path = args.run / "train-contrast-certificates.jsonl"
    certificates = read_jsonl(certificates_path)
    expected = int(contract["generator"]["training_neighborhood_capacity"])
    if len(certificates) != expected or any(row.get("partition") != "train" for row in certificates):
        raise RuntimeError("training certificate scope/count drift")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in certificates:
        family = str(row["world_family_id"])
        anchor_id = str(row["anchor_id"])
        rank_input = f"jev-v08n-selection-v01|{contract_hash}|{family}|{anchor_id}".encode("utf-8")
        by_family[family].append({
            "anchor_id": anchor_id,
            "family_id": family,
            "certificate_hash": row["certificate_hash"],
            "episode_ids": row["episode_ids"],
            "state_signature": row["state_signature"],
            "schema_signature": row["schema_signature"],
            "rank_sha256": hashlib.sha256(rank_input).hexdigest(),
        })
    families = sorted(by_family)
    if len(families) != int(contract["generator"]["training_family_count"]):
        raise RuntimeError("training family count drift")
    total = 5_000
    base, remainder = divmod(total, len(families))
    quotas = {family: base + (index < remainder) for index, family in enumerate(families)}
    selected: list[dict[str, Any]] = []
    for family in families:
        rows = sorted(by_family[family], key=lambda row: (row["rank_sha256"], row["anchor_id"]))
        if len(rows) < quotas[family]:
            raise RuntimeError(f"family capacity below quota: {family}")
        selected.extend(rows[:quotas[family]])
    selected.sort(key=lambda row: (row["family_id"], row["rank_sha256"], row["anchor_id"]))
    if len(selected) != total or len({row["anchor_id"] for row in selected}) != total:
        raise RuntimeError("selected neighborhood identity/count drift")

    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    selection_contract = {
        "protocol": "jev-information-density/v0.8n-shared-selection-v01",
        "phase_identity": "v0.8N-base-v01",
        "parent_contract_sha256": contract_hash,
        "selection_algorithm": "sha256(jev-v08n-selection-v01|parent_contract_sha256|world_family_id|anchor_id), fixed balanced quotas",
        "selected_count": total,
        "quotas": quotas,
        "uses_features": False,
        "uses_evaluation": False,
        "source_certificate_sha256": sha256_file(certificates_path),
    }
    selection_contract_path = output / "selection-contract.json"
    selected_path = output / "selected-training-neighborhoods.jsonl"
    receipt_path = output / "selection-receipt.json"
    if any(path.exists() for path in (selection_contract_path, selected_path, receipt_path)):
        raise RuntimeError("refusing overwrite of selection artifacts")
    write_json(selection_contract_path, selection_contract)
    write_jsonl(selected_path, selected)
    receipt = {
        "status": "V08N_N0_FEATURE_FREE_SELECTION_PASS",
        "phase_identity": "v0.8N-base-v01",
        "selection_contract_sha256": sha256_file(selection_contract_path),
        "selected_manifest_sha256": sha256_file(selected_path),
        "selected_count": len(selected),
        "family_counts": {family: sum(row["family_id"] == family for row in selected) for family in families},
        "source_certificate_sha256": sha256_file(certificates_path),
        "model_contact": False,
        "feature_extraction": False,
        "training": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
    }
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
