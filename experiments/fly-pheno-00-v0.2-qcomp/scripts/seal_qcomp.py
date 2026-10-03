"""Create the QCOMP executable and input contract after preparation."""
from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "manifests" / "QCOMP-MANIFEST.json"
CONTRACT = ROOT / "manifests" / "QCOMP-CONTRACT.json"
TARGET = pathlib.Path(r"D:\fly-pheno-00-v0.2-qcomp-target")
EXE = ROOT / "sealed" / "fly-pheno-00-v0.2-qcomp.exe"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main() -> None:
    subprocess.run(["cargo", "test", "--release", "--target-dir", str(TARGET)], cwd=ROOT / "executor", check=True)
    subprocess.run(["cargo", "build", "--release", "--target-dir", str(TARGET)], cwd=ROOT / "executor", check=True)
    EXE.parent.mkdir(parents=True, exist_ok=True)
    built = TARGET / "release" / "fly-pheno-00-v0-2-qcomp-executor.exe"
    EXE.write_bytes(built.read_bytes())
    paths = [MANIFEST, ROOT / "inputs/banks/training.json", ROOT / "inputs/banks/competence.json"]
    paths += sorted(ROOT.glob("inputs/anatomy/*.tsv"))
    paths += sorted(ROOT.glob("inputs/null-graphs/g*/edges-*.tsv"))
    paths += sorted((ROOT / "executor/src").glob("*.rs"))
    paths += [ROOT / "executor/Cargo.toml", ROOT / "executor/Cargo.lock"]
    entries = [{"path": str(p.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(p), "bytes": p.stat().st_size} for p in paths]
    contract = {
        "schema": "FLY-PHENO-00-v0.2-QCOMP-contract-v1",
        "study_id": "FLY-PHENO-00-v0.2-QCOMP",
        "status": "SEALED_QUALIFICATION_ONLY",
        "purpose": "establish a common competence frontier before any PHENO measured run",
        "horizons": [512, 1024, 2048, 4096, 8192],
        "threshold": 0.25,
        "competence_rate_requirement": 0.80,
        "substrates": ["fly", *[f"g{i:03d}" for i in range(1, 9)]],
        "sides": ["L", "R"],
        "learner_task_blocks": list(range(22000, 22012)),
        "graph_seeds": list(range(23000, 23008)),
        "response_seed": 26000,
        "input_hashes": entries,
        "executable": "sealed/fly-pheno-00-v0.2-qcomp.exe",
        "executable_sha256": sha(EXE),
        "no_lesions": True,
        "no_recovery_comparison": True,
        "no_measured_execution": True,
        "no_seed_replacement": True,
        "qualification_namespace": "FLY-PHENO-00-v0.2-QCOMP",
    }
    CONTRACT.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    CONTRACT.with_suffix(".sha256").write_text(f"{sha(CONTRACT)}  {CONTRACT.name}\n", encoding="utf-8")
    print(json.dumps({"contract": str(CONTRACT), "contract_sha256": sha(CONTRACT), "executable_sha256": sha(EXE)}, sort_keys=True))


if __name__ == "__main__":
    main()
