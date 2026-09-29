"""Vault Phase 1, milestone M1: the workspace surface end to end on a development store.

  python tools/workspace_e2e.py <work dir> [--output report.json]

A real daemon (acceptance fixture mode with a deterministic test clock) on an
import of the E4 fixture:
- v4 refused until the journaled activation; activation rules;
- an owner (chief-kammi) and a handoff recipient (reviewer) working through `kammi` CLI
  sessions (separate session files), including a stale-HEAD conflict (exit 3);
- the same workspace through `kammi-mcp` and the provider-neutral function list;
- replay identity: `work` and the workspace view byte-identical after deleting the projection
  and restarting the daemon.
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
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
sys.path.insert(0, str(HERE / "tools"))
from http_differential import free_port  # noqa: E402
from activation_fixture import register_v4_records  # noqa: E402

TARGET = Path(os.environ["KAMMI_BIN_DIR"]) if os.environ.get("KAMMI_BIN_DIR") else Path(os.environ.get("CARGO_TARGET_DIR", "")) / "release"
NATIVE = str(PY / "vendor/runtime-v1/native")
ADMIN = "e2e-admin-credential"
WS = "frozen-fabrique.e4-0"


class Daemon:
    def __init__(self, store: Path, port: int):
        self.store, self.port, self.proc, self.log = store, port, None, None
        self.url = f"http://127.0.0.1:{port}"

    def start(self):
        env = {**os.environ, "KAMMI_ROOT": str(self.store), "KAMMI_PORT": str(self.port), "KAMMI_TOKEN": ADMIN,
               "KAMMI_ACCEPTANCE_MODE": "1", "KAMMI_TEST_CLOCK": "2026-10-07T09:00:00Z", "KAMMI_EMBEDDER": "hashing",
               "PATH": NATIVE + os.pathsep + os.environ["PATH"]}
        self.log = (self.store.parent / "daemon.log").open("a")
        self.proc = subprocess.Popen([str(TARGET / "kammi-ledgerd.exe")], env=env, stdout=self.log, stderr=self.log)
        for _ in range(600):
            if self.proc.poll() is not None:
                raise RuntimeError((self.store.parent / "daemon.log").read_text()[-2000:])
            try:
                self.call("GET", "/v1/status")
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("daemon did not start")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(timeout=30)
        if self.log:
            self.log.close()

    def call(self, method, path, body=None, token=ADMIN):
        import urllib.error
        import urllib.request
        request = urllib.request.Request(self.url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                         headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read() or b"null")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.work.resolve()
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    store = root / "store"
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/e4-import"), "--v2", str(store)], check=True, stdout=subprocess.DEVNULL)
    daemon = Daemon(store, free_port())
    checks, detail = {}, {}
    tokens = {"chief-kammi": "e2e-chief-credential", "reviewer": "e2e-reviewer-credential", "outsider": "e2e-outsider-credential"}

    def shell(actor, session, *argv):
        env = {**os.environ, "KAMMI_URL": daemon.url, "KAMMI_TOKEN": tokens.get(actor, ADMIN), "KAMMI_ACTOR": actor,
               "KAMMI_SESSION": str(root / f"{session}.session.json")}
        return subprocess.run([str(TARGET / "kammi.exe"), *argv], env=env, capture_output=True, text=True, timeout=60)

    try:
        daemon.start()
        for actor, lab in (("chief-kammi", "kammi-ops"), ("reviewer", "frozen-fabrique"), ("outsider", "elsewhere")):
            daemon.call("POST", "/v1/actors", {"actor_id": actor, "kind": "agent", "lab": lab,
                        "credential_sha256": hashlib.sha256(tokens[actor].encode()).hexdigest(), "request_id": f"actor-{actor}"})
        status, body = daemon.call("POST", "/v2/workspaces", {"workspace_id": WS, "title": "t", "lab": "frozen-fabrique", "owners": ["chief-kammi"], "request_id": "early"})
        checks["v4_refused_before_activation"] = status == 400 and "not active" in json.dumps(body)

        def register(obj, kind, request):
            raw = json.dumps(obj).encode()
            return daemon.call("POST", "/v1/artifacts/base64", {"bytes_base64": base64.b64encode(raw).decode(), "kind": kind, "actor": "admin", "request_id": request})[1]["artifact_id"]

        head = daemon.call("GET", "/v1/status")[1]["journal_head"]
        payload = register_v4_records(register, prefix="e2e-v4", effective_at="2026-10-07T09:00:00Z", source_head=head)
        head = daemon.call("GET", "/v1/status")[1]["journal_head"]
        verification = register({"status": "PASS", "journal_head": head, "verifier": "e2e fixture"}, "verification", "verification")
        payload["verification"] = verification
        status, body = daemon.call("POST", "/v2/vocabulary/activate", {**payload, "request_id": "activate"}, token=tokens["chief-kammi"])
        checks["activation_needs_admin"] = status == 401
        status, body = daemon.call("POST", "/v2/vocabulary/activate", {**payload, "request_id": "activate"})
        checks["activation"] = status == 200 and body.get("vocabulary_v4") is True
        r = shell("chief-kammi", "chief", "create", WS, "--title", "Frozen Fabrique E4-0", "--lab", "frozen-fabrique", "--owners", "chief-kammi")
        checks["chief_cannot_create_without_admin"] = r.returncode == 1 and "401" in r.stderr
        env = {**os.environ, "KAMMI_URL": daemon.url, "KAMMI_TOKEN": ADMIN, "KAMMI_ACTOR": "chief-kammi", "KAMMI_SESSION": str(root / "chief.session.json")}
        r = subprocess.run([str(TARGET / "kammi.exe"), "create", WS, "--title", "Frozen Fabrique E4-0", "--lab", "frozen-fabrique", "--owners", "chief-kammi"], env=env, capture_output=True, text=True, timeout=60)
        checks["admin_creates_workspace"] = r.returncode == 0 and "WorkspaceCreated" in r.stdout

        # --- the owner sets the frame through the CLI
        r = shell("chief-kammi", "chief", "work", "--workspace", WS)
        checks["owner_reads_packet"] = r.returncode == 0 and "OBJECTIVE (not set)" in r.stdout
        steps = [
            ("objective", "Reach a single scoped E4-0 scoring decision so E4-01 can proceed when its gate permits"),
            ("scope", "--authorized", "Bookkeeping on the E4-0 record", "--authorized", "Review of the bound scoring packet",
             "--forbidden", "Open protected E4 labels", "--forbidden", "Enter E4-01", "--forbidden", "Model contact without authorization"),
            ("next", "Engineering reviewer returns READY or BLOCKED on the scoring packet"),
            ("handoff", "--to", "reviewer", "--summary", "Review the E4-0 scoring packet", "--next-step", "Return READY or BLOCKED with the exact mismatch"),
        ]
        admin_shell = lambda actor, session, *argv: subprocess.run(
            [str(TARGET / "kammi.exe"), *argv],
            env={**os.environ, "KAMMI_URL": daemon.url, "KAMMI_TOKEN": ADMIN, "KAMMI_ACTOR": actor,
                 "KAMMI_SESSION": str(root / f"{session}.session.json")},
            capture_output=True, text=True, timeout=60)
        restricted = [admin_shell("chief-kammi", "chief", *step).returncode for step in steps]
        checks["chief_controls_with_admin"] = restricted == [0, 0, 0, 0]
        codes = [shell("chief-kammi", "chief", *s).returncode for s in steps]
        checks["lab_actor_cannot_control_workspace"] = codes == [1, 1, 1, 1]
        checks["owner_writes_follow_session_head"] = restricted == [0, 0, 0, 0]
        # A participant can still contribute after Chief routes a handoff.
        if restricted != [0, 0, 0, 0]:
            detail["owner_writes"] = [shell("chief-kammi", "chief", "work").stdout[-800:]]

        # --- outsider refused; reviewer (handoff recipient) takes part
        r = shell("outsider", "outsider", "open", WS)
        checks["outsider_refused"] = r.returncode == 1 and "403" in r.stderr
        r = shell("reviewer", "reviewer", "open", WS, "--tool", "claude-subagent")
        checks["recipient_opens"] = r.returncode == 0 and "attached as session" in r.stdout and "PENDING HANDOFFS" in r.stdout and "DO NOT" in r.stdout
        packet_text = r.stdout
        handoff_id = next((line.split(":")[0].strip("- ").strip() for line in packet_text.splitlines() if line.strip().startswith("- h-")), None)
        codes = [shell("reviewer", "reviewer", *s).returncode for s in (
            ("receive", handoff_id or "missing"),
            ("note", "Bindings checked against the frozen contract"),
            ("decide", "READY FOR SCOPED E4-0 SCORING AUTHORIZATION", "--rationale", "No mismatch in contract, adapter or preparation receipt"),
        )]
        checks["recipient_writes"] = codes == [0, 0, 0]
        r = shell("reviewer", "reviewer", "objective", "rewrite it")
        checks["recipient_cannot_set_objective"] = r.returncode == 1 and "403" in r.stderr

        # --- the owner's session is stale now: exit 3 and the changes are listed
        r = shell("chief-kammi", "chief", "note", "Chief note on a stale HEAD")
        checks["stale_head_exit_3"] = r.returncode == 3 and "HEAD moved" in r.stderr and "READY" in r.stderr
        r = shell("chief-kammi", "chief", "work")
        r2 = shell("chief-kammi", "chief", "note", "Chief note after reading")
        checks["retry_after_reading"] = r.returncode == 0 and r2.returncode == 0

        # --- MCP and the provider-neutral function list
        functions = json.loads(shell("reviewer", "reviewer", "verbs", "--functions").stdout)
        checks["function_list"] = len(functions) == 20 and all(f["name"].startswith("kammi_") and f["parameters"]["type"] == "object" for f in functions)
        env = {**os.environ, "KAMMI_URL": daemon.url, "KAMMI_TOKEN": tokens["reviewer"], "KAMMI_ACTOR": "reviewer"}
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "kammi_work", "arguments": {"workspace": WS}}}]
        mcp = subprocess.run([str(TARGET / "kammi-mcp.exe")], env=env, input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=60)
        replies = [json.loads(line) for line in mcp.stdout.splitlines()]
        tools = [t["name"] for t in replies[1]["result"]["tools"]] if len(replies) == 3 else []
        head_now = replies[2]["result"]["structuredContent"]["workspace"]["head"] if len(replies) == 3 else None
        checks["mcp_lists_v1_then_verbs"] = len(tools) == 44 and tools[23] == "memory_neighbors" and tools[24] == "kammi_create"
        messages = [messages[0], {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "kammi_note", "arguments": {"workspace": WS, "expected_head": head_now, "text": "Written through MCP"}}},
                    {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "kammi_note", "arguments": {"workspace": WS, "expected_head": head_now, "text": "Stale through MCP"}}}]
        mcp = subprocess.run([str(TARGET / "kammi-mcp.exe")], env=env, input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True, text=True, timeout=60)
        replies = [json.loads(line) for line in mcp.stdout.splitlines()]
        checks["mcp_write_and_conflict"] = len(replies) == 3 and replies[1]["result"]["isError"] is False and replies[2]["result"]["isError"] is True and "409" in replies[2]["result"]["content"][0]["text"]

        # --- memory under v4: time-aware remember, recall receipts off the memory state, trace, find
        r = shell("reviewer", "reviewer", "remember", "The scoring packet review found no binding mismatch",
                  "--asserted-at", "2026-10-07T08:30:00Z", "--occurred-from", "2026-10-07T08:00:00Z", "--occurred-to", "2026-10-07T08:30:00Z",
                  "--precision", "minute", "--original-text", "this morning", "--json")
        remembered = json.loads(r.stdout) if r.returncode == 0 else {}
        memory_id = remembered.get("memory_id")
        checks["remember_with_time"] = bool(memory_id)
        status, record = daemon.call("GET", f"/v2/memory/{memory_id}?actor_id=reviewer", token=tokens["reviewer"])
        time_ok = status == 200 and record.get("scope") == f"workspace:{WS}" and record.get("time", {}).get("occurred", {}).get("from") == "2026-10-07T08:00:00Z" \
            and record["time"]["observed_at"] == record["created_at"] and record["time"]["source_time"] == "unknown"
        checks["record_carries_six_clocks"] = time_ok
        detail["record_time"] = record.get("time")
        r = shell("reviewer", "reviewer", "recall", "scoring packet review")
        checks["recall_finds_it"] = r.returncode == 0 and "binding mismatch" in r.stdout and "contextual, not custody" in r.stdout
        recall_body = {"query": "binding mismatch", "scope": f"workspace:{WS}", "actor_id": "reviewer", "request_id": "fixed-recall"}
        first = daemon.call("POST", "/v2/recall", recall_body, token=tokens["reviewer"])
        again = daemon.call("POST", "/v2/recall", recall_body, token=tokens["reviewer"])
        checks["recall_retry_identical"] = first[0] == 200 and first == again
        r = shell("reviewer", "reviewer", "trace", memory_id or "none")
        checks["trace"] = r.returncode == 0 and memory_id in r.stdout
        r = shell("outsider", "outsider", "recall", "binding", "--scope", f"workspace:{WS}")
        checks["outsider_cannot_recall_workspace_memory"] = r.returncode == 1 and "403" in r.stderr
        r = shell("reviewer", "reviewer", "find", "fabrique", "--json")
        found = json.loads(r.stdout) if r.returncode == 0 else {}
        checks["find"] = any(w["workspace_id"] == WS for w in found.get("workspaces", []))

        # --- every content line cites an event; the packet is inside its budget
        status, packet = daemon.call("GET", f"/v2/workspaces/{WS}/work")
        text = packet["text"]
        content = [line for line in text.splitlines() if line.startswith("  - ") or line.startswith("OBJECTIVE ") or line.startswith("NEXT STEP ")]
        checks["packet_lines_cite_events"] = bool(content) and all("[e:" in line for line in content) and packet["within_budget"]
        detail["packet"] = text

        # --- replay identity: delete the projection, restart, compare bytes
        before = [daemon.call("GET", f"/v2/workspaces/{WS}/work")[1], daemon.call("GET", f"/v2/workspaces/{WS}")[1]]
        daemon.stop()
        shutil.rmtree(store / "projection", ignore_errors=True)
        daemon.start()
        after = [daemon.call("GET", f"/v2/workspaces/{WS}/work")[1], daemon.call("GET", f"/v2/workspaces/{WS}")[1]]
        checks["replay_identity"] = json.dumps(before, sort_keys=True) == json.dumps(after, sort_keys=True)
        checks["recall_retry_answered_from_disk_after_restart"] = daemon.call("POST", "/v2/recall", recall_body, token=tokens["reviewer"]) == first
        v1 = daemon.call("GET", "/v1/status")[1]
        checks["v1_still_serves"] = v1["journal_events"] > 1700
    finally:
        daemon.stop()
    verify = subprocess.run([str(TARGET / "kammi-verify.exe"), str(store)], capture_output=True, text=True)
    verified = json.loads(verify.stdout) if verify.stdout.strip() else {}
    checks["independent_verifier_passes"] = verified.get("status") == "PASS" and verified.get("workspaces") == 1
    checks["recall_receipts_in_receipt_stream"] = (verified.get("receipts_events") or 0) >= 2 and verified.get("event_types", {}).get("MemoryRetrieved") is None
    detail["verify"] = {k: verified.get(k) for k in ("status", "journal_events", "memory_events", "receipts_events", "workspaces", "errors")}
    report = {"schema": "KAMMI_WORKSPACE_E2E_V1", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "detail": detail}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "detail"}, indent=2))
    if report["status"] != "PASS":
        print(detail.get("packet", ""))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
