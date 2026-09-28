"""Independent acceptance auditor: no production policy/seal/release imports."""
import hashlib
import json
import os
from pathlib import Path

import jcs
from scripts.independent_verify import verify_store, digest
from scripts.gate_evidence import GATE_TESTS, GATE_REPORTS

HERE = Path(__file__).resolve().parents[1]


def independently_hash_source():
    files = []
    excluded = {".venv", ".kammi-dev", "vendor", "__pycache__", "acceptance", "dist", "build"}
    for directory, dirs, names in os.walk(HERE, followlinks=False):
        dirs[:] = [d for d in dirs if d not in excluded and not d.endswith(".egg-info")]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink() or path.suffix not in {".py", ".rs", ".toml", ".lock", ".md", ".json", ".txt"}:
                continue
            files.append({"path": path.relative_to(HERE).as_posix(), "artifact_id": digest(path.read_bytes()), "bytes": path.stat().st_size})
    return digest(jcs.canonicalize({"schema": "KAMMI_SOURCE_MANIFEST_V1", "files": sorted(files, key=lambda row: row["path"])}))


def verify_legacy(root):
    def read(identity):
        path = root / "objects/sha256" / identity[7:9] / identity[9:]
        raw = path.read_bytes()
        assert digest(raw) == identity
        return raw
    legacy = json.loads(read("sha256:0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c"))
    rows = []
    for entry in legacy["entries"]:
        raw = read("sha256:" + entry["sha256"])
        assert len(raw) == entry["bytes"]
        rows.append(f"{entry['artifact_id']}\t{entry['path']}\t{entry['bytes']}\t{entry['sha256']}\n")
    flat_root = hashlib.sha256("".join(rows).encode()).hexdigest()
    assert len(rows) == 447 and flat_root == "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"
    return {"status": "PASS", "entries": len(rows), "unique_original_objects": len({e["sha256"] for e in legacy["entries"]}),
            "original_flat_root": flat_root, "contract_identity": "sha256:21fc77d5a288b9adef995d88f089890235f8dcb2fbc3c9e452725bb67892a22f"}


def audit(run_directory):
    load = lambda name: json.loads((run_directory / name).read_bytes())
    suite_path = run_directory / "ENDSTATE-ACCEPTANCE-v1.json"
    suite = json.loads(suite_path.read_bytes())
    tests = load("tests.json")
    assert tests["status"] == "PASS" and tests["source_unchanged"]
    assert independently_hash_source() == suite["source_root"] == tests["source_root"]
    assert tests["runtime_identity"] == suite["runtime_identity"]
    manifest = load("ENDSTATE-SOURCE-MANIFEST-v1.json")
    assert digest(jcs.canonicalize(manifest)) == suite["source_root"]
    assets = json.loads((HERE / "runtime/ASSET-MANIFEST-v1.json").read_bytes())
    for entry in assets["files"]:
        path = HERE / "vendor/runtime-v1" / entry["path"]
        with path.open("rb") as stream:
            assert hashlib.file_digest(stream, "sha256").hexdigest() == entry["sha256"]
        assert path.stat().st_size == entry["bytes"]
    passed = {case["test"] for case in tests["cases"] if case["status"] == "PASS"}
    assert len(passed) == tests["test_count"] and all(s["status"] == "PASS" for s in tests["subtests"])
    reports = {}
    for name, reference in suite["reports"].items():
        path = run_directory / reference["path"]
        assert digest(path.read_bytes()) == reference["artifact_id"]
        report = json.loads(path.read_bytes())
        assert report["status"] == "PASS"
        reports[name] = report
    assert reports["e4"]["entries"] == 447 and reports["e4"]["supplement_closure"] == 493
    assert reports["memory"]["records"] == 1211 and reports["memory"]["searches"] == 90
    assert reports["custody"]["lease_requests"] == 512 and reports["custody"]["stale_rejections"] == 64
    assert len(reports["collision"]["rounds"]) == 8
    assert all(r["granted"] == 1 and r["denied"] == 3 and r["stale_executor_rejected"] for r in reports["collision"]["rounds"])
    assert reports["http_cleanroom"]["distinct_daemon_process"] and reports["http_cleanroom"]["controlled_crash_exit"] == 91
    assert set(suite["gates"]) == set(GATE_TESTS)
    for gate, evidence in suite["gates"].items():
        assert evidence["status"] == "PASS" and evidence["evidence"]
        for required in GATE_TESTS[gate]:
            assert any(required in test for test in passed), (gate, required)
        for report in GATE_REPORTS.get(gate, []):
            assert suite["reports"][report]["artifact_id"] in evidence["evidence"]
    stores = {
        "e4": HERE / ".kammi-dev/e4-import", "cleanroom": Path(reports["cleanroom"]["fixture_store"]),
        "http_cleanroom": Path(reports["http_cleanroom"]["fixture_store"]),
        "custody": Path(suite["fixture_stores"]["custody"]), "memory": Path(suite["fixture_stores"]["memory"]),
        "collision": Path(reports["collision"]["fixture_store"]),
    }
    reconstructed = {name: verify_store(path) for name, path in stores.items()}
    return {"schema": "KAMMI_ENDSTATE_INDEPENDENT_AUDIT_V1", "status": "PASS",
        "source_root": suite["source_root"], "runtime_identity": suite["runtime_identity"],
        "acceptance_suite_root": digest(suite_path.read_bytes()), "gates_verified": sorted(suite["gates"]),
        "executed_tests": len(passed), "subtests": len(tests["subtests"]), "runtime_assets_verified": len(assets["files"]),
        "authority_reconstruction": reconstructed, "legacy_independent": verify_legacy(stores["e4"]),
        "independence": "Separate process; stdlib/JCS/Ed25519 checks; no production decision functions imported.",
        "limitations": suite["limitations"]}


if __name__ == "__main__":
    import sys
    directory = Path(sys.argv[1]).resolve()
    report = audit(directory)
    (directory / "ENDSTATE-INDEPENDENT-AUDIT-v1.json").write_bytes(jcs.canonicalize(report))
    print(json.dumps({"status": "PASS", "gates": len(report["gates_verified"])}), flush=True)
