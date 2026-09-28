from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
INVENTORY = CONSTRUCTION / "repository-source-inventory.json"
OUTPUT = CONSTRUCTION / "repository-source-audit-v1.json"
EXPECTED_TARGET_ROOT = Path(r"D:\rdc-e012-target")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main() -> None:
    if OUTPUT.exists():
        raise SystemExit(f"refusing to overwrite repository source audit: {OUTPUT}")
    inventory = json.loads(INVENTORY.read_text(encoding="utf-8"))
    previous = {
        repo for values in inventory["previous_evaluation_repositories"].values() for repo in values
    }
    rows = []
    for entry in inventory["selected_repositories"]:
        name = entry["repository_id"]
        source = CONSTRUCTION / "repositories" / name
        archive = CONSTRUCTION / entry["archive_path"]
        if git(source, "rev-parse", "HEAD") != entry["commit"]:
            raise RuntimeError(f"{name}: checkout commit drift")
        if git(source, "status", "--porcelain"):
            raise RuntimeError(f"{name}: source checkout is dirty")
        if sha256_file(archive) != entry["archive_sha256"]:
            raise RuntimeError(f"{name}: source archive hash drift")
        if sha256_file(source / "Cargo.toml") != entry["root_cargo_toml_sha256"]:
            raise RuntimeError(f"{name}: root Cargo.toml hash drift")
        if name in {"bytes", "clap"}:
            target = source / "target"
        else:
            target = CONSTRUCTION / "target" / "serde-json-harness"
        resolved_target = Path(os.path.realpath(target))
        if not str(resolved_target).lower().startswith(str(EXPECTED_TARGET_ROOT).lower()):
            raise RuntimeError(f"{name}: build target is not under D: ({resolved_target})")
        rows.append({
            "repository_id": name,
            "commit": entry["commit"],
            "release": entry["release"],
            "checkout_clean": True,
            "source_archive_sha256": entry["archive_sha256"],
            "root_cargo_toml_sha256": entry["root_cargo_toml_sha256"],
            "target_resolved_path": str(resolved_target),
            "target_on_D_drive": True,
            "new_evaluation_repository": name not in previous,
        })
    if len(rows) != 3 or any(not row["new_evaluation_repository"] for row in rows):
        raise RuntimeError("repository independence check failed")
    result = {
        "schema_version": 1,
        "state": "REPOSITORY_SOURCE_AUDIT_PASS",
        "model_contact_authorized": False,
        "repository_count": len(rows),
        "all_checkouts_clean": True,
        "all_targets_on_D_drive": True,
        "all_repositories_absent_from_E009_E010_E011": True,
        "repositories": rows,
    }
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"state": result["state"], "repositories": rows}, indent=2))


if __name__ == "__main__":
    main()
