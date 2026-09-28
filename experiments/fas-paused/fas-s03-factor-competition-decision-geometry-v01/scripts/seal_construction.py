from __future__ import annotations

import hashlib
import json
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
FILES = (
    "README.md",
    "S03-PROTOCOL.md",
    "contracts/analysis-contract-v01.json",
    "contracts/parent-binding-v01.json",
    "contracts/authorization-v01.json",
    "scripts/analyze_s03.py",
    "scripts/seal_construction.py",
)


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb", buffering=1024 * 1024) as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_root(rows: list[dict]) -> str:
    body = "".join(f'{row["path"]} {row["sha256"]}\n' for row in sorted(rows, key=lambda x: x["path"].casefold()))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def main() -> None:
    rows = []
    for relative in FILES:
        path = PROJECT / relative
        if not path.is_file():
            raise SystemExit(f"Missing construction file: {relative}")
        rows.append({"path": relative.replace("\\", "/"), "sha256": sha_file(path)})
    seal = {
        "seal_id": "FAS_S03_CONSTRUCTION_V01",
        "experiment_id": "fas-s03-factor-competition-decision-geometry-v01",
        "files": rows,
        "root_sha256": canonical_root(rows),
        "model_contact_authorized": False,
        "probe_fitting_authorized": False,
        "significance_testing_authorized": False,
        "adaptive_mechanisms_authorized": False,
    }
    target = PROJECT / "seals" / "construction-seal-v01.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(seal, sort_keys=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"S03_CONSTRUCTION_SEALED root={seal['root_sha256']}")


if __name__ == "__main__":
    main()
