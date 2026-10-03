from __future__ import annotations

import json

from s07_common import PROJECT, PROTOCOL_SEAL_V01, root_simple, sha256_file


def main() -> None:
    seal_path = PROJECT / "seals" / "protocol-seal-v02.json"
    if seal_path.exists():
        raise SystemExit("Refusing to overwrite the S07 protocol v02 seal")
    previous = json.loads(PROTOCOL_SEAL_V01.read_text(encoding="utf-8"))
    if root_simple(previous.get("entries", [])) != previous.get("root_sha256"):
        raise SystemExit("Historical S07 protocol v01 seal is corrupt")
    paths = [PROJECT / "FAS-S07-PROTOCOL.md", PROJECT / "seals" / "preflight-verifier-correction-v01.json"]
    paths.extend(sorted((PROJECT / "contracts").glob("*.json")))
    paths.extend(sorted((PROJECT / "scripts").glob("*.py")))
    entries = []
    for path in paths:
        entries.append({"path": path.relative_to(PROJECT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    entries.sort(key=lambda item: item["path"].casefold())
    seal = {
        "seal_id": "FAS_S07_PROTOCOL_SEAL_V02",
        "status": "SEALED_PRE_FIT",
        "entries": entries,
        "root_sha256": root_simple(entries),
        "supersedes_protocol_root_sha256": previous["root_sha256"],
        "supersession_scope": "correct ordinal sorting for the already-sealed S01 parent inventory; scientific contracts unchanged",
        "model_contact": False,
        "feature_extraction": False,
        "probe_fitting": False,
        "sae_fitting_authorized": True,
    }
    seal_path.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S07_PROTOCOL_V02_SEALED root={seal['root_sha256']} entries={len(entries)} supersedes={previous['root_sha256']}")


if __name__ == "__main__":
    main()
