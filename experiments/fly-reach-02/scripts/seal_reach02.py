from __future__ import annotations

import hashlib
import json
import pathlib
import shutil
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
TARGET = pathlib.Path(r"D:\fly-reach-02-target")
EXE = ROOT / "sealed/fly-reach-02.exe"


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
    shutil.copy2(TARGET / "release/fly-reach-02-executor.exe", EXE)
    paths = [
        ROOT / "manifests/REACH02-MANIFEST.json",
        ROOT / "source/DH08A-LINEAGE.md", ROOT / "source/persistent-state-schema.json",
        *sorted((ROOT / "inputs/anatomy").glob("*.tsv")),
        *sorted((ROOT / "inputs/null-graphs").glob("g*/edges-*.tsv")),
        *sorted((ROOT / "inputs/banks").glob("*.json")),
        *sorted((ROOT / "executor/src").glob("*.rs")), ROOT / "executor/Cargo.toml", ROOT / "executor/Cargo.lock",
    ]
    entries = [{"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths]
    contract = {
        "schema": "FLY-REACH-02-contract-v1", "study_id": "FLY-REACH-02", "status": "SEALED_ENGINEERING_ONLY",
        "purpose": "eligibility sign origin, cancellation, and stable inversion counterfactual",
        "qualification_blocks": [72000, 72001, 72002, 72003], "measured_blocks": list(range(82000, 82012)),
        "pretraining_trials": 8192, "threshold": 0.25, "reference_lr": 0.05, "oracle_lr": 0.5, "oracle_steps": 128,
        "stable_inversion_rule": {"min_observations": 128, "max_sign_agreement": 0.20, "mask_per_substrate_side": True},
        "arms": ["native", "sign_ref_native_mag", "stable_inversion_flip", "reference_direction_native_support", "weight_oracle"],
        "checkpoints": [0, 512, 1024, 2048, 4096, 8192],
        "diagnostics": ["local_contributions", "local_cancellation", "local_sign_agreement", "aggregate_sign_stability", "eligibility_cosine", "delivery_clip"],
        "input_hashes": entries, "executable": "sealed/fly-reach-02.exe", "executable_sha256": sha(EXE),
        "no_lesions": True, "no_biological_promotion": True, "no_pheno_reseal": True, "engineering_only": True,
    }
    contract_path = ROOT / "manifests/REACH02-CONTRACT.json"
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (ROOT / "manifests/REACH02-CONTRACT.sha256").write_text(f"{sha(contract_path)}  {contract_path.name}\n", encoding="utf-8")
    print(json.dumps({"contract_sha256": sha(contract_path), "executable_sha256": sha(EXE)}, sort_keys=True))


if __name__ == "__main__": main()
