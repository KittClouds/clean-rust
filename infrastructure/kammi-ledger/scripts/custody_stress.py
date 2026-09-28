"""Concurrent custody/lease stress and baseline performance characterization."""
from __future__ import annotations
import gc
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ledgerd.core import Ledger
from ledgerd.identity import canonical
from scripts.independent_verify import verify_store
from scripts.memory_stress import percentiles
from scripts.projection_compare import compare_rebuild


def run_custody_stress(root: Path):
    ledger = Ledger(root)
    latencies = {"artifact_registration": [], "authorization": [], "lease": [], "lineage": []}
    journal_times = []
    append = ledger.journal.append
    def timed_append(event):
        begin = time.perf_counter()
        identity = append(event)
        journal_times.append((time.perf_counter() - begin) * 1000)
        return identity
    ledger.journal.append = timed_append
    try:
        ledger.create_run("acceptance.stress", "library", "admin", "stress-run")
        policy, _ = ledger.register_policy({"schema": "KAMMI_POLICY_V1", "stage_id": "STRESS", "version": "v1",
                                           "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "policy")
        expiry = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        tokens = {}
        for i in range(8):
            actor, token = "agent-" + str(i), "stress-credential-" + str(i)
            tokens[actor] = token
            ledger.register_actor(actor, "agent", "library", hashlib.sha256(token.encode()).hexdigest(), "register-" + actor)
            for action in ("authorize_stage", "acquire_lease"):
                ledger.issue_grant(action + actor, actor, action, "acceptance.stress", "STRESS", policy, expiry, "grant-" + action + actor)
        ledger.register_resource("gpu.stress", "GPU", "fixture", {}, "resource")
        start = time.perf_counter()
        def register(i):
            begin = time.perf_counter()
            identity, _ = ledger.register_bytes(i.to_bytes(4, "little") + b"x" * 32764, kind="source", actor="agent-0", request_id="artifact-" + str(i))
            return identity, (time.perf_counter() - begin) * 1000
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(register, range(256)))
        registration_seconds = time.perf_counter() - start
        artifacts = [r[0] for r in results]
        latencies["artifact_registration"] = [r[1] for r in results]
        assert len(set(artifacts)) == 256
        seal_metrics = []
        for size in (16, 64, 256):
            seal, _ = ledger.create_seal(artifacts[:size], [], "admin", "seal-" + str(size))
            samples = []
            for _ in range(12):
                begin = time.perf_counter()
                assert len(ledger.verify_seal(seal)) == size
                samples.append((time.perf_counter() - begin) * 1000)
            seal_metrics.append({"closure": size, **percentiles(samples)})
            latencies["lineage"].extend(samples)
        for i in range(40):
            actor = "agent-" + str(i % 8)
            begin = time.perf_counter()
            _, decision = ledger.authorize_stage("acceptance.stress", "STRESS", actor, expiry, "authorize-" + str(i))
            assert decision["decision"] == "AUTHORIZED"
            latencies["authorization"].append((time.perf_counter() - begin) * 1000)
        collision_rounds = []
        stale_rejections = 0
        for round_number in range(64):
            def contender(i):
                actor = "agent-" + str(i)
                begin = time.perf_counter()
                event, receipt = ledger.acquire_lease("gpu.stress", "acceptance.stress", "STRESS", actor, tokens[actor], "collision", 30,
                                                      f"collision-{round_number}-{i}")
                return event, receipt, (time.perf_counter() - begin) * 1000
            with ThreadPoolExecutor(max_workers=8) as pool:
                receipts = list(pool.map(contender, range(8)))
            winners = [r for _, r, _ in receipts if r["decision"] == "GRANTED"]
            assert len(winners) == 1
            winner = winners[0]
            latencies["lease"].extend(ms for _, _, ms in receipts)
            ledger.release_lease(winner["lease_id"], winner["fencing_token"], winner["actor_id"], tokens[winner["actor_id"]], "release-" + str(round_number))
            assert not ledger.leases.valid(winner["lease_id"], "gpu.stress", winner["fencing_token"], winner["actor_id"], "acceptance.stress")
            stale_rejections += 1
            collision_rounds.append({"round": round_number, "granted": 1, "denied": 7, "fence": winner["fencing_token"]})
        buffer = b"h" * (16 * 1024 * 1024)
        begin = time.perf_counter()
        for _ in range(4):
            ledger.cas.put_bytes(buffer)
        hashing_seconds = time.perf_counter() - begin
        audit = verify_store(root)
        begin = time.perf_counter()
        projection = compare_rebuild(ledger)
        rebuild_ms = (time.perf_counter() - begin) * 1000
        return {"schema": "KAMMI_CUSTODY_STRESS_V1", "status": "PASS", "concurrent_clients": 8,
                "artifact_count": 256, "artifact_registration_per_second": 256 / registration_seconds,
                "cas_hash_and_write_mib_per_second": 64 / hashing_seconds,
                "latency": {name: percentiles(values) for name, values in latencies.items()},
                "journal_append": percentiles(journal_times),
                "seal_verification": seal_metrics, "rebuild_ms": rebuild_ms,
                "rebuild_events_per_second": len(ledger.journal.events) * 1000 / rebuild_ms,
                "projection_lag": ledger.status()["projection_lag"],
                "collision_rounds": collision_rounds, "lease_requests": 512, "stale_rejections": stale_rejections,
                "independent_audit": audit, "projection_audit": projection,
                "clock_scope": "real-time concurrent acquisition/release; process death/real expiry qualified by separate external client fixture"}
    finally:
        ledger.close()
        gc.collect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_custody_stress(args.root)
    args.output.write_bytes(canonical(report))
    print(json.dumps({"status": report["status"], "lease_requests": report["lease_requests"]}), flush=True)
