"""Differential /v1 cleanroom: the same workflow against the Python daemon and the Rust daemon.

Port of `kammi-ledger/scripts/http_cleanroom.py`. Both daemons start from the E4 fixture
(Python on a v1 copy, Rust on its kammi-migrate v2 import). One deterministic workflow runs
against each side and records every (status, body). The transcripts are then compared:

* status codes and error details must be identical;
* JSON shapes (keys, list lengths, types) must be identical;
* identities are compared through a bijection: event IDs embed `utc`, so the two sides mint
  different IDs, but every ID must map one-to-one (the same position always refers to the
  same object). Content IDs of identical bytes come out equal;
* timestamps must both be timestamps; base64 payloads that decode to JSON are compared
  recursively; signatures are compared by presence only;
* memory search ranks come from different embedders (Python bge-small vs a Phoenix runner),
  so only the asserted invariant (the target memory is retrieved) is compared there.

After the workflow, both daemons crash at `journal.after_fsync` (exit 91), restart to the
committed head and repair the retried request without a duplicate event. The Rust store is
then exported to the exact v1 layout and must be accepted by Python's independent verifier
and by a full Python `Ledger` replay.

Usage (from kammi-ledger, with its venv):
  .venv/Scripts/python.exe ../kammi-ledger-rs/tools/http_differential.py <work dir> [--embedder gemma300]
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
sys.path.insert(0, str(PY))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from ledgerd.identity import canonical, strict_json  # noqa: E402
from ledgerd.remote import public_bytes  # noqa: E402
from ledgerd.worker import execute_bundle  # noqa: E402

TARGET = Path(os.environ.get("CARGO_TARGET_DIR", "G:/kammi-ledger-rs-target")) / "release"
ID = re.compile(r"^(sha256:)?[0-9a-f]{64}$|^lease-[0-9a-f]{64}$")
TS = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?$")
SIGNATURES = {"signature_hex", "receipt_signature", "issuer_public_hex"}
# Deliberate /v1 fixes (see README): Python answers these with an unhandled 500.
EXPECTED = {"unknown-memory-get": (500, 404)}
# Same status; the detail is a third-party parser diagnostic (Python json / zipfile vs Rust).
DIAGNOSTIC = {"bad-json", "vault-import-bad-zip"}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class Side:
    def __init__(self, name, root, command, env, cwd):
        self.name, self.root, self.command, self.cwd = name, root, command, cwd
        self.port = free_port()
        self.env = {**os.environ, **env, "KAMMI_ROOT": str(root), "KAMMI_PORT": str(self.port),
                    "KAMMI_TOKEN": "cleanroom-admin", "KAMMI_ACCEPTANCE_MODE": "1"}
        self.url = f"http://127.0.0.1:{self.port}"
        self.process = None
        self.transcript = []
        self.logs = []

    def start(self, extra=None):
        log = (self.root.parent / f"{self.name}-daemon-{len(self.logs)}.log").open("w")
        self.logs.append(log)
        self.process = subprocess.Popen(self.command, cwd=self.cwd, env={**self.env, **(extra or {})}, stdout=log, stderr=log)
        started = time.time()
        while time.time() - started < 180:
            if self.process.poll() is not None:
                log.flush()
                raise RuntimeError(f"{self.name} daemon exited: " + Path(log.name).read_text())
            try:
                status, _ = self.raw("GET", "/v1/status", token="cleanroom-admin")
                if status == 200:
                    return time.time() - started
            except OSError:
                pass
            time.sleep(0.05)
        raise RuntimeError(f"{self.name} daemon startup timed out")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process = None

    def raw(self, method, path, body=None, token=None, headers=None, data=None):
        request = urllib.request.Request(self.url + path, method=method)
        if token:
            request.add_header("Authorization", "Bearer " + token)
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        if data is None and body is not None:
            data = canonical(body) if not isinstance(body, bytes) else body
        if data is not None and "Content-Type" not in (headers or {}):
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, data=data, timeout=600) as response:
                return response.status, (response.read(), dict(response.headers))
        except urllib.error.HTTPError as error:
            return error.code, (error.read(), dict(error.headers))

    def call(self, label, method, path, body=None, token="cleanroom-admin", headers=None, data=None, expect=200, record=True):
        status, (raw, response_headers) = self.raw(method, path, body, token, headers, data)
        try:
            parsed = json.loads(raw) if raw else None
        except ValueError:
            parsed = unzip_entries(raw) or {"__bytes_sha256": hashlib.sha256(raw).hexdigest(), "__len": len(raw)}
        if record:
            kept = {k.lower(): v for k, v in response_headers.items() if k.lower().startswith("x-") or k.lower() == "content-type"}
            self.transcript.append((label, status, parsed, kept))
        if expect is not None and status != expect:
            raise RuntimeError(f"{self.name} {label}: {method} {path} -> {status} {raw[:400]!r}")
        return parsed, raw, response_headers


def unzip_entries(raw):
    """Zip bytes are not identity: compare a package by its entries (JSON parsed, else hash)."""
    import io
    import zipfile
    try:
        archive = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return None
    entries = {}
    for name in sorted(archive.namelist()):
        data = archive.read(name)
        try:
            entries[name] = strict_json(data)
        except Exception:
            entries[name] = "sha256:" + hashlib.sha256(data).hexdigest()
    return {"__zip_entries": entries}


def workflow(side: Side, expiry: str, worker_seed: bytes, results: dict):
    admin, agent, worker, phoenix = "cleanroom-admin", "cleanroom-agent", "cleanroom-worker", "cleanroom-phoenix"
    c = side.call
    run, stage = "acceptance.http-cleanroom", "HTTP_REPLAY"
    scope = {"run_id": run, "stage_id": stage, "actor_id": "agent"}

    def put(raw, kind, request):
        return c("put:" + request, "POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(),
                 "kind": kind, "actor": "auditor", "request_id": request})[0]["artifact_id"]

    history_run = "E4-0-legacy-history-complete-v1"
    history = c("history", "GET", f"/v1/runs/{history_run}/history")[0]
    summary = c("history-summary", "GET", f"/v1/runs/{history_run}/history/summary")[0]
    assert len(history["facts"]) == 557 and len(summary["stopped_attempts"]) == 29, side.name
    imported = json.loads((PY / "acceptance/e4-0/history-import-v3.json").read_text())
    lineage = c("lineage", "GET", f"/v1/seals/{imported['source_merkle_root']}/lineage")[0]
    assert lineage["entry_count"] == 493, side.name
    for actor, kind, credential in (("agent", "agent", agent), ("worker", "remote_worker", worker), ("phoenix", "service", phoenix)):
        c("actor-" + actor, "POST", "/v1/actors", {"actor_id": actor, "kind": kind, "lab": "library",
          "credential_sha256": hashlib.sha256(credential.encode()).hexdigest(), "request_id": "actor-" + actor})
    c("run", "POST", "/v1/runs", {"run_id": run, "lab": "library", "actor": "auditor", "request_id": "run"})
    policy = c("policy", "POST", "/v1/policies", {"policy": {"schema": "KAMMI_POLICY_V1", "stage_id": stage,
               "version": "v1", "requires": {"actor": "AUTHORIZED", "scientific_spec": "SEALED",
               "execution_spec": "SEALED", "predecessor_seal": "VERIFIED", "resource.gpu": "LEASED"},
               "forbids": {"truth_label_contact": True}}, "request_id": "policy"})[0]["policy_hash"]
    for action in ("bind_spec", "authorize_stage", "acquire_lease", "open_panel", "apply_adapter", "execute_bundle"):
        c("grant-" + action, "POST", "/v1/grants", {"grant_id": action, **scope, "action": action,
          "policy_hash": policy, "expires_utc": expiry, "request_id": "grant-" + action})
    science, execution, environment, input_id = [put(raw, kind, kind) for raw, kind in (
        (b"fresh synthetic scientific specification", "scientific-spec"),
        (b"fresh synthetic execution specification", "execution-spec"),
        (b"synthetic worker environment", "environment-lock"), (b"declared input", "input"))]
    seal = c("seal", "POST", "/v1/seals", {"direct_members": [science, execution, environment, input_id], "parents": [],
             "actor": "auditor", "request_id": "seal"})[0]["root"]
    for kind, identity in (("SCIENTIFIC", science), ("EXECUTION", execution)):
        c("bind-" + kind, "POST", "/v1/specs/bind", {**scope, "spec_kind": kind, "artifact_id": identity,
          "seal_root": seal, "request_id": "bind-" + kind}, token=agent)
    c("verify-for-run", "POST", f"/v1/seals/{seal}/verify-for-run", {**scope, "request_id": "verify"}, token=agent)
    c("resource", "POST", "/v1/resources", {"resource_id": "gpu.fixture", "kind": "GPU", "host": "local", "constraints": {}, "request_id": "resource"})
    lease = c("lease", "POST", "/v1/leases/acquire", {**scope, "resource_id": "gpu.fixture", "purpose": "replay",
              "ttl_seconds": 600, "request_id": "lease"}, token=agent)[0]["receipt"]
    c("lease-conflict", "POST", "/v1/leases/acquire", {**scope, "resource_id": "gpu.fixture", "purpose": "second",
      "ttl_seconds": 600, "request_id": "lease-2"}, token=agent, expect=None)
    c("lease-status", "GET", "/v1/resources/gpu.fixture/lease")
    c("authorize-flight", "POST", "/v1/authorize", {**scope, "expires_utc": expiry, "request_id": "authorize-flight"}, token=agent, expect=None)
    auth = c("authorize", "POST", "/v1/acceptance/stages/authorize", {**scope, "expires_utc": expiry, "request_id": "authorize"}, token=agent)[0]
    assert auth["receipt"]["decision"] == "AUTHORIZED", side.name
    authorization = auth["event_id"]
    c("policy-check", "POST", "/v1/policy/check", {**scope, "request_id": "policy-check"}, token=agent, expect=None)
    c("attempt", "POST", "/v1/attempts/start", {**scope, "attempt_id": "http-attempt", "authorization_id": authorization, "request_id": "attempt"}, token=agent)
    c("attempt-get", "GET", "/v1/attempts/http-attempt?actor_id=agent", token=agent)
    panel_id = put(b"visible synthetic terminal evidence", "panel", "panel-source")
    c("panel", "POST", "/v1/panels", {"panel_id": "P", "artifact_id": panel_id, "lab": "library", "request_id": "panel"})
    _, opened, headers = c("open", "POST", "/v1/panels/P/open", {**scope, "purpose": "terminal", "authorization_id": authorization, "request_id": "open"}, token=agent)
    assert opened == b"visible synthetic terminal evidence", side.name
    c("exposure", "GET", "/v1/panels/P/exposure")
    source = put(canonical({"schema": "evaluation-v1", "evaluation_checkpoint_cells": [1, 2]}), "manifest", "adapter-source")
    c("adapter", "POST", "/v1/adapters", {"adapter_id": "EVAL_CELLS_RENAME_V1", "request_id": "adapter"})
    derived = c("apply", "POST", "/v1/adapters/EVAL_CELLS_RENAME_V1/apply", {**scope, "source_artifact_id": source,
                "authorization_id": authorization, "purpose": "handoff", "request_id": "apply"}, token=agent)[0]["derived_view_id"]
    worker_key = Ed25519PrivateKey.from_private_bytes(worker_seed)
    c("worker-key", "POST", "/v1/remote/worker-keys", {"worker_actor_id": "worker", "public_key_hex": public_bytes(worker_key).hex(), "request_id": "worker-key"})
    bundle = {"schema": "KAMMI_REMOTE_BUNDLE_V1", "run_id": run, "lab": "library", "stage_id": stage,
              "scientific_spec": science, "execution_spec": execution, "git_commit": "a" * 40, "dirty_tree_policy": "CLEAN_REQUIRED",
              "input_roots": [seal], "input_artifacts": [input_id], "environment_lock": environment,
              "runtime_requirements": {"runtime": "python-fixture"}, "gpu_requirements": {}, "seeds": [7],
              "command": [sys.executable, "-c", "import os,pathlib; (pathlib.Path(os.environ['KAMMI_OUTPUT_DIR'])/'output').write_bytes(b'HTTP replay')"],
              "expected_outputs": ["output"], "authorization_id": authorization, "lease_id": lease["lease_id"],
              "lease_resource_id": "gpu.fixture", "fencing_token": lease["fencing_token"], "worker_actor_id": "worker"}
    envelope = c("bundle", "POST", "/v1/remote/bundles", {"bundle": bundle, "actor_id": "agent", "request_id": "bundle"}, token=agent)[0]["envelope"]
    bundle_id = envelope["bundle_artifact_id"]
    fetched = c("bundle-get", "GET", f"/v1/remote/bundles/{bundle_id}?worker_actor_id=worker", token=worker)[0]
    _, input_bytes, _ = c("bundle-input", "GET", f"/v1/remote/bundles/{bundle_id}/inputs/{input_id}?worker_actor_id=worker", token=worker)
    assert input_bytes == b"declared input", side.name
    c("bundle-wrong-worker", "GET", f"/v1/remote/bundles/{bundle_id}?worker_actor_id=agent", token=agent, expect=None)
    c("worker-start", "POST", f"/v1/remote/bundles/{bundle_id}/start", {"worker_actor_id": "worker", "request_id": "worker-start"}, token=worker)

    def valid(i, r, f):
        return side.call("validate", "POST", f"/v1/leases/{i}/validate", {"actor_id": "agent", "run_id": run,
                         "resource_id": r, "fencing_token": f}, token=agent, record=False)[0]["valid"]
    result = execute_bundle(base64.b64decode(fetched["bundle_base64"]), envelope["signature_hex"],
                            bytes.fromhex(envelope["issuer_public_hex"]), {input_id: b"declared input"}, worker_key,
                            {"git_commit": "a" * 40, "dirty_tree": False, "runtime": "python-fixture"}, valid)
    enc = lambda raw: base64.b64encode(raw).decode()  # noqa: E731
    returned = c("worker-return", "POST", f"/v1/remote/bundles/{bundle_id}/return", {"worker_actor_id": "worker",
                 "receipt_base64": enc(result[0]), "receipt_signature": result[1],
                 "outputs_base64": {k: enc(v) for k, v in result[2].items()}, "stdout_base64": enc(result[3]),
                 "stderr_base64": enc(result[4]), "request_id": "worker-return"}, token=worker)[0]["receipt"]
    memory_ids = []
    for index, text in enumerate(("Nested schema mismatch required a registered adapter; exact source remained unchanged.",
                                  "Apply a registered schema adapter and trace immutable source identity.")):
        memory_ids.append(c(f"memory-{index}", "POST", "/v1/memory", {"kind": "FAILURE_MODE", "scope": "library", "text": text,
                            "actor_id": "agent", "custody_refs": [source, derived], "tags": ["e4", "schema"],
                            "request_id": f"memory-{index}"}, token=agent)[0]["memory_id"])
    c("memory-retry", "POST", "/v1/memory", {"kind": "FAILURE_MODE", "scope": "library", "text": "Nested schema mismatch required a registered adapter; exact source remained unchanged.",
      "actor_id": "agent", "custody_refs": [source, derived], "tags": ["e4", "schema"], "request_id": "memory-0"}, token=agent)
    retrieved = {}
    for mode in ("fts", "vector", "hybrid", "graph"):
        found = c("search-" + mode, "POST", "/v1/memory/search", {"query": "schema mismatch", "scope": "library", "actor_id": "agent",
                  "mode": mode, "seed_memory": memory_ids[1] if mode == "graph" else None, "grounded_only": True,
                  "request_id": "search-" + mode}, token=agent)[0]
        retrieved[mode] = memory_ids[0] in [r["memory"]["memory_id"] for r in found["results"]]
    c("memory-get", "GET", f"/v1/memory/{memory_ids[0]}?actor_id=agent", token=agent)
    trace = c("memory-trace", "GET", f"/v1/memory/{memory_ids[0]}/trace?actor_id=agent", token=agent)[0]
    assert all(r["verified"] for r in trace["references"]), side.name
    c("memory-neighbors", "GET", f"/v1/memory/{memory_ids[0]}/neighbors?actor_id=agent", token=agent)
    c("memory-supersede", "POST", "/v1/memory/supersede", {"old_id": memory_ids[0], "new_id": memory_ids[1], "actor_id": "agent", "request_id": "supersede"}, token=agent)
    c("memory-supersede-cycle", "POST", "/v1/memory/supersede", {"old_id": memory_ids[1], "new_id": memory_ids[0], "actor_id": "agent", "request_id": "supersede-2"}, token=agent, expect=400)
    c("attempt-finish", "POST", "/v1/attempts/finish", {"attempt_id": "http-attempt", "actor_id": "agent", "outcome": "COMPLETE",
      "evidence_artifact": derived, "reason": "HTTP fixture complete", "request_id": "complete"}, token=agent)
    output_seal = c("output-seal", "POST", "/v1/seals", {"direct_members": [derived, *returned["outputs"].values()], "parents": [seal],
                    "actor": "auditor", "request_id": "output-seal"})[0]["root"]
    c("result", "POST", "/v1/results/declare", {**scope, "authorization_id": authorization, "seal_root": output_seal, "request_id": "result"}, token=agent)
    c("fact", "POST", "/v1/facts", {"fact": {"schema": "KAMMI_FACT_V1", "kind": "NOTE", "subject": run, "run_id": run,
      "statement": "differential cleanroom fact", "evidence": [output_seal]}, "actor": "auditor", "request_id": "fact"}, expect=None)

    # Vault plane: owner-scoped sources, assets, streams and portable packages.
    c("vault-agent-denied", "POST", "/v1/vaults", {"vault_id": "vault-b", "actor_id": "agent", "request_id": "vault-b"}, token=agent, expect=400)
    c("vault", "POST", "/v1/vaults", {"vault_id": "vault-a", "actor_id": "phoenix", "request_id": "vault"}, token=phoenix)
    c("vault-source", "POST", "/v1/vaults/source", {"vault_id": "vault-a", "source_id": "notes.md", "base_revision": 0,
      "content_base64": enc(b"# Notes\n\nfirst revision\n"), "actor_id": "phoenix", "request_id": "vault-source"}, token=phoenix)
    c("vault-source-stale", "POST", "/v1/vaults/source", {"vault_id": "vault-a", "source_id": "notes.md", "base_revision": 0,
      "content_base64": enc(b"stale"), "actor_id": "phoenix", "request_id": "vault-source-stale"}, token=phoenix, expect=400)
    c("vault-source-stream", "POST", "/v1/vaults/source-stream", data=b"# Notes\n\nsecond revision\n", token=phoenix,
      headers={"X-Actor-Id": "phoenix", "X-Vault-Id": "vault-a", "X-Source-Id": "notes.md", "X-Base-Revision": "1",
               "X-Request-Id": "vault-source-2", "Content-Type": "application/octet-stream"})
    asset = c("vault-asset", "POST", "/v1/vaults/asset", {"vault_id": "vault-a", "content_base64": enc(b"\x89PNG fixture"),
              "kind": "png", "actor_id": "phoenix", "request_id": "vault-asset"}, token=phoenix)[0]["artifact_id"]
    big = bytes(range(256)) * 4096 * 2  # 2 MiB: a loose object on the Rust side
    streamed = c("vault-asset-stream", "POST", "/v1/vaults/asset-stream", data=big, token=phoenix,
                 headers={"X-Actor-Id": "phoenix", "X-Vault-Id": "vault-a", "X-Kind": "blob",
                          "X-Request-Id": "vault-asset-2", "Content-Type": "application/octet-stream"})[0]["artifact_id"]
    c("vault-view", "GET", "/v1/vaults/vault-a?actor_id=phoenix", token=phoenix)
    c("vault-view-other", "GET", "/v1/vaults/vault-a?actor_id=worker", token=worker, expect=404)
    c("vault-get-source", "GET", "/v1/vaults/vault-a/sources/notes.md?actor_id=phoenix", token=phoenix)
    c("vault-source-bytes", "GET", "/v1/vaults/vault-a/sources/notes.md/bytes?actor_id=phoenix", token=phoenix)
    _, asset_bytes, _ = c("vault-get-asset", "GET", f"/v1/vaults/vault-a/assets/{asset}?actor_id=phoenix", token=phoenix)
    assert asset_bytes == b"\x89PNG fixture", side.name
    _, big_bytes, _ = c("vault-get-big", "GET", f"/v1/vaults/vault-a/assets/{streamed}?actor_id=phoenix", token=phoenix)
    assert big_bytes == big, side.name
    c("vault-reader", "POST", "/v1/vaults/reader", {"vault_id": "vault-a", "source_id": "notes.md", "revision": 2, "offset": 3,
      "actor_id": "phoenix", "request_id": "vault-reader"}, token=phoenix)
    _, package, package_headers = c("vault-export", "GET", "/v1/vaults/vault-a/package?actor_id=phoenix", token=phoenix)
    package_root = {k.lower(): v for k, v in package_headers.items()}["x-vault-package-root"]
    c("vault-import-self", "POST", "/v1/vaults/package", data=package, token=phoenix, expect=None,
      headers={"X-Actor-Id": "phoenix", "X-Package-Root": package_root, "Content-Type": "application/zip"})
    results.update(retrieved=retrieved, memory_ids=memory_ids, lease=lease, package_root=package_root, receipt=returned)


def negatives(side: Side, memory_id: str):
    """Error surface: status and detail must match exactly."""
    c = side.call
    cases = [
        ("no-auth", "GET", "/v1/status", None, None, {}),
        ("bad-token", "GET", "/v1/status", None, "nope", {}),
        ("bad-json", "POST", "/v1/runs", b"{not json", "cleanroom-admin", {}),
        ("duplicate-key", "POST", "/v1/runs", b'{"run_id":"a","run_id":"b","lab":"l","actor":"a","request_id":"r"}', "cleanroom-admin", {}),
        ("wire-missing", "POST", "/v1/runs", {"run_id": "x", "lab": "library", "actor": "auditor"}, "cleanroom-admin", {}),
        ("wire-extra", "POST", "/v1/runs", {"run_id": "x", "lab": "library", "actor": "auditor", "request_id": "r", "extra": 1}, "cleanroom-admin", {}),
        ("wire-type", "POST", "/v1/runs", {"run_id": 7, "lab": "library", "actor": "auditor", "request_id": "r"}, "cleanroom-admin", {}),
        ("too-large", "POST", "/v1/runs", b"x" * (16 * 1024 * 1024 + 1), "cleanroom-admin", {}),
        ("big-float", "POST", "/v1/runs", b'{"run_id":"x","lab":"library","actor":"auditor","request_id":1e400}', "cleanroom-admin", {}),
        ("big-int", "POST", "/v1/runs", b'{"run_id":"x","lab":"library","actor":"auditor","request_id":9007199254740993}', "cleanroom-admin", {}),
        ("reused-request", "POST", "/v1/runs", {"run_id": "other", "lab": "library", "actor": "auditor", "request_id": "run"}, "cleanroom-admin", {}),
        ("run-duplicate", "POST", "/v1/runs", {"run_id": "acceptance.http-cleanroom", "lab": "library", "actor": "auditor", "request_id": "run-dup"}, "cleanroom-admin", {}),
        ("artifact-missing-header", "POST", "/v1/artifacts", b"raw", "cleanroom-admin", {"X-Actor": "a", "X-Request-Id": "r", "Content-Type": "application/octet-stream"}),
        ("artifact-raw", "POST", "/v1/artifacts", b"raw upload bytes", "cleanroom-admin", {"X-Kind": "note", "X-Actor": "auditor", "X-Request-Id": "raw-1", "Content-Type": "application/octet-stream"}),
        ("memory-missing-actor", "GET", f"/v1/memory/{memory_id}", None, "cleanroom-agent", {}),
        ("memory-wrong-actor", "GET", f"/v1/memory/{memory_id}?actor_id=worker", None, "cleanroom-agent", {}),
        ("memory-scope", "POST", "/v1/memory", {"kind": "FAILURE_MODE", "scope": "other-lab", "text": "t", "actor_id": "agent", "request_id": "m-x"}, "cleanroom-agent", {}),
        ("memory-observed-ungrounded", "POST", "/v1/memory", {"kind": "OBSERVED", "scope": "library", "text": "t", "actor_id": "agent", "request_id": "m-y"}, "cleanroom-agent", {}),
        ("memory-bad-mode", "POST", "/v1/memory/search", {"query": "q", "scope": "library", "actor_id": "agent", "mode": "psychic", "request_id": "s-x"}, "cleanroom-agent", {}),
        ("unknown-memory-get", "GET", "/v1/memory/sha256:" + "0" * 64 + "?actor_id=agent", None, "cleanroom-agent", {}),
        ("lease-bad-fence", "POST", "/v1/leases/lease-" + "0" * 64 + "/renew", {"actor_id": "agent", "fencing_token": 1, "ttl_seconds": 5, "request_id": "renew-x"}, "cleanroom-agent", {}),
        ("scope-no-grant", "POST", "/v1/specs/bind", {"run_id": "E4-0-legacy-history-complete-v1", "stage_id": "S", "actor_id": "agent", "spec_kind": "SCIENTIFIC", "artifact_id": "sha256:" + "1" * 64, "seal_root": "sha256:" + "2" * 64, "request_id": "b-x"}, "cleanroom-agent", {}),
        ("history-unknown", "GET", "/v1/runs/nope/history", None, "cleanroom-admin", {}),
        ("lineage-unknown", "GET", "/v1/seals/sha256:" + "3" * 64 + "/lineage", None, "cleanroom-admin", {}),
        ("attempt-unknown", "GET", "/v1/attempts/nope?actor_id=agent", None, "cleanroom-agent", {}),
        ("attempt-missing-actor", "GET", "/v1/attempts/nope", None, "cleanroom-agent", {}),
        ("local-validate-bad", "POST", "/v1/local/validate", {"actor_id": "agent", "run_id": "r"}, "cleanroom-agent", {}),
        ("local-resolve-noactor", "POST", "/v1/local/resolve", {"run_id": "r"}, "cleanroom-agent", {}),
        ("vault-bad-id", "POST", "/v1/vaults", {"vault_id": "../x", "actor_id": "phoenix", "request_id": "v-x"}, "cleanroom-phoenix", {}),
        ("vault-bad-base64", "POST", "/v1/vaults/source", {"vault_id": "vault-a", "source_id": "n", "base_revision": 0, "content_base64": "!!", "actor_id": "phoenix", "request_id": "v-y"}, "cleanroom-phoenix", {}),
        ("vault-stream-headers", "POST", "/v1/vaults/asset-stream", b"x", "cleanroom-phoenix", {"X-Actor-Id": "phoenix", "Content-Type": "application/octet-stream"}),
        ("vault-stream-not-owner", "POST", "/v1/vaults/asset-stream", b"x", "cleanroom-worker", {"X-Actor-Id": "worker", "X-Vault-Id": "vault-a", "X-Kind": "k", "X-Request-Id": "w", "Content-Type": "application/octet-stream"}),
        ("vault-export-other", "GET", "/v1/vaults/vault-a/package?actor_id=worker", None, "cleanroom-worker", {}),
        ("vault-import-bad-zip", "POST", "/v1/vaults/package", b"not a zip", "cleanroom-phoenix", {"X-Actor-Id": "phoenix", "X-Package-Root": "sha256:" + "4" * 64, "Content-Type": "application/zip"}),
        ("panel-denied", "POST", "/v1/panels/P/open", {"run_id": "acceptance.http-cleanroom", "stage_id": "HTTP_REPLAY", "actor_id": "agent", "purpose": "terminal", "authorization_id": "sha256:" + "0" * 64, "request_id": "denied"}, "cleanroom-agent", {}),
        ("acceptance-nonfixture", "POST", "/v1/acceptance/stages/authorize", {"run_id": "E4-0-legacy-history-complete-v1", "stage_id": "S", "actor_id": "agent", "expires_utc": "2099-01-01T00:00:00+00:00", "request_id": "acc-x"}, "cleanroom-agent", {}),
        ("vault-stream-bad-revision", "POST", "/v1/vaults/source-stream", b"x", "cleanroom-phoenix", {"X-Actor-Id": "phoenix", "X-Vault-Id": "vault-a", "X-Source-Id": "n", "X-Base-Revision": "one", "X-Request-Id": "v-z", "Content-Type": "application/octet-stream"}),
        ("vault-asset-bad-kind", "POST", "/v1/vaults/asset", {"vault_id": "vault-a", "content_base64": "AAAA", "kind": "image/png", "actor_id": "phoenix", "request_id": "v-k"}, "cleanroom-phoenix", {}),
        ("unknown-route", "GET", "/v1/nope", None, "cleanroom-admin", {}),
    ]
    for label, method, path, body, token, headers in cases:
        data = body if isinstance(body, bytes) else None
        c(label, method, path, None if data is not None else body, token=token, headers=headers, data=data, expect=None)


class Mismatch(Exception):
    pass


class Comparer:
    def __init__(self):
        self.forward, self.backward = {}, {}
        self.identical_ids = 0
        self.mismatches = []

    def ident(self, a, b, where):
        if self.forward.setdefault(a, b) != b or self.backward.setdefault(b, a) != a:
            self.mismatches.append(f"{where}: identity bijection broken ({a} -> {self.forward[a]}, got {b})")
        elif a == b:
            self.identical_ids += 1

    def value(self, a, b, where, loose=False):
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                self.mismatches.append(f"{where}: keys differ py-only={sorted(set(a) - set(b))} rs-only={sorted(set(b) - set(a))}")
                return
            for key in a:
                if key in SIGNATURES:
                    continue
                if key == "embedding_model_id" or (loose and key in ("score", "scores", "rank", "channels")):
                    continue
                self.value(a[key], b[key], f"{where}.{key}", loose)
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                self.mismatches.append(f"{where}: list length {len(a)} != {len(b)}")
                return
            for i, (x, y) in enumerate(zip(a, b)):
                self.value(x, y, f"{where}[{i}]", loose)
        elif isinstance(a, str) and isinstance(b, str):
            if ID.match(a) and ID.match(b):
                self.ident(a, b, where)
            elif TS.match(a) and TS.match(b):
                pass
            elif a != b:
                decoded = [self.decode(v) for v in (a, b)]
                if decoded[0] is not None and decoded[1] is not None:
                    self.value(decoded[0], decoded[1], where + "<b64>", loose)
                else:
                    self.mismatches.append(f"{where}: {a[:120]!r} != {b[:120]!r}")
        elif type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool)):
            self.mismatches.append(f"{where}: type {type(a).__name__} != {type(b).__name__}")
        elif a != b and not loose:
            self.mismatches.append(f"{where}: {a!r} != {b!r}")

    @staticmethod
    def decode(text):
        if len(text) < 8:
            return None
        try:
            return strict_json(base64.b64decode(text, validate=True))
        except Exception:
            return None

    def transcripts(self, py, rs):
        if [t[0] for t in py] != [t[0] for t in rs]:
            self.mismatches.append("transcript step labels differ")
        rows = []
        for (label, ps, pb, ph), (_, rs_, rb, rh) in zip(py, rs):
            before = len(self.mismatches)
            if label in EXPECTED:
                ok = (ps, rs_) == EXPECTED[label]
                if not ok:
                    self.mismatches.append(f"{label}: expected divergence {EXPECTED[label]}, got {(ps, rs_)}")
                rows.append((label, ps, rs_, "EXPECTED-FIX" if ok else "FAIL"))
                continue
            if label in DIAGNOSTIC and ps == rs_ and isinstance(pb, dict) and isinstance(rb, dict) and set(pb) == set(rb) == {"detail"}:
                rows.append((label, ps, rs_, "ok-diagnostic-wording"))
                continue
            if ps != rs_:
                self.mismatches.append(f"{label}: status {ps} != {rs_} py={json.dumps(pb)[:300]} rs={json.dumps(rb)[:300]}")
            else:
                loose = label.startswith("search-") or label == "memory-neighbors"
                if loose and isinstance(pb, dict) and isinstance(rb, dict):
                    self.value(set(pb) and sorted(pb), set(rb) and sorted(rb), label + "{keys}")
                    for key in pb:
                        if key != "results":
                            self.value(pb[key], rb.get(key), f"{label}.{key}", True)
                else:
                    self.value(pb, rb, label)
                for header in set(ph) | set(rh):
                    if header in ("x-vault-package-root", "x-artifact-id", "x-exposure-event"):
                        if header in ph and header in rh:
                            self.ident(ph[header], rh[header], f"{label}<{header}>")
                        else:
                            self.mismatches.append(f"{label}: header {header} present on one side only")
                    elif header == "x-source-revision" and ph.get(header) != rh.get(header):
                        self.mismatches.append(f"{label}: header {header} {ph.get(header)} != {rh.get(header)}")
            rows.append((label, ps, rs_, "ok" if len(self.mismatches) == before else "FAIL"))
        return rows


def crash_and_retry(side: Side, extra: dict):
    """Controlled crash after the journal fsync; restart; exact retry repairs the response."""
    head = side.call("pre-crash-status", "GET", "/v1/status", record=False)[0]["journal_head"]
    side.stop()
    side.start({**extra, "KAMMI_FAULT_POINT": "journal.after_fsync"})
    body = {"bytes_base64": base64.b64encode(b"durably committed HTTP operation before controlled crash").decode(),
            "kind": "receipt", "actor": "auditor", "request_id": "controlled-crash"}
    try:
        side.raw("POST", "/v1/artifacts/base64", body, token="cleanroom-admin")
    except OSError:
        pass
    side.process.wait(timeout=30)
    code = side.process.returncode
    side.start()
    after = side.call("post-crash-status", "GET", "/v1/status", record=False)[0]["journal_head"]
    retried = side.call("crash-retry", "POST", "/v1/artifacts/base64", body, record=False)[0]
    final = side.call("post-retry-status", "GET", "/v1/status", record=False)[0]["journal_head"]
    return {"exit_code": code, "head_advanced": after != head, "retry_no_duplicate": after == final, "retry_response": retried}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--embedder", default="gemma300")
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
    started = time.time()
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(fixture), "--v2", str(v2)], check=True)
    import_seconds = time.time() - started
    key = work / "daemon-signing-secret"
    key.write_bytes(hashlib.sha256(b"kammi differential signing seed").digest())
    common = {"KAMMI_SIGNING_KEY_FILE": str(key)}
    python = Side("python", v1, [sys.executable, "-m", "ledgerd.api"],
                  {**common, "KAMMI_EMBEDDING_CACHE": str(PY / "vendor/runtime-v1/embedding-cache")}, PY)
    rust_env = {**common, "KAMMI_EMBEDDER": args.embedder, "PATH": str(PY / "vendor/runtime-v1/native") + os.pathsep + os.environ.get("PATH", "")}
    rust = Side("rust", v2, [str(TARGET / "kammi-ledgerd.exe")], rust_env, HERE)
    expiry = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    seed = hashlib.sha256(b"kammi differential worker seed").digest()
    report = {"schema": "KAMMI_HTTP_DIFFERENTIAL_V1", "import_seconds": round(import_seconds, 2)}
    try:
        outcomes, timings = {}, {}
        for side in (python, rust):
            timings[side.name] = {"startup_seconds": round(side.start(), 2)}
            started = time.time()
            results = {}
            workflow(side, expiry, seed, results)
            timings[side.name]["workflow_seconds"] = round(time.time() - started, 2)
            negatives(side, results["memory_ids"][0])
            outcomes[side.name] = results
        comparer = Comparer()
        rows = comparer.transcripts(python.transcript, rust.transcript)
        crashes = {side.name: crash_and_retry(side, {"KAMMI_ACCEPTANCE_FAULTS": "1"}) for side in (python, rust)}
        statuses = {side.name: side.call("final-status", "GET", "/v1/status", record=False)[0] for side in (python, rust)}
        for side in (python, rust):
            side.stop()
        # Rust-written authority must satisfy the unmodified Python verifier and replay.
        exported = work / "rust-export-v1"
        subprocess.run([str(TARGET / "kammi-migrate.exe"), "export-v1", "--v2", str(v2), "--out", str(exported)], check=True)
        from scripts.independent_verify import verify_store
        from ledgerd.core import Ledger
        rollback = {"memory_journal": "ACCEPTED"}
        try:
            audit = verify_store(exported)
        except ValueError as exc:
            # Python fixes memory vectors at 384 dimensions (bge-small); a 768-d Phoenix space
            # cannot roll back into Python memory. Custody must still verify on its own.
            if str(exc) != "memory embedding malformed" or statuses["rust"]["memory"]["records"] == 0:
                raise
            rollback = {"memory_journal": "REFUSED_BY_PYTHON_384D_RULE", "reason": str(exc)}
            shutil.rmtree(exported / "memory")
            audit = verify_store(exported)
        ledger = Ledger(exported)
        try:
            replay = {"journal_head": ledger.journal.head, "events": len(ledger.journal.events)}
        finally:
            ledger.close()
        report.update(
            status="PASS" if not comparer.mismatches and all(c["exit_code"] == 91 and c["head_advanced"] and c["retry_no_duplicate"] for c in crashes.values())
            and outcomes["python"]["retrieved"] == {m: True for m in ("fts", "vector", "hybrid", "graph")}
            and outcomes["rust"]["retrieved"] == {m: True for m in ("fts", "vector", "hybrid", "graph")}
            and audit["journal_head"] == statuses["rust"]["journal_head"] == replay["journal_head"] else "FAIL",
            steps=len(rows), identities_mapped=len(comparer.forward), identities_equal=comparer.identical_ids,
            mismatches=comparer.mismatches, rows=rows, crashes=crashes, timings=timings,
            retrieved={k: v["retrieved"] for k, v in outcomes.items()},
            counts={k: v.get("counts") for k, v in statuses.items()},
            python_verifier_on_rust_export=audit, rollback=rollback, python_replay_of_rust_export=replay,
            rust_memory_embedder=statuses["rust"].get("memory", {}).get("embedding_model_id") or statuses["rust"].get("memory"),
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
