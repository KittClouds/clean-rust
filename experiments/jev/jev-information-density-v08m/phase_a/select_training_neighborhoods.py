"""Select the fixed feature-free v0.8M training neighborhood sample.

Selection is deliberately metadata-only.  It uses a stable hash rank within
each generated world family and fixed per-family quotas; no LFM features,
evaluation artifacts, or model outputs are read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
CONTRACT = ROOT / "experiments/jev-information-density-v08m/phase_a/phase-a-v01-contract.json"


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    contract = read_json(CONTRACT)
    contract_hash = sha256_file(CONTRACT)
    require(contract["phase_a_identity"] == "phase-a-v01-clean", "phase identity drift")
    require(contract["phase_boundaries"]["phase_a0_model_contact"] is False, "A0 model boundary drift")
    require(contract["phase_boundaries"]["protected_evaluation_bodies_opened"] is False, "protected boundary drift")

    certificates_path = args.run / "train-contrast-certificates.jsonl"
    certificates = read_jsonl(certificates_path)
    expected = int(contract["generator"]["training_neighborhood_capacity"])
    require(len(certificates) == expected, f"training neighborhood count drift: {len(certificates)}")
    require(all(row.get("partition") == "train" for row in certificates), "non-training certificate encountered")

    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in certificates:
        family = str(row["world_family_id"])
        anchor_id = str(row["anchor_id"])
        rank_payload = f"jev-v08m-selection-v01|{contract_hash}|{family}|{anchor_id}".encode("utf-8")
        by_family[family].append({
            "anchor_id": anchor_id,
            "family_id": family,
            "certificate_hash": row["certificate_hash"],
            "episode_ids": row["episode_ids"],
            "state_signature": row["state_signature"],
            "schema_signature": row["schema_signature"],
            "rank_sha256": sha256_bytes(rank_payload),
        })

    families = sorted(by_family)
    require(len(families) == int(contract["generator"]["training_family_count"]), "training family count drift")
    total = 5_000
    base, remainder = divmod(total, len(families))
    quotas = {family: base + (index < remainder) for index, family in enumerate(families)}

    selected: list[dict[str, Any]] = []
    for family in families:
        rows = sorted(by_family[family], key=lambda row: (row["rank_sha256"], row["anchor_id"]))
        require(len(rows) >= quotas[family], f"family capacity below quota: {family}")
        selected.extend(rows[: quotas[family]])
    selected.sort(key=lambda row: (row["family_id"], row["rank_sha256"], row["anchor_id"]))
    require(len(selected) == total, "selected neighborhood count drift")
    require(len({row["anchor_id"] for row in selected}) == total, "duplicate selected neighborhood")

    selection_contract = {
        "protocol": "jev-information-density/v0.8m-phase-a-selection",
        "phase_a_identity": contract["phase_a_identity"],
        "parent_contract_sha256": contract_hash,
        "selection_identity": "training-neighborhoods-v01",
        "source_scope": "fresh generated training certificates only",
        "model_contact": False,
        "feature_extraction": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
        "selection_algorithm": {
            "rank": "sha256(jev-v08m-selection-v01|parent_contract_sha256|world_family_id|anchor_id)",
            "allocation": "fixed balanced quota per sorted world_family_id",
            "total": total,
            "quotas": quotas,
            "uses_features": False,
            "uses_evaluation": False,
        },
        "source": {
            "run": str(args.run),
            "certificate_path": str(certificates_path),
            "certificate_sha256": sha256_file(certificates_path),
            "certificate_count": len(certificates),
        },
    }
    selection_contract_path = args.output / "selection-contract.json"
    selected_path = args.output / "selected-training-neighborhoods.jsonl"
    receipt_path = args.output / "selection-receipt.json"
    for path in (selection_contract_path, selected_path, receipt_path):
        require(not path.exists(), f"refusing overwrite: {path}")

    write_json(selection_contract_path, selection_contract)
    write_jsonl(selected_path, selected)
    receipt = {
        "status": "PHASE_A0_TRAINING_NEIGHBORHOOD_SELECTION_PASS",
        "protocol": selection_contract["protocol"],
        "phase_a_identity": selection_contract["phase_a_identity"],
        "selection_contract_sha256": sha256_file(selection_contract_path),
        "selected_manifest_sha256": sha256_file(selected_path),
        "selected_count": len(selected),
        "family_counts": {family: sum(row["family_id"] == family for row in selected) for family in families},
        "selected_anchor_ids_sha256": sha256_bytes("\n".join(row["anchor_id"] for row in selected).encode("utf-8")),
        "source_certificate_sha256": sha256_file(certificates_path),
        "outcome_blind": True,
        "model_contact": False,
        "feature_extraction": False,
        "evaluation_inference": False,
        "protected_evaluation_bodies_opened": False,
        "phoenix_access": False,
    }
    write_json(receipt_path, receipt)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
