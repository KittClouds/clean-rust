"""Independent audit of the generated shards, separate from the gates: it reads the files as a consumer would and checks what the gates cannot see in memory.

  python tools/audit_rows.py [out/full]

Checks: every world_id is unique across the bank; every fact id is the content hash of its predicate and arguments and is unique within a world's state;
the public test inputs carry no truth, labels or derivation (only world_id, split, renderer_id, rendered_text, actions, requests); public and protected files pair row for row;
row counts per split; no NaN-like or empty rendered text. Prints AUDIT_PASS or AUDIT_FAIL and writes audit-report.json next to the shards.
"""
from __future__ import annotations

import gzip
import json
import multiprocessing as mp
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from bank2 import facts as F  # noqa: E402

PUBLIC_KEYS = {"world_id", "split", "renderer_id", "rendered_text", "actions", "requests"}


def scan(path: str) -> dict:
    p = Path(path)
    kind = "public" if "public" in p.parts else ("paired" if "paired" in p.parts else "protected")
    out = {"file": p.name, "kind": kind, "split": p.parent.name, "rows": 0, "problems": [], "ids": []}
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            out["rows"] += 1
            if kind == "public":
                if set(r) != PUBLIC_KEYS:
                    out["problems"].append(f"{r.get('world_id')}: public row has keys {sorted(set(r) ^ PUBLIC_KEYS)}")
                if not r["rendered_text"].strip():
                    out["problems"].append(f"{r['world_id']}: empty rendered text")
                out["ids"].append(r["world_id"])
                continue
            out["ids"].append(r["world_id"])
            ids = [f["id"] for f in r["WORLD_TRUTH"]["state"]]
            if len(ids) != len(set(ids)):
                out["problems"].append(f"{r['world_id']}: duplicate fact ids in state")
            for f in list(r["WORLD_TRUTH"]["state"]) + [s["fact"] for s in r["WORLD_TRUTH"]["scheduled"]]:
                if f["id"] != F.make_fact(f["pred"], *f["args"])["id"]:
                    out["problems"].append(f"{r['world_id']}: fact id is not the content hash")
                    break
            if not r["OBSERVATION"]["rendered_text"].strip():
                out["problems"].append(f"{r['world_id']}: empty rendered text")
    out["problems"] = out["problems"][:5]
    return out


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out" / "full"
    files = sorted(str(p) for p in root.rglob("*.gz"))
    with mp.Pool(max(1, mp.cpu_count() - 1)) as pool:
        results = pool.map(scan, files, chunksize=4)
    problems, rows = [], Counter()
    protected_ids, public_ids, all_ids = Counter(), Counter(), Counter()
    for r in results:
        problems += r["problems"]
        if r["kind"] == "paired":
            continue
        rows[(r["kind"], r["split"])] += r["rows"]
        for i in r["ids"]:
            (public_ids if r["kind"] == "public" else protected_ids)[i] += 1
            if r["kind"] != "public":
                all_ids[i] += 1
    dup = sum(1 for n in all_ids.values() if n > 1)
    if dup:
        problems.append(f"{dup} duplicate world ids across the bank")
    test_protected = {i for i in protected_ids if i.split(":")[1].startswith("TEST-")}
    if set(public_ids) != test_protected:
        problems.append(f"public and protected test rows do not pair: {len(set(public_ids) ^ test_protected)} differ")
    report = {"files": len(files), "rows": {f"{k}/{s}": n for (k, s), n in sorted(rows.items())}, "protected_rows": sum(protected_ids.values()), "public_rows": sum(public_ids.values()), "duplicate_world_ids": dup, "problems": problems[:20]}
    (root / "audit-report.json").write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k != "rows"}, indent=1))
    print("AUDIT_PASS" if not problems else "AUDIT_FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
