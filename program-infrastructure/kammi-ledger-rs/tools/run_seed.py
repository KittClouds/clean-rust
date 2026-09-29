"""Runs a `.kammi` seed script (one `kammi` verb per line, plus @ directives) against a Library.

  python tools/run_seed.py <seed.kammi> --url <library> --admin-token-file <file> --secrets <dir> [--session-dir <dir>]

Directives (see tools/seeds/*.kammi): @actor, @admin, @as, @register. Actor credentials are
generated once and kept in --secrets as <actor>.secret (never printed). Each actor has its own
CLI session file, so HEAD tracking follows each writer. Stops at the first failing line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import shlex
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
TARGET = Path(os.environ["KAMMI_BIN_DIR"]) if os.environ.get("KAMMI_BIN_DIR") else Path(os.environ.get("CARGO_TARGET_DIR", "")) / "release"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("seed", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--admin-token-file", type=Path, required=True)
    parser.add_argument("--secrets", type=Path, required=True)
    parser.add_argument("--session-dir", type=Path)
    args = parser.parse_args()
    admin = args.admin_token_file.read_text().strip()
    args.secrets.mkdir(parents=True, exist_ok=True)
    sessions = args.session_dir or args.secrets
    variables, mode, actor, results = {}, "admin", "admin", []

    def token_of(who):
        return (args.secrets / f"{who}.secret").read_text().strip()

    for number, raw in enumerate(args.seed.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        for name, value in variables.items():
            line = line.replace(f"${name}", value)
        words = shlex.split(line, posix=True)
        if words[0] == "@actor":
            who, kind, lab = words[1:4]
            secret = args.secrets / f"{who}.secret"
            if not secret.exists():
                secret.write_text(secrets.token_urlsafe(32))
            body = json.dumps({"actor_id": who, "kind": kind, "lab": lab, "request_id": f"seed-actor-{who}",
                               "credential_sha256": hashlib.sha256(token_of(who).encode()).hexdigest()}).encode()
            request = urllib.request.Request(args.url + "/v1/actors", data=body, method="POST",
                                             headers={"Authorization": "Bearer " + admin, "Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=60) as response:
                results.append({"line": number, "actor": who, "status": response.status})
            continue
        if words[0] in ("@admin", "@as"):
            mode, actor = ("admin" if words[0] == "@admin" else "actor"), words[1]
            continue
        env = {**os.environ, "KAMMI_URL": args.url, "KAMMI_TOKEN": admin if mode == "admin" else token_of(actor),
               "KAMMI_ACTOR": actor, "KAMMI_SESSION": str(sessions / f"{actor}.session.json")}
        if words[0] == "@register":
            var, path, kind = words[1:4]
            file = (args.seed.parent / path).resolve()
            r = subprocess.run([str(TARGET / "kammi.exe"), "artifact", str(file), "--kind", kind, "--actor", actor], env=env, capture_output=True, text=True)
            if r.returncode != 0:
                raise SystemExit(f"line {number}: {r.stderr.strip()}")
            variables[var] = json.loads(r.stdout)["artifact_id"]
            results.append({"line": number, "register": var, "artifact_id": variables[var]})
            continue
        r = subprocess.run([str(TARGET / "kammi.exe"), *words, "--json"], env=env, capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit(f"line {number} ({words[0]}): {r.stderr.strip()}")
        out = json.loads(r.stdout)
        results.append({"line": number, "verb": words[0], "event_id": out.get("event_id")})
    print(json.dumps({"status": "PASS", "lines": results}, indent=1))


if __name__ == "__main__":
    main()
