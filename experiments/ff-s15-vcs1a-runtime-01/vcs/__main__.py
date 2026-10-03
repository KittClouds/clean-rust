"""python -m vcs <command>

  validate-schema  SCHEMA.json
  compile          --schema S.json --authority SRC.json [--out AUTH.json]        normalize + seal an authority source
  decide           --schema S.json --authority AUTH.json --envelope E.json [--context C.json] [--out R.json]
  replay           --schema S.json --authority AUTH.json --envelope E.json [--context C.json] --receipt R.json     (exit 1 unless byte-identical)
  evaluate         --schema S.json --authority AUTH.json --scalar SRC.json --cases NAME=FILE.jsonl [...] [--preregistration P.md]
                   applies FROZEN authorities unchanged to named case files; a FROZEN schema requires a preregistration file, a FIXTURE schema marks the output as no evidence.

No command fits or chooses regions or coordinates; those belong to the schema's owner. Exit 0 ok, 1 failed check, 2 refused."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import authority as A, canon, harness as H, schema as S, transport as T
from .canon import NotBound, VcsError


def _load(path):
    return canon.loads_strict(Path(path).read_bytes())


def _out(obj, path):
    text = json.dumps(obj, sort_keys=True, indent=1, ensure_ascii=True) + "\n"
    if path:
        Path(path).write_text(text, encoding="ascii", newline="\n")
    else:
        sys.stdout.write(text)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vcs", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("validate-schema", "compile", "decide", "replay", "evaluate"):
        p = sub.add_parser(name)
        if name == "validate-schema":
            p.add_argument("schema_path")
        else:
            p.add_argument("--schema", required=True)
            p.add_argument("--authority")
            p.add_argument("--envelope")
            p.add_argument("--context")
            p.add_argument("--receipt")
            p.add_argument("--scalar")
            p.add_argument("--cases", nargs="*")
            p.add_argument("--preregistration")
            p.add_argument("--resamples", type=int, default=1000)
        p.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        schema = S.load_schema(_load(a.schema_path if a.cmd == "validate-schema" else a.schema))
        if a.cmd == "validate-schema":
            _out({"schema_id": schema.schema_id, "schema_version": schema.schema_version, "status": schema.status, "schema_hash": schema.schema_hash, "coordinates": list(schema.coords)}, a.out)
            return 0
        if a.cmd == "compile":
            auth = A.load_authority(_load(a.authority), schema)
            _out(auth.spec, a.out)
            return 0
        auth = A.verify_authority(_load(a.authority), schema)
        if a.cmd in ("decide", "replay"):
            env = _load(a.envelope)
            ctx = _load(a.context) if a.context else {}
            if a.cmd == "decide":
                _out(A.decide(auth, env, ctx), a.out)
                return 0
            ok = A.replay(_load(a.receipt), auth, env, ctx)
            print("replay: byte-identical" if ok else "replay: DIFFERENT")
            return 0 if ok else 1
        grade = T.evidence_grade(schema, a.preregistration)
        scalar_src = _load(a.scalar)
        splits = {}
        for spec in a.cases or []:
            name, _, path = spec.partition("=")
            splits[name] = [H.check_case(schema, canon.loads_strict(line)) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
        if not splits:
            raise VcsError("evaluate needs at least one --cases NAME=FILE.jsonl")
        report = {"evidence": grade, "authority_id": auth.authority_id, "splits": {}}
        for name, cases in splits.items():
            strip = lambda one: {k: v for k, v in one.items() if k != "threshold"}  # noqa: E731
            src = strip(scalar_src) if isinstance(scalar_src, dict) else [strip(one) for one in scalar_src]
            report["splits"][name] = H.compare(schema, auth, src, cases, resamples=a.resamples, seed=f"cli|{name}")
        _out(report, a.out)
        return 0
    except NotBound as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    except VcsError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
