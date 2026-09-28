from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(r"C:\rd-c\selective-cognition-action-region-program\experiment-012")
CONSTRUCTION = ROOT / "bank" / "construction-01"
MANIFEST_PATH = CONSTRUCTION / "feasibility-input-manifest-v1.2.json"
AUDIT_PATH = CONSTRUCTION / "feasibility-audit-v1.json"
LOCK_PATH = CONSTRUCTION / "family-design-lock-v1.2.json"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def hash_tree_files(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.rglob("*")
        if path.is_file() and ".git" not in path.parts and "target" not in path.parts
        and "__pycache__" not in path.parts and path.suffix != ".pyc"
    )


def write_once(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError(f"refusing to overwrite frozen input: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    if LOCK_PATH.exists() or MANIFEST_PATH.exists():
        raise SystemExit("v1.2 manifest or lock already exists; refusing to rewrite frozen artifacts")
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    if audit.get("state") != "OFFLINE_FEASIBILITY_AUDIT_PASS":
        raise RuntimeError("offline feasibility audit has not passed")
    if audit.get("model_contact_authorized") is not False or audit.get("scored_task_frames_created") is not False:
        raise RuntimeError("audit boundary allows an invalid phase transition")

    input_roots = [
        CONSTRUCTION / "feasibility",
        CONSTRUCTION / "task-harnesses",
        CONSTRUCTION / "source" / "repositories",
        ROOT / "scripts",
        ROOT / "amendments",
    ]
    input_files: set[Path] = set()
    for directory in input_roots:
        input_files.update(hash_tree_files(directory))
    input_files.update({
        ROOT / "PROTOCOL.md",
        ROOT / "channel-contract-v0.json",
        ROOT / "observer-frame-projection-v0.md",
        ROOT / "freeze_protocol_v0_3.py",
        ROOT / "freeze_bank_design_v1_1_e012.py",
        ROOT / "protocol-lock-v0.3.json",
        ROOT / "bank-construction-plan-v1.1.md",
        ROOT / "bank-construction-plan-v1.2.md",
        CONSTRUCTION / "family-design-v1.1.json",
        CONSTRUCTION / "family-design-lock-v1.json",
        CONSTRUCTION / "family-design-lock-v1.1.json",
        CONSTRUCTION / "repository-source-inventory.json",
        AUDIT_PATH,
        CONSTRUCTION / "repository-source-audit-v1.json",
        Path(__file__),
    })
    missing = sorted(str(path) for path in input_files if not path.is_file())
    if missing:
        raise FileNotFoundError("missing v1.2 lock inputs: " + ", ".join(missing))

    files = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(input_files, key=lambda item: item.relative_to(ROOT).as_posix())
    ]
    manifest = {
        "schema_version": 1,
        "state": "FROZEN_FEASIBILITY_INPUTS",
        "hash_algorithm": "sha256",
        "files": files,
    }
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_bytes(manifest_bytes)

    amendment_a01_md = ROOT / "amendments" / "bank-amendment-01.md"
    amendment_a01_json = ROOT / "amendments" / "bank-amendment-01.json"
    amendment_a02_md = ROOT / "amendments" / "bank-amendment-02.md"
    amendment_a02_json = ROOT / "amendments" / "bank-amendment-02.json"
    lock = {
        "schema_version": 1,
        "state": "FROZEN_BEFORE_SCORED_TASK_FIXTURES",
        "model_contact_authorized": False,
        "scored_task_frames_created": False,
        "effective_bank_plan_version": "1.2",
        "bank_amendments": [
            {"id": "E012-BANK-A01", "markdown_sha256": sha256_file(amendment_a01_md),
             "json_sha256": sha256_file(amendment_a01_json)},
            {"id": "E012-BANK-A02", "markdown_sha256": sha256_file(amendment_a02_md),
             "json_sha256": sha256_file(amendment_a02_json)},
        ],
        "sha256": {
            "effective_protocol_lock": sha256_file(ROOT / "protocol-lock-v0.3.json"),
            "protocol_source": sha256_file(ROOT / "PROTOCOL.md"),
            "channel_contract": sha256_file(ROOT / "channel-contract-v0.json"),
            "observer_frame_projection": sha256_file(ROOT / "observer-frame-projection-v0.md"),
            "base_bank_design_lock": sha256_file(CONSTRUCTION / "family-design-lock-v1.json"),
            "prior_bank_design_lock_v1_1": sha256_file(CONSTRUCTION / "family-design-lock-v1.1.json"),
            "effective_bank_plan": sha256_file(ROOT / "bank-construction-plan-v1.2.md"),
            "effective_family_design": sha256_file(CONSTRUCTION / "family-design-v1.1.json"),
            "source_inventory": sha256_file(CONSTRUCTION / "repository-source-inventory.json"),
            "feasibility_audit": sha256_file(AUDIT_PATH),
            "repository_source_audit": sha256_file(CONSTRUCTION / "repository-source-audit-v1.json"),
            "feasibility_input_manifest": sha256_bytes(manifest_bytes),
            "feasibility_freezer_source": sha256_file(Path(__file__)),
        },
        "input_manifest_path": "bank/construction-01/feasibility-input-manifest-v1.2.json",
        "input_file_count": len(files),
        "selected_family_count": len(audit["families"]),
        "candidate_case_rows": audit["candidate_case_rows"],
        "baseline_case_rows": audit["baseline_case_rows"],
        "failed_feasibility_trials_preserved": audit["preserved_failed_trials"],
    }
    write_once(LOCK_PATH, lock)
    print(json.dumps({"lock": str(LOCK_PATH), "state": lock["state"],
                      "input_files": len(files), "manifest_sha256": sha256_bytes(manifest_bytes)}, indent=2))


if __name__ == "__main__":
    main()
