"""Capture E4 audit/contract/seal JSON omitted from the final legacy seal.

This oversight supplement does not alter or reinterpret the scientific seal.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ledgerd.core import Ledger
from ledgerd.identity import strict_json

HERE = Path(__file__).resolve().parents[1]
WORKSPACE = Path(r"C:\Users\shuga\.codex\worktrees\e4-0-contract-work\clean-rust")
BASE = WORKSPACE / "experiments/fas-frozen-observer-bundle-engineering-v01"
STORE = HERE / ".kammi-dev/e4-import"
PRIOR = HERE / "acceptance/e4-0/merkle-import-v1.json"
AUDIT = HERE / "acceptance/e4-0/legacy-flat-verification-v1.json"
OUTPUT = HERE / "acceptance/e4-0/history-supplement-v1.json"


def request(label: str) -> str:
    return "e4-supplement-" + hashlib.sha256(label.encode("utf-8")).hexdigest()


def candidates() -> list[Path]:
    paths: list[Path] = []
    for folder in sorted((BASE / "audits").glob("e4-0*")):
        if folder.is_dir():
            paths.extend(folder.rglob("*.json"))
        elif folder.suffix == ".json":
            paths.append(folder)
    for folder in ("contracts", "seals"):
        paths.extend((BASE / folder).glob("e4-0*.json"))
    return sorted(set(paths), key=lambda path: path.relative_to(WORKSPACE).as_posix())


def main() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    if audit["status"] != "PASS":
        raise ValueError("legacy seal audit missing")
    ledger = Ledger(STORE)
    legacy = strict_json(ledger.cas.get("sha256:" + audit["seal_file_sha256"]))
    sealed_paths = {entry["path"].casefold() for entry in legacy["entries"]}
    sealed_paths.update({
        "experiments/fas-frozen-observer-bundle-engineering-v01/contracts/e4-0-contract-v16-v09-final.json",
        "experiments/fas-frozen-observer-bundle-engineering-v01/seals/e4-0-contract-v16-v09-seal.json",
    })
    entries: list[dict] = []
    for source in candidates():
        resolved = source.resolve()
        if not resolved.is_relative_to(WORKSPACE.resolve()):
            raise ValueError("supplemental path escapes workspace")
        relative = source.relative_to(WORKSPACE).as_posix()
        if relative.casefold() in sealed_paths:
            continue
        artifact, _ = ledger.register_file(
            source, kind="legacy-e4-history-supplement",
            media_type="application/json", schema_id="legacy-unqualified-json-v1",
            actor="chief-kammi", request_id=request(relative),
        )
        after = hashlib.sha256(source.read_bytes()).hexdigest()
        if artifact[7:] != after:
            raise ValueError("source changed during supplemental capture")
        entries.append({
            "path": relative,
            "artifact": artifact,
            "bytes": source.stat().st_size,
        })
    root, _ = ledger.create_seal(
        sorted({entry["artifact"] for entry in entries}),
        [prior["successor_root"]], "chief-kammi", request("supplemental-seal"),
    )
    report = {
        "schema": "KAMMI_E4_HISTORY_SUPPLEMENT_V1",
        "status": "CAPTURED_NOT_LEGACY_SCIENTIFIC_SEAL",
        "parent_merkle_root": prior["successor_root"],
        "supplement_root": root,
        "source_path_count": len(entries),
        "unique_direct_objects": len({entry["artifact"] for entry in entries}),
        "verified_total_closure": len(ledger.verify_seal(root)),
        "entries": entries,
        "projection": ledger.status(),
    }
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"paths": len(entries), "root": root, "closure": report["verified_total_closure"]}))


if __name__ == "__main__":
    main()
