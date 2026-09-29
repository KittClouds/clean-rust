"""Phase 0: the Rust shell (`kammi`, `kammi-mcp`) against the frozen Python CLI and MCP.

  python tools/shell_conformance.py <work dir> [--output report.json]

Both shells talk to the same Rust daemon on an import of the E4 fixture. Reads must print
byte-identical output. MCP sessions run the same message list through Python first, then Rust:
writes reuse their request IDs, so the Rust replies are idempotent replays and must be JSON-equal
reply by reply (text content compared after parsing). Documented differences:
- exit codes follow the v4 ABI (usage 2, refused 1, unreachable 4) where Python prints a
  traceback and exits 1;
- an unreachable Library is an `isError` reply in Rust, where Python's MCP process dies.
"""
from __future__ import annotations

import argparse
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
sys.path.insert(0, str(PY))
sys.path.insert(0, str(HERE / "tools"))
from ledgerd.client import KammiClient  # noqa: E402
from http_differential import free_port  # noqa: E402

TARGET = Path(os.environ.get("CARGO_TARGET_DIR", "G:/kammi-ledger-rs-target")) / "release"


def run(cmd, env, stdin=None):
    return subprocess.run(cmd, env=env, cwd=PY, input=stdin, capture_output=True, text=True, timeout=120)


def py_cli(env, *args):
    return run([sys.executable, "-m", "ledgerd.cli", *args], env)


def rs_cli(env, *args):
    return run([str(TARGET / "kammi.exe"), *args], env)


def mcp_session(command, env, messages):
    result = run(command, env, "".join((m if isinstance(m, str) else json.dumps(m)) + "\n" for m in messages))
    replies = []
    for line in result.stdout.splitlines():
        reply = json.loads(line)
        for item in reply.get("result", {}).get("content", []) or []:
            if item.get("type") == "text":
                try:
                    item["text"] = json.loads(item["text"])
                except ValueError:
                    pass
        replies.append(reply)
    return result.returncode, replies


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
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/e4-import"), "--v2", str(store)],
                   check=True, stdout=subprocess.DEVNULL)
    port = free_port()
    env = {**os.environ, "KAMMI_ROOT": str(store), "KAMMI_TOKEN": "acceptance-admin-credential", "KAMMI_PORT": str(port),
           "KAMMI_URL": f"http://127.0.0.1:{port}", "KAMMI_EMBEDDER": "bge", "PYTHONDONTWRITEBYTECODE": "1"}
    log = (root / "daemon.log").open("w")
    daemon = subprocess.Popen([str(TARGET / "kammi-ledgerd.exe")], env=env, stdout=log, stderr=log)
    client = KammiClient(env["KAMMI_URL"], env["KAMMI_TOKEN"])
    checks, detail = {}, {}
    try:
        for _ in range(600):
            if daemon.poll() is not None:
                raise RuntimeError((root / "daemon.log").read_text())
            try:
                client.status()
                break
            except Exception:
                time.sleep(0.05)
        source = root / "source.txt"
        source.write_text("shell conformance fixture \u00e9")

        # --- CLI: writes (fresh request IDs on both sides, so compare what is deterministic)
        py_art, rs_art = py_cli(env, "artifact", str(source), "--kind", "source", "--actor", "admin"), rs_cli(env, "artifact", str(source), "--kind", "source", "--actor", "admin")
        a, b = json.loads(py_art.stdout), json.loads(rs_art.stdout)
        checks["cli_artifact"] = py_art.returncode == rs_art.returncode == 0 and a["artifact_id"] == b["artifact_id"] and set(a) == set(b)
        artifact = a["artifact_id"]
        py_run, rs_run = py_cli(env, "run", "shell.py", "phoenix", "--actor", "admin"), rs_cli(env, "run", "shell.rs", "phoenix", "--actor", "admin")
        checks["cli_run"] = py_run.returncode == rs_run.returncode == 0 and set(json.loads(py_run.stdout)) == set(json.loads(rs_run.stdout))
        # A second seal over the same members is refused by design, so each side seals its own member.
        other = root / "other.txt"
        other.write_text("second shell conformance fixture")
        other_artifact = json.loads(py_cli(env, "artifact", str(other), "--kind", "source", "--actor", "admin").stdout)["artifact_id"]
        py_seal, rs_seal = py_cli(env, "seal", "--member", artifact, "--actor", "admin"), rs_cli(env, "seal", "--member", other_artifact, "--actor", "admin")
        s1, s2 = json.loads(py_seal.stdout or "{}"), json.loads(rs_seal.stdout or "{}")
        checks["cli_seal"] = py_seal.returncode == rs_seal.returncode == 0 and set(s1) == set(s2) and bool(s1)
        again_py, again_rs = py_cli(env, "seal", "--member", other_artifact, "--actor", "admin"), rs_cli(env, "seal", "--member", artifact, "--actor", "admin")
        checks["cli_seal_duplicate_refused_alike"] = again_py.returncode != 0 and again_rs.returncode == 1 and "seal already exists" in again_rs.stderr
        root_id = next(v for k, v in sorted(s1.items()) if isinstance(v, str) and v.startswith("sha256:") and "root" in k)

        # --- CLI: reads must be byte-identical
        reads = [("lineage", ("lineage", root_id)), ("history", ("history", "shell.py")),
                 ("history_summary", ("history", "shell.py", "--summary")), ("call_get", ("call", "GET", f"/v1/seals/{root_id}/lineage"))]
        for label, read in reads:
            p, r = py_cli(env, *read), rs_cli(env, *read)
            name = "cli_read_" + label
            checks[name] = p.returncode == r.returncode == 0 and p.stdout == r.stdout
            if not checks[name]:
                detail[name] = {"python": p.stdout[:300] + p.stderr[-300:], "rust": r.stdout[:300] + r.stderr[-300:]}
        p, r = py_cli(env, "status"), rs_cli(env, "status")
        ps, rsj = json.loads(p.stdout), json.loads(r.stdout)
        checks["cli_status"] = set(ps) == set(rsj) and ps["journal_head"] == rsj["journal_head"] and ps["flight_gate"] == rsj["flight_gate"]
        body = root / "body.json"
        body.write_text(json.dumps({"run_id": "shell.body", "lab": "phoenix", "actor": "admin", "request_id": "shell-body-run"}))
        p, r = py_cli(env, "call", "POST", "/v1/runs", "--body", str(body)), rs_cli(env, "call", "POST", "/v1/runs", "--body", str(body))
        checks["cli_call_post_idempotent"] = p.returncode == r.returncode == 0 and p.stdout == r.stdout

        # --- CLI: refusals and usage
        p, r = py_cli(env, "history", "no.such.run"), rs_cli(env, "history", "no.such.run")
        checks["cli_refused"] = p.returncode != 0 and r.returncode == 1 and ("HTTP 404" in p.stderr) == ("HTTP 404" in r.stderr)
        r = rs_cli(env, "call", "GET", "/v2/anything")
        checks["cli_v1_only"] = r.returncode == 2 and "only v1 service endpoints" in r.stderr
        r = rs_cli(env, "work")
        checks["cli_reserved_verb"] = r.returncode == 2 and "Phase 1" in r.stderr
        r = rs_cli(env, "verbs")
        checks["cli_verbs"] = r.returncode == 0 and len(json.loads(r.stdout)) == 26
        r = run([str(TARGET / "kammi.exe"), "status"], {**env, "KAMMI_URL": f"http://127.0.0.1:{free_port()}"})
        checks["cli_unreachable"] = r.returncode == 4

        # --- MCP: same messages, Python first, then Rust (writes replay idempotently)
        actor_token = "shell-agent-credential"
        client.call("POST", "/v1/actors", {"actor_id": "shell-agent", "kind": "agent", "lab": "phoenix",
                    "credential_sha256": hashlib.sha256(actor_token.encode()).hexdigest(), "request_id": "shell-actor"})
        agent_env = {**env, "KAMMI_TOKEN": actor_token}
        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "custody_get_lineage", "arguments": {"root": root_id}}},
            {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "memory_record", "arguments": {"body": {
                "kind": "OBSERVED", "scope": "phoenix", "text": "Shell conformance memory \u00e9 traced to custody", "actor_id": "shell-agent",
                "custody_refs": [artifact], "request_id": "shell-mcp-record"}}}},
            {"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "memory_search", "arguments": {"body": {
                "query": "shell conformance", "scope": "phoenix", "actor_id": "shell-agent", "mode": "hybrid", "request_id": "shell-mcp-search"}}}},
            {"jsonrpc": "2.0", "id": 8, "method": "tools/call", "params": {"name": "memory_get", "arguments": {
                "memory_id": "sha256:" + "0" * 64, "actor_id": "shell-agent"}}},
            {"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": "no_such_tool", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 10, "method": "tools/call", "params": {"name": "custody_get_lineage", "arguments": {"root": root_id, "extra": "x"}}},
            {"jsonrpc": "1.0", "id": 11, "method": "ping"},
            {"jsonrpc": "2.0", "id": 12, "method": "resources/list"},
            "this is not json",
            "[1, 2, 3]",
        ]
        py_code, py_replies = mcp_session([sys.executable, "-m", "ledgerd.mcp"], agent_env, messages)
        rs_code, rs_replies = mcp_session([str(TARGET / "kammi-mcp.exe")], agent_env, messages)
        mismatches = [{"python": a, "rust": b} for a, b in zip(py_replies, rs_replies) if a != b]
        checks["mcp_session_equal"] = py_code == rs_code == 0 and len(py_replies) == len(rs_replies) == 14 and not mismatches
        if mismatches or len(py_replies) != len(rs_replies):
            detail["mcp"] = {"python_count": len(py_replies), "rust_count": len(rs_replies), "mismatches": mismatches[:3]}
        memory_id = next((r["result"]["structuredContent"]["memory_id"] for r in rs_replies if r.get("id") == 6 and "result" in r), None)
        checks["mcp_write_really_committed"] = bool(memory_id) and KammiClient(env["KAMMI_URL"], actor_token).call("GET", f"/v1/memory/{memory_id}?actor_id=shell-agent")["memory_id"] == memory_id
        big = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping", "pad": "x" * (1024 * 1024)})
        py_big, rs_big = run([sys.executable, "-m", "ledgerd.mcp"], agent_env, big + "\n"), run([str(TARGET / "kammi-mcp.exe")], agent_env, big + "\n")
        checks["mcp_frame_cap"] = py_big.returncode != 0 and rs_big.returncode != 0 and "frame too large" in rs_big.stderr
        code, replies = mcp_session([str(TARGET / "kammi-mcp.exe")], {**agent_env, "KAMMI_URL": f"http://127.0.0.1:{free_port()}"},
                                    [messages[1], messages[4 + 1]])
        checks["mcp_unreachable_is_error_not_crash"] = code == 0 and replies[-1]["result"]["isError"] is True
    finally:
        daemon.terminate()
        daemon.wait(timeout=20)
        log.close()
    report = {"schema": "KAMMI_SHELL_CONFORMANCE_V1", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "detail": detail}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
