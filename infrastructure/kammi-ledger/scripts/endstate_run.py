"""Complete frozen-source qualification, independent audit and infrastructure seal."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from ledgerd.api import create_app
from ledgerd.core import Ledger
from ledgerd.identity import canonical, raw_id, strict_json
from ledgerd.release import GATES, HERE, architecture_identity, runtime_identity, source_manifest
from scripts.gate_evidence import GATE_TESTS, GATE_REPORTS
from scripts.scaling_report import run_scaling


def write(path, value):
    path.write_bytes(canonical(value))
    return raw_id(path.read_bytes())


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    reports = HERE / "acceptance/endstate" / ("qualified-" + stamp)
    fixtures = HERE / ".kammi-dev" / ("qualified-" + stamp)
    reports.mkdir(parents=True)
    fixtures.mkdir(parents=True)
    source, source_root = source_manifest()
    runtime, runtime_root = runtime_identity()
    write(reports / "ENDSTATE-SOURCE-MANIFEST-v1.json", source)
    write(reports / "START.json", {"source_root": source_root, "runtime_identity": runtime_root, "started_at": stamp})
    print(json.dumps({"report_directory": str(reports), "source_root": source_root}), flush=True)
    def command(name, argv):
        print("START " + name, flush=True)
        with (reports / (name + ".log")).open("w") as log:
            result = subprocess.run(argv, cwd=HERE, stdout=log, stderr=log)
        if result.returncode:
            write(reports / "STOP.json", {"status": "FAIL", "phase": name, "exit_code": result.returncode,
                "flight_state": "CLOSED_PENDING_ACCEPTANCE", "log": name + ".log"})
            raise RuntimeError("qualification failed; preserved " + str(reports / (name + ".log")))
        assert source_manifest()[1] == source_root, "source changed during qualification"
        print("PASS " + name, flush=True)
    command("tests", [sys.executable, "-m", "scripts.qualified_tests", str(reports / "tests.json")])
    rust_commands = [
        ["cargo", "fmt", "--manifest-path", "sdk/rust/Cargo.toml", "--check"],
        ["cargo", "clippy", "--manifest-path", "sdk/rust/Cargo.toml", "--target-dir", "G:/kammi-ledger-target", "--all-targets", "--", "-D", "warnings"],
        ["cargo", "test", "--manifest-path", "sdk/rust/Cargo.toml", "--target-dir", "G:/kammi-ledger-target"],
        ["cargo", "build", "--manifest-path", "sdk/rust/Cargo.toml", "--target-dir", "G:/kammi-ledger-target", "--release", "--bin", "kammi-client-smoke"],
    ]
    for index, argv in enumerate(rust_commands):
        command("rust-" + str(index), argv)
    rust_binary = HERE / ".kammi-dev/clients/rust/kammi-client-smoke.exe"
    rust = {"schema": "KAMMI_RUST_SDK_QUALIFICATION_V1", "status": "PASS", "target": "G:/kammi-ledger-target",
        "c_link": str(rust_binary), "binary_artifact_id": raw_id(rust_binary.read_bytes()),
        "rustc": subprocess.check_output(["rustc", "-Vv"], text=True), "commands": rust_commands,
        "cross_process_http_memory_trace": "test_external_clients.ExternalClientTests.test_python_cli_mcp_rust_and_phoenix_process"}
    write(reports / "rust.json", rust)
    stages = [("collision", "scripts.lease_collision", "collision.json"),
              ("memory", "scripts.memory_stress", "ENDSTATE-MEMORY-RETRIEVAL-v1.json"),
              ("custody", "scripts.custody_stress", "custody.json"),
              ("cleanroom", "scripts.cleanroom_replay", "ENDSTATE-CLEANROOM-REPLAY-v1.json"),
              ("http-cleanroom", "scripts.http_cleanroom", "http-cleanroom.json")]
    for name, module, output in stages:
        command(name, [sys.executable, "-m", module, str(fixtures / name), "--output", str(reports / output)])
    load = lambda name: strict_json((reports / name).read_bytes())
    cleanroom, http, memory, custody, collision = [load(name) for name in
        ("ENDSTATE-CLEANROOM-REPLAY-v1.json", "http-cleanroom.json", "ENDSTATE-MEMORY-RETRIEVAL-v1.json", "custody.json", "collision.json")]
    write(reports / "ENDSTATE-E4-RECONSTRUCTION-v1.json", {"schema": "KAMMI_ENDSTATE_E4_V1", **cleanroom["e4"]})
    write(reports / "ENDSTATE-REMOTE-WORKER-v1.json", {"schema": "KAMMI_ENDSTATE_REMOTE_V1", "status": "PASS",
        "core_receipt": cleanroom["remote_receipt"], "http_receipt": http["remote_receipt"],
        "adversarial_test_class": "test_remote_adversarial.RemoteAdversarialTests"})
    write(reports / "ENDSTATE-LEASE-COLLISION-v1.json", collision)
    print("START scaling", flush=True)
    scaling = run_scaling(fixtures / "scaling")
    write(reports / "scaling.json", scaling)
    write(reports / "ENDSTATE-STRESS-REPORT-v1.json", {"schema": "KAMMI_ENDSTATE_STRESS_V1", "status": "PASS",
        "custody": custody, "memory": memory, "collision": collision, "scaling": scaling})
    assert runtime_identity()[1] == runtime_root and source_manifest()[1] == source_root
    runtime_report = {"schema": "KAMMI_ENDSTATE_RUNTIME_V1", "status": "PASS", "identity": runtime,
        "runtime_identity": runtime_root, "source_root": source_root, "offline_cleanroom_environment": sys.executable,
        "asset_manifest": str(HERE / "runtime/ASSET-MANIFEST-v1.json"), "captured_assets": str(HERE / "vendor/runtime-v1"),
        "deployment": "Windows x86-64 / CPython 3.13; capi; one shared 256MiB Ladybug projection; two native threads"}
    write(reports / "ENDSTATE-RUNTIME-QUALIFICATION-v1.json", runtime_report)
    names = {"rust": "rust.json", "collision": "ENDSTATE-LEASE-COLLISION-v1.json", "memory": "ENDSTATE-MEMORY-RETRIEVAL-v1.json",
        "custody": "custody.json", "cleanroom": "ENDSTATE-CLEANROOM-REPLAY-v1.json", "http_cleanroom": "http-cleanroom.json",
        "e4": "ENDSTATE-E4-RECONSTRUCTION-v1.json", "remote": "ENDSTATE-REMOTE-WORKER-v1.json", "scaling": "scaling.json"}
    references = {name: {"path": path, "artifact_id": raw_id((reports / path).read_bytes())} for name, path in names.items()}
    tests = load("tests.json")
    passing = {case["test"] for case in tests["cases"] if case["status"] == "PASS"}
    test_id = raw_id((reports / "tests.json").read_bytes())
    proofs = {}
    assert set(GATE_TESTS) == set(GATES)
    for gate in GATES:
        executed = []
        for predicate in GATE_TESTS[gate]:
            matches = sorted(test for test in passing if predicate in test)
            assert matches, (gate, predicate)
            executed.extend(matches)
        evidence = [test_id] if executed else []
        evidence.extend(references[name]["artifact_id"] for name in GATE_REPORTS.get(gate, []))
        proofs[gate] = {"status": "PASS", "evidence": sorted(set(evidence)), "executed_tests": sorted(set(executed))}
    limitations = ["Trusted local Windows account and loopback clients; direct filesystem access is outside guarded operation.",
        "Signed workers are trusted attestations; no hostile-code sandbox or hardware attestation.",
        "Process-kill recovery qualified; no physical power-cut/reboot/directory-metadata durability claim.",
        "Logical GPU leases and CPU fixture commands; no scientific observer contact or scientific flight authorization.",
        "Performance ranges and remaining ancestry/filter costs are reported descriptively; no throughput threshold was invented."]
    suite = {"schema": "KAMMI_ENDSTATE_ACCEPTANCE_V1", "status": "PASS", "source_root": source_root, "runtime_identity": runtime_root,
        "architecture_hash": architecture_identity(),
        "gates": proofs, "reports": references,
        "test_count": tests["test_count"], "fixture_stores": {"memory": str(fixtures / "memory"), "custody": str(fixtures / "custody")},
        "limitations": limitations, "issued_at": datetime.now(timezone.utc).isoformat()}
    suite_id = write(reports / "ENDSTATE-ACCEPTANCE-v1.json", suite)
    command("independent-audit", [sys.executable, "-m", "scripts.endstate_audit", str(reports)])
    audit_id = raw_id((reports / "ENDSTATE-INDEPENDENT-AUDIT-v1.json").read_bytes())
    service_root = HERE / ".kammi-dev/operational/store"
    if not service_root.exists():
        for path in ("objects/sha256", "journal"):
            shutil.copytree(HERE / ".kammi-dev/e4-import" / path, service_root / path)
    ledger = Ledger(service_root, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
    try:
        prior = ledger.library_acceptance
        if prior is not None and ledger.flight_state()["state"] == "OPEN":
            raise RuntimeError("current store is already qualified; redundant acceptance refused")
        prefix = "q-" + stamp + ":"
        identities = []
        for path in sorted(reports.iterdir()):
            if path.is_file() and path.suffix in {".json", ".log"}:
                identity, _ = ledger.register_bytes(path.read_bytes(), kind="library-qualification-evidence", actor="library-auditor",
                    request_id=prefix + "evidence-" + path.name)
                identities.append(identity)
        for file in source["files"]:
            ledger.register_bytes((HERE / file["path"]).read_bytes(), kind="qualified-source", actor="library-auditor",
                request_id=prefix + "source-" + hashlib.sha256(file["path"].encode()).hexdigest())
        source_seal, _ = ledger.create_seal(sorted({file["artifact_id"] for file in source["files"]}), [], "library-auditor", prefix + "source-seal")
        parents = [source_seal]
        if prior is not None:
            parents.append(strict_json(ledger.cas.get(prior))["evidence_merkle_root"])
        evidence_seal, _ = ledger.create_seal(sorted(set(identities)), parents, "library-auditor", prefix + "evidence-seal")
        acceptance = {"schema": "LibraryAcceptanceV1", "architecture_hash": suite["architecture_hash"],
            "source_root": source_root, "runtime_identity": runtime_root, "acceptance_suite_root": suite_id,
            "independent_verification_root": audit_id, "evidence_merkle_root": evidence_seal,
            "gates": {gate: "PASS" for gate in GATES}, "issued_at": datetime.now(timezone.utc).isoformat(), "predecessor_acceptance": prior,
            "scope": "Infrastructure acceptance only; scientific protocols retain their own authorization."}
        identity, event = ledger.accept_library(acceptance, prefix + "library-acceptance")
        assert ledger.flight_state()["state"] == "OPEN"
        # Actual ordinary authorize endpoint, with fixture scope/grant, after
        # acceptance. No acceptance bypass or scientific observer is involved.
        token = os.urandom(32).hex()
        actor_id, run_id, stage_id = "surface-" + stamp, "acceptance.surface." + stamp, "SURFACE_" + stamp
        ledger.register_actor(actor_id, "agent", "library", hashlib.sha256(token.encode()).hexdigest(), prefix + "surface-actor")
        ledger.create_run(run_id, "library", "auditor", prefix + "surface-run")
        policy, _ = ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": stage_id, "version": "v1",
            "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, prefix + "surface-policy")
        expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        ledger.issue_grant("surface-grant-" + stamp, actor_id, "authorize_stage", run_id, stage_id, policy, expiry, prefix + "surface-grant")
        with TestClient(create_app(ledger, "administrative-fixture-token")) as client:
            response = client.post("/v1/authorize", headers={"Authorization": "Bearer " + token}, json={"actor_id": actor_id,
                "run_id": run_id, "stage_id": stage_id, "expires_utc": expiry, "request_id": prefix + "surface-authorize"})
            assert response.status_code == 200 and response.json()["receipt"]["decision"] == "AUTHORIZED", response.text
        final = {"schema": "KAMMI_ENDSTATE_TERMINAL_V1", "status": "PASS", "flight_state": "OPEN", "acceptance_identity": identity,
            "acceptance_event": event, "source_root": source_root, "runtime_identity": runtime_root, "acceptance_suite_root": suite_id,
            "independent_verification_root": audit_id, "evidence_merkle_root": evidence_seal,
            "gates_passed": len(GATES), "tests_passed": tests["test_count"], "operational_store": str(service_root),
            "scientific_observer_contact": False, "scientific_flight_authorized": False}
        write(reports / "LibraryAcceptanceV1.json", acceptance)
        write(reports / "TERMINAL.json", final)
        (reports / "ENDSTATE-ACCEPTANCE-v1.md").write_text("# Kammi Ledger end-state acceptance\n\n"
            + f"All {len(GATES)} gates PASS. Infrastructure flight state: OPEN.\n\n"
            + "```json\n" + json.dumps(final, indent=2) + "\n```\n\n"
            + "## Qualified boundary\n\n" + "\n".join("- " + item for item in limitations) + "\n")
        print(json.dumps(final, indent=2), flush=True)
    finally:
        ledger.close()


if __name__ == "__main__":
    main()
