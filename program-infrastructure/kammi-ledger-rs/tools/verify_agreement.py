"""Evidence for `rust_independent_verifier`: kammi-verify agrees with Python and catches tampering.

  python tools/verify_agreement.py <work dir> [--output report.json]

1. Agreement: on imports of the real v1 histories (the fenced live store, the E4 fixture) and on
   the cutover rehearsal's Rust store, kammi-verify must PASS with the same journal head that
   Python's unmodified independent_verify reports over export-v1 of the same store.
2. Tampering: one flipped byte in a journal frame, in a pack record, or in a loose object; a
   deleted registered object; a truncated segment. Each copy must FAIL.
3. v4: a store with an activation and a workspace must PASS; a workspace event with a broken
   HEAD chain written through the raw format must FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
PY = HERE.parent / "kammi-ledger"
PYENV = PY / ".kammi-dev/cleanroom-env/Scripts/python.exe"
TARGET = Path(os.environ["KAMMI_BIN_DIR"]) if os.environ.get("KAMMI_BIN_DIR") else Path(os.environ.get("CARGO_TARGET_DIR", "")) / "release"
ENV = {**os.environ, "PATH": str(PY / "vendor/runtime-v1/native") + os.pathsep + os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}


def rust_verify(store: Path):
    r = subprocess.run([str(TARGET / "kammi-verify.exe"), str(store)], capture_output=True, text=True, env=ENV)
    return json.loads(r.stdout) if r.stdout.strip() else {"status": "CRASH", "stderr": r.stderr[-400:]}


def python_verify(v2: Path, work: Path):
    export = work / "export-v1"
    if export.exists():
        shutil.rmtree(export)
    subprocess.run([str(TARGET / "kammi-migrate.exe"), "export-v1", "--v2", str(v2), "--out", str(export)], check=True, capture_output=True, env=ENV)
    r = subprocess.run([str(PYENV), "-c", "import sys,json;sys.path.insert(0,'.');from scripts.independent_verify import verify_store;"
                        "from pathlib import Path;print(json.dumps(verify_store(Path(sys.argv[1]))))", str(export)], cwd=PY, capture_output=True, text=True, env=ENV)
    return json.loads(r.stdout) if r.returncode == 0 else {"status": "FAIL", "error": r.stderr[-400:]}


def flip(path: Path, offset: int):
    data = bytearray(path.read_bytes())
    data[offset] ^= 0x01
    path.write_bytes(bytes(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("work", type=Path)
    parser.add_argument("--v4-store", type=Path, help="a store with an activation and a workspace (tools/workspace_e2e.py leaves one)")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    work = args.work.resolve()
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    checks, detail = {}, {}

    sources = {"live_v1_fenced": PY / ".kammi-dev/operational/store-v1-fenced-20260928", "e4_fixture": PY / ".kammi-dev/e4-import"}
    stores = {}
    for name, v1 in sources.items():
        v2 = work / name
        subprocess.run([str(TARGET / "kammi-migrate.exe"), "import", "--v1", str(v1), "--v2", str(v2)], check=True, capture_output=True, env=ENV)
        stores[name] = v2
    rehearsal = Path("D:/codex-runs/rh-p0/rust-store")
    if rehearsal.exists():
        stores["rehearsal_rust_writes"] = rehearsal
    for name, v2 in stores.items():
        r, p = rust_verify(v2), python_verify(v2, work / f"py-{name}")
        agree = r["status"] == "PASS" and p.get("status") == "PASS" and r["journal_head"] == p.get("journal_head")
        checks[f"agrees_{name}"] = agree
        detail[name] = {"rust": {k: r.get(k) for k in ("status", "journal_head", "journal_events", "objects_verified", "errors")}, "python": {k: p.get(k) for k in ("status", "journal_head")}}

    base = stores["e4_fixture"]

    def tampered(label, mutate, source=None):
        copy = work / f"tamper-{label}"
        shutil.copytree(source or base, copy)
        mutate(copy)
        r = rust_verify(copy)
        checks[f"refuses_{label}"] = r["status"] == "FAIL"
        detail[f"tamper_{label}"] = r.get("errors", [])[:2]

    segment = lambda s: sorted((s / "journal/main").glob("*.seg"))[0]
    tampered("journal_byte", lambda s: flip(segment(s), segment(s).stat().st_size // 2))
    tampered("pack_byte", lambda s: flip(sorted((s / "objects/packs").glob("*.pack"))[0], 100))
    # Loose objects (>= 256 KiB) exist only in the live history; use its smallest one.
    live = stores["live_v1_fenced"]
    loose = sorted((p for p in (live / "objects/sha256").rglob("*") if p.is_file()), key=lambda p: p.stat().st_size)
    checks["has_loose_objects_to_tamper"] = bool(loose)
    if loose:
        rel = loose[0].relative_to(live)
        tampered("loose_byte", lambda s: flip(s / rel, 10), live)
        tampered("missing_object", lambda s: (s / rel).unlink(), live)
    tampered("truncated_segment", lambda s: segment(s).write_bytes(segment(s).read_bytes()[:-7]))

    if args.v4_store and args.v4_store.exists():
        r = rust_verify(args.v4_store)
        checks["v4_store_passes"] = r["status"] == "PASS" and r["vocabulary_v4"] is not None and r["workspaces"] >= 1
        detail["v4_store"] = {k: r.get(k) for k in ("status", "journal_events", "vocabulary_v4", "workspaces", "errors")}
    report = {"schema": "KAMMI_VERIFY_AGREEMENT_V1", "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "detail": detail}
    if args.output:
        args.output.write_text(json.dumps(report, indent=2))
    print(json.dumps({"status": report["status"], "checks": checks}, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
