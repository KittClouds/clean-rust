"""Phase 4A: Rust-only stress (Python does not participate).

  python tools/stress_test.py <work dir> [--only A1,A2,...] [--soak-minutes 30] [--scale 1000000]

Each scenario runs a fresh daemon (+ supervised projector, bge memory) on a fresh E4 import,
drives it with concurrent keep-alive clients, then checks invariants from the journal itself
(export-v1 of the store after the run), never from the daemon's own answers.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import random
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from http_differential import PY, TARGET, Side  # noqa: E402

ADMIN = "cleanroom-admin"
RUN, STAGE, LAB = "stress.run", "STRESS", "library"
NATIVE = PY / "vendor/runtime-v1/native"
ENV = {**os.environ, "PATH": str(NATIVE) + os.pathsep + os.environ.get("PATH", "")}


# ------------------------------------------------------------------ clients


class Client:
    """One keep-alive connection; reconnects on failure."""

    def __init__(self, port):
        self.port = port
        self.conn = None

    def call(self, method, path, body=None, token=ADMIN, timeout=120):
        if self.conn is None:
            self.conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
        headers = {"Authorization": "Bearer " + token}
        if data is not None:
            headers["Content-Type"] = "application/json"
        try:
            self.conn.request(method, path, body=data, headers=headers)
            response = self.conn.getresponse()
            raw = response.read()
            return response.status, (json.loads(raw) if raw else None)
        except (OSError, http.client.HTTPException):
            self.conn.close()
            self.conn = None
            raise

    def retry(self, method, path, body=None, token=ADMIN, until=600):
        """Same request (same request ID) until the daemon answers: idempotent retry."""
        deadline = time.time() + until
        while True:
            try:
                return self.call(method, path, body, token)
            except (OSError, http.client.HTTPException):
                if time.time() > deadline:
                    raise
                time.sleep(0.2)


def token_of(actor):
    return "stress-token-" + actor


# A1 and A7 run with the fixed clock after the rollback-window floor, so their stores can take
# the journaled v4 activation (neither depends on the clock: no leases, no grant expiry).
V4_CLOCK = {"KAMMI_TEST_CLOCK": "2026-10-07T00:00:00Z"}


def activate_v4(port, workspaces, owner="a0"):
    """Journaled activation on a stress store (fixture decision and verification), then workspaces."""
    c = Client(port)

    def register(obj, kind, request):
        raw = json.dumps(obj).encode()
        status, body = c.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(), "kind": kind, "actor": "auditor", "request_id": request})
        assert status == 200, body
        return body["artifact_id"]

    closure = register({"schema": "KAMMI_ROLLBACK_WINDOW_CLOSURE_V1", "decision": "CLOSE", "decided_by": "stress fixture"}, "decision", "v4-closure")
    backup = register({"backup": "stress fixture"}, "backup", "v4-backup")
    head = c.call("GET", "/v1/status")[1]["journal_head"]
    verification = register({"status": "PASS", "journal_head": head, "verifier": "stress fixture"}, "verification", "v4-verification")
    status, body = c.call("POST", "/v2/vocabulary/activate", {"vocabulary": "v4", "not_before": "2026-10-06T00:00:00Z", "closure_decision": closure,
                          "verification": verification, "backup": backup, "request_id": "v4-activate"})
    assert status == 200, body
    heads = {}
    for w in workspaces:
        status, body = c.call("POST", "/v2/workspaces", {"workspace_id": w, "title": w, "lab": LAB, "owners": [owner], "request_id": f"ws-{w}"})
        assert status == 200, body
        heads[w] = body["head"]
    return heads


def independent_verify(store: Path):
    r = subprocess.run([str(TARGET / "kammi-verify.exe"), str(store)], capture_output=True, text=True)
    report = json.loads(r.stdout) if r.stdout.strip() else {"status": "CRASH"}
    return report.get("status") == "PASS", {k: report.get(k) for k in ("status", "journal_events", "workspaces", "receipts_events", "errors")}


def setup(port, actors=16, resources=4):
    c = Client(port)
    for i in range(actors):
        a = f"a{i}"
        assert c.call("POST", "/v1/actors", {"actor_id": a, "kind": "agent", "lab": LAB,
                      "credential_sha256": hashlib.sha256(token_of(a).encode()).hexdigest(), "request_id": "actor-" + a})[0] == 200
    assert c.call("POST", "/v1/runs", {"run_id": RUN, "lab": LAB, "actor": "auditor", "request_id": "run"})[0] == 200
    status, body = c.call("POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": STAGE, "version": "v1",
                          "requires": {"actor": "AUTHORIZED"}, "forbids": {}}, "request_id": "policy"})
    assert status == 200, body
    expiry = "2099-01-01T00:00:00+00:00"
    for i in range(actors):
        assert c.call("POST", "/v1/grants", {"grant_id": f"lease-{i}", "run_id": RUN, "stage_id": STAGE, "actor_id": f"a{i}",
                      "action": "acquire_lease", "policy_hash": body["policy_hash"], "expires_utc": expiry, "request_id": f"grant-{i}"})[0] == 200
    for r in range(resources):
        assert c.call("POST", "/v1/resources", {"resource_id": f"r{r}", "kind": "GPU", "host": "local", "constraints": {},
                      "request_id": f"resource-{r}"})[0] == 200


# ------------------------------------------------------------------ journal analysis


def export_and_read(store: Path, work: Path):
    """Parses the v2 main journal segments directly (payloads travel inline, so no export).

    Segment: 16-byte header, then frames `body_len u32 LE | kind u8 | event_len u32 LE |
    event JCS | payload | sha256(body)`. Every frame's checksum is re-verified here.
    """
    events, payloads = [], {}
    for segment in sorted((store / "journal" / "main").glob("seg-*.seg")):
        data, off = segment.read_bytes(), 16
        while off + 4 <= len(data):
            body_len = struct.unpack("<I", data[off:off + 4])[0]
            if body_len == 0 or off + 4 + body_len + 32 > len(data):
                break
            body = data[off + 4:off + 4 + body_len]
            if hashlib.sha256(body).digest() != data[off + 4 + body_len:off + 4 + body_len + 32]:
                raise AssertionError(f"frame checksum mismatch in {segment.name} at {off}")
            event_len = struct.unpack("<I", body[1:5])[0]
            raw = body[5:5 + event_len]
            event = json.loads(raw)
            event["_id"] = "sha256:" + hashlib.sha256(b"kammi-event-v1\0" + raw).hexdigest()
            payloads[event["_id"]] = body[5 + event_len:]
            events.append(event)
            off += 4 + body_len + 32
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1)), "journal sequence is not contiguous"

    def payload(event):
        return json.loads(payloads[event["_id"]])

    return events, payload


def exactly_once(events, acked: dict):
    counts = Counter(e["request_id"] for e in events)
    ids = {e["request_id"]: e["_id"] for e in events}
    lost = [r for r in acked if counts[r] == 0]
    duplicated = [r for r in acked if counts[r] > 1]
    mismatched = [r for r, event_id in acked.items() if event_id and ids.get(r) != event_id]
    return {"acknowledged": len(acked), "lost": len(lost), "duplicated": len(duplicated), "event_id_mismatch": len(mismatched),
            "examples": (lost + duplicated + mismatched)[:5]}


def lease_invariant(events, payload):
    active, fencing, violations, grants = {}, defaultdict(int), [], 0
    for e in events:
        kind = e["type"]
        if kind not in ("LeaseGranted", "LeaseReleased", "LeaseExpired"):
            continue
        p = payload(e)
        rid = p["resource_id"]
        if kind == "LeaseGranted":
            grants += 1
            if active.get(rid):
                violations.append(f"seq {e['seq']}: {rid} granted while {active[rid]} active")
            if p["fencing_token"] != fencing[rid] + 1:
                violations.append(f"seq {e['seq']}: {rid} token {p['fencing_token']} after {fencing[rid]}")
            fencing[rid] = p["fencing_token"]
            active[rid] = p["lease_id"]
        elif active.get(rid) == p["lease_id"]:
            active[rid] = None
    return {"grants": grants, "violations": len(violations), "examples": violations[:5], "final_tokens": dict(fencing)}


def verify_store(store: Path):
    r = subprocess.run([str(TARGET / "kammi-migrate.exe"), "verify", "--v2", str(store)], capture_output=True, text=True)
    return r.returncode == 0, (r.stdout[-400:] if r.returncode == 0 else r.stderr[-400:])


def verify_projection(store: Path):
    db = store / "projection" / "custody.lbdb"
    r = subprocess.run([str(TARGET / "kammi-projector.exe"), "verify", "--deep", "--store", str(store), "--db", str(db)],
                       capture_output=True, text=True, env=ENV)
    return '"verified":true' in r.stdout, (r.stdout.strip() or r.stderr.strip())[:300]


def rss_mb(pid):
    if not pid:
        return None
    out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True, text=True).stdout
    m = re.search(r'"([\d,.\s]+) K"', out)
    return round(int(re.sub(r"[^\d]", "", m.group(1))) / 1024, 1) if m else None


# ------------------------------------------------------------------ harness


RIGS = []


class Rig:
    def __init__(self, work: Path, name: str, embedder="bge"):
        RIGS.append(self)
        self.dir = work / name
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.store = self.dir / "store"
        subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/e4-import"), "--v2", str(self.store)],
                       check=True, stdout=subprocess.DEVNULL)
        key = self.dir / "signing"
        key.write_bytes(hashlib.sha256(b"stress").digest())
        self.side = Side("rust", self.store, [str(TARGET / "kammi-ledgerd.exe")],
                         {"KAMMI_SIGNING_KEY_FILE": str(key), "KAMMI_EMBEDDER": embedder}, HERE)
        self.side.root = self.dir / "store"

    def start(self, extra=None):
        seconds = self.side.start(extra)
        return seconds

    def status(self):
        return Client(self.side.port).call("GET", "/v1/status")[1]

    def wait_projection(self, timeout=300):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = self.status()
                if s.get("projection_lag") == 0 and s["projection"].get("memory_lag") == 0 and s["projection"]["process"] == "RUNNING":
                    return s
            except Exception:
                pass
            time.sleep(0.5)
        raise AssertionError("projection did not converge")

    def daemon_pid(self):
        return self.side.process.pid if self.side.process else None

    def projector_pid(self):
        try:
            return self.status()["projection"]["pid"]
        except Exception:
            return None

    def stop(self):
        self.side.stop()
        time.sleep(1)


def run_threads(n, target, seconds):
    stop = threading.Event()
    results = [dict() for _ in range(n)]
    threads = [threading.Thread(target=target, args=(i, stop, results[i]), daemon=True) for i in range(n)]
    for t in threads:
        t.start()
    time.sleep(seconds)
    stop.set()
    for t in threads:
        t.join(timeout=600)
    return results


# ------------------------------------------------------------------ scenarios


def a1(work, seconds):
    rig = Rig(work, "a1")
    rig.start(V4_CLOCK)
    setup(rig.side.port)
    port = rig.side.port
    heads = activate_v4(port, [f"ws{i}" for i in range(4)] + ["ws-shared"])

    def writer(i, stop, out):
        c, acked, statuses, n = Client(port), {}, Counter(), 0
        ws_statuses, conflicts = Counter(), 0
        head = heads.get(f"ws{i}")
        while not stop.is_set():
            n += 1
            rid = f"w{i}-{n}"
            if i < 4:
                # One writer per workspace: its own HEAD chain, never stale.
                body = {"type": "WorkspaceNoteRecorded", "payload": {"expected_head": head, "note_id": f"n{i}-{n}", "text": f"a1 note {rid}", "refs": []},
                        "actor_id": "a0", "request_id": rid}
                status, reply = c.retry("POST", f"/v2/workspaces/ws{i}/commands", body)
                ws_statuses[status] += 1
                if status == 200:
                    head = reply["head"]
                    acked[rid] = reply["event_id"]
                continue
            if i < 8:
                # Contending writers on one workspace: read HEAD, write, and on 409 read again.
                current = c.retry("GET", "/v2/workspaces/ws-shared")[1]["head"]
                body = {"type": "WorkspaceNoteRecorded", "payload": {"expected_head": current, "note_id": f"s{i}-{n}", "text": f"a1 shared {rid}", "refs": []},
                        "actor_id": "a0", "request_id": rid}
                status, reply = c.retry("POST", "/v2/workspaces/ws-shared/commands", body)
                ws_statuses[status] += 1
                if status == 200:
                    acked[rid] = reply["event_id"]
                elif status == 409:
                    conflicts += 1
                continue
            if n % 5 == 0:
                status, body = c.retry("POST", "/v1/runs", {"run_id": "run-" + rid, "lab": LAB, "actor": "auditor", "request_id": rid})
            else:
                raw = f"a1 {rid} {'z' * (n % 200)}".encode()
                status, body = c.retry("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(), "kind": "stress",
                                       "actor": "auditor", "request_id": rid})
            statuses[status] += 1
            if status == 200:
                acked[rid] = body["event_id"]
        out.update(acked=acked, statuses=statuses, ws_statuses=ws_statuses, conflicts=conflicts)

    started = time.time()
    results = run_threads(32, writer, seconds)
    elapsed = time.time() - started
    rig.wait_projection()
    rig.stop()
    acked = {k: v for r in results for k, v in r["acked"].items()}
    statuses = sum((r["statuses"] for r in results), Counter())
    ws_own = sum((r["ws_statuses"] for r in results[:4]), Counter())
    ws_shared = sum((r["ws_statuses"] for r in results[4:8]), Counter())
    conflicts = sum(r["conflicts"] for r in results)
    events, _ = export_and_read(rig.store, rig.dir)
    once = exactly_once(events, acked)
    store_ok, store_detail = verify_store(rig.store)
    proj_ok, proj_detail = verify_projection(rig.store)
    indep_ok, indep = independent_verify(rig.store)
    ok = (once["lost"] == 0 and once["duplicated"] == 0 and once["event_id_mismatch"] == 0 and set(statuses) == {200} and store_ok and proj_ok
          and set(ws_own) == {200} and set(ws_shared) <= {200, 409} and ws_shared[200] > 0 and indep_ok)
    total = sum(statuses.values()) + sum(ws_own.values()) + sum(ws_shared.values())
    return ok, {"clients": 32, "seconds": round(elapsed, 1), "writes": total, "writes_per_second": round(total / elapsed),
                "statuses": dict(statuses), "workspace": {"own_writer_statuses": dict(ws_own), "shared_writer_statuses": dict(ws_shared), "conflicts_recovered": conflicts},
                "exactly_once": once, "store_verify": store_ok, "projection_deep_verify": proj_ok, "projection": proj_detail, "independent_verify": indep}


def a2(work, seconds):
    rig = Rig(work, "a2")
    rig.start()
    setup(rig.side.port)
    port = rig.side.port

    def worker(i, stop, out):
        c, actor, n = Client(port), f"a{i}", 0
        tally, stale = Counter(), Counter()
        while not stop.is_set():
            n += 1
            rid = f"l{i}-{n}"
            body = {"run_id": RUN, "stage_id": STAGE, "actor_id": actor, "resource_id": f"r{random.randrange(4)}",
                    "purpose": "stress", "ttl_seconds": 2, "request_id": rid}
            status, reply = c.retry("POST", "/v1/leases/acquire", body, token=token_of(actor))
            receipt = (reply or {}).get("receipt", {})
            tally[f"acquire:{status}:{receipt.get('decision')}"] += 1
            if receipt.get("decision") != "GRANTED":
                time.sleep(random.random() * 0.05)
                continue
            lease, token = receipt["lease_id"], receipt["fencing_token"]
            time.sleep(random.random() * 0.3)
            if random.random() < 0.5:
                status, _ = c.retry("POST", f"/v1/leases/{lease}/renew", {"actor_id": actor, "fencing_token": token, "ttl_seconds": 2,
                                    "request_id": rid + "-renew"}, token=token_of(actor))
                tally[f"renew:{status}"] += 1
            status, _ = c.retry("POST", f"/v1/leases/{lease}/release", {"actor_id": actor, "fencing_token": token,
                                "request_id": rid + "-release"}, token=token_of(actor))
            tally[f"release:{status}"] += 1
            # Stale fence after release: must be refused.
            status, _ = c.retry("POST", f"/v1/leases/{lease}/renew", {"actor_id": actor, "fencing_token": token, "ttl_seconds": 2,
                                "request_id": rid + "-stale"}, token=token_of(actor))
            stale[status] += 1
        out.update(tally=tally, stale=stale)

    results = run_threads(16, worker, seconds)
    rig.stop()
    tally = sum((r["tally"] for r in results), Counter())
    stale = sum((r["stale"] for r in results), Counter())
    events, payload = export_and_read(rig.store, rig.dir)
    invariant = lease_invariant(events, payload)
    store_ok, _ = verify_store(rig.store)
    ok = invariant["violations"] == 0 and invariant["grants"] > 0 and set(stale) == {400} and store_ok
    return ok, {"workers": 16, "resources": 4, "seconds": seconds, "operations": dict(tally), "stale_renew_statuses": dict(stale),
                "journal_invariant": invariant, "store_verify": store_ok}


def a3(work, kills, interval):
    rig = Rig(work, "a3")
    rig.start()
    setup(rig.side.port)
    port = rig.side.port
    issued, lock = {}, threading.Lock()

    def writer(i, stop, out):
        c, n, acked = Client(port), 0, {}
        while not stop.is_set():
            n += 1
            rid = f"k{i}-{n}"
            raw = f"a3 {rid}".encode()
            with lock:
                issued[rid] = True
            status, body = c.retry("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(), "kind": "stress",
                                   "actor": "auditor", "request_id": rid})
            if status == 200:
                acked[rid] = body["event_id"]
        out.update(acked=acked)

    stop = threading.Event()
    results = [dict() for _ in range(16)]
    threads = [threading.Thread(target=writer, args=(i, stop, results[i]), daemon=True) for i in range(16)]
    for t in threads:
        t.start()
    restarts = []
    for _ in range(kills):
        time.sleep(interval)
        pid = rig.daemon_pid()
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        rig.side.process.wait(timeout=30)
        started = time.time()
        rig.side.start()
        restarts.append(round(time.time() - started, 2))
    time.sleep(interval)
    stop.set()
    for t in threads:
        t.join(timeout=600)
    converged = rig.wait_projection()
    rig.stop()
    acked = {k: v for r in results for k, v in r["acked"].items()}
    events, _ = export_and_read(rig.store, rig.dir)
    once = exactly_once(events, acked)
    never_acked = [r for r in issued if r not in acked]
    store_ok, _ = verify_store(rig.store)
    proj_ok, proj_detail = verify_projection(rig.store)
    ok = once["lost"] == 0 and once["duplicated"] == 0 and once["event_id_mismatch"] == 0 and not never_acked and store_ok and proj_ok
    return ok, {"hard_kills": kills, "restart_seconds": restarts, "exactly_once": once, "requests_never_acknowledged": len(never_acked),
                "store_verify": store_ok, "projection_deep_verify": proj_ok, "projection_restarts": converged["projection"]["restarts"]}


def a4_a5(work, seconds, kill_every):
    rig = Rig(work, "a4")
    rig.start()
    setup(rig.side.port)
    port = rig.side.port
    for i in range(8):
        Client(port).call("POST", "/v1/actors", {"actor_id": f"m{i}", "kind": "agent", "lab": LAB,
                          "credential_sha256": hashlib.sha256(token_of(f"m{i}").encode()).hexdigest(), "request_id": f"actor-m{i}"})

    def writer(i, stop, out):
        c, n, statuses = Client(port), 0, Counter()
        while not stop.is_set():
            n += 1
            raw = f"a4 w{i}-{n}".encode()
            status, _ = c.retry("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(), "kind": "stress",
                                "actor": "auditor", "request_id": f"a4w{i}-{n}"})
            statuses[status] += 1
        out.update(statuses=statuses)

    def memory(i, stop, out):
        c, n, actor = Client(port), 0, f"m{i}"
        record_statuses, search_statuses, own, own_checked = Counter(), Counter(), 0, 0
        while not stop.is_set():
            n += 1
            # One purely alphabetic token: Ladybug's FTS tokenizer splits letter/digit runs, and
            # markers such as qz1x7q share subtokens, so every stress memory would match lexically.
            marker = "".join(chr(97 + b % 26) for b in hashlib.sha256(f"a5-{i}-{n}".encode()).digest()[:12])
            status, body = c.retry("POST", "/v1/memory", {"kind": "INTERPRETIVE", "scope": LAB, "text": f"stress memory {marker} about lease churn",
                                   "actor_id": actor, "tags": [f"s{i % 3}"], "request_id": f"mem-{i}-{n}"}, token=token_of(actor))
            record_statuses[status] += 1
            memory_id = (body or {}).get("memory_id")
            status, result = c.retry("POST", "/v1/memory/search", {"query": marker, "scope": LAB, "actor_id": actor, "mode": "hybrid",
                                     "limit": 10, "request_id": f"search-{i}-{n}"}, token=token_of(actor))
            search_statuses[status] += 1
            if status == 200 and memory_id:
                own_checked += 1
                own += memory_id in [r["memory"]["memory_id"] for r in result["results"]]
        out.update(record=record_statuses, search=search_statuses, own=own, own_checked=own_checked)

    stop = threading.Event()
    writer_out = [dict() for _ in range(8)]
    memory_out = [dict() for _ in range(4)]
    threads = [threading.Thread(target=writer, args=(i, stop, writer_out[i]), daemon=True) for i in range(8)]
    threads += [threading.Thread(target=memory, args=(i, stop, memory_out[i]), daemon=True) for i in range(4)]
    for t in threads:
        t.start()
    kills, deadline = 0, time.time() + seconds
    while time.time() < deadline:
        time.sleep(kill_every)
        pid = rig.projector_pid()
        if pid:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
            kills += 1
    stop.set()
    for t in threads:
        t.join(timeout=600)
    converged = rig.wait_projection()
    rig.stop()
    writes = sum((o["statuses"] for o in writer_out), Counter())
    records = sum((o["record"] for o in memory_out), Counter())
    searches = sum((o["search"] for o in memory_out), Counter())
    own = sum(o["own"] for o in memory_out)
    checked = sum(o["own_checked"] for o in memory_out)
    proj_ok, proj_detail = verify_projection(rig.store)
    store_ok, _ = verify_store(rig.store)
    a4_ok = set(writes) == {200} and set(records) == {200} and set(searches) <= {200, 503} and proj_ok and store_ok
    a5_ok = checked > 0 and own == checked and set(searches) <= {200, 503}
    return (a4_ok, {"seconds": seconds, "projector_kills": kills, "projector_restarts": converged["projection"]["restarts"],
                    "custody_write_statuses": dict(writes), "memory_record_statuses": dict(records), "search_statuses": dict(searches),
                    "projection_deep_verify": proj_ok, "projection": proj_detail, "store_verify": store_ok}), \
           (a5_ok, {"searches_with_own_write_checked": checked, "saw_own_write": own, "search_statuses": dict(searches),
                    "note": "a search answered 503 during a projector outage is not checked for read-your-writes"})


def a6(work, events):
    rig = Rig(work, "a6", embedder="bge")
    synth = subprocess.run([str(TARGET / "kammi-synth.exe"), str(rig.store), str(events)], capture_output=True, text=True, check=True)
    generated = json.loads(synth.stdout)
    started = time.time()
    rig.start()
    daemon_ready = time.time() - started
    log = Path(rig.side.logs[-1].name)
    time.sleep(1)
    replay = re.search(r"replayed (\d+) events in ([\d.]+)s", log.read_text())
    daemon_rss = rss_mb(rig.daemon_pid())
    t = time.time()
    converged = rig.wait_projection(timeout=3600)
    projection_ready = time.time() - t
    bulk = re.search(r"bulk-loaded (\d+) events in ([\d.]+)s", log.read_text())
    projector_rss = rss_mb(converged["projection"]["pid"])
    # live catch-up: 5,000 API writes while the projector follows
    c = Client(rig.side.port)
    t = time.time()
    for n in range(5000):
        c.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(f"catchup {n}".encode()).decode(), "kind": "stress",
               "actor": "auditor", "request_id": f"catchup-{n}"})
    write_seconds = time.time() - t
    t = time.time()
    rig.wait_projection(timeout=600)
    drain = time.time() - t
    daemon_rss_after = rss_mb(rig.daemon_pid())
    rig.stop()
    t = time.time()
    store_ok, _ = verify_store(rig.store)
    verify_seconds = time.time() - t
    t = time.time()
    proj_ok, proj_detail = verify_projection(rig.store)
    deep_seconds = time.time() - t
    ok = store_ok and proj_ok
    return ok, {"synthetic_events": generated["appended"], "journal_events": generated["seq"], "synth_events_per_second": round(generated["events_per_second"]),
                "daemon_replay_seconds": float(replay.group(2)) if replay else None, "daemon_ready_seconds": round(daemon_ready, 1),
                "daemon_rss_mb": daemon_rss, "daemon_rss_mb_after_5k_writes": daemon_rss_after,
                "projector_bulk_load": {"events": int(bulk.group(1)), "seconds": float(bulk.group(2))} if bulk else None,
                "projection_ready_seconds": round(projection_ready, 1), "projector_rss_mb": projector_rss,
                "live_writes": 5000, "live_write_seconds": round(write_seconds, 1), "catch_up_drain_seconds": round(drain, 2),
                "store_deep_verify_seconds": round(verify_seconds, 1), "store_verify": store_ok,
                "projection_deep_verify_seconds": round(deep_seconds, 1), "projection_deep_verify": proj_ok, "projection": proj_detail}


def a7(work, minutes, kill_every):
    rig = Rig(work, "a7")
    rig.start(V4_CLOCK)
    setup(rig.side.port)
    port = rig.side.port
    activate_v4(port, ["soak-ws"])
    Client(port).call("POST", "/v1/actors", {"actor_id": "soak", "kind": "agent", "lab": LAB,
                      "credential_sha256": hashlib.sha256(token_of("soak").encode()).hexdigest(), "request_id": "actor-soak"})
    samples, statuses, lock = [], Counter(), threading.Lock()

    def load(i, stop, out):
        c, n = Client(port), 0
        while not stop.is_set():
            n += 1
            if i == 0 and n % 10 == 0:
                status, _ = c.retry("POST", "/v1/memory", {"kind": "INTERPRETIVE", "scope": LAB, "text": f"soak memory {n} about restarts and leases",
                                    "actor_id": "soak", "tags": ["soak"], "request_id": f"soak-m-{n}"}, token=token_of("soak"))
            elif i == 2 and n % 10 == 0:
                current = c.retry("GET", "/v2/workspaces/soak-ws")[1]["head"]
                status, _ = c.retry("POST", "/v2/workspaces/soak-ws/commands", {"type": "WorkspaceNoteRecorded", "actor_id": "a0", "request_id": f"soak-ws-{n}",
                                    "payload": {"expected_head": current, "note_id": f"n{n}", "text": f"soak note {n}", "refs": []}})
            elif i == 3 and n % 7 == 0:
                status, _ = c.retry("POST", "/v2/recall", {"query": "soak note", "scope": "workspace:soak-ws", "actor_id": "a0", "request_id": f"soak-recall-{n}"})
            elif i == 1 and n % 5 == 0:
                status, _ = c.retry("POST", "/v1/memory/search", {"query": "restarts leases", "scope": LAB, "actor_id": "soak", "mode": "hybrid",
                                    "limit": 10, "request_id": f"soak-s-{n}"}, token=token_of("soak"))
            else:
                status, _ = c.retry("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(f"soak {i}-{n}".encode()).decode(),
                                    "kind": "stress", "actor": "auditor", "request_id": f"soak-{i}-{n}"})
            with lock:
                statuses[status] += 1
            time.sleep(0.02)

    stop = threading.Event()
    threads = [threading.Thread(target=load, args=(i, stop, {}), daemon=True) for i in range(6)]
    for t in threads:
        t.start()
    started, last_kill, kills = time.time(), time.time(), 0
    while time.time() - started < minutes * 60:
        time.sleep(10)
        try:
            events = rig.status()["journal_events"]
        except Exception:  # noqa: BLE001
            events = None
        samples.append({"t": round(time.time() - started), "events": events, "daemon_mb": rss_mb(rig.daemon_pid()),
                        "projector_mb": rss_mb(rig.projector_pid())})
        if time.time() - last_kill > kill_every:
            pid = rig.projector_pid()
            if pid:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                kills += 1
            last_kill = time.time()
    stop.set()
    for t in threads:
        t.join(timeout=600)
    final = rig.wait_projection()
    time.sleep(10)
    soak_final_mb = rss_mb(rig.daemon_pid())
    final_head, final_events = final["journal_head"], final["journal_events"]
    rig.stop()
    store_ok, _ = verify_store(rig.store)
    proj_ok, proj_detail = verify_projection(rig.store)

    # Fresh replay of the exact final head: the memory the retained state alone needs.
    rig.start()
    fresh_status = rig.wait_projection()
    fresh_samples = []
    for _ in range(4):
        time.sleep(10)
        fresh_samples.append(rss_mb(rig.daemon_pid()))
    rig.stop()
    fresh_mb = sorted(fresh_samples)[len(fresh_samples) // 2]
    same_head = fresh_status["journal_head"] == final_head and fresh_status["journal_events"] == final_events
    no_leak = same_head and soak_final_mb <= 1.10 * fresh_mb

    # Memory as a function of event count (least squares over warm samples), and the residual
    # after conditioning on it: a leak shows up as residual growth over time.
    warm = [s for s in samples[len(samples) // 6:] if s["daemon_mb"] and s["events"]]
    n = len(warm)
    mean_e = sum(s["events"] for s in warm) / n
    mean_m = sum(s["daemon_mb"] for s in warm) / n
    var_e = sum((s["events"] - mean_e) ** 2 for s in warm) or 1.0
    slope = sum((s["events"] - mean_e) * (s["daemon_mb"] - mean_m) for s in warm) / var_e
    residuals = [s["daemon_mb"] - (mean_m + slope * (s["events"] - mean_e)) for s in warm]
    third = max(1, n // 3)
    residual_growth_mb = sum(residuals[-third:]) / third - sum(residuals[:third]) / third
    residual_ok = residual_growth_mb <= 0.05 * fresh_mb

    # The original criterion (last third <= 1.2x first third), kept for the record.
    daemon = [s["daemon_mb"] for s in samples if s["daemon_mb"]]
    legacy = daemon[len(daemon) // 6:]
    lthird = max(1, len(legacy) // 3)
    first, last = sum(legacy[:lthird]) / lthird, sum(legacy[-lthird:]) / lthird
    legacy_ok = last <= 1.2 * first

    indep_ok, indep = independent_verify(rig.store)
    ok = no_leak and residual_ok and store_ok and proj_ok and indep_ok and set(statuses) <= {200, 503, 409}
    return ok, {"criterion": "A7 v2 (amended 2026-09-28): soak-final RSS <= 1.10x fresh-replay RSS at the same head; "
                             "no residual growth (> 5% of fresh RSS) after conditioning on event count",
                "minutes": minutes, "operations": sum(statuses.values()), "statuses": dict(statuses), "projector_kills": kills,
                "final_head": final_head, "final_events": final_events,
                "soak_final_daemon_mb": soak_final_mb, "fresh_replay_daemon_mb": fresh_mb, "fresh_replay_samples_mb": fresh_samples,
                "fresh_replay_same_head": same_head, "soak_to_fresh_ratio": round(soak_final_mb / fresh_mb, 3), "no_leak": no_leak,
                "state_kb_per_event": round(slope * 1024, 2), "residual_growth_mb": round(residual_growth_mb, 1), "residual_ok": residual_ok,
                "original_criterion": {"rule": "last third <= 1.2x first third", "daemon_mb_first_third": round(first, 1),
                                       "daemon_mb_last_third": round(last, 1), "verdict": "PASS" if legacy_ok else "FAIL_BY_SPEC"},
                "daemon_mb_max": max(daemon), "projector_mb_max": max((s["projector_mb"] or 0) for s in samples),
                "samples": samples[:: max(1, len(samples) // 30)], "store_verify": store_ok, "projection_deep_verify": proj_ok,
                "workspace_traffic": "notes on soak-ws and recall into the receipt stream", "independent_verify": indep}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--only", default="A1,A2,A3,A4,A6,A7")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--soak-minutes", type=float, default=30)
    parser.add_argument("--scale", type=int, default=1_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    wanted = set(args.only.split(","))
    report = {"schema": "KAMMI_PHASE4_STRESS_V1", "gates": {}, "evidence": {}}

    def guarded(scenario, *a, **k):
        """Runs a scenario; an exception is a FAIL with its message, and daemons always stop."""
        try:
            return scenario(*a, **k)
        except Exception as exc:  # noqa: BLE001
            import traceback
            return False, {"error": f"{type(exc).__name__}: {exc}", "trace": traceback.format_exc()[-1500:]}
        finally:
            while RIGS:
                RIGS.pop().side.stop()

    def record(name, result):
        ok, evidence = result
        report["gates"][name], report["evidence"][name] = ok, evidence
        print(f"[{name}] {'PASS' if ok else 'FAIL'} {json.dumps(evidence)[:400]}", flush=True)
        if args.output:
            args.output.write_text(json.dumps(report, indent=2, default=str))

    if "A1" in wanted:
        record("A1", guarded(a1, work, args.seconds))
    if "A2" in wanted:
        record("A2", guarded(a2, work, args.seconds))
    if "A3" in wanted:
        record("A3", guarded(a3, work, kills=10, interval=12))
    if "A4" in wanted or "A5" in wanted:
        both = guarded(a4_a5, work, args.seconds, kill_every=5)
        four, five = both if isinstance(both[0], tuple) else (both, both)
        record("A4", four)
        record("A5", five)
    if "A6" in wanted:
        record("A6", guarded(a6, work, args.scale))
    if "A7" in wanted:
        record("A7", guarded(a7, work, args.soak_minutes, kill_every=120))
    report["status"] = "PASS" if report["gates"] and all(report["gates"].values()) else "FAIL"
    if args.output:
        args.output.write_text(json.dumps(report, indent=2, default=str))
    print(json.dumps({"status": report["status"], "gates": report["gates"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
