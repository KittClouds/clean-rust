"""Small client-only CLI; it never opens Ladybug directly."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .client import KammiClient
from uuid import uuid4


def main() -> None:
    parser = argparse.ArgumentParser(prog="kammi")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    call = sub.add_parser("call")
    call.add_argument("method", choices=["GET", "POST"])
    call.add_argument("endpoint")
    call.add_argument("--body", type=Path)
    artifact = sub.add_parser("artifact")
    artifact.add_argument("path", type=Path)
    artifact.add_argument("--kind", required=True)
    artifact.add_argument("--actor", required=True)
    run = sub.add_parser("run")
    run.add_argument("run_id")
    run.add_argument("lab")
    run.add_argument("--actor", required=True)
    seal = sub.add_parser("seal")
    seal.add_argument("--member", action="append", default=[])
    seal.add_argument("--parent", action="append", default=[])
    seal.add_argument("--actor", required=True)
    lineage = sub.add_parser("lineage")
    lineage.add_argument("root")
    history = sub.add_parser("history")
    history.add_argument("run_id")
    history.add_argument("--summary", action="store_true")
    args = parser.parse_args()
    client = KammiClient.from_environment()
    if args.command == "status":
        result = client.status()
    elif args.command == "call":
        result = client.call(args.method, args.endpoint,
                             json.loads(args.body.read_text()) if args.body else None)
    elif args.command == "artifact":
        result = client.register_file(args.path, args.kind, args.actor, str(uuid4()))
    elif args.command == "run":
        result = client.create_run(args.run_id, args.lab, args.actor, str(uuid4()))
    elif args.command == "seal":
        result = client.create_seal(args.member, args.parent, args.actor, str(uuid4()))
    elif args.command == "history":
        result = (client.history_summary(args.run_id) if args.summary
                  else client.history(args.run_id))
    else:
        result = client.lineage(args.root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

