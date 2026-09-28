"""Operation counts and timing curves; no throughput target confers acceptance."""
import gc
import math
import time
from pathlib import Path

from ledgerd.identity import canonical
from ledgerd.seals import make_seal, verify_lineage
from ledgerd.cas import ContentStore
from ledgerd.journal import EventJournal
from scripts.memory_stress import percentiles


def run_scaling(root):
    root.mkdir(parents=True)
    curves = []
    for size in (128, 512, 2048):
        member = "sha256:" + "1" * 64
        seals, parent = {}, None
        for _ in range(size):
            value, parent = make_seal([member], [parent] if parent else [])
            seals[parent] = canonical(value)
        timings, counts = [], []
        for _ in range(5):
            loaded, verified = [0], [0]
            def load(identity):
                loaded[0] += 1
                return seals[identity]
            def verify(_):
                verified[0] += 1
                return True
            start = time.perf_counter()
            assert verify_lineage(parent, load, verify) == [member]
            timings.append((time.perf_counter() - start) * 1000)
            assert loaded[0] == size and verified[0] == 1
            counts.append({"seal_loads": loaded[0], "artifact_checks": verified[0]})
        curves.append({"seals": size, "distinct_members": 1, "cost": percentiles(timings), "operation_counts": counts})
    root_cas = ContentStore(root / "journal-benchmark")
    journal = EventJournal(root / "journal-benchmark")
    payload, _ = root_cas.put_bytes(canonical({"run_id": "benchmark", "lab": "library"}))
    replay, append_times = [], []
    for size in (128, 512, 2048):
        while len(journal.events) < size:
            event = {"schema": "KAMMI_EVENT_V1", "seq": len(journal.events) + 1, "prev": journal.head,
                "type": "RunCreated", "payload_artifact": payload, "actor": "benchmark",
                "request_id": "append-" + str(len(journal.events)), "utc": "2026-09-27T00:00:00Z"}
            start = time.perf_counter()
            journal.append(event)
            append_times.append((time.perf_counter() - start) * 1000)
        samples = []
        for _ in range(5):
            start = time.perf_counter()
            read = EventJournal(root / "journal-benchmark")
            assert read.head == journal.head and len(read.events) == size
            samples.append((time.perf_counter() - start) * 1000)
        replay.append({"events": size, "cost": percentiles(samples)})
    def exponent(first, last, size_key):
        return math.log(last["cost"]["p50_ms"] / first["cost"]["p50_ms"]) / math.log(last[size_key] / first[size_key])
    return {"schema": "KAMMI_SCALING_REPORT_V1", "status": "PASS", "seal_dag": curves,
        "journal_replay": replay, "journal_append": percentiles(append_times),
        "measured_exponents": {"seal_dag": exponent(curves[0], curves[-1], "seals"),
                               "journal_replay": exponent(replay[0], replay[-1], "events")},
        "deterministic_complexity": "DAG verifier: one visit per distinct seal/edge, one check per distinct member; journal replay: one framed scan.",
        "remaining_costs": ["Seal construction recursively verifies each requested parent ancestry; constructing a long chain with full verification after each successor can be quadratic over the whole construction sequence.",
                            "Queries matching very common terms still traverse matching postings; no constant-time claim.",
                            "Scope/trust filters may require larger HNSW overfetch; worst-case full-corpus retrieval is retained for correctness."],
        "interpretation": "Timing descriptive on 128..2048 elements; no universal complexity guarantee from three timing points.",
        "scope": "Journal framing microbenchmark below live API; repeated RunCreated payload is synthetic, not a lab run history."}
