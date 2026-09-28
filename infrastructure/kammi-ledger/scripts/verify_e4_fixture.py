"""Read-only legacy E4-0 closure receipt. This is an external fixture adapter."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.legacy_flat import verify_flat_seal

WORKSPACE = Path(
    r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust"
)
BASE = WORKSPACE / "experiments/fas-frozen-observer-bundle-engineering-v01"
CONTRACT = BASE / "contracts/e4-0-contract-v16-v09-final.json"
SEAL = BASE / "seals/e4-0-contract-v16-v09-seal.json"
CONTRACT_SHA = "21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"
SEAL_SHA = "0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c"
ROOT_SHA = "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"


def main() -> None:
    contract_sha = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    if contract_sha != CONTRACT_SHA:
        raise ValueError("fixture contract hash mismatch")
    report = verify_flat_seal(
        WORKSPACE, SEAL,
        expected_seal_sha256=SEAL_SHA,
        expected_root_sha256=ROOT_SHA,
    )
    report["contract_sha256"] = contract_sha
    report["fixture_workspace"] = str(WORKSPACE)
    output = Path(__file__).resolve().parents[1] / "acceptance/e4-0/legacy-flat-verification-v1.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "verified_entries": report["verified_entries"], "declared_entries": report["declared_entries"], "report": str(output)}))


if __name__ == "__main__":
    main()

