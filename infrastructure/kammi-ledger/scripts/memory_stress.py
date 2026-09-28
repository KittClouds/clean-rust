"""Larger memory corpus with exact, semantic, relational and trust needles."""
from __future__ import annotations

import gc
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ledgerd.core import Ledger
from ledgerd.identity import canonical
from scripts.independent_verify import verify_store

HERE = Path(__file__).resolve().parents[1]


def percentiles(values):
    ordered = sorted(values)
    return {"p50_ms": ordered[len(ordered) // 2], "p95_ms": ordered[min(len(ordered) - 1, int(len(ordered) * .95))]}


def run_memory_stress(root: Path, count=1200):
    ledger = Ledger(root, embedding_cache=HERE / "vendor/runtime-v1/embedding-cache")
    timings = {"fts": [], "vector": [], "hybrid": []}
    try:
        evidence, _ = ledger.register_bytes(b"Synthetic construction evidence for memory tests only.",
                                            kind="receipt", actor="audit", request_id="memory-evidence")
        corpus = []
        topics = ["garden irrigation and soil", "shipping inventory reconciliation", "meeting calendar timezone", "audio waveform playback",
                  "SQL relational query planning", "mesh vertex rendering", "paper citation search", "invoice accounting"]
        for i in range(count):
            corpus.append(("PROCEDURE", f"Procedure {i}: review {topics[i % len(topics)]} for project {i % 41} before committing changes.", [], ["topic-" + str(i % 8)]))
        corpus.extend([
            ("FAILURE_MODE", "Nested schema path mismatch made an auditor inspect the wrong evaluation field. NeedlestoneZ19", [evidence], ["schema", "e4"]),
            ("FAILURE_MODE", "A display application was confused with a neural training workload, so accelerator ownership was incorrectly assigned.", [evidence], ["gpu", "e4"]),
            ("HYPOTHESIS", "A display application always owns the accelerator during neural training workloads.", [], ["gpu", "e4"]),
            ("DECISION", "The predecessor receipt should be copied into every descendant contract.", [evidence], ["lineage", "e4"]),
            ("PROCEDURE", "Bind an immutable predecessor reference and load its exact identity. Avoid copied ancestor fields.", [evidence], ["lineage", "e4"]),
            ("FAILURE_MODE", "Missing transitive members caused a flat ancestry seal to omit required source bytes.", [evidence], ["lineage", "e4"]),
            ("FAILURE_MODE", "Duplicate paths referred to identical bytes; content identity deduplicates without erasing provenance.", [evidence], ["cas", "e4"]),
            ("FAILURE_MODE", "Historical receipt aliasing hid which immutable object a successor actually cited.", [evidence], ["lineage", "e4"]),
            ("FAILURE_MODE", "An auditor expectation bug incorrectly rejected a valid schema; repair tooling separately from science.", [evidence], ["schema", "e4"]),
            ("RESULT_SUMMARY", "The sealed predecessor remains authoritative after a failed successor attempt.", [evidence], ["lineage", "e4"]),
            ("INTERPRETIVE", "All lineage failures probably indicate poor scientific hypotheses.", [], ["lineage", "e4"]),
        ])
        started = time.perf_counter()
        # Prewarm CPU model once; service owns all record serialization and references.
        ledger.memory.embedder.encode([corpus[0][1]])
        ids = []
        for i, (kind, text, refs, tags) in enumerate(corpus):
            identity, _ = ledger.memory.record(kind=kind, scope="library", text=text, actor="audit",
                                               custody_refs=refs, tags=tags, request_id="record-" + str(i))
            ids.append(identity)
            if i % 200 == 0:
                print(json.dumps({"memory_records": i + 1}), flush=True)
        insertion_ms = (time.perf_counter() - started) * 1000
        ledger.memory.supersede(ids[count + 3], ids[count + 4], "audit", "supersede-old-decision")
        print("MEMORY_FTS_EXACT_BEGIN", flush=True)
        exact = ledger.memory.search("NeedlestoneZ19", scope="library", actor="audit", request_id="exact", mode="fts", limit=1)
        assert exact["results"][0]["memory"]["memory_id"] == ids[count]
        print("MEMORY_VECTOR_SEMANTIC_BEGIN", flush=True)
        semantic = ledger.memory.search("video card lease mistakenly attributed to model fitting instead of window drawing",
                                         scope="library", actor="audit", request_id="semantic", mode="vector", limit=5,
                                         grounded_only=True, exclude_kinds=["HYPOTHESIS"])
        assert ids[count + 1] in [r["memory"]["memory_id"] for r in semantic["results"]]
        print("MEMORY_GRAPH_BEGIN", flush=True)
        graph = ledger.memory.search("", scope="library", actor="audit", request_id="graph", mode="graph",
                                      seed_memory=ids[count + 3], exclude_kinds=["INTERPRETIVE", "HYPOTHESIS"])
        assert ids[count + 4] in [r["memory"]["memory_id"] for r in graph["results"]]
        assert ids[count + 3] not in [r["memory"]["memory_id"] for r in graph["results"]]
        assert ledger.memory.trace(ids[count])["references"][0]["verified"]
        print("MEMORY_CONCURRENT_QUERIES_BEGIN", flush=True)
        def search_job(i):
            mode = ("fts", "vector", "hybrid")[i % 3]
            start = time.perf_counter()
            result = ledger.memory.search("schema auditor mismatch", scope="library", actor="audit", request_id="stress-search-" + str(i),
                                           mode=mode, limit=10, grounded_only=True)
            elapsed = (time.perf_counter() - start) * 1000
            assert all(r["memory"]["custody_refs"] for r in result["results"])
            return mode, elapsed
        with ThreadPoolExecutor(max_workers=8) as pool:
            for mode, elapsed in pool.map(search_job, range(90)):
                timings[mode].append(elapsed)
        audit = verify_store(root)
        return {"schema": "KAMMI_MEMORY_STRESS_V1", "status": "PASS", "records": len(corpus),
                "insertion_ms": insertion_ms, "search_concurrency": 8, "searches": 90,
                "checks": ["exact_needle", "semantic_needle", "graph_relational", "trust_filters", "supersession", "custody_trace", "independent_reconstruction"],
                "retrieval_latency": {mode: percentiles(values) for mode, values in timings.items()},
                "authority_audit": audit, "fixture_scope": "Synthetic stress corpus; E4 failure descriptions are contextual paraphrases, not scientific observations."}
    finally:
        ledger.close()
        gc.collect()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_memory_stress(args.root)
    args.output.write_bytes(canonical(report))
    print(json.dumps({"status": report["status"], "records": report["records"]}), flush=True)
