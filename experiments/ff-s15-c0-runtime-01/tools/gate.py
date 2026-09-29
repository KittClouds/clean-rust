"""The C0 gate, end to end, with a hash-anchored report.

  python tools/gate.py [--out evidence/c0-gate-report.json]

Passes only if: schemas and fixtures match their generators; the whole test suite passes; every
golden case reproduces byte for byte in separate processes under different hash seeds, working
directories and interpreter flags; and two independent `run` processes agree with the stored receipt.

The report's `results` block is deterministic (hashes and verdicts); `environment` is informational
and is not part of what the gate certifies. There is no timestamp: time belongs to the Kammi journal.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from s15 import canon, model, runtime  # noqa: E402

FIX = ROOT / "fixtures"
MATRIX = [({"PYTHONHASHSEED": "0"}, []), ({"PYTHONHASHSEED": "1"}, []), ({"PYTHONHASHSEED": "4242"}, ["-O"]), ({"PYTHONHASHSEED": "random"}, ["-X", "utf8=0"])]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sub(args, cwd=None, env=None):
    return subprocess.run(args, cwd=cwd, env={**os.environ, "PYTHONPATH": str(ROOT), **(env or {})}, capture_output=True, text=True, timeout=900)


def main() -> int:
    out = None
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1])
    checks: dict = {}

    checks["schemas_match_generator"] = sub([sys.executable, str(ROOT / "tools" / "build_schemas.py"), "--check"]).returncode == 0
    checks["fixtures_match_builder"] = sub([sys.executable, str(ROOT / "tools" / "make_fixtures.py"), "--check"]).returncode == 0

    suite = sub([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", "."], cwd=ROOT)
    ran = re.search(r"Ran (\d+) tests", suite.stderr)
    checks["test_suite"] = {"ran": int(ran.group(1)) if ran else 0, "passed": suite.returncode == 0}

    world = model.load_world(FIX / "policy.json", FIX / "contracts", FIX / "bundles")
    cases, stored = {}, {}
    for case in sorted(p for p in (FIX / "cases").iterdir() if p.is_dir()):
        observation = canon.loads_strict((case / "observation.json").read_bytes())
        vector = canon.loads_strict((case / "vector.json").read_bytes())
        receipt, data = runtime.run(world, observation, vector)
        stored[case.name] = (case / "expected-receipt.json").read_bytes()
        cases[case.name] = {
            "inputs_sha256": sha((case / "observation.json").read_bytes() + b"\n" + (case / "vector.json").read_bytes()), "receipt_sha256": sha(data),
            "tier": receipt["escalation"]["choice"], "disposition": receipt["disposition"], "cost_units": receipt["cost"]["units"], "matches_golden": data == stored[case.name],
        }
    checks["in_process_matches_golden"] = all(c["matches_golden"] for c in cases.values())

    matrix = []
    with tempfile.TemporaryDirectory() as elsewhere:
        for env, flags in MATRIX:
            done = sub([sys.executable, *flags, "-m", "s15", "golden"], cwd=elsewhere, env=env)
            matrix.append({"hash_seed": env["PYTHONHASHSEED"], "flags": flags, "identical_cases": done.stdout.count("identical"), "exit_code": done.returncode})
        cross = {}
        for name in cases:
            produced = []
            for env, flags in MATRIX[:2]:
                target = Path(elsewhere) / f"{name}-{env['PYTHONHASHSEED']}.json"
                sub([sys.executable, *flags, "-m", "s15", "run", "--policy", str(FIX / "policy.json"), "--contracts", str(FIX / "contracts"), "--bundles", str(FIX / "bundles"),
                     "--observation", str(FIX / "cases" / name / "observation.json"), "--vector", str(FIX / "cases" / name / "vector.json"), "--out", str(target)], cwd=elsewhere, env=env)
                produced.append(target.read_bytes() if target.exists() else b"")
            cross[name] = produced[0] == produced[1] == stored[name]
    checks["process_matrix"] = matrix
    checks["process_matrix_all_identical"] = all(m["exit_code"] == 0 and m["identical_cases"] == len(cases) for m in matrix)
    checks["cross_process_run_identical"] = all(cross.values())

    passed = (checks["schemas_match_generator"] and checks["fixtures_match_builder"] and checks["test_suite"]["passed"] and checks["in_process_matches_golden"]
              and checks["process_matrix_all_identical"] and checks["cross_process_run_identical"])
    report = {
        "schema": "S15_C0_GATE_REPORT_V1", "gate": "byte-identical decision and receipt for the same inputs and contracts", "verdict": "PASS" if passed else "FAIL",
        "runtime": {"name": runtime.RUNTIME_NAME, "version": runtime.RUNTIME_VERSION},
        "results": {
            "checks": checks, "cases": cases,
            "golden_manifest_sha256": sha((FIX / "GOLDEN.sha256").read_bytes()),
            "schema_sha256": {p.name: sha(p.read_bytes()) for p in sorted((ROOT / "schemas").glob("*.json"))},
            "policy_id": world.policy["policy_id"], "contract_ids": sorted(world.contracts), "bundle_ids": sorted(world.bundles),
        },
        "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(), "platform": platform.platform(), "informational": True},
    }
    data = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(data, encoding="ascii", newline="\n")
    print(data)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
