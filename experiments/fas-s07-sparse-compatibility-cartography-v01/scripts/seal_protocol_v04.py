from __future__ import annotations

import json

from s07_common import PROJECT, PROTOCOL_SEAL_V03, root_simple, sha256_file


def main() -> None:
    seal_path = PROJECT / "seals" / "protocol-seal-v04.json"
    if seal_path.exists():
        raise SystemExit("Refusing to overwrite the S07 protocol v04 seal")
    previous = json.loads(PROTOCOL_SEAL_V03.read_text(encoding="utf-8"))
    if root_simple(previous.get("entries", [])) != previous.get("root_sha256"):
        raise SystemExit("Historical S07 protocol v03 seal is corrupt")
    paths = [PROJECT / "FAS-S07-PROTOCOL.md"]
    paths.extend([
        PROJECT / "seals" / "preflight-verifier-correction-v01.json",
        PROJECT / "seals" / "parent-binding-correction-v01.json",
        PROJECT / "seals" / "semantic-target-mapping-correction-v01.json",
        PROJECT / "seals" / "s01-source-row-identity-correction-v01.json",
    ])
    paths.extend(sorted((PROJECT / "contracts").glob("*.json")))
    paths.extend(sorted((PROJECT / "scripts").glob("*.py")))
    entries = []
    for path in paths:
        entries.append({"path": path.relative_to(PROJECT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda item: item["path"].casefold())
    seal = {
        "seal_id": "FAS_S07_PROTOCOL_SEAL_V04",
        "status": "SEALED_POST_TRAINING_METADATA_CORRECTION",
        "entries": entries,
        "root_sha256": root_simple(entries),
        "supersedes_protocol_root_sha256": previous["root_sha256"],
        "supersession_scope": "interpret S01 candidate-position labels through the sealed candidate-to-state map before gate comparison; training contract and sources unchanged",
        "training_compatible_prior_protocol_roots": ["da952f0368811bf31688a91c9c69f1a01e2305cf6aabed3c0e380024de08abd4"],
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "sae_fitting_authorized": False,
        "evaluation_gate_authorized": True,
    }
    seal_path.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S07_PROTOCOL_V04_SEALED root={seal['root_sha256']} entries={len(entries)} supersedes={previous['root_sha256']}")


if __name__ == "__main__":
    main()
