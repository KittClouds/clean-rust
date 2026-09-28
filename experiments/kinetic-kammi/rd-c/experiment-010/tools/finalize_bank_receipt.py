from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BANK = ROOT / "tasks" / "heldout-bank-v1"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def tree_hash(directory: Path, excluded: set[str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in directory.rglob("*") if item.is_file() and item.name not in excluded):
        digest.update(path.relative_to(directory).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def main() -> None:
    candidate_path = BANK / "candidate-lock.json"
    receipt_path = BANK / "bank-build-receipt.json"
    freeze_path = BANK / "bank-freeze.json"
    candidate = read_json(candidate_path)
    receipt = read_json(receipt_path)
    freeze = read_json(freeze_path)
    if freeze.get("state") != "FROZEN_BEFORE_MODEL_CONTACT":
        raise SystemExit("bank must already be frozen before receipt amendment")
    before_receipt_sha = sha256(receipt_path.read_bytes())
    receipt["source_repository_revision"] = candidate["repository_revision"]
    amended_families = []
    for family, family_lock in candidate["families"].items():
        family_receipts = receipt["completion_checks"][family]
        family_receipts["test_filter"] = family_lock["test_filter"]
        for variant in family_lock["variants"]:
            record = family_receipts[variant]
            if "completion_log" not in record or "completion_log_sha256" not in record:
                raise SystemExit(f"missing original test log receipt for {family}/{variant}")
            record["log"] = record["completion_log"]
            record["log_sha256"] = record["completion_log_sha256"]
        amended_families.append(family)
    write_json(receipt_path, receipt)
    amendment = {
        "schema_version": 1,
        "type": "PRECONTACT_RECEIPT_SCHEMA_ADAPTATION",
        "reason": "The E009 frozen-receipt reader expects repository_revision, family test_filter, and log/log_sha256 aliases. This amendment adds those receipt fields from the unchanged candidate lock and completion logs; it does not change frames, patches, tests, pass/fail outcomes, or labels.",
        "amended_families": amended_families,
        "receipt_sha256_before": before_receipt_sha,
        "receipt_sha256_after": sha256(receipt_path.read_bytes()),
        "candidate_lock_sha256": sha256(candidate_path.read_bytes()),
    }
    amendment_path = BANK / "receipt-amendment.json"
    if amendment_path.exists():
        raise SystemExit("receipt amendment already exists")
    write_json(amendment_path, amendment)
    freeze["sha256"]["bank_build_receipt"] = sha256(receipt_path.read_bytes())
    freeze["sha256"]["receipt_amendment"] = sha256(amendment_path.read_bytes())
    freeze["bank_tree_sha256_excluding_freeze"] = tree_hash(BANK, {"bank-freeze.json"})
    freeze["receipt_schema_amended_before_model_contact"] = True
    write_json(freeze_path, freeze)
    print(json.dumps({"receipt_sha256": sha256(receipt_path.read_bytes()), "bank_tree_sha256": freeze["bank_tree_sha256_excluding_freeze"], "amended_families": amended_families}, indent=2))


if __name__ == "__main__":
    main()
