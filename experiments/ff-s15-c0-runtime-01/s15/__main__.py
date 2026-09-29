"""Command line for the C0 reference runtime.

    python -m s15 check   --policy P --contracts DIR --bundles DIR
    python -m s15 run     --policy P --contracts DIR --bundles DIR --observation O --vector V [--out RECEIPT]
    python -m s15 replay  --policy P --contracts DIR --bundles DIR --observation O --vector V --receipt RECEIPT
    python -m s15 golden  [--update]
    python -m s15 show    FILE

Exit codes: 0 success, 1 a check or comparison failed, 2 unusable input.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import canon, model, runtime

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


def _world(args) -> model.World:
    return model.load_world(Path(args.policy), Path(args.contracts), Path(args.bundles))


def _case_inputs(observation_path: Path, vector_path: Path) -> tuple[dict, dict]:
    return canon.loads_strict(observation_path.read_bytes()), canon.loads_strict(vector_path.read_bytes())


def _summary(receipt: dict) -> str:
    return (f"{receipt['disposition']}"
            f"{' -> ' + receipt['disposition_target'] if receipt['disposition_target'] else ''}"
            f" | tier {receipt['escalation']['choice']} ({receipt['escalation']['reason']})"
            f" | cost {receipt['cost']['units']} | receipt {receipt['receipt_id']}")


def cmd_check(args) -> int:
    world = _world(args)
    print(f"ok: policy {world.policy['name']} r{world.policy['policy_revision']} {world.policy['policy_id']}; "
          f"{len(world.contracts)} contracts, {len(world.bundles)} bundles, {len(world.observers)} observers")
    return 0


def cmd_run(args) -> int:
    world = _world(args)
    observation, vector = _case_inputs(Path(args.observation), Path(args.vector))
    receipt, data = runtime.run(world, observation, vector)
    if args.out:
        Path(args.out).write_bytes(data)
    print(_summary(receipt))
    return 0


def cmd_replay(args) -> int:
    world = _world(args)
    observation, vector = _case_inputs(Path(args.observation), Path(args.vector))
    ok, message = runtime.replay(world, observation, vector, Path(args.receipt).read_bytes())
    print(("ok: " if ok else "FAIL: ") + message)
    return 0 if ok else 1


def cmd_golden(args) -> int:
    world = model.load_world(FIXTURES / "policy.json", FIXTURES / "contracts", FIXTURES / "bundles")
    failures, lines = 0, []
    for case in sorted(p for p in (FIXTURES / "cases").iterdir() if p.is_dir()):
        observation, vector = _case_inputs(case / "observation.json", case / "vector.json")
        receipt, data = runtime.run(world, observation, vector)
        expected = case / "expected-receipt.json"
        if args.update:
            expected.write_bytes(data)
            status = "written"
        elif not expected.exists():
            status, failures = "MISSING", failures + 1
        elif expected.read_bytes() != data:
            status, failures = "DIFFERS", failures + 1
        else:
            status = "identical"
        lines.append(f"{canon.sha256_id(data)[7:]}  {case.name}/expected-receipt.json")
        print(f"{status:9s} {case.name:28s} {_summary(receipt)}")
    if args.update:
        (FIXTURES / "GOLDEN.sha256").write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return 1 if failures else 0


def cmd_show(args) -> int:
    print(json.dumps(canon.loads_strict(Path(args.file).read_bytes()), indent=2, sort_keys=True))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="s15", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def world_args(p):
        p.add_argument("--policy", required=True)
        p.add_argument("--contracts", required=True)
        p.add_argument("--bundles", required=True)

    p = sub.add_parser("check")
    world_args(p)
    p.set_defaults(fn=cmd_check)
    p = sub.add_parser("run")
    world_args(p)
    p.add_argument("--observation", required=True)
    p.add_argument("--vector", required=True)
    p.add_argument("--out")
    p.set_defaults(fn=cmd_run)
    p = sub.add_parser("replay")
    world_args(p)
    p.add_argument("--observation", required=True)
    p.add_argument("--vector", required=True)
    p.add_argument("--receipt", required=True)
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("golden")
    p.add_argument("--update", action="store_true")
    p.set_defaults(fn=cmd_golden)
    p = sub.add_parser("show")
    p.add_argument("file")
    p.set_defaults(fn=cmd_show)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except (canon.CanonError, model.RecordError, runtime.InputError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
