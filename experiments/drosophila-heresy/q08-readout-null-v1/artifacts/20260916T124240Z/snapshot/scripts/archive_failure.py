"""Archive failed Q08 engineering evidence with explicit post-execution provenance."""

import datetime
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(path):
    with pathlib.Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    require(sys.flags.optimize == 0, "optimized Python forbidden")
    smoke = ROOT / "qualification/smoke-seed9200"
    summary = json.loads((smoke / "independent-summary.json").read_text())
    contract = json.loads((ROOT / "CONTRACT.json").read_text())
    require(summary["status"] == "SMOKE_CONSTRUCTOR_FAILED", "this archive is only for failed qualification")
    require(summary["events"] == 512 and summary["scientific_seed_bundles_used"] == 0, "scope drift")
    require(digest(ROOT / "PLAN.md") == contract["plan_sha256"], "frozen contract drift")
    for name, expected in summary["input_hashes"].items():
        require(digest(smoke / name) == expected, f"smoke input changed: {name}")
    binary = ROOT / "target/release/q08-readout-null-v1.exe"
    require(str(binary.resolve()).lower().startswith(
        "d:\\drosophila-heresy\\q08-readout-null-v1-target\\"
    ), "target drive drift")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "artifacts" / stamp
    out.mkdir(parents=True, exist_ok=False)
    snapshot = out / "snapshot"
    snapshot.mkdir()
    files = [ROOT / name for name in ["PLAN.md", "CONTRACT.json", "GEOMETRY.md", "RESULT.md", "NEXT.md",
                                     "Cargo.toml", "Cargo.lock", "smoke-config.json"]]
    files += sorted((ROOT / "src").rglob("*.rs"))
    files += sorted((ROOT / "scripts").glob("*.py"))
    files += sorted(path for path in (ROOT / "qualification").rglob("*") if path.is_file())
    hashes = {}
    for path in files:
        relative = path.relative_to(ROOT)
        target = snapshot / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        require(digest(target) == digest(path), f"snapshot differs: {relative}")
        hashes[str(relative)] = digest(target)
    shutil.copy2(binary, snapshot / binary.name)
    hashes[binary.name] = digest(snapshot / binary.name)
    require({str(path.relative_to(snapshot)) for path in snapshot.rglob("*") if path.is_file()}
            == set(hashes), "snapshot manifest incomplete")
    archive = {
        "protocol": "Q08-ReadoutNull-v1",
        "status": "BLOCKED_PRESEAL_CONSTRUCTOR_QUALIFICATION",
        "kind": "POST_EXECUTION_ENGINEERING_EVIDENCE_ARCHIVE",
        "source_and_binary_captured_before_execution": False,
        "contract_frozen_before_smoke": True,
        "created_utc": stamp,
        "fingerprints": hashes,
        "parent_dh08a_seal_sha256": contract["parent_dh08a_seal_sha256"],
        "qualification_seeds_used": [9200],
        "qualification_seeds_unopened": list(range(9201, 9206)),
        "scientific_seed_bundles_used": 0,
        "full_qualification_executed": False,
        "dh08b_measured_execution_authorized_by_qualification": False,
        "tests": {"rust_passed": 59, "rust_failed": 0, "rust_ignored": 9,
                  "clippy": "PASSED", "independent_receipt_tests_passed": 4},
        "events_failed": summary["events_failed"],
        "failure_counts": summary["failure_counts"],
        "python": sys.version,
        "interpreter_sha256": digest(sys.executable),
    }
    (out / "archive.json").write_text(json.dumps(archive, indent=2) + "\n")
    status = {key: archive[key] for key in ["protocol", "status", "qualification_seeds_used",
              "qualification_seeds_unopened", "scientific_seed_bundles_used", "full_qualification_executed"]}
    status["archive"] = str(out)
    status["archive_sha256"] = digest(out / "archive.json")
    (ROOT / "STATUS.json").write_text(json.dumps(status, indent=2) + "\n")
    print(json.dumps(status, indent=2))


if __name__ == "__main__":
    main()
