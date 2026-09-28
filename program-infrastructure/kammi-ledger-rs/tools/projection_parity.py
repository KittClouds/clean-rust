"""Row-level parity of two Ladybug custody projections, read through Python's own binding.

  python projection_parity.py <python.lbdb> <rust.lbdb>

Every node table is dumped with all properties, every rel table as (from key, to key,
properties), all sorted. The two dumps must be identical.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
NATIVE = HERE.parent / "kammi-ledger" / "vendor/runtime-v1/native"
os.environ["LBUG_C_API_LIB_PATH"] = str(NATIVE / "lbug_shared.dll")
os.add_dll_directory(str(NATIVE))
import ladybug as lb  # noqa: E402

KEYS = {"Seal": "root"}


def dump(path):
    db = lb.Database(str(path), read_only=True)
    conn = lb.Connection(db)
    tables = [(r[1], r[2]) for r in conn.execute("CALL SHOW_TABLES() RETURN *")]
    out = {}
    for name, kind in sorted(tables):
        if kind == "NODE":
            props = [r[1] for r in conn.execute(f"CALL TABLE_INFO('{name}') RETURN *")]
            cols = ", ".join(f"n.{p}" for p in props)
            rows = sorted(json.dumps(list(r), default=str) for r in conn.execute(f"MATCH (n:{name}) RETURN {cols}"))
            out[name] = rows
    for name, kind in sorted(tables):
        if kind == "REL":
            props = [r[1] for r in conn.execute(f"CALL TABLE_INFO('{name}') RETURN *")]
            extra = "".join(f", r.{p}" for p in props)
            rows = []
            for row in conn.execute(f"MATCH (a)-[r:{name}]->(b) RETURN label(a), a, label(b), b{extra}"):
                ka, kb = KEYS.get(row[0], "id"), KEYS.get(row[2], "id")
                rows.append(json.dumps([row[0], row[1][ka], row[2], row[3][kb], *row[4:]], default=str))
            out[name] = sorted(rows)
    conn.close()
    db.close()
    return out


def main():
    a, b = dump(sys.argv[1]), dump(sys.argv[2])
    report = {"tables": {}, "status": "PASS"}
    for name in sorted(set(a) | set(b)):
        ra, rb = a.get(name), b.get(name)
        same = ra == rb
        entry = {"python_rows": None if ra is None else len(ra), "rust_rows": None if rb is None else len(rb), "identical": same}
        if not same:
            report["status"] = "FAIL"
            sa, sb = set(ra or []), set(rb or [])
            entry["python_only"] = sorted(sa - sb)[:5]
            entry["rust_only"] = sorted(sb - sa)[:5]
        report["tables"][name] = entry
    print(json.dumps(report, indent=1))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
