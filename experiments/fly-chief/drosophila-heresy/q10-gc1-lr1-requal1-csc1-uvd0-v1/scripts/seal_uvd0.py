from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
SINGLES = REPO / "experiments/drosophila-heresy/q10-gc1-lr1-requal1-sreplace-singles-v1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest().upper()


def write_new(path: Path, value: object) -> None:
    if path.exists():
        raise RuntimeError(f"existing sealed output: {path}")
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> int:
    if os.environ.get("PYTHONDONTWRITEBYTECODE") != "1":
        raise RuntimeError("PYTHONDONTWRITEBYTECODE must be 1")
    for name in ("CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json"):
        if (ROOT / name).exists():
            raise RuntimeError(f"existing output: {name}")
    runner = ROOT / "scripts/run_uvd0.py"
    if not runner.is_file():
        raise RuntimeError("runner missing")
    ast.parse(runner.read_text(encoding="utf-8"), filename=str(runner))
    bindings: list[dict[str, object]] = []
    paths = [
        ("singleton_execution", SINGLES / "execution.json"),
        ("singleton_contract", SINGLES / "CONTRACT.json"),
        ("singleton_root_manifest", SINGLES / "ROOT_MANIFEST.json"),
        ("uvd0_plan", ROOT / "PLAN.md"),
        ("uvd0_runner", runner),
    ]
    execution = json.loads((SINGLES / "execution.json").read_text(encoding="utf-8"))
    for slug in sorted(execution["shard_hashes"]):
        paths.append((f"singleton_shard:{slug}", SINGLES / "shards" / f"{slug}.jsonl"))
    for label, path in paths:
        if not path.is_file():
            raise RuntimeError(f"missing input: {path}")
        bindings.append({"label": label, "path": path.relative_to(REPO).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    contract = {
        "protocol": "Q10-CSC1-UVD0",
        "identity": ROOT.name,
        "status": "SEALED_PREMEASUREMENT",
        "parent_bindings": bindings,
        "contexts": sorted(execution["shard_hashes"]),
        "singleton_count": 3696,
        "write_allowlist": ["CONTRACT.json", "PREEXECUTION.json", "execution.json", "STATUS.json", "shards/*.jsonl"],
        "pair_selection": "all nonzero singleton actions from different groups with disjoint changed-coordinate sets",
        "pair_outcomes_consulted": False,
        "pair_replay_performed": False,
        "scientific_promotion": False,
    }
    write_new(ROOT / "CONTRACT.json", contract)
    write_new(ROOT / "PREEXECUTION.json", {
        "protocol": "Q10-CSC1-UVD0",
        "identity": ROOT.name,
        "status": "PREEXECUTION_SEALED",
        "contract_sha256": sha(ROOT / "CONTRACT.json"),
        "bound_inputs": len(bindings),
        "pair_outcomes_consulted": False,
        "pair_replay_performed": False,
    })
    print(json.dumps({"status": "SEALED_PREMEASUREMENT", "bound_inputs": len(bindings)}))


if __name__ == "__main__":
    raise SystemExit(main())
