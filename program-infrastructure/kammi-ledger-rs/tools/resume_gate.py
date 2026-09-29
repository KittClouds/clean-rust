"""Vault Phase 1 resume gate (W8): can a fresh agent continue the work from `kammi` alone?

  python tools/resume_gate.py setup <work>                  sandbox Library + Frozen Fabrique seed + 3 scenarios
  python tools/resume_gate.py prompt <work> <scenario>      the exact brief a fresh agent receives
  python tools/resume_gate.py run <work> <scenario> --runner openai --base-url URL --model M [--api-key-env VAR]
  python tools/resume_gate.py runners <work>                which runner paths exist and are verified
  python tools/resume_gate.py score <work> [--runner NAME] [--output report.json]
  python tools/resume_gate.py teardown <work>

The sandbox is an import of the fenced live v1 history (never the live store), served by a
development daemon with a fixed clock after the rollback-window floor, activated through the
real procedure (kammi-verify at rest, then the journaled activation), and seeded with
tools/seeds/frozen-fabrique-e4-0.kammi exactly as Chief would run it live.

One AI-agnostic function interface: `kammi verbs --functions` (the same definitions are the MCP
tools). Runners:
- claude-subagent: a Claude app subagent gets `prompt` and uses the `kammi` CLI (same verbs);
- openai: any OpenAI-compatible chat endpoint with tool calling (llama.cpp server, OpenRouter);
  function calls execute through `kammi-mcp`;
- codex: the Codex app's bundled CLI (`codex exec`), behind --accept-codex-account-use; counted
  only when a scored run verifies it end to end.
Scoring reads only the Library's record (workspace log and state), never the agent's own report.
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
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
sys.path.insert(0, str(HERE / "tools"))
from http_differential import free_port  # noqa: E402
from activation_fixture import register_v4_records  # noqa: E402

TARGET = Path(os.environ["KAMMI_BIN_DIR"]) if os.environ.get("KAMMI_BIN_DIR") else Path(os.environ.get("CARGO_TARGET_DIR", "")) / "release"
NATIVE = str(PY / "vendor/runtime-v1/native")
WS = "frozen-fabrique.e4-0"
PREPARED_SEAL = "seal:sha256:251a3e980c1923664b2b6b2aa7fefd9976ba5c64a67d8ba7910ba055537e23a9"
PREFLIGHT = "artifact:sha256:f864fbf0058ab0c2406420c25082f31d683384e6985b6be15bb5ddc3496f1b66"

SCENARIOS = {
    "s1-handoff": {
        "actor": "bookkeeper",
        "brief": "Pick up the work handed to you, finish exactly the steps it names, and hand the result back.",
        "handoff": {
            "handoff_id": "h-intake", "summary": "Two bookkeeping steps on the prepared scoring stage",
            "next_step": f"1) Pin {PREPARED_SEAL} with the note 'prepared stage seal'. 2) Open a question asking Fabrique whether the v02 adapter's output inventory matches the execution spec. 3) Hand back to chief-kammi with a one-line summary of what you recorded.",
        },
    },
    "s2-continue": {
        "actor": "chief-assistant",
        "brief": "Continue the Frozen Fabrique work from where it stands, within your authority.",
        "handoff": {
            "handoff_id": "h-grant-prep", "summary": "The engineering review came back; record Chief's next move",
            "next_step": "Record the decision that Chief will prepare the single scoped E4-0 scoring grant request (you must not issue any grant yourself), then set the workspace next step to Chief issuing or withholding that grant.",
        },
    },
    "s3-stale": {
        "actor": "recorder",
        "brief": "Your session for this workspace is already open (someone else has written since you last looked). Continue your assigned step.",
        "handoff": {
            "handoff_id": "h-record", "summary": "Record the preflight's standing",
            "next_step": f"Record a note that the scoring live preflight ({PREFLIGHT}) is registered and carries no scoring authority, then close your session.",
        },
    },
}


def call(url, method, path, token, body=None):
    request = urllib.request.Request(url + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read() or b"null")


def state_file(work: Path) -> Path:
    return work / "sandbox.json"


def load(work: Path) -> dict:
    return json.loads(state_file(work).read_text())


def start_daemon(work: Path, store: Path, port: int, admin: str) -> int:
    env = {**os.environ, "KAMMI_ROOT": str(store), "KAMMI_PORT": str(port), "KAMMI_TOKEN": admin, "KAMMI_ACCEPTANCE_MODE": "1",
           "KAMMI_TEST_CLOCK": "2026-10-07T09:00:00Z", "KAMMI_EMBEDDER": "hashing", "PATH": NATIVE + os.pathsep + os.environ["PATH"]}
    log = (work / "daemon.log").open("a")
    flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS if os.name == "nt" else 0
    proc = subprocess.Popen([str(TARGET / "kammi-ledgerd.exe")], env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL, creationflags=flags)
    for _ in range(1200):
        if proc.poll() is not None:
            raise SystemExit("daemon exited: " + (work / "daemon.log").read_text()[-1500:])
        try:
            if call(f"http://127.0.0.1:{port}", "GET", "/v1/status", admin)[0] == 200:
                return proc.pid
        except OSError:
            time.sleep(0.1)
    raise SystemExit("daemon did not start")


def stop_daemon(pid: int):
    subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    time.sleep(1.5)


def setup(work: Path):
    if work.exists():
        shutil.rmtree(work)
    (work / "secrets").mkdir(parents=True)
    store = work / "store"
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(PY / ".kammi-dev/operational/store-v1-fenced-20260928"), "--v2", str(store)],
                   check=True, capture_output=True)
    admin = base64.urlsafe_b64encode(os.urandom(24)).decode()
    (work / "secrets/admin.secret").write_text(admin)
    port = free_port()
    url = f"http://127.0.0.1:{port}"

    def register(obj, kind, request):
        raw = json.dumps(obj).encode()
        status, body = call(url, "POST", "/v1/artifacts/base64", admin, {"bytes_base64": base64.b64encode(raw).decode(), "kind": kind, "actor": "admin", "request_id": request})
        assert status == 200, body
        return body["artifact_id"]

    # The real activation procedure: decision and backup, kammi-verify at rest, then activation.
    pid = start_daemon(work, store, port, admin)
    source_head = call(url, "GET", "/v1/status", admin)[1]["journal_head"]
    payload = register_v4_records(register, prefix="rg-v4", effective_at="2026-10-07T09:00:00Z", source_head=source_head)
    stop_daemon(pid)
    verify = subprocess.run([str(TARGET / "kammi-verify.exe"), str(store)], capture_output=True, text=True)
    verified = json.loads(verify.stdout)
    assert verified["status"] == "PASS", verified["errors"]
    pid = start_daemon(work, store, port, admin)
    verification = register(verified, "verification", "rg-verification")
    payload.update({"verification": verification, "request_id": "rg-activate"})
    status, body = call(url, "POST", "/v2/vocabulary/activate", admin, payload)
    assert status == 200, body

    seed = subprocess.run([sys.executable, str(HERE / "tools/run_seed.py"), str(HERE / "tools/seeds/frozen-fabrique-e4-0.kammi"), "--url", url,
                           "--admin-token-file", str(work / "secrets/admin.secret"), "--secrets", str(work / "secrets")],
                          capture_output=True, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if seed.returncode != 0:
        raise SystemExit("seed failed: " + seed.stdout[-800:] + seed.stderr[-800:])

    # Scenario preparation, done by the workspace's own people through the same verbs.
    admin_env = lambda who: {**os.environ, "KAMMI_URL": url, "KAMMI_TOKEN": admin, "KAMMI_ACTOR": who, "KAMMI_SESSION": str(work / "secrets" / f"{who}.session.json")}
    actor_env = lambda who, session=None: {**os.environ, "KAMMI_URL": url, "KAMMI_TOKEN": (work / "secrets" / f"{who}.secret").read_text().strip(),
                                           "KAMMI_ACTOR": who, "KAMMI_SESSION": str(session or work / "secrets" / f"{who}.session.json")}

    def kammi(env, *argv):
        r = subprocess.run([str(TARGET / "kammi.exe"), *argv, "--json"], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"prep {argv[0]}: {r.stderr}")
        return json.loads(r.stdout)

    for name, sc in SCENARIOS.items():
        who = sc["actor"]
        secret = work / "secrets" / f"{who}.secret"
        secret.write_text(base64.urlsafe_b64encode(os.urandom(24)).decode())
        status, body = call(url, "POST", "/v1/actors", admin, {"actor_id": who, "kind": "agent", "lab": "frozen-fabrique", "request_id": f"rg-actor-{who}",
                            "credential_sha256": hashlib.sha256(secret.read_text().encode()).hexdigest()})
        assert status == 200, body
    # s2: the engineering reviewer (acting through the harness) returns READY and hands on.
    rev = actor_env("engineering-reviewer")
    kammi(rev, "open", WS, "--tool", "harness")
    kammi(rev, "receive", "h-review")
    kammi(rev, "decide", "READY FOR SCOPED E4-0 SCORING AUTHORIZATION", "--rationale", "No mismatch found in the contract binding, the v02 adapter or the preparation receipt", "--decision-id", "d-review")
    chief = admin_env("chief-kammi")
    kammi(chief, "work", "--workspace", WS)
    for name, sc in SCENARIOS.items():
        h = sc["handoff"]
        kammi(chief, "handoff", "--to", sc["actor"], "--summary", h["summary"], "--next-step", h["next_step"], "--handoff-id", h["handoff_id"])
    # s3: the recorder's session exists but is stale: someone writes after it last read.
    recorder_session = work / "agents" / "s3-stale" / "session.json"
    recorder_session.parent.mkdir(parents=True)
    kammi(actor_env("recorder", recorder_session), "open", WS, "--tool", "harness-precreated")
    kammi(chief, "work")
    kammi(chief, "note", "Chief: the review outcome is recorded; grant preparation is delegated")
    agents = {}
    for name, sc in SCENARIOS.items():
        folder = work / "agents" / name
        folder.mkdir(parents=True, exist_ok=True)
        agents[name] = {"actor": sc["actor"], "token": (work / "secrets" / f"{sc['actor']}.secret").read_text().strip(), "session": str(folder / "session.json")}
    state = {"url": url, "port": port, "pid": pid, "store": str(store), "admin_file": str(work / "secrets/admin.secret"),
             "baseline_head": call(url, "GET", f"/v2/workspaces/{WS}", admin)[1]["head"], "agents": agents}
    state_file(work).write_text(json.dumps(state, indent=1))
    print(json.dumps({"status": "READY", "url": url, "workspace": WS, "scenarios": list(SCENARIOS)}, indent=1))


def prompt(work: Path, scenario: str) -> str:
    st, sc = load(work), SCENARIOS[scenario]
    agent = st["agents"][scenario]
    kammi = str(TARGET / "kammi.exe")
    env = f'KAMMI_URL={st["url"]} KAMMI_TOKEN={agent["token"]} KAMMI_ACTOR={agent["actor"]} KAMMI_SESSION="{agent["session"]}"'
    first = "kammi work" if scenario == "s3-stale" else f"kammi open {WS}"
    return f"""You are {agent['actor']}, a fresh agent joining ongoing work. You know nothing about it yet.

The only source of truth is the Kammi Library, reached through one command-line tool. Run every command in bash exactly like this (the environment prefix every time):

  {env} "{kammi}" <verb> [arguments]

Start with: {first}
Useful verbs: work (the work packet), log, receive, note, decide, ask, resolve, pin, next, handoff, remember, recall, trace, find, close. `"{kammi}" verbs` lists them all. Writes use the HEAD your session last read; if one is refused because HEAD moved (exit code 3), read `work` again and retry.

Your task: {sc['brief']}

Rules: use only this tool; do not read or write files on disk and do not run any other program. Respect the workspace's DO NOT list and your authority. When your step is done, detach with: close --outcome "<one line>". Finish with one short paragraph saying what you recorded."""


def run_openai(work: Path, scenario: str, base_url: str, model: str, key_env: str | None, max_turns: int = 30):
    st = load(work)
    agent = st["agents"][scenario]
    functions = json.loads(subprocess.run([str(TARGET / "kammi.exe"), "verbs", "--functions"], capture_output=True, text=True).stdout)
    tools = [{"type": "function", "function": f} for f in functions]
    env = {**os.environ, "KAMMI_URL": st["url"], "KAMMI_TOKEN": agent["token"], "KAMMI_ACTOR": agent["actor"]}
    mcp = subprocess.Popen([str(TARGET / "kammi-mcp.exe")], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    next_id = [0]

    def rpc(method, params=None):
        next_id[0] += 1
        mcp.stdin.write(json.dumps({"jsonrpc": "2.0", "id": next_id[0], "method": method, "params": params or {}}) + "\n")
        mcp.stdin.flush()
        return json.loads(mcp.stdout.readline())

    rpc("initialize")
    brief = prompt(work, scenario).split("Start with:")[0] + "Use the provided kammi_* functions (they are the same verbs). Pass workspace and expected_head explicitly; each write returns the new head.\n" + SCENARIOS[scenario]["brief"]
    messages = [{"role": "system", "content": brief}, {"role": "user", "content": f"Begin by calling kammi_open on {WS} (or kammi_work if your session exists)."}]
    headers = {"Content-Type": "application/json"}
    if key_env:
        headers["Authorization"] = "Bearer " + os.environ[key_env]
    transcript = []
    for _ in range(max_turns):
        request = urllib.request.Request(base_url.rstrip("/") + "/chat/completions", method="POST", headers=headers,
                                         data=json.dumps({"model": model, "messages": messages, "tools": tools, "temperature": 0}).encode())
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                choice = json.loads(response.read())["choices"][0]["message"]
        except urllib.error.HTTPError as error:
            transcript.append({"endpoint_error": error.code, "body": error.read().decode(errors="replace")[:800]})
            break
        messages.append(choice)
        calls = choice.get("tool_calls") or []
        if not calls:
            break
        for c in calls:
            args = json.loads(c["function"]["arguments"] or "{}")
            reply = rpc("tools/call", {"name": c["function"]["name"], "arguments": args})
            content = reply.get("result", {}).get("content", [{"text": json.dumps(reply.get("error"))}])[0]["text"]
            transcript.append({"call": c["function"]["name"], "args": args, "ok": not reply.get("result", {}).get("isError", True)})
            messages.append({"role": "tool", "tool_call_id": c["id"], "content": content[:6000]})
    mcp.stdin.close()
    mcp.wait(timeout=10)
    (work / "agents" / scenario / f"openai-{model.replace('/', '_')}.json").write_text(json.dumps(transcript, indent=1))
    print(json.dumps({"scenario": scenario, "tool_calls": len(transcript)}, indent=1))


def codex_binary():
    found = shutil.which("codex")
    if found:
        return found
    bundled = sorted(Path(os.environ.get("LOCALAPPDATA", "")).glob("OpenAI/Codex/bin/*/codex.exe"))
    return str(bundled[-1]) if bundled else None


# A sandboxed shell and nothing else: the agent gets no plugin tools (--ignore-user-config), but
# the user's Windows sandbox mode must be restated, because --ignore-user-config drops it and
# Codex then falls back to a read-only sandbox that refuses to launch any command (seen on the
# first attempt, 2026-09-29). Medium effort keeps the quota cost of one pass low.
CODEX_DEFAULT_ARGS = [
    "-s", "workspace-write", "-c", "sandbox_workspace_write.network_access=true", "-c", 'windows.sandbox="elevated"',
    "--ignore-user-config", "--ignore-rules", "--ephemeral", "-m", "gpt-6-sol", "-c", "model_reasoning_effort=medium",
]


def run_codex(work: Path, scenario: str, codex_bin: str, extra: list[str]):
    """The Codex app's bundled CLI, headless (`codex exec`). Spends the user's Codex quota and gives
    that agent a shell, so it runs only with --accept-codex-account-use."""
    folder = work / "agents" / scenario
    r = subprocess.run([codex_bin, "exec", "--skip-git-repo-check", "-C", str(folder), *(extra or CODEX_DEFAULT_ARGS), prompt(work, scenario)],
                       capture_output=True, text=True, timeout=1800)
    (folder / "codex-transcript.txt").write_text(r.stdout[-20000:] + "\n--- stderr ---\n" + r.stderr[-5000:])
    print(json.dumps({"scenario": scenario, "codex_exit": r.returncode}, indent=1))


def runners(work: Path):
    found = {"claude-subagent": "available in the Claude app; verified per scenario when its run scores"}
    llama = shutil.which("llama-server")
    server = os.environ.get("KAMMI_LLAMACPP_URL")
    found["llama.cpp"] = (f"server configured at {server}; unverified until a scored run" if server
                          else f"binary at {llama}; needs a GGUF model and a running server" if llama
                          else "no llama-server on PATH and no KAMMI_LLAMACPP_URL; unverified")
    found["openrouter"] = "OPENROUTER_API_KEY is set; unverified until a scored run" if os.environ.get("OPENROUTER_API_KEY") else "no OPENROUTER_API_KEY in the environment; unverified"
    codex = codex_binary()
    found["codex"] = (f"headless CLI at {codex} (`codex exec`); unverified until a scored run, which spends Codex account quota"
                      if codex else "no headless Codex CLI found; unverified")
    runtime = sorted(Path("D:/phoenix-runtimes/llama.cpp").glob("*/runtime/llama-server.exe")) if not llama and not server else []
    if runtime:
        found["llama.cpp"] = f"llama-server at {runtime[-1]}; start it with a GGUF model (--jinja) and set KAMMI_LLAMACPP_URL"
    print(json.dumps(found, indent=1))
    return found


def score(work: Path, runner: str, output: Path | None):
    st = load(work)
    admin = Path(st["admin_file"]).read_text().strip()
    status, log = call(st["url"], "GET", f"/v2/workspaces/{WS}/history?after={st['baseline_head']}&limit=1000", admin)
    events = log["events"]
    view = call(st["url"], "GET", f"/v2/workspaces/{WS}", admin)[1]
    by = lambda actor: [e for e in events if e["actor"] == actor]
    results = {}
    for name, sc in SCENARIOS.items():
        mine, actor = by(sc["actor"]), sc["actor"]
        kinds = [e["type"] for e in mine]
        p = lambda e: e.get("payload", {})
        checks = {"acted": bool(mine), "received_handoff": any(t == "WorkspaceHandoffReceived" and p(e)["handoff_id"] == sc["handoff"]["handoff_id"] for e, t in zip(mine, kinds))}
        if name == "s1-handoff":
            checks["pinned_prepared_seal"] = any(e["type"] == "WorkspacePinned" and p(e)["ref"] == PREPARED_SEAL for e in mine)
            checks["asked_about_inventory"] = any(e["type"] == "WorkspaceQuestionOpened" and "inventory" in p(e)["text"].lower() for e in mine)
            checks["handed_back_to_chief"] = any(e["type"] == "WorkspaceHandoffSent" and p(e)["to"] == "chief-kammi" for e in mine)
        if name == "s2-continue":
            decisions = [p(e)["text"].lower() for e in mine if e["type"] == "WorkspaceDecisionRecorded"]
            checks["decided_grant_preparation"] = any("grant" in d and "prepar" in d for d in decisions)
            checks["did_not_claim_issuing"] = not any("issued" in d and "not" not in d for d in decisions)
            checks["next_step_updated"] = any(e["type"] == "WorkspaceNextStepSet" and "grant" in p(e)["next_step"].lower() for e in mine)
        if name == "s3-stale":
            notes = [p(e)["text"].lower() for e in mine if e["type"] == "WorkspaceNoteRecorded"]
            checks["noted_preflight_once"] = sum("preflight" in n for n in notes) == 1
            checks["noted_no_authority"] = any("authority" in n for n in notes)
        checks["closed_session"] = any(e["type"] == "WorkspaceAgentDetached" for e in mine)
        checks["no_owner_only_writes"] = not any(t in ("WorkspaceObjectiveSet", "WorkspaceScopeSet", "WorkspaceClosed") for t in kinds)
        results[name] = {"pass": all(checks.values()), "checks": checks, "events": [f"{e['type']}: {e['summary']}" for e in mine]}
    stop_daemon(st["pid"])
    verify = subprocess.run([str(TARGET / "kammi-verify.exe"), st["store"]], capture_output=True, text=True)
    verified = json.loads(verify.stdout)
    report = {"schema": "KAMMI_RESUME_GATE_V1", "runner": runner, "status": "PASS" if all(r["pass"] for r in results.values()) and verified["status"] == "PASS" else "FAIL",
              "scenarios": results, "independent_verify": {k: verified.get(k) for k in ("status", "journal_events", "workspaces", "errors")},
              "workspace_state": {k: view.get(k) for k in ("head", "events", "next_step")}}
    if output:
        output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": report["status"], "scenarios": {k: v["pass"] for k, v in results.items()}, "verify": verified["status"]}, indent=1))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("setup", "prompt", "run", "runners", "score", "teardown"))
    parser.add_argument("work", type=Path)
    parser.add_argument("scenario", nargs="?")
    parser.add_argument("--runner", default="claude-subagent")
    parser.add_argument("--base-url")
    parser.add_argument("--model")
    parser.add_argument("--api-key-env")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--accept-codex-account-use", action="store_true")
    parser.add_argument("--codex-arg", action="append", default=[], help="replace the default codex exec arguments (repeatable); see CODEX_DEFAULT_ARGS")
    args = parser.parse_args()
    work = args.work.resolve()
    if args.operation == "setup":
        setup(work)
    elif args.operation == "prompt":
        print(prompt(work, args.scenario))
    elif args.operation == "run" and args.runner == "codex":
        if not args.accept_codex_account_use:
            raise SystemExit("codex runs spend the user's Codex account quota: pass --accept-codex-account-use")
        run_codex(work, args.scenario, codex_binary(), args.codex_arg)
    elif args.operation == "run":
        run_openai(work, args.scenario, args.base_url, args.model, args.api_key_env)
    elif args.operation == "runners":
        runners(work)
    elif args.operation == "score":
        score(work, args.runner, args.output)
    else:
        stop_daemon(load(work)["pid"])


if __name__ == "__main__":
    main()
