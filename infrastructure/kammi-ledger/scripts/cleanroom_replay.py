"""Complete isolated custody-to-memory workflow on fresh E4 authority copies."""
from __future__ import annotations
import gc
import hashlib
import json
import os
import shutil
import sys
import time
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from ledgerd.backup import backup, restore
from ledgerd.core import Ledger
from ledgerd.identity import canonical, strict_json
from ledgerd.remote import public_bytes
from ledgerd.worker import execute_bundle
from scripts.independent_verify import verify_store
from scripts.projection_compare import snapshot

HERE = Path(__file__).resolve().parents[1]


def run_cleanroom(root: Path):
    root.mkdir(parents=True)
    source = HERE / ".kammi-dev/e4-import"
    store = root / "store"
    shutil.copytree(source / "objects/sha256", store / "objects/sha256")
    shutil.copytree(source / "journal", store / "journal")
    signing_key = os.urandom(32)
    ledger = Ledger(store, signing_key=signing_key, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
    try:
        legacy = strict_json(ledger.cas.get("sha256:0635de4a384b4d5121d8b2295e88a73f649c53e402ffcda311fcaf9c8d93099c"))
        builder = hashlib.sha256()
        for e in legacy["entries"]:
            raw = ledger.cas.get("sha256:" + e["sha256"])
            assert len(raw) == e["bytes"]
            builder.update(f"{e['artifact_id']}\t{e['path']}\t{e['bytes']}\t{e['sha256']}\n".encode())
        assert builder.hexdigest() == "278ae16eeb6852d3efad44221556a87be6df54964471f0870931fe2e99b305d1"
        assert len(legacy["entries"]) == 447
        imported = json.loads((HERE / "acceptance/e4-0/history-import-v3.json").read_text())
        history = ledger.history_summary(imported["run_id"])
        assert not history["authorization_conferred"] and len(history["stopped_attempts"]) == 29
        assert len(ledger.history(imported["run_id"])) == 557
        assert len(ledger.verify_seal(imported["source_merkle_root"])) == 493
        e4 = {"status": "PASS", "entries": 447, "unique_original_objects": 432,
              "supplement_closure": 493, "facts": 557, "stopped_attempts": 29,
              "scientific_seal_unchanged": True, "live_authorizations_from_history": 0,
              "history_summary": history, "reconstructed_head": ledger.journal.head}
        ledger.register_actor("agent", "agent", "library", hashlib.sha256(b"agent-fixture-token").hexdigest(), "actor")
        ledger.register_actor("worker", "remote_worker", "library", hashlib.sha256(b"worker-fixture-token").hexdigest(), "worker")
        worker_private = Ed25519PrivateKey.generate()
        ledger.register_worker_key("worker", public_bytes(worker_private).hex(), "worker-key")
        ledger.create_run("acceptance.library", "library", "auditor", "new-run")
        policy_hash, _ = ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": "REPLAY", "version": "v1",
            "requires": {"actor": "AUTHORIZED", "scientific_spec": "SEALED", "execution_spec": "SEALED",
                         "predecessor_seal": "VERIFIED", "resource.gpu": "LEASED"},
            "forbids": {"truth_label_contact": True}}, "new-policy")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        for action in ("authorize_stage", "open_panel", "acquire_lease", "execute_bundle", "apply_adapter"):
            ledger.issue_grant("grant-" + action, "agent", action, "acceptance.library", "REPLAY", policy_hash, expiry, "grant-" + action)
        scientific, _ = ledger.register_bytes(b"fixture scientific spec", kind="scientific-spec", actor="auditor", request_id="science")
        execution, _ = ledger.register_bytes(b"fixture execution spec", kind="execution-spec", actor="auditor", request_id="execution")
        env, _ = ledger.register_bytes(b"fixture environment lock", kind="environment-lock", actor="auditor", request_id="environment")
        input_artifact, _ = ledger.register_bytes(b"fixture input", kind="input", actor="auditor", request_id="input")
        seal, _ = ledger.create_seal([scientific, execution, env, input_artifact], [], "auditor", "new-seal")
        for kind, artifact in (("SCIENTIFIC", scientific), ("EXECUTION", execution)):
            ledger.bind_spec("acceptance.library", "REPLAY", kind, artifact, seal, "agent", "bind-" + kind)
        ledger.record_seal_verification("acceptance.library", "REPLAY", seal, "agent", "verified-seal")
        ledger.register_resource("gpu.fixture", "GPU", "local", {}, "resource")
        _, lease = ledger.acquire_lease("gpu.fixture", "acceptance.library", "REPLAY", "agent", "agent-fixture-token", "replay", 120, "lease")
        authorization, receipt = ledger.authorize_stage("acceptance.library", "REPLAY", "agent", expiry, "auth")
        assert receipt["decision"] == "AUTHORIZED"
        ledger.start_attempt("replay-attempt", "acceptance.library", "REPLAY", "agent", authorization, "attempt-start")
        panel_artifact, _ = ledger.register_bytes(b"guarded terminal fixture", kind="panel", actor="auditor", request_id="panel-bytes")
        ledger.register_panel("panel.fixture", panel_artifact, "library", "panel")
        data, opened, _ = ledger.open_panel("panel.fixture", "terminal", "acceptance.library", "REPLAY", "agent", "agent-fixture-token", authorization, "exposure")
        assert data == b"guarded terminal fixture" and ledger.exposure.report("panel.fixture")["count"] == 1
        schema_source, _ = ledger.register_bytes(canonical({"schema": "evaluation-v1", "evaluation_checkpoint_cells": [1, 2]}), kind="manifest", actor="auditor", request_id="adapter-source")
        ledger.register_adapter("EVAL_CELLS_RENAME_V1", "adapter")
        derived, _ = ledger.apply_adapter("EVAL_CELLS_RENAME_V1", schema_source, "agent", "agent-fixture-token", "acceptance.library", "REPLAY", authorization, "fixture", "adapter-apply")
        assert strict_json(ledger.cas.get(derived))["evaluation_cells"] == [1, 2]
        command = [sys.executable, "-c", "import os,pathlib; (pathlib.Path(os.environ['KAMMI_OUTPUT_DIR'])/'out.txt').write_text('qualified worker fixture')"]
        bundle = {"schema": "KAMMI_REMOTE_BUNDLE_V1", "run_id": "acceptance.library", "lab": "library", "stage_id": "REPLAY",
                  "scientific_spec": scientific, "execution_spec": execution, "git_commit": "a" * 40,
                  "dirty_tree_policy": "CLEAN_REQUIRED", "input_roots": [seal], "input_artifacts": [input_artifact],
                  "environment_lock": env, "runtime_requirements": {"runtime": "python-fixture"}, "gpu_requirements": {},
                  "seeds": [7], "command": command, "expected_outputs": ["out.txt"], "authorization_id": authorization,
                  "lease_id": lease["lease_id"], "lease_resource_id": "gpu.fixture", "fencing_token": lease["fencing_token"], "worker_actor_id": "worker"}
        _, envelope = ledger.create_remote_bundle(bundle, "agent", "agent-fixture-token", "bundle")
        ledger.remote_worker_started(envelope["bundle_artifact_id"], "worker", "worker-fixture-token", "worker-start")
        result = execute_bundle(ledger.cas.get(envelope["bundle_artifact_id"]), envelope["signature_hex"], bytes.fromhex(envelope["issuer_public_hex"]),
                                {input_artifact: b"fixture input"}, worker_private,
                                {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"},
                                lambda i, r, f: ledger.leases.valid(i, r, f, "agent", "acceptance.library"))
        returned, remote_receipt = ledger.accept_remote_return(envelope["bundle_artifact_id"], result[0], result[1], "worker", "worker-fixture-token",
                                                              result[2], result[3], result[4], "worker-return")
        memory, _ = ledger.memory.record(kind="FAILURE_MODE", scope="library", text="E4's nested schema path mismatch required a registered adapter, while the original source remained unchanged.",
                                          actor="agent", custody_refs=[schema_source, derived, returned], tags=["e4", "schema"], request_id="grounded-failure")
        procedure, _ = ledger.memory.record(kind="PROCEDURE", scope="library", text="Apply the registered adapter and trace the derived view back to exact source identity.",
                                             actor="agent", custody_refs=[derived], tags=["e4", "schema"], request_id="grounded-procedure")
        for mode in ("fts", "vector", "hybrid", "graph"):
            result_search = ledger.memory.search("schema field mismatch", scope="library", actor="fresh-agent", request_id="retrieve-" + mode,
                                                mode=mode, seed_memory=procedure if mode == "graph" else None, grounded_only=True)
            assert memory in [r["memory"]["memory_id"] for r in result_search["results"]]
        assert all(ref["verified"] for ref in ledger.memory.trace(memory)["references"])
        ledger.finish_attempt("replay-attempt", "agent", "COMPLETE", derived, "fixture completed", "attempt-complete")
        output_root, _ = ledger.create_seal([derived, *remote_receipt["outputs"].values()], [seal], "agent", "output-seal")
        ledger.declare_result("acceptance.library", "REPLAY", "agent", authorization, output_root, None, "result-head")
        before_crash, memory_before_crash = ledger.journal.head, ledger.memory.journal.head
        ledger.close()
        gc.collect()
        code = ("from pathlib import Path;import os,sys;from ledgerd.core import Ledger;"
                "l=Ledger(Path(sys.argv[1]));os.environ['KAMMI_ACCEPTANCE_FAULTS']='1';"
                "os.environ['KAMMI_FAULT_POINT']='journal.after_fsync';"
                "l.register_bytes(b'controlled cleanroom crash',kind='receipt',actor='audit',request_id='cleanroom-crash')")
        crashed = subprocess.run([sys.executable, "-c", code, str(store)], capture_output=True, timeout=30)
        assert crashed.returncode == 91, crashed.stderr
        committed = verify_store(store)
        ledger = Ledger(store, signing_key=signing_key, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
        assert ledger.journal.head == committed["journal_head"] and ledger.journal.head != before_crash
        assert ledger.memory.journal.head == memory_before_crash
        before, memory_head, rows = ledger.journal.head, ledger.memory.journal.head, snapshot(ledger)
        independent = verify_store(store)
        backup(ledger, root / "backup")
        ledger.close()
        gc.collect()
        restore(root / "backup", root / "restored")
        ledger = Ledger(root / "restored", signing_key=signing_key, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
        assert ledger.journal.head == before and ledger.memory.journal.head == memory_head
        assert snapshot(ledger) == rows
        assert verify_store(ledger.root) == independent
        assert ledger.memory.trace(memory)["references"][0]["verified"]
        ledger.release_lease(lease["lease_id"], lease["fencing_token"], "agent", "agent-fixture-token", "release")
        _, next_lease = ledger.acquire_lease("gpu.fixture", "acceptance.library", "REPLAY", "agent", "agent-fixture-token", "replacement", 120, "next-lease")
        assert not ledger.leases.valid(lease["lease_id"], "gpu.fixture", lease["fencing_token"], "agent", "acceptance.library")
        denied, _, _ = ledger.open_panel("panel.fixture", "terminal", "acceptance.library", "REPLAY", "agent", "agent-fixture-token", "sha256:" + "0" * 64, "denied-exposure")
        assert denied is None
        return {"schema": "KAMMI_CLEANROOM_REPLAY_V1", "status": "PASS", "e4": e4,
                "custody_head_before_restore": before, "memory_head_before_restore": memory_head,
                "restored_exact_heads": True, "restored_exact_projection": True,
                "independent_audit": independent, "remote_receipt": remote_receipt,
                "memory_trace": ledger.memory.trace(memory), "final_head": ledger.journal.head,
                "fixture_store": str(ledger.root), "stale_fence_rejected": True, "unauthorized_panel_rejected": True,
                "steps": ["e4_rebuild", "447_seal", "557_history", "new_run", "spec_binding", "authorization", "fenced_lease", "guarded_exposure",
                          "adapter", "signed_bundle", "disposable_worker", "output_verification", "grounded_memory", "fts_vector_graph_fusion",
                          "custody_trace", "result_seal", "controlled_crash", "backup_restore", "projection_rebuild", "exact_heads", "stale_fence", "denied_panel"]}
    finally:
        ledger.close()
        gc.collect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_cleanroom(args.root)
    args.output.write_bytes(canonical(report))
    print(json.dumps({"status": report["status"], "e4_entries": report["e4"]["entries"]}), flush=True)
