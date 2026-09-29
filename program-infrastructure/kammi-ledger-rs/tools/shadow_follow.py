"""Phase 4B: gentle live shadow of the Python Library (Python stays authority).

  python tools/shadow_follow.py <work dir> [--cycles 6] [--interval-minutes 10] [--live <v1 store>]

The live store is only ever read: `kammi-migrate import` reads it through the v1 follower
(shared handles, positional reads, never mmap), and this script reads the live journal
heads with plain shared reads. No request goes to the live daemon (a memory search there
would write a receipt into Python's memory journal); search comparisons run on copies.

Per cycle:
  B1  sync the shadow v2 store; its heads equal the live v1 heads read independently
  B2  Rust kammi-state-dump of the shadow == Python oracle over export-v1 of the shadow
  B3  (first and last cycle) Rust projector bulk rebuild of the shadow == Python's projection
  B4  (last cycle) search spot check: Python daemon on the export copy vs Rust daemon on a
      shadow copy, same fixed clock, bge, identical responses
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_differential import PY, TARGET, Side  # noqa: E402

LIVE = PY / ".kammi-dev/operational/store"
CACHE = PY / "vendor/runtime-v1/embedding-cache"
ENV = {**os.environ, "PATH": str(PY / "vendor/runtime-v1/native") + os.pathsep + os.environ.get("PATH", ""), "PYTHONDONTWRITEBYTECODE": "1"}
CUSTODY_TABLES = ["LedgerMeta", "Artifact", "Event", "Seal", "Run", "CustodyFact", "SealMember", "SealParent", "HasEvent", "HasFact",
                  "FactEvidence", "Entity", "Link", "PhoenixVault", "PhoenixSource", "PhoenixGeneration", "PhoenixProductPrimary",
                  "PhoenixHasSource", "PhoenixHasGeneration", "PhoenixHasProductPrimary"]


def v1_head(journal: Path):
    """(events, head) of a v1 events.log read with shared reads; complete frames only."""
    if not journal.exists():
        return 0, "sha256:" + "0" * 64
    data = journal.read_bytes()
    off, count, head = 0, 0, "sha256:" + "0" * 64
    while off + 4 <= len(data):
        length = struct.unpack(">I", data[off:off + 4])[0]
        if off + 4 + length + 32 > len(data):
            break
        raw = data[off + 4:off + 4 + length]
        head = "sha256:" + hashlib.sha256(b"kammi-event-v1\0" + raw).hexdigest()
        count += 1
        off += 4 + length + 32
    return count, head


def run(cmd, **kw):
    started = time.time()
    result = subprocess.run(cmd, capture_output=True, text=True, env=ENV, **kw)
    return result, round(time.time() - started, 2)


def sync(shadow: Path, live: Path):
    result, seconds = run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(live), "--v2", str(shadow)])
    if result.returncode != 0:
        raise RuntimeError("import failed: " + result.stderr[-500:])
    line = result.stdout.strip().splitlines()[-1]
    main_head = line.split()[1]
    memory_head = line.split("memory ")[1].split()[0]
    return {"seconds": seconds, "report": line, "main_head": main_head, "memory_head": memory_head}


def state_parity(shadow: Path, cycle_dir: Path):
    export = cycle_dir / "export"
    result, export_seconds = run([str(TARGET / "kammi-migrate.exe"), "export-v1", "--v2", str(shadow), "--out", str(export)])
    if result.returncode != 0:
        raise RuntimeError("export failed: " + result.stderr[-500:])
    rust, rust_seconds = run([str(TARGET / "kammi-state-dump.exe"), str(shadow)])
    python, python_seconds = run([sys.executable, str(HERE / "tools/v1_state_oracle.py"), str(PY), str(export), str(CACHE)], cwd=PY)
    if rust.returncode != 0 or python.returncode != 0:
        raise RuntimeError(f"state dump failed: rust={rust.stderr[-300:]} python={python.stderr[-300:]}")
    (cycle_dir / "rust-state.json").write_text(rust.stdout)
    (cycle_dir / "python-state.json").write_text(python.stdout)
    diff, _ = run([sys.executable, str(HERE / "tools/json_diff.py"), str(cycle_dir / "python-state.json"), str(cycle_dir / "rust-state.json")])
    differences = [l for l in diff.stdout.splitlines() if l.strip() and not l.startswith("0 differences")]
    identical = diff.returncode == 0 and (not differences or "0 differences" in diff.stdout)
    return {"identical": identical, "differences": differences[:20], "export_seconds": export_seconds,
            "rust_seconds": rust_seconds, "python_seconds": python_seconds}, export


def projection_parity(shadow: Path, export: Path, cycle_dir: Path):
    db = cycle_dir / "rust-projection" / "custody.lbdb"
    result, seconds = run([str(TARGET / "kammi-projector.exe"), "project", "--bulk", "--store", str(shadow), "--db", str(db), "--memory-dims", "384"])
    if result.returncode != 0:
        raise RuntimeError("projector failed: " + result.stderr[-500:])
    probe = (
        "import json, sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from projection_parity import dump\n"
        "from memory_differential import memory_rows\n"
        "py, rs = dump(sys.argv[2]), dump(sys.argv[3])\n"
        "tables = json.loads(sys.argv[4])\n"
        "out = {}\n"
        "for t in tables:\n"
        "    a, b = py.get(t, []), rs.get(t, [])\n"
        "    if t == 'Entity':\n"
        "        a = [r for r in a if json.loads(r)[1] is not None]  # Python memory tags share Entity (kind null)\n"
        "    out[t] = {'python': len(a), 'rust': len(b), 'identical': a == b}\n"
        "pm, rm = memory_rows(sys.argv[2], 'Entity'), memory_rows(sys.argv[3], 'MemoryTag')\n"
        "for t in pm: out['memory:' + t] = {'python': len(pm[t]), 'rust': len(rm[t]), 'identical': pm[t] == rm[t]}\n"
        "print(json.dumps(out))\n"
    )
    compare, _ = run([sys.executable, "-c", probe, str(HERE / "tools"), str(export / "custody.lbdb"), str(db), json.dumps(CUSTODY_TABLES)], cwd=PY)
    if compare.returncode != 0:
        raise RuntimeError("projection compare failed: " + compare.stderr[-800:])
    tables = json.loads(compare.stdout)
    return {"identical": all(t["identical"] for t in tables.values()), "bulk_seconds": seconds,
            "differing": {k: v for k, v in tables.items() if not v["identical"]}, "tables": len(tables)}


def memory_scopes(export: Path):
    """Distinct scopes of the memory records in a v1 export (read from its memory journal)."""
    journal = export / "memory" / "journal" / "events.log"
    if not journal.exists():
        return {}
    data, off, records = journal.read_bytes(), 0, {}
    while off + 4 <= len(data):
        length = struct.unpack(">I", data[off:off + 4])[0]
        event = json.loads(data[off + 4:off + 4 + length])
        off += 4 + length + 32
        if event["type"] != "MemoryRecorded":
            continue
        digest = event["payload_artifact"][7:]
        payload = json.loads((export / "objects/sha256" / digest[:2] / digest[2:]).read_bytes())
        digest = payload["record_artifact_id"][7:]
        record = json.loads((export / "objects/sha256" / digest[:2] / digest[2:]).read_bytes())
        records[record["memory_id"]] = record
    return records


def search_spot_check(shadow: Path, export: Path, cycle_dir: Path):
    records = memory_scopes(export)
    if not records:
        return {"identical": True, "note": "live store holds no memory records", "queries": 0}
    py_copy, rs_copy = cycle_dir / "b4-python", cycle_dir / "b4-rust"
    shutil.copytree(export, py_copy, ignore=shutil.ignore_patterns("custody.lbdb*", "projection*", "locks"))
    shutil.copytree(shadow, rs_copy, ignore=shutil.ignore_patterns("projection", "locks"))
    clock = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    key = cycle_dir / "b4-signing"
    key.write_bytes(hashlib.sha256(b"shadow").digest())
    common = {"KAMMI_SIGNING_KEY_FILE": str(key), "KAMMI_TEST_CLOCK": clock}
    python = Side("python", py_copy, [sys.executable, str(HERE / "tools/py_fixed_clock.py")], {**common, "KAMMI_EMBEDDING_CACHE": str(CACHE)}, PY)
    rust = Side("rust", rs_copy, [str(TARGET / "kammi-ledgerd.exe")], {**common, "KAMMI_EMBEDDER": "bge"}, HERE)
    python.startup_timeout = rust.startup_timeout = 1200  # a live-sized copy: 1.2 GB re-hash + projection rebuild
    scopes = sorted({r["scope"] for r in records.values()})
    queries = sorted({" ".join(r["text"].split()[:6]) for r in records.values()})[:10] + ["custody evidence", "lease failure", "schema adapter"]
    try:
        for side in (python, rust):
            side.start()
            for n, scope in enumerate(scopes):
                token = f"shadow-probe-{n}"
                side.call(f"actor-{n}", "POST", "/v1/actors", {"actor_id": f"shadow-probe-{n}", "kind": "agent", "lab": scope,
                          "credential_sha256": hashlib.sha256(token.encode()).hexdigest(), "request_id": f"shadow-probe-actor-{n}"})
                for q, query in enumerate(queries):
                    for mode in ("fts", "vector", "hybrid"):
                        side.call(f"{mode}-{n}-{q}", "POST", "/v1/memory/search", {"query": query, "scope": scope, "actor_id": f"shadow-probe-{n}",
                                  "mode": mode, "limit": 10, "request_id": f"shadow-{mode}-{n}-{q}"}, token=token, expect=None)
                for m, memory_id in enumerate(sorted(i for i, r in records.items() if r["scope"] == scope)):
                    side.call(f"graph-{n}-{m}", "POST", "/v1/memory/search", {"query": "graph", "scope": scope, "actor_id": f"shadow-probe-{n}",
                              "mode": "graph", "seed_memory": memory_id, "limit": 10, "request_id": f"shadow-graph-{n}-{m}"}, token=token, expect=None)
                    side.call(f"trace-{n}-{m}", "GET", f"/v1/memory/{memory_id}/trace?actor_id=shadow-probe-{n}", token=token, expect=None)
            side.stop()
    finally:
        for side in (python, rust):
            side.stop()
            for log in side.logs:
                log.close()
    mismatches = [label for (label, ps, pb, _), (_, rs_, rb, _) in zip(python.transcript, rust.transcript) if (ps, pb) != (rs_, rb)]
    return {"identical": not mismatches and len(python.transcript) == len(rust.transcript), "steps": len(python.transcript),
            "memories": len(records), "scopes": scopes, "mismatches": mismatches[:10]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--live", type=Path, default=LIVE)
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--interval-minutes", type=float, default=10)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    shadow = work / "shadow-v2"
    cycles = []
    for cycle in range(1, args.cycles + 1):
        started = time.time()
        cycle_dir = work / f"cycle-{cycle}"
        if cycle_dir.exists():
            shutil.rmtree(cycle_dir)
        cycle_dir.mkdir()
        entry = {"cycle": cycle, "utc": datetime.now(timezone.utc).isoformat()}
        try:
            before = v1_head(args.live / "journal" / "events.log")
            synced = sync(shadow, args.live)
            after = v1_head(args.live / "journal" / "events.log")
            live_memory = v1_head(args.live / "memory" / "journal" / "events.log")
            # The live store may advance during the sync; the shadow must equal one of the observed heads.
            entry["B1"] = {"pass": synced["main_head"] in (before[1], after[1]) and synced["memory_head"] == live_memory[1],
                           "live_events": after[0], "live_head": after[1], "shadow_head": synced["main_head"],
                           "live_memory_events": live_memory[0], "sync": synced["report"], "sync_seconds": synced["seconds"]}
            parity, export = state_parity(shadow, cycle_dir)
            entry["B2"] = {"pass": parity["identical"], **parity}
            if cycle in (1, args.cycles):
                projection = projection_parity(shadow, export, cycle_dir)
                entry["B3"] = {"pass": projection["identical"], **projection}
            if cycle == args.cycles:
                spot = search_spot_check(shadow, export, cycle_dir)
                entry["B4"] = {"pass": spot["identical"], **spot}
            shutil.rmtree(export, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            entry["error"] = f"{type(exc).__name__}: {exc}"
        entry["seconds"] = round(time.time() - started, 1)
        cycles.append(entry)
        print(json.dumps({k: (v if not isinstance(v, dict) else {kk: vv for kk, vv in v.items() if kk in ("pass", "live_events", "differing", "differences", "steps", "mismatches")})
                          for k, v in entry.items()}), flush=True)
        report = {"schema": "KAMMI_PHASE4_SHADOW_V1", "live": str(args.live), "cycles": cycles}
        gates = {}
        for gate in ("B1", "B2", "B3", "B4"):
            seen = [c[gate]["pass"] for c in cycles if gate in c]
            gates[gate] = bool(seen) and all(seen)
        report["gates"] = gates
        report["errors"] = [c["error"] for c in cycles if "error" in c]
        report["status"] = "PASS" if cycle == args.cycles and all(gates.values()) and not report["errors"] else ("RUNNING" if cycle < args.cycles else "FAIL")
        if args.output:
            args.output.write_text(json.dumps(report, indent=2, default=str))
        if cycle < args.cycles:
            time.sleep(max(0, args.interval_minutes * 60 - (time.time() - started)))
    print(json.dumps({"status": report["status"], "gates": report["gates"], "errors": report["errors"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
