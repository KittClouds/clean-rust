"""Strict /v1 memory differential: Python daemon vs Rust daemon + supervised projector.

Both daemons run on the same fixed clock (acceptance fixture mode) with the same embedder
(bge-small-en-v1.5; Rust's vectors are byte-identical to Python's fastembed), so every event
ID, memory ID, rank and score must come out identical. Responses are compared for exact
equality; any float difference is reported with its magnitude.

Covers gates G5-G11 and G14 of docs/PHASE-3-GATES.md:
  G6 lexical (fts), G7 vector, G8 hybrid (+ grounded_only, exclude_kinds, include_superseded,
  limit), G9 graph/neighbours, G10 get/trace, G11 supersession, across Python's FTS
  rebuild-on-doubling state machine and a restart of both daemons; then G5 row parity of
  the memory tables read through Python's own Ladybug binding.

Usage (kammi-ledger venv):
  python tools/memory_differential.py <work dir> [--output report.json]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_differential import PY, TARGET, Side  # noqa: E402

KINDS = ["OBSERVED", "DERIVED", "INTERPRETIVE", "HYPOTHESIS", "PREFERENCE", "PROCEDURE", "DECISION", "FAILURE_MODE", "RESULT_SUMMARY"]


def first_difference(a, b, path="$"):
    """(path, python value, rust value) of the first difference, or None."""
    if type(a) is not type(b):
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
            return None if a == b else (path, a, b)
        return (path, a, b)
    if isinstance(a, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a or key not in b:
                return (f"{path}.{key}", a.get(key, "<absent>"), b.get(key, "<absent>"))
            found = first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return (f"{path}[len]", len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            found = first_difference(x, y, f"{path}[{i}]")
            if found:
                return found
        return None
    return None if a == b else (path, a, b)


def category(label):
    for prefix in ("fts", "vector", "hybrid", "graph", "trace", "get", "neighbors", "supersede", "record", "restart"):
        if label.startswith(prefix):
            return prefix
    return "setup"


def workflow(side: Side, corpus, expiry: str, restart):
    c = side.call
    admin, agent, other = "cleanroom-admin", "cleanroom-agent", "cleanroom-other"
    for actor, lab, token in (("agent", "library", agent), ("other", "lab-b", other)):
        c("setup-actor-" + actor, "POST", "/v1/actors", {"actor_id": actor, "kind": "agent", "lab": lab,
          "credential_sha256": hashlib.sha256(token.encode()).hexdigest(), "request_id": "actor-" + actor})
    artifacts = []
    for i in range(8):
        raw = f"memory differential evidence {i}".encode()
        artifacts.append(c(f"setup-artifact-{i}", "POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(),
                           "kind": "evidence", "actor": "auditor", "request_id": f"artifact-{i}"})[0]["artifact_id"])
    docs, queries = corpus["documents"][:72], corpus["queries"]
    memory_ids = []

    def search(label, query, mode, *, limit=10, token=agent, actor="agent", scope="library", **extra):
        body = {"query": query, "scope": scope, "actor_id": actor, "mode": mode, "limit": limit, "request_id": label, **extra}
        return c(label, "POST", "/v1/memory/search", body, token=token, expect=None)[0]

    for i, doc in enumerate(docs):
        kind = KINDS[i % len(KINDS)]
        refs = [artifacts[i % 8]] if kind in ("OBSERVED", "DERIVED") or i % 3 == 0 else []
        tags = [doc["source"].rsplit(".", 1)[0], f"t{i % 5}"]
        body = {"kind": kind, "scope": "library", "text": doc["text"], "actor_id": "agent", "custody_refs": refs,
                "tags": tags, "request_id": f"mem-{i}"}
        if i % 4:
            body["confidence"] = (i % 10) / 10
        memory_ids.append(c(f"record-{i}", "POST", "/v1/memory", body, token=agent)[0]["memory_id"])
        if i % 6 == 5:  # interleaved searches exercise the FTS overlay and rebuild-on-doubling
            q = queries[i % len(queries)]["text"]
            search(f"fts-interleaved-{i}", q, "fts")
            search(f"hybrid-interleaved-{i}", q, "hybrid")
    c("record-retry", "POST", "/v1/memory", {"kind": KINDS[0], "scope": "library", "text": docs[0]["text"], "actor_id": "agent",
      "custody_refs": [artifacts[0]], "tags": [docs[0]["source"].rsplit(".", 1)[0], "t0"], "request_id": "mem-0"}, token=agent)
    c("record-other-scope", "POST", "/v1/memory", {"kind": "INTERPRETIVE", "scope": "lab-b", "text": corpus["documents"][100]["text"],
      "actor_id": "other", "request_id": "mem-other"}, token=other)

    for old, new in ((0, 1), (1, 2), (5, 9), (10, 11)):
        c(f"supersede-{old}-{new}", "POST", "/v1/memory/supersede", {"old_id": memory_ids[old], "new_id": memory_ids[new],
          "actor_id": "agent", "request_id": f"supersede-{old}-{new}"}, token=agent)
    c("supersede-cycle", "POST", "/v1/memory/supersede", {"old_id": memory_ids[2], "new_id": memory_ids[0], "actor_id": "agent",
      "request_id": "supersede-cycle"}, token=agent, expect=None)
    c("supersede-self", "POST", "/v1/memory/supersede", {"old_id": memory_ids[3], "new_id": memory_ids[3], "actor_id": "agent",
      "request_id": "supersede-self"}, token=agent, expect=None)

    for j, q in enumerate(queries):
        for mode in ("fts", "vector", "hybrid"):
            search(f"{mode}-q{j}", q["text"], mode)
        search(f"graph-q{j}", q["text"], "graph", seed_memory=memory_ids[j % len(memory_ids)])
        search(f"hybrid-seeded-q{j}", q["text"], "hybrid", seed_memory=memory_ids[(j * 7) % len(memory_ids)])
    for j, q in enumerate(queries[:12]):
        search(f"hybrid-limit3-q{j}", q["text"], "hybrid", limit=3)
        search(f"hybrid-limit25-q{j}", q["text"], "hybrid", limit=25)
        search(f"fts-grounded-q{j}", q["text"], "fts", grounded_only=True)
        search(f"vector-exclude-q{j}", q["text"], "vector", exclude_kinds=["HYPOTHESIS", "PREFERENCE"])
        search(f"hybrid-superseded-q{j}", q["text"], "hybrid", include_superseded=True)
    search("hybrid-other-scope", queries[0]["text"], "hybrid", token=other, actor="other", scope="lab-b")
    search("hybrid-scope-denied", queries[0]["text"], "hybrid", scope="lab-b")
    search("fts-bad-limit", queries[0]["text"], "fts", limit=0)
    search("fts-retry", queries[0]["text"], "fts")  # same request id as fts-q0: replayed receipt
    for i, memory_id in enumerate(memory_ids):
        c(f"get-{i}", "GET", f"/v1/memory/{memory_id}?actor_id=agent", token=agent)
        c(f"trace-{i}", "GET", f"/v1/memory/{memory_id}/trace?actor_id=agent", token=agent)
        c(f"neighbors-{i}", "GET", f"/v1/memory/{memory_id}/neighbors?actor_id=agent", token=agent)
    c("get-wrong-scope", "GET", f"/v1/memory/{memory_ids[0]}?actor_id=other", token=other, expect=None)

    restart(side)
    for j, q in enumerate(queries[:20]):
        search(f"restart-fts-q{j}", q["text"], "fts")
        search(f"restart-hybrid-q{j}", q["text"], "hybrid", seed_memory=memory_ids[j])
    for i in range(72, 80):
        doc = corpus["documents"][i]
        c(f"record-after-restart-{i}", "POST", "/v1/memory", {"kind": "PROCEDURE", "scope": "library", "text": doc["text"],
          "actor_id": "agent", "tags": ["after-restart"], "request_id": f"mem-{i}"}, token=agent)
        search(f"restart-fts-after-{i}", doc["text"][:80], "fts")
    return memory_ids


def memory_rows(db_path: Path, tag_table: str):
    """Memory tables of one projection, normalised so Python and Rust compare directly."""
    native = PY / "vendor/runtime-v1/native"
    os.environ["LBUG_C_API_LIB_PATH"] = str(native / "lbug_shared.dll")
    os.add_dll_directory(str(native))
    import ladybug as lb
    db = lb.Database(str(db_path), read_only=True)
    conn = lb.Connection(db)
    q = lambda text: sorted(json.dumps(list(r), default=str) for r in conn.execute(text))  # noqa: E731
    rows = {
        "Memory": q("MATCH (m:Memory) RETURN m.id, m.text, m.scope, m.kind, m.embedding"),
        "CustodyRef": q("MATCH (r:CustodyRef) RETURN r.id"),
        "Cites": q("MATCH (m:Memory)-[:Cites]->(r:CustodyRef) RETURN m.id, r.id"),
        "About": q(f"MATCH (m:Memory)-[:About]->(t:{tag_table}) RETURN m.id, t.id"),
        "Tags": q(f"MATCH (m:Memory)-[:About]->(t:{tag_table}) RETURN DISTINCT t.id"),
        "Supersedes": q("MATCH (a:Memory)-[:Supersedes]->(b:Memory) RETURN a.id, b.id"),
    }
    conn.close()
    db.close()
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    fixture = PY / ".kammi-dev/e4-import"
    v1 = work / "python" / "store"
    for path in ("objects/sha256", "journal"):
        shutil.copytree(fixture / path, v1 / path)
    v2 = work / "rust" / "store"
    v2.parent.mkdir(parents=True)
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(fixture), "--v2", str(v2)], check=True, stdout=subprocess.DEVNULL)
    fixed = datetime.now(timezone.utc).replace(microsecond=0)
    clock = fixed.isoformat()
    expiry = (fixed + timedelta(hours=2)).isoformat()
    key = work / "daemon-signing-secret"
    key.write_bytes(hashlib.sha256(b"kammi differential signing seed").digest())
    common = {"KAMMI_SIGNING_KEY_FILE": str(key), "KAMMI_TEST_CLOCK": clock}
    python = Side("python", v1, [sys.executable, str(HERE / "tools/py_fixed_clock.py")],
                  {**common, "KAMMI_EMBEDDING_CACHE": str(PY / "vendor/runtime-v1/embedding-cache")}, PY)
    rust = Side("rust", v2, [str(TARGET / "kammi-ledgerd.exe")], {**common, "KAMMI_EMBEDDER": "bge"}, HERE)
    corpus = json.loads((HERE / "crates/kammi-embed/fixtures/qualification-corpus-v1.json").read_text(encoding="utf-8"))
    report = {"schema": "KAMMI_MEMORY_DIFFERENTIAL_V1", "clock": clock}

    def restart(side):
        side.stop()
        side.start()

    try:
        timings = {}
        for side in (python, rust):
            started = time.time()
            side.start()
            workflow(side, corpus, expiry, restart)
            timings[side.name] = round(time.time() - started, 1)
        rust_status = rust.call("status", "GET", "/v1/status", record=False)[0]
        for side in (python, rust):
            side.stop()
        rows, mismatches, per_category = [], [], {}
        if [t[0] for t in python.transcript] != [t[0] for t in rust.transcript]:
            mismatches.append({"step": "*", "detail": "transcript step labels differ"})
        for (label, ps, pb, _), (_, rs_, rb, _) in zip(python.transcript, rust.transcript):
            cat = per_category.setdefault(category(label), {"steps": 0, "identical": 0})
            cat["steps"] += 1
            diff = None if ps == rs_ else ("status", ps, rs_)
            diff = diff or first_difference(pb, rb)
            if diff is None:
                cat["identical"] += 1
            else:
                entry = {"step": label, "path": diff[0], "python": str(diff[1])[:300], "rust": str(diff[2])[:300]}
                if isinstance(diff[1], float) and isinstance(diff[2], float):
                    entry["abs_difference"] = abs(diff[1] - diff[2])
                mismatches.append(entry)
        # A hard-killed Python daemon leaves a WAL its binding may refuse; let Python recover its
        # projection exactly as its daemon does on start (quarantine + rebuild + memory replay).
        recover = ("import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; from ledgerd.core import Ledger; "
                   "Ledger(Path(sys.argv[2]), embedding_cache=Path(sys.argv[3])).close()")
        subprocess.run([sys.executable, "-c", recover, str(PY), str(v1), str(PY / "vendor/runtime-v1/embedding-cache")],
                       check=True, cwd=PY, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
        try:
            py_rows = memory_rows(v1 / "custody.lbdb", "Entity")
            rs_rows = memory_rows(v2 / "projection" / "custody.lbdb", "MemoryTag")
            row_parity = {table: {"python": len(py_rows[table]), "rust": len(rs_rows[table]), "identical": py_rows[table] == rs_rows[table]}
                          for table in py_rows}
        except Exception as exc:  # report the transcript result even if a projection will not open
            row_parity = {"error": {"python": 0, "rust": 0, "identical": False, "detail": str(exc)}}
        report.update(
            status="PASS" if not mismatches and all(t["identical"] for t in row_parity.values()) else "FAIL",
            steps=len(python.transcript), per_category=per_category, mismatches=mismatches[:40], mismatch_count=len(mismatches),
            row_parity=row_parity, timings_seconds=timings,
            rust_projection=rust_status.get("projection"), rust_memory_status=rust_status.get("memory"),
        )
    finally:
        for side in (python, rust):
            side.stop()
            for log in side.logs:
                log.close()
    text = json.dumps(report, indent=2, default=str)
    if args.output:
        args.output.write_text(text)
    print(text)
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
