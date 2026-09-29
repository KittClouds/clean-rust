"""The Library release routine (docs/RELEASE.md): stage, evidence, accept, switch, probe.

  python tools/release.py build                      reproducible build of the release binaries
  python tools/release.py plan                       what changed since the installed release, and the tier
  python tools/release.py run [--evidence-from DIR]  release HEAD to the live Library

Run from the kammi-ledger venv with CARGO_TARGET_DIR set. The live daemon hashes the release's
source snapshot, never this working tree, so nothing here touches the live flight gate until
`run` reaches the switch. Tiers:

- source-only: the new kammi-ledgerd and kammi-projector are byte-identical to the installed
  ones. Behavioural evidence produced by those binaries is reused (recorded in reuse.json);
  the workspace tests and the shell conformance run fresh.
- full: a daemon or projector binary changed. --evidence-from must hold fresh harness reports
  and a binaries.json showing they were produced by exactly the staged binaries.

The switch verifies the stopped live store at its current head, issues `kammi-ledgerd accept`
(staged binary, staged source snapshot), installs, starts and probes. Before v4 this uses the
Python export/restore verifier; after activation it uses a native-v2 copy and `kammi-verify`.
The post-v4 profile retires Python rollback and binds the four v4-specific acceptance gates.
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
from datetime import datetime, timezone
from pathlib import Path

RS = Path(__file__).resolve().parents[1]
REPO = RS.parents[1]
PY = RS.parent / "kammi-ledger"
PYENV = PY / ".kammi-dev/cleanroom-env/Scripts/python.exe"
sys.path.insert(0, str(RS / "tools"))
import rust_service as svc  # noqa: E402

OPS, STORE = svc.OPS, svc.STORE
TARGET = Path(os.environ.get("CARGO_TARGET_DIR", "")) / "release"
HASHED = {".rs", ".toml", ".lock", ".md", ".json", ".txt", ".wgsl"}
SKIP = {"target", "vendor", ".git", "tmp", "__pycache__"}
# kammi-verify ships with every release: the audit's independent verifier from activation on.
BINARIES = svc.BINARIES + ("kammi.exe", "kammi-mcp.exe", "kammi-verify.exe")
BEHAVIOUR = ("kammi-ledgerd.exe", "kammi-projector.exe")
NATIVE = str(PY / "vendor/runtime-v1/native")
V1_CORPUS = [PY / ".kammi-dev/operational/store-v1-fenced-20260928", PY / ".kammi-dev/e4-import"]
# Evidence produced per release (never reused) and the files the script writes itself.
FRESH = {"workspace-tests.txt", "shell-conformance.json", "backup-restore.json", "independent-verify.json", "evidence-map.json", "reuse.json"}


def now():
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def sh(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    return subprocess.run(cmd, **kw)


def tree(root: Path):
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(d for d in dirs if d not in SKIP)
        for name in sorted(files):
            yield (Path(directory) / name).relative_to(root)


def hashed_files(root: Path):
    return {rel.as_posix(): sha256(root / rel) for rel in tree(root) if rel.suffix in HASHED}


def installed():
    info = json.loads((OPS / "release.json").read_text())
    return info, OPS / info["release_dir"]


def evidence_dir(info: dict, release_dir: Path) -> Path:
    """Resolve the active evidence profile, including post-activation reacceptance evidence."""
    relative = info.get("evidence_dir", str(release_dir.relative_to(OPS) / "evidence"))
    return OPS / relative


# Phase 1 proofs, registered under the gates they support when present in the evidence.
SUPPLEMENTARY = {
    "verify-agreement.json": ["artifact_tamper", "journal_tamper", "cleanroom_replay"],
    "workspace-e2e.json": ["cleanroom_replay", "mcp_interface", "memory_plane"],
}


def evidence_map(evidence: Path | None = None, vocabulary_v4: bool = False):
    source = (RS / "tools/cutover_rehearsal.py").read_text(encoding="utf-8")
    start = source.index("EVIDENCE = {")
    namespace = {}
    exec(source[start:source.index("\n}\n", start) + 3], namespace)
    gates = namespace["EVIDENCE"]
    for gate in ("export_v1_rollback", "backup_restore", "shadow_zero_diff"):
        gates[gate] = gates[gate] + ["cutover-rollback-rehearsal.json"]
    for gate in ("mcp_interface", "python_sdk", "rust_sdk"):
        gates[gate] = gates[gate] + ["shell-conformance.json"]
    for name, supported in SUPPLEMENTARY.items():
        if evidence is not None and (evidence / name).exists():
            for gate in supported:
                gates[gate] = gates[gate] + [name]
    if vocabulary_v4:
        gates.pop("export_v1_rollback", None)
        gates.update({
            "rust_independent_verifier": ["verify-agreement.json"],
            "v4_replay_identity": ["workspace-e2e.json"],
            # The local 2B runner is a deliberately non-qualifying diagnostic and previously
            # failed 0/3; the gate is met by the qualified Claude resume run (3/3).
            "resume_gate": ["resume-gate-claude-devbuild.json"],
            "activation_rehearsal": ["activation-rehearsal.json"],
        })
    return {"gates": gates, "independent_verification": "independent-verify.json"}


def build():
    """Reproducible build (docs/RELEASE.md): each behaviour binary alone, so feature unification
    with unrelated workspace members cannot change its bytes; /Brepro comes from .cargo/config.toml."""
    for packages in (["-p", "kammi-ledgerd"], ["-p", "kammi-projector"],
                     ["-p", "kammi-migrate", "-p", "kammi-core", "-p", "kammi-shell", "-p", "kammi-verify"]):
        result = sh(["cargo", "build", "--release", *packages], cwd=RS)
        if result.returncode != 0:
            raise SystemExit("build failed:\n" + result.stderr[-2000:])


def plan():
    info, current = installed()
    status = sh(["git", "status", "--porcelain", "--", str(RS)], cwd=REPO).stdout.strip()
    commit = sh(["git", "rev-parse", "--short=8", "HEAD"], cwd=REPO).stdout.strip()
    before, after = hashed_files(current / "source"), hashed_files(RS)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    built = {name: sha256(TARGET / name) for name in BINARIES if (TARGET / name).exists()}
    old_bins = json.loads((current / "binaries.json").read_text())
    behaviour_same = all(built.get(b) == old_bins.get(b) for b in BEHAVIOUR)
    return {"installed": info["commit"], "head": commit, "tree_clean": not status, "dirty": status.splitlines()[:20],
            "hashed_files_changed": changed, "binaries_built": built,
            "behaviour_binaries_unchanged": behaviour_same, "tier": "source-only" if behaviour_same else "full"}


def run_tests(evidence: Path):
    env = {**os.environ, "KAMMI_V1_CORPUS": ";".join(map(str, V1_CORPUS)), "KAMMI_JCS_PYTHON": str(PY / ".venv/Scripts/python.exe"),
           "KAMMI_LEDGER_PY": str(PY), "KAMMI_JCS_ORACLE_CASES": "1000000", "KAMMI_CRASH_RANDOM": "300",
           "KAMMI_WORK_DIR": str(Path(os.environ["CARGO_TARGET_DIR"]) / "acceptance-work"),
           # Tests build with unified features; a separate target keeps them from relinking the
           # release binaries that later steps and harnesses run.
           "CARGO_TARGET_DIR": os.environ["CARGO_TARGET_DIR"].rstrip("/\\") + "-tests"}
    with (evidence / "workspace-tests.txt").open("w") as log:
        code = subprocess.run(["cargo", "test", "--release", "--workspace", "--", "--nocapture"], cwd=RS, env=env,
                              stdout=log, stderr=subprocess.STDOUT).returncode
    text = (evidence / "workspace-tests.txt").read_text(errors="replace")
    if code != 0 or "FAILED" in text or "panicked" in text or "test result: ok" not in text:
        raise RuntimeError("workspace tests failed; see workspace-tests.txt")


def verify_at_head(bin_dir: Path, work: Path, evidence: Path, vocabulary_v4: bool = False):
    """Verify the stopped store using the active format's restore and verifier path."""
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    env = {**os.environ, "PATH": NATIVE + os.pathsep + os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}
    if vocabulary_v4:
        restored = work / "restored-v2"
        shutil.copytree(STORE, restored, ignore=shutil.ignore_patterns("projection", "projection-*", "locks"))
        live = sh([str(bin_dir / "kammi-verify.exe"), str(STORE)], env=env)
        back = sh([str(bin_dir / "kammi-verify.exe"), str(restored)], env=env)
        live_result = json.loads(live.stdout) if live.returncode == 0 and live.stdout.strip() else {"status": "FAIL", "error": live.stderr[-600:]}
        back_result = json.loads(back.stdout) if back.returncode == 0 and back.stdout.strip() else {"status": "FAIL", "error": back.stderr[-600:]}
        comparable = ("journal_head", "journal_events", "objects_verified", "vocabulary_v4", "workspaces")
        identical = (live_result.get("status") == back_result.get("status") == "PASS"
                     and all(live_result.get(k) == back_result.get(k) for k in comparable))
        (evidence / "backup-restore.json").write_text(json.dumps({
            "schema": "KAMMI_RUST_BACKUP_RESTORE_V2", "status": "PASS" if identical else "FAIL",
            "scope": "release: byte-copy of the stopped native v2 store; Rust verifier state agrees",
            "restore_method": "copytree excluding disposable projection and locks",
            "restored_state_identical": identical,
            "live": {k: live_result.get(k) for k in comparable + ("status",)},
            "restored": {k: back_result.get(k) for k in comparable + ("status",)},
        }, indent=1))
        (evidence / "independent-verify.json").write_text(json.dumps(live_result, indent=1))
        if not identical:
            raise RuntimeError(f"native v2 verification/restore mismatch: live={live_result}, restored={back_result}")
        return live_result["journal_head"]
    export, restored = work / "export-v1", work / "restored"
    for cmd in ([bin_dir / "kammi-migrate.exe", "export-v1", "--v2", STORE, "--out", export],
                [bin_dir / "kammi-migrate.exe", "import", "--v1", export, "--v2", restored]):
        result = sh([str(c) for c in cmd], env=env)
        if result.returncode != 0:
            raise RuntimeError(f"{cmd[1]} failed: {result.stderr[-400:]}")
    live, back = sh([str(bin_dir / "kammi-state-dump.exe"), str(STORE)], env=env), sh([str(bin_dir / "kammi-state-dump.exe"), str(restored)], env=env)
    identical = live.returncode == back.returncode == 0 and live.stdout == back.stdout
    (evidence / "backup-restore.json").write_text(json.dumps({"schema": "KAMMI_RUST_BACKUP_RESTORE_V1", "status": "PASS" if identical else "FAIL",
        "scope": "release: export-v1 of the stopped live store, re-imported; state identical", "restored_state_identical": identical}, indent=1))
    audit = sh([str(PYENV), "-c", "import sys,json;sys.path.insert(0,'.');from scripts.independent_verify import verify_store;"
                "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[1]))))", str(export)], cwd=PY, env=env)
    (evidence / "independent-verify.json").write_text(audit.stdout if audit.returncode == 0 else json.dumps({"status": "FAIL", "error": audit.stderr[-600:]}))
    verified = json.loads((evidence / "independent-verify.json").read_text())
    if not identical or verified.get("status") != "PASS":
        raise RuntimeError(f"verification at head failed: restore identical={identical}, independent_verify={verified.get('status')}")
    return verified["journal_head"]


def accept(bin_dir: Path, source: Path, evidence: Path, request_id: str):
    result = sh([str(bin_dir / "kammi-ledgerd.exe"), "accept", "--store", str(STORE), "--evidence-map", str(evidence / "evidence-map.json"),
                 "--request-id", request_id], env={**os.environ, "KAMMI_SOURCE_DIR": str(source)})
    if result.returncode != 0:
        raise RuntimeError(f"accept refused: {result.stderr[-800:]}")
    receipt = json.loads(result.stdout)
    if receipt.get("status") != "PASS":
        raise RuntimeError(f"accept did not open the gate: {receipt}")
    return receipt


def stop_all():
    """Stops the installed daemon and waits for its projector child (matched by path, never by name)."""
    stopped = svc.stop()
    for _ in range(120):
        remaining = svc.pids()
        if not remaining:
            return stopped
        time.sleep(0.5)
    for pid, _, _ in svc.pids():
        sh(["taskkill", "/F", "/PID", str(pid)])
    time.sleep(1)
    if svc.pids():
        raise RuntimeError(f"processes under {svc.BIN} would not stop: {svc.pids()}")
    return stopped


def install(release_dir: Path, info: dict):
    for name in BINARIES:
        if (release_dir / "bin" / name).exists():
            shutil.copy2(release_dir / "bin" / name, svc.BIN / name)
    (OPS / "release.json").write_text(json.dumps(info, indent=1))


def reaccept_v4(evidence_from: Path):
    """Bind the current v4 flight to the post-activation acceptance profile, without a code switch."""
    if not svc.vocabulary_v4_active():
        raise SystemExit("reaccept-v4 requires LibraryVocabularyActivated in the live journal")
    info, release_dir = installed()
    bin_dir = OPS / info["bin_dir"]
    source_dir = OPS / info["source_dir"]
    produced = json.loads((evidence_from / "binaries.json").read_text(encoding="utf-8"))
    installed_hashes = {name: sha256(bin_dir / name) for name in BINARIES}
    if any(produced.get(name) != digest for name, digest in installed_hashes.items()):
        raise SystemExit("v4 evidence was not produced by the currently installed release binaries")

    stamp = now()
    work = OPS / "v4-acceptance" / stamp
    evidence = work / "evidence"
    evidence.mkdir(parents=True, exist_ok=False)
    replaced_during_reacceptance = {"backup-restore.json", "independent-verify.json", "evidence-map.json", "reuse.json"}
    for item in evidence_from.iterdir():
        if item.is_file() and item.name not in replaced_during_reacceptance and item.name != "binaries.json":
            shutil.copy2(item, evidence / item.name)
    (evidence / "binaries.json").write_text(json.dumps(produced, indent=1), encoding="utf-8")
    mapping = evidence_map(evidence, vocabulary_v4=True)
    if len(mapping["gates"]) != 35:
        raise RuntimeError(f"post-v4 evidence map has {len(mapping['gates'])} gates, expected 35")
    (evidence / "evidence-map.json").write_text(json.dumps(mapping, indent=1), encoding="utf-8")

    report = {"schema": "KAMMI_V4_REACCEPTANCE_V1", "started": now(), "commit": info["commit"],
              "gates": len(mapping["gates"]), "steps": []}
    try:
        stop_all()
        head = verify_at_head(bin_dir, work / "verify", evidence, vocabulary_v4=True)
        report["verified_head"] = head
        receipt = accept(bin_dir, source_dir, evidence, f"rust-v4-reaccept-{stamp}")
        report["acceptance"] = receipt
        restarted = svc.start()
        status = restarted["status"]
        if status.get("flight_gate") != "OPEN" or status.get("acceptance_identity") != receipt["acceptance_identity"]:
            raise RuntimeError(f"post-v4 reacceptance did not reopen the same release: {status}")
        report["status"] = "PASS"
        report["flight_gate"] = status["flight_gate"]
    except BaseException as exc:
        report["status"] = "FAIL"
        report["error"] = f"{type(exc).__name__}: {exc}"
        try:
            svc.start()
        except Exception as restart_error:  # noqa: BLE001
            report["restart_error"] = str(restart_error)
        (work / "reacceptance-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
        raise

    destination = release_dir / f"evidence-v4-{stamp}"
    shutil.copytree(evidence, destination)
    report["evidence_dir"] = str(destination)
    (destination / "reacceptance-report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    info["acceptance_identity"] = receipt["acceptance_identity"]
    info["evidence_dir"] = str(destination.relative_to(OPS)).replace("\\", "/")
    info["acceptance_profile"] = "v4"
    (OPS / "release.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    with (OPS / "reacceptance-history.jsonl").open("a", encoding="utf-8") as history:
        history.write(json.dumps({"commit": info["commit"], "acceptance_identity": info["acceptance_identity"],
                                  "profile": "v4", "journal_head": head, "utc": now(),
                                  "evidence_dir": info["evidence_dir"]}) + "\n")
    print(json.dumps({"status": report["status"], "acceptance_identity": info["acceptance_identity"],
                      "journal_head": head, "evidence_dir": info["evidence_dir"]}, indent=1))


def probes(commit: str, acceptance: str):
    token = svc.admin_token()
    env = {**os.environ, "KAMMI_URL": f"http://127.0.0.1:{svc.PORT}", "KAMMI_TOKEN": token, "PYTHONDONTWRITEBYTECODE": "1"}
    out = {}
    status = svc.status()
    out["flight_open_with_new_acceptance"] = status["flight_gate"] == "OPEN" and status["acceptance_identity"] == acceptance
    kammi = sh([str(svc.BIN / "kammi.exe"), "status"], env=env)
    out["rust_kammi_status"] = kammi.returncode == 0 and json.loads(kammi.stdout)["acceptance_identity"] == acceptance
    messages = "".join(json.dumps(m) + "\n" for m in ({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                                                        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}))
    mcp = sh([str(svc.BIN / "kammi-mcp.exe")], env=env, input=messages)
    replies = [json.loads(line) for line in mcp.stdout.splitlines()] if mcp.returncode == 0 else []
    # The 24 fixed v1 tools come first, unchanged; releases from Vault Phase 1 on add kammi_* verbs.
    names = [t["name"] for t in replies[1]["result"]["tools"]] if len(replies) == 2 else []
    out["rust_kammi_mcp"] = len(names) >= 24 and names[23] == "memory_neighbors" and all(n.startswith("kammi_") for n in names[24:])
    cli = sh([str(PYENV), "-m", "ledgerd.cli", "status"], env=env, cwd=PY)
    out["python_cli"] = cli.returncode == 0 and json.loads(cli.stdout)["flight_gate"] == "OPEN"
    sys.path.insert(0, str(PY))
    from cutover_rehearsal import probe_authorize
    from ledgerd.client import KammiClient
    out["authorize"] = probe_authorize(KammiClient(env["KAMMI_URL"], token), env["KAMMI_URL"], f"release-probe-{commit}", "kammi-ops") == "AUTHORIZED"
    return out


def run(args):
    report = {"schema": "KAMMI_LIBRARY_RELEASE_V1", "started": now(), "steps": []}
    step = lambda name, **fields: (report["steps"].append({"step": name, "utc": now(), **fields}), print(f"-- {name} {json.dumps(fields)[:300]}", flush=True))
    vocabulary_v4 = svc.vocabulary_v4_active()
    report["vocabulary_profile"] = "v4" if vocabulary_v4 else "v1"
    p = plan()
    if not p["tree_clean"]:
        raise SystemExit(f"working tree not clean (commit first): {p['dirty']}")
    old_info, old_dir = installed()
    commit = p["head"]
    if commit == old_info["commit"]:
        raise SystemExit(f"{commit} is already the installed release")
    build()
    p = plan()
    step("plan", tier=p["tier"], installed=p["installed"], head=commit, hashed_files_changed=p["hashed_files_changed"])

    new_dir = OPS / "releases" / commit
    if new_dir.exists():
        shutil.rmtree(new_dir)
    (new_dir / "bin").mkdir(parents=True)
    for rel in tree(RS):
        target = new_dir / "source" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RS / rel, target)
    if hashed_files(new_dir / "source") != hashed_files(RS):
        raise SystemExit("source snapshot differs from the tree")
    bins = {}
    for name in BINARIES:
        shutil.copy2(TARGET / name, new_dir / "bin" / name)
        bins[name] = sha256(new_dir / "bin" / name)
    (new_dir / "binaries.json").write_text(json.dumps(bins, indent=1))
    step("staged", source_files=sum(1 for _ in tree(new_dir / "source")), binaries=bins)

    evidence = new_dir / "evidence"
    evidence.mkdir()
    if p["tier"] == "source-only":
        reused = []
        old_evidence = evidence_dir(old_info, old_dir)
        for f in sorted(old_evidence.iterdir()):
            if f.name not in FRESH and f.name != "stress-run1-original-a7.json":
                shutil.copy2(f, evidence / f.name)
                reused.append(f.name)
        (evidence / "reuse.json").write_text(json.dumps({"status": "PASS", "reused_from_release": old_info["commit"], "files": reused,
            "because": {b: bins[b] for b in BEHAVIOUR}, "rule": "docs/RELEASE.md: behaviour evidence is reused only when kammi-ledgerd and kammi-projector are byte-identical"}, indent=1))
    else:
        if not args.evidence_from:
            raise SystemExit("tier full: a daemon or projector binary changed; run the harnesses and pass --evidence-from")
        produced = json.loads((args.evidence_from / "binaries.json").read_text())
        if any(produced.get(b) != bins[b] for b in BEHAVIOUR):
            raise SystemExit("--evidence-from was not produced by the staged binaries")
        for f in args.evidence_from.iterdir():
            if f.name not in FRESH:
                shutil.copy2(f, evidence / f.name)
    step("evidence: workspace tests (fresh)")
    run_tests(evidence)
    shell_env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "KAMMI_BIN_DIR": str(new_dir / "bin")}
    conformance = sh([sys.executable, str(RS / "tools/shell_conformance.py"), str(new_dir / "work/shell"), "--output", str(evidence / "shell-conformance.json")],
                     cwd=PY, env=shell_env)
    if conformance.returncode != 0:
        raise SystemExit("shell conformance failed:\n" + conformance.stdout[-1500:])
    (evidence / "evidence-map.json").write_text(json.dumps(evidence_map(evidence, vocabulary_v4), indent=1))
    step("evidence ready", files=sorted(f.name for f in evidence.iterdir()))

    # --- switch: from here the live Library is briefly down
    report["downtime_started"] = now()
    step("stop", **stop_all())
    accepted = None
    try:
        head = verify_at_head(new_dir / "bin", new_dir / "work/verify", evidence, vocabulary_v4)
        step("verified at head", journal_head=head)
        receipt = accept(new_dir / "bin", new_dir / "source", evidence, f"rust-release-{commit}-{now()}")
        accepted = receipt["acceptance_identity"]
        step("accepted", acceptance_identity=accepted, source_root=receipt["source_root"], runtime_identity=receipt["runtime_identity"])
        info = {"commit": commit, "release_dir": f"releases/{commit}", "source_dir": f"releases/{commit}/source", "evidence_dir": f"releases/{commit}/evidence",
                "bin_dir": f"releases/{commit}/bin", "acceptance_identity": accepted, "kammi_ledgerd_sha256": bins["kammi-ledgerd.exe"],
                "released_utc": now(), "via": f"tools/release.py ({p['tier']})", "previous": old_info["commit"]}
        install(new_dir, info)
        started = svc.start()
        report["downtime_ended"] = now()
        step("started", state=started["state"], flight=started["status"]["flight_gate"])
        checks = probes(commit, accepted)
        step("probes", **checks)
        if not all(checks.values()):
            raise RuntimeError(f"probes failed: {checks}")
    except Exception as exc:
        step("FAILED", error=str(exc)[:800])
        stop_all()
        if accepted:
            fallback = old_dir / f"evidence-fallback-{now()}"
            old_evidence = evidence_dir(old_info, old_dir)
            shutil.copytree(old_evidence, fallback)
            verify_at_head(old_dir / "bin", new_dir / "work/fallback", fallback, vocabulary_v4)
            old_receipt = accept(old_dir / "bin", old_dir / "source", fallback, f"rust-release-fallback-{old_info['commit']}-{now()}")
            old_info = {**old_info, "acceptance_identity": old_receipt["acceptance_identity"], "released_utc": now(), "via": f"fallback from {commit}"}
            step("re-accepted previous release", acceptance_identity=old_receipt["acceptance_identity"])
        install(old_dir, old_info)
        restarted = svc.start()
        report["downtime_ended"] = now()
        step("previous release serving", flight=restarted["status"]["flight_gate"])
        report["status"] = "FAIL"
        (new_dir / "release-report.json").write_text(json.dumps(report, indent=1))
        raise SystemExit(f"release failed and was rolled back: {exc}")
    report["status"] = "PASS"
    (new_dir / "release-report.json").write_text(json.dumps(report, indent=1))
    with (OPS / "releases.jsonl").open("a") as history:
        history.write(json.dumps({"commit": commit, "previous": old_info["commit"], "acceptance_identity": accepted, "tier": p["tier"],
                                  "utc": now(), "downtime": [report["downtime_started"], report["downtime_ended"]]}) + "\n")
    print(json.dumps({"status": "PASS", "commit": commit, "acceptance_identity": accepted, "tier": p["tier"]}, indent=1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("build", "plan", "run", "reaccept-v4"))
    parser.add_argument("--evidence-from", type=Path)
    args = parser.parse_args()
    if args.operation == "build":
        build()
        print(json.dumps({name: sha256(TARGET / name) for name in BINARIES}, indent=1))
    elif args.operation == "plan":
        print(json.dumps(plan(), indent=1))
    elif args.operation == "reaccept-v4":
        if not args.evidence_from:
            raise SystemExit("reaccept-v4 requires --evidence-from <qualified evidence directory>")
        reaccept_v4(args.evidence_from.resolve())
    else:
        run(args)
