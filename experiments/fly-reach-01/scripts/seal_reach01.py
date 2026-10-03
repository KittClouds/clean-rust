from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = pathlib.Path(r"D:\fly-reach-01-target")
EXE = ROOT / "sealed/fly-reach-01.exe"
MANIFEST = ROOT / "manifests/REACH01-MANIFEST.json"
CONTRACT = ROOT / "manifests/REACH01-CONTRACT.json"


def sha(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    executor = ROOT / "executor"
    subprocess.run(["cargo", "test", "--release", "--target-dir", str(TARGET)], cwd=executor, check=True)
    subprocess.run(["cargo", "build", "--release", "--target-dir", str(TARGET)], cwd=executor, check=True)
    EXE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET / "release/fly-reach-01-executor.exe", EXE)
    paths = [
        MANIFEST,
        ROOT / "source/DH08A-LINEAGE.md",
        ROOT / "source/persistent-state-schema.json",
        ROOT / "inputs/banks/training.json",
        ROOT / "inputs/banks/competence.json",
        ROOT / "inputs/banks/evaluator-large.json",
        *sorted((ROOT / "inputs/anatomy").glob("*.tsv")),
        *sorted((ROOT / "inputs/null-graphs").glob("g*/edges-*.tsv")),
        *sorted((ROOT / "executor/src").glob("*.rs")),
        ROOT / "executor/Cargo.toml",
        ROOT / "executor/Cargo.lock",
    ]
    entries = [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths]
    contract = {
        "schema": "FLY-REACH-01-contract-v1",
        "study_id": "FLY-REACH-01",
        "status": "SEALED_ENGINEERING_ONLY",
        "purpose": "direction failure anatomy for native adaptive authority",
        "primary_task": "four_cue",
        "horizon": 8192,
        "threshold": 0.25,
        "reference_lr": 0.05,
        "oracle_lr": 0.5,
        "oracle_steps": 128,
        "arms": ["native", "sign_ref_native_mag", "mag_ref_native_sign", "reference_direction_native_support", "reference_direction_full_support", "weight_oracle"],
        "checkpoints": [0, 512, 1024, 2048, 4096, 8192],
        "diagnostics": ["eligibility", "modulation", "aggregation", "delivered", "cosine", "support_fraction", "reference_mass_on_native_support", "sign_agreement", "magnitude_pearson", "stage_trajectory"],
        "input_hashes": entries,
        "executable": "sealed/fly-reach-01.exe",
        "executable_sha256": sha(EXE),
        "no_lesions": True,
        "no_biological_promotion": True,
        "no_pheno_reseal": True,
        "engineering_only": True,
    }
    CONTRACT.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "manifests/REACH01-CONTRACT.sha256").write_text(f"{sha(CONTRACT)}  {CONTRACT.name}\n", encoding="utf-8")
    print(json.dumps({"contract_sha256": sha(CONTRACT), "executable_sha256": sha(EXE)}, sort_keys=True))


if __name__ == "__main__":
    main()
